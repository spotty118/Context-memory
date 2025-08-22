"""
Background jobs for cleanup and maintenance tasks.
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from app.db.session import get_db_session
from app.db.models import (
    SemanticItem, EpisodicItem, Artifact, RequestLog, 
    UsageStats, APIKey, Workspace
)
from app.workers.queue import cleanup_job
from app.core.config import settings

logger = structlog.get_logger(__name__)

@cleanup_job
def cleanup_old_context_items(days_old: int = 30) -> Dict[str, Any]:
    """
    Clean up old context memory items that haven't been accessed recently.
    
    Args:
        days_old: Number of days since last access to consider for cleanup
    
    Returns:
        Dictionary with cleanup results
    """
    logger.info("context_cleanup_started", days_old=days_old)
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        with get_db_session() as db:
            results = {
                "semantic_items_removed": 0,
                "episodic_items_removed": 0,
                "artifacts_removed": 0,
                "total_removed": 0,
                "cleanup_time": datetime.utcnow().isoformat()
            }
            
            # Clean up old semantic items
            old_semantic = db.query(SemanticItem).filter(
                SemanticItem.last_accessed_at < cutoff_date,
                SemanticItem.salience < 0.1  # Only remove low-salience items
            ).all()
            
            for item in old_semantic:
                db.delete(item)
                results["semantic_items_removed"] += 1
            
            # Clean up old episodic items
            old_episodic = db.query(EpisodicItem).filter(
                EpisodicItem.last_accessed_at < cutoff_date,
                EpisodicItem.salience < 0.1
            ).all()
            
            for item in old_episodic:
                db.delete(item)
                results["episodic_items_removed"] += 1
            
            # Clean up old artifacts (be more conservative)
            very_old_date = datetime.utcnow() - timedelta(days=days_old * 2)
            old_artifacts = db.query(Artifact).filter(
                Artifact.last_accessed_at < very_old_date,
                Artifact.usage_count == 0
            ).all()
            
            for item in old_artifacts:
                db.delete(item)
                results["artifacts_removed"] += 1
            
            results["total_removed"] = (
                results["semantic_items_removed"] + 
                results["episodic_items_removed"] + 
                results["artifacts_removed"]
            )
            
            db.commit()
            
            logger.info("context_cleanup_completed", **results)
            return results
        
    except Exception as e:
        error_msg = f"Context cleanup failed: {str(e)}"
        logger.exception("context_cleanup_failed", message=error_msg)
        return {
            "error": error_msg,
            "cleanup_time": datetime.utcnow().isoformat()
        }

@cleanup_job
def cleanup_old_request_logs(days_old: int = 90) -> Dict[str, Any]:
    """
    Clean up old request logs to prevent database bloat.
    
    Args:
        days_old: Number of days of logs to keep
    
    Returns:
        Dictionary with cleanup results
    """
    logger.info("request_log_cleanup_started", days_old=days_old)
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        with get_db_session() as db:
            # Count logs to be deleted
            logs_to_delete = db.query(RequestLog).filter(
                RequestLog.created_at < cutoff_date
            ).count()
            
            # Delete old logs in batches to avoid locking
            batch_size = 1000
            total_deleted = 0
            
            while True:
                batch = db.query(RequestLog).filter(
                    RequestLog.created_at < cutoff_date
                ).limit(batch_size).all()
                
                if not batch:
                    break
                
                for log in batch:
                    db.delete(log)
                
                db.commit()
                total_deleted += len(batch)
                
                logger.info("request_log_batch_deleted", batch_size=len(batch))
            
            results = {
                "logs_removed": total_deleted,
                "cleanup_time": datetime.utcnow().isoformat()
            }
            
            logger.info("request_log_cleanup_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Request log cleanup failed: {str(e)}"
        logger.exception("request_log_cleanup_failed", message=error_msg)
        return {
            "error": error_msg,
            "cleanup_time": datetime.utcnow().isoformat()
        }

@cleanup_job
def cleanup_expired_api_keys() -> Dict[str, Any]:
    """
    Clean up expired API keys and their associated data.
    
    Returns:
        Dictionary with cleanup results
    """
    logger.info("expired_api_key_cleanup_started")
    
    try:
        with get_db_session() as db:
            # Find expired API keys
            expired_keys = db.query(APIKey).filter(
                APIKey.expires_at < datetime.utcnow(),
                APIKey.status != "deleted"
            ).all()
            
            results = {
                "expired_keys_found": len(expired_keys),
                "keys_deleted": 0,
                "cleanup_time": datetime.utcnow().isoformat()
            }
            
            for key in expired_keys:
                # Mark as deleted instead of actually deleting for audit trail
                key.status = "deleted"
                key.updated_at = datetime.utcnow()
                results["keys_deleted"] += 1
            
            db.commit()
            
            logger.info("expired_api_key_cleanup_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Expired API key cleanup failed: {str(e)}"
        logger.exception("expired_api_key_cleanup_failed", message=error_msg)
        return {
            "error": error_msg,
            "cleanup_time": datetime.utcnow().isoformat()
        }

@cleanup_job
def vacuum_database() -> Dict[str, Any]:
    """
    Run database maintenance operations to optimize performance.
    
    Returns:
        Dictionary with maintenance results
    """
    logger.info("database_vacuum_started")
    
    try:
        with get_db_session() as db:
            # Get database statistics before vacuum
            stats_before = _get_database_stats(db)
            
            # Run VACUUM ANALYZE on main tables
            tables_to_vacuum = [
                "semantic_items",
                "episodic_items", 
                "artifacts",
                "request_logs",
                "usage_stats",
                "api_keys"
            ]
            
            for table in tables_to_vacuum:
                try:
                    db.execute(text(f"VACUUM ANALYZE {table}"))
                    logger.info("table_vacuumed", table=table)
                except Exception as e:
                    logger.exception("table_vacuum_failed", table=table)
            
            # Get statistics after vacuum
            stats_after = _get_database_stats(db)
            
            results = {
                "tables_vacuumed": len(tables_to_vacuum),
                "stats_before": stats_before,
                "stats_after": stats_after,
                "vacuum_time": datetime.utcnow().isoformat()
            }
            
            logger.info("database_vacuum_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Database vacuum failed: {str(e)}"
        logger.exception("database_vacuum_failed", message=error_msg)
        return {
            "error": error_msg,
            "vacuum_time": datetime.utcnow().isoformat()
        }

@cleanup_job
def optimize_embeddings_index() -> Dict[str, Any]:
    """
    Optimize the vector embeddings index for better performance.
    
    Returns:
        Dictionary with optimization results
    """
    logger.info("embeddings_index_optimization_started")
    
    try:
        with get_db_session() as db:
            # Reindex vector columns for better performance
            vector_tables = [
                ("semantic_items", "embedding_vector"),
                ("episodic_items", "embedding_vector"),
                ("artifacts", "embedding_vector")
            ]
            
            results = {
                "indexes_optimized": 0,
                "optimization_time": datetime.utcnow().isoformat()
            }
            
            for table, column in vector_tables:
                try:
                    # Check if index exists and rebuild if necessary
                    index_name = f"idx_{table}_{column}"
                    
                    # Drop and recreate index for optimization
                    db.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
                    db.execute(text(f"""
                        CREATE INDEX {index_name} ON {table} 
                        USING ivfflat ({column} vector_cosine_ops) 
                        WITH (lists = 100)
                    """))
                    
                    results["indexes_optimized"] += 1
                    logger.info("vector_index_optimized", table=table, column=column)
                
                except Exception as e:
                    logger.exception("vector_index_optimization_failed", 
                               table=table, column=column)
            
            logger.info("embeddings_index_optimization_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Embeddings index optimization failed: {str(e)}"
        logger.exception("embeddings_index_optimization_failed", message=error_msg)
        return {
            "error": error_msg,
            "optimization_time": datetime.utcnow().isoformat()
        }

@cleanup_job
def archive_old_usage_stats(days_old: int = 365) -> Dict[str, Any]:
    """
    Archive old usage statistics to prevent table bloat.
    
    Args:
        days_old: Number of days of stats to keep in main table
    
    Returns:
        Dictionary with archival results
    """
    logger.info("usage_stats_archival_started", days_old=days_old)
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        with get_db_session() as db:
            # Count stats to be archived
            stats_to_archive = db.query(UsageStats).filter(
                UsageStats.created_at < cutoff_date
            ).count()
            
            # Create archive table if it doesn't exist
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS usage_stats_archive (
                    LIKE usage_stats INCLUDING ALL
                )
            """))
            
            # Move old stats to archive table
            db.execute(text("""
                INSERT INTO usage_stats_archive 
                SELECT * FROM usage_stats 
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            # Delete from main table
            db.execute(text("""
                DELETE FROM usage_stats 
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            results = {
                "stats_archived": stats_to_archive,
                "archival_time": datetime.utcnow().isoformat()
            }
            
            logger.info("usage_stats_archival_completed", **results)
            return results
    
    except Exception as e:
        error_msg = f"Usage stats archival failed: {str(e)}"
        logger.exception("usage_stats_archival_failed", message=error_msg)
        return {
            "error": error_msg,
            "archival_time": datetime.utcnow().isoformat()
        }

def _get_database_stats(db: Session) -> Dict[str, Any]:
    """Get basic database statistics."""
    try:
        # Get table sizes
        result = db.execute(text("""
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        """)).fetchall()
        
        return {
            "table_sizes": [
                {
                    "table": row.tablename,
                    "size": row.size,
                    "size_bytes": row.size_bytes
                }
                for row in result
            ]
        }
    
    except Exception as e:
        logger.exception("database_stats_failed")
        return {"error": str(e)}

