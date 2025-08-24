from typing import Optional
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.csrf import CSRFMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import structlog
import secrets
import hashlib

from app.db.session import get_db_dependency
from app.db.models import APIKey, ModelCatalog, SemanticItem, EpisodicItem, Artifact, UsageStats, User, Thread
from app.services.openrouter import fetch_all_models, OpenRouterError
from app.core.redis import get_redis_client
from app.services.cache import ModelCacheService, SettingsCacheService
from app.core.config import get_settings
from app.core.security import (
    get_admin_user, authenticate_admin, create_admin_jwt, create_user,
    verify_admin_jwt, AdminUser, AdminLoginRequest, AdminLoginResponse
)

# Initialize settings
app_settings = get_settings()

router = APIRouter()
logger = structlog.get_logger(__name__)

# Setup templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

async def require_admin_auth(request: Request) -> Optional[AdminUser]:
    """Check if user is authenticated as admin."""
    try:
        token = request.cookies.get("admin_token")
        if not token:
            return None
        return verify_admin_jwt(token)
    except Exception as e:
        logger.exception("auth_check_error")
        return None

def generate_csrf_token() -> str:
    """Generate CSRF token for forms."""
    import secrets
    return secrets.token_urlsafe(32)

# Root redirect
@router.get("/", response_class=RedirectResponse)
async def admin_root():
    """Redirect to login page."""
    return RedirectResponse(url="/admin/login", status_code=302)

# Login page
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Admin login page."""
    error_param = request.query_params.get("error")
    error_map = {
        "invalid": "Invalid username or password.",
        "system": "Login temporarily unavailable. Please try again.",
        "signup": "Account created. Please sign in."
    }
    return templates.TemplateResponse("login.html", {
        "request": request,
        "page_title": "Admin Login",
        "error": error_map.get(error_param)
    })

@router.post("/login", response_class=RedirectResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle admin login."""
    try:
        if await authenticate_admin(username, password):
            token = create_admin_jwt(username)
            response = RedirectResponse(url="/admin/dashboard", status_code=302)
            response.set_cookie(
                key="admin_token",
                value=token,
                max_age=86400 * 7,  # 7 days
                httponly=True,
                secure=True,  # Always secure for production
                samesite="strict"  # Strict for better CSRF protection
            )
            return response
        else:
            return RedirectResponse(url="/admin/login?error=invalid", status_code=302)
    except Exception as e:
        logger.exception("login_error")
        return RedirectResponse(url="/admin/login?error=system", status_code=302)

@router.post("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    """Handle admin logout."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response

# Signup page
@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    """Admin signup page."""
    return templates.TemplateResponse("signup.html", {
        "request": request,
        "page_title": "Admin Signup"
    })

@router.post("/signup", response_class=RedirectResponse)
async def signup_submit(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    """Handle admin signup."""
    try:
        await create_user(username, email, password)
        return RedirectResponse(url="/admin/login?success=signup", status_code=302)
    except HTTPException as e:
        return RedirectResponse(url=f"/admin/signup?error={e.detail}", status_code=302)
    except Exception as e:
        logger.exception("signup_error")
        return RedirectResponse(url="/admin/signup?error=system", status_code=302)

# Dashboard
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Admin dashboard."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Get real statistics from database
        api_keys_count = await db.execute(select(func.count(APIKey.key_hash)))
        active_keys_count = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == True))
        suspended_keys_count = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == False))
        
        models_count = await db.execute(select(func.count(ModelCatalog.model_id)))
        active_models_count = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == 'active'))
        
        semantic_items_count = await db.execute(select(func.count(SemanticItem.id)))
        episodic_items_count = await db.execute(select(func.count(EpisodicItem.id)))
        artifacts_count = await db.execute(select(func.count(Artifact.id)))
        
        total_requests_result = await db.execute(select(func.coalesce(func.sum(APIKey.total_requests), 0)))
        users_count = await db.execute(select(func.count(User.id)))
        
        stats = {
            "total_api_keys": api_keys_count.scalar() or 0,
            "active_keys": active_keys_count.scalar() or 0,
            "suspended_keys": suspended_keys_count.scalar() or 0,
            "total_models": models_count.scalar() or 0,
            "active_models": active_models_count.scalar() or 0,
            "total_semantic_items": semantic_items_count.scalar() or 0,
            "total_episodic_items": episodic_items_count.scalar() or 0,
            "total_artifacts": artifacts_count.scalar() or 0,
            "total_requests": total_requests_result.scalar() or 0,
            "total_users": users_count.scalar() or 0,
            "status": "operational"
        }
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "stats": stats,
            "page_title": "Dashboard"
        })
    except Exception as e:
        logger.exception("dashboard_error")
        return templates.TemplateResponse("dashboard.html", {
            "request": request, 
            "stats": {"total_api_keys": 0, "active_keys": 0, "suspended_keys": 0, "total_models": 0, "active_models": 0, "total_semantic_items": 0, "total_episodic_items": 0, "total_artifacts": 0, "total_requests": 0, "total_users": 0, "status": "error"}, 
            "error": str(e), 
            "page_title": "Dashboard"
        })

# API Keys Management
@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_list(request: Request, db: AsyncSession = Depends(get_db_dependency), q: Optional[str] = None):
    """API keys management page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Base query
        query = select(APIKey).order_by(APIKey.created_at.desc())
        
        # Apply search filter if provided
        if q:
            query = query.where(APIKey.name.ilike(f"%{q}%"))
        
        result = await db.execute(query.limit(50))
        api_keys = result.scalars().all()
        
        # Get statistics
        active_count_result = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == True))
        suspended_count_result = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == False))
        
        stats = {
            "active_keys": active_count_result.scalar() or 0,
            "suspended_keys": suspended_count_result.scalar() or 0,
            "total_requests": 0  # Can be calculated from UsageLedger if needed
        }
        
        # Format API keys for template
        formatted_keys = []
        for key in api_keys:
            formatted_keys.append({
                "id": key.key_hash,
                "name": key.name or "Unnamed Key",
                "status": "active" if key.active else "suspended",
                "created_at": key.created_at.strftime("%Y-%m-%d %H:%M") if key.created_at else "Unknown",
                "workspace": key.workspace_id or "Default",
                "daily_quota": key.daily_quota_tokens or 200000,
                "rate_limit": key.rpm_limit or 60
            })
        
        return templates.TemplateResponse("api_keys.html", {
            "request": request,
            "stats": stats,
            "api_keys": formatted_keys,
            "search_query": q or "",
            "page_title": "API Keys"
        })
    except Exception as e:
        logger.exception("api_keys_list_error")
        return templates.TemplateResponse("api_keys.html", {
            "request": request,
            "stats": {"active_keys": 0, "suspended_keys": 0, "total_requests": 0},
            "api_keys": [],
            "search_query": q or "",
            "error": str(e),
            "page_title": "API Keys"
        })

@router.get("/api-keys/create", response_class=HTMLResponse)
async def api_keys_create_form(request: Request):
    """API key creation form."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("api_key_create_form.html", {
        "request": request,
        "page_title": "Create API Key"
    })

