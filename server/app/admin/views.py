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

async def require_admin_auth(request: Request) -> Optional[AdminUser]:
    """Require admin authentication, return AdminUser or None."""
    try:
        return await get_admin_user(request)
    except Exception:
        return None

# Root redirect to login
@router.get("/", response_class=RedirectResponse)
async def admin_root():
    """Redirect admin root to login."""
    return RedirectResponse(url="/admin/login", status_code=302)

# Authentication routes
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show admin login page."""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "page_title": "Admin Login"
    })

@router.post("/login", response_class=RedirectResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle admin login submission."""
    try:
        if await authenticate_admin(username, password):
            jwt_token = create_admin_jwt(username)
            response = RedirectResponse(url="/admin/dashboard", status_code=302)
            response.set_cookie(
                key="admin_token",
                value=jwt_token,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=app_settings.JWT_EXPIRE_MINUTES * 60
            )
            return response
        else:
            return RedirectResponse(url="/admin/login?error=invalid_credentials", status_code=302)
    except Exception as e:
        logger.exception("login_error")
        return RedirectResponse(url="/admin/login?error=login_failed", status_code=302)

@router.get("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    """Admin logout."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    """Show admin signup page."""
    return templates.TemplateResponse("signup.html", {
        "request": request,
        "page_title": "Admin Signup"
    })

@router.post("/signup", response_class=RedirectResponse)
async def signup_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle admin signup submission."""
    try:
        if password != confirm_password:
            return RedirectResponse(url="/admin/signup?error=password_mismatch", status_code=302)
        
        await create_user(username, email, password)
        return RedirectResponse(url="/admin/login?success=account_created", status_code=302)
    except HTTPException as e:
        error_msg = "username_taken" if "username" in str(e.detail).lower() else "signup_failed"
        return RedirectResponse(url=f"/admin/signup?error={error_msg}", status_code=302)
    except Exception as e:
        logger.exception("signup_error")
        return RedirectResponse(url="/admin/signup?error=signup_failed", status_code=302)

# Dashboard
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Admin dashboard with system overview."""
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
        
        # API Key stats
        total_keys_result = await db.execute(select(func.count(APIKey.key_hash)))
        stats["total_api_keys"] = total_keys_result.scalar() or 0
        
        active_keys_result = await db.execute(select(func.count(APIKey.key_hash)).where(APIKey.active == True))
        stats["active_keys"] = active_keys_result.scalar() or 0
        stats["suspended_keys"] = stats["total_api_keys"] - stats["active_keys"]
        
        # Model stats
        total_models_result = await db.execute(select(func.count(ModelCatalog.model_id)))
        stats["total_models"] = total_models_result.scalar() or 0
        
        active_models_result = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "active"))
        stats["active_models"] = active_models_result.scalar() or 0
        
        # Memory stats
        semantic_result = await db.execute(select(func.count(SemanticItem.id)))
        stats["total_semantic_items"] = semantic_result.scalar() or 0
        
        episodic_result = await db.execute(select(func.count(EpisodicItem.id)))
        stats["total_episodic_items"] = episodic_result.scalar() or 0
        
        artifacts_result = await db.execute(select(func.count(Artifact.ref)))
        stats["total_artifacts"] = artifacts_result.scalar() or 0
        
        # User stats
        from app.db.models import User
        users_result = await db.execute(select(func.count(User.id)))
        stats["total_users"] = users_result.scalar() or 0
        
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
        total_requests_result = await db.execute(select(func.coalesce(func.sum(APIKey.total_requests), 0)))
        
        stats = {
            "active_keys": active_count_result.scalar() or 0,
            "suspended_keys": suspended_count_result.scalar() or 0,
            "total_requests": total_requests_result.scalar() or 0
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
                "rate_limit": key.rate_limit_requests or 60
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
async def generate_api_key(
    request: Request, 
    db: AsyncSession = Depends(get_db_dependency), 
    name: str = Form(...),
    description: Optional[str] = Form(None)
):
    """Generate a new API key."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Generate new API key
        key_prefix = app_settings.API_KEY_PREFIX
        key_length = app_settings.API_KEY_LENGTH
        random_part = secrets.token_urlsafe(key_length)
        new_key = f"{key_prefix}_{random_part}"
        
        # Hash for storage
        key_hash = hashlib.sha256(new_key.encode()).hexdigest()
        
        # Create database record
        api_key = APIKey(
            key_hash=key_hash,
            name=name,
            description=description,
            active=True,
            daily_quota_tokens=app_settings.DEFAULT_DAILY_QUOTA_TOKENS,
            rate_limit_requests=app_settings.RATE_LIMIT_REQUESTS,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(api_key)
        await db.commit()
        
        logger.info("Generated new API key", key_hash=key_hash[:12], name=name)
        
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

# Models Management
@router.get("/models", response_class=HTMLResponse)
async def models_list(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Models management page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        query = select(ModelCatalog).order_by(ModelCatalog.created_at.desc()).limit(50)
        result = await db.execute(query)
        models = result.scalars().all()
        
        total_models_result = await db.execute(select(func.count(ModelCatalog.model_id)))
        active_models_result = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "active"))
        deprecated_models_result = await db.execute(select(func.count(ModelCatalog.model_id)).where(ModelCatalog.status == "deprecated"))
        
        stats = {
            "active_models": active_models_result.scalar() or 0,
            "deprecated_models": deprecated_models_result.scalar() or 0,
            "most_used_model": "GPT-4",
            "total_requests": 0
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
        latest_model_result = await db.execute(
            select(ModelCatalog).order_by(ModelCatalog.updated_at.desc()).limit(1)
        )
        latest = latest_model_result.scalar_one_or_none()
        last_sync = latest.updated_at.strftime("%Y-%m-%d %H:%M") if latest else "Never"
        
        return templates.TemplateResponse("models.html", {
            "request": request,
            "stats": stats,
            "models": formatted_models,
            "last_sync": last_sync,
            "total_models": len(formatted_models),
            "active_models": stats["active_models"],
            "page_title": "Models"
        })
    except Exception as e:
        logger.exception("models_error")
        return templates.TemplateResponse("models.html", {
            "request": request,
            "stats": {"active_models": 0, "deprecated_models": 0, "most_used_model": "N/A", "total_requests": 0},
            "models": [],
            "last_sync": "Unknown",
            "total_models": 0,
            "active_models": 0,
            "error": str(e),
            "page_title": "Models"
        })

@router.get("/models/sync-status", response_class=HTMLResponse)
async def models_sync_status(request: Request, db: AsyncSession = Depends(get_db_dependency)):
    """Get model sync status for HTMX updates."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        # Get latest model sync time
        latest_model_result = await db.execute(
            select(ModelCatalog).order_by(ModelCatalog.updated_at.desc()).limit(1)
        )
        latest = latest_model_result.scalar_one_or_none()
        
        if latest:
            last_sync = latest.updated_at.strftime("%Y-%m-%d at %H:%M UTC")
            models_count_result = await db.execute(select(func.count(ModelCatalog.model_id)))
            models_count = models_count_result.scalar() or 0
            
            status_class = "bg-green-50 border-green-200"
            icon_class = "text-green-400"
            icon = "check-circle"
            message = f"Last synced on {last_sync} • {models_count} models available"
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
        models_data = await fetch_all_models()
        
        updated_count = 0
        new_count = 0
        
        for model_data in models_data:
            model_id = model_data.get("id")
            if not model_id:
                continue
                
            # Check if model exists
            existing_result = await db.execute(
                select(ModelCatalog).where(ModelCatalog.model_id == model_id)
            )
            model = existing_result.scalar_one_or_none()
            
            if model:
                # Update existing model
                model.display_name = model_data.get("name", model_id)
                model.provider = "openrouter"
                model.context_window = model_data.get("context_length", 0)
                model.input_price_per_1k = model_data.get("pricing", {}).get("prompt", 0)
                model.output_price_per_1k = model_data.get("pricing", {}).get("completion", 0)
                model.supports_vision = "vision" in model_data.get("id", "").lower()
                model.supports_tools = True
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

# Settings
@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    """Settings management page."""
    admin_user = await require_admin_auth(request)
    if not admin_user:
        return RedirectResponse(url="/admin/login", status_code=302)
    
    try:
        settings_data = {
            "openrouter_key": "sk-or-..." if app_settings.OPENROUTER_API_KEY else "",
            "jwt_secret": app_settings.JWT_SECRET_KEY[:8] + "..." if app_settings.JWT_SECRET_KEY else "",
            "database_url": "postgresql://..." if app_settings.DATABASE_URL else "",
            "redis_url": "redis://redis:6379/0"
        }
        
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "page_title": "Settings",
            "settings": settings_data,
            "openrouter_configured": bool(app_settings.OPENROUTER_API_KEY)
        })
    except Exception as e:
        logger.exception("settings_error")
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "page_title": "Settings",
            "settings": {},
            "error": str(e)
        })

# Favicon handler
@router.get("/favicon.ico", response_class=JSONResponse)
async def favicon():
    """Handle favicon requests."""
    return JSONResponse(content=None, status_code=204)
