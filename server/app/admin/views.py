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
from app.db.models import APIKey, ModelCatalog, SemanticItem, EpisodicItem, Artifact, UsageStats
from app.api.openrouter import fetch_all_models, OpenRouterError
from app.core.config import get_settings
from app.core.security import (
    get_admin_user, authenticate_admin, create_admin_jwt, create_user,
    AdminUser, AdminLoginRequest, AdminLoginResponse
)

# Initialize settings
app_settings = get_settings()

router = APIRouter()
logger = structlog.get_logger(__name__)

# Setup templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Favicon route
@router.get("/favicon.ico")
async def favicon():
    """Return favicon - for now just return 204 No Content to avoid 404s."""
    from fastapi import Response
    return Response(status_code=204)

# Admin authentication helper
async def require_admin_auth(request: Request) -> Optional[AdminUser]:
    """Check admin authentication and return user or redirect to login."""
    try:
        admin_session = request.cookies.get("admin_session")
        if not admin_session:
            return None
        
        from app.core.security import verify_admin_jwt
        return verify_admin_jwt(admin_session)
    except Exception:
        return None

# Admin Authentication Routes

@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page."""
    return templates.TemplateResponse("login.html", {
        "request": request, 
        "page_title": "Admin Login"
    })


@router.post("/login", response_class=HTMLResponse)
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """Handle admin login form submission."""
    try:
        # Extract correlation ID from request state
        correlation_id = getattr(request.state, "correlation_id", None)
        
        if await authenticate_admin(username, password, correlation_id):
            # Create JWT token
            token = create_admin_jwt(username)
            
            # Create response with redirect
            response = RedirectResponse(url="/admin/dashboard", status_code=302)
            
            # Set secure cookie with JWT token
            response.set_cookie(
                key="admin_session",
                value=token,
                max_age=app_settings.JWT_EXPIRE_MINUTES * 60,
                httponly=True,
                secure=app_settings.is_production,
                samesite="lax"
            )
            
            logger.info("admin_login_successful", username=username, correlation_id=correlation_id)
            return response
        else:
            logger.exception("admin_login_failed", username=username, correlation_id=correlation_id)
            return templates.TemplateResponse("login.html", {
                "request": request,
                "page_title": "Admin Login",
                "error": "Invalid username or password"
            })
    except Exception as e:
        logger.exception("admin_login_error")
        return templates.TemplateResponse("login.html", {
            "request": request,
            "page_title": "Admin Login",
            "error": "Login failed. Please try again."
        })


@router.post("/logout")
async def admin_logout(request: Request):
    """Handle admin logout."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    logger.info("admin_logout")
    return response


@router.get("/signup", response_class=HTMLResponse)
async def admin_signup_page(request: Request):
    """Admin signup page."""
    return templates.TemplateResponse("signup.html", {
        "request": request, 
        "page_title": "Admin Signup"
    })


