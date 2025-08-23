from typing import Optional
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import structlog
import secrets
import hashlib

from app.db.session import get_db_dependency
from app.db.models import APIKey, ModelCatalog, SemanticItem, EpisodicItem, Artifact, UsageStats, User
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
                secure=False,  # Set to True in production with HTTPS
                samesite="lax"
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
        return JSONResponse({
            "success": True,
            "models_count": len(models_data),
            "message": f"Fetched {len(models_data)} models from OpenRouter"
        })
    except OpenRouterError as e:
        logger.exception("fetch_models_error")
        return JSONResponse({"error": f"OpenRouter API error: {str(e)}"}, status_code=500)
    except Exception as e:
        logger.exception("fetch_models_error")
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

@router.get("/favicon.ico")
async def favicon():
    """Return 204 No Content for favicon requests."""
    return JSONResponse(content={}, status_code=204)
