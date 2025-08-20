"""
Main FastAPI application entry point for Context Memory + LLM Gateway.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import structlog
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings
from app.telemetry.logging import setup_logging
from app.telemetry.otel import setup_telemetry
from app.db.session import init_db
from app.api import llm_gateway, models, ingest, recall, workingset, expand, feedback, health, workers
from app.admin.views import router as admin_router


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with structured logging."""
    start_time = structlog.get_logger().info("request_started", 
        method=request.method,
        url=str(request.url),
        client_ip=request.client.host if request.client else None,
    )
    
    response = await call_next(request)
    
    # Don't log prompts unless explicitly enabled
    log_data = {
        "method": request.method,
        "url": str(request.url),
        "status_code": response.status_code,
        "client_ip": request.client.host if request.client else None,
    }
    
    if response.status_code >= 400:
        logger.error("request_completed", **log_data)
    else:
        logger.info("request_completed", **log_data)
    
    return response


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler with structured logging."""
    logger.error(
        "unhandled_exception",
        exception=str(exc),
        exception_type=type(exc).__name__,
        url=str(request.url),
        method=request.method,
    )
    
    if settings.is_development:
        # In development, return detailed error information
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc),
                "type": type(exc).__name__,
            }
        )
    else:
        # In production, return generic error message
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        )


# API Routes
app.include_router(health.router, prefix="", tags=["Health"])
app.include_router(llm_gateway.router, prefix="/v1", tags=["LLM Gateway"])
app.include_router(models.router, prefix="/v1", tags=["Models"])
app.include_router(ingest.router, prefix="/v1", tags=["Context Memory"])
app.include_router(recall.router, prefix="/v1", tags=["Context Memory"])
app.include_router(workingset.router, prefix="/v1", tags=["Context Memory"])
app.include_router(expand.router, prefix="/v1", tags=["Context Memory"])
app.include_router(feedback.router, prefix="/v1", tags=["Context Memory"])
app.include_router(workers.router, prefix="/v1", tags=["Workers"])

# Admin interface
app.include_router(admin_router, prefix="/admin", tags=["Admin"])

# Static files for admin interface
try:
    app.mount("/static", StaticFiles(directory="app/admin/static"), name="static")
except RuntimeError:
    # Static directory doesn't exist, skip mounting
    pass


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with basic service information."""
    return {
        "service": "Context Memory + LLM Gateway",
        "version": "1.0.0",
        "status": "operational",
        "environment": settings.ENVIRONMENT,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=settings.is_development,
        log_config=None,  # Use our custom logging setup
    )