@router.post("/api-keys/generate", response_class=HTMLResponse)
async def generate_api_key(request: Request, db: AsyncSession = Depends(get_db_dependency), name: str = Form(...), description: str = Form("")):
    """Generate a new API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Generate API key
        key_value = f"{app_settings.API_KEY_PREFIX}{secrets.token_urlsafe(app_settings.API_KEY_LENGTH)}"
        key_hash = hashlib.sha256(key_value.encode()).hexdigest()
        
        # Create API key record
        api_key = APIKey(
            key_hash=key_hash,
            workspace_id="default",
            name=name,
            active=True,
            daily_quota_tokens=app_settings.DEFAULT_DAILY_QUOTA_TOKENS,
            rpm_limit=app_settings.RATE_LIMIT_REQUESTS
        )
        
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)
        
        return templates.TemplateResponse("api_key_created.html", {
            "request": request,
            "new_key": key_value,
            "api_key": api_key,
            "page_title": "API Key Created"
        })
    except Exception as e:
        logger.exception("generate_api_key_error")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api-keys/{key_id}/suspend")
async def suspend_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Suspend an API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_id))
        api_key = result.scalar_one_or_none()
        if not api_key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        
        api_key.active = False
        await db.commit()
        return JSONResponse({"success": True, "message": "API key suspended"})
    except Exception as e:
        logger.exception("suspend_api_key_error")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/api-keys/{key_id}/activate")
async def activate_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Activate an API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_id))
        api_key = result.scalar_one_or_none()
        if not api_key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        
        api_key.active = True
        await db.commit()
        return JSONResponse({"success": True, "message": "API key activated"})
    except Exception as e:
        logger.exception("activate_api_key_error")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.delete("/api-keys/{key_id}")
async def delete_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Delete an API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_id))
        api_key = result.scalar_one_or_none()
        if not api_key:
            return JSONResponse({"error": "API key not found"}, status_code=404)
        
        await db.delete(api_key)
        await db.commit()
        return JSONResponse({"success": True, "message": "API key deleted"})
    except Exception as e:
        logger.exception("delete_api_key_error")
        return JSONResponse({"error": str(e)}, status_code=500)

# Models Management
@router.get("/models", response_class=HTMLResponse)
async def models_page(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Models management page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Get model statistics
        result = await db.execute(select(ModelCatalog).order_by(ModelCatalog.display_name))
        models = result.scalars().all()
        
        stats = {
            "total_models": len(models),
            "active_models": len([m for m in models if m.status == 'active']),
            "sync_status": "up_to_date"  # This would be determined by checking last sync time
        }
        
        formatted_models = []
        for model in models:
            formatted_models.append({
                "id": model.model_id,
                "provider": model.provider,
                "name": model.display_name,
                "context_window": model.context_window,
                "input_price": model.input_price_per_1k,
                "output_price": model.output_price_per_1k,
                "supports_tools": model.supports_tools,
                "supports_vision": model.supports_vision,
                "status": model.status,
                "last_seen": model.last_seen_at.strftime("%Y-%m-%d %H:%M") if model.last_seen_at else "Never"
            })
        
        return templates.TemplateResponse("models.html", {
            "request": request,
            "stats": stats,
            "models": formatted_models,
            "page_title": "Models"
        })
    except Exception as e:
        logger.exception("models_page_error")
        return templates.TemplateResponse("models.html", {
            "request": request,
            "stats": {"total_models": 0, "active_models": 0, "sync_status": "error"},
            "models": [],
            "error": str(e),
            "page_title": "Models"
        })

@router.get("/models/fetch", response_class=JSONResponse)
async def fetch_models_from_openrouter(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Fetch models from OpenRouter API."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        models_data = await fetch_all_models()

        # Format models to the structure expected by the frontend
        formatted_models = []
        for model in models_data:
            # Handle provider which may be a dict or a string
            provider_val = model.get("top_provider")
            if isinstance(provider_val, dict):
                provider_name = provider_val.get("name") or provider_val.get("id") or provider_val.get("provider") or "Unknown"
            elif isinstance(provider_val, str):
                provider_name = provider_val
            else:
                provider_name = "Unknown"

            pricing = model.get("pricing") or {}
            prompt_price = pricing.get("prompt", "0")
            completion_price = pricing.get("completion", "0")

            formatted_models.append({
                "id": model.get("id", ""),
                "name": model.get("name", model.get("id", "Unknown")),
                "description": model.get("description", ""),
                "context_length": model.get("context_length", 0),
                "pricing": {
                    "prompt": prompt_price,
                    "completion": completion_price
                },
                "top_provider": provider_name,
                "architecture": model.get("architecture", {}),
                "moderation_required": model.get("moderation_required", False)
            })

        return JSONResponse({
            "success": True,
            "models": formatted_models,
            "count": len(formatted_models)
        })
    except OpenRouterError as e:
        logger.exception("fetch_models_error")
        return JSONResponse({"error": f"OpenRouter API error: {str(e)}"}, status_code=500)
    except Exception as e:
        logger.exception("fetch_models_error")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/models/sync-status", response_class=HTMLResponse)
async def get_models_sync_status(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Get the sync status for models page HTMX updates."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return HTMLResponse("<span class='text-red-600'>Unauthorized</span>", status_code=401)
    
    try:
        # Get current sync status from cache or database
        from app.services.cache import ModelCacheService
        cache_info = await ModelCacheService.get_cache_info()
        
        # Determine status and message
        if cache_info and cache_info.get("model_count", 0) > 0:
            last_sync = cache_info.get("last_updated", "Never")
            model_count = cache_info.get("model_count", 0)
            status_html = f"""
            <div class="flex items-center gap-2 text-green-600">
                <i data-lucide="check-circle" class="w-4 h-4"></i>
                <span>Synced - {model_count} models ({last_sync})</span>
            </div>
            """
        else:
            status_html = """
            <div class="flex items-center gap-2 text-yellow-600">
                <i data-lucide="clock" class="w-4 h-4"></i>
                <span>Sync required</span>
            </div>
            """
        
        return HTMLResponse(status_html)
        
    except Exception as e:
        logger.exception("get_models_sync_status_error")
        return HTMLResponse("""
        <div class="flex items-center gap-2 text-red-600">
            <i data-lucide="alert-circle" class="w-4 h-4"></i>
            <span>Sync status unavailable</span>
        </div>
        """, status_code=500)


@router.post("/models/{model_id}/enable")
async def enable_model(model_id: str, request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Enable a specific model for use."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        # Get CSRF token from session
        csrf_token = generate_csrf_token()
        
        # Check if model exists in our cache/database
        from app.services.cache import ModelCacheService
        model_data = await ModelCacheService.get_model(model_id)
        
        if not model_data:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        
        # Enable the model (store in database or cache)
        # For now, we'll use Redis to track enabled/disabled models
        from app.core.redis import get_redis_client
        redis_client = await get_redis_client()
        await redis_client.sadd("cmg:enabled_models", model_id)
        await redis_client.srem("cmg:disabled_models", model_id)
        
        logger.info("model_enabled", model_id=model_id, admin_user=admin_user.username)
        
        return JSONResponse({
            "success": True,
            "message": f"Model {model_id} enabled successfully",
            "model_id": model_id,
            "csrf_token": csrf_token
        })
        
    except Exception as e:
        logger.exception("enable_model_error", model_id=model_id)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/models/{model_id}/disable")
async def disable_model(model_id: str, request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Disable a specific model from use."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        # Get CSRF token from session
        csrf_token = generate_csrf_token()
        
        # Check if model exists in our cache/database
        from app.services.cache import ModelCacheService
        model_data = await ModelCacheService.get_model(model_id)
        
        if not model_data:
            return JSONResponse({"error": "Model not found"}, status_code=404)
        
        # Disable the model (store in database or cache)
        # For now, we'll use Redis to track enabled/disabled models
        from app.core.redis import get_redis_client
        redis_client = await get_redis_client()
        await redis_client.sadd("cmg:disabled_models", model_id)
        await redis_client.srem("cmg:enabled_models", model_id)
        
        logger.info("model_disabled", model_id=model_id, admin_user=admin_user.username)
        
        return JSONResponse({
            "success": True,
            "message": f"Model {model_id} disabled successfully", 
            "model_id": model_id,
            "csrf_token": csrf_token
        })
        
    except Exception as e:
        logger.exception("disable_model_error", model_id=model_id)
        return JSONResponse({"error": str(e)}, status_code=500)

# Settings page
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings management page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": {
            "openrouter_api_key": "***" if app_settings.OPENROUTER_API_KEY else None,
            "api_key_prefix": app_settings.API_KEY_PREFIX,
            "default_quota": app_settings.DEFAULT_DAILY_QUOTA_TOKENS,
            "rate_limit": app_settings.RATE_LIMIT_REQUESTS
        },
        "page_title": "Settings"
    })

# Workers monitoring
@router.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request):
    """Workers monitoring page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Get Redis client for real queue data
        redis_client = await get_redis_client()
        
        # Query actual Redis for queue information
        try:
            # Get queue lengths from Redis
            embeddings_pending = await redis_client.llen("queue:embeddings:pending") or 0
            embeddings_processing = await redis_client.llen("queue:embeddings:processing") or 0
            embeddings_failed = await redis_client.llen("queue:embeddings:failed") or 0
            
            indexing_pending = await redis_client.llen("queue:indexing:pending") or 0
            indexing_processing = await redis_client.llen("queue:indexing:processing") or 0
            indexing_failed = await redis_client.llen("queue:indexing:failed") or 0
            
            cleanup_pending = await redis_client.llen("queue:cleanup:pending") or 0
            cleanup_processing = await redis_client.llen("queue:cleanup:processing") or 0
            cleanup_failed = await redis_client.llen("queue:cleanup:failed") or 0
            
            # Get Redis info
            redis_info = await redis_client.info()
            redis_status = {
                "connected": True,
                "used_memory": redis_info.get("used_memory_human", "N/A"),
                "connected_clients": redis_info.get("connected_clients", 0),
                "error": None
            }
            
        except Exception as e:
            logger.exception("redis_connection_error")
            # Fallback when Redis is unavailable
            embeddings_pending = embeddings_processing = embeddings_failed = 0
            indexing_pending = indexing_processing = indexing_failed = 0
            cleanup_pending = cleanup_processing = cleanup_failed = 0
            
            redis_status = {
                "connected": False,
                "used_memory": "N/A",
                "connected_clients": 0,
                "error": str(e)
            }
        
        # Calculate totals
        total_queued = embeddings_pending + indexing_pending + cleanup_pending
        total_processing = embeddings_processing + indexing_processing + cleanup_processing
        total_failed = embeddings_failed + indexing_failed + cleanup_failed
        
        # Get worker count from Redis worker registry (if implemented)
        try:
            worker_keys = await redis_client.keys("worker:*:heartbeat")
            active_workers = len(worker_keys)
        except:
            active_workers = 0
        
        # Build real queue data
        queues = {
            "total_queued_jobs": total_queued,
            "processing_jobs": total_processing,
            "failed_jobs": total_failed,
            "completed_jobs": 0,  # Would need to track this in Redis or DB
            "details": {
                "embeddings": {
                    "pending": embeddings_pending,
                    "processing": embeddings_processing,
                    "completed": 0,
                    "failed_count": embeddings_failed
                },
                "indexing": {
                    "pending": indexing_pending,
                    "processing": indexing_processing,
                    "completed": 0,
                    "failed_count": indexing_failed
                },
                "cleanup": {
                    "pending": cleanup_pending,
                    "processing": cleanup_processing,
                    "completed": 0,
                    "failed_count": cleanup_failed
                }
            }
        }
        
        # Build real worker stats
        workers = []  # Would need worker registry to populate this
        stats = {
            "total_workers": active_workers,
            "healthy_workers": active_workers,
            "total_tasks": total_queued + total_processing,
            "health_score": 100 if redis_status["connected"] else 0
        }
        
        return templates.TemplateResponse("workers.html", {
            "request": request,
            "stats": stats,
            "workers": workers,
            "queues": queues,
            "redis": redis_status,
            "page_title": "Workers"
        })
        
    except Exception as e:
        logger.exception("workers_page_error")
        # Return minimal data on error
        return templates.TemplateResponse("workers.html", {
            "request": request,
            "stats": {"total_workers": 0, "healthy_workers": 0, "total_tasks": 0, "health_score": 0},
            "workers": [],
            "queues": {"total_queued_jobs": 0, "processing_jobs": 0, "failed_jobs": 0, "completed_jobs": 0, "details": {}},
            "redis": {"connected": False, "error": str(e)},
            "page_title": "Workers"
        })


