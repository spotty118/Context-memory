"""
Supabase client configuration and setup with circuit breaker protection.
"""
import os
from typing import Optional
from supabase import create_client, Client
from postgrest import APIError
import structlog

from app.core.config import settings
from app.core.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig

logger = structlog.get_logger()

class SupabaseClient:
    """Singleton Supabase client wrapper."""
    
    _client: Optional[Client] = None
    
    @classmethod
    def get_client(cls) -> Client:
        """Get or create Supabase client instance."""
        if cls._client is None:
            try:
                cls._client = create_client(
                    supabase_url=settings.SUPABASE_URL,
                    supabase_key=settings.SUPABASE_ANON_KEY
                )
                logger.info("supabase_client_initialized")
            except Exception as e:
                logger.exception("supabase_client_init_failed")
                raise
        return cls._client
    
    @classmethod
    def get_service_client(cls) -> Client:
        """Get Supabase client with service role key for admin operations."""
        try:
            return create_client(
                supabase_url=settings.SUPABASE_URL,
                supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY
            )
        except Exception as e:
            logger.exception("supabase_service_client_init_failed")
            raise

# Convenience function
def get_supabase() -> Client:
    """Get the main Supabase client."""
    return SupabaseClient.get_client()

def get_supabase_admin() -> Client:
    """Get Supabase client with admin privileges."""
    return SupabaseClient.get_service_client()

# Database table constants
class Tables:
    """Supabase table names."""
    API_KEYS = "api_keys"
    MODELS = "models"
    CONTEXTS = "contexts" 
    CONTEXT_ITEMS = "context_items"
    EMBEDDINGS = "embeddings"
    USAGE_STATS = "usage_stats"
    USERS = "users"
    THREADS = "threads"
    FEEDBACK = "feedback"
    WORKING_SETS = "working_sets"
    CACHE_ENTRIES = "cache_entries"

# Helper functions for common operations with circuit breaker protection
async def insert_record(table: str, data: dict) -> dict:
    """Insert a record into Supabase table with circuit breaker protection."""
    circuit_breaker = get_circuit_breaker("supabase", CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=30.0,
        success_threshold=3,
        timeout=10.0,
        expected_exception=Exception
    ))
    
    async def _insert():
        response = get_supabase().table(table).insert(data).execute()
        if response.data:
            return response.data[0]
        raise APIError("Insert failed")
    
    try:
        return await circuit_breaker.call(_insert)
    except Exception as e:
        logger.exception("supabase_insert_failed", table=table)
        raise

async def update_record(table: str, record_id: str, data: dict) -> dict:
    """Update a record in Supabase table with circuit breaker protection."""
    circuit_breaker = get_circuit_breaker("supabase")
    
    async def _update():
        response = get_supabase().table(table).update(data).eq("id", record_id).execute()
        if response.data:
            return response.data[0]
        raise APIError("Update failed")
    
    try:
        return await circuit_breaker.call(_update)
    except Exception as e:
        logger.exception("supabase_update_failed", table=table, record_id=record_id)
        raise

async def delete_record(table: str, record_id: str) -> bool:
    """Delete a record from Supabase table with circuit breaker protection."""
    circuit_breaker = get_circuit_breaker("supabase")
    
    async def _delete():
        response = get_supabase().table(table).delete().eq("id", record_id).execute()
        return True
    
    try:
        return await circuit_breaker.call(_delete)
    except Exception as e:
        logger.exception("supabase_delete_failed", table=table, record_id=record_id)
        return False

async def get_record(table: str, record_id: str) -> Optional[dict]:
    """Get a single record by ID with circuit breaker protection."""
    circuit_breaker = get_circuit_breaker("supabase")
    
    async def _get():
        response = get_supabase().table(table).select("*").eq("id", record_id).execute()
        if response.data:
            return response.data[0]
        return None
    
    try:
        return await circuit_breaker.call(_get)
    except Exception as e:
        logger.exception("supabase_get_failed", table=table, record_id=record_id)
        return None

async def list_records(table: str, limit: int = 100, offset: int = 0, filters: Optional[dict] = None) -> list:
    """List records from a table with optional filters and circuit breaker protection."""
    circuit_breaker = get_circuit_breaker("supabase")
    
    async def _list():
        query = get_supabase().table(table).select("*")
        
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        
        response = query.range(offset, offset + limit - 1).execute()
        return response.data or []
    
    try:
        return await circuit_breaker.call(_list)
    except Exception as e:
        logger.exception("supabase_list_failed", table=table)
        return []
