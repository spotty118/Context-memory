"""
Main FastAPI application entry point for Context Memory + LLM Gateway.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from datetime import datetime
import uuid
import time

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import structlog
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings
from app.telemetry.logging import setup_logging
from app.telemetry.otel import setup_telemetry
from app.db.session import init_db
from app.api import llm_gateway, models, ingest, recall, workingset, expand, feedback, health, workers, cache, benchmarks
from app.api.v2 import enhanced_context
from app.admin.views import router as admin_router
from app.core.exceptions import ContextMemoryError
from app.core.audit import log_security_event, SecurityEventType, SecurityRisk
from app.core.versioning import (
    create_version_middleware, create_version_endpoints, APIVersion,
    version_registry, create_versioned_router
)


# Setup structured logging
setup_logging()
logger = structlog.get_logger(__name__)

# Setup Sentry if configured
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        integrations=[
            FastApiIntegration(auto_enabling=True),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        environment=settings.ENVIRONMENT,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown tasks."""
    # Startup
    logger.info("Starting Context Memory + LLM Gateway", environment=settings.ENVIRONMENT)
    
    # Initialize database
    await init_db()
    
    # Setup telemetry
    if settings.METRICS_ENABLED:
        setup_telemetry(app)
    
    # Warm cache with frequently accessed data
    try:
        from app.services.cache import ModelCacheService, SettingsCacheService
        logger.info("warming_cache_on_startup")
        await ModelCacheService.warm_cache(limit=50)  # Warm top 50 models
        await SettingsCacheService.warm_cache()
        logger.info("cache_warmed_successfully")
    except Exception as e:
        logger.exception("cache_warm_failed_on_startup")
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")


# Create FastAPI application
app = FastAPI(
    title="Context Memory + LLM Gateway",
    description="A cloud-hosted service providing LLM gateway functionality with context memory capabilities",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)
# Note: ProxyHeadersMiddleware was removed in newer Starlette versions
# Trust headers are now handled via uvicorn --forwarded-allow-ips or server config

# Security middleware
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # Configure with actual domains in production
    )

# CORS middleware
cors_origins = settings.CORS_ORIGINS if getattr(settings, "CORS_ORIGINS", []) else (["*"] if settings.is_development else [])
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Versioning Middleware
app.middleware("http")(create_version_middleware())


