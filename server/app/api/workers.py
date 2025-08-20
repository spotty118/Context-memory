"""
API endpoints for worker and job management.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
import structlog

from app.core.security import get_current_api_key
from app.workers.queue import (
    enqueue_job, get_job_status, cancel_job, get_queue_stats, 
    clear_queue, QueueNames
)
from app.workers.scheduler import task_scheduler
from app.workers.model_sync import sync_model_catalog, cleanup_deprecated_models
from app.workers.embeddings import generate_embeddings_for_item, batch_generate_embeddings
from app.workers.cleanup import cleanup_old_context_items, cleanup_old_request_logs
from app.workers.analytics import aggregate_daily_usage_stats, calculate_context_memory_stats

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
        logger.error("queue_stats_failed", error=str(e))
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
        logger.error("queue_clear_failed", queue=queue_name, error=str(e))
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
        logger.error("job_enqueue_failed", job_type=job_request.job_type, error=str(e))
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
        logger.error("job_status_failed", job_id=job_id, error=str(e))
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
        logger.error("job_cancel_failed", job_id=job_id, error=str(e))
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
        logger.error("scheduler_status_failed", error=str(e))
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
        logger.error("task_reschedule_failed", task_name=task_name, error=str(e))
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
        logger.error("model_sync_trigger_failed", error=str(e))
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
        logger.error("embedding_generation_trigger_failed", error=str(e))
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
        logger.error("context_cleanup_trigger_failed", error=str(e))
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
        logger.error("usage_aggregation_trigger_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to trigger usage aggregation")

@router.get("/health")
async def worker_health_check():
    """Health check for worker system."""
    try:
        # Check queue connectivity
        stats = get_queue_stats()
        
        # Check scheduler status
        scheduler_status = task_scheduler.get_scheduled_jobs_status()
        
        return {
            "status": "healthy",
            "queues": {
                "total": len(stats),
                "accessible": len([q for q in stats.values() if "error" not in q])
            },
            "scheduler": {
                "total_jobs": scheduler_status["total_jobs"],
                "status": "running" if scheduler_status["total_jobs"] > 0 else "idle"
            },
            "timestamp": scheduler_status["status_time"]
        }
    
    except Exception as e:
        logger.error("worker_health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": str(e)
        }

