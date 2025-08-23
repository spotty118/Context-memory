"""
Context Memory feedback API endpoint.
"""
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import structlog

from app.core.security import get_api_key
from app.db.session import get_db_dependency
from app.db.models import APIKey, UsageStats, SemanticItem, EpisodicItem

router = APIRouter()
logger = structlog.get_logger(__name__)


class FeedbackRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID")
    item_id: str = Field(..., description="Item ID being rated")
    feedback_type: str = Field(..., description="Type of feedback (useful, not_useful, click, reference)")
    value: Optional[float] = Field(None, description="Numeric feedback value")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional feedback metadata")


class FeedbackResponse(BaseModel):
    success: bool
    message: str


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db_dependency)
):
    """
    Submit feedback to update usage/salience/rehearsals.
    
    Updates:
    - Usage statistics (clicks, references)
    - Salience scores
    - Rehearsal schedules
    - Event log
    """
    logger.info(
        "feedback_submitted",
        workspace_id=api_key.workspace_id,
        thread_id=request.thread_id,
        item_id=request.item_id,
        feedback_type=request.feedback_type,
        value=request.value,
    )
    
    try:
        # Update usage statistics
        await _update_usage_stats(
            request.item_id,
            request.thread_id,
            request.feedback_type,
            db
        )
        
        # Update salience based on feedback
        salience_delta = await _calculate_salience_delta(
            request.feedback_type, 
            request.value
        )
        
        if salience_delta != 0:
            await _update_item_salience(
                request.item_id, 
                salience_delta, 
                db
            )
        
        # Schedule rehearsal if needed
        if request.feedback_type in ['useful', 'reference']:
            await _schedule_rehearsal(request.item_id, request.thread_id, db)
        
        # Commit all changes
        await db.commit()
        
        logger.info(
            "feedback_processed",
            workspace_id=api_key.workspace_id,
            item_id=request.item_id,
            feedback_type=request.feedback_type,
            salience_delta=salience_delta,
        )
        
        return FeedbackResponse(
            success=True,
            message=f"Feedback recorded for {request.item_id}"
        )
    
    except Exception as e:
        await db.rollback()
        logger.error(
            "feedback_processing_failed",
            workspace_id=api_key.workspace_id,
            item_id=request.item_id,
            error=str(e)
        )
        
        return FeedbackResponse(
            success=False,
            message=f"Failed to process feedback: {str(e)}"
        )


async def _update_usage_stats(
    item_id: str,
    thread_id: str,
    feedback_type: str,
    db: AsyncSession
) -> None:
    """Update usage statistics for the item."""
    # Get or create usage stats
    result = await db.execute(
        select(UsageStats).where(UsageStats.item_id == item_id)
    )
    stats = result.scalar_one_or_none()
    
    if not stats:
        stats = UsageStats(
            item_id=item_id,
            thread_id=thread_id,
            clicks=0,
            references=0,
            last_used_at=datetime.utcnow()
        )
        db.add(stats)
    
    # Update based on feedback type
    if feedback_type == 'click':
        stats.clicks += 1
    elif feedback_type == 'reference':
        stats.references += 1
    elif feedback_type in ['useful', 'not_useful']:
        # These don't directly map to usage stats but update last_accessed
        pass
    
    stats.last_used_at = datetime.utcnow()
    
    logger.debug(
        "usage_stats_updated",
        item_id=item_id,
        workspace_id=None,
        feedback_type=feedback_type,
        clicks=stats.clicks,
        references=stats.references,
        expansions=0,
    )


async def _calculate_salience_delta(feedback_type: str, value: Optional[float]) -> float:
    """Calculate salience adjustment based on feedback."""
    # Feedback type to salience delta mapping
    salience_adjustments = {
        'useful': 0.1,
        'not_useful': -0.1,
        'click': 0.02,
        'reference': 0.05,
    }
    
    base_delta = salience_adjustments.get(feedback_type, 0.0)
    
    # Apply value multiplier if provided
    if value is not None:
        # Normalize value to -1 to 1 range if needed
        if feedback_type in ['useful', 'not_useful']:
            # Value should be 0-1 for usefulness ratings
            normalized_value = max(-1.0, min(1.0, (value * 2) - 1))  # Convert 0-1 to -1-1
            base_delta *= abs(normalized_value)
            if normalized_value < 0:
                base_delta *= -1
    
    return base_delta


