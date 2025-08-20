"""
Models API endpoints for model catalog and resolution.
"""
from typing import List, Dict, Any, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
import structlog

from app.core.config import settings
from app.core.security import get_api_key, get_optional_api_key
from app.db.session import get_db_dependency
from app.db.models import APIKey, ModelCatalog, Settings

router = APIRouter()
logger = structlog.get_logger(__name__)


async def get_global_settings(db) -> Dict[str, Any]:
    """Get global settings from database."""
    result = await db.execute(
        select(Settings.key, Settings.value)
        .where(Settings.key.in_([
            'global_default_model',
            'global_embed_model', 
            'model_allowlist_global',
            'model_blocklist_global'
        ]))
    )
    
    settings_dict = {}
    for row in result:
        settings_dict[row.key] = row.value
    
    return settings_dict


async def is_model_allowed(
    model_id: str,
    api_key: Optional[APIKey],
    global_settings: Dict[str, Any]
) -> bool:
    """
    Check if a model is allowed for the given API key.
    
    Args:
        model_id: Model ID to check
        api_key: API key record (None for public access)
        global_settings: Global settings from database
        
    Returns:
        bool: True if model is allowed, False otherwise
    """
    # Check per-key blocklist first
    if api_key and api_key.model_blocklist and model_id in api_key.model_blocklist:
        return False
    
    # Check global blocklist
    global_blocklist = global_settings.get('model_blocklist_global', [])
    if model_id in global_blocklist:
        return False
    
    # Check per-key allowlist if it exists
    if api_key and api_key.model_allowlist:
        return model_id in api_key.model_allowlist
    
    # Check global allowlist
    global_allowlist = global_settings.get('model_allowlist_global', [])
    if global_allowlist:
        return model_id in global_allowlist
    
    # If no allowlists are configured, allow all models not in blocklists
    return True


@router.get("/models")
async def list_models(
    api_key: Optional[APIKey] = Depends(get_optional_api_key),
    db = Depends(get_db_dependency)
) -> Dict[str, Any]:
    """
    List available models filtered by API key permissions.
    
    Returns:
        dict: Available models with metadata
    """
    # Get global settings
    global_settings = await get_global_settings(db)
    
    # Get all active models from catalog
    result = await db.execute(
        select(ModelCatalog)
        .where(ModelCatalog.status == 'active')
        .order_by(ModelCatalog.provider, ModelCatalog.model_id)
    )
    
    all_models = result.scalars().all()
    
    # Filter models based on permissions
    allowed_models = []
    for model in all_models:
        if await is_model_allowed(model.model_id, api_key, global_settings):
            model_data = {
                "id": model.model_id,
                "object": "model",
                "created": int(model.created_at.timestamp()) if model.created_at else 0,
                "owned_by": model.provider,
                "permission": [],
                "root": model.model_id,
                "parent": None,
                # Additional metadata
                "display_name": model.display_name,
                "context_window": model.context_window,
                "pricing": {
                    "input_per_1k": float(model.input_price_per_1k) if model.input_price_per_1k else None,
                    "output_per_1k": float(model.output_price_per_1k) if model.output_price_per_1k else None,
                },
                "capabilities": {
                    "tools": model.supports_tools,
                    "vision": model.supports_vision,
                    "json_mode": model.supports_json_mode,
                    "embeddings": model.embeddings,
                },
                "provider": model.provider,
                "status": model.status,
            }
            allowed_models.append(model_data)
    
    logger.info(
        "models_listed",
        total_models=len(all_models),
        allowed_models=len(allowed_models),
        workspace_id=api_key.workspace_id if api_key else None,
    )
    
    return {
        "object": "list",
        "data": allowed_models,
    }


