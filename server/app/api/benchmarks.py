"""
API endpoints for performance benchmarking and monitoring.
Provides web-based interface for running and viewing benchmark results.
"""
import asyncio
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, Field
import structlog

from app.core.security import get_api_key
from app.db.models import APIKey
from app.core.benchmarks import (
    PerformanceBenchmark, BenchmarkConfig, BenchmarkType,
    BenchmarkStatus, BenchmarkMetrics, get_default_endpoints
)


router = APIRouter(prefix="/benchmarks", tags=["Performance Benchmarks"])
logger = structlog.get_logger(__name__)

# Global storage for benchmark results (in production, use Redis or database)
benchmark_runs: Dict[str, Dict[str, Any]] = {}
active_benchmarks: Dict[str, PerformanceBenchmark] = {}


class BenchmarkRequest(BaseModel):
    """Request model for starting a benchmark."""
    benchmark_type: str = Field(..., description="Type of benchmark (latency, throughput, load_test, stress_test, endurance)")
    endpoints: Optional[List[str]] = Field(None, description="Specific endpoints to test (default: all)")
    config: Dict[str, Any] = Field(default_factory=dict, description="Benchmark configuration overrides")


class BenchmarkRunResponse(BaseModel):
    """Response model for benchmark run."""
    run_id: str
    status: str
    benchmark_type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    endpoints_tested: List[str]
    config: Dict[str, Any]


class BenchmarkMetricsResponse(BaseModel):
    """Response model for benchmark metrics."""
    run_id: str
    metrics: Dict[str, Dict[str, Any]]
    summary: Dict[str, Any]


@router.get("/status")
async def get_benchmark_status(
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Get overall benchmark system status.
    
    Returns:
        System status and active benchmark information
    """
    active_runs = len(active_benchmarks)
    total_runs = len(benchmark_runs)
    
    # Get recent runs (last 24 hours)
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    recent_runs = [
        run for run in benchmark_runs.values()
        if run["start_time"] >= cutoff_time
    ]
    
    return {
        "status": "healthy",
        "active_benchmarks": active_runs,
        "total_runs": total_runs,
        "recent_runs_24h": len(recent_runs),
        "available_endpoints": [ep.name for ep in get_default_endpoints()],
        "supported_benchmark_types": [bt.value for bt in BenchmarkType],
        "workspace_id": api_key.workspace_id
    }


@router.get("/runs")
async def list_benchmark_runs(
    limit: int = 50,
    benchmark_type: Optional[str] = None,
    status: Optional[str] = None,
    api_key: APIKey = Depends(get_api_key)
) -> List[BenchmarkRunResponse]:
    """
    List benchmark runs with optional filtering.
    
    Args:
        limit: Maximum number of runs to return
        benchmark_type: Filter by benchmark type
        status: Filter by status
        
    Returns:
        List of benchmark runs
    """
    runs = list(benchmark_runs.values())
    
    # Apply filters
    if benchmark_type:
        runs = [run for run in runs if run.get("benchmark_type") == benchmark_type]
    
    if status:
        runs = [run for run in runs if run.get("status") == status]
    
    # Sort by start time (newest first) and limit
    runs.sort(key=lambda x: x.get("start_time", datetime.min), reverse=True)
    runs = runs[:limit]
    
    return [
        BenchmarkRunResponse(
            run_id=run["run_id"],
            status=run["status"],
            benchmark_type=run["benchmark_type"],
            start_time=run["start_time"],
            end_time=run.get("end_time"),
            duration_seconds=run.get("duration_seconds"),
            endpoints_tested=run.get("endpoints_tested", []),
            config=run.get("config", {})
        )
        for run in runs
    ]


@router.post("/run")
async def start_benchmark(
    request: BenchmarkRequest,
    background_tasks: BackgroundTasks,
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Start a new benchmark run.
    
    Args:
        request: Benchmark configuration
        background_tasks: FastAPI background tasks
        
    Returns:
        Benchmark run information
    """
    # Validate benchmark type
    try:
        benchmark_type = BenchmarkType(request.benchmark_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid benchmark type. Must be one of: {[bt.value for bt in BenchmarkType]}"
        )
    
    # Generate run ID
    run_id = str(uuid.uuid4())
    
    # Get endpoints to test
    if request.endpoints:
        available_endpoints = get_default_endpoints()
        endpoint_names = {ep.name for ep in available_endpoints}
        invalid_endpoints = set(request.endpoints) - endpoint_names
        
        if invalid_endpoints:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid endpoints: {list(invalid_endpoints)}"
            )
        
        endpoints = [ep for ep in available_endpoints if ep.name in request.endpoints]
    else:
        endpoints = get_default_endpoints()
    
    # Create benchmark configuration
    config_dict = {
        "base_url": "http://localhost:8000",  # Internal call
        "api_key": None,  # Use internal calls
        "concurrent_requests": 10,
        "total_requests": 100,
        "request_timeout": 30,
        "warm_up_requests": 5,
        **request.config
    }
    
    config = BenchmarkConfig(**config_dict)
    
    # Store run information
    run_info = {
        "run_id": run_id,
        "status": BenchmarkStatus.PENDING.value,
        "benchmark_type": benchmark_type.value,
        "start_time": datetime.utcnow(),
        "end_time": None,
        "duration_seconds": None,
        "endpoints_tested": [ep.name for ep in endpoints],
        "config": config_dict,
        "workspace_id": api_key.workspace_id
    }
    
    benchmark_runs[run_id] = run_info
    
    # Start benchmark in background
    background_tasks.add_task(
        _run_benchmark_background,
        run_id,
        endpoints,
        benchmark_type,
        config
    )
    
    logger.info(
        "benchmark_started",
        run_id=run_id,
        benchmark_type=benchmark_type.value,
        endpoints=len(endpoints),
        workspace_id=api_key.workspace_id
    )
    
    return {
        "run_id": run_id,
        "status": "started",
        "benchmark_type": benchmark_type.value,
        "endpoints_count": len(endpoints),
        "estimated_duration_seconds": _estimate_duration(benchmark_type, config)
    }


