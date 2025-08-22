"""
End-to-end tests for complete workflows.
"""
import pytest
from unittest.mock import patch, MagicMock
import time

from fastapi.testclient import TestClient


@pytest.mark.e2e
class TestCompleteContextMemoryWorkflow:
    """Test complete context memory workflow from ingestion to recall."""
    
    def test_full_context_memory_cycle(self, client: TestClient, auth_headers):
        """Test complete cycle: ingest -> recall -> working set -> feedback."""
        thread_id = "test-thread-e2e-123"
        
        # Step 1: Ingest chat content
        ingest_data = {
            "thread_id": thread_id,
            "content_type": "chat",
            "content": """
            User: We need to build a user authentication system for our web app.
            Assistant: I recommend using JWT tokens for session management and bcrypt for password hashing.
            User: Great! We also need OAuth integration with Google and GitHub.
            Assistant: I'll implement OAuth2 flows for both providers. We should store the tokens securely.
            """,
            "metadata": {
                "source": "chat_session",
                "timestamp": "2025-01-20T10:00:00Z"
            }
        }
        
        with patch('app.services.extractor.ContextExtractor.extract_from_chat') as mock_extract, \
             patch('app.db.session.get_db_session') as mock_get_db:
            
            # Mock extraction results
            mock_extract.return_value = {
                "semantic_items": [
                    {
                        "id": "S001",
                        "thread_id": thread_id,
                        "item_type": "decision",
                        "content": "Use JWT tokens for session management",
                        "salience": 0.8
                    },
                    {
                        "id": "S002", 
                        "thread_id": thread_id,
                        "item_type": "requirement",
                        "content": "Implement OAuth integration with Google and GitHub",
                        "salience": 0.9
                    }
                ],
                "episodic_items": [],
                "artifacts": []
            }
            
            # Mock database operations
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Ingest the content
            ingest_response = client.post(
                "/v1/ingest",
                headers=auth_headers,
                json=ingest_data
            )
            
            assert ingest_response.status_code == 200
            ingest_result = ingest_response.json()
            assert ingest_result["status"] == "success"
            assert ingest_result["items_created"]["semantic_items"] == 2
        
        # Step 2: Recall context for related work
        recall_data = {
            "thread_id": thread_id,
            "purpose": "Continue implementing authentication system",
            "token_budget": 4000,
            "include_artifacts": True
        }
        
        with patch('app.services.retrieval.ContextRetriever.retrieve_context') as mock_retrieve:
            mock_retrieve.return_value = {
                "semantic_items": [
                    {
                        "id": "S001",
                        "content": "Use JWT tokens for session management",
                        "score": 0.95,
                        "item_type": "decision"
                    },
                    {
                        "id": "S002",
                        "content": "Implement OAuth integration with Google and GitHub", 
                        "score": 0.90,
                        "item_type": "requirement"
                    }
                ],
                "episodic_items": [],
                "artifacts": []
            }
            
            recall_response = client.post(
                "/v1/recall",
                headers=auth_headers,
                json=recall_data
            )
            
            assert recall_response.status_code == 200
            recall_result = recall_response.json()
            assert len(recall_result["context_items"]["semantic_items"]) == 2
            assert recall_result["context_items"]["semantic_items"][0]["score"] > 0.9
        
        # Step 3: Get working set for implementation
        workingset_data = {
            "thread_id": thread_id,
            "purpose": "Implement OAuth authentication with JWT tokens",
            "token_budget": 8000,
            "include_artifacts": True,
            "focus_areas": ["authentication", "oauth", "jwt", "security"]
        }
        
        with patch('app.services.workingset.WorkingSetBuilder.build_working_set') as mock_build:
            mock_build.return_value = {
                "mission": "Implement OAuth authentication with JWT tokens for the web application",
                "constraints": [
                    "Must support Google and GitHub OAuth providers",
                    "Use JWT tokens for session management",
                    "Implement secure token storage"
                ],
                "focus_decisions": [
                    "Use JWT tokens for session management",
                    "Implement OAuth2 flows for Google and GitHub"
                ],
                "focus_tasks": [
                    "Set up OAuth2 client credentials",
                    "Implement JWT token generation and validation",
                    "Create secure token storage mechanism",
                    "Build OAuth callback handlers"
                ],
                "runbook": [
                    "1. Configure OAuth2 applications in Google and GitHub",
                    "2. Install and configure OAuth2 client library",
                    "3. Implement JWT token utilities (generate, verify, refresh)",
                    "4. Create OAuth2 authorization endpoints",
                    "5. Implement OAuth2 callback handlers",
                    "6. Set up secure token storage (httpOnly cookies or secure storage)",
                    "7. Add authentication middleware",
                    "8. Test OAuth flows with both providers"
                ],
                "artifacts": [],
                "citations": {
                    "semantic": ["S001", "S002"],
                    "episodic": [],
                    "artifacts": []
                },
                "open_questions": [
                    "Should we implement token refresh automatically?",
                    "How long should JWT tokens be valid?",
                    "Should we support multiple concurrent sessions per user?"
                ]
            }
            
            workingset_response = client.post(
                "/v1/workingset",
                headers=auth_headers,
                json=workingset_data
            )
            
            assert workingset_response.status_code == 200
            workingset_result = workingset_response.json()
            working_set = workingset_result["working_set"]
            
            assert "OAuth authentication" in working_set["mission"]
            assert len(working_set["focus_decisions"]) >= 2
            assert len(working_set["runbook"]) >= 5
            assert len(working_set["open_questions"]) >= 2
            assert "S001" in working_set["citations"]["semantic"]
            assert "S002" in working_set["citations"]["semantic"]
        
        # Step 4: Provide feedback on helpful items
        feedback_data = {
            "item_id": "S001",
            "feedback_type": "helpful",
            "value": 1.0
        }
        
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            mock_item = MagicMock()
            mock_item.salience = 0.8
            mock_db.query.return_value.filter.return_value.first.return_value = mock_item
            
            feedback_response = client.post(
                "/v1/feedback",
                headers=auth_headers,
                json=feedback_data
            )
            
            assert feedback_response.status_code == 200
            feedback_result = feedback_response.json()
            assert feedback_result["status"] == "success"
            assert feedback_result["updated_salience"] > 0.8  # Should increase
    
    def test_multi_content_type_ingestion(self, client: TestClient, auth_headers):
        """Test ingesting different content types in sequence."""
        thread_id = "test-thread-multi-123"
        
        # Ingest chat content
        chat_data = {
            "thread_id": thread_id,
            "content_type": "chat",
            "content": "User decided to use React for frontend development."
        }
        
        # Ingest diff content  
        diff_data = {
            "thread_id": thread_id,
            "content_type": "diff",
            "content": """
            diff --git a/src/App.jsx b/src/App.jsx
            new file mode 100644
            index 0000000..1234567
            --- /dev/null
            +++ b/src/App.jsx
            @@ -0,0 +1,10 @@
            +import React from 'react';
            +
            +function App() {
            +  return (
            +    <div className="App">
            +      <h1>Hello World</h1>
            +    </div>
            +  );
            +}
            +export default App;
            """
        }
        
        # Ingest log content
        log_data = {
            "thread_id": thread_id,
            "content_type": "logs",
            "content": """
            2025-01-20 10:00:00 ERROR [webpack] Module not found: Can't resolve 'react-router-dom'
            2025-01-20 10:01:00 INFO [npm] Installing react-router-dom@6.8.0
            2025-01-20 10:02:00 INFO [webpack] Compilation successful
            """
        }
        
        with patch('app.services.extractor.ContextExtractor') as mock_extractor_class, \
             patch('app.db.session.get_db_session') as mock_get_db:
            
            mock_extractor = MagicMock()
            mock_extractor_class.return_value = mock_extractor
            
            # Mock different extraction results for each content type
            mock_extractor.extract_from_chat.return_value = {
                "semantic_items": [{"id": "S001", "content": "Use React for frontend"}],
                "episodic_items": [],
                "artifacts": []
            }
            
            mock_extractor.extract_from_diff.return_value = {
                "semantic_items": [],
                "episodic_items": [],
                "artifacts": [{"id": "CODE001", "title": "App.jsx", "content": "React component"}]
            }
            
            mock_extractor.extract_from_logs.return_value = {
                "semantic_items": [],
                "episodic_items": [{"id": "E001", "content": "Module not found error"}],
                "artifacts": []
            }
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Ingest each content type
            responses = []
            for data in [chat_data, diff_data, log_data]:
                response = client.post("/v1/ingest", headers=auth_headers, json=data)
                responses.append(response)
                assert response.status_code == 200
            
            # Verify all content types were processed
            assert all(r.json()["status"] == "success" for r in responses)


