"""
OpenRouter service for proxying requests to OpenRouter API.
"""
import json
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional, List
from fastapi import Request
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from app.core.config import settings
from app.core.usage import record_usage
from app.db.models import APIKey
from app.core.circuit_breaker import (
    get_circuit_breaker, CircuitBreakerConfig, CircuitBreakerError
)
from app.core.exceptions import OpenRouterError as CustomOpenRouterError

logger = structlog.get_logger(__name__)

# Circuit breaker configuration for OpenRouter
OPENROUTER_CIRCUIT_BREAKER_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,        # Open after 5 consecutive failures
    recovery_timeout=60.0,      # Wait 60 seconds before attempting recovery
    success_threshold=3,        # Need 3 successes to close from half-open
    timeout=30.0,              # 30 second timeout for requests
    expected_exception=httpx.HTTPStatusError
)

# Get circuit breaker instance
openrouter_circuit_breaker = get_circuit_breaker(
    "openrouter_api", 
    OPENROUTER_CIRCUIT_BREAKER_CONFIG
)


class OpenRouterError(Exception):
    """Custom exception for OpenRouter API errors."""
    def __init__(self, status_code: int, message: str, details: Optional[Dict] = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"OpenRouter API error {status_code}: {message}")


def get_proxy_headers(request: Request) -> Dict[str, str]:
    """
    Get headers for proxying requests to OpenRouter.

    Args:
        request: Original FastAPI request

    Returns:
        dict: Headers to send to OpenRouter
    """
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": request.headers.get("referer", "https://context-memory-gateway.local/"),
        "X-Title": "Context Memory Gateway",
        "User-Agent": request.headers.get("user-agent", "Context-Memory-Gateway/1.0.0"),
    }

    # Forward some client headers if present
    forward_headers = ["x-forwarded-for", "x-real-ip", "cf-connecting-ip"]
    for header in forward_headers:
        if header in request.headers:
            headers[header] = request.headers[header]

    return headers


async def make_openrouter_request(
    method: str,
    endpoint: str,
    headers: Dict[str, str],
    json_data: Optional[Dict[str, Any]] = None,
    timeout: float = 300.0
) -> httpx.Response:
    """
    Make a request to OpenRouter API with circuit breaker and retry logic.

    Args:
        method: HTTP method
        endpoint: API endpoint path
        headers: Request headers
        json_data: JSON payload
        timeout: Request timeout in seconds

    Returns:
        httpx.Response: Response from OpenRouter

    Raises:
        CircuitBreakerError: If circuit breaker is open
        CustomOpenRouterError: If request fails after retries
    """
    async def _make_request() -> httpx.Response:
        """Internal function to make the actual request."""
        url = f"{settings.OPENROUTER_API_BASE}{endpoint}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=timeout
                )

                if response.status_code >= 400:
                    error_details = {}
                    try:
                        error_details = response.json()
                    except:
                        error_details = {"raw_response": response.text}

                    logger.error(
                        "openrouter_request_failed",
                        status_code=response.status_code,
                        url=url,
                        error_details=error_details
                    )

                    # Raise HTTP status error to trigger circuit breaker
                    response.raise_for_status()

                return response

            except httpx.TimeoutException as e:
                logger.warning("openrouter_request_timeout", url=url, timeout=timeout)
                raise
            except httpx.ConnectError as e:
                logger.exception("openrouter_connection_error", url=url)
                raise
            except Exception as e:
                logger.exception("openrouter_request_error", url=url)
                raise
    
    try:
        # Use circuit breaker to protect the request
        return await openrouter_circuit_breaker.call(_make_request)
    
    except CircuitBreakerError as e:
        logger.warning(
            "openrouter_circuit_breaker_open",
            retry_after=e.retry_after,
            endpoint=endpoint
        )
        # Convert to our custom exception
        raise CustomOpenRouterError(
            message=f"OpenRouter service temporarily unavailable: {e.message}",
            status_code=503,
            response_data={"retry_after": e.retry_after}
        )
    
    except httpx.HTTPStatusError as e:
        # Convert HTTP errors to our custom exception
        error_details = {}
        try:
            error_details = e.response.json()
        except:
            error_details = {"raw_response": e.response.text}
        
        raise CustomOpenRouterError(
            message=error_details.get("error", {}).get("message", "Unknown error"),
            status_code=e.response.status_code,
            response_data=error_details
        )


async def fetch_all_models() -> List[Dict[str, Any]]:
    """
    Fetch all available models from OpenRouter.

    Returns:
        list: List of model dictionaries

    Raises:
        OpenRouterError: If request fails
    """
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    response = await make_openrouter_request(
        method="GET",
        endpoint="/v1/models",
        headers=headers,
        timeout=30.0
    )

    data = response.json()
    models = data.get("data", [])

    logger.info("openrouter_models_fetched", count=len(models))
    return models


