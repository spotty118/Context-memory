"""
Comprehensive tests for concurrent rate limiting and failure scenarios.
"""
import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock

from app.core.ratelimit import TokenBucket, check_rpm, check_rph, get_rate_limit_status
from app.db.models import APIKey
from fastapi import HTTPException


@pytest.mark.asyncio
class TestConcurrentRateLimiting:
    """Test rate limiting under concurrent access patterns."""
    
    def create_test_api_key(self, rpm_limit=50):
        """Create a test API key for concurrent testing."""
        return APIKey(
            key_hash="concurrent_test_hash",
            workspace_id="concurrent_workspace",
            name="Concurrent Test Key",
            active=True,
            rpm_limit=rpm_limit
        )
    
    async def test_concurrent_rpm_checks(self):
        """Test concurrent RPM checks from the same API key."""
        api_key = self.create_test_api_key(rpm_limit=100)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Create outcomes for concurrent requests
            # First 80 should succeed, next 20 should fail
            successful_outcomes = [[1, 100-i] for i in range(1, 81)]  # 80 successes
            failed_outcomes = [[0, 20] for _ in range(20)]  # 20 failures
            
            mock_redis.eval.side_effect = successful_outcomes + failed_outcomes
            
            # Create 100 concurrent tasks
            tasks = [check_rpm(api_key, 1) for _ in range(100)]
            
            # Execute all tasks
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count results
            successes = sum(1 for r in results if not isinstance(r, Exception))
            failures = sum(1 for r in results if isinstance(r, HTTPException))
            
            assert successes == 80
            assert failures == 20
    
    async def test_concurrent_different_api_keys(self):
        """Test concurrent requests from different API keys."""
        api_key1 = APIKey(
            key_hash="key1_hash",
            workspace_id="workspace1",
            name="Key 1",
            active=True,
            rpm_limit=10
        )
        
        api_key2 = APIKey(
            key_hash="key2_hash",
            workspace_id="workspace2",
            name="Key 2",
            active=True,
            rpm_limit=20
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Both keys should succeed independently
            mock_redis.eval.return_value = [1, 5]  # Always succeed
            
            # Create tasks for both keys
            tasks = []
            for _ in range(5):
                tasks.append(check_rpm(api_key1, 1))
                tasks.append(check_rpm(api_key2, 1))
            
            # All should succeed since they're independent buckets
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # All should succeed
            assert all(not isinstance(r, Exception) for r in results)
    
    async def test_thundering_herd_scenario(self):
        """Test handling of thundering herd scenarios."""
        api_key = self.create_test_api_key(rpm_limit=1)  # Very low limit
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Only first request succeeds, rest fail
            outcomes = [[1, 0]] + [[0, 0] for _ in range(49)]  # 1 success, 49 failures
            mock_redis.eval.side_effect = outcomes
            
            # Create many concurrent requests (thundering herd)
            tasks = [check_rpm(api_key, 1) for _ in range(50)]
            
            # Execute all at once
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Only one should succeed
            successes = sum(1 for r in results if not isinstance(r, Exception))
            failures = sum(1 for r in results if isinstance(r, HTTPException))
            
            assert successes == 1
            assert failures == 49
    
    async def test_mixed_request_sizes_concurrent(self):
        """Test concurrent requests with different token consumption."""
        api_key = self.create_test_api_key(rpm_limit=100)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate mixed request outcomes
            # Large request (50 tokens), several small ones (1 token each)
            outcomes = [
                [1, 50],  # Large request succeeds, 50 remaining
                [1, 49], [1, 48], [1, 47], [1, 46], [1, 45],  # 5 small requests
                [0, 45]  # Next request fails
            ]
            mock_redis.eval.side_effect = outcomes
            
            # Create mixed tasks
            tasks = [
                check_rpm(api_key, 50),  # One large request
                *[check_rpm(api_key, 1) for _ in range(6)]  # Six small requests
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 6 should succeed (1 large + 5 small), 1 should fail
            successes = sum(1 for r in results if not isinstance(r, Exception))
            failures = sum(1 for r in results if isinstance(r, HTTPException))
            
            assert successes == 6
            assert failures == 1


@pytest.mark.asyncio
class TestRateLimitStatusAndHeaders:
    """Test rate limit status reporting and HTTP headers."""
    
    def create_test_api_key(self, rpm_limit=30):
        """Create a test API key."""
        return APIKey(
            key_hash="status_test_hash",
            workspace_id="status_workspace",
            name="Status Test Key",
            active=True,
            rpm_limit=rpm_limit
        )
    
    async def test_rate_limit_status_reporting(self):
        """Test rate limit status reporting functionality."""
        api_key = self.create_test_api_key(rpm_limit=60)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Mock status for both RPM and RPH buckets
            current_time = time.time()
            status_responses = [
                [30, current_time - 10],  # RPM bucket: 30 tokens, last refill 10s ago
                [1800, current_time - 300]  # RPH bucket: 1800 tokens, last refill 5m ago
            ]
            mock_redis.hmget.side_effect = status_responses
            
            status = await get_rate_limit_status(api_key)
            
            assert status["rpm"]["limit"] == 60
            assert status["rpm"]["remaining"] == 30
            assert status["rph"]["limit"] == 3600  # 60 * 60
            assert status["rph"]["remaining"] == 1800
            assert "reset_at" in status["rpm"]
            assert "reset_at" in status["rph"]
    
    async def test_rate_limit_headers_on_failure(self):
        """Test rate limit headers on rate limit exceeded."""
        api_key = self.create_test_api_key(rpm_limit=10)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Rate limit exceeded
            mock_redis.eval.return_value = [0, 0]
            
            with pytest.raises(HTTPException) as exc_info:
                await check_rpm(api_key, 1)
            
            headers = exc_info.value.headers
            assert headers["X-RateLimit-Limit"] == "10"
            assert headers["X-RateLimit-Remaining"] == "0"
            assert "X-RateLimit-Reset" in headers
            assert headers["Retry-After"] == "60"
    
    async def test_rate_limit_status_with_no_prior_usage(self):
        """Test rate limit status when no prior usage exists."""
        api_key = self.create_test_api_key(rpm_limit=50)
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # No prior usage (returns None values)
            mock_redis.hmget.side_effect = [[None, None], [None, None]]
            
            status = await get_rate_limit_status(api_key)
            
            # Should default to full capacity
            assert status["rpm"]["limit"] == 50
            assert status["rpm"]["remaining"] == 50  # Default to capacity
            assert status["rph"]["limit"] == 3000  # 50 * 60
            assert status["rph"]["remaining"] == 3000


@pytest.mark.asyncio 
class TestRateLimitRedisFailureScenarios:
    """Test rate limiting behavior when Redis is unavailable."""
    
    def create_test_api_key(self):
        """Create a test API key."""
        return APIKey(
            key_hash="redis_fail_test",
            workspace_id="test_workspace",
            name="Redis Fail Test",
            active=True,
            rpm_limit=10
        )
    
    async def test_redis_connection_failure(self):
        """Test behavior when Redis connection fails."""
        api_key = self.create_test_api_key()
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            # Simulate Redis connection failure
            mock_get_redis.side_effect = Exception("Redis connection failed")
            
            # Should raise an exception (fail-safe approach)
            with pytest.raises(Exception):
                await check_rpm(api_key, 1)
    
    async def test_redis_script_execution_failure(self):
        """Test behavior when Redis Lua script execution fails."""
        api_key = self.create_test_api_key()
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate script execution failure
            mock_redis.eval.side_effect = Exception("Script execution failed")
            
            with pytest.raises(Exception):
                await check_rpm(api_key, 1)
    
    async def test_redis_timeout_scenario(self):
        """Test behavior when Redis operations timeout."""
        api_key = self.create_test_api_key()
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Simulate timeout
            mock_redis.eval.side_effect = asyncio.TimeoutError("Redis timeout")
            
            with pytest.raises(asyncio.TimeoutError):
                await check_rpm(api_key, 1)


@pytest.mark.asyncio
class TestRateLimitingWithDifferentConfigurations:
    """Test rate limiting with various configuration scenarios."""
    
    async def test_default_settings_fallback(self):
        """Test rate limiting with default settings when API key has no limits."""
        api_key = APIKey(
            key_hash="default_test",
            workspace_id="test_workspace", 
            name="Default Test",
            active=True,
            rpm_limit=None  # No specific limit, should use defaults
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis, \
             patch('app.core.config.settings') as mock_settings:
            
            mock_settings.RATE_LIMIT_REQUESTS = 100
            mock_settings.RATE_LIMIT_WINDOW = 60
            
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            mock_redis.eval.return_value = [1, 99]
            
            # Should use default settings
            await check_rpm(api_key, 1)
            
            # Verify the bucket was configured with defaults
            mock_redis.eval.assert_called_once()
            call_args = mock_redis.eval.call_args[0]
            assert call_args[2] == 100  # capacity
            assert call_args[3] == 100  # refill_rate
            assert call_args[4] == 60   # window_seconds
    
    async def test_hourly_vs_minute_rate_limits(self):
        """Test that hourly and minute rate limits work independently."""
        api_key = APIKey(
            key_hash="hourly_test",
            workspace_id="test_workspace",
            name="Hourly Test",
            active=True,
            rpm_limit=10  # 10 per minute = 600 per hour
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Test minute limit first
            mock_redis.eval.return_value = [1, 9]  # Success, 9 remaining
            await check_rpm(api_key, 1)
            
            # Test hourly limit separately
            mock_redis.eval.return_value = [1, 599]  # Success, 599 remaining
            await check_rph(api_key, 1)
    
    async def test_edge_case_api_key_configurations(self):
        """Test edge cases in API key configurations."""
        
        # Test very high limit
        high_limit_key = APIKey(
            key_hash="high_limit",
            workspace_id="test_workspace",
            name="High Limit Key",
            active=True,
            rpm_limit=999999
        )
        
        # Test very low limit
        low_limit_key = APIKey(
            key_hash="low_limit",
            workspace_id="test_workspace",
            name="Low Limit Key", 
            active=True,
            rpm_limit=1
        )
        
        with patch('app.core.ratelimit.get_redis') as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # High limit should work normally
            mock_redis.eval.return_value = [1, 999998]
            await check_rpm(high_limit_key, 1)
            
            # Low limit should also work but be restrictive
            mock_redis.eval.return_value = [1, 0]  # Last token
            await check_rpm(low_limit_key, 1)
            
            # Next request on low limit should fail
            mock_redis.eval.return_value = [0, 0]
            with pytest.raises(HTTPException):
                await check_rpm(low_limit_key, 1)