"""
LLM Gateway API endpoints for chat completions and embeddings.
"""
import hashlib
import json
from typing import Dict, Any, List, Optional, Union
from fastapi import APIRouter, Request, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
import structlog

from app.core.config import settings
from app.core.security import get_api_key, redact_sensitive_data
from app.core.ratelimit import check_rpm
from app.core.usage import check_daily_quota
from app.db.session import get_db_dependency
from app.db.models import APIKey, IdempotencyRecord
from app.api.models import resolve_model_for_request
from app.services.openrouter import (
    proxy_chat_completion, 
    stream_and_meter_usage, 
    proxy_embeddings,
    get_proxy_headers,
    OpenRouterError
)
import httpx

router = APIRouter()
logger = structlog.get_logger(__name__)


# Request/Response Models
class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the message sender")
    content: Union[str, List[Dict[str, Any]]] = Field(..., description="Message content")
    name: Optional[str] = Field(None, description="Name of the sender")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID")


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(None, description="Model to use")
    messages: List[ChatMessage] = Field(..., description="List of messages")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Sampling temperature")
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Nucleus sampling parameter")
    max_tokens: Optional[int] = Field(None, ge=1, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Whether to stream the response")
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="Available tools")
    tool_choice: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Tool choice")
    response_format: Optional[Dict[str, str]] = Field(None, description="Response format")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    
    @validator('temperature')
    def validate_temperature(cls, v):
        if v is not None and v > settings.MAX_TEMPERATURE:
            raise ValueError(f"Temperature cannot exceed {settings.MAX_TEMPERATURE}")
        return v
    
    @validator('max_tokens')
    def validate_max_tokens(cls, v):
        if v is not None and v > settings.MAX_OUTPUT_TOKENS:
            raise ValueError(f"max_tokens cannot exceed {settings.MAX_OUTPUT_TOKENS}")
        return v


class EmbeddingsRequest(BaseModel):
    model: Optional[str] = Field(None, description="Model to use for embeddings")
    input: Union[str, List[str]] = Field(..., description="Input text(s) to embed")
    encoding_format: Optional[str] = Field("float", description="Encoding format")
    dimensions: Optional[int] = Field(None, description="Number of dimensions")


def generate_request_hash(request_body: Dict[str, Any]) -> str:
    """Generate a hash of the request body for idempotency."""
    # Remove metadata and other non-deterministic fields
    hashable_body = {k: v for k, v in request_body.items() 
                    if k not in ['metadata', 'stream']}
    
    request_str = json.dumps(hashable_body, sort_keys=True)
    return hashlib.sha256(request_str.encode()).hexdigest()


async def check_idempotency(
    idempotency_key: str,
    api_key: APIKey,
    request_body: Dict[str, Any],
    db
) -> Optional[Dict[str, Any]]:
    """
    Check for existing idempotent response.
    
    Returns:
        dict: Cached response if found, None otherwise
    """
    request_hash = generate_request_hash(request_body)
    
    # Look up existing response
    existing = await db.get(IdempotencyRecord, idempotency_key)
    
    if existing:
        # Verify the request hash matches
        if existing.request_hash == request_hash and existing.api_key_hash == api_key.key_hash:
            logger.info(
                "idempotency_cache_hit",
                idempotency_key=idempotency_key,
                workspace_id=api_key.workspace_id,
            )
            return existing.response
        else:
            # Different request with same idempotency key
            logger.warning(
                "idempotency_key_conflict",
                idempotency_key=idempotency_key,
                workspace_id=api_key.workspace_id,
            )
            raise HTTPException(
                status_code=409,
                detail="Idempotency key conflict: same key used for different request"
            )
    
    return None


async def store_idempotent_response(
    idempotency_key: str,
    api_key: APIKey,
    request_body: Dict[str, Any],
    response_data: Dict[str, Any],
    db
) -> None:
    """Store response for idempotency."""
    request_hash = generate_request_hash(request_body)
    
    idempotency_record = IdempotencyRecord(
        id=idempotency_key,
        api_key_hash=api_key.key_hash,
        request_hash=request_hash,
        response=response_data
    )
    
    db.add(idempotency_record)
    await db.commit()
    
    logger.debug(
        "idempotency_response_stored",
        idempotency_key=idempotency_key,
        workspace_id=api_key.workspace_id,
    )


