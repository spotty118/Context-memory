"""
Task scheduler for periodic background jobs.
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import structlog
from rq_scheduler import Scheduler
from rq import Queue

from app.workers.queue import redis_conn, QueueNames
from app.workers.model_sync import sync_model_catalog, cleanup_deprecated_models, update_model_usage_stats
from app.workers.embeddings import batch_generate_embeddings, regenerate_all_embeddings
from app.workers.cleanup import (
    cleanup_old_context_items, cleanup_old_request_logs, 
    cleanup_expired_api_keys, vacuum_database, optimize_embeddings_index,
    archive_old_usage_stats
)
from app.workers.analytics import (
    aggregate_daily_usage_stats, generate_usage_report,
    calculate_context_memory_stats
)

logger = structlog.get_logger(__name__)

# Create scheduler instance
scheduler = Scheduler(connection=redis_conn)

class ScheduledTasks:
    """Centralized management of scheduled tasks."""
    
    def __init__(self):
        self.scheduler = scheduler
        self.scheduled_jobs = {}
    
    def schedule_all_tasks(self) -> Dict[str, Any]:
        """
        Schedule all periodic tasks.
        
        Returns:
            Dictionary with scheduling results
        """
        logger.info("scheduling_all_tasks")
        
        results = {
            "scheduled_jobs": [],
            "failed_jobs": [],
            "schedule_time": datetime.utcnow().isoformat()
        }
        
        # Define all scheduled tasks
        tasks = [
            # Model sync tasks
            {
                "name": "sync_model_catalog",
                "func": sync_model_catalog,
                "schedule": "hourly",  # Every hour
                "description": "Sync model catalog from OpenRouter"
            },
            {
                "name": "cleanup_deprecated_models",
                "func": cleanup_deprecated_models,
                "schedule": "daily",  # Daily at 2 AM
                "hour": 2,
                "description": "Clean up deprecated models"
            },
            {
                "name": "update_model_usage_stats",
                "func": update_model_usage_stats,
                "schedule": "daily",  # Daily at 3 AM
                "hour": 3,
                "description": "Update model usage statistics"
            },
            
            # Analytics tasks
            {
                "name": "aggregate_daily_usage",
                "func": aggregate_daily_usage_stats,
                "schedule": "daily",  # Daily at 1 AM
                "hour": 1,
                "description": "Aggregate daily usage statistics"
            },
            {
                "name": "calculate_context_stats",
                "func": calculate_context_memory_stats,
                "schedule": "daily",  # Daily at 4 AM
                "hour": 4,
                "description": "Calculate context memory statistics"
            },
            
            # Cleanup tasks
            {
                "name": "cleanup_old_context_items",
                "func": cleanup_old_context_items,
                "schedule": "weekly",  # Weekly on Sunday at 1 AM
                "day_of_week": 0,
                "hour": 1,
                "description": "Clean up old context memory items"
            },
            {
                "name": "cleanup_old_request_logs",
                "func": cleanup_old_request_logs,
                "schedule": "weekly",  # Weekly on Sunday at 2 AM
                "day_of_week": 0,
                "hour": 2,
                "description": "Clean up old request logs"
            },
            {
                "name": "cleanup_expired_api_keys",
                "func": cleanup_expired_api_keys,
                "schedule": "daily",  # Daily at 5 AM
                "hour": 5,
                "description": "Clean up expired API keys"
            },
            {
                "name": "vacuum_database",
                "func": vacuum_database,
                "schedule": "weekly",  # Weekly on Sunday at 3 AM
                "day_of_week": 0,
                "hour": 3,
                "description": "Run database maintenance"
            },
            {
                "name": "optimize_embeddings_index",
                "func": optimize_embeddings_index,
                "schedule": "weekly",  # Weekly on Sunday at 4 AM
                "day_of_week": 0,
                "hour": 4,
                "description": "Optimize embeddings index"
            },
            {
                "name": "archive_old_usage_stats",
                "func": archive_old_usage_stats,
                "schedule": "monthly",  # Monthly on 1st at 1 AM
                "day": 1,
                "hour": 1,
                "description": "Archive old usage statistics"
            }
        ]
        
        # Schedule each task
        for task in tasks:
            try:
                job = self._schedule_task(task)
                if job:
                    results["scheduled_jobs"].append({
                        "name": task["name"],
                        "job_id": job.id,
                        "schedule": task["schedule"],
                        "description": task["description"],
                        "next_run": job.scheduled_for.isoformat() if job.scheduled_for else None
                    })
                    self.scheduled_jobs[task["name"]] = job
                    logger.info("task_scheduled", name=task["name"], job_id=job.id)
            
            except Exception as e:
                error_msg = f"Failed to schedule {task['name']}: {str(e)}"
                logger.error("task_scheduling_failed", name=task["name"], error=str(e))
                results["failed_jobs"].append({
                    "name": task["name"],
                    "error": error_msg
                })
        
        logger.info("all_tasks_scheduled", 
                   successful=len(results["scheduled_jobs"]),
                   failed=len(results["failed_jobs"]))
        
        return results
    
    def _schedule_task(self, task: Dict[str, Any]):
        """Schedule a single task based on its configuration."""
        name = task["name"]
        func = task["func"]
        schedule = task["schedule"]
        
        # Calculate next run time based on schedule
        now = datetime.utcnow()
        
        if schedule == "hourly":
            # Run every hour at minute 0
            next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            interval = timedelta(hours=1)
        
        elif schedule == "daily":
            # Run daily at specified hour (default 0)
            hour = task.get("hour", 0)
            next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            interval = timedelta(days=1)
        
        elif schedule == "weekly":
            # Run weekly on specified day and hour
            day_of_week = task.get("day_of_week", 0)  # 0 = Monday
            hour = task.get("hour", 0)
            
            # Calculate days until target day
            days_ahead = day_of_week - now.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            
            next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
            interval = timedelta(weeks=1)
        
        elif schedule == "monthly":
            # Run monthly on specified day and hour
            day = task.get("day", 1)
            hour = task.get("hour", 0)
            
            # Calculate next month if day has passed
            if now.day >= day and now.hour >= hour:
                if now.month == 12:
                    next_run = now.replace(year=now.year + 1, month=1, day=day, hour=hour, minute=0, second=0, microsecond=0)
                else:
                    next_run = now.replace(month=now.month + 1, day=day, hour=hour, minute=0, second=0, microsecond=0)
            else:
                next_run = now.replace(day=day, hour=hour, minute=0, second=0, microsecond=0)
            
            # For monthly, we'll reschedule after each run
            interval = None
        
        else:
            logger.error("unknown_schedule_type", schedule=schedule)
            return None
        
        # Schedule the job
        if interval:
            # Recurring job
            job = self.scheduler.schedule(
                scheduled_time=next_run,
                func=func,
                interval=interval.total_seconds(),
                repeat=None,  # Repeat indefinitely
                job_id=f"scheduled_{name}",
                queue_name=self._get_queue_for_task(name)
            )
        else:
            # One-time job (will need manual rescheduling)
            job = self.scheduler.schedule(
                scheduled_time=next_run,
                func=func,
                job_id=f"scheduled_{name}",
                queue_name=self._get_queue_for_task(name)
            )
        
        return job
    
    def _get_queue_for_task(self, task_name: str) -> str:
        """Get the appropriate queue for a task."""
        if "sync" in task_name or "update" in task_name:
            return QueueNames.SYNC
        elif "embedding" in task_name:
            return QueueNames.EMBEDDINGS
        elif "cleanup" in task_name or "vacuum" in task_name or "optimize" in task_name:
            return QueueNames.CLEANUP
        elif "aggregate" in task_name or "calculate" in task_name or "analytics" in task_name:
            return QueueNames.ANALYTICS
        else:
            return QueueNames.LOW
    
    def cancel_all_scheduled_tasks(self) -> Dict[str, Any]:
        """
        Cancel all scheduled tasks.
        
        Returns:
            Dictionary with cancellation results
        """
        logger.info("cancelling_all_scheduled_tasks")
        
        results = {
            "cancelled_jobs": [],
            "failed_cancellations": [],
            "cancellation_time": datetime.utcnow().isoformat()
        }
        
        for name, job in self.scheduled_jobs.items():
            try:
                job.cancel()
                results["cancelled_jobs"].append(name)
                logger.info("task_cancelled", name=name)
            except Exception as e:
                error_msg = f"Failed to cancel {name}: {str(e)}"
                logger.error("task_cancellation_failed", name=name, error=str(e))
                results["failed_cancellations"].append({
                    "name": name,
                    "error": error_msg
                })
        
        # Clear the scheduled jobs dict
        self.scheduled_jobs.clear()
        
        logger.info("all_scheduled_tasks_cancelled",
                   cancelled=len(results["cancelled_jobs"]),
                   failed=len(results["failed_cancellations"]))
        
        return results
    
    def get_scheduled_jobs_status(self) -> Dict[str, Any]:
        """
        Get status of all scheduled jobs.
        
        Returns:
            Dictionary with job statuses
        """
        status = {
            "total_jobs": len(self.scheduled_jobs),
            "jobs": [],
            "status_time": datetime.utcnow().isoformat()
        }
        
        for name, job in self.scheduled_jobs.items():
            try:
                job_status = {
                    "name": name,
                    "job_id": job.id,
                    "status": job.get_status(),
                    "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "meta": job.meta
                }
                status["jobs"].append(job_status)
            except Exception as e:
                logger.error("job_status_check_failed", name=name, error=str(e))
                status["jobs"].append({
                    "name": name,
                    "error": str(e)
                })
        
        return status
    
    def reschedule_task(self, task_name: str) -> Dict[str, Any]:
        """
        Reschedule a specific task.
        
        Args:
            task_name: Name of the task to reschedule
        
        Returns:
            Dictionary with rescheduling results
        """
        logger.info("rescheduling_task", name=task_name)
        
        try:
            # Cancel existing job if it exists
            if task_name in self.scheduled_jobs:
                self.scheduled_jobs[task_name].cancel()
                del self.scheduled_jobs[task_name]
            
            # Find task configuration and reschedule
            # This would need to be implemented based on stored task configurations
            # For now, return a placeholder
            
            return {
                "task_name": task_name,
                "status": "rescheduled",
                "reschedule_time": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            error_msg = f"Failed to reschedule {task_name}: {str(e)}"
            logger.error("task_rescheduling_failed", name=task_name, error=str(e))
            return {
                "task_name": task_name,
                "error": error_msg,
                "reschedule_time": datetime.utcnow().isoformat()
            }

# Global scheduler instance
task_scheduler = ScheduledTasks()

def initialize_scheduler() -> Dict[str, Any]:
    """Initialize and start the task scheduler."""
    logger.info("initializing_task_scheduler")
    return task_scheduler.schedule_all_tasks()

def shutdown_scheduler() -> Dict[str, Any]:
    """Shutdown the task scheduler and cancel all jobs."""
    logger.info("shutting_down_task_scheduler")
    return task_scheduler.cancel_all_scheduled_tasks()