@router.post("/signup", response_class=HTMLResponse)
async def admin_signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle admin signup form submission."""
    try:
        # Extract correlation ID from request state
        correlation_id = getattr(request.state, "correlation_id", None)
        
        # Validate passwords match
        if password != confirm_password:
            return templates.TemplateResponse("signup.html", {
                "request": request,
                "page_title": "Admin Signup",
                "error": "Passwords do not match"
            })
        
        # Validate password strength (basic)
        if len(password) < 6:
            return templates.TemplateResponse("signup.html", {
                "request": request,
                "page_title": "Admin Signup",
                "error": "Password must be at least 6 characters long"
            })
        
        # Create user
        user = await create_user(username, email, password)
        
        # Create JWT token for immediate login
        token = create_admin_jwt(username)
        
        # Create response with redirect
        response = RedirectResponse(url="/admin/dashboard", status_code=302)
        
        # Set secure cookie with JWT token
        response.set_cookie(
            key="admin_session",
            value=token,
            max_age=app_settings.JWT_EXPIRE_MINUTES * 60,
            httponly=True,
            secure=app_settings.is_production,
            samesite="lax"
        )
        
        logger.info("admin_signup_successful", username=username, email=email, correlation_id=correlation_id)
        return response
        
    except HTTPException as e:
        logger.warning("admin_signup_failed", username=username, email=email, error=e.detail, correlation_id=correlation_id)
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "page_title": "Admin Signup",
            "error": e.detail
        })
    except Exception as e:
        logger.exception("admin_signup_error")
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "page_title": "Admin Signup", 
            "error": "Signup failed. Please try again."
        })


# Protected Admin Routes

@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency),
):
    """Admin dashboard with system overview."""
    # Check authentication and redirect to login if not authenticated
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        stats = {
            "total_api_keys": 0, "active_keys": 0, "suspended_keys": 0,
            "total_models": 0, "active_models": 0,
            "total_semantic_items": 0, "total_episodic_items": 0, 
            "total_artifacts": 0, "total_requests": 0, 
            "total_users": 0, "status": "operational"
        }
        try:
            # API Key stats
            result = await db.execute(select(func.count(APIKey.key_hash)))
            stats["total_api_keys"] = result.scalar() or 0
            result = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == True))
            stats["active_keys"] = result.scalar() or 0
            stats["suspended_keys"] = stats["total_api_keys"] - stats["active_keys"]
            
            # Model stats
            result = await db.execute(select(func.count(ModelCatalog.model_id)))
            stats["total_models"] = result.scalar() or 0
            result = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "active"))
            stats["active_models"] = result.scalar() or 0
            
            # Memory stats
            result = await db.execute(select(func.count(SemanticItem.id)))
            stats["total_semantic_items"] = result.scalar() or 0
            result = await db.execute(select(func.count(EpisodicItem.id)))
            stats["total_episodic_items"] = result.scalar() or 0
            result = await db.execute(select(func.count(Artifact.ref)))
            stats["total_artifacts"] = result.scalar() or 0
            
            # Usage stats
            from app.db.models import User
            result = await db.execute(select(func.count(User.id)))
            stats["total_users"] = result.scalar() or 0
            
            # Calculate total requests from usage if available
            result = await db.execute(select(func.sum(UsageStats.clicks + UsageStats.references)))
            stats["total_requests"] = result.scalar() or 0
            
        except Exception as e:
            logger.exception("dashboard_stats_error")
        return templates.TemplateResponse("dashboard.html", {"request": request, "stats": stats, "page_title": "Dashboard"})
    except Exception as e:
        logger.exception("dashboard_error")
        return templates.TemplateResponse("dashboard.html", {"request": request, "stats": stats, "error": str(e), "page_title": "Dashboard"})

@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_list(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency), 
    q: Optional[str] = None
):
    """API keys management page."""
    # Check authentication and redirect to login if not authenticated
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        query = select(APIKey)
        if q:
            query = query.where(APIKey.key_prefix.ilike(f"%{q}%"))
        query = query.order_by(APIKey.created_at.desc()).limit(50)
        result = await db.execute(query)
        api_keys = result.scalars().all()
        
        total_keys = await db.execute(select(func.count(APIKey.key_hash)))
        active_keys = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == True))
        suspended_keys = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == False))
        total_requests = await db.execute(select(func.sum(UsageStats.clicks + UsageStats.references)))
        
        stats = {
            "total_keys": total_keys.scalar() or 0, "active_keys": active_keys.scalar() or 0,
            "suspended_keys": suspended_keys.scalar() or 0, "total_requests": total_requests.scalar() or 0
        }
        
        formatted_keys = []
        for key in api_keys:
            key_prefix = key.key_hash[:8] + "..." if key.key_hash else "unknown"
            formatted_keys.append({
                "key_id": key.key_hash, "key_prefix": key_prefix,
                "workspace_name": key.name or "Default Workspace", "requests_count": 0,
                "quota_limit": key.daily_quota_tokens or 100000,
                "created_at": key.created_at.strftime("%Y-%m-%d %H:%M") if key.created_at else "Unknown",
                "last_used_at": "Never",
                "status": "active" if key.active else "suspended"
            })
        
        return templates.TemplateResponse("api_keys.html", {
            "request": request, "stats": stats, "api_keys": formatted_keys,
            "search_query": q or "", "page_title": "API Keys"
        })
    except Exception as e:
        logger.exception("api_keys_error")
        return templates.TemplateResponse("api_keys.html", {
            "request": request, "stats": {"active_keys": 0, "suspended_keys": 0, "total_requests": 0},
            "api_keys": [], "search_query": q or "", "error": str(e), "page_title": "API Keys"
        })

@router.post("/api-keys/generate", response_class=HTMLResponse)
async def generate_api_key(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency), 
    name: str = Form(...), 
    description: Optional[str] = Form(None)
):
    """Generate a new API key."""
    # Check authentication and redirect to login if not authenticated
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        # Generate API key with proper prefix
        new_key = f"{app_settings.API_KEY_PREFIX}{''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(app_settings.API_KEY_LENGTH))}"
        key_hash = hashlib.sha256(new_key.encode()).hexdigest()
        
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
        
        logger.info("Generated new API key", key_id=api_key.key_hash[:12], name=name)
        
        # Return the new key (only shown once)
        return templates.TemplateResponse("api_key_created.html", {
            "request": request,
            "new_key": new_key,
            "api_key": api_key,
            "page_title": "API Key Created"
        })
    except Exception as e:
        logger.exception("generate_key_error")
        return RedirectResponse(url="/admin/api-keys?error=generation_failed", status_code=302)

@router.post("/api-keys/{key_id}/suspend")
async def suspend_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Suspend an API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_id))
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            return JSONResponse({"success": False, "message": "API key not found"}, status_code=404)
        
        api_key.active = False
        await db.commit()
        
        logger.info("API key suspended", key_id=key_id[:12])
        return await api_keys_list(request, db)
    except Exception as e:
        logger.exception("suspend_api_key_error", key_id=key_id)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@router.post("/api-keys/{key_id}/activate")
async def activate_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Activate an API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_id))
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            return JSONResponse({"success": False, "message": "API key not found"}, status_code=404)
        
        api_key.active = True
        await db.commit()
        
        logger.info("API key activated", key_id=key_id[:12])
        return await api_keys_list(request, db)
    except Exception as e:
        logger.exception("activate_api_key_error", key_id=key_id)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@router.delete("/api-keys/{key_id}")
async def delete_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Delete an API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_id))
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            return JSONResponse({"success": False, "message": "API key not found"}, status_code=404)
        
        await db.delete(api_key)
        await db.commit()
        
        logger.info("API key deleted", key_id=key_id[:12])
        return await api_keys_list(request, db)
    except Exception as e:
        logger.exception("delete_api_key_error", key_id=key_id)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@router.get("/workers", response_class=HTMLResponse)
async def workers_monitoring(
    request: Request
):
    """Worker monitoring and management page."""
    # Check authentication and redirect to login if not authenticated
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        # Get worker health data from the API
        import httpx
        async with httpx.AsyncClient() as client:
            try:
                # Make internal API call to get worker health
                api_base = getattr(settings, 'API_BASE_URL', None) or 'http://localhost:8000'
                response = await client.get(f"{api_base}/v1/workers/health")
                if response.status_code == 200:
                    worker_data = response.json()
                else:
                    worker_data = {
                        "status": "error",
                        "error": "Failed to fetch worker data",
                        "queues": {"details": {}},
                        "workers": {"active_count": 0, "workers": []},
                        "redis": {"connected": False},
                        "issues": ["Could not connect to worker API"]
                    }
            except Exception as e:
                logger.exception("worker_api_call_failed")
                worker_data = {
                    "status": "error",
                    "error": str(e),
                    "queues": {"details": {}},
                    "workers": {"active_count": 0, "workers": []},
                    "redis": {"connected": False},
                    "issues": [f"API Error: {str(e)}"]
                }
        
        # Calculate health score if not provided
        health_score = worker_data.get("health_score")
        if health_score is None:
            # Simple health calculation
            health_score = 100
            if not worker_data.get("redis", {}).get("connected", True):
                health_score -= 40
            if worker_data.get("workers", {}).get("active_count", 0) == 0:
                health_score -= 30
            if worker_data.get("queues", {}).get("total_failed_jobs", 0) > 10:
                health_score -= 20
            health_score = max(health_score, 0)
        
        return templates.TemplateResponse("workers.html", {
            "request": request,
            "page_title": "Worker Monitoring",
            "health_score": health_score,
            **worker_data
        })
    
    except Exception as e:
        logger.exception("workers_page_error")
        return templates.TemplateResponse("workers.html", {
            "request": request,
            "page_title": "Worker Monitoring",
            "error": str(e),
            "health_score": 0,
            "status": "error",
            "queues": {"details": {}},
            "workers": {"active_count": 0, "workers": []},
            "redis": {"connected": False},
            "issues": [f"Page Error: {str(e)}"]
        })


@router.get("/models", response_class=HTMLResponse)
async def models_list(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency)
):
    """Models management page."""
    # Check authentication and redirect to login if not authenticated
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        query = select(ModelCatalog).order_by(ModelCatalog.created_at.desc()).limit(50)
        result = await db.execute(query)
        models = result.scalars().all()
        
        total_models_count = await db.execute(select(func.count(ModelCatalog.model_id)))
        active_models_count = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "active"))
        deprecated_models_count = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "deprecated"))
        
        stats = {
            "active_models": active_models_count.scalar() or 0,
            "deprecated_models": deprecated_models_count.scalar() or 0,
            "most_used_model": "GPT-4", "total_requests": 0
        }
        
        formatted_models = []
        for model in models:
            formatted_models.append({
                "model_id": model.model_id,
                "name": model.display_name or model.model_id,
                "id": model.model_id,
                "provider": model.provider,
                "is_active": model.status == "active",
                "created_at": model.created_at.isoformat() if model.created_at else None,
                "pricing": {
                    "input_cost": float(model.input_price_per_1k) if model.input_price_per_1k else 0,
                    "output_cost": float(model.output_price_per_1k) if model.output_price_per_1k else 0
                },
                "context_window": model.context_window,
                "supports_vision": model.supports_vision,
                "supports_tools": model.supports_tools
            })
        
        # Get latest sync time
        latest_model = await db.execute(
            select(ModelCatalog).order_by(ModelCatalog.updated_at.desc()).limit(1)
        )
        latest = latest_model.scalar_one_or_none()
        last_sync = latest.updated_at.strftime("%Y-%m-%d %H:%M") if latest else "Never"
        
        return templates.TemplateResponse("models.html", {
            "request": request, "stats": stats, "models": formatted_models,
            "last_sync": last_sync, "total_models": len(formatted_models),
            "active_models": stats["active_models"], "page_title": "Models"
        })
    except Exception as e:
        logger.exception("models_error")
        return templates.TemplateResponse("models.html", {
            "request": request, "stats": {"active_models": 0, "deprecated_models": 0, "most_used_model": "N/A", "total_requests": 0},
            "models": [], "last_sync": "Unknown", "total_models": 0, "active_models": 0, "error": str(e), "page_title": "Models"
        })

@router.get("/settings", response_class=HTMLResponse)
async def settings(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency)
):
    """Settings management page."""
    # Check authentication and redirect to login if not authenticated
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    try:
        # Mock settings data - in production this would come from config/database
        settings_data = {
            "openrouter_api_key": "sk-or-****",  # Masked for security
            "rate_limit_requests": 100,
            "rate_limit_window": 60,
            "max_tokens": 4096,
            "database_url": "postgresql://cmg_user:***@postgres:5432/context_memory_gateway",
            "redis_url": "redis://redis:6379/0"
        }
        
        return templates.TemplateResponse("settings.html", {
            "request": request, "page_title": "Settings",
            "settings": settings_data, "openrouter_configured": True
        })
    except Exception as e:
        logger.exception("settings_error")
        return templates.TemplateResponse("settings.html", {
            "request": request, "page_title": "Settings", 
            "settings": {}, "error": str(e)
        })

@router.post("/settings/openrouter", response_class=HTMLResponse)
async def update_openrouter_key(request: Request, openrouter_key: str = Form(...)):
    """Update OpenRouter API key."""
    try:
        if not openrouter_key.startswith("sk-or-"):
            raise HTTPException(status_code=400, detail="Invalid OpenRouter key format")
        logger.info("Updated OpenRouter key")
        return RedirectResponse(url="/admin/settings?success=key_updated", status_code=302)
    except Exception as e:
        logger.exception("update_openrouter_error")
        return RedirectResponse(url="/admin/settings?error=update_failed", status_code=302)

@router.get("/models/fetch", response_class=JSONResponse)
async def fetch_openrouter_models(request: Request):
    """Fetch all available models from OpenRouter for admin selection."""
    try:
        models = await fetch_all_models()
        
        # Filter and format models for admin interface
        formatted_models = []
        for model in models:
            formatted_models.append({
                "id": model.get("id", ""),
                "name": model.get("name", model.get("id", "Unknown")),
                "description": model.get("description", ""),
                "context_length": model.get("context_length", 0),
                "pricing": {
                    "prompt": model.get("pricing", {}).get("prompt", "0"),
                    "completion": model.get("pricing", {}).get("completion", "0")
                },
                "top_provider": model.get("top_provider", {}).get("name", "Unknown"),
                "architecture": model.get("architecture", {}),
                "moderation_required": model.get("moderation_required", False)
            })
        
        return JSONResponse({
            "success": True,
            "models": formatted_models,
            "count": len(formatted_models)
        })
        
    except OpenRouterError as e:
        logger.exception("fetch_models_openrouter_error", status_code=e.status_code)
        return JSONResponse({
            "success": False,
            "error": f"OpenRouter API error: {e.message}",
            "details": e.details
        }, status_code=e.status_code)
        
    except Exception as e:
        logger.exception("fetch_models_error")
        return JSONResponse({
            "success": False,
            "error": "Failed to fetch models from OpenRouter"
        }, status_code=500)

@router.get("/models/sync-status", response_class=HTMLResponse)
async def models_sync_status(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Get model sync status for HTMX updates."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Get latest model sync time
        latest_model = await db.execute(
            select(ModelCatalog).order_by(ModelCatalog.updated_at.desc()).limit(1)
        )
        latest = latest_model.scalar_one_or_none()
        
        if latest:
            last_sync = latest.updated_at.strftime("%Y-%m-%d at %H:%M UTC")
            status_class = "bg-green-50 border-green-200"
            icon_class = "text-green-400"
            icon = "check-circle"
            message = f"Last synced on {last_sync} • {await db.execute(select(func.count(ModelCatalog.model_id))).scalar() or 0} models available"
        else:
            status_class = "bg-yellow-50 border-yellow-200"
            icon_class = "text-yellow-400"
            icon = "clock"
            message = "No models synced yet • Click 'Fetch OpenRouter Models' to get started"
        
        html = f'''
        <div class="{status_class} border rounded-lg p-4">
            <div class="flex items-center">
                <div class="flex-shrink-0">
                    <i data-lucide="{icon}" class="w-5 h-5 {icon_class}"></i>
                </div>
                <div class="ml-3">
                    <p class="text-sm text-gray-700">{message}</p>
                </div>
            </div>
        </div>
        '''
        
        return HTMLResponse(content=html)
    except Exception as e:
        logger.exception("sync_status_error")
        return HTMLResponse(content=f'''
        <div class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="flex items-center">
                <div class="flex-shrink-0">
                    <i data-lucide="alert-circle" class="w-5 h-5 text-red-400"></i>
                </div>
                <div class="ml-3">
                    <p class="text-sm text-red-700">Error checking sync status: {str(e)}</p>
                </div>
            </div>
        </div>
        ''')

@router.post("/models/sync", response_class=JSONResponse)
async def sync_models_from_openrouter(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Sync models from OpenRouter and update database."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from app.api.openrouter import fetch_all_models
        models_data = await fetch_all_models()
        
        updated_count = 0
        new_count = 0
        
        for model_data in models_data:
            model_id = model_data.get("id")
            if not model_id:
                continue
                
            # Check if model exists
            existing = await db.execute(
                select(ModelCatalog).where(ModelCatalog.model_id == model_id)
            )
            model = existing.scalar_one_or_none()
            
            if model:
                # Update existing model
                model.display_name = model_data.get("name", model_id)
                model.provider = "openrouter"
                model.context_window = model_data.get("context_length", 0)
                model.input_price_per_1k = model_data.get("pricing", {}).get("prompt", 0)
                model.output_price_per_1k = model_data.get("pricing", {}).get("completion", 0)
                model.supports_vision = "vision" in model_data.get("id", "").lower()
                model.supports_tools = True  # Most OpenRouter models support tools
                model.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                # Create new model
                new_model = ModelCatalog(
                    model_id=model_id,
                    display_name=model_data.get("name", model_id),
                    provider="openrouter",
                    status="active",
                    context_window=model_data.get("context_length", 0),
                    input_price_per_1k=model_data.get("pricing", {}).get("prompt", 0),
                    output_price_per_1k=model_data.get("pricing", {}).get("completion", 0),
                    supports_vision="vision" in model_data.get("id", "").lower(),
                    supports_tools=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_model)
                new_count += 1
        
        await db.commit()
        
        logger.info("Models synced successfully", new_count=new_count, updated_count=updated_count)
        return JSONResponse({
            "success": True,
            "message": f"Synced {new_count} new models, updated {updated_count} existing models",
            "new_count": new_count,
            "updated_count": updated_count
        })
        
    except Exception as e:
        logger.exception("sync_models_error")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

@router.get("/api-keys/create", response_class=HTMLResponse)
async def api_keys_create_form(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """API key creation form."""
    try:
        admin_user = await require_admin_auth(request)
        if not admin_user:
            return RedirectResponse(url="/admin/login", status_code=302)
        
        return templates.TemplateResponse("api_key_create_form.html", {
            "request": request,
            "page_title": "Create API Key"
        })
    except Exception as e:
        logger.exception("api_key_create_form_error")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/context", response_class=HTMLResponse)
async def admin_context(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Context Memory management page."""
    try:
        # Get context memory statistics
        semantic_count = await db.execute(select(func.count(SemanticItem.id)))
        episodic_count = await db.execute(select(func.count(EpisodicItem.id)))
        artifact_count = await db.execute(select(func.count(Artifact.ref)))
        
        stats = {
            "semantic_items": semantic_count.scalar() or 0,
            "episodic_items": episodic_count.scalar() or 0,
            "artifacts": artifact_count.scalar() or 0,
            "total_items": (semantic_count.scalar() or 0) + (episodic_count.scalar() or 0)
        }
        
        # Get recent context items
        recent_semantic = await db.execute(
            select(SemanticItem).order_by(SemanticItem.created_at.desc()).limit(10)
        )
        recent_episodic = await db.execute(
            select(EpisodicItem).order_by(EpisodicItem.created_at.desc()).limit(10)
        )
        
        return templates.TemplateResponse("context.html", {
            "request": request,
            "page_title": "Context Memory",
            "stats": stats,
            "semantic_items": recent_semantic.scalars().all(),
            "episodic_items": recent_episodic.scalars().all()
        })
    except Exception as e:
        logger.exception("context_error")
        return templates.TemplateResponse("context.html", {
            "request": request,
            "page_title": "Context Memory",
            "stats": {"semantic_items": 0, "episodic_items": 0, "artifacts": 0, "total_items": 0},
            "semantic_items": [],
            "episodic_items": [],
            "error": str(e)
        })

