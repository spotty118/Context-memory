"""
Unit tests for circuit breaker implementation.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.core.circuit_breaker import (
    CircuitBreaker, 
    CircuitBreakerConfig, 
    CircuitBreakerState, 
    CircuitBreakerError,
    CircuitBreakerRegistry,
    get_circuit_breaker
)


@pytest.fixture
def circuit_breaker():
    """Create a circuit breaker for testing."""
    config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=1.0,
        success_threshold=2,
        timeout=0.5,
        expected_exception=Exception
    )
    return CircuitBreaker("test_service", config)


@pytest.fixture
def mock_function():
    """Create a mock async function."""
    return AsyncMock()


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_state_success(self, circuit_breaker, mock_function):
        """Test successful requests in closed state."""
        mock_function.return_value = "success"
        
        result = await circuit_breaker.call(mock_function)
        
        assert result == "success"
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.failure_count == 0
        assert circuit_breaker.stats.successful_requests == 1
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_in_closed_state(self, circuit_breaker, mock_function):
        """Test failure handling in closed state."""
        mock_function.side_effect = Exception("test error")
        
        with pytest.raises(Exception):
            await circuit_breaker.call(mock_function)
            
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.failure_count == 1
        assert circuit_breaker.stats.failed_requests == 1
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failure_threshold(self, circuit_breaker, mock_function):
        """Test circuit breaker opens when failure threshold is reached."""
        mock_function.side_effect = Exception("test error")
        
        # Trigger failures up to threshold
        for _ in range(circuit_breaker.config.failure_threshold):
            with pytest.raises(Exception):
                await circuit_breaker.call(mock_function)
        
        # Circuit should now be open
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        assert circuit_breaker.failure_count == circuit_breaker.config.failure_threshold
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_rejects_requests_when_open(self, circuit_breaker, mock_function):
        """Test circuit breaker rejects requests when open."""
        # Force circuit breaker to open state
        circuit_breaker.state = CircuitBreakerState.OPEN
        circuit_breaker.failure_count = circuit_breaker.config.failure_threshold
        circuit_breaker.last_failure_time = asyncio.get_event_loop().time()
        
        mock_function.return_value = "success"
        
        with pytest.raises(CircuitBreakerError) as exc_info:
            await circuit_breaker.call(mock_function)
            
        assert "Circuit breaker 'test_service' is open" in str(exc_info.value)
        # Function should not have been called
        mock_function.assert_not_called()
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_transitions_to_half_open(self, circuit_breaker, mock_function):
        """Test circuit breaker transitions from open to half-open after recovery timeout."""
        # Force circuit breaker to open state
        circuit_breaker.state = CircuitBreakerState.OPEN
        circuit_breaker.failure_count = circuit_breaker.config.failure_threshold
        circuit_breaker.last_failure_time = asyncio.get_event_loop().time() - circuit_breaker.config.recovery_timeout - 0.1
        
        mock_function.return_value = "success"
        
        result = await circuit_breaker.call(mock_function)
        
        assert result == "success"
        assert circuit_breaker.state == CircuitBreakerState.HALF_OPEN
        assert circuit_breaker.success_count == 1
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_closes_from_half_open_on_success(self, circuit_breaker, mock_function):
        """Test circuit breaker closes from half-open after enough successes."""
        # Set to half-open state
        circuit_breaker.state = CircuitBreakerState.HALF_OPEN
        circuit_breaker.success_count = circuit_breaker.config.success_threshold - 1
        
        mock_function.return_value = "success"
        
        result = await circuit_breaker.call(mock_function)
        
        assert result == "success"
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.failure_count == 0
        assert circuit_breaker.success_count == 0
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_from_half_open_on_failure(self, circuit_breaker, mock_function):
        """Test circuit breaker opens from half-open on failure."""
        # Set to half-open state
        circuit_breaker.state = CircuitBreakerState.HALF_OPEN
        circuit_breaker.success_count = 1
        
        mock_function.side_effect = Exception("test error")
        
        with pytest.raises(Exception):
            await circuit_breaker.call(mock_function)
            
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        assert circuit_breaker.success_count == 0
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_timeout_handling(self, circuit_breaker):
        """Test circuit breaker handles timeouts correctly."""
        # Mock function that takes longer than timeout
        async def slow_function():
            await asyncio.sleep(circuit_breaker.config.timeout + 0.1)
            return "should not complete"
        
        with pytest.raises(asyncio.TimeoutError):
            await circuit_breaker.call(slow_function)
            
        assert circuit_breaker.stats.timeouts == 1
        assert circuit_breaker.failure_count == 1
        
    def test_circuit_breaker_get_stats(self, circuit_breaker):
        """Test circuit breaker statistics reporting."""
        stats = circuit_breaker.get_stats()
        
        assert stats["name"] == "test_service"
        assert stats["state"] == CircuitBreakerState.CLOSED.value
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0
        assert "stats" in stats
        assert "total_requests" in stats["stats"]
        assert "successful_requests" in stats["stats"]
        assert "failed_requests" in stats["stats"]


class TestCircuitBreakerRegistry:
    """Test circuit breaker registry functionality."""
    
    def test_registry_get_or_create(self):
        """Test registry creates and retrieves circuit breakers."""
        registry = CircuitBreakerRegistry()
        
        # First call should create
        breaker1 = registry.get_or_create("test_service")
        assert breaker1.name == "test_service"
        
        # Second call should retrieve same instance
        breaker2 = registry.get_or_create("test_service")
        assert breaker1 is breaker2
        
    def test_registry_get_all_stats(self):
        """Test registry returns stats for all circuit breakers."""
        registry = CircuitBreakerRegistry()
        
        breaker1 = registry.get_or_create("service1")
        breaker2 = registry.get_or_create("service2")
        
        stats = registry.get_all_stats()
        
        assert len(stats) == 2
        assert "service1" in stats
        assert "service2" in stats
        assert stats["service1"]["name"] == "service1"
        assert stats["service2"]["name"] == "service2"
        
    def test_registry_reset_all(self):
        """Test registry can reset all circuit breakers."""
        registry = CircuitBreakerRegistry()
        
        # Create and modify circuit breakers
        breaker1 = registry.get_or_create("service1")
        breaker2 = registry.get_or_create("service2")
        
        breaker1.state = CircuitBreakerState.OPEN
        breaker1.failure_count = 5
        breaker2.state = CircuitBreakerState.HALF_OPEN
        breaker2.success_count = 2
        
        # Reset all
        registry.reset_all()
        
        assert breaker1.state == CircuitBreakerState.CLOSED
        assert breaker1.failure_count == 0
        assert breaker1.success_count == 0
        assert breaker2.state == CircuitBreakerState.CLOSED
        assert breaker2.failure_count == 0
        assert breaker2.success_count == 0


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration functions."""
    
    def test_get_circuit_breaker_creates_with_default_config(self):
        """Test get_circuit_breaker creates circuit breaker with default config."""
        breaker = get_circuit_breaker("integration_test")
        
        assert breaker.name == "integration_test"
        assert isinstance(breaker.config, CircuitBreakerConfig)
        
    def test_get_circuit_breaker_with_custom_config(self):
        """Test get_circuit_breaker creates circuit breaker with custom config."""
        custom_config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=120.0,
            success_threshold=5,
            timeout=60.0
        )
        
        breaker = get_circuit_breaker("custom_test", custom_config)
        
        assert breaker.name == "custom_test"
        assert breaker.config.failure_threshold == 10
        assert breaker.config.recovery_timeout == 120.0
        assert breaker.config.success_threshold == 5
        assert breaker.config.timeout == 60.0