@pytest.mark.e2e
class TestLLMGatewayWorkflow:
    """Test complete LLM gateway workflow."""
    
    def test_chat_completion_with_context_injection(self, client: TestClient, auth_headers):
        """Test chat completion with automatic context injection."""
        thread_id = "test-thread-llm-123"
        
        # First, set up some context
        with patch('app.services.retrieval.ContextRetriever.retrieve_context') as mock_retrieve:
            mock_retrieve.return_value = {
                "semantic_items": [
                    {
                        "id": "S001",
                        "content": "User prefers React for frontend development",
                        "score": 0.9
                    }
                ],
                "episodic_items": [],
                "artifacts": []
            }
            
            # Make chat completion request with context injection
            chat_request = {
                "model": "openai/gpt-4",
                "messages": [
                    {"role": "user", "content": "What frontend framework should I use?"}
                ],
                "thread_id": thread_id,  # This should trigger context injection
                "inject_context": True,
                "max_tokens": 150
            }
            
            with patch('app.services.openrouter.OpenRouterService.chat_completion') as mock_chat:
                mock_chat.return_value = {
                    "id": "chatcmpl-test123",
                    "object": "chat.completion", 
                    "created": 1642781234,
                    "model": "openai/gpt-4",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Based on your previous preference, I recommend using React for your frontend development."
                            },
                            "finish_reason": "stop"
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 25,
                        "completion_tokens": 15,
                        "total_tokens": 40
                    }
                }
                
                response = client.post(
                    "/v1/chat/completions",
                    headers=auth_headers,
                    json=chat_request
                )
                
                assert response.status_code == 200
                result = response.json()
                assert "React" in result["choices"][0]["message"]["content"]
                
                # Verify that context was injected into the request
                mock_chat.assert_called_once()
                call_args = mock_chat.call_args[1]
                injected_messages = call_args["messages"]
                
                # Should have system message with context + original user message
                assert len(injected_messages) >= 2
                assert any("React" in str(msg) for msg in injected_messages)
    
    def test_streaming_with_usage_tracking(self, client: TestClient, auth_headers):
        """Test streaming response with proper usage tracking."""
        chat_request = {
            "model": "openai/gpt-4",
            "messages": [
                {"role": "user", "content": "Write a short poem about coding."}
            ],
            "stream": True,
            "max_tokens": 100
        }
        
        with patch('app.services.openrouter.OpenRouterService.chat_completion_stream') as mock_stream, \
             patch('app.core.usage.track_request') as mock_track:
            
            # Mock streaming response
            mock_stream.return_value = iter([
                'data: {"id":"chatcmpl-test","choices":[{"delta":{"content":"Coding"}}]}\n\n',
                'data: {"id":"chatcmpl-test","choices":[{"delta":{"content":" is"}}]}\n\n',
                'data: {"id":"chatcmpl-test","choices":[{"delta":{"content":" fun"}}]}\n\n',
                'data: [DONE]\n\n'
            ])
            
            response = client.post(
                "/v1/chat/completions",
                headers=auth_headers,
                json=chat_request
            )
            
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"
            
            # Verify usage tracking was called
            mock_track.assert_called()


