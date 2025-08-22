"""
Context Memory ingest API endpoint.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.core.security import get_api_key
from app.db.session import get_db_dependency
from app.db.models import APIKey, SemanticItem, EpisodicItem, Artifact
from app.services.extractor import ContextExtractor
from app.services.consolidator import ContextConsolidator

router = APIRouter()
logger = structlog.get_logger(__name__)


class IngestMaterials(BaseModel):
    chat: Optional[str] = Field(None, description="Chat conversation data")
    diffs: Optional[str] = Field(None, description="Code diff data")
    logs: Optional[str] = Field(None, description="Log data")


class IngestRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID for context")
    materials: IngestMaterials = Field(..., description="Materials to ingest")
    purpose: Optional[str] = Field(None, description="Purpose of ingestion")


class IngestResponse(BaseModel):
    thread_id: str
    added_ids: List[str]
    updated_ids: List[str]
    summary: str


@router.post("/ingest", response_model=IngestResponse)
async def ingest_context(
    request: IngestRequest,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db_dependency)
):
    """
    Ingest context materials into the memory system.
    
    Pipeline: redact → extract semantic/episodic → consolidate → persist → embed → store blobs
    """
    logger.info(
        "context_ingest_requested",
        workspace_id=api_key.workspace_id,
        thread_id=request.thread_id,
        purpose=request.purpose,
        has_chat=bool(request.materials.chat),
        has_diffs=bool(request.materials.diffs),
        has_logs=bool(request.materials.logs),
    )
    
    try:
        # Initialize services
        extractor = ContextExtractor()
        consolidator = ContextConsolidator()
        
        all_added_ids = []
        all_updated_ids = []
        
        # Process each material type
        materials_processed = []
        
        if request.materials.chat:
            # Redact sensitive data
            redacted_chat = extractor.redact_sensitive_data(request.materials.chat)
            
            # Extract items
            semantic_items = extractor.extract_semantic_items(redacted_chat, request.thread_id)
            episodic_items = extractor.extract_episodic_items(redacted_chat, request.thread_id, "chat")
            artifacts = extractor.extract_artifacts(redacted_chat, request.thread_id)
            
            # Get existing items for consolidation
            existing_semantic = await _get_existing_semantic_items(request.thread_id, db)
            existing_episodic = await _get_existing_episodic_items(request.thread_id, db)
            existing_artifacts = await _get_existing_artifacts(request.thread_id, db)
            
            # Consolidate
            consolidated_semantic, added_s, updated_s = consolidator.consolidate_semantic_items(
                semantic_items, existing_semantic
            )
            consolidated_episodic, added_e, updated_e = consolidator.consolidate_episodic_items(
                episodic_items, existing_episodic
            )
            consolidated_artifacts, added_a, updated_a = consolidator.consolidate_artifacts(
                artifacts, existing_artifacts
            )
            
            # Persist to database
            await _persist_semantic_items(consolidated_semantic, db)
            await _persist_episodic_items(consolidated_episodic, db)
            await _persist_artifacts(consolidated_artifacts, db)
            
            all_added_ids.extend(added_s + added_e + added_a)
            all_updated_ids.extend(updated_s + updated_e + updated_a)
            materials_processed.append("chat")
        
        if request.materials.diffs:
            # Process diffs (similar pattern)
            redacted_diffs = extractor.redact_sensitive_data(request.materials.diffs)
            
            episodic_items = extractor.extract_episodic_items(redacted_diffs, request.thread_id, "diffs")
            artifacts = extractor.extract_artifacts(redacted_diffs, request.thread_id)
            
            existing_episodic = await _get_existing_episodic_items(request.thread_id, db)
            existing_artifacts = await _get_existing_artifacts(request.thread_id, db)
            
            consolidated_episodic, added_e, updated_e = consolidator.consolidate_episodic_items(
                episodic_items, existing_episodic
            )
            consolidated_artifacts, added_a, updated_a = consolidator.consolidate_artifacts(
                artifacts, existing_artifacts
            )
            
            await _persist_episodic_items(consolidated_episodic, db)
            await _persist_artifacts(consolidated_artifacts, db)
            
            all_added_ids.extend(added_e + added_a)
            all_updated_ids.extend(updated_e + updated_a)
            materials_processed.append("diffs")
        
        if request.materials.logs:
            # Process logs (similar pattern)
            redacted_logs = extractor.redact_sensitive_data(request.materials.logs)
            
            episodic_items = extractor.extract_episodic_items(redacted_logs, request.thread_id, "logs")
            
            existing_episodic = await _get_existing_episodic_items(request.thread_id, db)
            
            consolidated_episodic, added_e, updated_e = consolidator.consolidate_episodic_items(
                episodic_items, existing_episodic
            )
            
            await _persist_episodic_items(consolidated_episodic, db)
            
            all_added_ids.extend(added_e)
            all_updated_ids.extend(updated_e)
            materials_processed.append("logs")
        
        # Commit all changes
        await db.commit()
        
        # Create summary
        summary = f"Processed {', '.join(materials_processed)}. Added {len(all_added_ids)} items, updated {len(all_updated_ids)} items."
        
        logger.info(
            "context_ingest_completed",
            workspace_id=api_key.workspace_id,
            thread_id=request.thread_id,
            added_count=len(all_added_ids),
            updated_count=len(all_updated_ids),
            materials=materials_processed,
        )
        
        return IngestResponse(
            thread_id=request.thread_id,
            added_ids=all_added_ids,
            updated_ids=all_updated_ids,
            summary=summary
        )
    
    except Exception as e:
        await db.rollback()
        logger.error(
            "context_ingest_failed",
            workspace_id=api_key.workspace_id,
            thread_id=request.thread_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


async def _get_existing_semantic_items(thread_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    """Get existing semantic items for consolidation."""
    result = await db.execute(select(SemanticItem).where(SemanticItem.thread_id == thread_id))
    items = result.scalars().all()
    
    return [
        {
            'id': item.id,
            'thread_id': item.thread_id,
            'kind': item.kind,
            'title': item.title,
            'body': item.body,
            'status': item.status,
            'tags': item.tags or [],
            'links': item.links or {},
            'salience': item.salience,
            'created_at': item.created_at,
            'updated_at': item.updated_at,
        }
        for item in items
    ]


async def _get_existing_episodic_items(thread_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    """Get existing episodic items for consolidation."""
    result = await db.execute(select(EpisodicItem).where(EpisodicItem.thread_id == thread_id))
    items = result.scalars().all()
    
    return [
        {
            'id': item.id,
            'thread_id': item.thread_id,
            'kind': item.kind,
            'title': item.title,
            'snippet': item.snippet,
            'source': item.source,
            'hash': item.hash,
            'salience': item.salience,
            'neighbors': item.neighbors or [],
            'created_at': item.created_at,
        }
        for item in items
    ]


async def _get_existing_artifacts(thread_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    """Get existing artifacts for consolidation."""
    result = await db.execute(select(Artifact).where(Artifact.thread_id == thread_id))
    artifacts = result.scalars().all()
    
    return [
        {
            'ref': artifact.ref,
            'thread_id': artifact.thread_id,
            'role': artifact.role,
            'hash': artifact.hash,
            'neighbors': artifact.neighbors or [],
        }
        for artifact in artifacts
    ]


async def _persist_semantic_items(items: List[Dict[str, Any]], db: AsyncSession) -> None:
    """Persist semantic items to database."""
    for item_data in items:
        # Check if item exists
        result = await db.execute(select(SemanticItem).where(SemanticItem.id == item_data['id']))
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing item
            for key, value in item_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            # Create new item
            item = SemanticItem(**item_data)
            db.add(item)


async def _persist_episodic_items(items: List[Dict[str, Any]], db: AsyncSession) -> None:
    """Persist episodic items to database."""
    for item_data in items:
        result = await db.execute(select(EpisodicItem).where(EpisodicItem.id == item_data['id']))
        existing = result.scalar_one_or_none()
        
        if existing:
            for key, value in item_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            item = EpisodicItem(**item_data)
            db.add(item)


async def _persist_artifacts(artifacts: List[Dict[str, Any]], db: AsyncSession) -> None:
    """Persist artifacts to database."""
    for artifact_data in artifacts:
        result = await db.execute(select(Artifact).where(Artifact.ref == artifact_data['ref']))
        existing = result.scalar_one_or_none()
        
        if existing:
            for key, value in artifact_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            artifact = Artifact(**artifact_data)
            db.add(artifact)

