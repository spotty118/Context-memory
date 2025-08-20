"""
Redis Queue setup and configuration for background workers.
"""
import redis
from rq import Queue, Worker
from rq.job import Job
from typing import List, Optional, Dict, Any
import structlog

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
        logger.error(
            "job_enqueue_failed",
            queue=queue_name,
            func=func.__name__,
            error=str(e)
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
        logger.error("job_status_fetch_failed", job_id=job_id, error=str(e))
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
        logger.error("job_cancel_failed", job_id=job_id, error=str(e))
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
            logger.error("queue_stats_failed", queue=name, error=str(e))
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
        logger.error("queue_clear_failed", queue=queue_name, error=str(e))
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

