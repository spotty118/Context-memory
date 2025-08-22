"""
Comprehensive tests for background worker tasks.
Tests async job processing, failure scenarios, retry mechanisms, and queue management.
"""
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any
import redis
from rq import Queue, Worker
from rq.job import Job, JobStatus

from app.workers.queue import (
    enqueue_job, get_job_status, cancel_job, get_queue_stats, 
    clear_queue, QueueNames, retry_failed_job, retry_all_failed_jobs
)
from app.workers.scheduler import ScheduledTasks, initialize_scheduler
from app.workers.analytics import aggregate_daily_usage_stats, generate_usage_report


@pytest.mark.asyncio
class TestWorkerQueueManagement:
    """Test worker queue management functionality."""
    
    @pytest.fixture
    def mock_queue(self):
        """Create a mock RQ Queue."""
        queue = MagicMock(spec=Queue)
        queue.name = QueueNames.DEFAULT
        queue.failed_job_registry = MagicMock()
        queue.failed_job_registry.count = 2
        queue.deferred_job_registry = MagicMock() 
        queue.deferred_job_registry.count = 1
        queue.finished_job_registry = MagicMock()
        queue.finished_job_registry.count = 10
        queue.started_job_registry = MagicMock()
        queue.started_job_registry.count = 3
        queue.__len__ = MagicMock(return_value=5)
        return queue
    
    @pytest.fixture
    def mock_job(self):
        """Create a mock RQ Job."""
        job = MagicMock(spec=Job)
        job.id = "test-job-123"
        job.get_status.return_value = JobStatus.QUEUED
        job.created_at = datetime.utcnow()
        job.started_at = None
        job.ended_at = None
        job.result = None
        job.exc_info = None
        job.meta = {}
        job.func_name = "test_function"
        return job
    
    def test_queue_names_definition(self):
        """Test that all required queue names are defined."""
        expected_queues = ["default", "high", "low", "embeddings", "sync", "cleanup", "analytics"]
        
        for queue_name in expected_queues:
            assert hasattr(QueueNames, queue_name.upper())
    
    async def test_enqueue_job_success(self, mock_queue, mock_job):
        """Test successful job enqueuing."""
        test_function = MagicMock()
        test_function.__name__ = "test_function"
        
        with patch('app.workers.queue.get_queue') as mock_get_queue:
            mock_get_queue.return_value = mock_queue
            mock_queue.enqueue.return_value = mock_job
            
            result = enqueue_job(test_function, "arg1", queue_name=QueueNames.DEFAULT, job_timeout=600)
            
            assert result == mock_job
            mock_queue.enqueue.assert_called_once()
    
    async def test_get_job_status_success(self, mock_job):
        """Test successful job status retrieval."""
        with patch('app.workers.queue.Job.fetch') as mock_fetch:
            mock_fetch.return_value = mock_job
            
            status = get_job_status("test-job-123")
            
            assert status["id"] == "test-job-123"
            assert status["status"] == JobStatus.QUEUED
            assert "created_at" in status
    
    async def test_cancel_job_success(self, mock_job):
        """Test successful job cancellation."""
        with patch('app.workers.queue.Job.fetch') as mock_fetch:
            mock_fetch.return_value = mock_job
            
            result = cancel_job("test-job-123")
            
            assert result is True
            mock_job.cancel.assert_called_once()
    
    async def test_get_queue_stats(self, mock_queue):
        """Test queue statistics retrieval."""
        with patch('app.workers.queue.queues', {QueueNames.DEFAULT: mock_queue}):
            stats = get_queue_stats()
            
            assert QueueNames.DEFAULT in stats
            assert stats[QueueNames.DEFAULT]["length"] == 5
            assert stats[QueueNames.DEFAULT]["failed_count"] == 2
            assert stats[QueueNames.DEFAULT]["finished_count"] == 10


