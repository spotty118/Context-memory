"""
Redis Queue setup and configuration for background workers.
"""
import redis
from rq import Queue, Worker
from rq.job import Job
from typing import List, Optional, Dict, Any
import structlog
import time
from datetime import datetime, timedelta

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Redis connection
redis_conn = redis.from_url(settings.REDIS_URL, decode_responses=True)

# Queue definitions
class QueueNames:
    DEFAULT = "default"
    HIGH = "high"
    LOW = "low"
    EMBEDDINGS = "embeddings"
    SYNC = "sync"
    CLEANUP = "cleanup"
    ANALYTICS = "analytics"

# Queue instances
queues = {
    QueueNames.HIGH: Queue(QueueNames.HIGH, connection=redis_conn),
    QueueNames.DEFAULT: Queue(QueueNames.DEFAULT, connection=redis_conn),
    QueueNames.LOW: Queue(QueueNames.LOW, connection=redis_conn),
    QueueNames.EMBEDDINGS: Queue(QueueNames.EMBEDDINGS, connection=redis_conn),
    QueueNames.SYNC: Queue(QueueNames.SYNC, connection=redis_conn),
    QueueNames.CLEANUP: Queue(QueueNames.CLEANUP, connection=redis_conn),
    QueueNames.ANALYTICS: Queue(QueueNames.ANALYTICS, connection=redis_conn),
}

def get_queue(name: str = QueueNames.DEFAULT) -> Queue:
    """Get a queue by name."""
    return queues.get(name, queues[QueueNames.DEFAULT])

def enqueue_job(
    func,
    *args,
    queue_name: str = QueueNames.DEFAULT,
    job_timeout: Optional[int] = None,
    job_id: Optional[str] = None,
    **kwargs
) -> Job:
    """
    Enqueue a job to be processed by a worker.
    
    Args:
        func: Function to execute
        *args: Arguments for the function
        queue_name: Name of the queue to use
        job_timeout: Timeout for the job in seconds
        job_id: Optional job ID for deduplication
        **kwargs: Keyword arguments for the function
    
    Returns:
        Job instance
    """
    queue = get_queue(queue_name)
    timeout = job_timeout or settings.JOB_TIMEOUT
    
    try:
        job = queue.enqueue(
            func,
            *args,
            job_timeout=timeout,
            job_id=job_id,
            **kwargs
        )
        
        logger.info(
            "job_enqueued",
            job_id=job.id,
            queue=queue_name,
            func=func.__name__,
            timeout=timeout
        )
        
        return job
    
    except Exception as e:
        logger.exception(
            "job_enqueue_failed",
            queue=queue_name,
            func=func.__name__
        )
        raise

def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get the status of a job.
    
    Args:
        job_id: ID of the job
    
    Returns:
        Dictionary with job status information
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        
        return {
            "id": job.id,
            "status": job.get_status(),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
            "result": job.result,
            "exc_info": job.exc_info,
            "meta": job.meta,
        }
    
    except Exception as e:
        logger.exception("job_status_fetch_failed", job_id=job_id)
        return {"id": job_id, "status": "unknown", "error": str(e)}

