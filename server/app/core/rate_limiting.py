"""
Redis-backed rate limiting with token bucket algorithm.
"""
import time
import json
from typing import Optional
from fastapi import HTTPException, Request
import structlog
from app.core.redis import get_redis_client
from app.core.config import settings

logger = structlog.get_logger(__name__)


class TokenBucketRateLimiter:
    """Redis-backed token bucket rate limiter."""
    
    def __init__(self, redis_key_prefix: str = "rate_limit"):
        self.redis_key_prefix = redis_key_prefix
        
    def get_bucket_key(self, identifier: str, bucket_type: str = "requests") -> str:
        """Generate Redis key for rate limit bucket."""
        return f"{self.redis_key_prefix}:{bucket_type}:{identifier}"
    
    async def is_allowed(
        self,
        identifier: str,
        max_requests: int,
        window_seconds: int,
        bucket_type: str = "requests"
    ) -> tuple[bool, dict]:
        """
        Check if request is allowed using token bucket algorithm.
        
        Returns:
            tuple: (is_allowed, rate_limit_info)
        """
        redis_client = await get_redis_client()
        bucket_key = self.get_bucket_key(identifier, bucket_type)
        
        current_time = time.time()
        
        # Use Redis pipeline for atomicity
        pipe = redis_client.pipeline()
        
        try:
            # Get current bucket state
            bucket_data = await redis_client.get(bucket_key)
            
            if bucket_data:
                bucket = json.loads(bucket_data)
                tokens = bucket.get("tokens", max_requests)
                last_refill = bucket.get("last_refill", current_time)
            else:
                # Initialize new bucket
                tokens = max_requests
                last_refill = current_time
            
            # Calculate tokens to add based on time elapsed
            time_elapsed = current_time - last_refill
            tokens_to_add = (time_elapsed / window_seconds) * max_requests
            tokens = min(max_requests, tokens + tokens_to_add)
            
            # Check if request is allowed
            is_allowed = tokens >= 1
            
            if is_allowed:
                tokens -= 1
            
            # Update bucket state
            new_bucket = {
                "tokens": tokens,
                "last_refill": current_time,
                "requests": bucket.get("requests", 0) + (1 if is_allowed else 0),
                "last_request": current_time if is_allowed else bucket.get("last_request")
            }
            
            # Store updated bucket with expiration
            await redis_client.setex(
                bucket_key,
                window_seconds * 2,  # Keep data longer than window for analytics
                json.dumps(new_bucket)
            )
            
            rate_limit_info = {
                "allowed": is_allowed,
                "tokens_remaining": int(tokens),
                "max_requests": max_requests,
                "window_seconds": window_seconds,
                "reset_time": int(current_time + window_seconds),
                "requests_made": new_bucket["requests"]
            }
            
            return is_allowed, rate_limit_info
            
        except Exception as e:
            logger.exception("rate_limit_check_failed", identifier=identifier, error=str(e))
            # Fail open - allow request if Redis is down
            return True, {
                "allowed": True,
                "tokens_remaining": max_requests,
                "max_requests": max_requests,
                "window_seconds": window_seconds,
                "reset_time": int(current_time + window_seconds),
                "error": "rate_limit_unavailable"
            }


