"""
Middleware for standardizing API responses and handling cross-cutting concerns.
"""
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import json
import structlog
from app.core.responses import APIResponseBuilder, StandardResponse, ResponseMeta, ErrorDetail
from datetime import datetime

logger = structlog.get_logger(__name__)


class ResponseStandardizationMiddleware(BaseHTTPMiddleware):
    """Middleware to standardize API response formats."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and standardize response format for API endpoints."""
        
        # Only apply to API endpoints, skip admin and static files
        if not request.url.path.startswith('/api/'):
            return await call_next(request)
        
        response = await call_next(request)
        
        # Only process JSON responses
        if not isinstance(response, JSONResponse):
            return response
        
        # Check if response is already in standard format
        try:
            content = json.loads(response.body)
            
            # If already has 'success' field, assume it's standardized
            if isinstance(content, dict) and 'success' in content:
                # Ensure meta field is present and complete
                if 'meta' not in content or not isinstance(content['meta'], dict):
                    content['meta'] = self._create_meta(request)
                else:
                    # Fill in missing meta fields
                    meta = content['meta']
                    if 'timestamp' not in meta:
                        meta['timestamp'] = datetime.utcnow().isoformat() + "Z"
                    if 'request_id' not in meta:
                        meta['request_id'] = getattr(request.state, 'correlation_id', 'unknown')
                    if 'version' not in meta:
                        meta['version'] = getattr(request.state, 'api_version', 'v1')
                
                # Update response content
                response.body = json.dumps(content).encode('utf-8')
                return response
            
            # Wrap non-standard responses
            standardized = self._wrap_response(request, content, response.status_code)
            response.body = json.dumps(standardized).encode('utf-8')
            
        except Exception as e:
            logger.exception("response_standardization_error", error=str(e))
            # If we can't parse/standardize, return original response
            pass
        
        return response
    
    def _create_meta(self, request: Request) -> dict:
        """Create meta object for response."""
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "request_id": getattr(request.state, 'correlation_id', 'unknown'),
            "version": getattr(request.state, 'api_version', 'v1')
        }
    
    def _wrap_response(self, request: Request, content: any, status_code: int) -> dict:
        """Wrap response in standard envelope."""
        
        # Determine if this is an error response
        is_error = status_code >= 400
        
        if is_error:
            # Handle error responses
            error_message = "An error occurred"
            error_code = "SYSTEM_ERROR"
            
            if isinstance(content, dict):
                error_message = content.get('detail') or content.get('message') or error_message
                error_code = content.get('code', error_code)
            elif isinstance(content, str):
                error_message = content
            
            return {
                "success": False,
                "data": None,
                "error": {
                    "code": error_code,
                    "message": error_message,
                    "details": content if isinstance(content, dict) else None
                },
                "meta": self._create_meta(request)
            }
        else:
            # Handle success responses
            return {
                "success": True,
                "data": content,
                "error": None,
                "meta": self._create_meta(request)
            }


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to responses."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response."""
        
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Add HSTS for HTTPS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Add CSP for admin pages
        if request.url.path.startswith('/admin/'):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; "
                "connect-src 'self'"
            )
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for detailed request/response logging."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response details."""
        
        # Skip logging for health checks and static files
        skip_paths = ['/health', '/metrics', '/favicon.ico']
        if any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)
        
        import time
        start_time = time.time()
        
        # Get client info
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Log request start
        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query_params=str(request.query_params),
            client_ip=client_ip,
            user_agent=user_agent,
            request_id=getattr(request.state, 'correlation_id', 'unknown')
        )
        
        try:
            response = await call_next(request)
            
            # Calculate response time
            response_time = time.time() - start_time
            
            # Log successful response
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                response_time_ms=round(response_time * 1000, 2),
                client_ip=client_ip,
                request_id=getattr(request.state, 'correlation_id', 'unknown')
            )
            
            return response
            
        except Exception as e:
            # Log error response
            response_time = time.time() - start_time
            
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                response_time_ms=round(response_time * 1000, 2),
                client_ip=client_ip,
                request_id=getattr(request.state, 'correlation_id', 'unknown')
            )
            
            raise


class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """Middleware to handle circuit breaker responses for external services."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle circuit breaker exceptions."""
        
        try:
            return await call_next(request)
        except Exception as e:
            # Check if this is a circuit breaker exception
            if "circuit breaker" in str(e).lower() or "CircuitBreakerError" in str(type(e).__name__):
                builder = APIResponseBuilder(request)
                return builder.error(
                    code="INTEGRATION_ERROR",
                    message="External service temporarily unavailable",
                    details={
                        "service": "openrouter",
                        "reason": "circuit_breaker_open",
                        "retry_after": 60
                    },
                    status_code=503
                )
            
            # Re-raise other exceptions
            raise
