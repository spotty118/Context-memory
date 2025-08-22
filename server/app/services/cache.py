"""
Specialized caching services for model catalog and settings.
Provides high-level caching interfaces with domain-specific optimizations.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_manager, CacheKeyGenerator, CacheInvalidator, cache_result
from app.db.models import ModelCatalog, Settings, APIKey
from app.core.config import settings as app_settings


logger = structlog.get_logger(__name__)


class ModelCacheService:
    """
    Specialized caching service for model catalog data.
    Provides intelligent caching for frequently accessed model information.
    """
    
    @staticmethod
    async def get_all_models(
        provider: Optional[str] = None,
        status: str = "active",
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all models with caching support.
        
        Args:
            provider: Filter by provider (optional)
            status: Filter by status (default: active)
            use_cache: Whether to use cache (default: True)
            
        Returns:
            List of model dictionaries
        """
        if not use_cache:
            return await ModelCacheService._fetch_models_from_db(provider, status)
        
        cache_key = CacheKeyGenerator.model_list(provider, status)
        
        # Try cache first
        cached_models = await cache_manager.get(cache_key, "model_list")
        if cached_models is not None:
            logger.debug("model_list_cache_hit", provider=provider, status=status, count=len(cached_models))
            return cached_models
        
        # Fetch from database
        models = await ModelCacheService._fetch_models_from_db(provider, status)
        
        # Cache the result
        await cache_manager.set(cache_key, models, "model_list")
        
        logger.debug("model_list_cached", provider=provider, status=status, count=len(models))
        return models
    
    @staticmethod
    async def get_model_by_id(
        model_id: str,
        use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get specific model by ID with caching.
        
        Args:
            model_id: Model identifier
            use_cache: Whether to use cache
            
        Returns:
            Model dictionary or None
        """
        if not use_cache:
            return await ModelCacheService._fetch_model_from_db(model_id)
        
        cache_key = CacheKeyGenerator.model_catalog(model_id)
        
        # Try cache first
        cached_model = await cache_manager.get(cache_key, "model_catalog")
        if cached_model is not None:
            logger.debug("model_cache_hit", model_id=model_id)
            return cached_model
        
        # Fetch from database
        model = await ModelCacheService._fetch_model_from_db(model_id)
        
        if model:
            # Cache the result
            await cache_manager.set(cache_key, model, "model_catalog")
            logger.debug("model_cached", model_id=model_id)
        
        return model
    
    @staticmethod
    async def get_models_by_provider(
        provider: str,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all models for a specific provider."""
        return await ModelCacheService.get_all_models(provider=provider, use_cache=use_cache)
    
    @staticmethod
    async def get_embedding_models(use_cache: bool = True) -> List[Dict[str, Any]]:
        """Get all embedding-capable models."""
        cache_key = f"{CacheKeyGenerator.PREFIX}:models:embeddings"
        
        if use_cache:
            cached_models = await cache_manager.get(cache_key, "model_list")
            if cached_models is not None:
                return cached_models
        
        # Fetch embedding models from database
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            result = await db.execute(
                select(ModelCatalog)
                .where(and_(
                    ModelCatalog.embeddings == True,
                    ModelCatalog.status == "active"
                ))
                .order_by(ModelCatalog.display_name)
            )
            
            models = []
            for model in result.scalars().all():
                models.append(ModelCacheService._model_to_dict(model))
        
        if use_cache:
            await cache_manager.set(cache_key, models, "model_list")
        
        return models
    
    @staticmethod
    async def get_model_stats() -> Dict[str, Any]:
        """Get cached model statistics."""
        cache_key = f"{CacheKeyGenerator.PREFIX}:models:stats"
        
        # Try cache first
        cached_stats = await cache_manager.get(cache_key, "model_list")
        if cached_stats is not None:
            return cached_stats
        
        # Calculate stats from database
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            # Get counts by status
            total_count = await db.execute(select(func.count(ModelCatalog.model_id)))
            active_count = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "active"))
            deprecated_count = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "deprecated"))
            
            # Get provider distribution
            provider_result = await db.execute(
                select(ModelCatalog.provider, func.count(ModelCatalog.model_id))
                .where(ModelCatalog.status == "active")
                .group_by(ModelCatalog.provider)
            )
            
            provider_stats = {}
            for provider, count in provider_result:
                provider_stats[provider] = count
            
            stats = {
                "total_models": total_count.scalar() or 0,
                "active_models": active_count.scalar() or 0,
                "deprecated_models": deprecated_count.scalar() or 0,
                "provider_distribution": provider_stats,
                "last_updated": datetime.utcnow().isoformat()
            }
        
        # Cache for 10 minutes
        await cache_manager.set(cache_key, stats, "model_list", ttl_override=600)
        
        return stats
    
    @staticmethod
    async def invalidate_model_cache(model_id: Optional[str] = None):
        """Invalidate model cache entries."""
        await CacheInvalidator.invalidate_model_cache(model_id)
        
        # Also invalidate stats cache
        await cache_manager.delete(f"{CacheKeyGenerator.PREFIX}:models:stats", "model_list")
        await cache_manager.delete(f"{CacheKeyGenerator.PREFIX}:models:embeddings", "model_list")
    
    @staticmethod
    async def warm_cache(limit: int = 100):
        """
        Warm the model cache with frequently accessed models.
        
        Args:
            limit: Maximum number of models to pre-cache
        """
        logger.info("warming_model_cache", limit=limit)
        
        try:
            # Pre-cache all active models
            models = await ModelCacheService.get_all_models(status="active", use_cache=False)
            
            # Cache individual models (up to limit)
            for model in models[:limit]:
                model_id = model.get("model_id")
                if model_id:
                    cache_key = CacheKeyGenerator.model_catalog(model_id)
                    await cache_manager.set(cache_key, model, "model_catalog")
            
            # Pre-cache embedding models
            await ModelCacheService.get_embedding_models(use_cache=False)
            
            # Pre-cache model stats
            await ModelCacheService.get_model_stats()
            
            logger.info("model_cache_warmed", models_cached=len(models))
            
        except Exception as e:
            logger.exception("model_cache_warm_error")
    
    @staticmethod
    async def _fetch_models_from_db(
        provider: Optional[str] = None,
        status: str = "active"
    ) -> List[Dict[str, Any]]:
        """Fetch models from database."""
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            query = select(ModelCatalog).where(ModelCatalog.status == status)
            
            if provider:
                query = query.where(ModelCatalog.provider == provider)
            
            query = query.order_by(ModelCatalog.display_name)
            result = await db.execute(query)
            
            models = []
            for model in result.scalars().all():
                models.append(ModelCacheService._model_to_dict(model))
        
        return models
    
    @staticmethod
    async def _fetch_model_from_db(model_id: str) -> Optional[Dict[str, Any]]:
        """Fetch single model from database."""
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            result = await db.execute(
                select(ModelCatalog).where(ModelCatalog.model_id == model_id)
            )
            
            model = result.scalar_one_or_none()
            if model:
                return ModelCacheService._model_to_dict(model)
        
        return None
    
    @staticmethod
    def _model_to_dict(model: ModelCatalog) -> Dict[str, Any]:
        """Convert ModelCatalog to dictionary."""
        return {
            "model_id": model.model_id,
            "provider": model.provider,
            "display_name": model.display_name,
            "context_window": model.context_window,
            "input_price_per_1k": float(model.input_price_per_1k) if model.input_price_per_1k else 0.0,
            "output_price_per_1k": float(model.output_price_per_1k) if model.output_price_per_1k else 0.0,
            "supports_tools": model.supports_tools,
            "supports_vision": model.supports_vision,
            "supports_json_mode": model.supports_json_mode,
            "embeddings": model.embeddings,
            "status": model.status,
            "last_seen_at": model.last_seen_at.isoformat() if model.last_seen_at else None,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
            "metadata": model.metadata
        }