def cancel_job(job_id: str) -> bool:
    """
    Cancel a job.
    
    Args:
        job_id: ID of the job to cancel
    
    Returns:
        True if job was cancelled, False otherwise
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        job.cancel()
        
        logger.info("job_cancelled", job_id=job_id)
        return True
    
    except Exception as e:
        logger.exception("job_cancel_error", job_id=job_id)
        return False

def get_queue_stats() -> Dict[str, Dict[str, Any]]:
    """
    Get statistics for all queues.
    
    Returns:
        Dictionary with queue statistics
    """
    stats = {}
    
    for name, queue in queues.items():
        try:
            stats[name] = {
                "length": len(queue),
                "failed_count": queue.failed_job_registry.count,
                "deferred_count": queue.deferred_job_registry.count,
                "finished_count": queue.finished_job_registry.count,
                "started_count": queue.started_job_registry.count,
            }
        except Exception as e:
            logger.exception("queue_stats_error", error=str(e))
            stats[name] = {"error": str(e)}
    
    return stats

def clear_queue(queue_name: str) -> int:
    """
    Clear all jobs from a queue.
    
    Args:
        queue_name: Name of the queue to clear
    
    Returns:
        Number of jobs cleared
    """
    queue = get_queue(queue_name)
    
    try:
        count = len(queue)
        queue.empty()
        
        logger.info("queue_cleared", queue=queue_name, jobs_cleared=count)
        return count
    
    except Exception as e:
        logger.exception("queue_clear_failed", queue=queue_name)
        raise

def create_worker(queue_names: List[str]) -> Worker:
    """
    Create a worker for the specified queues.
    
    Args:
        queue_names: List of queue names to process
    
    Returns:
        Worker instance
    """
    worker_queues = [get_queue(name) for name in queue_names]
    
    worker = Worker(
        worker_queues,
        connection=redis_conn,
        name=f"worker-{'-'.join(queue_names)}"
    )
    
    return worker

def start_worker(queue_names: List[str] = None):
    """
    Start a worker process.
    
    Args:
        queue_names: List of queue names to process. Defaults to all queues.
    """
    if queue_names is None:
        queue_names = list(queues.keys())
    
    logger.info("starting_worker", queues=queue_names)
    
    worker = create_worker(queue_names)
    worker.work(with_scheduler=True)

# Job decorators for common patterns
def high_priority_job(func):
    """Decorator to mark a function as a high priority job."""
    func._queue_name = QueueNames.HIGH
    return func

def low_priority_job(func):
    """Decorator to mark a function as a low priority job."""
    func._queue_name = QueueNames.LOW
    return func

def embedding_job(func):
    """Decorator to mark a function as an embedding job."""
    func._queue_name = QueueNames.EMBEDDINGS
    return func

def sync_job(func):
    """Decorator to mark a function as a sync job."""
    func._queue_name = QueueNames.SYNC
    return func

def cleanup_job(func):
    """Decorator to mark a function as a cleanup job."""
    func._queue_name = QueueNames.CLEANUP
    return func

def analytics_job(func):
    """Decorator to mark a function as an analytics job."""
    func._queue_name = QueueNames.ANALYTICS
    return func


# Failed job retry strategies
def get_failed_jobs(queue_name: str = None) -> List[Dict[str, Any]]:
    """
    Get all failed jobs from specified queue or all queues.
    
    Args:
        queue_name: Optional queue name to filter by
    
    Returns:
        List of failed job dictionaries
    """
    failed_jobs = []
    
    queues_to_check = [get_queue(queue_name)] if queue_name else list(queues.values())
    
    for queue in queues_to_check:
        try:
            failed_job_registry = queue.failed_job_registry
            
            for job_id in failed_job_registry.get_job_ids():
                try:
                    job = Job.fetch(job_id, connection=redis_conn)
                    failed_jobs.append({
                        "id": job.id,
                        "queue": queue.name,
                        "func_name": job.func_name,
                        "args": job.args,
                        "kwargs": job.kwargs,
                        "created_at": job.created_at.isoformat() if job.created_at else None,
                        "failed_at": job.ended_at.isoformat() if job.ended_at else None,
                        "exc_info": job.exc_info,
                        "retry_count": job.meta.get("retry_count", 0),
                        "last_retry_at": job.meta.get("last_retry_at"),
                        "next_retry_at": job.meta.get("next_retry_at")
                    })
                except Exception as e:
                    logger.exception("failed_job_fetch_error", job_id=job_id)
                    failed_jobs.append({
                        "id": job_id,
                        "queue": queue.name,
                        "error": f"Failed to fetch job details: {str(e)}"
                    })
        
        except Exception as e:
            logger.exception("failed_jobs_registry_error", queue=queue.name)
    
    return failed_jobs


def retry_failed_job(
    job_id: str, 
    max_retries: int = 3, 
    backoff_factor: float = 2.0,
    retry_jitter: bool = True
) -> Dict[str, Any]:
    """
    Retry a failed job with exponential backoff strategy.
    
    Args:
        job_id: ID of the failed job
        max_retries: Maximum number of retry attempts
        backoff_factor: Exponential backoff factor
        retry_jitter: Whether to add jitter to prevent thundering herd
    
    Returns:
        Dictionary with retry result
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        
        # Get current retry count from job metadata
        retry_count = job.meta.get("retry_count", 0)
        
        if retry_count >= max_retries:
            return {
                "job_id": job_id,
                "status": "max_retries_exceeded",
                "retry_count": retry_count,
                "max_retries": max_retries,
                "message": f"Job has already been retried {retry_count} times"
            }
        
        # Calculate backoff delay
        base_delay = backoff_factor ** retry_count
        
        # Add jitter if enabled (±25% random variation)
        if retry_jitter:
            import random
            jitter = random.uniform(0.75, 1.25)
            delay = base_delay * jitter
        else:
            delay = base_delay
        
        # Update job metadata
        job.meta["retry_count"] = retry_count + 1
        job.meta["last_retry_at"] = datetime.utcnow().isoformat()
        job.meta["next_retry_at"] = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
        job.meta["backoff_factor"] = backoff_factor
        job.save_meta()
        
        # Get the original queue
        queue_name = job.meta.get("original_queue", QueueNames.DEFAULT)
        queue = get_queue(queue_name)
        
        # Re-enqueue the job with delay
        new_job = queue.enqueue_in(
            timedelta(seconds=delay),
            job.func,
            *job.args,
            **job.kwargs,
            job_timeout=job.timeout,
            meta=job.meta
        )
        
        # Remove from failed job registry
        queue.failed_job_registry.remove(job_id)
        
        logger.info(
            "job_retry_scheduled",
            job_id=job_id,
            new_job_id=new_job.id,
            retry_count=retry_count + 1,
            delay_seconds=delay,
            max_retries=max_retries
        )
        
        return {
            "job_id": job_id,
            "new_job_id": new_job.id,
            "status": "retry_scheduled",
            "retry_count": retry_count + 1,
            "delay_seconds": delay,
            "scheduled_for": (datetime.utcnow() + timedelta(seconds=delay)).isoformat(),
            "max_retries": max_retries
        }
    
    except Exception as e:
        logger.exception("job_retry_error", job_id=job_id)
        return {
            "job_id": job_id,
            "status": "retry_failed",
            "error": str(e)
        }


