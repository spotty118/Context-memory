"""
Redis-backed distributed circuit breaker for sharing state across multiple application instances.
"""
import asyncio
import json
import time
from typing import Optional, Dict, Any
from enum import Enum
import structlog
from app.core.redis import get_redis_client
from app.core.circuit_breaker import CircuitBreakerState, CircuitBreakerConfig

logger = structlog.get_logger(__name__)


class DistributedCircuitBreaker:
    """Circuit breaker with Redis-backed shared state for distributed deployments."""
    
    def __init__(self, name: str, config: CircuitBreakerConfig, redis_key_prefix: str = "circuit_breaker"):
        self.name = name
        self.config = config
        self.redis_key = f"{redis_key_prefix}:{name}"
        self.heartbeat_key = f"{redis_key_prefix}:{name}:heartbeat"
        self.local_state = CircuitBreakerState.CLOSED
        self._lock = asyncio.Lock()
        
    async def get_state(self) -> Dict[str, Any]:
        """Get circuit breaker state from Redis."""
        try:
            redis_client = await get_redis_client()
            state_data = await redis_client.get(self.redis_key)
            
            if state_data:
                return json.loads(state_data)
            else:
                # Initialize default state
                default_state = {
                    "state": CircuitBreakerState.CLOSED.value,
                    "failure_count": 0,
                    "success_count": 0,
                    "last_failure_time": None,
                    "opened_at": None,
                    "last_attempt_time": None,
                    "total_calls": 0
                }
                await self._update_state(default_state)
                return default_state
                
        except Exception as e:
            logger.exception("redis_circuit_breaker_state_error", name=self.name, error=str(e))
            # Fallback to local state if Redis is unavailable
            return {
                "state": self.local_state.value,
                "failure_count": 0,
                "success_count": 0,
                "last_failure_time": None,
                "opened_at": None,
                "last_attempt_time": None,
                "total_calls": 0
            }
    
    async def _update_state(self, state_data: Dict[str, Any]) -> None:
        """Update circuit breaker state in Redis."""
        try:
            redis_client = await get_redis_client()
            
            # Set state with expiration (to handle cleanup of unused circuit breakers)
            await redis_client.setex(
                self.redis_key,
                self.config.timeout * 10,  # Keep state longer than timeout
                json.dumps(state_data)
            )
            
            # Update heartbeat to show this instance is active
            await redis_client.setex(
                self.heartbeat_key,
                60,  # 1 minute heartbeat
                json.dumps({
                    "instance_id": f"cb_{int(time.time())}",
                    "last_seen": time.time()
                })
            )
            
        except Exception as e:
            logger.exception("redis_circuit_breaker_update_error", name=self.name, error=str(e))
    
    async def _should_attempt_reset(self, state_data: Dict[str, Any]) -> bool:
        """Check if circuit breaker should attempt to reset from OPEN to HALF_OPEN."""
        if state_data["state"] != CircuitBreakerState.OPEN.value:
            return False
        
        opened_at = state_data.get("opened_at")
        if not opened_at:
            return False
        
        # Check if timeout period has elapsed
        return time.time() - opened_at >= self.config.timeout
    
    async def call(self, func, *args, **kwargs):
        """Execute function with distributed circuit breaker protection."""
        async with self._lock:
            state_data = await self.get_state()
            current_state = CircuitBreakerState(state_data["state"])
            
            # Check if circuit is open and should remain open
            if current_state == CircuitBreakerState.OPEN:
                if not await self._should_attempt_reset(state_data):
                    logger.warning(
                        "circuit_breaker_open",
                        name=self.name,
                        failure_count=state_data["failure_count"]
                    )
                    raise Exception(f"Circuit breaker '{self.name}' is OPEN")
                else:
                    # Transition to HALF_OPEN for testing
                    state_data["state"] = CircuitBreakerState.HALF_OPEN.value
                    await self._update_state(state_data)
        
        # Execute the function
        start_time = time.time()
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
            await self._on_success()
            return result
            
        except asyncio.TimeoutError:
            logger.warning(
                "circuit_breaker_timeout",
                name=self.name,
                timeout=self.config.timeout
            )
            await self._on_failure()
            raise Exception(f"Circuit breaker '{self.name}' timeout after {self.config.timeout}s")
            
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self) -> None:
        """Handle successful function execution."""
        try:
            state_data = await self.get_state()
            current_state = CircuitBreakerState(state_data["state"])
            
            state_data["success_count"] += 1
            state_data["total_calls"] += 1
            state_data["last_attempt_time"] = time.time()
            
            # Reset failure count on success
            if current_state == CircuitBreakerState.HALF_OPEN:
                # Transition back to CLOSED if enough successes in HALF_OPEN
                if state_data["success_count"] >= self.config.recovery_threshold:
                    state_data["state"] = CircuitBreakerState.CLOSED.value
                    state_data["failure_count"] = 0
                    state_data["opened_at"] = None
                    
                    logger.info(
                        "circuit_breaker_recovered",
                        name=self.name,
                        success_count=state_data["success_count"]
                    )
            elif current_state == CircuitBreakerState.CLOSED:
                # Reset failure count on success in CLOSED state
                state_data["failure_count"] = 0
            
            await self._update_state(state_data)
            
        except Exception as e:
            logger.exception("circuit_breaker_success_handler_error", name=self.name, error=str(e))
    
    async def _on_failure(self) -> None:
        """Handle failed function execution."""
        try:
            state_data = await self.get_state()
            current_state = CircuitBreakerState(state_data["state"])
            
            state_data["failure_count"] += 1
            state_data["total_calls"] += 1
            state_data["last_failure_time"] = time.time()
            state_data["last_attempt_time"] = time.time()
            
            # Check if we should transition to OPEN
            if (current_state in [CircuitBreakerState.CLOSED, CircuitBreakerState.HALF_OPEN] and 
                state_data["failure_count"] >= self.config.failure_threshold):
                
                state_data["state"] = CircuitBreakerState.OPEN.value
                state_data["opened_at"] = time.time()
                state_data["success_count"] = 0  # Reset success count
                
                logger.warning(
                    "circuit_breaker_opened",
                    name=self.name,
                    failure_count=state_data["failure_count"],
                    threshold=self.config.failure_threshold
                )
            
            await self._update_state(state_data)
            
        except Exception as e:
            logger.exception("circuit_breaker_failure_handler_error", name=self.name, error=str(e))
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics."""
        try:
            state_data = await self.get_state()
            
            return {
                "name": self.name,
                "state": state_data["state"],
                "failure_count": state_data["failure_count"],
                "success_count": state_data["success_count"],
                "total_calls": state_data["total_calls"],
                "failure_rate": (
                    state_data["failure_count"] / max(state_data["total_calls"], 1) * 100
                ),
                "last_failure_time": state_data["last_failure_time"],
                "opened_at": state_data["opened_at"],
                "last_attempt_time": state_data["last_attempt_time"],
                "config": {
                    "failure_threshold": self.config.failure_threshold,
                    "recovery_threshold": self.config.recovery_threshold,
                    "timeout": self.config.timeout
                }
            }
            
        except Exception as e:
            logger.exception("circuit_breaker_metrics_error", name=self.name, error=str(e))
            return {
                "name": self.name,
                "state": "UNKNOWN",
                "error": str(e)
            }
    
    async def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        try:
            state_data = {
                "state": CircuitBreakerState.CLOSED.value,
                "failure_count": 0,
                "success_count": 0,
                "last_failure_time": None,
                "opened_at": None,
                "last_attempt_time": time.time(),
                "total_calls": 0
            }
            
            await self._update_state(state_data)
            
            logger.info("circuit_breaker_manually_reset", name=self.name)
            
        except Exception as e:
            logger.exception("circuit_breaker_reset_error", name=self.name, error=str(e))


class DistributedCircuitBreakerRegistry:
    """Registry for managing distributed circuit breakers."""
    
    def __init__(self):
        self._breakers: Dict[str, DistributedCircuitBreaker] = {}
    
    def get_breaker(self, name: str, config: CircuitBreakerConfig) -> DistributedCircuitBreaker:
        """Get or create a distributed circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = DistributedCircuitBreaker(name, config)
        return self._breakers[name]
    
    async def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers."""
        metrics = {}
        
        for name, breaker in self._breakers.items():
            try:
                metrics[name] = await breaker.get_metrics()
            except Exception as e:
                logger.exception("circuit_breaker_registry_metrics_error", name=name, error=str(e))
                metrics[name] = {"name": name, "state": "ERROR", "error": str(e)}
        
        return metrics
    
    async def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for name, breaker in self._breakers.items():
            try:
                await breaker.reset()
            except Exception as e:
                logger.exception("circuit_breaker_registry_reset_error", name=name, error=str(e))


# Global registry instance
distributed_registry = DistributedCircuitBreakerRegistry()


def get_distributed_circuit_breaker(name: str, config: CircuitBreakerConfig) -> DistributedCircuitBreaker:
    """Get a distributed circuit breaker instance."""
    return distributed_registry.get_breaker(name, config)