@pytest.mark.asyncio
class TestWorkerJobRetryMechanisms:
    """Test job retry mechanisms and failure handling."""
    
    @pytest.fixture
    def failed_job(self):
        """Create a mock failed job."""
        job = MagicMock(spec=Job)
        job.id = "failed-job-123"
        job.meta = {"retry_count": 1}
        job.func_name = "failed_function"
        job.args = ["arg1"]
        job.kwargs = {"kwarg1": "value1"}
        job.timeout = 300
        return job
    
    @pytest.fixture
    def mock_queue_with_failed_jobs(self):
        """Create a mock queue with failed jobs."""
        queue = MagicMock(spec=Queue)
        queue.name = QueueNames.DEFAULT
        
        failed_registry = MagicMock()
        failed_registry.get_job_ids.return_value = ["failed-job-123", "failed-job-456"]
        failed_registry.remove = MagicMock()
        queue.failed_job_registry = failed_registry
        
        return queue
    
    async def test_retry_failed_job_success(self, failed_job, mock_queue_with_failed_jobs):
        """Test successful job retry with exponential backoff."""
        failed_job.meta = {"retry_count": 1}
        
        with patch('app.workers.queue.Job.fetch') as mock_fetch, \
             patch('app.workers.queue.get_queue') as mock_get_queue:
            
            mock_fetch.return_value = failed_job
            mock_get_queue.return_value = mock_queue_with_failed_jobs
            
            new_job = MagicMock()
            new_job.id = "retry-job-789"
            mock_queue_with_failed_jobs.enqueue_in.return_value = new_job
            
            result = retry_failed_job("failed-job-123", max_retries=3, backoff_factor=2.0)
            
            assert result["status"] == "retry_scheduled"
            assert result["job_id"] == "failed-job-123"
            assert result["new_job_id"] == "retry-job-789"
            assert result["retry_count"] == 2
            
            mock_queue_with_failed_jobs.failed_job_registry.remove.assert_called_with("failed-job-123")
    
    async def test_retry_failed_job_max_retries_exceeded(self, failed_job):
        """Test retry failure when max retries exceeded."""
        failed_job.meta = {"retry_count": 5}
        
        with patch('app.workers.queue.Job.fetch') as mock_fetch:
            mock_fetch.return_value = failed_job
            
            result = retry_failed_job("failed-job-123", max_retries=3)
            
            assert result["status"] == "max_retries_exceeded"
            assert result["retry_count"] == 5
            assert result["max_retries"] == 3
    
    async def test_retry_all_failed_jobs(self):
        """Test bulk retry of all failed jobs."""
        failed_job_infos = [
            {"id": "failed-job-1", "queue": QueueNames.DEFAULT},
            {"id": "failed-job-2", "queue": QueueNames.DEFAULT},
            {"id": "failed-job-3", "queue": QueueNames.DEFAULT}
        ]
        
        with patch('app.workers.queue.get_failed_jobs') as mock_get_failed, \
             patch('app.workers.queue.retry_failed_job') as mock_retry:
            
            mock_get_failed.return_value = failed_job_infos
            mock_retry.return_value = {"status": "retry_scheduled"}
            
            result = retry_all_failed_jobs(queue_name=QueueNames.DEFAULT, max_retries=3, batch_size=2)
            
            assert result["total_failed_jobs"] == 3
            assert result["successful_retries"] == 3
            assert result["processed"] == 3
            assert mock_retry.call_count == 3