async def _update_item_salience(item_id: str, salience_delta: float, db: AsyncSession) -> None:
    """Update salience score for semantic or episodic item."""
    # Try semantic item first
    result = await db.execute(select(SemanticItem).where(SemanticItem.id == item_id))
    semantic_item = result.scalar_one_or_none()
    if semantic_item:
        old_salience = semantic_item.salience
        new_salience = max(0.0, min(1.0, old_salience + salience_delta))  # Clamp to 0-1
        semantic_item.salience = new_salience
        semantic_item.updated_at = datetime.utcnow()
        
        logger.debug(
            "semantic_salience_updated",
            item_id=item_id,
            old_salience=old_salience,
            new_salience=new_salience,
            delta=salience_delta,
        )
        return
    
    # Try episodic item
    result = await db.execute(select(EpisodicItem).where(EpisodicItem.id == item_id))
    episodic_item = result.scalar_one_or_none()
    if episodic_item:
        old_salience = episodic_item.salience
        new_salience = max(0.0, min(1.0, old_salience + salience_delta))  # Clamp to 0-1
        episodic_item.salience = new_salience
        
        logger.debug(
            "episodic_salience_updated",
            item_id=item_id,
            old_salience=old_salience,
            new_salience=new_salience,
            delta=salience_delta,
        )
        return
    
    # Item not found - log warning
    logger.warning(
        "salience_update_item_not_found",
        item_id=item_id,
        salience_delta=salience_delta,
    )


async def _schedule_rehearsal(item_id: str, thread_id: str, db: AsyncSession) -> None:
    """Schedule rehearsal for the item using spaced repetition algorithm."""
    from app.core.redis import get_redis_client
    from datetime import timedelta
    import math
    
    try:
        # Get Redis client for scheduling
        redis_client = await get_redis_client()
        
        # Get current rehearsal count for this item
        rehearsal_key = f"rehearsal:{item_id}:count"
        rehearsal_count = int(await redis_client.get(rehearsal_key) or 0)
        
        # Spaced repetition intervals (in hours): 1, 4, 12, 24, 72, 168 (1 week), 720 (1 month)
        intervals = [1, 4, 12, 24, 72, 168, 720]
        
        # Calculate next rehearsal time
        if rehearsal_count < len(intervals):
            next_interval_hours = intervals[rehearsal_count]
        else:
            # For items rehearsed many times, use exponential backoff
            next_interval_hours = 720 * (2 ** (rehearsal_count - len(intervals) + 1))
            # Cap at 6 months
            next_interval_hours = min(next_interval_hours, 4320)
        
        next_rehearsal_time = datetime.utcnow() + timedelta(hours=next_interval_hours)
        
        # Store rehearsal schedule in Redis sorted set
        rehearsal_queue_key = f"rehearsal_queue:{thread_id}"
        rehearsal_score = next_rehearsal_time.timestamp()
        
        rehearsal_data = {
            "item_id": item_id,
            "thread_id": thread_id,
            "scheduled_at": next_rehearsal_time.isoformat(),
            "rehearsal_count": rehearsal_count + 1,
            "interval_hours": next_interval_hours
        }
        
        # Add to sorted set with timestamp as score
        await redis_client.zadd(
            rehearsal_queue_key, 
            {f"{item_id}:{rehearsal_count + 1}": rehearsal_score}
        )
        
        # Store rehearsal metadata
        rehearsal_meta_key = f"rehearsal:{item_id}:{rehearsal_count + 1}:meta"
        await redis_client.setex(
            rehearsal_meta_key, 
            int(next_interval_hours * 3600 * 2),  # Store for 2x the interval
            json.dumps(rehearsal_data)
        )
        
        # Update rehearsal count
        await redis_client.incr(rehearsal_key)
        await redis_client.expire(rehearsal_key, int(next_interval_hours * 3600 * 2))
        
        logger.info(
            "rehearsal_scheduled",
            item_id=item_id,
            thread_id=thread_id,
            next_rehearsal=next_rehearsal_time.isoformat(),
            interval_hours=next_interval_hours,
            rehearsal_count=rehearsal_count + 1
        )
        
    except Exception as e:
        logger.exception(
            "rehearsal_scheduling_error",
            item_id=item_id,
            thread_id=thread_id
        )