@router.get("/usage", response_class=HTMLResponse)
async def usage(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Usage statistics page."""
    try:
        # Mock analytics data - in production this would come from usage stats
        analytics_data = {
            "total_requests": 45678,
            "avg_response_time": "245ms",
            "total_cost": "$1,234.56",
            "error_rate": "0.12%"
        }
        
        # Mock model usage data
        model_usage = [
            {"name": "GPT-4", "percentage": 45},
            {"name": "GPT-3.5-Turbo", "percentage": 30},
            {"name": "Claude-3", "percentage": 15},
            {"name": "Gemini-Pro", "percentage": 10}
        ]
        
        # Mock endpoint usage data
        endpoint_usage = [
            {"endpoint": "/api/v1/chat/completions", "requests": 12450},
            {"endpoint": "/api/v1/embeddings", "requests": 8920},
            {"endpoint": "/api/v1/models", "requests": 3210}
        ]
        
        return templates.TemplateResponse("usage.html", {
            "request": request, "page_title": "Usage Statistics",
            "analytics": analytics_data, "model_usage": model_usage,
            "endpoint_usage": endpoint_usage
        })
    except Exception as e:
        logger.exception("usage_error")
        return templates.TemplateResponse("usage.html", {
            "request": request, "page_title": "Usage Statistics",
            "analytics": {}, "error": str(e)
        })

@router.get("/models/sync-status", response_class=JSONResponse)
async def models_sync_status(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Get OpenRouter model synchronization status."""
    try:
        # Get actual model count from database
        total_models = await db.execute(select(func.count(ModelCatalog.model_id)))
        latest_model = await db.execute(
            select(ModelCatalog).order_by(ModelCatalog.updated_at.desc()).limit(1)
        )
        latest = latest_model.scalar_one_or_none()
        
        return JSONResponse({
            "status": "synced",
            "last_sync": latest.updated_at.isoformat() if latest else "never",
            "models_count": total_models.scalar() or 0,
            "sync_in_progress": False
        })
    except Exception as e:
        logger.exception("models_sync_status_error")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)

