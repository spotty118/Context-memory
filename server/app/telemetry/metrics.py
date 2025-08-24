"""
Prometheus metrics collection for Context Memory Gateway.
Provides comprehensive monitoring of application performance, errors, and business metrics.
"""
from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry, multiprocess, generate_latest
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST
from typing import Dict, Optional
import time
import structlog
from fastapi import Request, Response
from fastapi.responses import PlainTextResponse
import os
import psutil

logger = structlog.get_logger(__name__)

# Create registry for metrics
if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
    # Use multiprocess mode in production
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
else:
    # Use default registry in development
    from prometheus_client import REGISTRY
    registry = REGISTRY

# Application Info
app_info = Info(
    'context_memory_gateway_info',
    'Information about the Context Memory Gateway application',
    registry=registry
)

# Request metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests processed',
    ['method', 'endpoint', 'status_code'],
    registry=registry
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry
)

http_requests_in_progress = Gauge(
    'http_requests_in_progress',
    'Number of HTTP requests currently being processed',
    ['method', 'endpoint'],
    registry=registry
)

# API Key metrics
api_key_requests_total = Counter(
    'api_key_requests_total',
    'Total requests per API key',
    ['api_key_hash', 'endpoint'],
    registry=registry
)

api_key_rate_limit_hits = Counter(
    'api_key_rate_limit_hits_total',
    'Total rate limit hits per API key',
    ['api_key_hash', 'limit_type'],
    registry=registry
)

# Cache metrics
cache_operations_total = Counter(
    'cache_operations_total',
    'Total cache operations',
    ['operation', 'cache_type', 'status'],
    registry=registry
)

cache_hit_ratio = Gauge(
    'cache_hit_ratio',
    'Cache hit ratio percentage',
    ['cache_type'],
    registry=registry
)

cache_size = Gauge(
    'cache_size_bytes',
    'Current cache size in bytes',
    ['cache_type'],
    registry=registry
)

# Database metrics
database_connections_active = Gauge(
    'database_connections_active',
    'Number of active database connections',
    registry=registry
)

database_connections_total = Counter(
    'database_connections_total',
    'Total database connections created',
    registry=registry
)

database_query_duration_seconds = Histogram(
    'database_query_duration_seconds',
    'Database query duration in seconds',
    ['operation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=registry
)

# Error metrics
errors_total = Counter(
    'errors_total',
    'Total application errors',
    ['error_type', 'endpoint'],
    registry=registry
)

exceptions_total = Counter(
    'exceptions_total',
    'Total unhandled exceptions',
    ['exception_type'],
    registry=registry
)

# Business metrics
context_operations_total = Counter(
    'context_operations_total',
    'Total context memory operations',
    ['operation_type', 'status'],
    registry=registry
)

llm_requests_total = Counter(
    'llm_requests_total',
    'Total LLM gateway requests',
    ['provider', 'model', 'status'],
    registry=registry
)

llm_token_usage = Counter(
    'llm_token_usage_total',
    'Total LLM tokens consumed',
    ['provider', 'model', 'token_type'],
    registry=registry
)

# System metrics
system_memory_usage = Gauge(
    'system_memory_usage_bytes',
    'System memory usage in bytes',
    ['type'],
    registry=registry
)

system_cpu_usage = Gauge(
    'system_cpu_usage_percent',
    'System CPU usage percentage',
    registry=registry
)

# Worker metrics
worker_tasks_total = Counter(
    'worker_tasks_total',
    'Total background worker tasks',
    ['task_type', 'status'],
    registry=registry
)

worker_queue_size = Gauge(
    'worker_queue_size',
    'Current worker queue size',
    ['queue_name'],
    registry=registry
)

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    'circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=half_open, 2=open)',
    ['service_name'],
    registry=registry
)

circuit_breaker_requests_total = Counter(
    'circuit_breaker_requests_total',
    'Total requests processed by circuit breaker',
    ['service_name', 'result'],  # result: success, failure, rejected
    registry=registry
)

circuit_breaker_failures_total = Counter(
    'circuit_breaker_failures_total',
    'Total circuit breaker failures',
    ['service_name', 'failure_type'],  # failure_type: timeout, error, exception
    registry=registry
)