def retry_all_failed_jobs(
    queue_name: str = None,
    max_retries: int = 3,
    batch_size: int = 10
) -> Dict[str, Any]:
    """
    Retry all failed jobs in a queue with batch processing.
    
    Args:
        queue_name: Optional queue name to filter by
        max_retries: Maximum number of retry attempts per job
        batch_size: Number of jobs to process in each batch
    
    Returns:
        Dictionary with batch retry results
    """
    failed_jobs = get_failed_jobs(queue_name)
    
    results = {
        "total_failed_jobs": len(failed_jobs),
        "processed": 0,
        "successful_retries": 0,
        "failed_retries": 0,
        "max_retries_exceeded": 0,
        "results": []
    }
    
    # Process in batches to avoid overwhelming the system
    for i in range(0, len(failed_jobs), batch_size):
        batch = failed_jobs[i:i + batch_size]
        
        for job_info in batch:
            if "error" in job_info:
                # Skip jobs that couldn't be fetched
                results["failed_retries"] += 1
                continue
            
            retry_result = retry_failed_job(job_info["id"], max_retries)
            results["results"].append(retry_result)
            results["processed"] += 1
            
            if retry_result["status"] == "retry_scheduled":
                results["successful_retries"] += 1
            elif retry_result["status"] == "max_retries_exceeded":
                results["max_retries_exceeded"] += 1
            else:
                results["failed_retries"] += 1
        
        # Add small delay between batches
        if i + batch_size < len(failed_jobs):
            time.sleep(0.1)
    
    logger.info(
        "bulk_retry_completed",
        queue=queue_name or "all",
        total=results["total_failed_jobs"],
        successful=results["successful_retries"],
        failed=results["failed_retries"],
        max_retries_exceeded=results["max_retries_exceeded"]
    )
    
    return results


def cleanup_old_failed_jobs(older_than_days: int = 7) -> Dict[str, Any]:
    """
    Clean up failed jobs older than specified days.
    
    Args:
        older_than_days: Number of days to keep failed jobs
    
    Returns:
        Dictionary with cleanup results
    """
    cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
    cleanup_results = {
        "cleaned_queues": [],
        "total_cleaned": 0,
        "cutoff_date": cutoff_date.isoformat()
    }
    
    for name, queue in queues.items():
        try:
            failed_job_registry = queue.failed_job_registry
            job_ids = failed_job_registry.get_job_ids()
            
            cleaned_count = 0
            for job_id in job_ids:
                try:
                    job = Job.fetch(job_id, connection=redis_conn)
                    if job.ended_at and job.ended_at < cutoff_date:
                        failed_job_registry.remove(job_id)
                        cleaned_count += 1
                except Exception as e:
                    logger.exception("failed_job_cleanup_error", job_id=job_id)
            
            if cleaned_count > 0:
                cleanup_results["cleaned_queues"].append({
                    "queue": name,
                    "cleaned_count": cleaned_count
                })
                cleanup_results["total_cleaned"] += cleaned_count
        
        except Exception as e:
            logger.exception("queue_cleanup_error", error=str(e))
    
    logger.info(
        "failed_jobs_cleanup_completed",
        total_cleaned=cleanup_results["total_cleaned"],
        older_than_days=older_than_days
    )
    
    return cleanup_results

