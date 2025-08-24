"""
Rate limiting module using Redis token bucket algorithm.
"""
import time
from typing import Optional
import redis.asyncio as redis
from fastapi import HTTPException
import structlog

from app.core.config import settings
from app.db.models import APIKey
from app.core.redis import get_redis_client


logger = structlog.get_logger(__name__)

# Use shared Redis client from core.redis
async def get_redis() -> redis.Redis:
    """Get Redis client instance from shared pool."""
    return await get_redis_client()


class TokenBucket:
    """Token bucket rate limiter implementation using Redis."""
    
    def __init__(self, key: str, capacity: int, refill_rate: int, window_seconds: int = 60):
        """
        Initialize token bucket.
        
        Args:
            key: Redis key for this bucket
            capacity: Maximum number of tokens
            refill_rate: Tokens added per window
            window_seconds: Time window in seconds
        """
        # Use hierarchical key naming per Redis best practices
        self.key = f"cmg:ratelimit:{key}"
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.window_seconds = window_seconds
    
    async def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            bool: True if tokens were consumed, False if rate limited
        """
        redis_client = await get_redis()
        current_time = time.time()
        
        # Lua script for atomic token bucket operation
        lua_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local window_seconds = tonumber(ARGV[3])
        local tokens_requested = tonumber(ARGV[4])
        local current_time = tonumber(ARGV[5])
        
        -- Get current bucket state
        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local current_tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or current_time
        
        -- Calculate tokens to add based on time elapsed
        local time_elapsed = current_time - last_refill
        local tokens_to_add = math.floor(time_elapsed / window_seconds * refill_rate)
        
        -- Refill tokens up to capacity
        current_tokens = math.min(capacity, current_tokens + tokens_to_add)
        
        -- Check if we have enough tokens
        if current_tokens >= tokens_requested then
            -- Consume tokens
            current_tokens = current_tokens - tokens_requested
            
            -- Update bucket state
            redis.call('HMSET', key, 
                'tokens', current_tokens, 
                'last_refill', current_time
            )
            redis.call('EXPIRE', key, window_seconds * 2)  -- Expire after 2 windows
            
            return {1, current_tokens}  -- Success
        else
            -- Update last_refill time even if we can't consume
            redis.call('HMSET', key, 
                'tokens', current_tokens, 
                'last_refill', current_time
            )
            redis.call('EXPIRE', key, window_seconds * 2)
            
            return {0, current_tokens}  -- Rate limited
        end
        """
        
        result = await redis_client.eval(
            lua_script,
            1,  # Number of keys
            self.key,
            self.capacity,
            self.refill_rate,
            self.window_seconds,
            tokens,
            current_time
        )
        
        success, remaining_tokens = result
        return bool(success)
    
    async def get_status(self) -> dict:
        """Get current bucket status."""
        redis_client = await get_redis()
        bucket = await redis_client.hmget(self.key, 'tokens', 'last_refill')
        
        current_tokens = int(bucket[0]) if bucket[0] else self.capacity
        last_refill = float(bucket[1]) if bucket[1] else time.time()
        
        return {
            'current_tokens': current_tokens,
            'capacity': self.capacity,
            'refill_rate': self.refill_rate,
            'last_refill': last_refill,
        }


async def check_rpm(api_key: APIKey, requests: int = 1) -> None:
    """
    Check rate limit for requests per minute.
    
    Args:
        api_key: API key record
        requests: Number of requests to consume (default 1)
        
    Raises:
        HTTPException: If rate limit exceeded
    """
    # Use per-key limit or global defaults
    rpm_limit = api_key.rpm_limit or settings.RATE_LIMIT_REQUESTS
    window_seconds = settings.RATE_LIMIT_WINDOW
    
    bucket = TokenBucket(
        key=f"rpm:{api_key.key_hash}",
        capacity=rpm_limit,
        refill_rate=rpm_limit,
        window_seconds=window_seconds
    )
    
    allowed = await bucket.consume(requests)
    
    if not allowed:
        status = await bucket.get_status()
        logger.warning(
            "rate_limit_exceeded",
            workspace_id=api_key.workspace_id,
            key_name=api_key.name,
            limit_type="rpm",
            limit=rpm_limit,
            current_tokens=status['current_tokens'],
        )
        
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {rpm_limit} requests per minute.",
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": str(rpm_limit),
                "X-RateLimit-Remaining": str(status['current_tokens']),
                "X-RateLimit-Reset": str(int(time.time() + 60)),
            }
        )
    
    logger.debug(
        "rate_limit_check_passed",
        workspace_id=api_key.workspace_id,
        key_name=api_key.name,
        limit_type="rpm",
        requests_consumed=requests,
    )


async def check_rph(api_key: APIKey, requests: int = 1) -> None:
    """
    Check rate limit for requests per hour.
    
    Args:
        api_key: API key record
        requests: Number of requests to consume (default 1)
        
    Raises:
        HTTPException: If rate limit exceeded
    """
    # Calculate hourly limit based on per-window RPM config
    rpm_limit = api_key.rpm_limit or settings.RATE_LIMIT_REQUESTS
    rph_limit = rpm_limit * 60
    
    bucket = TokenBucket(
        key=f"rph:{api_key.key_hash}",
        capacity=rph_limit,
        refill_rate=rph_limit,
        window_seconds=3600  # 1 hour
    )
    
    allowed = await bucket.consume(requests)
    
    if not allowed:
        status = await bucket.get_status()
        logger.warning(
            "rate_limit_exceeded",
            workspace_id=api_key.workspace_id,
            key_name=api_key.name,
            limit_type="rph",
            limit=rph_limit,
            current_tokens=status['current_tokens'],
        )
        
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {rph_limit} requests per hour.",
            headers={
                "Retry-After": "3600",
                "X-RateLimit-Limit": str(rph_limit),
                "X-RateLimit-Remaining": str(status['current_tokens']),
                "X-RateLimit-Reset": str(int(time.time() + 3600)),
            }
        )


async def get_rate_limit_status(api_key: APIKey) -> dict:
    """
    Get current rate limit status for an API key.
    
    Args:
        api_key: API key record
        
    Returns:
        dict: Rate limit status information
    """
    rpm_limit = api_key.rpm_limit or settings.RATE_LIMIT_REQUESTS
    rph_limit = rpm_limit * 60
    
    rpm_bucket = TokenBucket(
        key=f"rpm:{api_key.key_hash}",
        capacity=rpm_limit,
        refill_rate=rpm_limit,
        window_seconds=settings.RATE_LIMIT_WINDOW
    )
    
    rph_bucket = TokenBucket(
        key=f"rph:{api_key.key_hash}",
        capacity=rph_limit,
        refill_rate=rph_limit,
        window_seconds=3600
    )
    
    rpm_status = await rpm_bucket.get_status()
    rph_status = await rph_bucket.get_status()
    
    return {
        "rpm": {
            "limit": rpm_limit,
            "remaining": rpm_status['current_tokens'],
            "reset_at": int(rpm_status['last_refill'] + 60),
        },
        "rph": {
            "limit": rph_limit,
            "remaining": rph_status['current_tokens'],
            "reset_at": int(rph_status['last_refill'] + 3600),
        }
    }