class SettingsCacheService:
    """
    Specialized caching service for application settings.
    Provides intelligent caching for global and workspace-specific settings.
    """
    
    @staticmethod
    async def get_global_settings(
        keys: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Get global settings with caching.
        
        Args:
            keys: Specific setting keys to retrieve (optional)
            use_cache: Whether to use cache
            
        Returns:
            Dictionary of settings
        """
        # Default global setting keys
        default_keys = [
            'global_default_model',
            'global_embed_model',
            'model_allowlist_global',
            'model_blocklist_global'
        ]
        
        keys_to_fetch = keys or default_keys
        
        if not use_cache:
            return await SettingsCacheService._fetch_settings_from_db(keys_to_fetch)
        
        cache_key = CacheKeyGenerator.global_settings()
        
        # Try cache first
        cached_settings = await cache_manager.get(cache_key, "global_settings")
        if cached_settings is not None:
            # Filter to requested keys if specified
            if keys:
                return {k: v for k, v in cached_settings.items() if k in keys}
            return cached_settings
        
        # Fetch from database
        settings_data = await SettingsCacheService._fetch_settings_from_db(keys_to_fetch)
        
        # Cache the result
        await cache_manager.set(cache_key, settings_data, "global_settings")
        
        logger.debug("global_settings_cached", keys_count=len(settings_data))
        return settings_data
    
    @staticmethod
    async def get_setting(
        key: str,
        default: Any = None,
        use_cache: bool = True
    ) -> Any:
        """
        Get a specific global setting value.
        
        Args:
            key: Setting key
            default: Default value if not found
            use_cache: Whether to use cache
            
        Returns:
            Setting value or default
        """
        if not use_cache:
            return await SettingsCacheService._fetch_setting_from_db(key, default)
        
        cache_key = CacheKeyGenerator.global_settings(key)
        
        # Try cache first
        cached_value = await cache_manager.get(cache_key, "global_settings")
        if cached_value is not None:
            return cached_value
        
        # Fetch from database
        value = await SettingsCacheService._fetch_setting_from_db(key, default)
        
        if value is not None:
            # Cache the individual setting
            await cache_manager.set(cache_key, value, "global_settings")
        
        return value
    
    @staticmethod
    async def set_setting(
        key: str,
        value: Any,
        invalidate_cache: bool = True
    ) -> bool:
        """
        Set a global setting and optionally invalidate cache.
        
        Args:
            key: Setting key
            value: Setting value
            invalidate_cache: Whether to invalidate related cache
            
        Returns:
            True if successful
        """
        try:
            from app.db.session import get_session_maker
            session_maker = get_session_maker()
            
            async with session_maker() as db:
                # Check if setting exists
                result = await db.execute(
                    select(Settings).where(Settings.key == key)
                )
                
                setting = result.scalar_one_or_none()
                
                if setting:
                    # Update existing
                    setting.value = value
                    setting.updated_at = datetime.utcnow()
                else:
                    # Create new
                    setting = Settings(
                        key=key,
                        value=value,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(setting)
                
                await db.commit()
            
            if invalidate_cache:
                await SettingsCacheService.invalidate_settings_cache(key)
            
            logger.info("setting_updated", key=key)
            return True
            
        except Exception as e:
            logger.exception("cache_warm_error", model_id=key)
            return False
    
    @staticmethod
    async def get_workspace_settings(
        workspace_id: str,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Get workspace-specific settings."""
        if not use_cache:
            return await SettingsCacheService._fetch_workspace_settings_from_db(workspace_id)
        
        cache_key = CacheKeyGenerator.workspace_settings(workspace_id)
        
        # Try cache first
        cached_settings = await cache_manager.get(cache_key, "workspace_settings")
        if cached_settings is not None:
            return cached_settings
        
        # Fetch from database
        settings_data = await SettingsCacheService._fetch_workspace_settings_from_db(workspace_id)
        
        # Cache the result
        await cache_manager.set(cache_key, settings_data, "workspace_settings")
        
        return settings_data
    
    @staticmethod
    async def get_api_key_settings(
        api_key: APIKey,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Get API key specific settings."""
        if not use_cache:
            return SettingsCacheService._extract_api_key_settings(api_key)
        
        cache_key = CacheKeyGenerator.api_key_settings(api_key.key_hash)
        
        # Try cache first
        cached_settings = await cache_manager.get(cache_key, "api_key_settings")
        if cached_settings is not None:
            return cached_settings
        
        # Extract settings from API key object
        settings_data = SettingsCacheService._extract_api_key_settings(api_key)
        
        # Cache the result
        await cache_manager.set(cache_key, settings_data, "api_key_settings")
        
        return settings_data
    
    @staticmethod
    async def invalidate_settings_cache(
        key: Optional[str] = None,
        workspace_id: Optional[str] = None,
        api_key_id: Optional[str] = None
    ):
        """Invalidate settings cache entries."""
        if key:
            # Invalidate specific setting
            await cache_manager.delete(CacheKeyGenerator.global_settings(key), "global_settings")
            # Also invalidate all global settings cache
            await cache_manager.delete(CacheKeyGenerator.global_settings(), "global_settings")
        elif workspace_id:
            await cache_manager.delete(CacheKeyGenerator.workspace_settings(workspace_id), "workspace_settings")
        elif api_key_id:
            await cache_manager.delete(CacheKeyGenerator.api_key_settings(api_key_id), "api_key_settings")
        else:
            # Invalidate all settings cache
            await CacheInvalidator.invalidate_settings_cache()
    
    @staticmethod
    async def warm_cache():
        """Warm the settings cache with commonly accessed settings."""
        logger.info("warming_settings_cache")
        
        try:
            # Pre-cache global settings
            await SettingsCacheService.get_global_settings(use_cache=False)
            
            # Pre-cache individual commonly accessed settings
            common_settings = [
                'global_default_model',
                'global_embed_model',
                'model_allowlist_global',
                'model_blocklist_global'
            ]
            
            for setting_key in common_settings:
                await SettingsCacheService.get_setting(setting_key, use_cache=False)
            
            logger.info("settings_cache_warmed")
            
        except Exception as e:
            logger.exception("cache_service_error")
    
    @staticmethod
    async def _fetch_settings_from_db(keys: List[str]) -> Dict[str, Any]:
        """Fetch settings from database."""
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            result = await db.execute(
                select(Settings.key, Settings.value)
                .where(Settings.key.in_(keys))
            )
            
            settings_dict = {}
            for row in result.mappings().all():
                settings_dict[row["key"]] = row["value"]
        
        return settings_dict
    
    @staticmethod
    async def _fetch_setting_from_db(key: str, default: Any = None) -> Any:
        """Fetch single setting from database."""
        from app.db.session import get_session_maker
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            result = await db.execute(
                select(Settings.value).where(Settings.key == key)
            )
            
            row = result.scalar_one_or_none()
            return row if row is not None else default
    
    @staticmethod
    async def _fetch_workspace_settings_from_db(workspace_id: str) -> Dict[str, Any]:
        """Fetch workspace settings from database."""
        # For now, workspace settings might be stored as JSON in global settings
        # or in a separate table. This is a placeholder implementation.
        return {
            "workspace_id": workspace_id,
            "default_model": None,
            "embed_model": None,
            "rate_limits": {},
            "features": {}
        }
    
    @staticmethod
    def _extract_api_key_settings(api_key: APIKey) -> Dict[str, Any]:
        """Extract settings from API key object."""
        return {
            "api_key_id": api_key.key_hash,
            "workspace_id": api_key.workspace_id,
            "name": api_key.name,
            "active": api_key.active,
            "rpm_limit": api_key.rpm_limit,
            "rph_limit": api_key.rph_limit,
            "monthly_budget": api_key.monthly_budget,
            "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
            "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None
        }


# Export main components
__all__ = [
    "ModelCacheService",
    "SettingsCacheService"
]