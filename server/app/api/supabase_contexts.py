"""
Supabase-based Context Memory endpoints.
Replaces SQLAlchemy-based context operations.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
import structlog

from app.core.supabase import get_supabase_admin, Tables
from app.core.security import get_current_api_key

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/contexts", tags=["contexts"])

class ContextResponse(BaseModel):
    id: str
    workspace_id: str
    context_name: str
    description: Optional[str]
    metadata: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str

class ContextItemResponse(BaseModel):
    id: str
    context_id: str
    content: str
    content_type: str
    metadata: Dict[str, Any]
    chunk_index: int
    total_chunks: int
    token_count: Optional[int]
    created_at: str

class CreateContextRequest(BaseModel):
    context_name: str
    description: Optional[str] = None
    workspace_id: str = "default"
    metadata: Dict[str, Any] = {}

class CreateContextItemRequest(BaseModel):
    content: str
    content_type: str = "text"
    metadata: Dict[str, Any] = {}
    chunk_index: int = 0
    total_chunks: int = 1

@router.get("/", response_model=List[ContextResponse])
async def list_contexts(
    workspace_id: Optional[str] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    api_key = Depends(get_current_api_key)
):
    """List contexts with optional filtering."""
    try:
        supabase = get_supabase_admin()
        query = supabase.table(Tables.CONTEXTS).select("*")
        
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        
        if active_only:
            query = query.eq("is_active", True)
            
        response = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        
        return [ContextResponse(**ctx) for ctx in response.data]
        
    except Exception as e:
        logger.exception("list_contexts_failed")
        raise HTTPException(status_code=500, detail="Failed to list contexts")

@router.post("/", response_model=ContextResponse)
async def create_context(
    request: CreateContextRequest,
    api_key = Depends(get_current_api_key)
):
    """Create a new context."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.CONTEXTS).insert({
            "context_name": request.context_name,
            "description": request.description,
            "workspace_id": request.workspace_id,
            "metadata": request.metadata,
            "is_active": True,
            "created_by": "api"
        }).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create context")
            
        return ContextResponse(**response.data[0])
        
    except Exception as e:
        logger.exception("create_context_failed")
        raise HTTPException(status_code=500, detail="Failed to create context")