# Correlation ID middleware
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to requests for tracing across services."""
    # Check if correlation ID is already provided in headers
    correlation_id = request.headers.get("x-correlation-id")
    
    if not correlation_id:
        # Generate new correlation ID if not provided
        correlation_id = str(uuid.uuid4())
    
    # Store correlation ID in request state
    request.state.correlation_id = correlation_id
    request.state.request_id = correlation_id  # Also set as request_id for compatibility
    
    logger.debug(
        "correlation_id_assigned",
        correlation_id=correlation_id,
        path=request.url.path,
        method=request.method
    )
    
    response = await call_next(request)
    
    # Add correlation ID to response headers
    response.headers["x-correlation-id"] = correlation_id
    response.headers["x-request-id"] = correlation_id
    
    return response


# Request size limit middleware
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Middleware to limit request body size and prevent DoS attacks."""
    # Check Content-Length header
    content_length = request.headers.get("content-length")
    
    if content_length:
        try:
            content_length = int(content_length)
            
            # Check if request exceeds maximum size
            if content_length > settings.MAX_REQUEST_SIZE:
                logger.warning(
                    "request_size_exceeded",
                    content_length=content_length,
                    max_allowed=settings.MAX_REQUEST_SIZE,
                    path=request.url.path,
                    client_ip=request.client.host if request.client else None
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "Request entity too large",
                        "detail": f"Request body size ({content_length} bytes) exceeds maximum allowed ({settings.MAX_REQUEST_SIZE} bytes)",
                        "max_size_bytes": settings.MAX_REQUEST_SIZE
                    }
                )
        except ValueError:
            # Invalid Content-Length header
            logger.warning(
                "invalid_content_length",
                content_length_header=content_length,
                path=request.url.path,
                client_ip=request.client.host if request.client else None
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid Content-Length header"}
            )
    
    # Additional check for JSON payloads
    if request.headers.get("content-type", "").startswith("application/json") and content_length:
        if int(content_length) > settings.MAX_JSON_SIZE:
            logger.warning(
                "json_payload_too_large",
                content_length=content_length,
                max_json_size=settings.MAX_JSON_SIZE,
                path=request.url.path,
                client_ip=request.client.host if request.client else None
            )
            return JSONResponse(
                status_code=413,
                content={
                    "error": "JSON payload too large",
                    "detail": f"JSON payload size ({content_length} bytes) exceeds maximum allowed ({settings.MAX_JSON_SIZE} bytes)",
                    "max_json_size_bytes": settings.MAX_JSON_SIZE
                }
            )
    
    response = await call_next(request)
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with structured logging and correlation ID."""
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    
    start_time = time.time()
    logger.info(
        "request_started", 
        method=request.method,
        url=str(request.url),
        client_ip=request.client.host if request.client else None,
        correlation_id=correlation_id,
        user_agent=request.headers.get("user-agent", "unknown")
    )
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    
    # Don't log prompts unless explicitly enabled
    log_data = {
        "method": request.method,
        "url": str(request.url),
        "status_code": response.status_code,
        "client_ip": request.client.host if request.client else None,
        "correlation_id": correlation_id,
        "duration_seconds": round(duration, 4),
        "user_agent": request.headers.get("user-agent", "unknown")
    }
    
    if response.status_code >= 400:
        logger.error("request_completed", **log_data)
    else:
        logger.info("request_completed", **log_data)
    
    # Record metrics with correlation context
    from app.telemetry.otel import record_request_metrics
    record_request_metrics(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
        duration=duration
    )
    
    return response


# Custom exception handler for ContextMemoryError
@app.exception_handler(ContextMemoryError)
async def context_memory_exception_handler(request: Request, exc: ContextMemoryError):
    """Handle custom ContextMemoryError exceptions with standardized format."""
    
    # Extract correlation ID from request state
    correlation_id = getattr(request.state, "correlation_id", None)
    
    # Log security events for authentication/authorization errors
    if exc.status_code in [401, 403]:
        log_security_event(
            event_type=SecurityEventType.UNAUTHORIZED_ACCESS,
            risk_level=SecurityRisk.MEDIUM,
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
            method=request.method,
            success=False,
            error_message=exc.message,
            correlation_id=correlation_id
        )
    
    logger.warning(
        "context_memory_error",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        url=str(request.url),
        method=request.method,
        details=exc.details,
        correlation_id=correlation_id
    )
    
    # Return standardized error response
    response_data = {
        "error": exc.error_code,
        "message": exc.message,
        "timestamp": exc.timestamp.isoformat(),
        "path": request.url.path,
        "method": request.method
    }
    
    # Add details if present
    if exc.details:
        response_data["details"] = exc.details
    
    # Add request ID if available (will be implemented with correlation ID task)
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response_data["request_id"] = request_id
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data
    )


# HTTP exception handler for FastAPI's built-in exceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTP exceptions with standardized format."""
    
    # Generate request ID if not present
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        import uuid
        request_id = str(uuid.uuid4())
    
    logger.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        url=str(request.url),
        method=request.method,
        request_id=request_id
    )
    
    # Standardized error response
    response_data = {
        "error": f"HTTP_{exc.status_code}",
        "message": exc.detail,
        "timestamp": datetime.utcnow().isoformat(),
        "path": request.url.path,
        "method": request.method,
        "request_id": request_id
    }
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data
    )


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler with structured logging and standardized responses."""
    logger.error(
        "unhandled_exception",
        exception=str(exc),
        exception_type=type(exc).__name__,
        url=str(request.url),
        method=request.method,
    )
    
    # Generate request ID if not present
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        import uuid
        request_id = str(uuid.uuid4())
    
    # Standardized error response
    response_data = {
        "error": "INTERNAL_SERVER_ERROR",
        "message": "Internal server error",
        "timestamp": datetime.utcnow().isoformat(),
        "path": request.url.path,
        "method": request.method,
        "request_id": request_id
    }
    
    if settings.is_development:
        # In development, return detailed error information
        response_data.update({
            "message": f"Internal server error: {str(exc)}",
            "details": {
                "exception_type": type(exc).__name__,
                "exception_detail": str(exc)
            }
        })
    
    return JSONResponse(
        status_code=500,
        content=response_data
    )


# API Version information endpoints
app.include_router(create_version_endpoints(), prefix="/api", tags=["API Versioning"])

# Health endpoints (version-independent)
app.include_router(health.router, prefix="", tags=["Health"])

# V2 API Routes (Primary)
app.include_router(enhanced_context.router, prefix="", tags=["Enhanced Context Memory v2"])

# V1 API Routes (Backward Compatibility)
app.include_router(llm_gateway.router, prefix="/v1", tags=["LLM Gateway v1 (Legacy)"])
app.include_router(models.router, prefix="/v1", tags=["Models v1 (Legacy)"])
app.include_router(ingest.router, prefix="/v1", tags=["Context Memory v1 (Legacy)"])
app.include_router(recall.router, prefix="/v1", tags=["Context Memory v1 (Legacy)"])
app.include_router(workingset.router, prefix="/v1", tags=["Context Memory v1 (Legacy)"])
app.include_router(expand.router, prefix="/v1", tags=["Context Memory v1 (Legacy)"])
app.include_router(feedback.router, prefix="/v1", tags=["Context Memory v1 (Legacy)"])
app.include_router(workers.router, prefix="/v1", tags=["Workers v1 (Legacy)"])
app.include_router(cache.router, prefix="/v1", tags=["Cache v1 (Legacy)"])
app.include_router(benchmarks.router, prefix="/v1", tags=["Benchmarks v1 (Legacy)"])

# Admin interface (version-independent)
app.include_router(admin_router, prefix="/admin", tags=["Admin"])

# Static files for admin interface
try:
    app.mount("/static", StaticFiles(directory="app/admin/static"), name="static")
except RuntimeError:
    # Static directory doesn't exist, skip mounting
    pass


# Root endpoint - redirect to admin login
@app.get("/")
async def root(request: Request):
    """Root endpoint redirects to admin login."""
    return RedirectResponse(url="/admin/login", status_code=302)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_root():
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=settings.is_development,
        log_config=None,  # Use our custom logging setup
    )