@router.get("/runs/{run_id}")
async def get_benchmark_run(
    run_id: str,
    api_key: APIKey = Depends(get_api_key)
) -> BenchmarkRunResponse:
    """
    Get details of a specific benchmark run.
    
    Args:
        run_id: Benchmark run ID
        
    Returns:
        Benchmark run details
    """
    if run_id not in benchmark_runs:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    
    run = benchmark_runs[run_id]
    
    return BenchmarkRunResponse(
        run_id=run["run_id"],
        status=run["status"],
        benchmark_type=run["benchmark_type"],
        start_time=run["start_time"],
        end_time=run.get("end_time"),
        duration_seconds=run.get("duration_seconds"),
        endpoints_tested=run.get("endpoints_tested", []),
        config=run.get("config", {})
    )


@router.get("/runs/{run_id}/metrics")
async def get_benchmark_metrics(
    run_id: str,
    api_key: APIKey = Depends(get_api_key)
) -> BenchmarkMetricsResponse:
    """
    Get metrics for a completed benchmark run.
    
    Args:
        run_id: Benchmark run ID
        
    Returns:
        Benchmark metrics and summary
    """
    if run_id not in benchmark_runs:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    
    run = benchmark_runs[run_id]
    
    if run["status"] != BenchmarkStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Metrics not available. Run status: {run['status']}"
        )
    
    metrics = run.get("metrics", {})
    
    # Calculate summary statistics
    summary = _calculate_summary_metrics(metrics)
    
    return BenchmarkMetricsResponse(
        run_id=run_id,
        metrics=metrics,
        summary=summary
    )