@pytest.mark.asyncio
async def test_circuit_breaker_real_world_scenario():
    """Test circuit breaker in a realistic failure recovery scenario."""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout=0.1,  # Short timeout for fast test
        success_threshold=2,
        timeout=0.5
    )
    circuit_breaker = CircuitBreaker("real_world_test", config)
    
    # Mock service that initially fails
    call_count = 0
    async def unreliable_service():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("Service unavailable")
        return f"success_{call_count}"
    
    # Phase 1: Service failures - circuit should open
    with pytest.raises(Exception):
        await circuit_breaker.call(unreliable_service)
    with pytest.raises(Exception):
        await circuit_breaker.call(unreliable_service)
    
    assert circuit_breaker.state == CircuitBreakerState.OPEN
    
    # Phase 2: Circuit open - requests should be rejected
    with pytest.raises(CircuitBreakerError):
        await circuit_breaker.call(unreliable_service)
    
    # Service hasn't been called again
    assert call_count == 2
    
    # Phase 3: Wait for recovery timeout
    await asyncio.sleep(0.2)
    
    # Phase 4: Service recovery - circuit should close after success threshold
    result1 = await circuit_breaker.call(unreliable_service)
    assert result1 == "success_3"
    assert circuit_breaker.state == CircuitBreakerState.HALF_OPEN
    
    result2 = await circuit_breaker.call(unreliable_service)
    assert result2 == "success_4"
    assert circuit_breaker.state == CircuitBreakerState.CLOSED
    
    # Phase 5: Normal operation
    result3 = await circuit_breaker.call(unreliable_service)
    assert result3 == "success_5"
    assert circuit_breaker.state == CircuitBreakerState.CLOSED