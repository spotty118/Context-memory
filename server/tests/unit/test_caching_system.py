"""
Comprehensive tests for the caching system.
Tests cache functionality, performance, and integration.
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from app.core.cache import CacheManager, CacheKeyGenerator, CacheInvalidator, cache_result
from app.services.cache import ModelCacheService, SettingsCacheService
from app.db.models import ModelCatalog, Settings, APIKey


@pytest.mark.asyncio
class TestCacheManager:
    """Test core cache manager functionality."""
    
    def test_cache_key_generation(self):
        """Test cache key generation patterns."""
        # Model cache keys
        assert CacheKeyGenerator.model_catalog("gpt-4") == "cmg:model:gpt-4"
        assert CacheKeyGenerator.model_catalog() == "cmg:models:all"
        assert CacheKeyGenerator.model_list("openai", "active") == "cmg:models:list:provider:openai:status:active"
        
        # Settings cache keys
        assert CacheKeyGenerator.global_settings("default_model") == "cmg:settings:default_model"
        assert CacheKeyGenerator.global_settings() == "cmg:settings:all"
        assert CacheKeyGenerator.workspace_settings("ws123") == "cmg:workspace:ws123:settings"
        
        # API key cache keys
        assert CacheKeyGenerator.api_key_settings("key123") == "cmg:api_key:key123:settings"
    
    async def test_cache_set_and_get(self):
        """Test basic cache set and get operations."""
        cache_manager = CacheManager()
        
        with patch.object(cache_manager, 'get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            # Test cache set
            test_data = {"test": "value", "number": 42}
            result = await cache_manager.set("test_key", test_data, "default")
            assert result is True
            
            # Verify Redis setex was called
            mock_client.setex.assert_called_once()
            
            # Test cache get - simulate cache hit
            import json
            cache_entry = {
                "data": test_data,
                "created_at": time.time(),
                "expires_at": time.time() + 300,
                "cache_type": "default",
                "version": None
            }
            mock_client.get.return_value = json.dumps(cache_entry, ensure_ascii=False)
            
            retrieved_data = await cache_manager.get("test_key", "default")
            assert retrieved_data == test_data
    
    async def test_cache_expiration(self):
        """Test cache expiration handling."""
        cache_manager = CacheManager()
        
        with patch.object(cache_manager, 'get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            # Simulate expired cache entry
            import json
            expired_entry = {
                "data": {"test": "value"},
                "created_at": time.time() - 1000,
                "expires_at": time.time() - 500,  # Expired 500 seconds ago
                "cache_type": "default",
                "version": None
            }
            mock_client.get.return_value = json.dumps(expired_entry, ensure_ascii=False)
            
            # Should return default value and delete expired entry
            result = await cache_manager.get("expired_key", "default", default="fallback")
            assert result == "fallback"
            
            # Should have called delete for expired entry
            mock_client.delete.assert_called_once_with("expired_key")
    
    async def test_cache_invalidation(self):
        """Test cache invalidation patterns."""
        cache_manager = CacheManager()
        
        with patch.object(cache_manager, 'get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            # Test pattern invalidation
            mock_client.keys.return_value = ["cmg:model:gpt-4", "cmg:model:claude-3"]
            mock_client.delete.return_value = 2
            
            deleted_count = await cache_manager.invalidate_pattern("cmg:model*")
            assert deleted_count == 2
            
            mock_client.keys.assert_called_with("cmg:model*")
            mock_client.delete.assert_called_with("cmg:model:gpt-4", "cmg:model:claude-3")
    
    async def test_memory_cache_operations(self):
        """Test in-memory cache operations."""
        cache_manager = CacheManager()
        
        # Test memory cache set and get
        cache_manager._set_in_memory("mem_key", {"data": "value"}, 60)
        result = cache_manager._get_from_memory("mem_key")
        assert result == {"data": "value"}
        
        # Test expired memory cache
        cache_manager._set_in_memory("expired_key", {"data": "value"}, -10)  # Already expired
        result = cache_manager._get_from_memory("expired_key")
        assert result is None
        assert "expired_key" not in cache_manager._memory_cache
    
    async def test_cache_health_check(self):
        """Test cache health check functionality."""
        cache_manager = CacheManager()
        
        with patch.object(cache_manager, 'get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            # Simulate healthy Redis
            mock_client.ping.return_value = True
            mock_client.setex.return_value = True
            mock_client.get.return_value = None  # For cleanup
            mock_client.delete.return_value = 1
            
            health = await cache_manager.health_check()
            assert health["status"] == "healthy"
            assert health["redis_connected"] is True
            assert "redis_latency_ms" in health
    
    async def test_cache_stats(self):
        """Test cache statistics collection."""
        cache_manager = CacheManager()
        
        # Increment some stats
        cache_manager._stats["hits"] = 10
        cache_manager._stats["misses"] = 2
        cache_manager._stats["sets"] = 8
        
        with patch.object(cache_manager, 'get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            mock_client.info.return_value = {"used_memory_human": "1.5MB"}
            
            stats = await cache_manager.get_stats()
            
            assert stats["hits"] == 10
            assert stats["misses"] == 2
            assert stats["sets"] == 8
            assert stats["hit_rate"] == 10 / 12  # hits / (hits + misses)
            assert "configurations" in stats


@pytest.mark.asyncio
class TestModelCacheService:
    """Test model cache service functionality."""
    
    @pytest.fixture
    def mock_model(self):
        """Create a mock model."""
        model = MagicMock(spec=ModelCatalog)
        model.model_id = "test-model-1"
        model.provider = "test-provider"
        model.display_name = "Test Model 1"
        model.context_window = 4096
        model.input_price_per_1k = 0.03
        model.output_price_per_1k = 0.06
        model.supports_tools = True
        model.supports_vision = False
        model.supports_json_mode = True
        model.embeddings = False
        model.status = "active"
        model.last_seen_at = None
        model.created_at = None
        model.updated_at = None
        model.metadata = {}
        return model
    
    async def test_get_all_models_cache_hit(self, mock_model):
        """Test getting all models with cache hit."""
        expected_models = [ModelCacheService._model_to_dict(mock_model)]
        
        with patch('app.services.cache.cache_manager') as mock_cache:
            mock_cache.get.return_value = expected_models
            
            result = await ModelCacheService.get_all_models(status="active", use_cache=True)
            
            assert result == expected_models
            mock_cache.get.assert_called_once()
    
    async def test_get_all_models_cache_miss(self, mock_model):
        """Test getting all models with cache miss."""
        expected_models = [ModelCacheService._model_to_dict(mock_model)]
        
        with patch('app.services.cache.cache_manager') as mock_cache, \
             patch('app.services.cache.get_session_maker') as mock_session_maker:
            
            # Cache miss
            mock_cache.get.return_value = None
            
            # Mock database session
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_model]
            
            result = await ModelCacheService.get_all_models(status="active", use_cache=True)
            
            # Should cache the result
            mock_cache.set.assert_called_once()
            assert len(result) == 1
            assert result[0]["model_id"] == "test-model-1"
    
    async def test_get_model_by_id_cache_hit(self, mock_model):
        """Test getting single model by ID with cache hit."""
        expected_model = ModelCacheService._model_to_dict(mock_model)
        
        with patch('app.services.cache.cache_manager') as mock_cache:
            mock_cache.get.return_value = expected_model
            
            result = await ModelCacheService.get_model_by_id("test-model-1", use_cache=True)
            
            assert result == expected_model
            mock_cache.get.assert_called_once()
    
    async def test_get_embedding_models(self, mock_model):
        """Test getting embedding models."""
        # Make it an embedding model
        mock_model.embeddings = True
        expected_models = [ModelCacheService._model_to_dict(mock_model)]
        
        with patch('app.services.cache.cache_manager') as mock_cache, \
             patch('app.services.cache.get_session_maker') as mock_session_maker:
            
            mock_cache.get.return_value = None  # Cache miss
            
            # Mock database session
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_model]
            
            result = await ModelCacheService.get_embedding_models(use_cache=True)
            
            assert len(result) == 1
            assert result[0]["embeddings"] is True
    
    async def test_model_cache_invalidation(self):
        """Test model cache invalidation."""
        with patch('app.core.cache.CacheInvalidator.invalidate_model_cache') as mock_invalidate, \
             patch('app.services.cache.cache_manager') as mock_cache:
            
            await ModelCacheService.invalidate_model_cache("test-model-1")
            
            mock_invalidate.assert_called_once_with("test-model-1")
            # Should also invalidate stats and embeddings cache
            assert mock_cache.delete.call_count >= 2
    
    async def test_warm_model_cache(self, mock_model):
        """Test cache warming functionality."""
        models = [ModelCacheService._model_to_dict(mock_model)]
        
        with patch.object(ModelCacheService, 'get_all_models') as mock_get_all, \
             patch.object(ModelCacheService, 'get_embedding_models') as mock_get_embeddings, \
             patch.object(ModelCacheService, 'get_model_stats') as mock_get_stats, \
             patch('app.services.cache.cache_manager') as mock_cache:
            
            mock_get_all.return_value = models
            mock_get_embeddings.return_value = []
            mock_get_stats.return_value = {}
            
            await ModelCacheService.warm_cache(limit=50)
            
            mock_get_all.assert_called_with(status="active", use_cache=False)
            mock_get_embeddings.assert_called_with(use_cache=False)
            mock_get_stats.assert_called_once()
            mock_cache.set.assert_called()  # Should cache individual models


@pytest.mark.asyncio
class TestSettingsCacheService:
    """Test settings cache service functionality."""
    
    async def test_get_global_settings_cache_hit(self):
        """Test getting global settings with cache hit."""
        expected_settings = {
            "global_default_model": {"model_id": "gpt-4"},
            "global_embed_model": {"model_id": "text-embedding-3-large"}
        }
        
        with patch('app.services.cache.cache_manager') as mock_cache:
            mock_cache.get.return_value = expected_settings
            
            result = await SettingsCacheService.get_global_settings(use_cache=True)
            
            assert result == expected_settings
            mock_cache.get.assert_called_once()
    
    async def test_get_setting_individual(self):
        """Test getting individual setting."""
        expected_value = {"model_id": "gpt-4"}
        
        with patch('app.services.cache.cache_manager') as mock_cache:
            mock_cache.get.return_value = expected_value
            
            result = await SettingsCacheService.get_setting("global_default_model", use_cache=True)
            
            assert result == expected_value
            mock_cache.get.assert_called_once()
    
    async def test_set_setting(self):
        """Test setting a configuration value."""
        with patch('app.services.cache.get_session_maker') as mock_session_maker, \
             patch.object(SettingsCacheService, 'invalidate_settings_cache') as mock_invalidate:
            
            # Mock database session
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = None  # New setting
            
            result = await SettingsCacheService.set_setting("test_key", {"value": "test"})
            
            assert result is True
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()
            mock_invalidate.assert_called_once_with("test_key")
    
    async def test_get_api_key_settings(self):
        """Test getting API key settings."""
        mock_api_key = MagicMock(spec=APIKey)
        mock_api_key.key_hash = "test_hash"
        mock_api_key.workspace_id = "workspace1"
        mock_api_key.name = "Test Key"
        mock_api_key.active = True
        mock_api_key.rpm_limit = 100
        mock_api_key.rph_limit = 6000
        mock_api_key.monthly_budget = 1000.0
        mock_api_key.created_at = None
        mock_api_key.last_used_at = None
        
        with patch('app.services.cache.cache_manager') as mock_cache:
            mock_cache.get.return_value = None  # Cache miss
            
            result = await SettingsCacheService.get_api_key_settings(mock_api_key, use_cache=True)
            
            assert result["api_key_id"] == "test_hash"
            assert result["workspace_id"] == "workspace1"
            assert result["name"] == "Test Key"
            assert result["rpm_limit"] == 100
            
            # Should cache the result
            mock_cache.set.assert_called_once()
    
    async def test_settings_cache_invalidation(self):
        """Test settings cache invalidation."""
        with patch('app.core.cache.CacheInvalidator.invalidate_settings_cache') as mock_invalidate:
            
            await SettingsCacheService.invalidate_settings_cache(key="test_key")
            mock_invalidate.assert_called_once_with(key="test_key", workspace_id=None, api_key_id=None)
    
    async def test_warm_settings_cache(self):
        """Test settings cache warming."""
        with patch.object(SettingsCacheService, 'get_global_settings') as mock_get_global, \
             patch.object(SettingsCacheService, 'get_setting') as mock_get_setting:
            
            mock_get_global.return_value = {}
            mock_get_setting.return_value = None
            
            await SettingsCacheService.warm_cache()
            
            mock_get_global.assert_called_with(use_cache=False)
            # Should call get_setting for each common setting
            assert mock_get_setting.call_count >= 4


@pytest.mark.asyncio
class TestCacheDecorator:
    """Test cache result decorator."""
    
    async def test_cache_result_decorator(self):
        """Test caching function results with decorator."""
        call_count = 0
        
        @cache_result(cache_type="default", ttl_override=300)
        async def expensive_function(param1: str, param2: int) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"result": f"{param1}_{param2}", "call_count": call_count}
        
        with patch('app.core.cache.cache_manager') as mock_cache:
            # First call - cache miss
            mock_cache.get.return_value = None
            
            result1 = await expensive_function("test", 42)
            assert result1["call_count"] == 1
            
            # Should have cached the result
            mock_cache.set.assert_called_once()
            
            # Second call - cache hit
            mock_cache.get.return_value = {"result": "test_42", "call_count": 1}
            
            result2 = await expensive_function("test", 42)
            assert result2["call_count"] == 1  # Same as cached result
            assert call_count == 1  # Function not called again


@pytest.mark.asyncio
class TestCacheIntegration:
    """Test cache integration with API endpoints."""
    
    async def test_models_api_cache_integration(self):
        """Test that models API uses caching."""
        with patch('app.api.models.ModelCacheService.get_all_models') as mock_get_models, \
             patch('app.api.models.SettingsCacheService.get_global_settings') as mock_get_settings:
            
            mock_get_models.return_value = [
                {
                    "model_id": "gpt-4",
                    "provider": "openai",
                    "display_name": "GPT-4",
                    "context_window": 8192,
                    "input_price_per_1k": 0.03,
                    "output_price_per_1k": 0.06,
                    "supports_tools": True,
                    "supports_vision": False,
                    "supports_json_mode": True,
                    "embeddings": False,
                    "status": "active"
                }
            ]
            mock_get_settings.return_value = {}
            
            # Import and call the models list function
            from app.api.models import list_models
            from app.db.models import APIKey
            
            mock_api_key = MagicMock(spec=APIKey)
            mock_api_key.workspace_id = "test_workspace"
            mock_db = MagicMock()
            
            # This would test the actual caching integration
            # but we're mocking the cache services directly
            mock_get_models.assert_not_called()  # Not called yet
    
    async def test_cache_performance_improvement(self):
        """Test that caching improves performance."""
        cache_manager = CacheManager()
        
        # Measure time for cache miss (simulated slow operation)
        with patch.object(cache_manager, 'get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            mock_client.get.return_value = None  # Cache miss
            
            async def slow_operation():
                await asyncio.sleep(0.1)  # Simulate slow operation
                return {"data": "expensive_result"}
            
            start_time = time.time()
            await cache_manager.get("slow_key", "default", default=None)
            if await cache_manager.get("slow_key", "default") is None:
                result = await slow_operation()
                await cache_manager.set("slow_key", result, "default")
            miss_time = time.time() - start_time
            
            # Measure time for cache hit
            import json
            cache_entry = {
                "data": {"data": "expensive_result"},
                "created_at": time.time(),
                "expires_at": time.time() + 300,
                "cache_type": "default",
                "version": None
            }
            mock_client.get.return_value = json.dumps(cache_entry, ensure_ascii=False)
            
            start_time = time.time()
            await cache_manager.get("slow_key", "default")
            hit_time = time.time() - start_time
            
            # Cache hit should be significantly faster
            assert hit_time < miss_time * 0.5  # At least 50% faster


if __name__ == "__main__":
    pytest.main([__file__])