@router.delete("/runs/{run_id}")
async def cancel_benchmark(
    run_id: str,
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Cancel a running benchmark.
    
    Args:
        run_id: Benchmark run ID
        
    Returns:
        Cancellation status
    """
    if run_id not in benchmark_runs:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    
    run = benchmark_runs[run_id]
    
    if run["status"] not in [BenchmarkStatus.PENDING.value, BenchmarkStatus.RUNNING.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel benchmark with status: {run['status']}"
        )
    
    # Mark as cancelled
    run["status"] = BenchmarkStatus.CANCELLED.value
    run["end_time"] = datetime.utcnow()
    
    # Remove from active benchmarks
    if run_id in active_benchmarks:
        del active_benchmarks[run_id]
    
    logger.info("benchmark_cancelled", run_id=run_id)
    
    return {
        "run_id": run_id,
        "status": "cancelled",
        "message": "Benchmark cancelled successfully"
    }


@router.get("/baselines")
async def get_baseline_metrics(
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Get baseline performance metrics.
    
    Returns:
        Baseline metrics for comparison
    """
    # Calculate baselines from completed runs
    completed_runs = [
        run for run in benchmark_runs.values()
        if run["status"] == BenchmarkStatus.COMPLETED.value
    ]
    
    if not completed_runs:
        return {
            "message": "No completed benchmark runs available for baseline calculation",
            "endpoints": []
        }
    
    # Group by endpoint and calculate averages
    endpoint_metrics = {}
    
    for run in completed_runs:
        metrics = run.get("metrics", {})
        for endpoint_name, endpoint_data in metrics.items():
            if endpoint_name not in endpoint_metrics:
                endpoint_metrics[endpoint_name] = []
            endpoint_metrics[endpoint_name].append(endpoint_data)
    
    # Calculate baseline averages
    baselines = {}
    for endpoint_name, metrics_list in endpoint_metrics.items():
        if not metrics_list:
            continue
        
        avg_response_time = sum(m["avg_response_time_ms"] for m in metrics_list) / len(metrics_list)
        avg_throughput = sum(m["requests_per_second"] for m in metrics_list) / len(metrics_list)
        avg_error_rate = sum(m["error_rate_percent"] for m in metrics_list) / len(metrics_list)
        
        baselines[endpoint_name] = {
            "avg_response_time_ms": round(avg_response_time, 2),
            "requests_per_second": round(avg_throughput, 2),
            "error_rate_percent": round(avg_error_rate, 2),
            "sample_size": len(metrics_list)
        }
    
    return {
        "baselines": baselines,
        "total_runs": len(completed_runs),
        "last_updated": max(run["end_time"] for run in completed_runs) if completed_runs else None
    }


@router.post("/quick-test")
async def run_quick_test(
    background_tasks: BackgroundTasks,
    endpoints: Optional[List[str]] = None,
    api_key: APIKey = Depends(get_api_key)
) -> Dict[str, Any]:
    """
    Run a quick latency test with minimal configuration.
    
    Args:
        endpoints: Specific endpoints to test (optional)
        
    Returns:
        Quick test results
    """
    # Quick test configuration
    request = BenchmarkRequest(
        benchmark_type="latency",
        endpoints=endpoints,
        config={
            "total_requests": 20,
            "concurrent_requests": 5,
            "warm_up_requests": 2
        }
    )
    
    return await start_benchmark(request, background_tasks, api_key)


async def _run_benchmark_background(
    run_id: str,
    endpoints: List,
    benchmark_type: BenchmarkType,
    config: BenchmarkConfig
):
    """Run benchmark in background task."""
    try:
        # Update status to running
        benchmark_runs[run_id]["status"] = BenchmarkStatus.RUNNING.value
        
        # Create and run benchmark
        benchmark = PerformanceBenchmark(config)
        active_benchmarks[run_id] = benchmark
        
        metrics = await benchmark.run_benchmark(endpoints, benchmark_type)
        
        # Store results
        end_time = datetime.utcnow()
        start_time = benchmark_runs[run_id]["start_time"]
        duration = (end_time - start_time).total_seconds()
        
        benchmark_runs[run_id].update({
            "status": BenchmarkStatus.COMPLETED.value,
            "end_time": end_time,
            "duration_seconds": duration,
            "metrics": {name: metric.to_dict() for name, metric in metrics.items()}
        })
        
        logger.info(
            "benchmark_completed",
            run_id=run_id,
            duration_seconds=duration,
            endpoints_tested=len(endpoints)
        )
        
    except Exception as e:
        # Mark as failed
        benchmark_runs[run_id].update({
            "status": BenchmarkStatus.FAILED.value,
            "end_time": datetime.utcnow(),
            "error": str(e)
        })
        
        logger.exception("benchmark_failed", run_id=run_id)
    
    finally:
        # Remove from active benchmarks
        if run_id in active_benchmarks:
            del active_benchmarks[run_id]


def _estimate_duration(benchmark_type: BenchmarkType, config: BenchmarkConfig) -> int:
    """Estimate benchmark duration in seconds."""
    base_request_time = 0.1  # 100ms average per request
    
    if benchmark_type == BenchmarkType.LATENCY:
        # Sequential requests
        return int(config.total_requests * base_request_time + config.warm_up_requests * base_request_time)
    
    elif benchmark_type == BenchmarkType.THROUGHPUT:
        # Concurrent requests
        return int((config.total_requests / config.concurrent_requests) * base_request_time + 10)
    
    elif benchmark_type == BenchmarkType.ENDURANCE:
        # Duration-based
        return config.test_duration_seconds or 300
    
    else:
        # Load test, stress test
        return int(config.total_requests * base_request_time / config.concurrent_requests + 30)


def _calculate_summary_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate summary metrics across all endpoints."""
    if not metrics:
        return {}
    
    endpoint_metrics = list(metrics.values())
    
    total_requests = sum(m["total_requests"] for m in endpoint_metrics)
    total_successful = sum(m["successful_requests"] for m in endpoint_metrics)
    total_failed = sum(m["failed_requests"] for m in endpoint_metrics)
    
    avg_response_times = [m["avg_response_time_ms"] for m in endpoint_metrics if m["avg_response_time_ms"] > 0]
    throughputs = [m["requests_per_second"] for m in endpoint_metrics if m["requests_per_second"] > 0]
    
    return {
        "total_requests": total_requests,
        "total_successful": total_successful,
        "total_failed": total_failed,
        "overall_success_rate": (total_successful / total_requests * 100) if total_requests > 0 else 0,
        "avg_response_time_ms": sum(avg_response_times) / len(avg_response_times) if avg_response_times else 0,
        "total_throughput_rps": sum(throughputs),
        "endpoints_tested": len(metrics),
        "fastest_endpoint": min(endpoint_metrics, key=lambda x: x["avg_response_time_ms"])["endpoint"] if endpoint_metrics else None,
        "slowest_endpoint": max(endpoint_metrics, key=lambda x: x["avg_response_time_ms"])["endpoint"] if endpoint_metrics else None
    }


# Export router
__all__ = ["router"]