@router.post("/llm/chat")
async def chat_completions(
    request: Request,
    chat_request: ChatCompletionRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency)
):
    """
    Proxy chat completion requests to OpenRouter with full business logic.
    
    Supports both streaming and non-streaming responses.
    Enforces rate limits, quotas, model permissions, and idempotency.
    """
    # Rate limiting and quota checks
    await check_rpm(api_key)
    await check_daily_quota(api_key)
    
    # Convert request to dict for processing
    request_body = chat_request.dict(exclude_none=True)
    
    # Resolve model
    resolved_model, error = await resolve_model_for_request(
        requested_model=request_body.get("model"),
        api_key=api_key,
        purpose="chat",
        db=db
    )
    
    if error:
        logger.warning(
            "model_resolution_failed",
            workspace_id=api_key.workspace_id,
            requested_model=request_body.get("model"),
            error=error
        )
        raise HTTPException(status_code=400, detail=error)
    
    request_body["model"] = resolved_model
    
    model_id = resolved_model or settings.OPENROUTER_DEFAULT_MODEL or "unknown"
    
    # Handle idempotency for non-streaming requests
    idempotency_key = request.headers.get("idempotency-key")
    if idempotency_key and not request_body.get("stream", False):
        cached_response = await check_idempotency(idempotency_key, api_key, request_body, db)
        if cached_response:
            return cached_response
    
    # Log request (with sensitive data redacted)
    if settings.DEBUG_LOG_PROMPTS:
        logger.info("chat_request_received", request_body=request_body)
    else:
        logger.info("chat_request_received", request_body=redact_sensitive_data(request_body))
    
    try:
        if request_body.get("stream", False):
            # Streaming response
            async with httpx.AsyncClient() as client:
                or_request = client.build_request(
                    method="POST",
                    url=f"{settings.OPENROUTER_BASE}/v1/chat/completions",
                    json=request_body,
                    headers=get_proxy_headers(request),
                    timeout=300.0,
                )
                
                return StreamingResponse(
                    stream_and_meter_usage(or_request, api_key, model_id),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Model-Used": model_id,
                    }
                )
        else:
            # Non-streaming response
            response_data = await proxy_chat_completion(request, api_key, request_body)
            
            # Store idempotent response if key provided
            if idempotency_key:
                await store_idempotent_response(
                    idempotency_key, api_key, request_body, response_data, db
                )
            
            # Add custom headers
            headers = {
                "X-Model-Used": model_id,
            }
            
            return Response(
                content=json.dumps(response_data),
                media_type="application/json",
                headers=headers
            )
            
    except OpenRouterError as e:
        logger.error(
            "openrouter_proxy_error",
            workspace_id=api_key.workspace_id,
            model=model_id,
            status_code=e.status_code,
            message=e.message,
            details=e.details
        )
        
        # Map OpenRouter errors to appropriate HTTP status codes
        if e.status_code == 401:
            raise HTTPException(status_code=502, detail="Authentication failed with upstream provider")
        elif e.status_code == 429:
            raise HTTPException(status_code=429, detail="Rate limited by upstream provider")
        elif e.status_code >= 500:
            raise HTTPException(status_code=502, detail="Upstream provider error")
        else:
            raise HTTPException(status_code=e.status_code, detail=e.message)
    
    except Exception as e:
        logger.error(
            "chat_completion_error",
            workspace_id=api_key.workspace_id,
            model=model_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/embeddings")
async def embeddings(
    request: Request,
    embeddings_request: EmbeddingsRequest,
    api_key: APIKey = Depends(get_api_key),
    db = Depends(get_db_dependency)
):
    """
    Proxy embeddings requests to OpenRouter or local SBERT.
    
    Enforces rate limits, quotas, and model permissions.
    """
    # Rate limiting and quota checks
    await check_rpm(api_key)
    await check_daily_quota(api_key)
    
    # Convert request to dict
    request_body = embeddings_request.dict(exclude_none=True)
    
    # Resolve model
    resolved_model, error = await resolve_model_for_request(
        requested_model=request_body.get("model"),
        api_key=api_key,
        purpose="embeddings",
        db=db
    )
    
    if error:
        logger.warning(
            "embedding_model_resolution_failed",
            workspace_id=api_key.workspace_id,
            requested_model=request_body.get("model"),
            error=error
        )
        raise HTTPException(status_code=400, detail=error)
    
    request_body["model"] = resolved_model
    
    model_id = resolved_model or settings.OPENROUTER_DEFAULT_MODEL or "unknown"
    
    # Log request
    logger.info(
        "embeddings_request_received",
        workspace_id=api_key.workspace_id,
        model=model_id,
        input_type=type(request_body.get("input")).__name__,
        input_length=len(request_body.get("input", [])) if isinstance(request_body.get("input"), list) else 1
    )
    try:
        if settings.EMBEDDINGS_PROVIDER == "openrouter":
            # Proxy to OpenRouter
            response_data = await proxy_embeddings(request, api_key, request_body)
            
            return Response(
                content=json.dumps(response_data),
                media_type="application/json",
                headers={"X-Model-Used": model_id}
            )
        else:
            # Use local SBERT (would be implemented here)
            raise HTTPException(
                status_code=501,
                detail="Local SBERT embeddings not yet implemented"
            )
            
    except OpenRouterError as e:
        logger.error(
            "embeddings_proxy_error",
            workspace_id=api_key.workspace_id,
            model=model_id,
            status_code=e.status_code,
            message=e.message
        )
        
        if e.status_code == 401:
            raise HTTPException(status_code=502, detail="Authentication failed with upstream provider")
        elif e.status_code == 429:
            raise HTTPException(status_code=429, detail="Rate limited by upstream provider")
        elif e.status_code >= 500:
            raise HTTPException(status_code=502, detail="Upstream provider error")
        else:
            raise HTTPException(status_code=e.status_code, detail=e.message)
    
    except Exception as e:
        logger.error(
            "embeddings_error",
            workspace_id=api_key.workspace_id,
            model=model_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Internal server error")

