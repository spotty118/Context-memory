"""
Comprehensive tests for rate limiting edge cases, boundaries, and concurrent access.
"""
import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.ratelimit import TokenBucket, check_rpm, check_rph, get_rate_limit_status
from app.core.exceptions import RateLimitExceededError
from app.db.models import APIKey
from fastapi import HTTPException


@pytest.mark.asyncio
class TestTokenBucketEdgeCases:
    """Test TokenBucket implementation edge cases and boundaries."""
    
    async def test_token_bucket_initialization(self):
        """Test token bucket initialization with various parameters."""
        bucket = TokenBucket(
            key="test_key",
            capacity=100,
            refill_rate=50,
            window_seconds=60
        )
        
        assert bucket.key == "rate_limit:test_key"
        assert bucket.capacity == 100
        assert bucket.refill_rate == 50
        assert bucket.window_seconds == 60
    
    async def test_token_bucket_zero_capacity(self):
        """Test token bucket with zero capacity."""
        bucket = TokenBucket(
            key="zero_capacity",
            capacity=0,
            refill_rate=10,
            window_seconds=60
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Zero capacity should never allow consumption
            mock_redis.eval.return_value = [0, 0]  # Not allowed, 0 remaining
            
            result = await bucket.consume(1)
            assert result is False
    
    async def test_token_bucket_exact_capacity_consumption(self):
        """Test consuming exactly the bucket capacity."""
        bucket = TokenBucket(
            key="exact_capacity",
            capacity=10,
            refill_rate=10,
            window_seconds=60
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # First consumption of exactly capacity should succeed
            mock_redis.eval.return_value = [1, 0]  # Allowed, 0 remaining
            result = await bucket.consume(10)
            assert result is True
            
            # Next consumption should fail
            mock_redis.eval.return_value = [0, 0]  # Not allowed, 0 remaining
            result = await bucket.consume(1)
            assert result is False
    
    async def test_token_bucket_over_capacity_consumption(self):
        """Test consuming more tokens than bucket capacity."""
        bucket = TokenBucket(
            key="over_capacity",
            capacity=10,
            refill_rate=10,
            window_seconds=60
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Requesting more than capacity should fail
            mock_redis.eval.return_value = [0, 10]  # Not allowed, 10 remaining
            result = await bucket.consume(15)
            assert result is False
    
    async def test_token_bucket_concurrent_access(self):
        """Test token bucket under concurrent access."""
        bucket = TokenBucket(
            key="concurrent_test",
            capacity=100,
            refill_rate=100,
            window_seconds=60
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate different outcomes for concurrent requests
            outcomes = [
                [1, 99], [1, 98], [1, 97], [1, 96], [1, 95],  # 5 successes
                [0, 95], [0, 95], [0, 95]  # 3 failures
            ]
            mock_redis.eval.side_effect = outcomes
            
            # Run concurrent requests
            tasks = [bucket.consume(1) for _ in range(8)]
            results = await asyncio.gather(*tasks)
            
            # Should have 5 successes and 3 failures
            assert sum(results) == 5
            assert results.count(False) == 3


@pytest.mark.asyncio
class TestRateLimitBoundaryConditions:
    """Test rate limiting boundary conditions and edge cases."""
    
    def create_test_api_key(self, rpm_limit=None):
        """Create a test API key with specified limits."""
        return APIKey(
            key_hash="test_hash_123",
            workspace_id="test_workspace",
            name="Test Key",
            active=True,
            rpm_limit=rpm_limit
        )
    
    async def test_rpm_limit_boundary_exact_limit(self):
        """Test hitting exactly the RPM limit."""
        api_key = self.create_test_api_key(rpm_limit=10)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate consuming exactly the limit
            mock_redis.eval.return_value = [1, 0]  # Last token consumed
            
            # This should succeed (10th request in the window)
            await check_rpm(api_key, 1)
            
            # Next request should fail
            mock_redis.eval.return_value = [0, 0]  # No tokens left
            
            with pytest.raises(HTTPException) as exc_info:
                await check_rpm(api_key, 1)
            
            assert exc_info.value.status_code == 429
            assert "Rate limit exceeded" in exc_info.value.detail
    
    async def test_rpm_limit_boundary_over_limit(self):
        """Test exceeding RPM limit by one request."""
        api_key = self.create_test_api_key(rpm_limit=5)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate no tokens available
            mock_redis.eval.return_value = [0, 0]
            
            with pytest.raises(HTTPException) as exc_info:
                await check_rpm(api_key, 1)
            
            assert exc_info.value.status_code == 429
            assert "Maximum 5 requests per minute" in exc_info.value.detail
            assert exc_info.value.headers["X-RateLimit-Limit"] == "5"
            assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"
            assert "Retry-After" in exc_info.value.headers
    
    async def test_zero_rpm_limit(self):
        """Test API key with zero RPM limit."""
        api_key = self.create_test_api_key(rpm_limit=0)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Zero limit should always fail
            mock_redis.eval.return_value = [0, 0]
            
            with pytest.raises(HTTPException) as exc_info:
                await check_rpm(api_key, 1)
            
            assert exc_info.value.status_code == 429
            assert "Maximum 0 requests per minute" in exc_info.value.detail
    
    async def test_bulk_request_consumption(self):
        """Test consuming multiple requests at once."""
        api_key = self.create_test_api_key(rpm_limit=100)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Test consuming multiple requests
            mock_redis.eval.return_value = [1, 85]  # 15 tokens consumed
            await check_rpm(api_key, 15)
            
            # Test consuming more than remaining
            mock_redis.eval.return_value = [0, 85]  # Not enough tokens
            
            with pytest.raises(HTTPException):
                await check_rpm(api_key, 90)


@pytest.mark.asyncio
class TestRateLimitResetScenarios:
    """Test rate limit reset scenarios and timing."""
    
    def create_test_api_key(self, rpm_limit=10):
        """Create a test API key."""
        return APIKey(
            key_hash="reset_test_hash",
            workspace_id="test_workspace",
            name="Reset Test Key",
            active=True,
            rpm_limit=rpm_limit
        )
    
    async def test_rate_limit_reset_after_window(self):
        """Test rate limit reset after time window expires."""
        api_key = self.create_test_api_key(rpm_limit=5)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # First: exhaust the limit
            mock_redis.eval.return_value = [0, 0]  # No tokens left
            
            with pytest.raises(HTTPException):
                await check_rpm(api_key, 1)
            
            # Simulate time passing and bucket refilling
            mock_redis.eval.return_value = [1, 4]  # Tokens available again
            
            # Should succeed after reset
            await check_rpm(api_key, 1)
    
    async def test_concurrent_reset_scenarios(self):
        """Test concurrent requests during reset periods."""
        api_key = self.create_test_api_key(rpm_limit=20)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate concurrent requests hitting the bucket at reset time
            outcomes = [
                [1, 19], [1, 18], [1, 17], [1, 16], [1, 15],  # First 5 succeed
                [0, 15], [0, 15], [0, 15]  # Next 3 fail (rate limited)
            ]
            mock_redis.eval.side_effect = outcomes
            
            tasks = []
            for _ in range(8):
                tasks.append(check_rpm(api_key, 1))
            
            # Execute all tasks and count successes/failures
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            successes = sum(1 for r in results if not isinstance(r, Exception))
            failures = sum(1 for r in results if isinstance(r, HTTPException))
            
            assert successes == 5
            assert failures == 3