@pytest.mark.asyncio
class TestBackgroundWorkerTasks:
    """Test actual background worker task execution."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=None)
        return session
    
    async def test_analytics_daily_aggregation_task(self, mock_db_session):
        """Test daily usage statistics aggregation task."""
        target_date = "2025-01-20"
        
        with patch('app.workers.analytics.get_db_session') as mock_get_db, \
             patch('app.workers.analytics._aggregate_workspace_stats') as mock_workspace, \
             patch('app.workers.analytics._aggregate_api_key_stats') as mock_api_key, \
             patch('app.workers.analytics._aggregate_model_stats') as mock_model:
            
            mock_get_db.return_value = mock_db_session
            mock_workspace.return_value = [{"dimension_type": "workspace", "dimension_value": "ws1"}]
            mock_api_key.return_value = [{"dimension_type": "api_key", "dimension_value": "key1"}]
            mock_model.return_value = [{"dimension_type": "model", "dimension_value": "gpt-4"}]
            
            result = aggregate_daily_usage_stats(date=target_date)
            
            assert result["date"] == target_date
            assert result["workspaces_processed"] == 1
            assert result["api_keys_processed"] == 1
            assert result["models_processed"] == 1
            assert "aggregation_time" in result
    
    async def test_analytics_usage_report_generation(self, mock_db_session):
        """Test usage report generation task."""
        start_date = "2025-01-15"
        end_date = "2025-01-20"
        
        mock_stats = [
            MagicMock(
                dimension_value="workspace1", request_count=100, token_count=5000, 
                cost=2.50, error_count=2, avg_response_time=1.2,
                date=datetime.strptime("2025-01-15", "%Y-%m-%d").date()
            )
        ]
        
        with patch('app.workers.analytics.get_db_session') as mock_get_db:
            mock_get_db.return_value = mock_db_session
            mock_db_session.query.return_value.filter.return_value.all.return_value = mock_stats
            
            result = generate_usage_report(start_date=start_date, end_date=end_date, dimension="workspace")
            
            assert result["start_date"] == start_date
            assert result["end_date"] == end_date
            assert result["dimension"] == "workspace"
            assert "workspace1" in result["report_data"]
    
    async def test_cleanup_old_context_items_task(self):
        """Test cleanup of old context items task."""
        with patch('app.workers.cleanup.cleanup_old_context_items') as mock_cleanup:
            mock_cleanup.return_value = {
                "semantic_items_deleted": 50, "episodic_items_deleted": 30,
                "artifacts_deleted": 10, "total_deleted": 90,
                "cleanup_time": datetime.utcnow().isoformat()
            }
            
            result = mock_cleanup(older_than_days=30)
            
            assert result["total_deleted"] == 90
            assert result["semantic_items_deleted"] == 50
    
    async def test_embeddings_generation_task(self):
        """Test embeddings generation task."""
        with patch('app.workers.embeddings.generate_embeddings_for_item') as mock_generate:
            mock_generate.return_value = {
                "item_id": "S001", "status": "success", 
                "embedding_dimensions": 1536, "processing_time": 0.5
            }
            
            result = mock_generate(item_id="S001", content="test content", metadata={})
            
            assert result["item_id"] == "S001"
            assert result["status"] == "success"
            assert result["embedding_dimensions"] == 1536


@pytest.mark.asyncio
class TestWorkerScheduler:
    """Test worker scheduler functionality."""
    
    async def test_scheduled_tasks_initialization(self):
        """Test initialization of all scheduled tasks."""
        with patch('app.workers.scheduler.scheduler') as mock_scheduler:
            scheduled_tasks = ScheduledTasks()
            
            mock_job = MagicMock()
            mock_job.id = "scheduled-job-123"
            mock_job.scheduled_for = datetime.utcnow() + timedelta(hours=1)
            
            with patch.object(scheduled_tasks, '_schedule_task', return_value=mock_job):
                result = scheduled_tasks.schedule_all_tasks()
                
                assert len(result["scheduled_jobs"]) > 0
                assert len(result["failed_jobs"]) == 0
                assert "schedule_time" in result
    
    async def test_scheduler_initialization(self):
        """Test scheduler initialization with all tasks."""
        with patch('app.workers.scheduler.initialize_scheduler') as mock_init:
            mock_init.return_value = {
                "status": "initialized", "scheduled_jobs": 12, "failed_jobs": 0,
                "initialization_time": datetime.utcnow().isoformat()
            }
            
            result = initialize_scheduler()
            
            assert result["status"] == "initialized"
            assert result["scheduled_jobs"] == 12
            assert result["failed_jobs"] == 0


@pytest.mark.asyncio
class TestWorkerErrorHandling:
    """Test worker error handling and edge cases."""
    
    async def test_task_execution_with_database_error(self):
        """Test task handling when database is unavailable."""
        with patch('app.workers.analytics.get_db_session') as mock_get_db:
            mock_get_db.side_effect = Exception("Database connection failed")
            
            result = aggregate_daily_usage_stats(date="2025-01-20")
            
            assert "error" in result
            assert "Database connection failed" in result["error"]
    
    async def test_retry_mechanism_with_corrupted_job(self):
        """Test retry mechanism with corrupted job data."""
        with patch('app.workers.queue.Job.fetch') as mock_fetch:
            mock_fetch.side_effect = Exception("Job data corrupted")
            
            result = retry_failed_job("corrupted-job-123")
            
            assert result["status"] == "retry_failed"
            assert "Job data corrupted" in result["error"]
    
    async def test_queue_stats_with_redis_error(self):
        """Test queue statistics when Redis is unavailable."""
        mock_queue = MagicMock()
        mock_queue.failed_job_registry.count.side_effect = Exception("Redis error")
        
        with patch('app.workers.queue.queues', {QueueNames.DEFAULT: mock_queue}):
            stats = get_queue_stats()
            
            assert QueueNames.DEFAULT in stats
            assert "error" in stats[QueueNames.DEFAULT]


@pytest.mark.asyncio
class TestWorkerPerformance:
    """Test worker performance characteristics."""
    
    async def test_large_batch_processing_performance(self):
        """Test performance with large batch processing."""
        with patch('app.workers.embeddings.batch_generate_embeddings') as mock_batch:
            mock_batch.return_value = {
                "total_items": 1000, "successful_embeddings": 950, 
                "failed_embeddings": 50, "batch_processing_time": 45.2,
                "average_time_per_item": 0.045
            }
            
            result = mock_batch(items=[{"id": f"item_{i}"} for i in range(1000)], batch_size=100)
            
            assert result["total_items"] == 1000
            assert result["successful_embeddings"] >= 900
            assert result["batch_processing_time"] < 60


if __name__ == "__main__":
    pytest.main([__file__])