async def stream_and_meter_usage(
    request: httpx.Request,
    api_key: APIKey,
    model_id: str
) -> AsyncGenerator[str, None]:
    """
    Stream response from OpenRouter and meter usage asynchronously.

    Args:
        request: Prepared httpx request
        api_key: API key record for usage tracking
        model_id: Model being used

    Yields:
        str: Server-sent event chunks
    """
    usage_data = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", request.url, headers=request.headers, content=request.content) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    logger.error(
                        "openrouter_stream_error",
                        status_code=response.status_code,
                        error=error_text.decode()
                    )
                    yield f"data: {json.dumps({'error': 'OpenRouter API error'})}\n\n"
                    return

                async for chunk in response.aiter_text():
                    if chunk.strip():
                        # Parse SSE chunk to extract usage data
                        if chunk.startswith("data: "):
                            data_part = chunk[6:].strip()
                            if data_part and data_part != "[DONE]":
                                try:
                                    chunk_data = json.loads(data_part)

                                    # Extract usage information if present
                                    if "usage" in chunk_data:
                                        usage_info = chunk_data["usage"]
                                        usage_data.update({
                                            "prompt_tokens": usage_info.get("prompt_tokens", 0),
                                            "completion_tokens": usage_info.get("completion_tokens", 0),
                                            "total_tokens": usage_info.get("total_tokens", 0),
                                        })
                                except json.JSONDecodeError:
                                    pass  # Ignore malformed JSON chunks

                        yield chunk

                # Record usage after streaming completes
                if usage_data["total_tokens"] > 0:
                    asyncio.create_task(record_usage(
                        api_key=api_key,
                        model_id=model_id,
                        prompt_tokens=usage_data["prompt_tokens"],
                        completion_tokens=usage_data["completion_tokens"]
                    ))

                    logger.info(
                        "streaming_usage_recorded",
                        workspace_id=api_key.workspace_id,
                        model=model_id,
                        **usage_data
                    )

        except Exception as e:
            logger.exception(
                "openrouter_streaming_error",
                workspace_id=api_key.workspace_id,
                model=model_id
            )
            yield f"data: {json.dumps({'error': 'Streaming error occurred'})}\n\n"


async def proxy_chat_completion(
    request: Request,
    api_key: APIKey,
    request_body: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Proxy a non-streaming chat completion request to OpenRouter.

    Args:
        request: Original FastAPI request
        api_key: API key record
        request_body: Request payload

    Returns:
        dict: Response from OpenRouter

    Raises:
        OpenRouterError: If request fails
    """
    headers = get_proxy_headers(request)

    response = await make_openrouter_request(
        method="POST",
        endpoint="/v1/chat/completions",
        headers=headers,
        json_data=request_body,
        timeout=300.0
    )

    response_data = response.json()

    req_model = request_body.get("model")
    model_id: str = (
        str(req_model) if req_model is not None
        else api_key.default_model
        or settings.OPENROUTER_DEFAULT_MODEL
        or "unknown"
    )

    # Record usage
    if "usage" in response_data:
        usage_info = response_data["usage"]
        await record_usage(
            api_key=api_key,
            model_id=model_id,
            prompt_tokens=usage_info.get("prompt_tokens", 0),
            completion_tokens=usage_info.get("completion_tokens", 0)
        )

        logger.info(
            "chat_completion_usage_recorded",
            workspace_id=api_key.workspace_id,
            model=model_id,
            prompt_tokens=usage_info.get("prompt_tokens", 0),
            completion_tokens=usage_info.get("completion_tokens", 0),
            total_tokens=usage_info.get("total_tokens", 0),
        )

    return response_data


async def proxy_embeddings(
    request: Request,
    api_key: APIKey,
    request_body: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Proxy an embeddings request to OpenRouter.

    Args:
        request: Original FastAPI request
        api_key: API key record
        request_body: Request payload

    Returns:
        dict: Response from OpenRouter

    Raises:
        OpenRouterError: If request fails
    """
    headers = get_proxy_headers(request)

    response = await make_openrouter_request(
        method="POST",
        endpoint="/v1/embeddings",
        headers=headers,
        json_data=request_body,
        timeout=60.0
    )

    response_data = response.json()

    req_model = request_body.get("model")
    model_id: str = (
        str(req_model) if req_model is not None
        else api_key.default_model
        or settings.OPENROUTER_DEFAULT_MODEL
        or "unknown"
    )

    # Record usage for embeddings
    if "usage" in response_data:
        usage_info = response_data["usage"]
        await record_usage(
            api_key=api_key,
            model_id=model_id,
            embedding_tokens=usage_info.get("total_tokens", 0)
        )

        logger.info(
            "embeddings_usage_recorded",
            workspace_id=api_key.workspace_id,
            model=model_id,
            tokens=usage_info.get("total_tokens", 0),
        )

    return response_data




class OpenRouterService:
    """Compatibility service wrapper used by workers and tests.
    Provides a class interface around module-level functions.
    """

    async def fetch_all_models(self) -> List[Dict[str, Any]]:
        return await fetch_all_models()

    async def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        # Fallback approach: fetch all and filter; OpenRouter may not have per-id endpoint
        try:
            models = await fetch_all_models()
            for m in models:
                if m.get("id") == model_id:
                    return m
        except Exception:
            pass
        return None

    async def chat_completion(self, request: Request, api_key: APIKey, request_body: Dict[str, Any]) -> Dict[str, Any]:
        return await proxy_chat_completion(request, api_key, request_body)

    async def chat_completion_stream(self, prepared_request: httpx.Request, api_key: APIKey, model_id: str):
        # Return an async generator for streaming
        return stream_and_meter_usage(prepared_request, api_key, model_id)
