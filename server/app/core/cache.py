"""
Advanced caching service for Context Memory Gateway.
Provides Redis-based caching for model catalogs, settings, and other frequently accessed data.
"""
import json
import time
from typing import Dict, Any, Optional, List, Union, Type, TypeVar, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import asyncio
import structlog
import redis.asyncio as redis
from functools import wraps

from app.core.config import settings
from app.core.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig

logger = structlog.get_logger(__name__)

T = TypeVar('T')


class CacheLayer(Enum):
    """Cache layer definitions."""
    MEMORY = "memory"      # In-process memory cache (fastest)
    REDIS = "redis"        # Redis cache (shared across instances)
    DATABASE = "database"  # Database (slowest, but authoritative)


@dataclass
class CacheConfig:
    """Cache configuration for different data types."""
    ttl_seconds: int
    layer: CacheLayer = CacheLayer.REDIS
    enable_compression: bool = False
    enable_versioning: bool = False
    max_size_mb: int = 10  # Per cache entry


class CacheKeyGenerator:
    """Centralized cache key generation with consistent patterns."""
    
    PREFIX = "cmg"  # Context Memory Gateway prefix
    
    @staticmethod
    def model_catalog(model_id: Optional[str] = None) -> str:
        """Generate cache key for model catalog."""
        if model_id:
            return f"{CacheKeyGenerator.PREFIX}:model:{model_id}"
        return f"{CacheKeyGenerator.PREFIX}:models:all"
    
    @staticmethod
    def model_list(provider: Optional[str] = None, status: Optional[str] = None) -> str:
        """Generate cache key for model lists."""
        parts = [CacheKeyGenerator.PREFIX, "models", "list"]
        if provider:
            parts.append(f"provider:{provider}")
        if status:
            parts.append(f"status:{status}")
        return ":".join(parts)
    
    @staticmethod
    def global_settings(key: Optional[str] = None) -> str:
        """Generate cache key for global settings."""
        if key:
            return f"{CacheKeyGenerator.PREFIX}:settings:{key}"
        return f"{CacheKeyGenerator.PREFIX}:settings:all"
    
    @staticmethod
    def api_key_settings(api_key_id: str) -> str:
        """Generate cache key for API key specific settings."""
        return f"{CacheKeyGenerator.PREFIX}:api_key:{api_key_id}:settings"
    
    @staticmethod
    def workspace_settings(workspace_id: str) -> str:
        """Generate cache key for workspace settings."""
        return f"{CacheKeyGenerator.PREFIX}:workspace:{workspace_id}:settings"
    
    @staticmethod
    def rate_limit_status(api_key_id: str, window: str) -> str:
        """Generate cache key for rate limit status."""
        return f"{CacheKeyGenerator.PREFIX}:rate_limit:{api_key_id}:{window}"


