"""
Background jobs for generating embeddings for context memory items.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import openai
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db_session
from app.db.models import SemanticItem, EpisodicItem, Artifact
from app.workers.queue import embedding_job
from app.core.config import settings

logger = structlog.get_logger(__name__)

# Initialize OpenAI client
openai_client = openai.OpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url=settings.OPENROUTER_API_BASE
)

@embedding_job
def generate_embeddings_for_item(item_type: str, item_id: str) -> Dict[str, Any]:
    """
    Generate embeddings for a specific context memory item.
    
    Args:
        item_type: Type of item ('semantic', 'episodic', 'artifact')
        item_id: ID of the item
    
    Returns:
        Dictionary with generation results
    """
    logger.info("embedding_generation_started", item_type=item_type, item_id=item_id)
    
    try:
        with get_db_session() as db:
            # Get the item based on type
            item = _get_item_by_type(db, item_type, item_id)
            if not item:
                return {
                    "error": f"Item not found: {item_type} {item_id}",
                    "item_type": item_type,
                    "item_id": item_id
                }
            
            # Check if embeddings already exist
            if item.embedding_vector is not None:
                logger.info("embedding_already_exists", item_type=item_type, item_id=item_id)
                return {
                    "status": "skipped",
                    "reason": "embeddings_already_exist",
                    "item_type": item_type,
                    "item_id": item_id
                }
            
            # Generate embedding
            embedding_text = _get_embedding_text(item)
            if not embedding_text:
                return {
                    "error": "No text available for embedding",
                    "item_type": item_type,
                    "item_id": item_id
                }
            
            # Call OpenAI embedding API
            embedding_vector = _generate_embedding(embedding_text)
            
            # Store embedding in database
            item.embedding_vector = embedding_vector
            item.updated_at = datetime.utcnow()
            
            db.commit()
            
            logger.info(
                "embedding_generation_completed",
                item_type=item_type,
                item_id=item_id,
                vector_dimensions=len(embedding_vector) if embedding_vector else 0
            )
            
            return {
                "status": "success",
                "item_type": item_type,
                "item_id": item_id,
                "vector_dimensions": len(embedding_vector) if embedding_vector else 0,
                "generation_time": datetime.utcnow().isoformat()
            }
    
    except Exception as e:
        error_msg = f"Embedding generation failed for {item_type} {item_id}: {str(e)}"
        logger.exception("embedding_generation_failed", message=error_msg, item_type=item_type, item_id=item_id)
        return {
            "error": error_msg,
            "item_type": item_type,
            "item_id": item_id,
            "generation_time": datetime.utcnow().isoformat()
        }

@embedding_job
def batch_generate_embeddings(
    item_type: str, 
    item_ids: List[str], 
    batch_size: int = 10
) -> Dict[str, Any]:
    """
    Generate embeddings for multiple items in batches.
    
    Args:
        item_type: Type of items ('semantic', 'episodic', 'artifact')
        item_ids: List of item IDs
        batch_size: Number of items to process in each batch
    
    Returns:
        Dictionary with batch generation results
    """
    logger.info(
        "batch_embedding_generation_started",
        item_type=item_type,
        item_count=len(item_ids),
        batch_size=batch_size
    )
    
    results = {
        "total_items": len(item_ids),
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "generation_time": datetime.utcnow().isoformat()
    }
    
    try:
        with get_db_session() as db:
            # Process items in batches
            for i in range(0, len(item_ids), batch_size):
                batch_ids = item_ids[i:i + batch_size]
                
                logger.info(
                    "processing_batch",
                    batch_start=i,
                    batch_size=len(batch_ids)
                )
                
                # Get items for this batch
                items = _get_items_by_type(db, item_type, batch_ids)
                
                # Filter items that need embeddings
                items_needing_embeddings = [
                    item for item in items 
                    if item.embedding_vector is None
                ]
                
                if not items_needing_embeddings:
                    results["skipped"] += len(batch_ids)
                    continue
                
                # Prepare texts for embedding
                embedding_texts = []
                item_mapping = {}
                
                for item in items_needing_embeddings:
                    text = _get_embedding_text(item)
                    if text:
                        embedding_texts.append(text)
                        item_mapping[len(embedding_texts) - 1] = item
                
                if not embedding_texts:
                    results["skipped"] += len(batch_ids)
                    continue
                
                # Generate embeddings for batch
                try:
                    embeddings = _generate_embeddings_batch(embedding_texts)
                    
                    # Store embeddings
                    for idx, embedding in enumerate(embeddings):
                        if idx in item_mapping:
                            item = item_mapping[idx]
                            item.embedding_vector = embedding
                            item.updated_at = datetime.utcnow()
                            results["successful"] += 1
                    
                    db.commit()
                
                except Exception as e:
                    error_msg = f"Batch embedding failed: {str(e)}"
                    logger.exception("batch_embedding_failed", message=error_msg)
                    results["errors"].append(error_msg)
                    results["failed"] += len(items_needing_embeddings)
        
        logger.info("batch_embedding_generation_completed", **results)
        return results
    
    except Exception as e:
        error_msg = f"Batch embedding generation failed: {str(e)}"
        logger.exception("batch_embedding_generation_failed", message=error_msg)
        results["errors"].append(error_msg)
        return results

@embedding_job
def regenerate_all_embeddings(item_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Regenerate embeddings for all items or items of a specific type.
    
    Args:
        item_type: Optional item type to filter by
    
    Returns:
        Dictionary with regeneration results
    """
    logger.info("regenerate_all_embeddings_started", item_type=item_type)
    
    try:
        with get_db_session() as db:
            results = {
                "total_processed": 0,
                "successful": 0,
                "failed": 0,
                "errors": [],
                "regeneration_time": datetime.utcnow().isoformat()
            }
            
            # Get all items that need embeddings
            item_types_to_process = [item_type] if item_type else ["semantic", "episodic", "artifact"]
            
            for current_type in item_types_to_process:
                # Get all items of this type
                items = _get_all_items_by_type(db, current_type)
                
                logger.info(
                    "processing_item_type",
                    item_type=current_type,
                    item_count=len(items)
                )
                
                # Process items in batches
                batch_size = 50
                for i in range(0, len(items), batch_size):
                    batch_items = items[i:i + batch_size]
                    
                    try:
                        # Prepare texts for embedding
                        embedding_texts = []
                        item_mapping = {}
                        
                        for item in batch_items:
                            text = _get_embedding_text(item)
                            if text:
                                embedding_texts.append(text)
                                item_mapping[len(embedding_texts) - 1] = item
                        
                        if not embedding_texts:
                            continue
                        
                        # Generate embeddings
                        embeddings = _generate_embeddings_batch(embedding_texts)
                        
                        # Store embeddings
                        for idx, embedding in enumerate(embeddings):
                            if idx in item_mapping:
                                item = item_mapping[idx]
                                item.embedding_vector = embedding
                                item.updated_at = datetime.utcnow()
                                results["successful"] += 1
                        
                        results["total_processed"] += len(batch_items)
                        db.commit()
                    
                    except Exception as e:
                        error_msg = f"Batch processing failed: {str(e)}"
                        logger.exception("batch_processing_failed", message=error_msg)
                        results["errors"].append(error_msg)
                        results["failed"] += len(batch_items)
            
            logger.info("regenerate_all_embeddings_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Regenerate all embeddings failed: {str(e)}"
        logger.exception("regenerate_all_embeddings_failed", message=error_msg)
        return {
            "error": error_msg,
            "regeneration_time": datetime.utcnow().isoformat()
        }

def _get_item_by_type(db: Session, item_type: str, item_id: str):
    """Get an item by type and ID."""
    if item_type == "semantic":
        return db.query(SemanticItem).filter(SemanticItem.id == item_id).first()
    elif item_type == "episodic":
        return db.query(EpisodicItem).filter(EpisodicItem.id == item_id).first()
    elif item_type == "artifact":
        return db.query(Artifact).filter(Artifact.id == item_id).first()
    return None

def _get_items_by_type(db: Session, item_type: str, item_ids: List[str]):
    """Get multiple items by type and IDs."""
    if item_type == "semantic":
        return db.query(SemanticItem).filter(SemanticItem.id.in_(item_ids)).all()
    elif item_type == "episodic":
        return db.query(EpisodicItem).filter(EpisodicItem.id.in_(item_ids)).all()
    elif item_type == "artifact":
        return db.query(Artifact).filter(Artifact.id.in_(item_ids)).all()
    return []

def _get_all_items_by_type(db: Session, item_type: str):
    """Get all items of a specific type."""
    if item_type == "semantic":
        return db.query(SemanticItem).all()
    elif item_type == "episodic":
        return db.query(EpisodicItem).all()
    elif item_type == "artifact":
        return db.query(Artifact).all()
    return []

def _get_embedding_text(item) -> Optional[str]:
    """Extract text for embedding from an item."""
    if hasattr(item, 'content') and item.content:
        return item.content
    elif hasattr(item, 'description') and item.description:
        return item.description
    elif hasattr(item, 'title') and item.title:
        return item.title
    return None

def _generate_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding for a single text."""
    try:
        response = openai_client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=text
        )
        
        return response.data[0].embedding
    
    except Exception as e:
        logger.exception("single_embedding_generation_failed")
        return None

def _generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts."""
    try:
        response = openai_client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=texts
        )
        
        return [data.embedding for data in response.data]
    
    except Exception as e:
        logger.exception("embedding_generation_error", model=settings.EMBEDDING_MODEL)
        raise
