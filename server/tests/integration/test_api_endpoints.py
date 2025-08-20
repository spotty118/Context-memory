"""
Integration tests for API endpoints.
"""
import pytest
from unittest.mock import patch, MagicMock
import json

from fastapi.testclient import TestClient


@pytest.mark.integration
class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_basic_health_check(self, client: TestClient):
        """Test basic health check endpoint."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data
    
    def test_detailed_health_check(self, client: TestClient):
        """Test detailed health check endpoint."""
        with patch('app.api.health.redis_conn') as mock_redis:
            mock_redis.ping.return_value = True
            
            response = client.get("/health/detailed")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "services" in data
            assert "database" in data["services"]
            assert "redis" in data["services"]


@pytest.mark.integration
class TestModelsEndpoints:
    """Test model catalog endpoints."""
    
    def test_list_models(self, client: TestClient, auth_headers):
        """Test listing available models."""
        response = client.get("/v1/models", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert isinstance(data["models"], list)
    
    def test_get_model_details(self, client: TestClient, auth_headers):
        """Test getting specific model details."""
        # First, we need a model to exist
        with patch('app.services.openrouter.OpenRouterService.get_model') as mock_get_model:
            mock_get_model.return_value = {
                "id": "openai/gpt-4",
                "name": "GPT-4",
                "provider": "openai",
                "context_length": 8192
            }
            
            response = client.get("/v1/models/openai/gpt-4", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "openai/gpt-4"
            assert data["name"] == "GPT-4"
    
    def test_list_models_unauthorized(self, client: TestClient):
        """Test listing models without authentication."""
        response = client.get("/v1/models")
        
        assert response.status_code == 401


@pytest.mark.integration
class TestLLMGatewayEndpoints:
    """Test LLM Gateway endpoints."""
    
    def test_chat_completion_success(self, client: TestClient, auth_headers, sample_chat_completion_request, sample_chat_completion_response):
        """Test successful chat completion."""
        with patch('app.services.openrouter.OpenRouterService.chat_completion') as mock_chat:
            mock_chat.return_value = sample_chat_completion_response
            
            response = client.post(
                "/v1/chat/completions",
                headers=auth_headers,
                json=sample_chat_completion_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "chatcmpl-test123"
            assert len(data["choices"]) == 1
            assert data["choices"][0]["message"]["role"] == "assistant"
    
    def test_chat_completion_unauthorized(self, client: TestClient, sample_chat_completion_request):
        """Test chat completion without authentication."""
        response = client.post(
            "/v1/chat/completions",
            json=sample_chat_completion_request
        )
        
        assert response.status_code == 401
    
    def test_chat_completion_invalid_model(self, client: TestClient, auth_headers):
        """Test chat completion with invalid model."""
        request_data = {
            "model": "invalid/model",
            "messages": [{"role": "user", "content": "Hello"}]
        }
        
        response = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json=request_data
        )
        
        assert response.status_code == 400
    
    def test_chat_completion_streaming(self, client: TestClient, auth_headers):
        """Test streaming chat completion."""
        request_data = {
            "model": "openai/gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True
        }
        
        with patch('app.services.openrouter.OpenRouterService.chat_completion_stream') as mock_stream:
            mock_stream.return_value = iter([
                "data: " + json.dumps({
                    "id": "chatcmpl-test123",
                    "choices": [{"delta": {"content": "Hello"}}]
                }) + "\n\n",
                "data: [DONE]\n\n"
            ])
            
            response = client.post(
                "/v1/chat/completions",
                headers=auth_headers,
                json=request_data
            )
            
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"


@pytest.mark.integration
class TestContextMemoryEndpoints:
    """Test context memory endpoints."""
    
    def test_ingest_chat_content(self, client: TestClient, auth_headers, sample_context_ingest_request):
        """Test ingesting chat content."""
        with patch('app.services.extractor.ContextExtractor.extract_from_chat') as mock_extract:
            mock_extract.return_value = {
                "semantic_items": [{"id": "S001", "content": "Test decision"}],
                "episodic_items": [],
                "artifacts": []
            }
            
            response = client.post(
                "/v1/ingest",
                headers=auth_headers,
                json=sample_context_ingest_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "items_created" in data
    
    def test_recall_context(self, client: TestClient, auth_headers, sample_context_recall_request):
        """Test recalling context."""
        with patch('app.services.retrieval.ContextRetriever.retrieve_context') as mock_retrieve:
            mock_retrieve.return_value = {
                "semantic_items": [{"id": "S001", "content": "Test decision", "score": 0.9}],
                "episodic_items": [],
                "artifacts": []
            }
            
            response = client.post(
                "/v1/recall",
                headers=auth_headers,
                json=sample_context_recall_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "context_items" in data
            assert len(data["context_items"]["semantic_items"]) > 0
    
    def test_get_working_set(self, client: TestClient, auth_headers, sample_working_set_request):
        """Test getting working set."""
        with patch('app.services.workingset.WorkingSetBuilder.build_working_set') as mock_build:
            mock_build.return_value = {
                "mission": "Test mission",
                "constraints": ["Time constraint"],
                "focus_decisions": ["Use React"],
                "focus_tasks": ["Implement auth"],
                "runbook": ["Step 1", "Step 2"],
                "artifacts": [{"id": "CODE001", "title": "Auth component"}],
                "citations": {"semantic": ["S001"], "episodic": [], "artifacts": ["CODE001"]},
                "open_questions": ["How to handle errors?"]
            }
            
            response = client.post(
                "/v1/workingset",
                headers=auth_headers,
                json=sample_working_set_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "working_set" in data
            assert "mission" in data["working_set"]
            assert "runbook" in data["working_set"]
    
    def test_expand_by_id_semantic(self, client: TestClient, auth_headers):
        """Test expanding semantic item by ID."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            mock_item = MagicMock()
            mock_item.id = "S001"
            mock_item.content = "Test semantic content"
            mock_item.item_type = "decision"
            mock_db.query.return_value.filter.return_value.first.return_value = mock_item
            
            response = client.get("/v1/expand/S001", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "S001"
            assert data["content"] == "Test semantic content"
    
    def test_expand_by_id_not_found(self, client: TestClient, auth_headers):
        """Test expanding non-existent item."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None
            
            response = client.get("/v1/expand/NONEXISTENT", headers=auth_headers)
            
            assert response.status_code == 404
    
    def test_provide_feedback(self, client: TestClient, auth_headers):
        """Test providing feedback on context items."""
        feedback_data = {
            "item_id": "S001",
            "feedback_type": "helpful",
            "value": 1.0
        }
        
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            mock_item = MagicMock()
            mock_item.salience = 0.5
            mock_db.query.return_value.filter.return_value.first.return_value = mock_item
            
            response = client.post(
                "/v1/feedback",
                headers=auth_headers,
                json=feedback_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


@pytest.mark.integration
class TestWorkerEndpoints:
    """Test worker management endpoints."""
    
    def test_get_queue_stats(self, client: TestClient, auth_headers):
        """Test getting queue statistics."""
        with patch('app.workers.queue.get_queue_stats') as mock_stats:
            mock_stats.return_value = {
                "default": {"length": 5, "failed_count": 0},
                "high": {"length": 2, "failed_count": 1}
            }
            
            response = client.get("/v1/workers/queues/stats", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert "queues" in data
            assert "default" in data["queues"]
    
    def test_enqueue_job(self, client: TestClient, auth_headers):
        """Test enqueuing a background job."""
        job_data = {
            "job_type": "sync_model_catalog",
            "parameters": {},
            "queue_name": "sync"
        }
        
        with patch('app.workers.queue.enqueue_job') as mock_enqueue:
            mock_job = MagicMock()
            mock_job.id = "test-job-123"
            mock_job.get_status.return_value = "queued"
            mock_job.created_at = None
            mock_enqueue.return_value = mock_job
            
            response = client.post(
                "/v1/workers/jobs",
                headers=auth_headers,
                json=job_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-123"
            assert data["status"] == "queued"
    
    def test_get_job_status(self, client: TestClient, auth_headers):
        """Test getting job status."""
        with patch('app.workers.queue.get_job_status') as mock_status:
            mock_status.return_value = {
                "id": "test-job-123",
                "status": "finished",
                "result": {"success": True}
            }
            
            response = client.get("/v1/workers/jobs/test-job-123", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "test-job-123"
            assert data["status"] == "finished"
    
    def test_cancel_job(self, client: TestClient, auth_headers):
        """Test cancelling a background job."""
        with patch('app.workers.queue.cancel_job') as mock_cancel:
            mock_cancel.return_value = True
            
            response = client.delete("/v1/workers/jobs/test-job-123", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "cancelled"
    
    def test_trigger_model_sync(self, client: TestClient, auth_headers):
        """Test triggering model sync."""
        with patch('app.workers.queue.enqueue_job') as mock_enqueue:
            mock_job = MagicMock()
            mock_job.id = "sync-job-123"
            mock_enqueue.return_value = mock_job
            
            response = client.post("/v1/workers/sync/models", headers=auth_headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "sync-job-123"
            assert "Model sync job enqueued" in data["message"]
    
    def test_worker_health_check(self, client: TestClient):
        """Test worker system health check."""
        with patch('app.workers.queue.get_queue_stats') as mock_stats, \
             patch('app.workers.scheduler.task_scheduler.get_scheduled_jobs_status') as mock_scheduler:
            
            mock_stats.return_value = {"default": {"length": 0}}
            mock_scheduler.return_value = {"total_jobs": 5, "status_time": "2025-01-20T10:00:00Z"}
            
            response = client.get("/v1/workers/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "queues" in data
            assert "scheduler" in data


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling across endpoints."""
    
    def test_404_not_found(self, client: TestClient):
        """Test 404 error handling."""
        response = client.get("/nonexistent-endpoint")
        
        assert response.status_code == 404
    
    def test_method_not_allowed(self, client: TestClient):
        """Test 405 error handling."""
        response = client.put("/health")  # Health endpoint only supports GET
        
        assert response.status_code == 405
    
    def test_validation_error(self, client: TestClient, auth_headers):
        """Test validation error handling."""
        invalid_data = {
            "model": "",  # Empty model should cause validation error
            "messages": []  # Empty messages should cause validation error
        }
        
        response = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json=invalid_data
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_internal_server_error_handling(self, client: TestClient, auth_headers):
        """Test internal server error handling."""
        with patch('app.api.health.redis_conn.ping') as mock_ping:
            mock_ping.side_effect = Exception("Redis connection failed")
            
            response = client.get("/health/detailed", headers=auth_headers)
            
            # Should handle the error gracefully
            assert response.status_code in [200, 500]  # Depending on implementation