@pytest.mark.e2e
class TestWorkerIntegration:
    """Test worker system integration."""
    
    def test_model_sync_workflow(self, client: TestClient, auth_headers):
        """Test complete model synchronization workflow."""
        # Trigger model sync
        with patch('app.workers.queue.enqueue_job') as mock_enqueue:
            mock_job = MagicMock()
            mock_job.id = "sync-job-123"
            mock_job.get_status.return_value = "queued"
            mock_enqueue.return_value = mock_job
            
            sync_response = client.post(
                "/v1/workers/sync/models",
                headers=auth_headers
            )
            
            assert sync_response.status_code == 200
            sync_result = sync_response.json()
            job_id = sync_result["job_id"]
        
        # Check job status
        with patch('app.workers.queue.get_job_status') as mock_status:
            mock_status.return_value = {
                "id": job_id,
                "status": "finished",
                "result": {
                    "models_synced": 50,
                    "models_updated": 5,
                    "models_added": 2
                }
            }
            
            status_response = client.get(
                f"/v1/workers/jobs/{job_id}",
                headers=auth_headers
            )
            
            assert status_response.status_code == 200
            status_result = status_response.json()
            assert status_result["status"] == "finished"
            assert status_result["result"]["models_synced"] == 50
    
    def test_embedding_generation_workflow(self, client: TestClient, auth_headers):
        """Test embedding generation workflow."""
        # Trigger embedding generation for specific items
        embedding_request = {
            "item_type": "semantic",
            "item_ids": ["S001", "S002", "S003"]
        }
        
        with patch('app.workers.queue.enqueue_job') as mock_enqueue:
            mock_job = MagicMock()
            mock_job.id = "embedding-job-123"
            mock_enqueue.return_value = mock_job
            
            response = client.post(
                "/v1/workers/embeddings/generate",
                headers=auth_headers,
                json=embedding_request
            )
            
            assert response.status_code == 200
            result = response.json()
            assert result["item_count"] == 3
            assert result["item_type"] == "semantic"
    
    def test_cleanup_workflow(self, client: TestClient, auth_headers):
        """Test cleanup workflow."""
        # Trigger context cleanup
        with patch('app.workers.queue.enqueue_job') as mock_enqueue:
            mock_job = MagicMock()
            mock_job.id = "cleanup-job-123"
            mock_enqueue.return_value = mock_job
            
            response = client.post(
                "/v1/workers/cleanup/context?days_old=30",
                headers=auth_headers
            )
            
            assert response.status_code == 200
            result = response.json()
            assert result["days_old"] == 30
            assert "cleanup job enqueued" in result["message"]


