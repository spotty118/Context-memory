"""
Comprehensive health check endpoints for Kubernetes and monitoring systems.
Provides detailed application health, readiness, and liveness checks.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
import asyncio
import time
import structlog
from datetime import datetime, timedelta
import os
import psutil
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_db
from app.core.config import settings
from app.core.cache import get_cache_manager
from app.core.redis import get_redis_client
from app.core.supabase import get_supabase
from app.telemetry.metrics import metrics_collector
from app.core.circuit_breaker import circuit_breaker_registry

logger = structlog.get_logger(__name__)

router = APIRouter()

# Health check configuration
HEALTH_CHECK_TIMEOUT = 5.0  # seconds
MAX_RESPONSE_TIME = 2.0  # seconds for healthy response
MAX_CPU_USAGE = 90.0  # percent
MAX_MEMORY_USAGE = 90.0  # percent


class HealthChecker:
    """Centralized health checking for all application components."""
    
    def __init__(self):
        self.startup_time = datetime.utcnow()
        self.last_health_check = None
        self.health_cache = {}
        self.health_cache_ttl = 10  # seconds
        
    async def check_database_health(self, db: AsyncSession) -> Dict[str, Any]:
        """Check database connectivity and performance."""
        start_time = time.time()
        
        try:
            # Simple connectivity test
            result = await db.execute(text("SELECT 1 as healthy"))
            row = result.fetchone()
            
            if row and row.healthy == 1:
                response_time = time.time() - start_time
                
                # Check connection pool status
                pool_info = {
                    "status": "healthy",
                    "response_time_ms": round(response_time * 1000, 2),
                    "pool_size": getattr(db.bind.pool, 'size', 'unknown'),
                    "checked_out": getattr(db.bind.pool, 'checkedout', 'unknown'),
                    "overflow": getattr(db.bind.pool, 'overflow', 'unknown')
                }
                
                if response_time > MAX_RESPONSE_TIME:
                    pool_info["status"] = "degraded"
                    pool_info["warning"] = f"High response time: {response_time:.3f}s"
                
                return pool_info
            else:
                return {"status": "unhealthy", "error": "Invalid response from database"}
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
    
    async def check_redis_health(self) -> Dict[str, Any]:
        """Check Redis connectivity and performance."""
        start_time = time.time()
        
        try:
            redis_client = await get_redis_client()
            if not redis_client:
                return {"status": "unhealthy", "error": "Redis client not available"}
            
            # Test basic operations
            test_key = f"health_check_{int(time.time())}"
            await redis_client.set(test_key, "healthy", ex=60)
            value = await redis_client.get(test_key)
            await redis_client.delete(test_key)
            
            response_time = time.time() - start_time
            
            if value == "healthy":
                info = await redis_client.info()
                return {
                    "status": "healthy" if response_time <= MAX_RESPONSE_TIME else "degraded",
                    "response_time_ms": round(response_time * 1000, 2),
                    "connected_clients": info.get("connected_clients", "unknown"),
                    "used_memory": info.get("used_memory_human", "unknown"),
                    "uptime": info.get("uptime_in_seconds", "unknown")
                }
            else:
                return {"status": "unhealthy", "error": "Redis read/write test failed"}
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
    
    async def check_supabase_health(self) -> Dict[str, Any]:
        """Check Supabase connectivity."""
        start_time = time.time()
        
        try:
            client = get_supabase()
            
            # Test basic connectivity with a simple query
            response = client.table("api_keys").select("id").limit(1).execute()
            
            response_time = time.time() - start_time
            
            return {
                "status": "healthy" if response_time <= MAX_RESPONSE_TIME else "degraded",
                "response_time_ms": round(response_time * 1000, 2),
                "url": settings.SUPABASE_URL,
                "connection": "established"
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
    
    async def check_cache_health(self) -> Dict[str, Any]:
        """Check cache system health."""
        start_time = time.time()
        
        try:
            cache_manager = get_cache_manager()
            
            # Test cache operations
            test_key = f"health_check_{int(time.time())}"
            await cache_manager.set(test_key, "healthy", ttl=60)
            value = await cache_manager.get(test_key)
            await cache_manager.delete(test_key)
            
            response_time = time.time() - start_time
            
            if value == "healthy":
                return {
                    "status": "healthy" if response_time <= MAX_RESPONSE_TIME else "degraded",
                    "response_time_ms": round(response_time * 1000, 2),
                    "backend": "redis" if hasattr(cache_manager, 'redis_client') else "memory"
                }
            else:
                return {"status": "unhealthy", "error": "Cache read/write test failed"}
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
    
    def check_system_health(self) -> Dict[str, Any]:
        """Check system resource health."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # Disk usage for the root partition
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            
            # Process information
            process = psutil.Process()
            process_memory = process.memory_info()
            
            status = "healthy"
            warnings = []
            
            if cpu_percent > MAX_CPU_USAGE:
                status = "degraded"
                warnings.append(f"High CPU usage: {cpu_percent:.1f}%")
            
            if memory_percent > MAX_MEMORY_USAGE:
                status = "degraded"
                warnings.append(f"High memory usage: {memory_percent:.1f}%")
            
            if disk_percent > 85.0:
                status = "degraded"
                warnings.append(f"High disk usage: {disk_percent:.1f}%")
            
            return {
                "status": status,
                "warnings": warnings,
                "cpu_usage_percent": round(cpu_percent, 1),
                "memory_usage_percent": round(memory_percent, 1),
                "disk_usage_percent": round(disk_percent, 1),
                "process_memory_mb": round(process_memory.rss / 1024 / 1024, 1),
                "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else None
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def run_comprehensive_health_check(self, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """Run all health checks and return comprehensive status."""
        
        # Check cache first to avoid expensive checks
        now = time.time()
        if (self.last_health_check and 
            now - self.last_health_check < self.health_cache_ttl and
            self.health_cache):
            return self.health_cache
        
        start_time = time.time()
        
        # Run all health checks concurrently
        health_tasks = {
            "redis": self.check_redis_health(),
            "supabase": self.check_supabase_health(),
            "cache": self.check_cache_health(),
        }
        
        # Add database check if session is available
        if db:
            health_tasks["database"] = self.check_database_health(db)
        
        # Wait for all checks with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*health_tasks.values(), return_exceptions=True),
                timeout=HEALTH_CHECK_TIMEOUT
            )
            
            # Map results back to component names
            component_health = {}
            for i, (component, _) in enumerate(health_tasks.items()):
                if isinstance(results[i], Exception):
                    component_health[component] = {
                        "status": "unhealthy",
                        "error": str(results[i])
                    }
                else:
                    component_health[component] = results[i]
            
        except asyncio.TimeoutError:
            component_health = {comp: {"status": "timeout", "error": "Health check timed out"} 
                              for comp in health_tasks.keys()}
        
        # Add system health (synchronous)
        component_health["system"] = self.check_system_health()
        
        # Calculate overall status
        statuses = [comp.get("status", "unknown") for comp in component_health.values()]
        
        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses or "timeout" in statuses:
            overall_status = "degraded"
        else:
            overall_status = "healthy"
        
        # Add circuit breaker status
        circuit_breaker_stats = circuit_breaker_registry.get_all_stats()
        
        # Build comprehensive response
        health_response = {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int((datetime.utcnow() - self.startup_time).total_seconds()),
            "version": "1.0.0",
            "environment": settings.ENVIRONMENT,
            "response_time_ms": round((time.time() - start_time) * 1000, 2),
            "components": component_health,
            "circuit_breakers": circuit_breaker_stats
        }
        
        # Cache the result
        self.health_cache = health_response
        self.last_health_check = now
        
        return health_response


# Global health checker instance
health_checker = HealthChecker()


@router.get("/health", summary="Basic Health Check")
async def health_check():
    """
    Basic health check endpoint.
    Returns 200 if the application is running.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "context-memory-gateway"
        }
    )


@router.get("/health/ready", summary="Readiness Probe")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """
    Kubernetes readiness probe endpoint.
    Checks if the application is ready to serve traffic.
    """
    try:
        health_data = await health_checker.run_comprehensive_health_check(db)
        
        if health_data["status"] in ["healthy", "degraded"]:
            return JSONResponse(
                status_code=200,
                content=health_data
            )
        else:
            return JSONResponse(
                status_code=503,
                content=health_data
            )
            
    except Exception as e:
        logger.exception("readiness_check_failed", error=str(e))
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/health/live", summary="Liveness Probe")
async def liveness_check():
    """
    Kubernetes liveness probe endpoint.
    Checks if the application is alive and should not be restarted.
    """
    try:
        # Simple liveness check - just verify the application is responsive
        uptime = datetime.utcnow() - health_checker.startup_time
        
        # Check if the application has been running too long without restart
        max_uptime_hours = 24 * 7  # 7 days
        if uptime.total_seconds() > max_uptime_hours * 3600:
            logger.warning("application_uptime_warning", uptime_hours=uptime.total_seconds() / 3600)
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "alive",
                "timestamp": datetime.utcnow().isoformat(),
                "uptime_seconds": int(uptime.total_seconds()),
                "pid": os.getpid()
            }
        )
        
    except Exception as e:
        logger.exception("liveness_check_failed", error=str(e))
        return JSONResponse(
            status_code=503,
            content={
                "status": "dead",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/health/detailed", summary="Detailed Health Check")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """
    Detailed health check with comprehensive component status.
    Use for monitoring and debugging purposes.
    """
    try:
        health_data = await health_checker.run_comprehensive_health_check(db)
        
        # Add additional debug information
        health_data["debug"] = {
            "startup_time": health_checker.startup_time.isoformat(),
            "last_health_check": health_checker.last_health_check,
            "cache_ttl": health_checker.health_cache_ttl,
            "process_id": os.getpid(),
            "python_version": os.sys.version
        }
        
        status_code = 200 if health_data["status"] != "unhealthy" else 503
        
        return JSONResponse(
            status_code=status_code,
            content=health_data
        )
        
    except Exception as e:
        logger.exception("detailed_health_check_failed", error=str(e))
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@router.get("/health/circuit-breakers", summary="Circuit Breaker Status")
async def circuit_breaker_status():
    """
    Get status of all circuit breakers.
    Useful for monitoring external service health.
    """
    try:
        stats = circuit_breaker_registry.get_all_stats()
        
        # Calculate overall circuit breaker health
        overall_status = "healthy"
        open_circuits = [name for name, breaker_stats in stats.items() if breaker_stats["state"] == "open"]
        half_open_circuits = [name for name, breaker_stats in stats.items() if breaker_stats["state"] == "half_open"]
        
        if open_circuits:
            overall_status = "degraded" if len(open_circuits) < len(stats) else "unhealthy"
        elif half_open_circuits:
            overall_status = "warning"
        
        return JSONResponse(
            status_code=200 if overall_status in ["healthy", "warning"] else 503,
            content={
                "status": overall_status,
                "timestamp": datetime.utcnow().isoformat(),
                "summary": {
                    "total_circuits": len(stats),
                    "open_circuits": len(open_circuits),
                    "half_open_circuits": len(half_open_circuits),
                    "closed_circuits": len(stats) - len(open_circuits) - len(half_open_circuits)
                },
                "circuit_breakers": stats,
                "open_circuit_names": open_circuits,
                "half_open_circuit_names": half_open_circuits
            }
        )
        
    except Exception as e:
        logger.exception("circuit_breaker_status_failed")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )