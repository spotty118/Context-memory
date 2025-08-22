"""
API endpoints for worker and job management.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from pydantic import BaseModel
import structlog

from app.core.security import get_current_api_key
from app.workers.queue import (
    enqueue_job, get_job_status, cancel_job, get_queue_stats, 
    clear_queue, QueueNames, redis_conn, get_failed_jobs,
    retry_failed_job, retry_all_failed_jobs, cleanup_old_failed_jobs
)
from app.workers.scheduler import task_scheduler
from app.workers.model_sync import sync_model_catalog, cleanup_deprecated_models
from app.workers.embeddings import generate_embeddings_for_item, batch_generate_embeddings
from app.workers.cleanup import cleanup_old_context_items, cleanup_old_request_logs
from app.workers.analytics import aggregate_daily_usage_stats, calculate_context_memory_stats
from app.telemetry.otel import record_worker_system_metrics

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workers", tags=["workers"])

# Request/Response models
class JobRequest(BaseModel):
    job_type: str
    parameters: Dict[str, Any] = {}
    queue_name: str = QueueNames.DEFAULT
    job_timeout: Optional[int] = None

class JobResponse(BaseModel):
    job_id: str
    status: str
    queue: str
    created_at: Optional[str] = None

class QueueStatsResponse(BaseModel):
    queues: Dict[str, Dict[str, Any]]

class SchedulerStatusResponse(BaseModel):
    total_jobs: int
    jobs: List[Dict[str, Any]]
    status_time: str

@router.get("/queues/stats", response_model=QueueStatsResponse)
async def get_queue_statistics(
    api_key = Depends(get_current_api_key)
):
    """Get statistics for all job queues."""
    try:
        stats = get_queue_stats()
        return QueueStatsResponse(queues=stats)
    
    except Exception as e:
        logger.exception("queue_stats_failed")
        raise HTTPException(status_code=500, detail="Failed to get queue statistics")

@router.post("/queues/{queue_name}/clear")
async def clear_job_queue(
    queue_name: str,
    api_key = Depends(get_current_api_key)
):
    """Clear all jobs from a specific queue."""
    try:
        if queue_name not in QueueNames.__dict__.values():
            raise HTTPException(status_code=400, detail="Invalid queue name")
        
        cleared_count = clear_queue(queue_name)
        
        return {
            "queue": queue_name,
            "jobs_cleared": cleared_count,
            "status": "success"
        }
    
    except Exception as e:
        logger.exception("queue_clear_failed", queue=queue_name)
        raise HTTPException(status_code=500, detail="Failed to clear queue")

@router.post("/jobs", response_model=JobResponse)
async def enqueue_background_job(
    job_request: JobRequest,
    api_key = Depends(get_current_api_key)
):
    """Enqueue a background job for processing."""
    try:
        # Map job types to functions
        job_functions = {
            "sync_model_catalog": sync_model_catalog,
            "cleanup_deprecated_models": cleanup_deprecated_models,
            "generate_embeddings": generate_embeddings_for_item,
            "batch_generate_embeddings": batch_generate_embeddings,
            "cleanup_old_context_items": cleanup_old_context_items,
            "cleanup_old_request_logs": cleanup_old_request_logs,
            "aggregate_daily_usage_stats": aggregate_daily_usage_stats,
            "calculate_context_memory_stats": calculate_context_memory_stats,
        }
        
        if job_request.job_type not in job_functions:
            raise HTTPException(
                status_code=400, 
                detail=f"Unknown job type: {job_request.job_type}"
            )
        
        func = job_functions[job_request.job_type]
        
        # Enqueue the job
        job = enqueue_job(
            func,
            **job_request.parameters,
            queue_name=job_request.queue_name,
            job_timeout=job_request.job_timeout
        )
        
        return JobResponse(
            job_id=job.id,
            status=job.get_status(),
            queue=job_request.queue_name,
            created_at=job.created_at.isoformat() if job.created_at else None
        )
    
    except Exception as e:
        logger.exception("job_enqueue_failed", job_type=job_request.job_type)
        raise HTTPException(status_code=500, detail="Failed to enqueue job")

@router.get("/jobs/{job_id}")
async def get_job_details(
    job_id: str,
    api_key = Depends(get_current_api_key)
):
    """Get details and status of a specific job."""
    try:
        job_status = get_job_status(job_id)
        return job_status
    
    except Exception as e:
        logger.exception("job_status_failed", job_id=job_id)
        raise HTTPException(status_code=500, detail="Failed to get job status")

@router.delete("/jobs/{job_id}")
async def cancel_background_job(
    job_id: str,
    api_key = Depends(get_current_api_key)
):
    """Cancel a background job."""
    try:
        success = cancel_job(job_id)
        
        if success:
            return {
                "job_id": job_id,
                "status": "cancelled",
                "message": "Job cancelled successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="Job not found or already completed")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("job_cancel_failed", job_id=job_id)
        raise HTTPException(status_code=500, detail="Failed to cancel job")

@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(
    api_key = Depends(get_current_api_key)
):
    """Get status of all scheduled jobs."""
    try:
        status = task_scheduler.get_scheduled_jobs_status()
        return SchedulerStatusResponse(**status)
    
    except Exception as e:
        logger.exception("scheduler_status_failed")
        raise HTTPException(status_code=500, detail="Failed to get scheduler status")

@router.post("/scheduler/reschedule/{task_name}")
async def reschedule_task(
    task_name: str,
    api_key = Depends(get_current_api_key)
):
    """Reschedule a specific scheduled task."""
    try:
        result = task_scheduler.reschedule_task(task_name)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("task_reschedule_failed", task_name=task_name)
        raise HTTPException(status_code=500, detail="Failed to reschedule task")

# Convenience endpoints for common operations
@router.post("/sync/models")
async def trigger_model_sync(
    background_tasks: BackgroundTasks,
    api_key = Depends(get_current_api_key)
):
    """Trigger immediate model catalog sync."""
    try:
        job = enqueue_job(
            sync_model_catalog,
            queue_name=QueueNames.SYNC
        )
        
        return {
            "job_id": job.id,
            "message": "Model sync job enqueued",
            "status": "enqueued"
        }
    
    except Exception as e:
        logger.exception("model_sync_trigger_failed")
        raise HTTPException(status_code=500, detail="Failed to trigger model sync")

@router.post("/embeddings/generate")
async def trigger_embedding_generation(
    item_type: str,
    item_ids: List[str],
    api_key = Depends(get_current_api_key)
):
    """Trigger embedding generation for specific items."""
    try:
        if item_type not in ["semantic", "episodic", "artifact"]:
            raise HTTPException(status_code=400, detail="Invalid item type")
        
        job = enqueue_job(
            batch_generate_embeddings,
            item_type=item_type,
            item_ids=item_ids,
            queue_name=QueueNames.EMBEDDINGS
        )
        
        return {
            "job_id": job.id,
            "message": f"Embedding generation job enqueued for {len(item_ids)} items",
            "status": "enqueued",
            "item_type": item_type,
            "item_count": len(item_ids)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("embedding_generation_trigger_failed")
        raise HTTPException(status_code=500, detail="Failed to trigger embedding generation")

@router.post("/cleanup/context")
async def trigger_context_cleanup(
    days_old: int = 30,
    api_key = Depends(get_current_api_key)
):
    """Trigger cleanup of old context memory items."""
    try:
        job = enqueue_job(
            cleanup_old_context_items,
            days_old=days_old,
            queue_name=QueueNames.CLEANUP
        )
        
        return {
            "job_id": job.id,
            "message": f"Context cleanup job enqueued (items older than {days_old} days)",
            "status": "enqueued",
            "days_old": days_old
        }
    
    except Exception as e:
        logger.exception("context_cleanup_trigger_failed")
        raise HTTPException(status_code=500, detail="Failed to trigger context cleanup")

@router.post("/analytics/aggregate")
async def trigger_usage_aggregation(
    date: Optional[str] = None,
    api_key = Depends(get_current_api_key)
):
    """Trigger usage statistics aggregation for a specific date."""
    try:
        job = enqueue_job(
            aggregate_daily_usage_stats,
            date=date,
            queue_name=QueueNames.ANALYTICS
        )
        
        return {
            "job_id": job.id,
            "message": f"Usage aggregation job enqueued for {date or 'yesterday'}",
            "status": "enqueued",
            "date": date
        }
    
    except Exception as e:
        logger.exception("usage_aggregation_trigger_failed")
        raise HTTPException(status_code=500, detail="Failed to trigger usage aggregation")

@router.get("/health")
async def worker_health_check():
    """Comprehensive health check for worker system."""
    try:
        # Check queue connectivity and detailed stats
        stats = get_queue_stats()
        
        # Check scheduler status
        scheduler_status = task_scheduler.get_scheduled_jobs_status()
        
        # Check Redis connectivity
        try:
            redis_info = redis_conn.info()
            redis_status = {
                "connected": True,
                "used_memory": redis_info.get("used_memory_human"),
                "connected_clients": redis_info.get("connected_clients"),
                "uptime_in_seconds": redis_info.get("uptime_in_seconds")
            }
        except Exception as e:
            redis_status = {
                "connected": False,
                "error": str(e)
            }
        
        # Calculate queue health metrics
        total_queued = sum(q.get("length", 0) for q in stats.values() if "error" not in q)
        total_failed = sum(q.get("failed_count", 0) for q in stats.values() if "error" not in q)
        total_finished = sum(q.get("finished_count", 0) for q in stats.values() if "error" not in q)
        
        # Determine overall health status
        health_status = "healthy"
        health_issues = []
        
        if not redis_status["connected"]:
            health_status = "unhealthy"
            health_issues.append("Redis connection failed")
        
        if len([q for q in stats.values() if "error" in q]) > 0:
            health_status = "degraded"
            health_issues.append("Some queues have errors")
        
        if total_failed > 100:  # Threshold for too many failures
            health_status = "degraded"
            health_issues.append(f"High failure count: {total_failed}")
        
        # Get active workers information
        from rq import Worker
        active_workers = Worker.all(connection=redis_conn)
        worker_info = []
        
        for worker in active_workers:
            try:
                worker_info.append({
                    "name": worker.name,
                    "state": worker.get_state(),
                    "current_job": worker.get_current_job_id(),
                    "successful_jobs": worker.successful_job_count,
                    "failed_jobs": worker.failed_job_count,
                    "total_working_time": worker.total_working_time,
                    "birth_date": worker.birth_date.isoformat() if worker.birth_date else None,
                    "last_heartbeat": worker.last_heartbeat.isoformat() if worker.last_heartbeat else None
                })
            except Exception as e:
                worker_info.append({
                    "name": getattr(worker, 'name', 'unknown'),
                    "error": str(e)
                })
        
        result = {
            "status": health_status,
            "issues": health_issues,
            "timestamp": datetime.utcnow().isoformat(),
            "queues": {
                "total": len(stats),
                "accessible": len([q for q in stats.values() if "error" not in q]),
                "total_queued_jobs": total_queued,
                "total_failed_jobs": total_failed,
                "total_finished_jobs": total_finished,
                "details": stats
            },
            "workers": {
                "active_count": len(active_workers),
                "workers": worker_info
            },
            "scheduler": {
                "total_jobs": scheduler_status["total_jobs"],
                "status": "running" if scheduler_status["total_jobs"] > 0 else "idle",
                "next_scheduled": scheduler_status.get("next_run_time")
            },
            "redis": redis_status
        }
        
        # Record comprehensive worker metrics
        try:
            # Calculate health score based on multiple factors
            health_score = 100
            
            # Redis connectivity (40% weight)
            if not redis_status["connected"]:
                health_score -= 40
            
            # Queue errors (20% weight)
            error_queues = len([q for q in stats.values() if "error" in q])
            if error_queues > 0:
                health_score -= min(error_queues * 10, 20)
            
            # Failure rate (20% weight)
            if total_finished > 0:
                failure_rate = total_failed / (total_failed + total_finished)
                health_score -= min(failure_rate * 20, 20)
            
            # Worker availability (20% weight)
            if len(active_workers) == 0:
                health_score -= 20  # Major deduction for no workers
            elif all(w.get("state") == "busy" for w in worker_info if "error" not in w):
                health_score -= 5  # Minor penalty for all workers busy
            
            health_score = max(health_score, 0)
            
            # Record metrics
            record_worker_system_metrics(
                queue_stats=stats,
                worker_info=worker_info,
                health_score=health_score
            )
            
        except Exception as e:
            logger.warning("worker_metrics_recording_failed", exc_info=True)
 
        return result
    
    except Exception as e:
        logger.exception("worker_health_check_failed")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


# Failed job management endpoints
@router.get("/jobs/failed")
async def get_failed_jobs_list(
    queue_name: Optional[str] = Query(None, description="Filter by queue name"),
    api_key = Depends(get_current_api_key)
):
    """Get list of all failed jobs with details."""
    try:
        failed_jobs = get_failed_jobs(queue_name)
        
        return {
            "failed_jobs": failed_jobs,
            "total_count": len(failed_jobs),
            "queue_filter": queue_name,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.exception("failed_jobs_list_failed")
        raise HTTPException(status_code=500, detail="Failed to get failed jobs list")


@router.post("/jobs/{job_id}/retry")
async def retry_failed_job_endpoint(
    job_id: str,
    max_retries: int = Query(3, description="Maximum number of retry attempts"),
    backoff_factor: float = Query(2.0, description="Exponential backoff factor"),
    retry_jitter: bool = Query(True, description="Add jitter to prevent thundering herd"),
    api_key = Depends(get_current_api_key)
):
    """Retry a specific failed job with exponential backoff."""
    try:
        result = retry_failed_job(
            job_id=job_id,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            retry_jitter=retry_jitter
        )
        
        if result["status"] == "retry_failed":
            raise HTTPException(status_code=400, detail=result.get("error", "Retry failed"))
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("job_retry_endpoint_failed", job_id=job_id)
        raise HTTPException(status_code=500, detail="Failed to retry job")


@router.post("/jobs/failed/retry-all")
async def retry_all_failed_jobs_endpoint(
    queue_name: Optional[str] = Query(None, description="Filter by queue name"),
    max_retries: int = Query(3, description="Maximum number of retry attempts per job"),
    batch_size: int = Query(10, description="Number of jobs to process in each batch"),
    api_key = Depends(get_current_api_key)
):
    """Retry all failed jobs in a queue with batch processing."""
    try:
        result = retry_all_failed_jobs(
            queue_name=queue_name,
            max_retries=max_retries,
            batch_size=batch_size
        )
        
        return result
    
    except Exception as e:
        logger.exception("bulk_retry_endpoint_failed")
        raise HTTPException(status_code=500, detail="Failed to retry failed jobs")


@router.delete("/jobs/failed/cleanup")
async def cleanup_old_failed_jobs_endpoint(
    older_than_days: int = Query(7, description="Clean up failed jobs older than this many days"),
    api_key = Depends(get_current_api_key)
):
    """Clean up old failed jobs to free up memory."""
    try:
        result = cleanup_old_failed_jobs(older_than_days=older_than_days)
        
        return {
            "message": f"Cleaned up {result['total_cleaned']} failed jobs older than {older_than_days} days",
            **result
        }
    
    except Exception as e:
        logger.exception("failed_jobs_cleanup_endpoint_failed")
        raise HTTPException(status_code=500, detail="Failed to cleanup old failed jobs")


# Enhanced monitoring endpoints
@router.get("/metrics/detailed")
async def get_detailed_worker_metrics(
    api_key = Depends(get_current_api_key)
):
    """Get detailed worker and queue metrics for monitoring dashboards."""
    try:
        # Get basic queue stats
        queue_stats = get_queue_stats()
        
        # Get failed jobs summary
        failed_jobs_summary = {}
        for queue_name in QueueNames.__dict__.values():
            if isinstance(queue_name, str):
                failed_jobs = get_failed_jobs(queue_name)
                failed_jobs_summary[queue_name] = {
                    "count": len(failed_jobs),
                    "recent_failures": len([
                        job for job in failed_jobs 
                        if job.get("failed_at") and 
                        datetime.fromisoformat(job["failed_at"].replace('Z', '+00:00')) > 
                        datetime.utcnow().replace(tzinfo=None) - timedelta(hours=24)
                    ])
                }
        
        # Get worker performance metrics
        from rq import Worker
        workers = Worker.all(connection=redis_conn)
        worker_metrics = {
            "total_workers": len(workers),
            "idle_workers": len([w for w in workers if w.get_state() == 'idle']),
            "busy_workers": len([w for w in workers if w.get_state() == 'busy']),
            "total_successful_jobs": sum(w.successful_job_count for w in workers),
            "total_failed_jobs": sum(w.failed_job_count for w in workers),
            "average_job_duration": sum(w.total_working_time for w in workers) / len(workers) if workers else 0
        }
        
        # Calculate overall health score (0-100)
        health_score = 100
        total_failed = sum(q.get("failed_count", 0) for q in queue_stats.values() if "error" not in q)
        total_finished = sum(q.get("finished_count", 0) for q in queue_stats.values() if "error" not in q)
        
        if total_finished > 0:
            failure_rate = total_failed / (total_failed + total_finished)
            health_score -= min(failure_rate * 50, 30)  # Max 30 point deduction for failures
        
        if worker_metrics["total_workers"] == 0:
            health_score -= 40  # Major deduction for no workers
        elif worker_metrics["idle_workers"] == 0 and worker_metrics["busy_workers"] > 0:
            health_score -= 10  # Minor deduction for all workers busy
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health_score": max(health_score, 0),
            "queue_stats": queue_stats,
            "failed_jobs_summary": failed_jobs_summary,
            "worker_metrics": worker_metrics,
            "total_failed_jobs": total_failed,
            "total_finished_jobs": total_finished,
            "failure_rate": total_failed / (total_failed + total_finished) if (total_failed + total_finished) > 0 else 0
        }
    
    except Exception as e:
        logger.exception("detailed_metrics_failed")
        raise HTTPException(status_code=500, detail="Failed to get detailed worker metrics")
