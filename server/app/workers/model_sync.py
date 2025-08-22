"""
Background job for synchronizing model catalog from OpenRouter.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import structlog
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.db.models import ModelCatalog
from app.services.openrouter import OpenRouterService
from app.workers.queue import sync_job
from app.core.config import settings

logger = structlog.get_logger(__name__)

@sync_job
def sync_model_catalog() -> Dict[str, Any]:
    """
    Synchronize model catalog from OpenRouter.
    
    This job:
    1. Fetches all available models from OpenRouter
    2. Updates existing models with new information
    3. Adds new models to the catalog
    4. Marks models not seen as deprecated
    5. Updates sync timestamp
    
    Returns:
        Dictionary with sync results
    """
    logger.info("model_sync_started")
    
    try:
        # Initialize OpenRouter service
        openrouter = OpenRouterService()
        
        # Fetch models from OpenRouter (using async method)
        import asyncio
        or_models = asyncio.run(openrouter.fetch_all_models())
        logger.info("openrouter_models_fetched", count=len(or_models))
        
        # Get database session
        with get_db_session() as db:
            # Track sync results
            results = {
                "total_fetched": len(or_models),
                "new_models": 0,
                "updated_models": 0,
                "deprecated_models": 0,
                "errors": [],
                "sync_time": datetime.utcnow().isoformat()
            }
            
            # Get existing models
            existing_models = {
                model.model_id: model
                for model in db.query(ModelCatalog).all()
            }
            
            # Track which models we've seen
            seen_model_ids = set()
            
            # Process each model from OpenRouter
            for or_model in or_models:
                try:
                    model_id = or_model.get("id")
                    if not model_id:
                        continue
                    
                    seen_model_ids.add(model_id)
                    
                    # Check if model exists
                    existing_model = existing_models.get(model_id)
                    
                    if existing_model:
                        # Update existing model
                        updated = _update_model(existing_model, or_model)
                        if updated:
                            results["updated_models"] += 1
                    else:
                        # Create new model
                        _create_model(db, or_model)
                        results["new_models"] += 1
                
                except Exception as e:
                    error_msg = f"Error processing model {or_model.get('id', 'unknown')}: {str(e)}"
                    logger.error("model_sync_error", error=error_msg)
                    results["errors"].append(error_msg)
            
            # Mark unseen models as deprecated
            for model_id, model in existing_models.items():
                if model_id not in seen_model_ids and model.status == "active":
                    model.status = "deprecated"
                    model.updated_at = datetime.utcnow()
                    results["deprecated_models"] += 1
            
            # Commit all changes
            db.commit()
            
            logger.info(
                "model_sync_completed",
                **{k: v for k, v in results.items() if k != "errors"}
            )
            
            return results
    
    except Exception as e:
        error_msg = f"Model sync failed: {str(e)}"
        logger.error("model_sync_failed", error=error_msg)
        return {
            "error": error_msg,
            "sync_time": datetime.utcnow().isoformat()
        }

def _update_model(existing_model: ModelCatalog, or_model: Dict[str, Any]) -> bool:
    """
    Update an existing model with new information from OpenRouter.
    
    Args:
        existing_model: Existing model from database
        or_model: Model data from OpenRouter
    
    Returns:
        True if model was updated, False otherwise
    """
    updated = False
    
    # Parse provider from model ID
    provider = or_model.get("id", "").split("/")[0] if "/" in or_model.get("id", "") else "unknown"
    
    # Fields to update (matching ModelCatalog schema)
    updates = {
        "display_name": or_model.get("name"),
        "provider": provider,
        "context_window": or_model.get("context_length"),
        "input_price_per_1k": _parse_cost(or_model.get("pricing", {}).get("prompt")),
        "output_price_per_1k": _parse_cost(or_model.get("pricing", {}).get("completion")),
        "supports_tools": or_model.get("architecture", {}).get("modality") == "text->text",
        "supports_vision": "image" in or_model.get("architecture", {}).get("input_modalities", []),
        "supports_json_mode": or_model.get("supports_json_mode", False),
        "metadata": {
            "description": or_model.get("description"),
            "architecture": or_model.get("architecture", {}),
            "top_provider": or_model.get("top_provider"),
            "moderation_required": or_model.get("moderation_required", False)
        }
    }
    
    # Update changed fields
    for field, new_value in updates.items():
        if new_value is not None and getattr(existing_model, field) != new_value:
            setattr(existing_model, field, new_value)
            updated = True
    
    # Update status if model is available again
    if existing_model.status == "deprecated":
        existing_model.status = "active"
        updated = True
    
    # Update last_seen_at
    existing_model.last_seen_at = datetime.utcnow()
    
    if updated:
        existing_model.updated_at = datetime.utcnow()
    
    return updated

def _create_model(db: Session, or_model: Dict[str, Any]) -> ModelCatalog:
    """
    Create a new model from OpenRouter data.
    
    Args:
        db: Database session
        or_model: Model data from OpenRouter
    
    Returns:
        Created model instance
    """
    # Parse provider from model ID
    provider = or_model.get("id", "").split("/")[0] if "/" in or_model.get("id", "") else "unknown"
    
    model = ModelCatalog(
        model_id=or_model["id"],
        provider=provider,
        display_name=or_model.get("name", or_model["id"]),
        context_window=or_model.get("context_length"),
        input_price_per_1k=_parse_cost(or_model.get("pricing", {}).get("prompt")),
        output_price_per_1k=_parse_cost(or_model.get("pricing", {}).get("completion")),
        supports_tools=or_model.get("architecture", {}).get("modality") == "text->text",
        supports_vision="image" in or_model.get("architecture", {}).get("input_modalities", []),
        supports_json_mode=or_model.get("supports_json_mode", False),
        embeddings=or_model.get("architecture", {}).get("modality") == "text->embedding",
        status="active",
        last_seen_at=datetime.utcnow(),
        metadata={
            "description": or_model.get("description"),
            "architecture": or_model.get("architecture", {}),
            "top_provider": or_model.get("top_provider"),
            "moderation_required": or_model.get("moderation_required", False)
        }
    )
    
    db.add(model)
    return model

def _parse_cost(cost_str: Optional[str]) -> Optional[float]:
    """
    Parse cost string to float and convert to per-1K rate.
    
    Args:
        cost_str: Cost string like "0.0000025" (per token)
    
    Returns:
        Cost per 1K tokens as float or None
    """
    if not cost_str:
        return None
    
    try:
        # Convert per-token cost to per-1K cost
        per_token_cost = float(str(cost_str).replace("$", "").strip())
        return per_token_cost * 1000
    except (ValueError, TypeError):
        return None

@sync_job
def cleanup_deprecated_models(days_old: int = 30) -> Dict[str, Any]:
    """
    Clean up deprecated models that haven't been used recently.
    
    Args:
        days_old: Number of days since last use to consider for cleanup
    
    Returns:
        Dictionary with cleanup results
    """
    logger.info("deprecated_model_cleanup_started", days_old=days_old)
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        with get_db_session() as db:
            # Find deprecated models not used recently
            deprecated_models = db.query(ModelCatalog).filter(
                ModelCatalog.status == "deprecated",
                ModelCatalog.updated_at < cutoff_date
            ).all()
            
            results = {
                "models_found": len(deprecated_models),
                "models_removed": 0,
                "cleanup_time": datetime.utcnow().isoformat()
            }
            
            # Remove old deprecated models
            for model in deprecated_models:
                try:
                    db.delete(model)
                    results["models_removed"] += 1
                    logger.info("deprecated_model_removed", model_id=model.id)
                except Exception as e:
                    logger.error("model_removal_failed", model_id=model.id, error=str(e))
            
            db.commit()
            
            logger.info("deprecated_model_cleanup_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Deprecated model cleanup failed: {str(e)}"
        logger.error("deprecated_model_cleanup_failed", error=error_msg)
        return {
            "error": error_msg,
            "cleanup_time": datetime.utcnow().isoformat()
        }

@sync_job
def update_model_usage_stats() -> Dict[str, Any]:
    """
    Update usage statistics for models based on request logs.
    
    Returns:
        Dictionary with update results
    """
    logger.info("model_usage_stats_update_started")
    
    try:
        with get_db_session() as db:
            # This would typically aggregate request logs
            # For now, we'll just update the timestamp
            
            results = {
                "models_updated": 0,
                "update_time": datetime.utcnow().isoformat()
            }
            
            # Update all active models' usage stats
            active_models = db.query(ModelCatalog).filter(
                ModelCatalog.status == "active"
            ).all()
            
            for model in active_models:
                # In a real implementation, this would:
                # 1. Count requests from RequestLog table
                # 2. Calculate average response time
                # 3. Update model popularity score
                # 4. Track error rates
                
                # For now, just update the timestamp
                model.updated_at = datetime.utcnow()
                results["models_updated"] += 1
            
            db.commit()
            
            logger.info("model_usage_stats_update_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Model usage stats update failed: {str(e)}"
        logger.error("model_usage_stats_update_failed", error=error_msg)
        return {
            "error": error_msg,
            "update_time": datetime.utcnow().isoformat()
        }