class CacheManager:
    """
    Advanced cache manager with multi-layer caching, TTL management, and invalidation.
    """
    
    def __init__(self):
        self._redis_client: Optional[redis.Redis] = None
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_configs: Dict[str, CacheConfig] = self._initialize_cache_configs()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0
        }
    
    def _initialize_cache_configs(self) -> Dict[str, CacheConfig]:
        """Initialize cache configurations for different data types."""
        return {
            "model_catalog": CacheConfig(
                ttl_seconds=3600,  # 1 hour
                layer=CacheLayer.REDIS,
                enable_compression=True,
                enable_versioning=True
            ),
            "model_list": CacheConfig(
                ttl_seconds=1800,  # 30 minutes
                layer=CacheLayer.REDIS,
                enable_compression=True
            ),
            "global_settings": CacheConfig(
                ttl_seconds=900,   # 15 minutes
                layer=CacheLayer.REDIS,
                enable_versioning=True
            ),
            "api_key_settings": CacheConfig(
                ttl_seconds=600,   # 10 minutes
                layer=CacheLayer.REDIS
            ),
            "workspace_settings": CacheConfig(
                ttl_seconds=1200,  # 20 minutes
                layer=CacheLayer.REDIS
            ),
            "rate_limit_stats": CacheConfig(
                ttl_seconds=60,    # 1 minute
                layer=CacheLayer.MEMORY  # Fast access for rate limiting
            )
        }
    
    async def get_redis_client(self) -> redis.Redis:
        """Get Redis client with connection pooling and circuit breaker protection."""
        if self._redis_client is None:
            circuit_breaker = get_circuit_breaker("redis", CircuitBreakerConfig(
                failure_threshold=5,
                recovery_timeout=30.0,
                success_threshold=2,
                timeout=10.0,
                expected_exception=Exception
            ))
            
            async def _create_client():
                return redis.from_url(
                    settings.REDIS_URL, 
                    decode_responses=True,
                    max_connections=20,
                    retry_on_timeout=True
                )
            
            self._redis_client = await circuit_breaker.call(_create_client)
        return self._redis_client
    
    async def get(
        self, 
        key: str, 
        cache_type: str = "default",
        default: Any = None
    ) -> Any:
        """
        Get value from cache with multi-layer support.
        
        Args:
            key: Cache key
            cache_type: Type of cache (affects TTL and behavior)
            default: Default value if not found
            
        Returns:
            Cached value or default
        """
        try:
            config = self._cache_configs.get(cache_type, CacheConfig(ttl_seconds=300))
            
            # Try memory cache first (if enabled for this type)
            if config.layer == CacheLayer.MEMORY:
                memory_result = self._get_from_memory(key)
                if memory_result is not None:
                    self._stats["hits"] += 1
                    return memory_result
            
            # Try Redis cache
            redis_client = await self.get_redis_client()
            cached_data = await redis_client.get(key)
            
            if cached_data is not None:
                try:
                    # Parse cached data structure
                    cache_entry = json.loads(cached_data)
                    
                    # Check if expired
                    if cache_entry.get("expires_at") and cache_entry["expires_at"] < time.time():
                        await self.delete(key, cache_type)
                        self._stats["misses"] += 1
                        return default
                    
                    # Extract value and update memory cache if applicable
                    value = cache_entry["data"]
                    if config.layer == CacheLayer.MEMORY:
                        self._set_in_memory(key, value, config.ttl_seconds)
                    
                    self._stats["hits"] += 1
                    logger.debug("cache_hit", key=key, cache_type=cache_type)
                    return value
                    
                except (json.JSONDecodeError, KeyError) as e:
                    logger.exception("cache_parse_error", key=key)
                    await self.delete(key, cache_type)
            
            self._stats["misses"] += 1
            logger.debug("cache_miss", key=key, cache_type=cache_type)
            return default
            
        except Exception as e:
            logger.exception("cache_get_error", key=key)
            return default
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        cache_type: str = "default",
        ttl_override: Optional[int] = None
    ) -> bool:
        """
        Set value in cache with TTL and compression support.
        
        Args:
            key: Cache key
            value: Value to cache
            cache_type: Type of cache (affects TTL and behavior)
            ttl_override: Override default TTL for this entry
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config = self._cache_configs.get(cache_type, CacheConfig(ttl_seconds=300))
            ttl = ttl_override or config.ttl_seconds
            
            # Prepare cache entry
            cache_entry = {
                "data": value,
                "created_at": time.time(),
                "expires_at": time.time() + ttl,
                "cache_type": cache_type,
                "version": 1 if config.enable_versioning else None
            }
            
            # Set in Redis
            redis_client = await self.get_redis_client()
            serialized_data = json.dumps(cache_entry, ensure_ascii=False)
            
            # Check size limit
            size_mb = len(serialized_data.encode('utf-8')) / (1024 * 1024)
            if size_mb > config.max_size_mb:
                logger.warning("cache_size_exceeded", key=key, size_mb=size_mb, limit_mb=config.max_size_mb)
                return False
            
            await redis_client.setex(key, ttl + 60, serialized_data)  # Extra 60s for grace period
            
            # Set in memory cache if applicable
            if config.layer == CacheLayer.MEMORY:
                self._set_in_memory(key, value, ttl)
            
            self._stats["sets"] += 1
            logger.debug("cache_set", key=key, cache_type=cache_type, ttl=ttl, size_mb=round(size_mb, 3))
            return True
            
        except Exception as e:
            logger.exception("cache_set_error", key=key)
            return False
    
    async def delete(self, key: str, cache_type: str = "default") -> bool:
        """Delete from all cache layers."""
        try:
            # Delete from Redis
            redis_client = await self.get_redis_client()
            await redis_client.delete(key)
            
            # Delete from memory
            if key in self._memory_cache:
                del self._memory_cache[key]
            
            self._stats["deletes"] += 1
            logger.debug("cache_delete", key=key, cache_type=cache_type)
            return True
            
        except Exception as e:
            logger.exception("cache_delete_error", key=key)
            return False
    
    async def clear_pattern(self, pattern: str) -> int:
        """
        Clear all cache entries matching a pattern using SCAN for better performance.
        
        Args:
            pattern: Redis pattern (e.g., "cmg:models:*")
            
        Returns:
            Number of keys deleted
        """
        try:
            redis_client = await self.get_redis_client()
            keys_to_delete = []
            
            # Use SCAN instead of KEYS for better performance
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
                keys_to_delete.extend(keys)
                if cursor == 0:
                    break
            
            if keys_to_delete:
                # Use pipeline for batch deletion
                pipe = redis_client.pipeline()
                
                # Split into batches to avoid memory issues with large datasets
                batch_size = 100
                total_deleted = 0
                
                for i in range(0, len(keys_to_delete), batch_size):
                    batch = keys_to_delete[i:i + batch_size]
                    pipe.delete(*batch)
                    results = await pipe.execute()
                    total_deleted += sum(results)
                    pipe.reset()
                
                # Clean memory cache
                memory_keys_to_delete = [k for k in self._memory_cache.keys() if self._matches_pattern(k, pattern)]
                for key in memory_keys_to_delete:
                    del self._memory_cache[key]
                
                logger.info("cache_pattern_invalidated", pattern=pattern, deleted_count=total_deleted)
                return total_deleted
            
            return 0
            
        except Exception as e:
            logger.exception("cache_clear_error", pattern=pattern)
            return 0
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.
        
        Args:
            pattern: Redis pattern (e.g., "cmg:models:*")
            
        Returns:
            Number of keys deleted
        """
        try:
            redis_client = await self.get_redis_client()
            keys = await redis_client.keys(pattern)
            
            if keys:
                deleted = await redis_client.delete(*keys)
                
                # Clean memory cache
                memory_keys_to_delete = [k for k in self._memory_cache.keys() if self._matches_pattern(k, pattern)]
                for key in memory_keys_to_delete:
                    del self._memory_cache[key]
                
                logger.info("cache_pattern_invalidated", pattern=pattern, deleted_count=deleted)
                return deleted
            
            return 0
            
        except Exception as e:
            logger.exception("cache_clear_error", pattern=pattern)
            return 0
    
    def _get_from_memory(self, key: str) -> Any:
        """Get value from in-memory cache."""
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if entry["expires_at"] > time.time():
                return entry["data"]
            else:
                del self._memory_cache[key]
        return None
    
    def _set_in_memory(self, key: str, value: Any, ttl: int):
        """Set value in in-memory cache."""
        self._memory_cache[key] = {
            "data": value,
            "expires_at": time.time() + ttl
        }
        
        # Simple cleanup - remove expired entries if memory cache gets large
        if len(self._memory_cache) > 1000:
            current_time = time.time()
            expired_keys = [k for k, v in self._memory_cache.items() if v["expires_at"] <= current_time]
            for key in expired_keys:
                del self._memory_cache[key]
    
    def _matches_pattern(self, key: str, pattern: str) -> bool:
        """Simple pattern matching for memory cache cleanup."""
        return pattern.replace("*", "") in key
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            redis_client = await self.get_redis_client()
            redis_info = await redis_client.info("memory")
            
            return {
                **self._stats,
                "memory_cache_size": len(self._memory_cache),
                "redis_memory_usage": redis_info.get("used_memory_human", "unknown"),
                "hit_rate": self._stats["hits"] / max(self._stats["hits"] + self._stats["misses"], 1),
                "configurations": {k: {"ttl": v.ttl_seconds, "layer": v.layer.value} for k, v in self._cache_configs.items()}
            }
        except Exception as e:
            logger.exception("cache_stats_error")
            return self._stats
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform cache health check."""
        try:
            redis_client = await self.get_redis_client()
            
            # Test Redis connectivity
            start_time = time.time()
            await redis_client.ping()
            redis_latency = (time.time() - start_time) * 1000
            
            # Test set/get operation
            test_key = f"{CacheKeyGenerator.PREFIX}:health_check"
            test_value = {"timestamp": time.time()}
            
            await self.set(test_key, test_value, "default", 60)
            retrieved = await self.get(test_key, "default")
            
            await self.delete(test_key, "default")
            
            return {
                "status": "healthy",
                "redis_connected": True,
                "redis_latency_ms": round(redis_latency, 2),
                "read_write_test": retrieved == test_value,
                "memory_cache_entries": len(self._memory_cache),
                "stats": await self.get_stats()
            }
            
        except Exception as e:
            logger.exception("cache_health_check_error")
            return {
                "status": "unhealthy",
                "redis_connected": False,
                "error": str(e),
                "memory_cache_entries": len(self._memory_cache)
            }


# Global cache manager instance
cache_manager = CacheManager()


def cache_result(
    cache_type: str = "default",
    ttl_override: Optional[int] = None,
    key_generator: Optional[Callable[..., str]] = None
):
    """
    Decorator for caching function results.
    
    Args:
        cache_type: Type of cache configuration to use
        ttl_override: Override default TTL
        key_generator: Custom key generator function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Generate cache key
            if key_generator:
                cache_key = key_generator(*args, **kwargs)
            else:
                # Default key generation
                func_name = func.__name__
                args_str = "_".join(str(arg)[:50] for arg in args)
                kwargs_str = "_".join(f"{k}:{str(v)[:50]}" for k, v in kwargs.items())
                cache_key = f"{CacheKeyGenerator.PREFIX}:func:{func_name}:{args_str}:{kwargs_str}"
            
            # Try to get from cache
            cached_result = await cache_manager.get(cache_key, cache_type)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            await cache_manager.set(cache_key, result, cache_type, ttl_override)
            
            return result
        
        return wrapper
    return decorator


