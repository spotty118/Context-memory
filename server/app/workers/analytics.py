"""
Background jobs for analytics and usage statistics aggregation.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import text, func, desc

from app.db.session import get_db_session
from app.db.models import (
    RequestLog, UsageStats, APIKey, Workspace, ModelCatalog,
    SemanticItem, EpisodicItem, Artifact
)
from app.workers.queue import analytics_job
from app.core.config import settings

logger = structlog.get_logger(__name__)

@analytics_job
def aggregate_daily_usage_stats(date: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregate usage statistics for a specific date.
    
    Args:
        date: Date to aggregate in YYYY-MM-DD format. Defaults to yesterday.
    
    Returns:
        Dictionary with aggregation results
    """
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()
    
    logger.info("daily_usage_aggregation_started", date=target_date.isoformat())
    
    try:
        with get_db_session() as db:
            # Date range for aggregation
            start_time = datetime.combine(target_date, datetime.min.time())
            end_time = datetime.combine(target_date, datetime.max.time())
            
            results = {
                "date": target_date.isoformat(),
                "workspaces_processed": 0,
                "api_keys_processed": 0,
                "models_processed": 0,
                "aggregation_time": datetime.utcnow().isoformat()
            }
            
            # Aggregate by workspace
            workspace_stats = _aggregate_workspace_stats(db, start_time, end_time)
            results["workspaces_processed"] = len(workspace_stats)
            
            # Aggregate by API key
            api_key_stats = _aggregate_api_key_stats(db, start_time, end_time)
            results["api_keys_processed"] = len(api_key_stats)
            
            # Aggregate by model
            model_stats = _aggregate_model_stats(db, start_time, end_time)
            results["models_processed"] = len(model_stats)
            
            # Store aggregated stats
            for stats in workspace_stats + api_key_stats + model_stats:
                existing_stat = db.query(UsageStats).filter(
                    UsageStats.date == target_date,
                    UsageStats.dimension_type == stats["dimension_type"],
                    UsageStats.dimension_value == stats["dimension_value"]
                ).first()
                
                if existing_stat:
                    # Update existing record
                    for key, value in stats.items():
                        if hasattr(existing_stat, key):
                            setattr(existing_stat, key, value)
                    existing_stat.updated_at = datetime.utcnow()
                else:
                    # Create new record
                    usage_stat = UsageStats(**stats)
                    db.add(usage_stat)
            
            db.commit()
            
            logger.info("daily_usage_aggregation_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Daily usage aggregation failed: {str(e)}"
        logger.error("daily_usage_aggregation_failed", error=error_msg)
        return {
            "error": error_msg,
            "date": target_date.isoformat() if 'target_date' in locals() else None,
            "aggregation_time": datetime.utcnow().isoformat()
        }

@analytics_job
def generate_usage_report(
    start_date: str, 
    end_date: str, 
    dimension: str = "workspace"
) -> Dict[str, Any]:
    """
    Generate a comprehensive usage report for a date range.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        dimension: Dimension to report on (workspace, api_key, model)
    
    Returns:
        Dictionary with report data
    """
    logger.info(
        "usage_report_generation_started",
        start_date=start_date,
        end_date=end_date,
        dimension=dimension
    )
    
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        with get_db_session() as db:
            # Get aggregated stats for the period
            stats = db.query(UsageStats).filter(
                UsageStats.date >= start_dt,
                UsageStats.date <= end_dt,
                UsageStats.dimension_type == dimension
            ).all()
            
            # Group by dimension value
            report_data = {}
            for stat in stats:
                dim_value = stat.dimension_value
                if dim_value not in report_data:
                    report_data[dim_value] = {
                        "total_requests": 0,
                        "total_tokens": 0,
                        "total_cost": 0.0,
                        "avg_response_time": 0.0,
                        "error_count": 0,
                        "daily_breakdown": []
                    }
                
                report_data[dim_value]["total_requests"] += stat.request_count
                report_data[dim_value]["total_tokens"] += stat.token_count
                report_data[dim_value]["total_cost"] += stat.cost
                report_data[dim_value]["error_count"] += stat.error_count
                
                # Add daily breakdown
                report_data[dim_value]["daily_breakdown"].append({
                    "date": stat.date.isoformat(),
                    "requests": stat.request_count,
                    "tokens": stat.token_count,
                    "cost": stat.cost,
                    "errors": stat.error_count,
                    "avg_response_time": stat.avg_response_time
                })
            
            # Calculate averages
            for dim_value, data in report_data.items():
                if data["total_requests"] > 0:
                    daily_times = [
                        day["avg_response_time"] 
                        for day in data["daily_breakdown"] 
                        if day["avg_response_time"] > 0
                    ]
                    if daily_times:
                        data["avg_response_time"] = sum(daily_times) / len(daily_times)
            
            results = {
                "start_date": start_date,
                "end_date": end_date,
                "dimension": dimension,
                "report_data": report_data,
                "summary": {
                    "total_dimensions": len(report_data),
                    "period_days": (end_dt - start_dt).days + 1,
                    "grand_total_requests": sum(d["total_requests"] for d in report_data.values()),
                    "grand_total_tokens": sum(d["total_tokens"] for d in report_data.values()),
                    "grand_total_cost": sum(d["total_cost"] for d in report_data.values()),
                    "grand_total_errors": sum(d["error_count"] for d in report_data.values())
                },
                "generation_time": datetime.utcnow().isoformat()
            }
            
            logger.info("usage_report_generation_completed", **results["summary"])
            return results
    
    except Exception as e:
        error_msg = f"Usage report generation failed: {str(e)}"
        logger.error("usage_report_generation_failed", error=error_msg)
        return {
            "error": error_msg,
            "start_date": start_date,
            "end_date": end_date,
            "dimension": dimension,
            "generation_time": datetime.utcnow().isoformat()
        }

@analytics_job
def calculate_context_memory_stats() -> Dict[str, Any]:
    """
    Calculate statistics about context memory usage and performance.
    
    Returns:
        Dictionary with context memory statistics
    """
    logger.info("context_memory_stats_calculation_started")
    
    try:
        with get_db_session() as db:
            # Basic counts
            semantic_count = db.query(SemanticItem).count()
            episodic_count = db.query(EpisodicItem).count()
            artifact_count = db.query(Artifact).count()
            
            # Items with embeddings
            semantic_with_embeddings = db.query(SemanticItem).filter(
                SemanticItem.embedding_vector.isnot(None)
            ).count()
            
            episodic_with_embeddings = db.query(EpisodicItem).filter(
                EpisodicItem.embedding_vector.isnot(None)
            ).count()
            
            artifact_with_embeddings = db.query(Artifact).filter(
                Artifact.embedding_vector.isnot(None)
            ).count()
            
            # Salience statistics
            semantic_avg_salience = db.query(func.avg(SemanticItem.salience)).scalar() or 0
            episodic_avg_salience = db.query(func.avg(EpisodicItem.salience)).scalar() or 0
            
            # Usage statistics
            semantic_usage = db.query(func.sum(SemanticItem.usage_count)).scalar() or 0
            episodic_usage = db.query(func.sum(EpisodicItem.usage_count)).scalar() or 0
            artifact_usage = db.query(func.sum(Artifact.usage_count)).scalar() or 0
            
            # Most accessed items
            top_semantic = db.query(SemanticItem).order_by(
                desc(SemanticItem.usage_count)
            ).limit(10).all()
            
            top_episodic = db.query(EpisodicItem).order_by(
                desc(EpisodicItem.usage_count)
            ).limit(10).all()
            
            top_artifacts = db.query(Artifact).order_by(
                desc(Artifact.usage_count)
            ).limit(10).all()
            
            results = {
                "counts": {
                    "semantic_items": semantic_count,
                    "episodic_items": episodic_count,
                    "artifacts": artifact_count,
                    "total_items": semantic_count + episodic_count + artifact_count
                },
                "embeddings": {
                    "semantic_with_embeddings": semantic_with_embeddings,
                    "episodic_with_embeddings": episodic_with_embeddings,
                    "artifact_with_embeddings": artifact_with_embeddings,
                    "total_with_embeddings": (
                        semantic_with_embeddings + 
                        episodic_with_embeddings + 
                        artifact_with_embeddings
                    ),
                    "embedding_coverage": {
                        "semantic": semantic_with_embeddings / max(semantic_count, 1),
                        "episodic": episodic_with_embeddings / max(episodic_count, 1),
                        "artifact": artifact_with_embeddings / max(artifact_count, 1)
                    }
                },
                "salience": {
                    "semantic_avg": float(semantic_avg_salience),
                    "episodic_avg": float(episodic_avg_salience)
                },
                "usage": {
                    "semantic_total_usage": semantic_usage,
                    "episodic_total_usage": episodic_usage,
                    "artifact_total_usage": artifact_usage,
                    "total_usage": semantic_usage + episodic_usage + artifact_usage
                },
                "top_items": {
                    "semantic": [
                        {
                            "id": item.id,
                            "content": item.content[:100] + "..." if len(item.content) > 100 else item.content,
                            "usage_count": item.usage_count,
                            "salience": item.salience
                        }
                        for item in top_semantic
                    ],
                    "episodic": [
                        {
                            "id": item.id,
                            "content": item.content[:100] + "..." if len(item.content) > 100 else item.content,
                            "usage_count": item.usage_count,
                            "salience": item.salience
                        }
                        for item in top_episodic
                    ],
                    "artifacts": [
                        {
                            "id": item.id,
                            "title": item.title,
                            "usage_count": item.usage_count,
                            "file_size": item.file_size
                        }
                        for item in top_artifacts
                    ]
                },
                "calculation_time": datetime.utcnow().isoformat()
            }
            
            logger.info("context_memory_stats_calculation_completed", **results["counts"])
            return results
    
    except Exception as e:
        error_msg = f"Context memory stats calculation failed: {str(e)}"
        logger.error("context_memory_stats_calculation_failed", error=error_msg)
        return {
            "error": error_msg,
            "calculation_time": datetime.utcnow().isoformat()
        }

def _aggregate_workspace_stats(
    db: Session, 
    start_time: datetime, 
    end_time: datetime
) -> List[Dict[str, Any]]:
    """Aggregate usage stats by workspace."""
    workspaces = db.query(Workspace).all()
    stats = []
    
    for workspace in workspaces:
        # Get request logs for this workspace
        logs = db.query(RequestLog).join(APIKey).filter(
            APIKey.workspace_id == workspace.id,
            RequestLog.created_at >= start_time,
            RequestLog.created_at <= end_time
        ).all()
        
        if logs:
            total_requests = len(logs)
            total_tokens = sum(log.token_count for log in logs if log.token_count)
            total_cost = sum(log.cost for log in logs if log.cost)
            error_count = len([log for log in logs if log.status_code >= 400])
            avg_response_time = sum(log.response_time for log in logs if log.response_time) / len(logs)
            
            stats.append({
                "date": start_time.date(),
                "dimension_type": "workspace",
                "dimension_value": workspace.id,
                "request_count": total_requests,
                "token_count": total_tokens,
                "cost": total_cost,
                "error_count": error_count,
                "avg_response_time": avg_response_time,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
    
    return stats

def _aggregate_api_key_stats(
    db: Session, 
    start_time: datetime, 
    end_time: datetime
) -> List[Dict[str, Any]]:
    """Aggregate usage stats by API key."""
    api_keys = db.query(APIKey).all()
    stats = []
    
    for api_key in api_keys:
        logs = db.query(RequestLog).filter(
            RequestLog.api_key_id == api_key.id,
            RequestLog.created_at >= start_time,
            RequestLog.created_at <= end_time
        ).all()
        
        if logs:
            total_requests = len(logs)
            total_tokens = sum(log.token_count for log in logs if log.token_count)
            total_cost = sum(log.cost for log in logs if log.cost)
            error_count = len([log for log in logs if log.status_code >= 400])
            avg_response_time = sum(log.response_time for log in logs if log.response_time) / len(logs)
            
            stats.append({
                "date": start_time.date(),
                "dimension_type": "api_key",
                "dimension_value": api_key.id,
                "request_count": total_requests,
                "token_count": total_tokens,
                "cost": total_cost,
                "error_count": error_count,
                "avg_response_time": avg_response_time,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
    
    return stats

def _aggregate_model_stats(
    db: Session, 
    start_time: datetime, 
    end_time: datetime
) -> List[Dict[str, Any]]:
    """Aggregate usage stats by model."""
    models = db.query(ModelCatalog).all()
    stats = []
    
    for model in models:
        logs = db.query(RequestLog).filter(
            RequestLog.model_id == model.id,
            RequestLog.created_at >= start_time,
            RequestLog.created_at <= end_time
        ).all()
        
        if logs:
            total_requests = len(logs)
            total_tokens = sum(log.token_count for log in logs if log.token_count)
            total_cost = sum(log.cost for log in logs if log.cost)
            error_count = len([log for log in logs if log.status_code >= 400])
            avg_response_time = sum(log.response_time for log in logs if log.response_time) / len(logs)
            
            stats.append({
                "date": start_time.date(),
                "dimension_type": "model",
                "dimension_value": model.id,
                "request_count": total_requests,
                "token_count": total_tokens,
                "cost": total_cost,
                "error_count": error_count,
                "avg_response_time": avg_response_time,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
    
    return stats

