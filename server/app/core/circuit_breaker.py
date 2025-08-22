"""
Circuit breaker pattern implementation for external API calls.

This module provides circuit breaker functionality to prevent cascading failures
when external services (like OpenRouter) become unavailable or slow.
"""
import time
import asyncio
from enum import Enum
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import structlog

from app.core.config import settings

# Import telemetry functions
try:
    from app.telemetry.otel import (
        update_circuit_breaker_state,
        record_circuit_breaker_operation
    )
except ImportError:
    # Fallback functions if telemetry is not available
    def update_circuit_breaker_state(name: str, state: str) -> None:
        pass
    
    def record_circuit_breaker_operation(name: str, operation: str) -> None:
        pass


logger = structlog.get_logger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5          # Number of failures before opening
    recovery_timeout: float = 60.0      # Seconds before attempting recovery
    success_threshold: int = 3          # Successes needed to close from half-open
    timeout: float = 30.0               # Request timeout in seconds
    expected_exception: type = Exception # Exception type that triggers circuit breaker


@dataclass
class CircuitBreakerStats:
    """Circuit breaker statistics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeouts: int = 0
    circuit_breaker_opens: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    
    def __init__(self, message: str = "Circuit breaker is open", retry_after: Optional[float] = None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


class CircuitBreaker:
    """
    Circuit breaker implementation for external API calls.
    
    The circuit breaker has three states:
    - CLOSED: Normal operation, requests are allowed
    - OPEN: Circuit is open, requests fail fast
    - HALF_OPEN: Testing if the service has recovered
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function call with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
        
        Returns:
            Function result
        
        Raises:
            CircuitBreakerError: If circuit is open
            Original exception: If function fails when circuit is closed/half-open
        """
        async with self._lock:
            self.stats.total_requests += 1
            
            # Check if circuit should transition from OPEN to HALF_OPEN
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    logger.info(
                        "circuit_breaker_transitioning_to_half_open",
                        name=self.name,
                        failure_count=self.failure_count
                    )
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                else:
                    # Circuit is still open, fail fast
                    retry_after = self._get_retry_after()
                    logger.debug(
                        "circuit_breaker_open_fail_fast",
                        name=self.name,
                        retry_after=retry_after
                    )
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is open",
                        retry_after=retry_after
                    )
        
        # Execute the function call
        start_time = time.time()
        try:
            # Add timeout protection
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.config.timeout
            )
            
            # Record success
            await self._on_success()
            record_circuit_breaker_operation(self.name, "success")
            return result
            
        except asyncio.TimeoutError:
            self.stats.timeouts += 1
            logger.warning(
                "circuit_breaker_timeout",
                name=self.name,
                timeout=self.config.timeout,
                duration=time.time() - start_time
            )
            await self._on_failure()
            record_circuit_breaker_operation(self.name, "timeout")
            raise
            
        except self.config.expected_exception as e:
            logger.warning(
                "circuit_breaker_expected_failure",
                name=self.name,
                exception=str(e),
                duration=time.time() - start_time
            )
            await self._on_failure()
            record_circuit_breaker_operation(self.name, "failure")
            raise
            
        except Exception as e:
            logger.error(
                "circuit_breaker_unexpected_failure",
                name=self.name,
                exception=str(e),
                duration=time.time() - start_time
            )
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """Handle successful function execution."""
        async with self._lock:
            self.stats.successful_requests += 1
            self.stats.last_success_time = datetime.utcnow()
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                logger.debug(
                    "circuit_breaker_half_open_success",
                    name=self.name,
                    success_count=self.success_count,
                    threshold=self.config.success_threshold
                )
                
                if self.success_count >= self.config.success_threshold:
                    # Reset circuit breaker to CLOSED state
                    logger.info(
                        "circuit_breaker_closing",
                        name=self.name,
                        success_count=self.success_count
                    )
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    update_circuit_breaker_state(self.name, "closed")
            elif self.state == CircuitBreakerState.CLOSED:
                # Reset failure count on success in CLOSED state
                self.failure_count = 0
    
    async def _on_failure(self):
        """Handle failed function execution."""
        async with self._lock:
            self.stats.failed_requests += 1
            self.stats.last_failure_time = datetime.utcnow()
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            logger.debug(
                "circuit_breaker_failure",
                name=self.name,
                failure_count=self.failure_count,
                threshold=self.config.failure_threshold,
                state=self.state.value
            )
            
            # Check if we should open the circuit
            if (self.state == CircuitBreakerState.CLOSED and 
                self.failure_count >= self.config.failure_threshold):
                
                logger.error(
                    "circuit_breaker_opening",
                    name=self.name,
                    failure_count=self.failure_count,
                    threshold=self.config.failure_threshold
                )
                
                self.state = CircuitBreakerState.OPEN
                self.stats.circuit_breaker_opens += 1
                update_circuit_breaker_state(self.name, "open")
                record_circuit_breaker_operation(self.name, "open")
                
            elif self.state == CircuitBreakerState.HALF_OPEN:
                # Failure in HALF_OPEN state, back to OPEN
                logger.warning(
                    "circuit_breaker_half_open_failure_back_to_open",
                    name=self.name
                )
                self.state = CircuitBreakerState.OPEN
                self.success_count = 0
    
    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should transition from OPEN to HALF_OPEN."""
        if self.last_failure_time is None:
            return True
        
        return (time.time() - self.last_failure_time) >= self.config.recovery_timeout
    
    def _get_retry_after(self) -> Optional[float]:
        """Get retry after time for open circuit."""
        if self.last_failure_time is None:
            return None
        
        elapsed = time.time() - self.last_failure_time
        return max(0, self.config.recovery_timeout - elapsed)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "stats": {
                "total_requests": self.stats.total_requests,
                "successful_requests": self.stats.successful_requests,
                "failed_requests": self.stats.failed_requests,
                "timeouts": self.stats.timeouts,
                "circuit_breaker_opens": self.stats.circuit_breaker_opens,
                "success_rate": (
                    self.stats.successful_requests / self.stats.total_requests * 100
                    if self.stats.total_requests > 0 else 0
                ),
                "last_failure_time": (
                    self.stats.last_failure_time.isoformat()
                    if self.stats.last_failure_time else None
                ),
                "last_success_time": (
                    self.stats.last_success_time.isoformat()
                    if self.stats.last_success_time else None
                )
            }
        }


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""
    
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
    
    def get_or_create(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        """Get existing circuit breaker or create a new one."""
        if name not in self._breakers:
            if config is None:
                config = CircuitBreakerConfig()
            self._breakers[name] = CircuitBreaker(name, config)
            logger.info("circuit_breaker_created", name=name)
        
        return self._breakers[name]
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all circuit breakers."""
        return {
            name: breaker.get_stats() 
            for name, breaker in self._breakers.items()
        }
    
    def reset_all(self):
        """Reset all circuit breakers to CLOSED state."""
        for breaker in self._breakers.values():
            breaker.state = CircuitBreakerState.CLOSED
            breaker.failure_count = 0
            breaker.success_count = 0
        logger.info("all_circuit_breakers_reset")


# Global circuit breaker registry
circuit_breaker_registry = CircuitBreakerRegistry()


def get_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """Get a circuit breaker by name."""
    return circuit_breaker_registry.get_or_create(name, config)