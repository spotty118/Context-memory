"""
Usage tracking and quota enforcement module.
"""
import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy import select, func, and_
from fastapi import HTTPException
import structlog

from app.core.config import settings
from app.db.session import get_db
from app.db.models import APIKey, UsageLedger, ModelCatalog


logger = structlog.get_logger(__name__)


async def check_daily_quota(api_key: APIKey) -> None:
    """
    Check if API key has exceeded daily token quota.
    
    Args:
        api_key: API key record
        
    Raises:
        HTTPException: If daily quota exceeded
    """
    daily_quota = api_key.daily_quota_tokens or settings.DEFAULT_DAILY_QUOTA_TOKENS
    
    # Get today's usage
    today = datetime.date.today()
    today_start = datetime.datetime.combine(today, datetime.time.min)
    today_end = datetime.datetime.combine(today, datetime.time.max)
    
    async with get_db() as db:
        # Sum tokens used today
        result = await db.execute(
            select(func.sum(UsageLedger.tokens))
            .where(
                and_(
                    UsageLedger.api_key_hash == api_key.key_hash,
                    UsageLedger.created_at >= today_start,
                    UsageLedger.created_at <= today_end
                )
            )
        )
        
        tokens_used_today = result.scalar() or 0
        
        if tokens_used_today >= daily_quota:
            logger.warning(
                "daily_quota_exceeded",
                workspace_id=api_key.workspace_id,
                key_name=api_key.name,
                tokens_used=tokens_used_today,
                daily_quota=daily_quota,
            )
            
            raise HTTPException(
                status_code=429,
                detail=f"Daily quota exceeded. Used {tokens_used_today}/{daily_quota} tokens today.",
                headers={
                    "X-Quota-Limit": str(daily_quota),
                    "X-Quota-Used": str(tokens_used_today),
                    "X-Quota-Remaining": str(max(0, daily_quota - tokens_used_today)),
                    "X-Quota-Reset": str(int((today_start + datetime.timedelta(days=1)).timestamp())),
                }
            )
        
        logger.debug(
            "daily_quota_check_passed",
            workspace_id=api_key.workspace_id,
            key_name=api_key.name,
            tokens_used=tokens_used_today,
            daily_quota=daily_quota,
            remaining=daily_quota - tokens_used_today,
        )