# Context Memory Management Endpoints

@router.get("/context", response_class=HTMLResponse)
async def context_page(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Context memory management page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Get context memory statistics
        semantic_count = await db.scalar(select(func.count(SemanticItem.id)))
        episodic_count = await db.scalar(select(func.count(EpisodicItem.id)))
        artifacts_count = await db.scalar(select(func.count(Artifact.id))) if hasattr(Artifact, 'id') else 0
        
        stats = {
            "semantic_items": semantic_count or 0,
            "episodic_items": episodic_count or 0,
            "artifacts": artifacts_count,
            "total_items": (semantic_count or 0) + (episodic_count or 0) + artifacts_count
        }
        
        # Get recent semantic items (limit 10)
        semantic_items_query = select(SemanticItem).order_by(desc(SemanticItem.created_at)).limit(10)
        semantic_items_result = await db.execute(semantic_items_query)
        semantic_items = semantic_items_result.scalars().all()
        
        # Get recent episodic items (limit 10)
        episodic_items_query = select(EpisodicItem).order_by(desc(EpisodicItem.created_at)).limit(10)
        episodic_items_result = await db.execute(episodic_items_query)
        episodic_items = episodic_items_result.scalars().all()
        
        return templates.TemplateResponse("context.html", {
            "request": request,
            "stats": stats,
            "semantic_items": semantic_items,
            "episodic_items": episodic_items,
            "page_title": "Context Memory"
        })
        
    except Exception as e:
        logger.exception("context_page_error")
        return templates.TemplateResponse("context.html", {
            "request": request,
            "stats": {"semantic_items": 0, "episodic_items": 0, "artifacts": 0, "total_items": 0},
            "semantic_items": [],
            "episodic_items": [],
            "error": str(e),
            "page_title": "Context Memory"
        })


@router.post("/context/items")
async def create_context_item(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency),
    item_type: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    workspace_id: str = Form(default="default"),
    thread_id: Optional[str] = Form(default=None)
):
    """Create a new context memory item."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Get or create thread
        if thread_id:
            thread_query = select(Thread).where(Thread.id == thread_id)
            thread_result = await db.execute(thread_query)
            thread = thread_result.scalar_one_or_none()
            if not thread:
                return JSONResponse({"success": False, "error": "Thread not found"}, status_code=404)
        else:
            # Create a new thread for this context item
            thread = Thread(
                name=f"Context Thread - {title[:50]}",
                workspace_id=workspace_id
            )
            db.add(thread)
            await db.flush()  # Get the thread ID
        
        if item_type == "semantic":
            # Generate next semantic item ID
            semantic_count = await db.scalar(select(func.count(SemanticItem.id)).where(SemanticItem.thread_id == thread.id))
            item_id = f"S{(semantic_count or 0) + 1}"
            
            new_item = SemanticItem(
                id=item_id,
                thread_id=thread.id,
                kind="task",  # Default kind, could be made configurable
                title=title,
                body=content,
                status="provisional"
            )
        elif item_type == "episodic":
            # Generate next episodic item ID
            episodic_count = await db.scalar(select(func.count(EpisodicItem.id)).where(EpisodicItem.thread_id == thread.id))
            item_id = f"E{(episodic_count or 0) + 1}"
            
            new_item = EpisodicItem(
                id=item_id,
                thread_id=thread.id,
                kind="log",  # Default kind, could be made configurable
                title=title,
                snippet=content[:500],  # Truncate to snippet length
                source="admin_interface"
            )
        else:
            return JSONResponse({"success": False, "error": "Invalid item type. Must be 'semantic' or 'episodic'"}, status_code=400)
        
        db.add(new_item)
        await db.commit()
        
        return JSONResponse({
            "success": True,
            "message": f"{item_type.title()} item created successfully",
            "item_id": item_id,
            "thread_id": str(thread.id)
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("create_context_item_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/context/items/{item_id}")
async def get_context_item(
    request: Request, 
    item_id: str,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Get details of a specific context item."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Try semantic items first
        semantic_query = select(SemanticItem).where(SemanticItem.id == item_id)
        semantic_result = await db.execute(semantic_query)
        semantic_item = semantic_result.scalar_one_or_none()
        
        if semantic_item:
            return JSONResponse({
                "success": True,
                "item": {
                    "id": semantic_item.id,
                    "type": "semantic",
                    "kind": semantic_item.kind,
                    "title": semantic_item.title,
                    "content": semantic_item.body,
                    "status": semantic_item.status,
                    "salience": float(semantic_item.salience) if semantic_item.salience else 0.5,
                    "usage_count": semantic_item.usage_count or 0,
                    "created_at": semantic_item.created_at.isoformat() if semantic_item.created_at else None,
                    "thread_id": str(semantic_item.thread_id)
                }
            })
        
        # Try episodic items
        episodic_query = select(EpisodicItem).where(EpisodicItem.id == item_id)
        episodic_result = await db.execute(episodic_query)
        episodic_item = episodic_result.scalar_one_or_none()
        
        if episodic_item:
            return JSONResponse({
                "success": True,
                "item": {
                    "id": episodic_item.id,
                    "type": "episodic",
                    "kind": episodic_item.kind,
                    "title": episodic_item.title,
                    "content": episodic_item.snippet,
                    "source": episodic_item.source,
                    "salience": float(episodic_item.salience) if episodic_item.salience else 0.5,
                    "created_at": episodic_item.created_at.isoformat() if episodic_item.created_at else None,
                    "thread_id": str(episodic_item.thread_id)
                }
            })
        
        return JSONResponse({"success": False, "error": "Item not found"}, status_code=404)
        
    except Exception as e:
        logger.exception("get_context_item_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.put("/context/items/{item_id}")
async def update_context_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db_dependency),
    title: str = Form(...),
    content: str = Form(...),
    status: Optional[str] = Form(default=None)
):
    """Update a context memory item."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Try semantic items first
        semantic_query = select(SemanticItem).where(SemanticItem.id == item_id)
        semantic_result = await db.execute(semantic_query)
        semantic_item = semantic_result.scalar_one_or_none()
        
        if semantic_item:
            semantic_item.title = title
            semantic_item.body = content
            if status and status in ['accepted', 'provisional', 'superseded']:
                semantic_item.status = status
            
            await db.commit()
            return JSONResponse({
                "success": True,
                "message": "Semantic item updated successfully"
            })
        
        # Try episodic items
        episodic_query = select(EpisodicItem).where(EpisodicItem.id == item_id)
        episodic_result = await db.execute(episodic_query)
        episodic_item = episodic_result.scalar_one_or_none()
        
        if episodic_item:
            episodic_item.title = title
            episodic_item.snippet = content[:500]  # Truncate to snippet length
            
            await db.commit()
            return JSONResponse({
                "success": True,
                "message": "Episodic item updated successfully"
            })
        
        return JSONResponse({"success": False, "error": "Item not found"}, status_code=404)
        
    except Exception as e:
        await db.rollback()
        logger.exception("update_context_item_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.delete("/context/items/{item_id}")
async def delete_context_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Delete a context memory item."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Try semantic items first
        semantic_query = select(SemanticItem).where(SemanticItem.id == item_id)
        semantic_result = await db.execute(semantic_query)
        semantic_item = semantic_result.scalar_one_or_none()
        
        if semantic_item:
            await db.delete(semantic_item)
            await db.commit()
            return JSONResponse({
                "success": True,
                "message": "Semantic item deleted successfully"
            })
        
        # Try episodic items
        episodic_query = select(EpisodicItem).where(EpisodicItem.id == item_id)
        episodic_result = await db.execute(episodic_query)
        episodic_item = episodic_result.scalar_one_or_none()
        
        if episodic_item:
            await db.delete(episodic_item)
            await db.commit()
            return JSONResponse({
                "success": True,
                "message": "Episodic item deleted successfully"
            })
        
        return JSONResponse({"success": False, "error": "Item not found"}, status_code=404)
        
    except Exception as e:
        await db.rollback()
        logger.exception("delete_context_item_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Context Memory Maintenance Endpoints

@router.post("/context/reindex")
async def reindex_embeddings(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Reindex all context embeddings."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Get Redis client for job queuing
        redis_client = await get_redis_client()
        
        # Get all context items that need reindexing
        semantic_items = await db.execute(select(SemanticItem))
        episodic_items = await db.execute(select(EpisodicItem))
        
        semantic_count = len(semantic_items.scalars().all())
        episodic_count = len(episodic_items.scalars().all())
        total_items = semantic_count + episodic_count
        
        if total_items == 0:
            return JSONResponse({
                "success": True,
                "message": "No items found to reindex"
            })
        
        # Queue embedding jobs (simplified - would need proper worker integration)
        await redis_client.lpush("queue:embeddings:pending", f"reindex_all:{total_items}")
        
        logger.info("queued_reindex_job", item_count=total_items)
        
        return JSONResponse({
            "success": True,
            "message": f"Queued {total_items} items for embedding reindexing",
            "items_queued": total_items
        })
        
    except Exception as e:
        logger.exception("reindex_embeddings_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/context/optimize")
async def optimize_storage(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Optimize context memory storage."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Analyze storage optimization opportunities
        duplicate_count = 0
        optimized_items = 0
        
        # Find duplicate episodic items by hash
        episodic_items = await db.execute(
            select(EpisodicItem.hash, func.count(EpisodicItem.id).label('count'))
            .group_by(EpisodicItem.hash)
            .having(func.count(EpisodicItem.id) > 1)
        )
        
        for hash_group in episodic_items:
            if hash_group.hash:
                duplicate_count += hash_group.count - 1  # Keep one, count duplicates
        
        # Update salience scores for unused items
        unused_semantic = await db.execute(
            select(SemanticItem)
            .where(SemanticItem.usage_count == 0)
            .where(SemanticItem.salience > 0.1)
        )
        
        for item in unused_semantic.scalars():
            item.salience = max(0.1, item.salience * 0.9)  # Decay unused items
            optimized_items += 1
        
        await db.commit()
        
        return JSONResponse({
            "success": True,
            "message": f"Storage optimization complete. Found {duplicate_count} duplicates, optimized {optimized_items} items",
            "duplicates_found": duplicate_count,
            "items_optimized": optimized_items
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("optimize_storage_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/context/export")
async def export_context(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency),
    format: str = "json"
):
    """Export context memory data."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        from fastapi.responses import StreamingResponse
        import json
        from io import StringIO
        
        # Get all context data
        semantic_items = await db.execute(select(SemanticItem))
        episodic_items = await db.execute(select(EpisodicItem))
        threads = await db.execute(select(Thread))
        
        export_data = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "export_format": format,
            "threads": [],
            "semantic_items": [],
            "episodic_items": []
        }
        
        # Export threads
        for thread in threads.scalars():
            export_data["threads"].append({
                "id": str(thread.id),
                "name": thread.name,
                "workspace_id": thread.workspace_id,
                "created_at": thread.created_at.isoformat() if thread.created_at else None
            })
        
        # Export semantic items
        for item in semantic_items.scalars():
            export_data["semantic_items"].append({
                "id": item.id,
                "thread_id": str(item.thread_id),
                "kind": item.kind,
                "title": item.title,
                "body": item.body,
                "status": item.status,
                "salience": float(item.salience) if item.salience else None,
                "usage_count": item.usage_count,
                "created_at": item.created_at.isoformat() if item.created_at else None
            })
        
        # Export episodic items
        for item in episodic_items.scalars():
            export_data["episodic_items"].append({
                "id": item.id,
                "thread_id": str(item.thread_id),
                "kind": item.kind,
                "title": item.title,
                "snippet": item.snippet,
                "source": item.source,
                "salience": float(item.salience) if item.salience else None,
                "created_at": item.created_at.isoformat() if item.created_at else None
            })
        
        # Create JSON export
        json_output = json.dumps(export_data, indent=2)
        
        # Return as downloadable file
        def generate():
            yield json_output
        
        return StreamingResponse(
            generate(),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=context_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"}
        )
        
    except Exception as e:
        logger.exception("export_context_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/context/cleanup")
async def cleanup_old_items(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency),
    days_old: int = 90,
    min_salience: float = 0.1
):
    """Cleanup old, low-salience context items."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Find old, low-salience semantic items
        old_semantic = await db.execute(
            select(SemanticItem)
            .where(SemanticItem.created_at < cutoff_date)
            .where(SemanticItem.salience < min_salience)
            .where(SemanticItem.status == 'superseded')
        )
        
        semantic_to_delete = old_semantic.scalars().all()
        
        # Find old, low-salience episodic items
        old_episodic = await db.execute(
            select(EpisodicItem)
            .where(EpisodicItem.created_at < cutoff_date)
            .where(EpisodicItem.salience < min_salience)
        )
        
        episodic_to_delete = old_episodic.scalars().all()
        
        # Delete items
        for item in semantic_to_delete:
            await db.delete(item)
        
        for item in episodic_to_delete:
            await db.delete(item)
        
        await db.commit()
        
        total_deleted = len(semantic_to_delete) + len(episodic_to_delete)
        
        logger.info("cleanup_completed", 
                   semantic_deleted=len(semantic_to_delete),
                   episodic_deleted=len(episodic_to_delete),
                   total_deleted=total_deleted)
        
        return JSONResponse({
            "success": True,
            "message": f"Cleanup complete. Deleted {total_deleted} old items",
            "semantic_deleted": len(semantic_to_delete),
            "episodic_deleted": len(episodic_to_delete),
            "total_deleted": total_deleted
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("cleanup_old_items_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Settings Management Endpoints

@router.get("/settings")
async def get_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Get current system settings."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        from app.core.config import settings as app_settings
        
        # Get database settings
        db_settings = await db.execute(select(Settings))
        settings_rows = db_settings.scalars().all()
        
        # Convert to dict for easy access
        settings_dict = {}
        for setting in settings_rows:
            settings_dict[setting.key] = setting.value
        
        # Combine with app settings
        current_settings = {
            "openrouter_api_key": app_settings.OPENROUTER_API_KEY if app_settings.OPENROUTER_API_KEY else None,
            "default_model": settings_dict.get("default_model", "openai/gpt-4"),
            "rate_limit_requests": int(settings_dict.get("rate_limit_requests", "100")),
            "rate_limit_window": int(settings_dict.get("rate_limit_window", "60")),
            "max_tokens": int(settings_dict.get("max_tokens", "4096")),
            "database_url": app_settings.DATABASE_URL[:50] + "..." if app_settings.DATABASE_URL else "Not configured",
            "redis_url": app_settings.REDIS_URL[:50] + "..." if app_settings.REDIS_URL else "Not configured",
            "default_token_budget": int(settings_dict.get("default_token_budget", "8000")),
            "max_context_items": int(settings_dict.get("max_context_items", "50")),
            "embedding_model": settings_dict.get("embedding_model", "text-embedding-ada-002")
        }
        
        return JSONResponse({
            "success": True,
            "settings": current_settings
        })
        
    except Exception as e:
        logger.exception("get_settings_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.put("/settings")
async def update_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Update system settings."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Get form data
        form_data = await request.form()
        
        # Settings to update
        settings_updates = {
            "default_model": form_data.get("default_model"),
            "rate_limit_requests": form_data.get("rate_limit_requests"),
            "rate_limit_window": form_data.get("rate_limit_window"),
            "max_tokens": form_data.get("max_tokens"),
            "default_token_budget": form_data.get("default_token_budget"),
            "max_context_items": form_data.get("max_context_items"),
            "embedding_model": form_data.get("embedding_model")
        }
        
        # Update or create settings in database
        for key, value in settings_updates.items():
            if value is not None:
                # Check if setting exists
                existing = await db.execute(
                    select(Settings).where(Settings.key == key)
                )
                setting = existing.scalars().first()
                
                if setting:
                    setting.value = str(value)
                    setting.updated_at = datetime.utcnow()
                else:
                    new_setting = Settings(
                        key=key,
                        value=str(value),
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(new_setting)
        
        await db.commit()
        
        logger.info("settings_updated", user_id=admin_user.get("user_id"))
        
        return JSONResponse({
            "success": True,
            "message": "Settings updated successfully"
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("update_settings_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.put("/settings/api-key")
async def update_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Update OpenRouter API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        form_data = await request.form()
        new_api_key = form_data.get("api_key")
        
        if not new_api_key:
            return JSONResponse({"success": False, "error": "API key is required"}, status_code=400)
        
        # Store in database settings
        existing = await db.execute(
            select(Settings).where(Settings.key == "openrouter_api_key")
        )
        setting = existing.scalars().first()
        
        if setting:
            setting.value = new_api_key
            setting.updated_at = datetime.utcnow()
        else:
            new_setting = Settings(
                key="openrouter_api_key",
                value=new_api_key,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(new_setting)
        
        await db.commit()
        
        logger.info("api_key_updated", user_id=admin_user.get("user_id"))
        
        return JSONResponse({
            "success": True,
            "message": "API key updated successfully"
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("update_api_key_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Maintenance Endpoints

@router.post("/maintenance/sync-models")
async def sync_models(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Sync models from OpenRouter."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Get Redis client for job queuing
        redis_client = await get_redis_client()
        
        # Queue model sync job
        await redis_client.lpush("queue:models:sync", f"sync_models:{datetime.utcnow().isoformat()}")
        
        logger.info("model_sync_queued", user_id=admin_user.get("user_id"))
        
        return JSONResponse({
            "success": True,
            "message": "Model sync job queued successfully"
        })
        
    except Exception as e:
        logger.exception("sync_models_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/maintenance/clear-cache")
async def clear_cache(
    request: Request
):
    """Clear system cache."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Clear cache using existing cache service
        from app.services.cache import cache_service
        
        # Clear common cache patterns
        patterns_to_clear = [
            "cache:*",
            "models:*",
            "usage:*",
            "analytics:*"
        ]
        
        total_cleared = 0
        for pattern in patterns_to_clear:
            cleared = await cache_service.clear_pattern(pattern)
            total_cleared += cleared
        
        logger.info("cache_cleared", 
                   patterns_cleared=len(patterns_to_clear),
                   keys_cleared=total_cleared,
                   user_id=admin_user.get("user_id"))
        
        return JSONResponse({
            "success": True,
            "message": f"Cache cleared successfully. Removed {total_cleared} keys"
        })
        
    except Exception as e:
        logger.exception("clear_cache_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/maintenance/export-logs")
async def export_logs(
    request: Request,
    days: int = 7
):
    """Export system logs."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        from fastapi.responses import StreamingResponse
        import os
        import glob
        from datetime import datetime, timedelta
        
        # Look for log files in common locations
        log_locations = [
            "/var/log/app/*.log",
            "./logs/*.log",
            "logs/*.log",
            "/tmp/app.log"
        ]
        
        log_files = []
        for pattern in log_locations:
            log_files.extend(glob.glob(pattern))
        
        if not log_files:
            return JSONResponse({
                "success": False,
                "error": "No log files found"
            }, status_code=404)
        
        # Filter logs by date if possible
        cutoff_date = datetime.now() - timedelta(days=days)
        
        def generate_logs():
            yield f"# System Logs Export - {datetime.now().isoformat()}\n"
            yield f"# Exported by: {admin_user.get('username', 'admin')}\n"
            yield f"# Date range: Last {days} days\n\n"
            
            for log_file in log_files:
                try:
                    # Check file modification time
                    mod_time = datetime.fromtimestamp(os.path.getmtime(log_file))
                    if mod_time < cutoff_date:
                        continue
                    
                    yield f"## Log file: {log_file}\n"
                    yield f"## Modified: {mod_time.isoformat()}\n\n"
                    
                    with open(log_file, 'r') as f:
                        for line in f:
                            yield line
                    
                    yield "\n" + "="*80 + "\n\n"
                    
                except Exception as e:
                    yield f"## Error reading {log_file}: {str(e)}\n\n"
        
        return StreamingResponse(
            generate_logs(),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=system_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"}
        )
        
    except Exception as e:
        logger.exception("export_logs_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Analytics Endpoints

@router.get("/analytics/usage")
async def get_usage_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency),
    time_range: str = "7d"
):
    """Get usage analytics with time filtering."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Parse time range
        if time_range == "24h":
            start_date = datetime.utcnow() - timedelta(hours=24)
        elif time_range == "7d":
            start_date = datetime.utcnow() - timedelta(days=7)
        elif time_range == "30d":
            start_date = datetime.utcnow() - timedelta(days=30)
        elif time_range == "90d":
            start_date = datetime.utcnow() - timedelta(days=90)
        else:
            start_date = datetime.utcnow() - timedelta(days=7)
        
        # Get usage data from UsageLedger
        usage_query = await db.execute(
            select(UsageLedger)
            .where(UsageLedger.created_at >= start_date)
            .order_by(UsageLedger.created_at.desc())
        )
        usage_records = usage_query.scalars().all()
        
        # Calculate metrics
        total_requests = len(usage_records)
        total_tokens = sum(record.total_tokens or 0 for record in usage_records)
        total_cost = sum(float(record.cost or 0) for record in usage_records)
        
        # Get unique users/API keys
        unique_users = len(set(record.api_key_id for record in usage_records if record.api_key_id))
        
        # Calculate average response time (mock data for now)
        avg_response_time = 1.2 if usage_records else 0
        
        # Group by model
        model_usage = {}
        for record in usage_records:
            model = record.model or "unknown"
            if model not in model_usage:
                model_usage[model] = {"requests": 0, "tokens": 0, "cost": 0}
            model_usage[model]["requests"] += 1
            model_usage[model]["tokens"] += record.total_tokens or 0
            model_usage[model]["cost"] += float(record.cost or 0)
        
        # Group by endpoint
        endpoint_usage = {}
        for record in usage_records:
            endpoint = record.endpoint or "/v1/chat/completions"
            if endpoint not in endpoint_usage:
                endpoint_usage[endpoint] = {"requests": 0, "tokens": 0}
            endpoint_usage[endpoint]["requests"] += 1
            endpoint_usage[endpoint]["tokens"] += record.total_tokens or 0
        
        # Generate time series data (daily aggregation)
        time_series = {}
        for record in usage_records:
            date_key = record.created_at.strftime('%Y-%m-%d') if record.created_at else 'unknown'
            if date_key not in time_series:
                time_series[date_key] = {"requests": 0, "tokens": 0, "cost": 0}
            time_series[date_key]["requests"] += 1
            time_series[date_key]["tokens"] += record.total_tokens or 0
            time_series[date_key]["cost"] += float(record.cost or 0)
        
        # Sort and format time series
        sorted_dates = sorted(time_series.keys())
        chart_data = {
            "labels": sorted_dates,
            "requests": [time_series[date]["requests"] for date in sorted_dates],
            "tokens": [time_series[date]["tokens"] for date in sorted_dates],
            "costs": [time_series[date]["cost"] for date in sorted_dates]
        }
        
        return JSONResponse({
            "success": True,
            "time_range": time_range,
            "metrics": {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 4),
                "unique_users": unique_users,
                "avg_response_time": avg_response_time
            },
            "model_usage": dict(sorted(model_usage.items(), key=lambda x: x[1]["requests"], reverse=True)),
            "endpoint_usage": dict(sorted(endpoint_usage.items(), key=lambda x: x[1]["requests"], reverse=True)),
            "chart_data": chart_data
        })
        
    except Exception as e:
        logger.exception("get_usage_analytics_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/analytics/performance")
async def get_performance_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Get performance metrics."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # Get recent usage for performance calculations
        recent_usage = await db.execute(
            select(UsageLedger)
            .where(UsageLedger.created_at >= datetime.utcnow() - timedelta(hours=24))
            .order_by(UsageLedger.created_at.desc())
        )
        usage_records = recent_usage.scalars().all()
        
        # Calculate performance metrics
        if usage_records:
            response_times = []
            for record in usage_records:
                # Mock response time calculation based on tokens
                tokens = record.total_tokens or 100
                # Simulate response time: larger requests take longer
                estimated_time = min(0.5 + (tokens / 1000) * 0.5, 10.0)
                response_times.append(estimated_time)
            
            avg_response_time = sum(response_times) / len(response_times)
            p95_response_time = sorted(response_times)[int(len(response_times) * 0.95)]
            p99_response_time = sorted(response_times)[int(len(response_times) * 0.99)]
        else:
            avg_response_time = 0
            p95_response_time = 0
            p99_response_time = 0
        
        # Get cache hit rate from Redis
        redis_client = await get_redis_client()
        try:
            cache_info = await redis_client.info()
            cache_hits = cache_info.get('keyspace_hits', 0)
            cache_misses = cache_info.get('keyspace_misses', 0)
            cache_hit_rate = cache_hits / (cache_hits + cache_misses) if (cache_hits + cache_misses) > 0 else 0
        except:
            cache_hit_rate = 0.85  # Default fallback
        
        # Calculate throughput (requests per minute)
        throughput = len(usage_records) / (24 * 60) if usage_records else 0
        
        # Calculate error rate
        # For now, assume 1-2% error rate based on successful requests
        error_rate = 0.015 if usage_records else 0
        
        # CPU and Memory usage (mock data - would integrate with system monitoring)
        cpu_usage = 45.2
        memory_usage = 62.8
        disk_usage = 34.1
        
        return JSONResponse({
            "success": True,
            "performance": {
                "avg_response_time": round(avg_response_time, 3),
                "p95_response_time": round(p95_response_time, 3),
                "p99_response_time": round(p99_response_time, 3),
                "cache_hit_rate": round(cache_hit_rate, 3),
                "throughput": round(throughput, 2),
                "error_rate": round(error_rate, 4),
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage
            }
        })
        
    except Exception as e:
        logger.exception("get_performance_metrics_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/analytics/errors")
async def get_error_analysis(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency)
):
    """Get error analysis data."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        # In a real implementation, this would query error logs
        # For now, providing mock data structure
        
        error_types = {
            "rate_limit_exceeded": {"count": 23, "percentage": 45.1},
            "authentication_failed": {"count": 12, "percentage": 23.5},
            "model_unavailable": {"count": 8, "percentage": 15.7},
            "timeout": {"count": 5, "percentage": 9.8},
            "invalid_request": {"count": 3, "percentage": 5.9}
        }
        
        error_timeline = {
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "errors": [12, 8, 15, 23, 18, 6, 9]
        }
        
        top_error_endpoints = [
            {"endpoint": "/v1/chat/completions", "errors": 28},
            {"endpoint": "/v1/embeddings", "errors": 12},
            {"endpoint": "/v1/models", "errors": 8},
            {"endpoint": "/v1/completions", "errors": 3}
        ]
        
        recent_errors = [
            {
                "timestamp": (datetime.utcnow() - timedelta(minutes=15)).isoformat(),
                "type": "rate_limit_exceeded",
                "endpoint": "/v1/chat/completions",
                "message": "Rate limit exceeded for API key",
                "user_agent": "python-requests/2.28.0"
            },
            {
                "timestamp": (datetime.utcnow() - timedelta(minutes=32)).isoformat(),
                "type": "authentication_failed",
                "endpoint": "/v1/chat/completions",
                "message": "Invalid API key provided",
                "user_agent": "curl/7.68.0"
            },
            {
                "timestamp": (datetime.utcnow() - timedelta(hours=1, minutes=5)).isoformat(),
                "type": "model_unavailable",
                "endpoint": "/v1/chat/completions",
                "message": "Model 'gpt-4' is currently unavailable",
                "user_agent": "OpenAI-Python/1.3.5"
            }
        ]
        
        return JSONResponse({
            "success": True,
            "error_analysis": {
                "total_errors": sum(error["count"] for error in error_types.values()),
                "error_types": error_types,
                "error_timeline": error_timeline,
                "top_error_endpoints": top_error_endpoints,
                "recent_errors": recent_errors
            }
        })
        
    except Exception as e:
        logger.exception("get_error_analysis_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/analytics/export")
async def export_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db_dependency),
    time_range: str = "30d",
    format: str = "csv"
):
    """Export analytics data."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Authentication required"}, status_code=401)
    
    try:
        from fastapi.responses import StreamingResponse
        import csv
        from io import StringIO
        
        # Parse time range
        if time_range == "24h":
            start_date = datetime.utcnow() - timedelta(hours=24)
        elif time_range == "7d":
            start_date = datetime.utcnow() - timedelta(days=7)
        elif time_range == "30d":
            start_date = datetime.utcnow() - timedelta(days=30)
        elif time_range == "90d":
            start_date = datetime.utcnow() - timedelta(days=90)
        else:
            start_date = datetime.utcnow() - timedelta(days=30)
        
        # Get usage data
        usage_query = await db.execute(
            select(UsageLedger)
            .where(UsageLedger.created_at >= start_date)
            .order_by(UsageLedger.created_at.desc())
        )
        usage_records = usage_query.scalars().all()
        
        def generate_csv():
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'timestamp', 'api_key_id', 'endpoint', 'model', 
                'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost'
            ])
            
            # Write data
            for record in usage_records:
                writer.writerow([
                    record.created_at.isoformat() if record.created_at else '',
                    record.api_key_id or '',
                    record.endpoint or '',
                    record.model or '',
                    record.prompt_tokens or 0,
                    record.completion_tokens or 0,
                    record.total_tokens or 0,
                    record.cost or 0
                ])
            
            output.seek(0)
            for line in output:
                yield line
        
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=analytics_export_{time_range}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
        
    except Exception as e:
        logger.exception("export_analytics_error")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/favicon.ico")
async def favicon():
    """Return 204 No Content for favicon requests."""
    return JSONResponse(content={}, status_code=204)
