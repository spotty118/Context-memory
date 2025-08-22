"""
Cache management API endpoints.
Provides endpoints for monitoring, warming, and invalidating cache.
"""
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import structlog

from app.core.security import get_api_key
from app.db.models import APIKey
from app.core.cache import cache_manager, CacheInvalidator
from app.services.cache import ModelCacheService, SettingsCacheService


router = APIRouter(prefix="/cache", tags=["Cache Management"])
logger = structlog.get_logger(__name__)


class CacheWarmRequest(BaseModel):
    """Request model for cache warming operations."""
    models: bool = True
    settings: bool = True
    limit: int = 100


class CacheInvalidateRequest(BaseModel):
    """Request model for cache invalidation operations."""
    pattern: Optional[str] = None
    cache_type: Optional[str] = None
    model_id: Optional[str] = None
    setting_key: Optional[str] = None
    workspace_id: Optional[str] = None


@router.get("/status")
async def get_cache_status(
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Get current cache system status and statistics.
    
    Returns:
        Cache status including hit rates, memory usage, and configuration
    """
    try:
        # Get cache statistics
        stats = await cache_manager.get_stats()
        
        # Get cache health status
        health = await cache_manager.health_check()
        
        # Get model cache specific stats
        model_stats = await ModelCacheService.get_model_stats()
        
        return {
            "status": "healthy" if health["status"] == "healthy" else "degraded",
            "cache_stats": stats,
            "health_check": health,
            "model_stats": model_stats,
            "timestamp": stats.get("timestamp", "unknown")
        }
        
    except Exception as e:
        logger.error("cache_status_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get cache status: {str(e)}")


@router.post("/warm")
async def warm_cache(
    request: CacheWarmRequest,
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Warm the cache by pre-loading frequently accessed data.
    
    Args:
        request: Cache warming configuration
        
    Returns:
        Results of the warming operation
    """
    try:
        results = {
            "models_warmed": False,
            "settings_warmed": False,
            "errors": []
        }
        
        # Warm model cache
        if request.models:
            try:
                await ModelCacheService.warm_cache(limit=request.limit)
                results["models_warmed"] = True
                logger.info("model_cache_warmed", limit=request.limit)
            except Exception as e:
                error_msg = f"Model cache warming failed: {str(e)}"
                results["errors"].append(error_msg)
                logger.error("model_cache_warm_error", error=str(e))
        
        # Warm settings cache
        if request.settings:
            try:
                await SettingsCacheService.warm_cache()
                results["settings_warmed"] = True
                logger.info("settings_cache_warmed")
            except Exception as e:
                error_msg = f"Settings cache warming failed: {str(e)}"
                results["errors"].append(error_msg)
                logger.error("settings_cache_warm_error", error=str(e))
        
        return {
            "status": "completed" if not results["errors"] else "partial",
            "results": results,
            "workspace_id": api_key.workspace_id
        }
        
    except Exception as e:
        logger.error("cache_warm_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Cache warming failed: {str(e)}")


@router.post("/invalidate")
async def invalidate_cache(
    request: CacheInvalidateRequest,
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Invalidate cache entries based on specified criteria.
    
    Args:
        request: Cache invalidation configuration
        
    Returns:
        Results of the invalidation operation
    """
    try:
        results = {
            "invalidated_count": 0,
            "operations": []
        }
        
        # Pattern-based invalidation
        if request.pattern:
            count = await cache_manager.invalidate_pattern(request.pattern)
            results["invalidated_count"] += count
            results["operations"].append(f"Pattern '{request.pattern}': {count} keys")
            logger.info("cache_pattern_invalidated", pattern=request.pattern, count=count)
        
        # Model-specific invalidation
        if request.model_id:
            await ModelCacheService.invalidate_model_cache(request.model_id)
            results["operations"].append(f"Model '{request.model_id}' cache invalidated")
            logger.info("model_cache_invalidated", model_id=request.model_id)
        
        # Settings invalidation
        if request.setting_key:
            await SettingsCacheService.invalidate_settings_cache(key=request.setting_key)
            results["operations"].append(f"Setting '{request.setting_key}' cache invalidated")
            logger.info("setting_cache_invalidated", setting_key=request.setting_key)
        
        # Workspace-specific invalidation
        if request.workspace_id:
            await SettingsCacheService.invalidate_settings_cache(workspace_id=request.workspace_id)
            results["operations"].append(f"Workspace '{request.workspace_id}' cache invalidated")
            logger.info("workspace_cache_invalidated", workspace_id=request.workspace_id)
        
        # Cache type specific invalidation
        if request.cache_type:
            if request.cache_type == "models":
                await ModelCacheService.invalidate_model_cache()
                results["operations"].append("All model cache invalidated")
            elif request.cache_type == "settings":
                await SettingsCacheService.invalidate_settings_cache()
                results["operations"].append("All settings cache invalidated")
            else:
                results["operations"].append(f"Unknown cache type: {request.cache_type}")
        
        return {
            "status": "completed",
            "results": results,
            "workspace_id": api_key.workspace_id
        }
        
    except Exception as e:
        logger.error("cache_invalidate_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Cache invalidation failed: {str(e)}")


@router.delete("/clear")
async def clear_cache(
    cache_type: Optional[str] = None,
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Clear cache entries. Use with caution.
    
    Args:
        cache_type: Specific cache type to clear (optional)
        
    Returns:
        Results of the clear operation
    """
    try:
        results = {"cleared": [], "errors": []}
        
        if cache_type == "models":
            await ModelCacheService.invalidate_model_cache()
            results["cleared"].append("Model cache cleared")
            logger.info("model_cache_cleared")
            
        elif cache_type == "settings":
            await SettingsCacheService.invalidate_settings_cache()
            results["cleared"].append("Settings cache cleared")
            logger.info("settings_cache_cleared")
            
        elif cache_type is None:
            # Clear all cache
            model_count = await cache_manager.invalidate_pattern("cmg:model*")
            settings_count = await cache_manager.invalidate_pattern("cmg:settings*")
            
            results["cleared"].append(f"All cache cleared: {model_count + settings_count} keys")
            logger.info("all_cache_cleared", model_keys=model_count, settings_keys=settings_count)
            
        else:
            results["errors"].append(f"Unknown cache type: {cache_type}")
        
        return {
            "status": "completed" if not results["errors"] else "partial",
            "results": results,
            "workspace_id": api_key.workspace_id
        }
        
    except Exception as e:
        logger.error("cache_clear_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Cache clear failed: {str(e)}")


@router.get("/health")
async def cache_health_check(
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Perform comprehensive cache health check.
    
    Returns:
        Detailed health information about the cache system
    """
    try:
        health = await cache_manager.health_check()
        
        # Additional health checks
        additional_checks = {
            "redis_connectivity": health.get("redis_connected", False),
            "memory_cache_responsive": len(cache_manager._memory_cache) >= 0,
            "error_rate": health.get("stats", {}).get("errors", 0) / max(
                health.get("stats", {}).get("hits", 1) + health.get("stats", {}).get("misses", 1), 1
            ),
            "hit_rate": health.get("stats", {}).get("hit_rate", 0)
        }
        
        # Determine overall health
        is_healthy = (
            health.get("status") == "healthy" and
            additional_checks["redis_connectivity"] and
            additional_checks["error_rate"] < 0.1 and  # Less than 10% error rate
            additional_checks["hit_rate"] > 0.1  # At least 10% hit rate
        )
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "checks": {
                **health,
                **additional_checks
            },
            "recommendations": _get_health_recommendations(additional_checks),
            "workspace_id": api_key.workspace_id
        }
        
    except Exception as e:
        logger.error("cache_health_check_error", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "workspace_id": api_key.workspace_id
        }


@router.get("/config")
async def get_cache_config(
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Get current cache configuration.
    
    Returns:
        Cache configuration details
    """
    try:
        stats = await cache_manager.get_stats()
        
        return {
            "configurations": stats.get("configurations", {}),
            "memory_cache_enabled": True,
            "redis_cache_enabled": True,
            "default_ttls": {
                "model_catalog": 3600,
                "model_list": 1800,
                "global_settings": 900,
                "api_key_settings": 600,
                "workspace_settings": 1200
            },
            "workspace_id": api_key.workspace_id
        }
        
    except Exception as e:
        logger.error("cache_config_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get cache config: {str(e)}")


def _get_health_recommendations(checks: Dict[str, Any]) -> List[str]:
    """Generate health recommendations based on checks."""
    recommendations = []
    
    if not checks.get("redis_connectivity", False):
        recommendations.append("Redis connection issue detected. Check Redis server status.")
    
    if checks.get("error_rate", 0) > 0.05:  # More than 5% error rate
        recommendations.append("High cache error rate detected. Consider investigating Redis connectivity.")
    
    if checks.get("hit_rate", 0) < 0.2:  # Less than 20% hit rate
        recommendations.append("Low cache hit rate. Consider warming cache or reviewing TTL settings.")
    
    if not recommendations:
        recommendations.append("Cache system is operating normally.")
    
    return recommendations


# Export router
__all__ = ["router"]