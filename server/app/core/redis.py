"""
Redis client management for Context Memory Gateway.
Provides shared Redis connection pool for caching, queues, and session management.
"""
import redis.asyncio as redis
from typing import Optional
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# Global Redis client instance
_redis_client: Optional[redis.Redis] = None

async def get_redis_client() -> redis.Redis:
    """
    Get Redis client with connection pooling.
    
    Returns:
        Redis client instance with connection pool
    """
    global _redis_client
    
    if _redis_client is None:
        settings = get_settings()
        try:
            _redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=50,  # Increased for better concurrency
                retry_on_timeout=True,
                retry_on_error=[redis.ConnectionError, redis.TimeoutError],
                socket_connect_timeout=10,
                socket_timeout=30,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30
            )
            # Test the connection
            await _redis_client.ping()
            logger.info("redis_client_connected", url=settings.REDIS_URL)
        except Exception as e:
            logger.exception("redis_connection_failed", url=settings.REDIS_URL)
            raise e
    
    return _redis_client

async def close_redis_client():
    """Close Redis client connection."""
    global _redis_client
    if _redis_client:
        try:
            await _redis_client.aclose()
            logger.info("redis_client_closed")
        except Exception as e:
            logger.exception("redis_client_close_error")
        finally:
            _redis_client = None

async def health_check() -> dict:
    """
    Perform Redis health check.
    
    Returns:
        Health status dictionary
    """
    try:
        client = await get_redis_client()
        await client.ping()
        info = await client.info("server")
        
        return {
            "status": "healthy",
            "connected": True,
            "redis_version": info.get("redis_version", "unknown"),
            "uptime_seconds": info.get("uptime_in_seconds", 0)
        }
    except Exception as e:
        logger.exception("redis_health_check_failed")
        return {
            "status": "unhealthy",
            "connected": False,
            "error": str(e)
        }
