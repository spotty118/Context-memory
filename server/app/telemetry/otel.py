"""
OpenTelemetry setup for metrics and tracing.
"""
from typing import Optional
from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Histogram, Gauge
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_CONNECTIONS = Gauge(
    'http_active_connections',
    'Number of active HTTP connections'
)

LLM_REQUESTS = Counter(
    'llm_requests_total',
    'Total LLM requests',
    ['model', 'provider', 'workspace']
)

LLM_TOKENS = Counter(
    'llm_tokens_total',
    'Total LLM tokens processed',
    ['model', 'provider', 'workspace', 'direction']
)

LLM_COSTS = Counter(
    'llm_costs_total',
    'Total LLM costs in USD',
    ['model', 'provider', 'workspace']
)

# Context Memory Metrics
CONTEXT_OPERATIONS = Counter(
    'context_operations_total',
    'Total context memory operations',
    ['operation', 'workspace', 'status']
)

CONTEXT_RETRIEVAL_LATENCY = Histogram(
    'context_retrieval_duration_seconds',
    'Context retrieval latency in seconds',
    ['operation', 'workspace'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

CONTEXT_ITEMS_RETRIEVED = Histogram(
    'context_items_retrieved_count',
    'Number of context items retrieved per operation',
    ['operation', 'workspace'],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500]
)

CONTEXT_TOKEN_USAGE = Histogram(
    'context_token_usage_count',
    'Token usage for context operations',
    ['operation', 'workspace'],
    buckets=[100, 500, 1000, 2000, 4000, 8000, 16000, 32000]
)

WORKING_SET_SIZE = Histogram(
    'working_set_size_bytes',
    'Working set size in bytes',
    ['workspace'],
    buckets=[1024, 4096, 16384, 65536, 262144, 1048576, 4194304]
)

# API Key and Authentication Metrics
API_KEY_OPERATIONS = Counter(
    'api_key_operations_total',
    'Total API key operations',
    ['operation', 'status']
)

AUTHENTICATION_LATENCY = Histogram(
    'authentication_duration_seconds',
    'Authentication operation latency',
    ['method', 'status'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# Rate Limiting and Quota Metrics
RATE_LIMIT_HITS = Counter(
    'rate_limit_hits_total',
    'Total rate limit hits',
    ['workspace', 'limit_type']
)

QUOTA_USAGE = Gauge(
    'quota_usage_percentage',
    'Current quota usage percentage',
    ['workspace', 'quota_type']
)

# Database Performance Metrics
DATABASE_OPERATIONS = Counter(
    'database_operations_total',
    'Total database operations',
    ['operation', 'table', 'status']
)

DATABASE_QUERY_LATENCY = Histogram(
    'database_query_duration_seconds',
    'Database query latency',
    ['operation', 'table'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

DATABASE_CONNECTION_POOL = Gauge(
    'database_connection_pool_size',
    'Database connection pool metrics',
    ['status']  # active, idle, total
)

# Cache Performance Metrics
CACHE_OPERATIONS = Counter(
    'cache_operations_total',
    'Total cache operations',
    ['operation', 'status']  # hit, miss, set, delete
)

CACHE_LATENCY = Histogram(
    'cache_operation_duration_seconds',
    'Cache operation latency',
    ['operation'],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1]
)

# Circuit Breaker Metrics
CIRCUIT_BREAKER_STATE = Gauge(
    'circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half-open)',
    ['name']
)

CIRCUIT_BREAKER_OPERATIONS = Counter(
    'circuit_breaker_operations_total',
    'Circuit breaker operations',
    ['name', 'operation']  # success, failure, timeout, open
)

# Model Performance Metrics
MODEL_PERFORMANCE = Histogram(
    'model_response_duration_seconds',
    'Model response time',
    ['model', 'provider'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
)

MODEL_TOKEN_RATE = Histogram(
    'model_tokens_per_second',
    'Model token generation rate',
    ['model', 'provider'],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000]
)

MODEL_AVAILABILITY = Gauge(
    'model_availability',
    'Model availability (1=available, 0=unavailable)',
    ['model', 'provider']
)

# Worker and Job Queue Metrics
WORKER_COUNT = Gauge(
    'workers_active_total',
    'Number of active workers',
    ['queue', 'state']  # idle, busy, dead
)

JOB_QUEUE_SIZE = Gauge(
    'job_queue_size',
    'Number of jobs in queue',
    ['queue', 'status']  # pending, failed, finished, deferred
)

JOB_PROCESSING_TIME = Histogram(
    'job_processing_duration_seconds',
    'Job processing time',
    ['queue', 'job_type', 'status'],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 900.0, 1800.0]
)

JOB_RETRY_COUNT = Counter(
    'job_retries_total',
    'Total job retry attempts',
    ['queue', 'job_type', 'retry_reason']
)

SCHEDULER_JOBS = Gauge(
    'scheduler_jobs_total',
    'Number of scheduled jobs',
    ['status']  # scheduled, missed, running
)

WORKER_HEALTH_SCORE = Gauge(
    'worker_health_score',
    'Overall worker system health score (0-100)'
)

WORKER_MEMORY_USAGE = Gauge(
    'worker_memory_usage_bytes',
    'Worker memory usage in bytes',
    ['worker_name']
)

WORKER_JOB_SUCCESS_RATE = Gauge(
    'worker_job_success_rate',
    'Worker job success rate (0.0-1.0)',
    ['worker_name']
)


def setup_telemetry(app: FastAPI) -> None:
    """
    Set up OpenTelemetry instrumentation for the FastAPI app.
    
    Args:
        app: FastAPI application instance
    """
    if not settings.METRICS_ENABLED:
        logger.info("metrics_disabled")
        return
    
    try:
        # Basic Prometheus metrics setup
        logger.info("telemetry_setup_complete")
    except Exception as e:
        logger.exception("telemetry_setup_failed")


def record_request_metrics(method: str, endpoint: str, status_code: int, duration: float) -> None:
    """Record HTTP request metrics."""
    if settings.METRICS_ENABLED:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
        REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)


def record_llm_metrics(
    model: str,
    provider: str,
    workspace: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost: float = 0.0
) -> None:
    """Record LLM usage metrics."""
    if settings.METRICS_ENABLED:
        LLM_REQUESTS.labels(model=model, provider=provider, workspace=workspace).inc()
        
        if prompt_tokens > 0:
            LLM_TOKENS.labels(
                model=model, 
                provider=provider, 
                workspace=workspace, 
                direction='prompt'
            ).inc(prompt_tokens)
        
        if completion_tokens > 0:
            LLM_TOKENS.labels(
                model=model, 
                provider=provider, 
                workspace=workspace, 
                direction='completion'
            ).inc(completion_tokens)
        
        if cost > 0:
            LLM_COSTS.labels(model=model, provider=provider, workspace=workspace).inc(cost)


def get_metrics() -> str:
    """Get Prometheus metrics in text format."""
    if not settings.METRICS_ENABLED:
        return ""
    
    return generate_latest().decode('utf-8')


# Context Memory Metric Recording Functions

def record_context_operation(
    operation: str,
    workspace: str,
    status: str = "success",
    duration: Optional[float] = None,
    items_count: Optional[int] = None,
    tokens_used: Optional[int] = None
) -> None:
    """Record context memory operation metrics."""
    if not settings.METRICS_ENABLED:
        return
    
    CONTEXT_OPERATIONS.labels(
        operation=operation,
        workspace=workspace,
        status=status
    ).inc()
    
    if duration is not None:
        CONTEXT_RETRIEVAL_LATENCY.labels(
            operation=operation,
            workspace=workspace
        ).observe(duration)
    
    if items_count is not None:
        CONTEXT_ITEMS_RETRIEVED.labels(
            operation=operation,
            workspace=workspace
        ).observe(items_count)
    
    if tokens_used is not None:
        CONTEXT_TOKEN_USAGE.labels(
            operation=operation,
            workspace=workspace
        ).observe(tokens_used)


def record_working_set_metrics(workspace: str, size_bytes: int) -> None:
    """Record working set size metrics."""
    if settings.METRICS_ENABLED:
        WORKING_SET_SIZE.labels(workspace=workspace).observe(size_bytes)


# Authentication and API Key Metrics

def record_api_key_operation(operation: str, status: str = "success") -> None:
    """Record API key operation metrics."""
    if settings.METRICS_ENABLED:
        API_KEY_OPERATIONS.labels(operation=operation, status=status).inc()


def record_authentication_metrics(method: str, status: str, duration: float) -> None:
    """Record authentication operation metrics."""
    if settings.METRICS_ENABLED:
        AUTHENTICATION_LATENCY.labels(method=method, status=status).observe(duration)


# Rate Limiting and Quota Metrics

def record_rate_limit_hit(workspace: str, limit_type: str) -> None:
    """Record rate limit hit."""
    if settings.METRICS_ENABLED:
        RATE_LIMIT_HITS.labels(workspace=workspace, limit_type=limit_type).inc()


def update_quota_usage(workspace: str, quota_type: str, usage_percentage: float) -> None:
    """Update quota usage percentage."""
    if settings.METRICS_ENABLED:
        QUOTA_USAGE.labels(workspace=workspace, quota_type=quota_type).set(usage_percentage)


# Database Performance Metrics

def record_database_operation(
    operation: str,
    table: str,
    status: str = "success",
    duration: Optional[float] = None
) -> None:
    """Record database operation metrics."""
    if not settings.METRICS_ENABLED:
        return
    
    DATABASE_OPERATIONS.labels(
        operation=operation,
        table=table,
        status=status
    ).inc()
    
    if duration is not None:
        DATABASE_QUERY_LATENCY.labels(
            operation=operation,
            table=table
        ).observe(duration)


def update_database_pool_metrics(active: int, idle: int, total: int) -> None:
    """Update database connection pool metrics."""
    if settings.METRICS_ENABLED:
        DATABASE_CONNECTION_POOL.labels(status="active").set(active)
        DATABASE_CONNECTION_POOL.labels(status="idle").set(idle)
        DATABASE_CONNECTION_POOL.labels(status="total").set(total)


# Cache Performance Metrics

def record_cache_operation(
    operation: str,
    status: str,
    duration: Optional[float] = None
) -> None:
    """Record cache operation metrics."""
    if not settings.METRICS_ENABLED:
        return
    
    CACHE_OPERATIONS.labels(operation=operation, status=status).inc()
    
    if duration is not None:
        CACHE_LATENCY.labels(operation=operation).observe(duration)


# Circuit Breaker Metrics

def update_circuit_breaker_state(name: str, state: str) -> None:
    """Update circuit breaker state metric."""
    if settings.METRICS_ENABLED:
        state_value = {"closed": 0, "open": 1, "half_open": 2}.get(state, 0)
        CIRCUIT_BREAKER_STATE.labels(name=name).set(state_value)


def record_circuit_breaker_operation(name: str, operation: str) -> None:
    """Record circuit breaker operation."""
    if settings.METRICS_ENABLED:
        CIRCUIT_BREAKER_OPERATIONS.labels(name=name, operation=operation).inc()


# Model Performance Metrics

def record_model_performance(
    model: str,
    provider: str,
    duration: float,
    tokens_generated: Optional[int] = None
) -> None:
    """Record model performance metrics."""
    if not settings.METRICS_ENABLED:
        return
    
    MODEL_PERFORMANCE.labels(model=model, provider=provider).observe(duration)
    
    if tokens_generated is not None and duration > 0:
        tokens_per_second = tokens_generated / duration
        MODEL_TOKEN_RATE.labels(model=model, provider=provider).observe(tokens_per_second)


def update_model_availability(model: str, provider: str, available: bool) -> None:
    """Update model availability metric."""
    if settings.METRICS_ENABLED:
        MODEL_AVAILABILITY.labels(model=model, provider=provider).set(1 if available else 0)


# Batch metric recording for efficiency

def record_request_batch_metrics(
    method: str,
    endpoint: str,
    status_code: int,
    duration: float,
    workspace: Optional[str] = None,
    operation: Optional[str] = None
) -> None:
    """Record multiple metrics for a single request efficiently."""
    if not settings.METRICS_ENABLED:
        return
    
    # Record basic HTTP metrics
    record_request_metrics(method, endpoint, status_code, duration)
    
    # Record authentication metrics if applicable
    if operation == "authentication":
        auth_status = "success" if status_code < 400 else "failure"
        record_authentication_metrics("api_key", auth_status, duration)
    
    # Record rate limiting if applicable
    if status_code == 429 and workspace:
        record_rate_limit_hit(workspace, "requests_per_minute")


# Worker and Job Queue Metrics Recording Functions

def update_worker_count(queue: str, state: str, count: int) -> None:
    """Update worker count metrics."""
    if settings.METRICS_ENABLED:
        WORKER_COUNT.labels(queue=queue, state=state).set(count)


def update_job_queue_size(queue: str, status: str, count: int) -> None:
    """Update job queue size metrics."""
    if settings.METRICS_ENABLED:
        JOB_QUEUE_SIZE.labels(queue=queue, status=status).set(count)


def record_job_processing(
    queue: str,
    job_type: str,
    status: str,
    duration: float
) -> None:
    """Record job processing metrics."""
    if settings.METRICS_ENABLED:
        JOB_PROCESSING_TIME.labels(
            queue=queue,
            job_type=job_type,
            status=status
        ).observe(duration)


def record_job_retry(
    queue: str,
    job_type: str,
    retry_reason: str
) -> None:
    """Record job retry attempt."""
    if settings.METRICS_ENABLED:
        JOB_RETRY_COUNT.labels(
            queue=queue,
            job_type=job_type,
            retry_reason=retry_reason
        ).inc()


def update_scheduler_jobs(status: str, count: int) -> None:
    """Update scheduler job count metrics."""
    if settings.METRICS_ENABLED:
        SCHEDULER_JOBS.labels(status=status).set(count)


def update_worker_health_score(score: float) -> None:
    """Update overall worker system health score."""
    if settings.METRICS_ENABLED:
        WORKER_HEALTH_SCORE.set(score)


def update_worker_metrics(
    worker_name: str,
    memory_usage: Optional[int] = None,
    success_rate: Optional[float] = None
) -> None:
    """Update individual worker metrics."""
    if not settings.METRICS_ENABLED:
        return
    
    if memory_usage is not None:
        WORKER_MEMORY_USAGE.labels(worker_name=worker_name).set(memory_usage)
    
    if success_rate is not None:
        WORKER_JOB_SUCCESS_RATE.labels(worker_name=worker_name).set(success_rate)


def record_worker_system_metrics(
    queue_stats: dict,
    worker_info: list,
    health_score: float
) -> None:
    """Record comprehensive worker system metrics in batch."""
    if not settings.METRICS_ENABLED:
        return
    
    # Update health score
    update_worker_health_score(health_score)
    
    # Update queue metrics
    for queue_name, stats in queue_stats.items():
        if "error" not in stats:
            update_job_queue_size(queue_name, "pending", stats.get("length", 0))
            update_job_queue_size(queue_name, "failed", stats.get("failed_count", 0))
            update_job_queue_size(queue_name, "finished", stats.get("finished_count", 0))
            update_job_queue_size(queue_name, "deferred", stats.get("deferred_count", 0))
    
    # Update worker metrics
    worker_states = {"idle": 0, "busy": 0, "dead": 0}
    
    for worker in worker_info:
        if "error" not in worker:
            state = worker.get("state", "unknown")
            if state in worker_states:
                worker_states[state] += 1
            
            # Update individual worker metrics
            worker_name = worker.get("name", "unknown")
            successful_jobs = worker.get("successful_jobs", 0)
            failed_jobs = worker.get("failed_jobs", 0)
            
            if successful_jobs + failed_jobs > 0:
                success_rate = successful_jobs / (successful_jobs + failed_jobs)
                update_worker_metrics(worker_name, success_rate=success_rate)
    
    # Update worker count metrics (aggregate across all queues)
    for state, count in worker_states.items():
        update_worker_count("all", state, count)