class APIRateLimiter:
    """API-specific rate limiter with different limits for different endpoints."""
    
    def __init__(self):
        self.token_bucket = TokenBucketRateLimiter("api_rate_limit")
    
    async def check_api_key_limit(
        self,
        api_key_hash: str,
        endpoint_category: str = "default"
    ) -> tuple[bool, dict]:
        """Check rate limit for API key."""
        
        # Get limits based on endpoint category
        limits = self.get_endpoint_limits(endpoint_category)
        
        identifier = f"api_key:{api_key_hash}"
        return await self.token_bucket.is_allowed(
            identifier,
            limits["requests_per_minute"],
            60,  # 1 minute window
            "api_requests"
        )
    
    async def check_ip_limit(
        self,
        client_ip: str,
        endpoint_category: str = "default"
    ) -> tuple[bool, dict]:
        """Check rate limit for IP address."""
        
        limits = self.get_endpoint_limits(endpoint_category)
        
        identifier = f"ip:{client_ip}"
        return await self.token_bucket.is_allowed(
            identifier,
            limits["requests_per_minute"] * 2,  # More lenient for IP-based limiting
            60,
            "ip_requests"
        )
    
    def get_endpoint_limits(self, category: str) -> dict:
        """Get rate limits based on endpoint category."""
        
        limits_config = {
            "llm_gateway": {
                "requests_per_minute": 30,
                "tokens_per_hour": 50000
            },
            "context_memory": {
                "requests_per_minute": 60,
                "items_per_hour": 1000
            },
            "admin": {
                "requests_per_minute": 120,
            },
            "default": {
                "requests_per_minute": settings.RATE_LIMIT_REQUESTS,
            }
        }
        
        return limits_config.get(category, limits_config["default"])


# Global rate limiter instance
api_rate_limiter = APIRateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware for FastAPI."""
    
    # Skip rate limiting for certain paths
    skip_paths = ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]
    if any(request.url.path.startswith(path) for path in skip_paths):
        return await call_next(request)
    
    client_ip = request.client.host if request.client else "unknown"
    
    # Determine endpoint category
    endpoint_category = "default"
    if request.url.path.startswith("/api/v1/llm") or request.url.path.startswith("/api/v2/llm"):
        endpoint_category = "llm_gateway"
    elif request.url.path.startswith("/api/v1/context") or request.url.path.startswith("/api/v2/context"):
        endpoint_category = "context_memory"
    elif request.url.path.startswith("/admin"):
        endpoint_category = "admin"
    
    # Check IP-based rate limit first (basic protection)
    ip_allowed, ip_info = await api_rate_limiter.check_ip_limit(client_ip, endpoint_category)
    
    if not ip_allowed:
        logger.warning(
            "ip_rate_limit_exceeded",
            client_ip=client_ip,
            endpoint=request.url.path,
            category=endpoint_category
        )
        
        raise HTTPException(
            status_code=429,
            detail="Too many requests from IP address",
            headers={
                "X-RateLimit-Limit": str(ip_info["max_requests"]),
                "X-RateLimit-Remaining": str(ip_info["tokens_remaining"]),
                "X-RateLimit-Reset": str(ip_info["reset_time"]),
                "Retry-After": str(ip_info["window_seconds"])
            }
        )
    
    # For API endpoints, also check API key rate limits
    if request.url.path.startswith("/api"):
        api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
        
        if api_key:
            # Hash the API key for privacy
            import hashlib
            api_key_hash = hashlib.sha256(f"{api_key}{settings.AUTH_API_KEY_SALT}".encode()).hexdigest()
            
            api_key_allowed, api_key_info = await api_rate_limiter.check_api_key_limit(
                api_key_hash,
                endpoint_category
            )
            
            if not api_key_allowed:
                logger.warning(
                    "api_key_rate_limit_exceeded",
                    api_key_hash=api_key_hash[:8] + "...",
                    endpoint=request.url.path,
                    category=endpoint_category
                )
                
                raise HTTPException(
                    status_code=429,
                    detail="API key rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(api_key_info["max_requests"]),
                        "X-RateLimit-Remaining": str(api_key_info["tokens_remaining"]),
                        "X-RateLimit-Reset": str(api_key_info["reset_time"]),
                        "Retry-After": str(api_key_info["window_seconds"])
                    }
                )
    
    # Add rate limit headers to response
    response = await call_next(request)
    
    # Add IP rate limit headers
    response.headers["X-RateLimit-IP-Limit"] = str(ip_info["max_requests"])
    response.headers["X-RateLimit-IP-Remaining"] = str(ip_info["tokens_remaining"])
    response.headers["X-RateLimit-IP-Reset"] = str(ip_info["reset_time"])
    
    return response
