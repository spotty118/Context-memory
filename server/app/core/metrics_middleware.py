"""
Metrics collection middleware for automatic monitoring of HTTP requests and application metrics.
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
import time
import structlog
from typing import Callable
from app.telemetry.metrics import metrics_collector
import asyncio

logger = structlog.get_logger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically collect metrics for all HTTP requests."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics."""
        # Skip metrics collection for the metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)
            
        # Record request start
        metrics_collector.record_request_start(request)
        
        # Track API key usage if present
        api_key = self._extract_api_key(request)
        if api_key:
            # Hash the API key for privacy (use first 8 chars of hash)
            import hashlib
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            endpoint = self._get_endpoint_name(request)
            metrics_collector.record_api_key_usage(api_key_hash, endpoint)
        
        start_time = time.time()
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Record successful request
            metrics_collector.record_request_end(request, response)
            
            return response
            
        except Exception as exc:
            # Create error response
            error_response = Response(
                content="Internal Server Error",
                status_code=500,
                media_type="text/plain"
            )
            
            # Record the error
            metrics_collector.record_request_end(request, error_response)
            metrics_collector.record_exception(type(exc).__name__)
            
            # Re-raise the exception to let other error handlers deal with it
            raise exc
    
    def _extract_api_key(self, request: Request) -> str:
        """Extract API key from request headers."""
        # Check X-API-Key header
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return api_key
            
        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
            
        return None
    
    def _get_endpoint_name(self, request: Request) -> str:
        """Extract a clean endpoint name from the request."""
        path = request.url.path
        
        # Normalize common patterns
        if path.startswith("/api/v1/"):
            return path.replace("/api/v1", "/v1")
        elif path.startswith("/api/v2/"):
            return path.replace("/api/v2", "/v2")
        elif path.startswith("/admin/"):
            return "/admin/*"
        elif path == "/":
            return "/root"
        elif path == "/health":
            return "/health"
        else:
            return path


class SystemMetricsCollector:
    """Background task to collect system metrics periodically."""
    
    def __init__(self, interval: int = 30):
        self.interval = interval
        self._task = None
        
    async def start(self):
        """Start the system metrics collection task."""
        if self._task is None:
            self._task = asyncio.create_task(self._collect_loop())
            logger.info("system_metrics_collector_started", interval=self.interval)
    
    async def stop(self):
        """Stop the system metrics collection task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("system_metrics_collector_stopped")
    
    async def _collect_loop(self):
        """Main collection loop."""
        while True:
            try:
                await asyncio.sleep(self.interval)
                metrics_collector.update_system_metrics()
                metrics_collector.update_circuit_breaker_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("system_metrics_collection_error", error=str(e))


# Global system metrics collector
system_metrics_collector = SystemMetricsCollector(interval=30)