# Cache invalidation utilities
class CacheInvalidator:
    """Utilities for cache invalidation strategies."""
    
    @staticmethod
    async def invalidate_model_cache(model_id: Optional[str] = None):
        """Invalidate model-related cache entries."""
        if model_id:
            # Invalidate specific model
            await cache_manager.delete(CacheKeyGenerator.model_catalog(model_id), "model_catalog")
        else:
            # Invalidate all model cache
            await cache_manager.invalidate_pattern(f"{CacheKeyGenerator.PREFIX}:model*")
            await cache_manager.invalidate_pattern(f"{CacheKeyGenerator.PREFIX}:models*")
    
    @staticmethod
    async def invalidate_settings_cache(key: Optional[str] = None, workspace_id: Optional[str] = None):
        """Invalidate settings-related cache entries."""
        if key:
            await cache_manager.delete(CacheKeyGenerator.global_settings(key), "global_settings")
        elif workspace_id:
            await cache_manager.delete(CacheKeyGenerator.workspace_settings(workspace_id), "workspace_settings")
        else:
            await cache_manager.invalidate_pattern(f"{CacheKeyGenerator.PREFIX}:settings*")
    
    @staticmethod
    async def invalidate_api_key_cache(api_key_id: str):
        """Invalidate API key related cache entries."""
        await cache_manager.delete(CacheKeyGenerator.api_key_settings(api_key_id), "api_key_settings")
        await cache_manager.invalidate_pattern(f"{CacheKeyGenerator.PREFIX}:api_key:{api_key_id}*")


# Export main components
__all__ = [
    "CacheManager",
    "CacheKeyGenerator", 
    "CacheInvalidator",
    "cache_manager",
    "cache_result",
    "CacheConfig",
    "CacheLayer"
]