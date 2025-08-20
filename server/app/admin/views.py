"""
Admin interface views for Context Memory Gateway.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import structlog

from app.db.session import get_db_dependency
from app.db.models import (
    APIKey, Workspace, ModelCatalog, SemanticItem, EpisodicItem, 
    Artifact, UsageStats, RequestLog
)
from app.core.config import settings

router = APIRouter()
logger = structlog.get_logger(__name__)

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="app/admin/templates")


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db_dependency)
):
    """Admin dashboard with system overview."""
    try:
        # Gather dashboard statistics
        stats = await _get_dashboard_stats(db)
        recent_activities = await _get_recent_activities(db)
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "stats": stats,
                "recent_activities": recent_activities,
            }
        )
    except Exception as e:
        logger.error("dashboard_error", error=str(e))
        raise HTTPException(status_code=500, detail="Dashboard error")


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_list(
    request: Request,
    db: Session = Depends(get_db_dependency),
    q: Optional[str] = None,
    status: Optional[str] = None,
    workspace: Optional[str] = None
):
    """API keys management page."""
    try:
        # Build query with filters
        query = db.query(APIKey).join(Workspace)
        
        if q:
            query = query.filter(APIKey.key_prefix.ilike(f"%{q}%"))
        if status:
            query = query.filter(APIKey.status == status)
        if workspace:
            query = query.filter(Workspace.name.ilike(f"%{workspace}%"))
        
        api_keys = query.order_by(desc(APIKey.created_at)).limit(50).all()
        
        # Format keys for template
        formatted_keys = []
        for key in api_keys:
            # Get usage stats
            usage_stats = db.query(RequestLog).filter(
                RequestLog.api_key_id == key.id
            ).count()
            
            formatted_keys.append({
                'id': key.id,
                'key_prefix': key.key_prefix,
                'workspace_name': key.workspace.name,
                'status': key.status,
                'requests_count': usage_stats,
                'quota_limit': key.quota_limit or 100000,
                'created_at': key.created_at.strftime('%Y-%m-%d'),
                'last_used_at': _format_last_used(key.last_used_at),
            })
        
        # Get stats for cards
        stats = await _get_api_key_stats(db)
        
        return templates.TemplateResponse(
            "api_keys.html",
            {
                "request": request,
                "api_keys": formatted_keys,
                "stats": stats,
            }
        )
    except Exception as e:
        logger.error("api_keys_error", error=str(e))
        raise HTTPException(status_code=500, detail="API keys error")


@router.get("/models", response_class=HTMLResponse)
async def models_list(
    request: Request,
    db: Session = Depends(get_db_dependency),
    q: Optional[str] = None,
    provider: Optional[str] = None,
    status: Optional[str] = None
):
    """Models catalog management page."""
    try:
        # Build query with filters
        query = db.query(ModelCatalog)
        
        if q:
            query = query.filter(ModelCatalog.name.ilike(f"%{q}%"))
        if provider:
            query = query.filter(ModelCatalog.provider.ilike(f"%{provider}%"))
        if status:
            query = query.filter(ModelCatalog.status == status)
        
        models = query.order_by(ModelCatalog.name).limit(100).all()
        
        # Format models for template
        formatted_models = []
        for model in models:
            # Get usage stats
            usage_count = db.query(RequestLog).filter(
                RequestLog.model_id == model.id
            ).count()
            
            formatted_models.append({
                'id': model.id,
                'name': model.name,
                'provider': model.provider,
                'input_cost': model.input_cost or 0.0,
                'output_cost': model.output_cost or 0.0,
                'context_length': model.context_length or 0,
                'status': model.status,
                'requests_count': usage_count,
                'description': model.description or '',
            })
        
        # Get stats for cards
        stats = await _get_model_stats(db)
        
        # Get sync info
        last_sync = await _get_last_sync_time(db)
        total_models = len(models)
        active_models = len([m for m in models if m.status == 'active'])
        
        return templates.TemplateResponse(
            "models.html",
            {
                "request": request,
                "models": formatted_models,
                "stats": stats,
                "last_sync": last_sync,
                "total_models": total_models,
                "active_models": active_models,
            }
        )
    except Exception as e:
        logger.error("models_error", error=str(e))
        raise HTTPException(status_code=500, detail="Models error")


@router.get("/usage", response_class=HTMLResponse)
async def usage_analytics(
    request: Request,
    db: Session = Depends(get_db_dependency)
):
    """Usage analytics page."""
    try:
        # Get usage analytics data
        analytics = await _get_usage_analytics(db)
        
        return templates.TemplateResponse(
            "usage.html",
            {
                "request": request,
                "analytics": analytics,
            }
        )
    except Exception as e:
        logger.error("usage_analytics_error", error=str(e))
        raise HTTPException(status_code=500, detail="Usage analytics error")


@router.get("/context", response_class=HTMLResponse)
async def context_memory(
    request: Request,
    db: Session = Depends(get_db_dependency)
):
    """Context memory management page."""
    try:
        # Get context memory stats
        context_stats = await _get_context_stats(db)
        
        return templates.TemplateResponse(
            "context.html",
            {
                "request": request,
                "context_stats": context_stats,
            }
        )
    except Exception as e:
        logger.error("context_memory_error", error=str(e))
        raise HTTPException(status_code=500, detail="Context memory error")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db_dependency)
):
    """System settings page."""
    try:
        # Get current settings
        current_settings = {
            'openrouter_api_key': settings.OPENROUTER_API_KEY[:8] + "..." if settings.OPENROUTER_API_KEY else None,
            'default_model': settings.DEFAULT_MODEL,
            'max_tokens': settings.MAX_TOKENS,
            'rate_limit_requests': settings.RATE_LIMIT_REQUESTS,
            'rate_limit_window': settings.RATE_LIMIT_WINDOW,
            'database_url': settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else "Not configured",
            'redis_url': settings.REDIS_URL.split('@')[1] if '@' in settings.REDIS_URL else "Not configured",
        }
        
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "settings": current_settings,
            }
        )
    except Exception as e:
        logger.error("settings_error", error=str(e))
        raise HTTPException(status_code=500, detail="Settings error")


# API Key Management Actions
@router.post("/api-keys/{key_id}/suspend")
async def suspend_api_key(
    key_id: str,
    db: Session = Depends(get_db_dependency)
):
    """Suspend an API key."""
    try:
        api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        
        api_key.status = 'suspended'
        db.commit()
        
        logger.info("api_key_suspended", key_id=key_id)
        
        # Return updated table
        return await api_keys_list(request=None, db=db)
    
    except Exception as e:
        logger.error("suspend_api_key_error", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to suspend API key")


@router.post("/api-keys/{key_id}/activate")
async def activate_api_key(
    key_id: str,
    db: Session = Depends(get_db_dependency)
):
    """Activate an API key."""
    try:
        api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        
        api_key.status = 'active'
        db.commit()
        
        logger.info("api_key_activated", key_id=key_id)
        
        # Return updated table
        return await api_keys_list(request=None, db=db)
    
    except Exception as e:
        logger.error("activate_api_key_error", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to activate API key")


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    db: Session = Depends(get_db_dependency)
):
    """Delete an API key."""
    try:
        api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        
        db.delete(api_key)
        db.commit()
        
        logger.info("api_key_deleted", key_id=key_id)
        
        # Return updated table
        return await api_keys_list(request=None, db=db)
    
    except Exception as e:
        logger.error("delete_api_key_error", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to delete API key")


# Model Management Actions
@router.post("/models/sync")
async def sync_models(
    db: Session = Depends(get_db_dependency)
):
    """Sync models from OpenRouter."""
    try:
        # This would typically trigger a background job
        # For now, just update the sync timestamp
        logger.info("model_sync_triggered")
        
        # Return updated table
        return await models_list(request=None, db=db)
    
    except Exception as e:
        logger.error("sync_models_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to sync models")


@router.post("/models/{model_id}/disable")
async def disable_model(
    model_id: str,
    db: Session = Depends(get_db_dependency)
):
    """Disable a model."""
    try:
        model = db.query(ModelCatalog).filter(ModelCatalog.id == model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        
        model.status = 'disabled'
        db.commit()
        
        logger.info("model_disabled", model_id=model_id)
        
        # Return updated table
        return await models_list(request=None, db=db)
    
    except Exception as e:
        logger.error("disable_model_error", model_id=model_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to disable model")


@router.post("/models/{model_id}/enable")
async def enable_model(
    model_id: str,
    db: Session = Depends(get_db_dependency)
):
    """Enable a model."""
    try:
        model = db.query(ModelCatalog).filter(ModelCatalog.id == model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        
        model.status = 'active'
        db.commit()
        
        logger.info("model_enabled", model_id=model_id)
        
        # Return updated table
        return await models_list(request=None, db=db)
    
    except Exception as e:
        logger.error("enable_model_error", model_id=model_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to enable model")


# Helper functions
async def _get_dashboard_stats(db: Session) -> Dict[str, Any]:
    """Get dashboard statistics."""
    try:
        total_requests = db.query(RequestLog).count()
        active_keys = db.query(APIKey).filter(APIKey.status == 'active').count()
        
        # Context items
        semantic_items = db.query(SemanticItem).count()
        episodic_items = db.query(EpisodicItem).count()
        context_items = semantic_items + episodic_items
        
        # Average response time (placeholder)
        avg_response_time = "245ms"
        
        return {
            'total_requests': total_requests,
            'active_keys': active_keys,
            'context_items': context_items,
            'semantic_items': semantic_items,
            'episodic_items': episodic_items,
            'avg_response_time': avg_response_time,
        }
    except Exception as e:
        logger.error("get_dashboard_stats_error", error=str(e))
        return {}


async def _get_recent_activities(db: Session) -> List[Dict[str, Any]]:
    """Get recent system activities."""
    try:
        # This would typically come from an activity log table
        # For now, return mock data
        return [
            {
                'type': 'api_key',
                'message': 'New API key created for workspace "Production"',
                'time': '2 minutes ago',
                'icon': 'key',
                'color': 'green'
            },
            {
                'type': 'context',
                'message': 'Context ingestion completed for thread "chat-session-123"',
                'time': '5 minutes ago',
                'icon': 'database',
                'color': 'blue'
            },
            {
                'type': 'model',
                'message': 'Model catalog synchronized from OpenRouter',
                'time': '15 minutes ago',
                'icon': 'refresh-cw',
                'color': 'purple'
            },
        ]
    except Exception as e:
        logger.error("get_recent_activities_error", error=str(e))
        return []


async def _get_api_key_stats(db: Session) -> Dict[str, Any]:
    """Get API key statistics."""
    try:
        active_keys = db.query(APIKey).filter(APIKey.status == 'active').count()
        suspended_keys = db.query(APIKey).filter(APIKey.status == 'suspended').count()
        total_requests = db.query(RequestLog).count()
        
        return {
            'active_keys': active_keys,
            'suspended_keys': suspended_keys,
            'total_requests': f"{total_requests:,}",
        }
    except Exception as e:
        logger.error("get_api_key_stats_error", error=str(e))
        return {}


async def _get_model_stats(db: Session) -> Dict[str, Any]:
    """Get model statistics."""
    try:
        active_models = db.query(ModelCatalog).filter(ModelCatalog.status == 'active').count()
        deprecated_models = db.query(ModelCatalog).filter(ModelCatalog.status == 'deprecated').count()
        
        # Most used model (placeholder)
        most_used_model = "GPT-4"
        total_requests = "45.2K"
        
        return {
            'active_models': active_models,
            'deprecated_models': deprecated_models,
            'most_used_model': most_used_model,
            'total_requests': total_requests,
        }
    except Exception as e:
        logger.error("get_model_stats_error", error=str(e))
        return {}


async def _get_usage_analytics(db: Session) -> Dict[str, Any]:
    """Get usage analytics data."""
    try:
        # This would typically aggregate request logs
        return {
            'daily_requests': [120, 190, 300, 500, 420, 380, 290],
            'model_distribution': {
                'GPT-4': 35,
                'Claude-3': 25,
                'Gemini Pro': 20,
                'GPT-3.5': 15,
                'Others': 5
            }
        }
    except Exception as e:
        logger.error("get_usage_analytics_error", error=str(e))
        return {}


async def _get_context_stats(db: Session) -> Dict[str, Any]:
    """Get context memory statistics."""
    try:
        semantic_items = db.query(SemanticItem).count()
        episodic_items = db.query(EpisodicItem).count()
        artifacts = db.query(Artifact).count()
        
        return {
            'semantic_items': semantic_items,
            'episodic_items': episodic_items,
            'artifacts': artifacts,
            'total_items': semantic_items + episodic_items,
        }
    except Exception as e:
        logger.error("get_context_stats_error", error=str(e))
        return {}


async def _get_last_sync_time(db: Session) -> str:
    """Get last model sync time."""
    try:
        # This would typically come from a sync log table
        return "2 hours ago"
    except Exception as e:
        logger.error("get_last_sync_time_error", error=str(e))
        return "Unknown"


def _format_last_used(last_used_at: Optional[datetime]) -> str:
    """Format last used timestamp."""
    if not last_used_at:
        return "Never"
    
    now = datetime.utcnow()
    diff = now - last_used_at
    
    if diff.days > 0:
        return f"{diff.days} days ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hours ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minutes ago"
    else:
        return "Just now"

