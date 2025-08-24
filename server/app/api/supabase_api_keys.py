"""
Supabase-based API Keys management endpoints.
Replaces the SQLAlchemy-based API key operations.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Form
from pydantic import BaseModel
import hashlib
import secrets
import structlog

from app.core.supabase import get_supabase_admin, Tables
from app.core.auth import get_current_api_key

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])

class APIKeyResponse(BaseModel):
    id: str
    key_name: str
    description: Optional[str]
    workspace_id: str
    is_active: bool
    created_at: str
    last_used_at: Optional[str]

class CreateAPIKeyRequest(BaseModel):
    key_name: str
    description: Optional[str] = None
    workspace_id: str = "default"

def generate_api_key() -> str:
    """Generate a new API key."""
    return f"cmg_{secrets.token_urlsafe(32)}"

def hash_api_key(key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()

@router.get("/", response_model=List[APIKeyResponse])
async def list_api_keys(
    workspace_id: Optional[str] = None,
    active_only: bool = True,
    api_key = Depends(get_current_api_key)
):
    """List API keys with optional filtering."""
    try:
        supabase = get_supabase_admin()
        query = supabase.table(Tables.API_KEYS).select("*")
        
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        
        if active_only:
            query = query.eq("is_active", True)
            
        response = query.order("created_at", desc=True).execute()
        
        return [APIKeyResponse(**key) for key in response.data]
        
    except Exception as e:
        logger.exception("list_api_keys_failed")
        raise HTTPException(status_code=500, detail="Failed to list API keys")

@router.post("/", response_model=dict)
async def create_api_key(
    request: CreateAPIKeyRequest,
    api_key = Depends(get_current_api_key)
):
    """Create a new API key."""
    try:
        # Generate new API key
        new_key = generate_api_key()
        key_hash = hash_api_key(new_key)
        
        supabase = get_supabase_admin()
        response = supabase.table(Tables.API_KEYS).insert({
            "key_name": request.key_name,
            "description": request.description,
            "workspace_id": request.workspace_id,
            "key_hash": key_hash,
            "is_active": True,
            "created_by": "admin"
        }).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create API key")
            
        return {
            "api_key": new_key,  # Only returned once
            "key_info": APIKeyResponse(**response.data[0])
        }
        
    except Exception as e:
        logger.exception("create_api_key_failed")
        raise HTTPException(status_code=500, detail="Failed to create API key")

@router.patch("/{key_id}/activate")
async def activate_api_key(
    key_id: str,
    api_key = Depends(get_current_api_key)
):
    """Activate an API key."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.API_KEYS).update({
            "is_active": True
        }).eq("id", key_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="API key not found")
            
        return {"message": "API key activated"}
        
    except Exception as e:
        logger.exception("activate_api_key_failed")
        raise HTTPException(status_code=500, detail="Failed to activate API key")

@router.patch("/{key_id}/deactivate")
async def deactivate_api_key(
    key_id: str,
    api_key = Depends(get_current_api_key)
):
    """Deactivate an API key."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.API_KEYS).update({
            "is_active": False
        }).eq("id", key_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="API key not found")
            
        return {"message": "API key deactivated"}
        
    except Exception as e:
        logger.exception("deactivate_api_key_failed")
        raise HTTPException(status_code=500, detail="Failed to deactivate API key")

@router.delete("/{key_id}")
async def delete_api_key(
    key_id: str,
    api_key = Depends(get_current_api_key)
):
    """Delete an API key."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.API_KEYS).delete().eq("id", key_id).execute()
        
        return {"message": "API key deleted"}
        
    except Exception as e:
        logger.exception("delete_api_key_failed")
        raise HTTPException(status_code=500, detail="Failed to delete API key")

@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    key_id: str,
    api_key = Depends(get_current_api_key)
):
    """Get details of a specific API key."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.API_KEYS).select("*").eq("id", key_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="API key not found")
            
        return APIKeyResponse(**response.data[0])
        
    except Exception as e:
        logger.exception("get_api_key_failed")
        raise HTTPException(status_code=500, detail="Failed to get API key")

@router.get("/{key_id}/usage")
async def get_api_key_usage(
    key_id: str,
    days: int = 30,
    api_key = Depends(get_current_api_key)
):
    """Get usage statistics for an API key."""
    try:
        # First get the key hash
        supabase = get_supabase_admin()
        key_response = supabase.table(Tables.API_KEYS).select("key_hash").eq("id", key_id).execute()
        
        if not key_response.data:
            raise HTTPException(status_code=404, detail="API key not found")
            
        key_hash = key_response.data[0]["key_hash"]
        
        # Get usage stats
        from datetime import datetime, timedelta
        since_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        usage_response = supabase.table(Tables.USAGE_LEDGER).select(
            "total_tokens, cost_usd, model_id, endpoint, success"
        ).eq("api_key_hash", key_hash).gte("request_timestamp", since_date).execute()
        
        # Aggregate usage data
        total_tokens = sum(record.get("total_tokens", 0) for record in usage_response.data)
        total_cost = sum(float(record.get("cost_usd", 0)) for record in usage_response.data)
        total_requests = len(usage_response.data)
        successful_requests = sum(1 for record in usage_response.data if record.get("success", True))
        
        return {
            "key_id": key_id,
            "period_days": days,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "success_rate": successful_requests / total_requests if total_requests > 0 else 0
        }
        
    except Exception as e:
        logger.exception("get_api_key_usage_failed")
        raise HTTPException(status_code=500, detail="Failed to get API key usage")
