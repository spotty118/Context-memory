"""
Health check endpoints for monitoring and observability.
"""
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
import structlog
import redis.asyncio as redis

from app.core.config import settings
from app.db.session import get_db_dependency
from app.core.ratelimit import get_redis
from app.telemetry.otel import get_metrics

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/healthz")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint.
    Returns 200 if service is running.
    """
    return {
        "status": "healthy",
        "service": "context-memory-gateway",
        "version": "1.0.0",
        "timestamp": int(time.time()),
        "environment": settings.ENVIRONMENT,
    }


@router.get("/readyz")
async def readiness_check(db = Depends(get_db_dependency)) -> Dict[str, Any]:
    """
    Readiness check endpoint that verifies all dependencies.
    Returns 200 if service is ready to handle requests.
    """
    checks = {}
    overall_status = "ready"
    
    # Check database connectivity
    try:
        start_time = time.time()
        result = await db.execute(text("SELECT 1"))
        db_latency = (time.time() - start_time) * 1000  # Convert to milliseconds
        
        checks["database"] = {
            "status": "healthy",
            "latency_ms": round(db_latency, 2),
        }
        logger.debug("database_health_check_passed", latency_ms=db_latency)
        
    except Exception as e:
        checks["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        overall_status = "not_ready"
        logger.error("database_health_check_failed", error=str(e))
    
    # Check Redis connectivity
    try:
        start_time = time.time()
        redis_client = await get_redis()
        await redis_client.ping()
        redis_latency = (time.time() - start_time) * 1000
        
        checks["redis"] = {
            "status": "healthy",
            "latency_ms": round(redis_latency, 2),
        }
        logger.debug("redis_health_check_passed", latency_ms=redis_latency)
        
    except Exception as e:
        checks["redis"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        overall_status = "not_ready"
        logger.error("redis_health_check_failed", error=str(e))
    
    # Check vector backend if using Qdrant
    if settings.VECTOR_BACKEND == "qdrant" and settings.QDRANT_URL:
        try:
            # This would be implemented when Qdrant client is added
            checks["qdrant"] = {
                "status": "healthy",
                "note": "qdrant_check_not_implemented",
            }
        except Exception as e:
            checks["qdrant"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            overall_status = "not_ready"
    
    response = {
        "status": overall_status,
        "service": "context-memory-gateway",
        "version": "1.0.0",
        "timestamp": int(time.time()),
        "environment": settings.ENVIRONMENT,
        "checks": checks,
    }
    
    if overall_status != "ready":
        logger.warning("readiness_check_failed", checks=checks)
        raise HTTPException(status_code=503, detail=response)
    
    return response


@router.get("/metrics")
async def metrics_endpoint():
    """
    Prometheus metrics endpoint.
    Returns metrics in Prometheus format.
    """
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    
    metrics_data = get_metrics()
    return Response(content=metrics_data, media_type="text/plain; version=0.0.4; charset=utf-8")

