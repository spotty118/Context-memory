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
from fastapi.responses import JSONResponse, HTMLResponse
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
        logger.warning("cache_warm_failed_on_startup", error=str(e))
    
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

# V1 API Routes
app.include_router(llm_gateway.router, prefix="/v1", tags=["LLM Gateway v1"])
app.include_router(models.router, prefix="/v1", tags=["Models v1"])
app.include_router(ingest.router, prefix="/v1", tags=["Context Memory v1"])
app.include_router(recall.router, prefix="/v1", tags=["Context Memory v1"])
app.include_router(workingset.router, prefix="/v1", tags=["Context Memory v1"])
app.include_router(expand.router, prefix="/v1", tags=["Context Memory v1"])
app.include_router(feedback.router, prefix="/v1", tags=["Context Memory v1"])
app.include_router(workers.router, prefix="/v1", tags=["Workers v1"])
app.include_router(cache.router, prefix="/v1", tags=["Cache v1"])
app.include_router(benchmarks.router, prefix="/v1", tags=["Benchmarks v1"])

# Future V2 API Routes (placeholder for when v2 is implemented)
# v2_router = create_versioned_router("v2", tags=["API v2"])
# app.include_router(v2_router)

# Admin interface (version-independent)
app.include_router(admin_router, prefix="/admin", tags=["Admin"])

# Static files for admin interface
try:
    app.mount("/static", StaticFiles(directory="app/admin/static"), name="static")
except RuntimeError:
    # Static directory doesn't exist, skip mounting
    pass


# Root endpoint
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint with web interface landing page."""
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Context Memory + LLM Gateway</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }}
            .container {{
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                margin-top: 50px;
            }}
            h1 {{
                color: #2c3e50;
                text-align: center;
                margin-bottom: 10px;
            }}
            .subtitle {{
                text-align: center;
                color: #7f8c8d;
                margin-bottom: 40px;
                font-size: 1.1em;
            }}
            .status {{
                text-align: center;
                padding: 10px;
                background: #2ecc71;
                color: white;
                border-radius: 5px;
                margin: 20px 0;
                font-weight: bold;
            }}
            .features {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 30px;
                margin: 40px 0;
            }}
            .feature-card {{
                background: #f8f9fa;
                padding: 25px;
                border-radius: 8px;
                border-left: 4px solid #3498db;
            }}
            .feature-card h3 {{
                color: #2c3e50;
                margin-top: 0;
            }}
            .endpoints {{
                background: #ecf0f1;
                padding: 20px;
                border-radius: 5px;
                margin: 30px 0;
            }}
            .endpoints h3 {{
                margin-top: 0;
                color: #2c3e50;
            }}
            .endpoint-link {{
                display: inline-block;
                margin: 10px 10px 10px 0;
                padding: 10px 15px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                transition: background 0.3s;
            }}
            .endpoint-link:hover {{
                background: #2980b9;
            }}
            .admin-link {{
                background: #e74c3c;
            }}
            .admin-link:hover {{
                background: #c0392b;
            }}
            .docs-link {{
                background: #f39c12;
            }}
            .docs-link:hover {{
                background: #e67e22;
            }}
            .footer {{
                text-align: center;
                margin-top: 40px;
                color: #7f8c8d;
                font-size: 0.9em;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🧠 Context Memory + LLM Gateway</h1>
            <p class="subtitle">Advanced context memory system with LLM gateway capabilities</p>
            
            <div class="status">
                🟢 System Status: Operational | Environment: {settings.ENVIRONMENT.title()}
            </div>

            <div class="features">
                <div class="feature-card">
                    <h3>🔗 LLM Gateway</h3>
                    <p>Unified API access to multiple LLM providers including OpenAI, OpenRouter, and more with intelligent routing and load balancing.</p>
                </div>
                
                <div class="feature-card">
                    <h3>🧠 Context Memory</h3>
                    <p>Advanced semantic and episodic memory system that maintains conversation context across sessions and interactions.</p>
                </div>
                
                <div class="feature-card">
                    <h3>🔍 Vector Search</h3>
                    <p>Powered by Qdrant vector database for efficient similarity search and context retrieval from stored memories.</p>
                </div>
                
                <div class="feature-card">
                    <h3>🔐 API Management</h3>
                    <p>Comprehensive API key management, usage tracking, and access control for secure multi-tenant deployment.</p>
                </div>
            </div>

            <div class="endpoints">
                <h3>🚀 Available Endpoints</h3>
                <a href="/docs" class="endpoint-link docs-link">📚 API Documentation</a>
                <a href="/admin/" class="endpoint-link admin-link">⚙️ Admin Dashboard</a>
                <a href="/admin/api-keys" class="endpoint-link admin-link">🔑 API Keys</a>
                <a href="/admin/models" class="endpoint-link admin-link">🤖 Models</a>
            </div>

            <div class="endpoints">
                <h3>🔌 API Integration</h3>
                <p><strong>Base URL:</strong> <code>http://45.79.220.225/v1/</code></p>
                <p><strong>Current API Version:</strong> v1 (Latest)</p>
                <p><strong>Authentication:</strong> Bearer token authentication required</p>
                <p><strong>Version Management:</strong> <a href="/api/versions">View API Versions</a></p>
                <p>Compatible with OpenAI SDK - simply change the base URL to start using our enhanced memory features.</p>
            </div>

            <div class="footer">
                <p>Context Memory + LLM Gateway v1.0.0 | Server: 45.79.220.225 |
                <a href="https://github.com/justinadams-context-memory" target="_blank">Documentation</a></p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=settings.is_development,
        log_config=None,  # Use our custom logging setup
    )