circuit_breaker_state_transitions_total = Counter(
    'circuit_breaker_state_transitions_total',
    'Total circuit breaker state transitions',
    ['service_name', 'from_state', 'to_state'],
    registry=registry
)

circuit_breaker_response_time_seconds = Histogram(
    'circuit_breaker_response_time_seconds',
    'Circuit breaker protected operation response time in seconds',
    ['service_name'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry
)


class MetricsCollector:
    """Central metrics collection and management."""
    
    def __init__(self):
        self._request_start_times: Dict[str, float] = {}
        
    def record_request_start(self, request: Request) -> None:
        """Record the start of a request for duration tracking."""
        request_id = getattr(request.state, 'correlation_id', id(request))
        self._request_start_times[request_id] = time.time()
        
        # Increment in-progress counter
        endpoint = self._get_endpoint_name(request)
        http_requests_in_progress.labels(
            method=request.method,
            endpoint=endpoint
        ).inc()
        
    def record_request_end(self, request: Request, response: Response) -> None:
        """Record the end of a request with metrics."""
        request_id = getattr(request.state, 'correlation_id', id(request))
        endpoint = self._get_endpoint_name(request)
        
        # Record total requests
        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=str(response.status_code)
        ).inc()
        
        # Record duration if we have start time
        start_time = self._request_start_times.pop(request_id, None)
        if start_time:
            duration = time.time() - start_time
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=endpoint
            ).observe(duration)
            
        # Decrement in-progress counter
        http_requests_in_progress.labels(
            method=request.method,
            endpoint=endpoint
        ).dec()
        
    def record_api_key_usage(self, api_key_hash: str, endpoint: str) -> None:
        """Record API key usage."""
        api_key_requests_total.labels(
            api_key_hash=api_key_hash[:8] + "...",  # Truncate for privacy
            endpoint=endpoint
        ).inc()
        
    def record_rate_limit_hit(self, api_key_hash: str, limit_type: str) -> None:
        """Record rate limit hit."""
        api_key_rate_limit_hits.labels(
            api_key_hash=api_key_hash[:8] + "...",
            limit_type=limit_type
        ).inc()
        
    def record_cache_operation(self, operation: str, cache_type: str, status: str) -> None:
        """Record cache operation."""
        cache_operations_total.labels(
            operation=operation,
            cache_type=cache_type,
            status=status
        ).inc()
        
    def update_cache_metrics(self, cache_type: str, hit_ratio: float, size_bytes: int) -> None:
        """Update cache performance metrics."""
        cache_hit_ratio.labels(cache_type=cache_type).set(hit_ratio)
        cache_size.labels(cache_type=cache_type).set(size_bytes)
        
    def record_database_operation(self, operation: str, duration: float) -> None:
        """Record database operation metrics."""
        database_query_duration_seconds.labels(operation=operation).observe(duration)
        
    def update_database_connections(self, active: int, total: int) -> None:
        """Update database connection metrics."""
        database_connections_active.set(active)
        # Note: total is updated via counter increment when connections are created
        
    def record_error(self, error_type: str, endpoint: str) -> None:
        """Record application error."""
        errors_total.labels(
            error_type=error_type,
            endpoint=endpoint
        ).inc()
        
    def record_exception(self, exception_type: str) -> None:
        """Record unhandled exception."""
        exceptions_total.labels(exception_type=exception_type).inc()
        
    def record_context_operation(self, operation_type: str, status: str) -> None:
        """Record context memory operation."""
        context_operations_total.labels(
            operation_type=operation_type,
            status=status
        ).inc()
        
    def record_llm_request(self, provider: str, model: str, status: str, 
                          input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Record LLM gateway request and token usage."""
        llm_requests_total.labels(
            provider=provider,
            model=model,
            status=status
        ).inc()
        
        if input_tokens > 0:
            llm_token_usage.labels(
                provider=provider,
                model=model,
                token_type="input"
            ).inc(input_tokens)
            
        if output_tokens > 0:
            llm_token_usage.labels(
                provider=provider,
                model=model,
                token_type="output"
            ).inc(output_tokens)
            
    def record_worker_task(self, task_type: str, status: str) -> None:
        """Record background worker task."""
        worker_tasks_total.labels(
            task_type=task_type,
            status=status
        ).inc()
        
    def update_worker_queue_size(self, queue_name: str, size: int) -> None:
        """Update worker queue size."""
        worker_queue_size.labels(queue_name=queue_name).set(size)
        
    def update_system_metrics(self) -> None:
        """Update system resource metrics."""
        try:
            # Memory metrics
            memory = psutil.virtual_memory()
            system_memory_usage.labels(type="total").set(memory.total)
            system_memory_usage.labels(type="available").set(memory.available)
            system_memory_usage.labels(type="used").set(memory.used)
            
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=None)
            system_cpu_usage.set(cpu_percent)
            
        except Exception as e:
            logger.warning("failed_to_update_system_metrics", error=str(e))
    
    def update_circuit_breaker_metrics(self) -> None:
        """Update circuit breaker metrics from all registered circuit breakers."""
        try:
            from app.core.circuit_breaker import circuit_breaker_registry
            
            stats = circuit_breaker_registry.get_all_stats()
            for service_name, breaker_stats in stats.items():
                # Update state metric (0=closed, 1=half_open, 2=open)
                state_value = {
                    "closed": 0,
                    "half_open": 1,
                    "open": 2
                }.get(breaker_stats["state"], 0)
                
                circuit_breaker_state.labels(service_name=service_name).set(state_value)
                
        except Exception as e:
            logger.warning("failed_to_update_circuit_breaker_metrics", error=str(e))
    
    def record_circuit_breaker_request(self, service_name: str, result: str, response_time: float = None) -> None:
        """Record a circuit breaker request."""
        try:
            circuit_breaker_requests_total.labels(service_name=service_name, result=result).inc()
            
            if response_time is not None:
                circuit_breaker_response_time_seconds.labels(service_name=service_name).observe(response_time)
                
        except Exception as e:
            logger.warning("failed_to_record_circuit_breaker_request", error=str(e))
    
    def record_circuit_breaker_failure(self, service_name: str, failure_type: str) -> None:
        """Record a circuit breaker failure."""
        try:
            circuit_breaker_failures_total.labels(service_name=service_name, failure_type=failure_type).inc()
        except Exception as e:
            logger.warning("failed_to_record_circuit_breaker_failure", error=str(e))
    
    def record_circuit_breaker_state_transition(self, service_name: str, from_state: str, to_state: str) -> None:
        """Record a circuit breaker state transition."""
        try:
            circuit_breaker_state_transitions_total.labels(
                service_name=service_name, 
                from_state=from_state, 
                to_state=to_state
            ).inc()
        except Exception as e:
            logger.warning("failed_to_record_circuit_breaker_state_transition", error=str(e))
            
    def _get_endpoint_name(self, request: Request) -> str:
        """Extract a clean endpoint name from the request."""
        path = request.url.path
        
        # Normalize common patterns
        if path.startswith("/api/v1/"):
            return path.replace("/api/v1", "/v1")
        elif path.startswith("/api/v2/"):
            return path.replace("/api/v2", "/v2")
        elif path.startswith("/admin/"):
            return "/admin/*"
        elif path == "/":
            return "/root"
        elif path == "/health":
            return "/health"
        else:
            return path


# Global metrics collector instance
metrics_collector = MetricsCollector()


def setup_app_info():
    """Set up application information metrics."""
    app_info.info({
        'version': '1.0.0',
        'service': 'context-memory-gateway',
        'environment': os.getenv('ENVIRONMENT', 'development')
    })


def get_metrics_response() -> PlainTextResponse:
    """Generate Prometheus metrics response."""
    try:
        metrics_data = generate_latest(registry)
        return PlainTextResponse(
            content=metrics_data.decode('utf-8'),
            media_type=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        logger.exception("failed_to_generate_metrics", error=str(e))
        return PlainTextResponse(
            content="# Metrics generation failed\n",
            media_type=CONTENT_TYPE_LATEST,
            status_code=500
        )