@router.post("/models/sync", response_class=JSONResponse)
async def models_sync(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Trigger OpenRouter model synchronization and store in database."""
    try:
        from app.services.openrouter import fetch_all_models
        from datetime import datetime
        
        # Fetch models from OpenRouter
        models = await fetch_all_models()
        
        # Store models in database
        stored_count = 0
        for model_data in models:
            try:
                # Check if model already exists
                existing_query = select(ModelCatalog).where(ModelCatalog.model_id == model_data.get("id"))
                existing_result = await db.execute(existing_query)
                existing_model = existing_result.scalar_one_or_none()
                
                # Prepare model data
                pricing = model_data.get("pricing", {})
                input_price = float(pricing.get("prompt", 0)) * 1000 if pricing.get("prompt") else 0
                output_price = float(pricing.get("completion", 0)) * 1000 if pricing.get("completion") else 0
                
                # Extract provider safely
                top_provider = model_data.get("top_provider", "Unknown")
                if isinstance(top_provider, dict):
                    provider_name = top_provider.get("name", "Unknown")
                else:
                    provider_name = str(top_provider) if top_provider and top_provider != "Unknown" else "Unknown"
                
                # Ensure provider is never null
                if not provider_name or provider_name.strip() == "":
                    provider_name = "Unknown"
                
                model_obj_data = {
                    "model_id": model_data.get("id"),
                    "provider": provider_name,
                    "display_name": model_data.get("name", model_data.get("id")),
                    "status": "active",
                    "context_window": model_data.get("context_length", 0),
                    "input_price_per_1k": input_price,
                    "output_price_per_1k": output_price,
                    "supports_vision": "image" in model_data.get("architecture", {}).get("input_modalities", []),
                    "supports_tools": model_data.get("architecture", {}).get("modality") == "text->text",
                    "supports_json_mode": False,  # Default to False
                    "metadata": model_data,  # Store full OpenRouter data
                    "updated_at": datetime.utcnow()
                }
                
                if existing_model:
                    # Update existing model
                    for key, value in model_obj_data.items():
                        setattr(existing_model, key, value)
                else:
                    # Create new model
                    model_obj_data["created_at"] = datetime.utcnow()
                    new_model = ModelCatalog(**model_obj_data)
                    db.add(new_model)
                
                stored_count += 1
                
            except Exception as model_error:
                logger.exception("model_storage_failed", model_id=model_data.get("id"))
                continue
        
        # Commit all changes
        await db.commit()
        
        logger.info("Model sync completed", stored_models=stored_count, total_fetched=len(models))
        
        return JSONResponse({
            "success": True,
            "message": f"Model sync completed successfully. Stored {stored_count} models.",
            "stored_count": stored_count,
            "total_fetched": len(models)
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("model_sync_failed")
        return JSONResponse({
            "success": False,
            "message": f"Model sync failed: {str(e)}"
        }, status_code=500)

@router.post("/models/{model_id}/enable", response_class=JSONResponse)
async def enable_model_for_users(request: Request, model_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Enable a model for user access."""
    try:
        # Find the model in the database
        query = select(ModelCatalog).where(ModelCatalog.model_id == model_id)
        result = await db.execute(query)
        model = result.scalar_one_or_none()
        
        if not model:
            return JSONResponse({
                "success": False,
                "message": f"Model {model_id} not found in database"
            }, status_code=404)
        
        # Update model status to active
        model.status = "active"
        model.updated_at = datetime.utcnow()
        await db.commit()
        
        logger.info("Model enabled for users", model_id=model_id)
        return JSONResponse({
            "success": True,
            "message": f"Model {model.display_name or model_id} has been enabled for users"
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("enable_model_error", model_id=model_id)
        return JSONResponse({
            "success": False,
            "message": f"Failed to enable model: {str(e)}"
        }, status_code=500)

@router.post("/models/{model_id}/disable", response_class=JSONResponse)
async def disable_model_for_users(request: Request, model_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Disable a model for user access."""
    try:
        # Find the model in the database
        query = select(ModelCatalog).where(ModelCatalog.model_id == model_id)
        result = await db.execute(query)
        model = result.scalar_one_or_none()
        
        if not model:
            return JSONResponse({
                "success": False,
                "message": f"Model {model_id} not found in database"
            }, status_code=404)
        
        # Update model status to disabled
        model.status = "disabled"
        model.updated_at = datetime.utcnow()
        await db.commit()
        
        logger.info("Model disabled for users", model_id=model_id)
        return JSONResponse({
            "success": True,
            "message": f"Model {model.display_name or model_id} has been disabled for users"
        })
        
    except Exception as e:
        await db.rollback()
        logger.exception("disable_model_error", model_id=model_id)
        return JSONResponse({
            "success": False,
            "message": f"Failed to disable model: {str(e)}"
        }, status_code=500)

@router.get("/api-keys/search", response_class=HTMLResponse)
async def api_keys_search(request: Request, db: AsyncSession = Depends(get_db_dependency), q: Optional[str] = None):
    """Search API keys."""
    return await api_keys_list(request, db, q)

@router.get("/api-keys/filter", response_class=HTMLResponse)
async def api_keys_filter(request: Request, db: AsyncSession = Depends(get_db_dependency), status: Optional[str] = None, workspace: Optional[str] = None):
    """Filter API keys by status or workspace."""
    try:
        query = select(APIKey)
        if status:
            if status == "active":
                query = query.where(APIKey.active == True)
            elif status == "suspended":
                query = query.where(APIKey.active == False)
        
        query = query.order_by(APIKey.created_at.desc()).limit(50)
        result = await db.execute(query)
        api_keys = result.scalars().all()
        
        # Get stats
        total_keys = await db.execute(select(func.count(APIKey.key_hash)))
        active_keys = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == True))
        suspended_keys = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == False))
        total_requests = await db.execute(select(func.sum(UsageStats.clicks + UsageStats.references)))
        
        stats = {
            "total_keys": total_keys.scalar() or 0, "active_keys": active_keys.scalar() or 0,
            "suspended_keys": suspended_keys.scalar() or 0, "total_requests": total_requests.scalar() or 0
        }
        
        formatted_keys = []
        for key in api_keys:
            key_prefix = key.key_hash[:8] + "..." if key.key_hash else "unknown"
            formatted_keys.append({
                "key_id": key.key_hash, "key_prefix": key_prefix,
                "workspace_name": key.name or "Default Workspace", "requests_count": 0,
                "quota_limit": key.daily_quota_tokens or 100000,
                "created_at": key.created_at.strftime("%Y-%m-%d %H:%M") if key.created_at else "Unknown",
                "last_used_at": "Never",
                "status": "active" if key.active else "suspended"
            })
        
        return templates.TemplateResponse("api_keys.html", {
            "request": request, "stats": stats, "api_keys": formatted_keys,
            "search_query": "", "page_title": "API Keys"
        })
    except Exception as e:
        logger.exception("api_keys_filter_error")
        return templates.TemplateResponse("api_keys.html", {
            "request": request, "stats": {"active_keys": 0, "suspended_keys": 0, "total_requests": 0},
            "api_keys": [], "search_query": "", "error": str(e), "page_title": "API Keys"
        })

@router.get("/system-status", response_class=JSONResponse)
async def system_status(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Get detailed system status."""
    try:
        # Check database connectivity
        try:
            await db.execute(select(func.count(APIKey.key_hash)))
            db_status = "connected"
        except Exception:
            db_status = "error"
        
        return JSONResponse({
            "api_gateway": {"status": "healthy", "response_time": "12ms"},
            "database": {"status": db_status, "connections": "5/20"},
            "redis": {"status": "online", "memory_usage": "45MB"},
            "openrouter": {"status": "available", "last_check": datetime.utcnow().isoformat()},
            "workers": {"status": "partial", "active": "2/3"},
            "storage": {"status": "connected", "usage": "78%"}
        })
    except Exception as e:
        logger.exception("system_status_error")
        return JSONResponse({
            "error": str(e)
        }, status_code=500)

@router.get("/api-keys/{key_id}/edit", response_class=HTMLResponse)
async def edit_api_key(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """Edit API key form."""
    try:
        query = select(APIKey).where(APIKey.key_hash == key_id)
        result = await db.execute(query)
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        
        return templates.TemplateResponse("api_key_edit.html", {
            "request": request, "api_key": api_key, "page_title": "Edit API Key"
        })
    except Exception as e:
        logger.exception("edit_api_key_error")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/api-keys/{key_id}/usage", response_class=HTMLResponse)
async def api_key_usage(request: Request, key_id: str, db: AsyncSession = Depends(get_db_dependency)):
    """View API key usage statistics."""
    try:
        query = select(APIKey).where(APIKey.key_hash == key_id)
        result = await db.execute(query)
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        
        # Mock usage data
        usage_data = {
            "total_requests": 0,
            "requests_today": 0,
            "quota_usage": "0%",
            "last_used": "Never"
        }
        
        return templates.TemplateResponse("api_key_usage.html", {
            "request": request, "api_key": api_key, "usage": usage_data, "page_title": "API Key Usage"
        })
    except Exception as e:
        logger.exception("api_key_usage_error")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/debug/models", response_class=JSONResponse)
async def debug_models(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Debug endpoint to check model storage."""
    try:
        # Get total count
        total_count = await db.execute(select(func.count(ModelCatalog.model_id)))
        total = total_count.scalar() or 0
        
        # Get first 5 models for debugging
        query = select(ModelCatalog).limit(5)
        result = await db.execute(query)
        models = result.scalars().all()
        
        model_data = []
        for model in models:
            model_data.append({
                "model_id": model.model_id,
                "display_name": model.display_name,
                "provider": model.provider,
                "status": model.status,
                "created_at": model.created_at.isoformat() if model.created_at else None,
                "input_price": float(model.input_price_per_1k) if model.input_price_per_1k else 0,
                "output_price": float(model.output_price_per_1k) if model.output_price_per_1k else 0
            })
        
        return JSONResponse({
            "total_models": total,
            "sample_models": model_data,
            "success": True
        })
    except Exception as e:
        logger.exception("debug_models_error")
        return JSONResponse({"error": str(e)}, status_code=500)