@router.get("/{context_id}", response_model=ContextResponse)
async def get_context(
    context_id: str,
    api_key = Depends(get_current_api_key)
):
    """Get a specific context."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.CONTEXTS).select("*").eq("id", context_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Context not found")
            
        return ContextResponse(**response.data[0])
        
    except Exception as e:
        logger.exception("get_context_failed")
        raise HTTPException(status_code=500, detail="Failed to get context")

@router.put("/{context_id}", response_model=ContextResponse)
async def update_context(
    context_id: str,
    request: CreateContextRequest,
    api_key = Depends(get_current_api_key)
):
    """Update a context."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.CONTEXTS).update({
            "context_name": request.context_name,
            "description": request.description,
            "metadata": request.metadata
        }).eq("id", context_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Context not found")
            
        return ContextResponse(**response.data[0])
        
    except Exception as e:
        logger.exception("update_context_failed")
        raise HTTPException(status_code=500, detail="Failed to update context")

@router.delete("/{context_id}")
async def delete_context(
    context_id: str,
    api_key = Depends(get_current_api_key)
):
    """Delete a context and all its items."""
    try:
        supabase = get_supabase_admin()
        
        # Delete context items first (due to foreign key constraint)
        supabase.table(Tables.CONTEXT_ITEMS).delete().eq("context_id", context_id).execute()
        
        # Delete context
        response = supabase.table(Tables.CONTEXTS).delete().eq("id", context_id).execute()
        
        return {"message": "Context deleted successfully"}
        
    except Exception as e:
        logger.exception("delete_context_failed")
        raise HTTPException(status_code=500, detail="Failed to delete context")

@router.get("/{context_id}/items", response_model=List[ContextItemResponse])
async def get_context_items(
    context_id: str,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    api_key = Depends(get_current_api_key)
):
    """Get items in a context."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.CONTEXT_ITEMS).select("*").eq(
            "context_id", context_id
        ).order("chunk_index").range(offset, offset + limit - 1).execute()
        
        return [ContextItemResponse(**item) for item in response.data]
        
    except Exception as e:
        logger.exception("get_context_items_failed")
        raise HTTPException(status_code=500, detail="Failed to get context items")

@router.post("/{context_id}/items", response_model=ContextItemResponse)
async def add_context_item(
    context_id: str,
    request: CreateContextItemRequest,
    api_key = Depends(get_current_api_key)
):
    """Add an item to a context."""
    try:
        # First verify context exists
        supabase = get_supabase_admin()
        ctx_response = supabase.table(Tables.CONTEXTS).select("workspace_id").eq("id", context_id).execute()
        
        if not ctx_response.data:
            raise HTTPException(status_code=404, detail="Context not found")
            
        workspace_id = ctx_response.data[0]["workspace_id"]
        
        # Add context item
        response = supabase.table(Tables.CONTEXT_ITEMS).insert({
            "context_id": context_id,
            "workspace_id": workspace_id,
            "content": request.content,
            "content_type": request.content_type,
            "metadata": request.metadata,
            "chunk_index": request.chunk_index,
            "total_chunks": request.total_chunks,
            "token_count": len(request.content.split())  # Simple token count
        }).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to add context item")
            
        return ContextItemResponse(**response.data[0])
        
    except Exception as e:
        logger.exception("add_context_item_failed")
        raise HTTPException(status_code=500, detail="Failed to add context item")

@router.delete("/{context_id}/items/{item_id}")
async def delete_context_item(
    context_id: str,
    item_id: str,
    api_key = Depends(get_current_api_key)
):
    """Delete a context item."""
    try:
        supabase = get_supabase_admin()
        response = supabase.table(Tables.CONTEXT_ITEMS).delete().eq("id", item_id).eq("context_id", context_id).execute()
        
        return {"message": "Context item deleted successfully"}
        
    except Exception as e:
        logger.exception("delete_context_item_failed")
        raise HTTPException(status_code=500, detail="Failed to delete context item")

@router.post("/{context_id}/search")
async def search_context(
    context_id: str,
    query: str = Query(..., description="Search query"),
    limit: int = Query(10, le=100),
    api_key = Depends(get_current_api_key)
):
    """Search within a context using embeddings similarity."""
    try:
        supabase = get_supabase_admin()
        
        # For now, do a simple text search
        # TODO: Implement proper embedding-based search
        response = supabase.table(Tables.CONTEXT_ITEMS).select("*").eq(
            "context_id", context_id
        ).ilike("content", f"%{query}%").limit(limit).execute()
        
        results = []
        for item in response.data:
            # Calculate simple relevance score based on query match
            content_lower = item["content"].lower()
            query_lower = query.lower()
            score = content_lower.count(query_lower) / len(content_lower.split())
            
            results.append({
                **item,
                "relevance_score": score
            })
        
        # Sort by relevance
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        return {
            "query": query,
            "results": results,
            "total_results": len(results)
        }
        
    except Exception as e:
        logger.exception("search_context_failed")
        raise HTTPException(status_code=500, detail="Failed to search context")

@router.get("/{context_id}/stats")
async def get_context_stats(
    context_id: str,
    api_key = Depends(get_current_api_key)
):
    """Get statistics for a context."""
    try:
        supabase = get_supabase_admin()
        
        # Get context info
        ctx_response = supabase.table(Tables.CONTEXTS).select("*").eq("id", context_id).execute()
        if not ctx_response.data:
            raise HTTPException(status_code=404, detail="Context not found")
            
        context = ctx_response.data[0]
        
        # Get item stats
        items_response = supabase.table(Tables.CONTEXT_ITEMS).select("token_count").eq("context_id", context_id).execute()
        
        total_items = len(items_response.data)
        total_tokens = sum(item.get("token_count", 0) for item in items_response.data if item.get("token_count"))
        
        return {
            "context_id": context_id,
            "context_name": context["context_name"],
            "total_items": total_items,
            "total_tokens": total_tokens,
            "is_active": context["is_active"],
            "created_at": context["created_at"],
            "updated_at": context["updated_at"]
        }
        
    except Exception as e:
        logger.exception("get_context_stats_failed")
        raise HTTPException(status_code=500, detail="Failed to get context stats")