async def resolve_model_for_request(
    requested_model: Optional[str],
    api_key: APIKey,
    purpose: str,  # 'chat' or 'embeddings'
    db
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve the model to use for a request based on resolution rules.
    
    Args:
        requested_model: Model requested by client
        api_key: API key record
        purpose: Purpose of the request ('chat' or 'embeddings')
        db: Database session
        
    Returns:
        tuple: (resolved_model_id, error_message)
    """
    global_settings = await get_global_settings(db)
    
    # Step 1: If client specifies model and it's allowed, use it
    if requested_model:
        if await is_model_allowed(requested_model, api_key, global_settings):
            # Verify model exists and is active
            result = await db.execute(
                select(ModelCatalog)
                .where(and_(
                    ModelCatalog.model_id == requested_model,
                    ModelCatalog.status == 'active'
                ))
            )
            model = result.scalar_one_or_none()
            
            if model:
                # Check if model supports the requested purpose
                if purpose == 'embeddings' and not model.embeddings:
                    return None, f"Model {requested_model} does not support embeddings"
                elif purpose == 'chat' and model.embeddings:
                    return None, f"Model {requested_model} is an embedding model, not a chat model"
                
                return requested_model, None
            else:
                return None, f"Model {requested_model} not found or inactive"
        else:
            return None, f"Model {requested_model} not allowed for this API key"
    
    # Step 2: Use per-API-key default if set and allowed
    default_field = 'default_embed_model' if purpose == 'embeddings' else 'default_model'
    per_key_default = getattr(api_key, default_field)
    
    if per_key_default:
        if await is_model_allowed(per_key_default, api_key, global_settings):
            result = await db.execute(
                select(ModelCatalog)
                .where(and_(
                    ModelCatalog.model_id == per_key_default,
                    ModelCatalog.status == 'active'
                ))
            )
            model = result.scalar_one_or_none()
            if model:
                return per_key_default, None
    
    # Step 3: Use global default from settings
    global_default_key = 'global_embed_model' if purpose == 'embeddings' else 'global_default_model'
    global_default_setting = global_settings.get(global_default_key)
    
    if global_default_setting and 'model_id' in global_default_setting:
        global_default = global_default_setting['model_id']
        if await is_model_allowed(global_default, api_key, global_settings):
            result = await db.execute(
                select(ModelCatalog)
                .where(and_(
                    ModelCatalog.model_id == global_default,
                    ModelCatalog.status == 'active'
                ))
            )
            model = result.scalar_one_or_none()
            if model:
                return global_default, None
    
    # Step 4: Fallback to environment variable (optional)
    env_fallback = settings.OPENROUTER_DEFAULT_MODEL
    if env_fallback:
        if await is_model_allowed(env_fallback, api_key, global_settings):
            result = await db.execute(
                select(ModelCatalog)
                .where(and_(
                    ModelCatalog.model_id == env_fallback,
                    ModelCatalog.status == 'active'
                ))
            )
            model = result.scalar_one_or_none()
            if model:
                return env_fallback, None
    
    # Step 5: No suitable model found
    return None, "No suitable model found. Please specify a model or configure defaults."


@router.get("/models/{model_id}")
async def get_model(
    model_id: str,
    api_key: Optional[APIKey] = Depends(get_optional_api_key),
    db = Depends(get_db_dependency)
) -> Dict[str, Any]:
    """
    Get details for a specific model.
    
    Args:
        model_id: Model ID to retrieve
        api_key: Optional API key for permission checking
        db: Database session
        
    Returns:
        dict: Model details
    """
    # Get global settings
    global_settings = await get_global_settings(db)
    
    # Check if model is allowed
    if not await is_model_allowed(model_id, api_key, global_settings):
        raise HTTPException(
            status_code=404,
            detail="Model not found or not allowed"
        )
    
    # Get model from catalog
    result = await db.execute(
        select(ModelCatalog)
        .where(and_(
            ModelCatalog.model_id == model_id,
            ModelCatalog.status == 'active'
        ))
    )
    
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    return {
        "id": model.model_id,
        "object": "model",
        "created": int(model.created_at.timestamp()) if model.created_at else 0,
        "owned_by": model.provider,
        "permission": [],
        "root": model.model_id,
        "parent": None,
        "display_name": model.display_name,
        "context_window": model.context_window,
        "pricing": {
            "input_per_1k": float(model.input_price_per_1k) if model.input_price_per_1k else None,
            "output_per_1k": float(model.output_price_per_1k) if model.output_price_per_1k else None,
        },
        "capabilities": {
            "tools": model.supports_tools,
            "vision": model.supports_vision,
            "json_mode": model.supports_json_mode,
            "embeddings": model.embeddings,
        },
        "provider": model.provider,
        "status": model.status,
        "last_seen_at": model.last_seen_at.isoformat() if model.last_seen_at else None,
        "metadata": model.metadata,
    }

