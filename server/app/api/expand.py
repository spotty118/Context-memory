"""
Context Memory expand-by-ID API endpoint.
"""
from typing import Dict, Any, Union
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import structlog

from app.core.security import get_api_key
from app.db.session import get_db_dependency
from app.db.models import APIKey, SemanticItem, EpisodicItem, Artifact, UsageStats

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/expand/{item_id}")
async def expand_by_id(
    item_id: str,
    api_key: APIKey = Depends(get_api_key),
    db: Session = Depends(get_db_dependency)
) -> Union[Dict[str, Any], Response]:
    """
    Expand an item by ID.
    
    Supports:
    - E# (episodic items) - returns raw evidence/snippet
    - S# (semantic items) - returns full content
    - CODE:path#Lstart-Lend - returns exact lines with content hash
    """
    logger.info(
        "expand_requested",
        workspace_id=api_key.workspace_id,
        item_id=item_id,
    )
    
    try:
        # Record usage for analytics
        await _record_expansion(item_id, api_key.workspace_id, db)
        
        if item_id.startswith("E"):
            # Episodic item
            item = db.query(EpisodicItem).filter(EpisodicItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Episodic item not found")
            
            return {
                "id": item.id,
                "type": "episodic",
                "thread_id": item.thread_id,
                "kind": item.kind,
                "title": item.title,
                "snippet": item.snippet,
                "source": item.source,
                "hash": item.hash,
                "salience": item.salience,
                "neighbors": item.neighbors or [],
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            
        elif item_id.startswith("S"):
            # Semantic item
            item = db.query(SemanticItem).filter(SemanticItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Semantic item not found")
            
            return {
                "id": item.id,
                "type": "semantic",
                "thread_id": item.thread_id,
                "kind": item.kind,
                "title": item.title,
                "body": item.body,
                "status": item.status,
                "tags": item.tags or [],
                "links": item.links or {},
                "salience": item.salience,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            
        elif item_id.startswith("CODE:"):
            # Code artifact
            artifact = db.query(Artifact).filter(Artifact.ref == item_id).first()
            if not artifact:
                # Return basic info even if not in database
                return {
                    "id": item_id,
                    "type": "code",
                    "ref": item_id,
                    "content": f"Code reference: {item_id[5:]}",
                    "hash": "unknown",
                    "lines": _extract_line_range(item_id),
                    "note": "Artifact not found in database - showing reference only"
                }
            
            return {
                "id": artifact.ref,
                "type": "code",
                "thread_id": artifact.thread_id,
                "ref": artifact.ref,
                "role": artifact.role,
                "hash": artifact.hash,
                "neighbors": artifact.neighbors or [],
                "lines": _extract_line_range(artifact.ref),
                "content": f"Code reference: {artifact.ref[5:]}",  # Remove 'CODE:' prefix
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid item ID format")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "expand_failed",
            workspace_id=api_key.workspace_id,
            item_id=item_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to expand item")


@router.get("/expand/{item_id}/raw")
async def expand_raw(
    item_id: str,
    api_key: APIKey = Depends(get_api_key),
    db: Session = Depends(get_db_dependency)
) -> Response:
    """
    Get raw content for an item (may return signed URL for large content).
    """
    logger.info(
        "expand_raw_requested",
        workspace_id=api_key.workspace_id,
        item_id=item_id,
    )
    
    try:
        # Record usage
        await _record_expansion(item_id, api_key.workspace_id, db)
        
        if item_id.startswith("E"):
            # Episodic item - return snippet
            item = db.query(EpisodicItem).filter(EpisodicItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Episodic item not found")
            
            content = f"Title: {item.title}\n\nSnippet:\n{item.snippet}"
            if item.source:
                content += f"\n\nSource: {item.source}"
            
            return Response(
                content=content,
                media_type="text/plain",
                headers={"X-Item-Type": "episodic"}
            )
            
        elif item_id.startswith("S"):
            # Semantic item - return full body
            item = db.query(SemanticItem).filter(SemanticItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Semantic item not found")
            
            content = f"Title: {item.title}\n\nBody:\n{item.body}"
            if item.tags:
                content += f"\n\nTags: {', '.join(item.tags)}"
            
            return Response(
                content=content,
                media_type="text/plain",
                headers={"X-Item-Type": "semantic"}
            )
            
        elif item_id.startswith("CODE:"):
            # Code artifact - return reference info
            artifact = db.query(Artifact).filter(Artifact.ref == item_id).first()
            
            if artifact:
                content = f"Code Reference: {artifact.ref}\nRole: {artifact.role}\nHash: {artifact.hash}"
                if artifact.neighbors:
                    content += f"\nRelated: {', '.join(artifact.neighbors)}"
            else:
                content = f"Code Reference: {item_id}\nNote: Artifact not found in database"
            
            return Response(
                content=content,
                media_type="text/plain",
                headers={"X-Item-Type": "code"}
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid item ID format")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "expand_raw_failed",
            workspace_id=api_key.workspace_id,
            item_id=item_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to get raw content")


async def _record_expansion(item_id: str, workspace_id: str, db: Session) -> None:
    """Record item expansion for usage analytics."""
    try:
        # Get or create usage stats
        stats = db.query(UsageStats).filter(
            UsageStats.item_id == item_id,
            UsageStats.workspace_id == workspace_id
        ).first()
        
        if stats:
            stats.expansions += 1
            stats.last_accessed = db.execute("SELECT NOW()").scalar()
        else:
            stats = UsageStats(
                item_id=item_id,
                workspace_id=workspace_id,
                clicks=0,
                references=0,
                expansions=1,
                last_accessed=db.execute("SELECT NOW()").scalar()
            )
            db.add(stats)
        
        db.commit()
        
        logger.debug(
            "expansion_recorded",
            item_id=item_id,
            workspace_id=workspace_id,
            total_expansions=stats.expansions
        )
    
    except Exception as e:
        logger.warning(
            "expansion_recording_failed",
            item_id=item_id,
            workspace_id=workspace_id,
            error=str(e)
        )
        # Don't fail the main request if usage recording fails
        db.rollback()


def _extract_line_range(ref: str) -> str:
    """Extract line range from code reference."""
    if "#L" in ref:
        line_part = ref.split("#L", 1)[1]
        return line_part
    return "unknown"