@pytest.mark.e2e
@pytest.mark.slow
class TestPerformanceWorkflows:
    """Test performance-related workflows."""
    
    def test_high_volume_context_ingestion(self, client: TestClient, auth_headers):
        """Test ingesting high volume of context items."""
        thread_id = "test-thread-volume-123"
        
        # Simulate ingesting 10 different pieces of content
        contents = [
            f"User discussed requirement #{i}: Feature {i} needs to be implemented."
            for i in range(10)
        ]
        
        with patch('app.services.extractor.ContextExtractor.extract_from_chat') as mock_extract, \
             patch('app.db.session.get_db_session') as mock_get_db:
            
            mock_extract.return_value = {
                "semantic_items": [{"id": f"S{i:03d}", "content": f"Requirement {i}"}],
                "episodic_items": [],
                "artifacts": []
            }
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            start_time = time.time()
            
            # Ingest all content pieces
            for i, content in enumerate(contents):
                ingest_data = {
                    "thread_id": thread_id,
                    "content_type": "chat",
                    "content": content
                }
                
                response = client.post(
                    "/v1/ingest",
                    headers=auth_headers,
                    json=ingest_data
                )
                
                assert response.status_code == 200
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Should complete within reasonable time (adjust threshold as needed)
            assert total_time < 5.0  # 5 seconds for 10 ingestions
    
    def test_large_context_recall(self, client: TestClient, auth_headers):
        """Test recalling large amounts of context."""
        thread_id = "test-thread-large-123"
        
        # Mock large context retrieval
        large_context = {
            "semantic_items": [
                {
                    "id": f"S{i:03d}",
                    "content": f"This is semantic item {i} with detailed content about feature {i}.",
                    "score": 0.9 - (i * 0.01),  # Decreasing scores
                    "item_type": "requirement"
                }
                for i in range(100)  # 100 items
            ],
            "episodic_items": [],
            "artifacts": []
        }
        
        recall_data = {
            "thread_id": thread_id,
            "purpose": "Review all requirements for the project",
            "token_budget": 16000,  # Large budget
            "include_artifacts": True
        }
        
        with patch('app.services.retrieval.ContextRetriever.retrieve_context') as mock_retrieve:
            mock_retrieve.return_value = large_context
            
            start_time = time.time()
            
            response = client.post(
                "/v1/recall",
                headers=auth_headers,
                json=recall_data
            )
            
            end_time = time.time()
            response_time = end_time - start_time
            
            assert response.status_code == 200
            result = response.json()
            
            # Should handle large context efficiently
            assert len(result["context_items"]["semantic_items"]) > 0
            assert response_time < 2.0  # Should respond within 2 seconds

