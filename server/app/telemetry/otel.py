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
        logger.error("telemetry_setup_failed", error=str(e))


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