async def record_usage(
    api_key: APIKey,
    model_id: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    embedding_tokens: int = 0,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Record token usage in the usage ledger.
    
    Args:
        api_key: API key record
        model_id: Model used
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        embedding_tokens: Number of embedding tokens
        metadata: Additional metadata to store
    """
    async with get_db() as db:
        # Get model pricing information
        model = await db.get(ModelCatalog, model_id)
        
        # Calculate costs
        prompt_cost = Decimal('0')
        completion_cost = Decimal('0')
        
        if model and model.input_price_per_1k:
            prompt_cost = Decimal(str(model.input_price_per_1k)) * Decimal(str(prompt_tokens)) / Decimal('1000')
        
        if model and model.output_price_per_1k:
            completion_cost = Decimal(str(model.output_price_per_1k)) * Decimal(str(completion_tokens)) / Decimal('1000')
        
        # For embeddings, use input pricing
        embedding_cost = Decimal('0')
        if embedding_tokens and model and model.input_price_per_1k:
            embedding_cost = Decimal(str(model.input_price_per_1k)) * Decimal(str(embedding_tokens)) / Decimal('1000')
        
        # Record prompt tokens
        if prompt_tokens > 0:
            prompt_entry = UsageLedger(
                api_key_hash=api_key.key_hash,
                workspace_id=api_key.workspace_id,
                model=model_id,
                direction='prompt',
                tokens=prompt_tokens,
                cost_usd=prompt_cost,
                metadata=metadata,
            )
            db.add(prompt_entry)
        
        # Record completion tokens
        if completion_tokens > 0:
            completion_entry = UsageLedger(
                api_key_hash=api_key.key_hash,
                workspace_id=api_key.workspace_id,
                model=model_id,
                direction='completion',
                tokens=completion_tokens,
                cost_usd=completion_cost,
                metadata=metadata,
            )
            db.add(completion_entry)
        
        # Record embedding tokens
        if embedding_tokens > 0:
            embedding_entry = UsageLedger(
                api_key_hash=api_key.key_hash,
                workspace_id=api_key.workspace_id,
                model=model_id,
                direction='embedding',
                tokens=embedding_tokens,
                cost_usd=embedding_cost,
                metadata=metadata,
            )
            db.add(embedding_entry)
        
        await db.commit()
        
        total_tokens = prompt_tokens + completion_tokens + embedding_tokens
        total_cost = prompt_cost + completion_cost + embedding_cost
        
        logger.info(
            "usage_recorded",
            workspace_id=api_key.workspace_id,
            key_name=api_key.name,
            model=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            embedding_tokens=embedding_tokens,
            total_tokens=total_tokens,
            total_cost=float(total_cost),
        )


async def get_usage_stats(
    api_key: APIKey,
    start_date: Optional[datetime.date] = None,
    end_date: Optional[datetime.date] = None
) -> Dict[str, Any]:
    """
    Get usage statistics for an API key.
    
    Args:
        api_key: API key record
        start_date: Start date for stats (default: 30 days ago)
        end_date: End date for stats (default: today)
        
    Returns:
        dict: Usage statistics
    """
    if not start_date:
        start_date = datetime.date.today() - datetime.timedelta(days=30)
    if not end_date:
        end_date = datetime.date.today()
    
    start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max)
    
    async with get_db() as db:
        # Total usage in period
        total_result = await db.execute(
            select(
                func.sum(UsageLedger.tokens).label('total_tokens'),
                func.sum(UsageLedger.cost_usd).label('total_cost'),
                func.count(UsageLedger.id).label('total_requests')
            )
            .where(
                and_(
                    UsageLedger.api_key_hash == api_key.key_hash,
                    UsageLedger.created_at >= start_datetime,
                    UsageLedger.created_at <= end_datetime
                )
            )
        )
        
        total_stats = total_result.first()
        
        # Usage by model
        model_result = await db.execute(
            select(
                UsageLedger.model,
                func.sum(UsageLedger.tokens).label('tokens'),
                func.sum(UsageLedger.cost_usd).label('cost'),
                func.count(UsageLedger.id).label('requests')
            )
            .where(
                and_(
                    UsageLedger.api_key_hash == api_key.key_hash,
                    UsageLedger.created_at >= start_datetime,
                    UsageLedger.created_at <= end_datetime
                )
            )
            .group_by(UsageLedger.model)
            .order_by(func.sum(UsageLedger.tokens).desc())
        )
        
        model_stats = []
        for row in model_result:
            model_stats.append({
                'model': row.model,
                'tokens': int(row.tokens or 0),
                'cost': float(row.cost or 0),
                'requests': int(row.requests or 0),
            })
        
        # Daily usage in period
        daily_result = await db.execute(
            select(
                func.date(UsageLedger.created_at).label('date'),
                func.sum(UsageLedger.tokens).label('tokens'),
                func.sum(UsageLedger.cost_usd).label('cost'),
                func.count(UsageLedger.id).label('requests')
            )
            .where(
                and_(
                    UsageLedger.api_key_hash == api_key.key_hash,
                    UsageLedger.created_at >= start_datetime,
                    UsageLedger.created_at <= end_datetime
                )
            )
            .group_by(func.date(UsageLedger.created_at))
            .order_by(func.date(UsageLedger.created_at))
        )
        
        daily_stats = []
        for row in daily_result:
            daily_stats.append({
                'date': row.date.isoformat(),
                'tokens': int(row.tokens or 0),
                'cost': float(row.cost or 0),
                'requests': int(row.requests or 0),
            })
        
        return {
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
            },
            'total': {
                'tokens': int(total_stats.total_tokens or 0),
                'cost': float(total_stats.total_cost or 0),
                'requests': int(total_stats.total_requests or 0),
            },
            'by_model': model_stats,
            'daily': daily_stats,
        }


async def get_daily_quota_status(api_key: APIKey) -> Dict[str, Any]:
    """
    Get current daily quota status for an API key.
    
    Args:
        api_key: API key record
        
    Returns:
        dict: Daily quota status
    """
    daily_quota = api_key.daily_quota_tokens or settings.DEFAULT_DAILY_QUOTA_TOKENS
    
    # Get today's usage
    today = datetime.date.today()
    today_start = datetime.datetime.combine(today, datetime.time.min)
    today_end = datetime.datetime.combine(today, datetime.time.max)
    
    async with get_db() as db:
        result = await db.execute(
            select(func.sum(UsageLedger.tokens))
            .where(
                and_(
                    UsageLedger.api_key_hash == api_key.key_hash,
                    UsageLedger.created_at >= today_start,
                    UsageLedger.created_at <= today_end
                )
            )
        )
        
        tokens_used_today = result.scalar() or 0
        
        return {
            'quota': daily_quota,
            'used': tokens_used_today,
            'remaining': max(0, daily_quota - tokens_used_today),
            'reset_at': int((today_start + datetime.timedelta(days=1)).timestamp()),
            'percentage_used': (tokens_used_today / daily_quota * 100) if daily_quota > 0 else 0,
        }

