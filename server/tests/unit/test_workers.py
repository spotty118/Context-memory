"""
Unit tests for worker functions.
"""
import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta

from app.workers.model_sync import sync_model_catalog, cleanup_deprecated_models, update_model_usage_stats
from app.workers.embeddings import generate_embeddings_for_item, batch_generate_embeddings
from app.workers.cleanup import cleanup_old_context_items, cleanup_old_request_logs, vacuum_database
from app.workers.analytics import aggregate_daily_usage_stats, calculate_context_memory_stats


@pytest.mark.worker
class TestModelSyncWorkers:
    """Test model synchronization workers."""
    
    def test_sync_model_catalog_success(self):
        """Test successful model catalog synchronization."""
        mock_models = [
            {
                "id": "openai/gpt-4",
                "name": "GPT-4",
                "provider": "openai",
                "description": "GPT-4 model",
                "context_length": 8192,
                "pricing": {"prompt": "0.03", "completion": "0.06"},
                "supports_streaming": True,
                "supports_functions": True
            },
            {
                "id": "anthropic/claude-3-opus",
                "name": "Claude 3 Opus", 
                "provider": "anthropic",
                "description": "Claude 3 Opus model",
                "context_length": 200000,
                "pricing": {"prompt": "0.015", "completion": "0.075"},
                "supports_streaming": True,
                "supports_functions": False
            }
        ]
        
        with patch('app.services.openrouter.OpenRouterService') as mock_service_class, \
             patch('app.db.session.get_db_session') as mock_get_db:
            
            # Mock OpenRouter service
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.fetch_all_models.return_value = mock_models
            
            # Mock database session
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.all.return_value = []  # No existing models
            
            # Run the sync
            result = sync_model_catalog()
            
            assert result["status"] == "success"
            assert result["models_processed"] == 2
            assert result["models_added"] == 2
            assert result["models_updated"] == 0
            
            # Verify database operations
            assert mock_db.add.call_count == 2
            mock_db.commit.assert_called_once()
    
    def test_sync_model_catalog_with_updates(self):
        """Test model catalog sync with existing models to update."""
        new_models = [
            {
                "id": "openai/gpt-4",
                "name": "GPT-4",
                "provider": "openai",
                "context_length": 8192,
                "pricing": {"prompt": "0.025", "completion": "0.05"},  # Updated pricing
                "supports_streaming": True,
                "supports_functions": True
            }
        ]
        
        # Mock existing model in database
        existing_model = MagicMock()
        existing_model.model_id = "openai/gpt-4"
        existing_model.input_price = 0.03  # Old price
        existing_model.output_price = 0.06  # Old price
        
        with patch('app.services.openrouter.OpenRouterService') as mock_service_class, \
             patch('app.db.session.get_db_session') as mock_get_db:
            
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.fetch_all_models.return_value = new_models
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.all.return_value = [existing_model]
            mock_db.query.return_value.filter.return_value.first.return_value = existing_model
            
            result = sync_model_catalog()
            
            assert result["status"] == "success"
            assert result["models_updated"] == 1
            assert result["models_added"] == 0
            
            # Verify model was updated
            assert existing_model.input_price == 0.025
            assert existing_model.output_price == 0.05
    
    def test_sync_model_catalog_api_error(self):
        """Test model catalog sync with API error."""
        with patch('app.services.openrouter.OpenRouterService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.fetch_all_models.side_effect = Exception("API Error")
            
            result = sync_model_catalog()
            
            assert result["status"] == "error"
            assert "API Error" in result["error"]
    
    def test_cleanup_deprecated_models(self):
        """Test cleanup of deprecated models."""
        # Mock deprecated models
        deprecated_models = [
            MagicMock(model_id="old/model-1", status="deprecated"),
            MagicMock(model_id="old/model-2", status="deprecated")
        ]
        
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.all.return_value = deprecated_models
            
            result = cleanup_deprecated_models()
            
            assert result["status"] == "success"
            assert result["models_cleaned"] == 2
            
            # Verify models were marked as unavailable
            for model in deprecated_models:
                assert model.status == "unavailable"
    
    def test_update_model_usage_stats(self):
        """Test updating model usage statistics."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Mock query results for usage statistics
            mock_db.execute.return_value.fetchall.return_value = [
                ("openai/gpt-4", 100, 50000),  # model_id, request_count, token_count
                ("anthropic/claude-3-opus", 50, 25000)
            ]
            
            result = update_model_usage_stats()
            
            assert result["status"] == "success"
            assert result["models_updated"] == 2
            
            # Verify database operations
            mock_db.execute.assert_called()
            mock_db.commit.assert_called_once()


@pytest.mark.worker
class TestEmbeddingWorkers:
    """Test embedding generation workers."""
    
    def test_generate_embeddings_for_item_semantic(self):
        """Test generating embeddings for a semantic item."""
        item_id = "S001"
        
        # Mock semantic item
        mock_item = MagicMock()
        mock_item.id = item_id
        mock_item.content = "Test semantic content for embedding"
        
        # Mock embedding response
        mock_embedding = [0.1] * 1536  # 1536-dimensional embedding
        
        with patch('app.db.session.get_db_session') as mock_get_db, \
             patch('openai.OpenAI') as mock_openai_class:
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = mock_item
            
            # Mock OpenAI client
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.data = [MagicMock(embedding=mock_embedding)]
            mock_client.embeddings.create.return_value = mock_response
            
            result = generate_embeddings_for_item("semantic", item_id)
            
            assert result["status"] == "success"
            assert result["item_id"] == item_id
            assert result["embedding_dimensions"] == 1536
            
            # Verify embedding was stored
            assert mock_item.embedding == mock_embedding
            mock_db.commit.assert_called_once()
    
    def test_generate_embeddings_for_item_not_found(self):
        """Test generating embeddings for non-existent item."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None
            
            result = generate_embeddings_for_item("semantic", "NONEXISTENT")
            
            assert result["status"] == "error"
            assert "not found" in result["error"]
    
    def test_batch_generate_embeddings(self):
        """Test batch embedding generation."""
        item_ids = ["S001", "S002", "S003"]
        
        # Mock semantic items
        mock_items = []
        for i, item_id in enumerate(item_ids):
            mock_item = MagicMock()
            mock_item.id = item_id
            mock_item.content = f"Test content {i}"
            mock_items.append(mock_item)
        
        mock_embeddings = [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]
        
        with patch('app.db.session.get_db_session') as mock_get_db, \
             patch('openai.OpenAI') as mock_openai_class:
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.all.return_value = mock_items
            
            # Mock OpenAI client for batch processing
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.data = [
                MagicMock(embedding=emb) for emb in mock_embeddings
            ]
            mock_client.embeddings.create.return_value = mock_response
            
            result = batch_generate_embeddings("semantic", item_ids)
            
            assert result["status"] == "success"
            assert result["items_processed"] == 3
            assert result["embeddings_generated"] == 3
            
            # Verify all items got embeddings
            for i, item in enumerate(mock_items):
                assert item.embedding == mock_embeddings[i]
    
    def test_batch_generate_embeddings_api_error(self):
        """Test batch embedding generation with API error."""
        item_ids = ["S001", "S002"]
        
        with patch('app.db.session.get_db_session') as mock_get_db, \
             patch('openai.OpenAI') as mock_openai_class:
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.all.return_value = [MagicMock(), MagicMock()]
            
            # Mock API error
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_client.embeddings.create.side_effect = Exception("API rate limit exceeded")
            
            result = batch_generate_embeddings("semantic", item_ids)
            
            assert result["status"] == "error"
            assert "API rate limit exceeded" in result["error"]


@pytest.mark.worker
class TestCleanupWorkers:
    """Test cleanup and maintenance workers."""
    
    def test_cleanup_old_context_items(self):
        """Test cleanup of old context items."""
        days_old = 30
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Mock old items to be cleaned up
        old_semantic_items = [MagicMock(id="S001"), MagicMock(id="S002")]
        old_episodic_items = [MagicMock(id="E001")]
        
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Mock queries for old items
            mock_db.query.return_value.filter.return_value.filter.return_value.all.side_effect = [
                old_semantic_items,  # First call for semantic items
                old_episodic_items   # Second call for episodic items
            ]
            
            result = cleanup_old_context_items(days_old=days_old)
            
            assert result["status"] == "success"
            assert result["semantic_items_deleted"] == 2
            assert result["episodic_items_deleted"] == 1
            assert result["total_items_deleted"] == 3
            
            # Verify deletion operations
            assert mock_db.delete.call_count == 3  # 2 semantic + 1 episodic
            mock_db.commit.assert_called_once()
    
    def test_cleanup_old_request_logs(self):
        """Test cleanup of old request logs."""
        days_old = 7
        
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Mock deletion result
            mock_result = MagicMock()
            mock_result.rowcount = 150  # 150 logs deleted
            mock_db.execute.return_value = mock_result
            
            result = cleanup_old_request_logs(days_old=days_old)
            
            assert result["status"] == "success"
            assert result["logs_deleted"] == 150
            
            # Verify database operations
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_called_once()
    
    def test_vacuum_database(self):
        """Test database vacuum operation."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            result = vacuum_database()
            
            assert result["status"] == "success"
            assert "vacuum_completed" in result
            
            # Verify VACUUM command was executed
            mock_db.execute.assert_called()
            mock_db.commit.assert_called_once()
    
    def test_vacuum_database_error(self):
        """Test database vacuum with error."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.execute.side_effect = Exception("Database connection error")
            
            result = vacuum_database()
            
            assert result["status"] == "error"
            assert "Database connection error" in result["error"]


@pytest.mark.worker
class TestAnalyticsWorkers:
    """Test analytics workers."""
    
    def test_aggregate_daily_usage_stats(self):
        """Test daily usage statistics aggregation."""
        target_date = "2025-01-20"
        
        # Mock raw usage data
        usage_data = [
            ("workspace-1", "api-key-1", "openai/gpt-4", 10, 5000),  # requests, tokens
            ("workspace-1", "api-key-2", "anthropic/claude-3-opus", 5, 2500),
            ("workspace-2", "api-key-3", "openai/gpt-4", 8, 4000)
        ]
        
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Mock query results
            mock_db.execute.return_value.fetchall.return_value = usage_data
            
            result = aggregate_daily_usage_stats(date=target_date)
            
            assert result["status"] == "success"
            assert result["date"] == target_date
            assert result["records_processed"] == 3
            assert result["aggregations_created"] > 0
            
            # Verify database operations
            mock_db.execute.assert_called()
            mock_db.commit.assert_called_once()
    
    def test_calculate_context_memory_stats(self):
        """Test context memory statistics calculation."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Mock statistics queries
            mock_db.execute.return_value.scalar.side_effect = [
                1000,  # total_semantic_items
                500,   # total_episodic_items
                200,   # total_artifacts
                0.75,  # avg_salience
                50     # active_threads
            ]
            
            result = calculate_context_memory_stats()
            
            assert result["status"] == "success"
            assert result["total_semantic_items"] == 1000
            assert result["total_episodic_items"] == 500
            assert result["total_artifacts"] == 200
            assert result["average_salience"] == 0.75
            assert result["active_threads"] == 50
            
            # Verify multiple queries were executed
            assert mock_db.execute.call_count >= 5
    
    def test_calculate_context_memory_stats_error(self):
        """Test context memory stats calculation with database error."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_db.execute.side_effect = Exception("Database query failed")
            
            result = calculate_context_memory_stats()
            
            assert result["status"] == "error"
            assert "Database query failed" in result["error"]


@pytest.mark.worker
class TestWorkerErrorHandling:
    """Test worker error handling and resilience."""
    
    def test_worker_with_database_connection_error(self):
        """Test worker behavior with database connection errors."""
        with patch('app.db.session.get_db_session') as mock_get_db:
            mock_get_db.side_effect = Exception("Database connection failed")
            
            result = sync_model_catalog()
            
            assert result["status"] == "error"
            assert "Database connection failed" in result["error"]
    
    def test_worker_with_partial_failure(self):
        """Test worker handling partial failures in batch operations."""
        item_ids = ["S001", "S002", "S003"]
        
        with patch('app.db.session.get_db_session') as mock_get_db, \
             patch('openai.OpenAI') as mock_openai_class:
            
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            # Mock items where one fails to process
            mock_items = [MagicMock(id=item_id, content=f"Content {item_id}") for item_id in item_ids]
            mock_db.query.return_value.filter.return_value.all.return_value = mock_items
            
            # Mock OpenAI client that fails on second call
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_client.embeddings.create.side_effect = [
                MagicMock(data=[MagicMock(embedding=[0.1] * 1536)]),  # Success
                Exception("Rate limit exceeded"),  # Failure
                MagicMock(data=[MagicMock(embedding=[0.3] * 1536)])   # Success
            ]
            
            result = batch_generate_embeddings("semantic", item_ids)
            
            # Should handle partial failure gracefully
            assert result["status"] == "partial_success"
            assert result["items_processed"] == 3
            assert result["embeddings_generated"] == 2  # 2 out of 3 succeeded
            assert result["failed_items"] == 1

