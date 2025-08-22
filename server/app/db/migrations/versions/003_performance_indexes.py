"""Add performance indexes

Revision ID: 003_performance_indexes
Revises: 002_seed_data
Create Date: 2025-01-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_performance_indexes'
down_revision = '002_seed_data'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add performance-optimized composite indexes."""
    
    # Usage ledger performance indexes
    # Composite index for common API key + date queries
    op.create_index(
        'idx_usage_ledger_api_key_created_at',
        'usage_ledger',
        ['api_key_hash', 'created_at'],
        postgresql_using='btree'
    )
    
    # Composite index for workspace + date queries
    op.create_index(
        'idx_usage_ledger_workspace_created_at',
        'usage_ledger',
        ['workspace_id', 'created_at'],
        postgresql_using='btree'
    )
    
    # Composite index for API key + direction queries
    op.create_index(
        'idx_usage_ledger_api_key_direction',
        'usage_ledger',
        ['api_key_hash', 'direction'],
        postgresql_using='btree'
    )
    
    # Composite index for model + created_at for analytics
    op.create_index(
        'idx_usage_ledger_model_created_at',
        'usage_ledger',
        ['model', 'created_at'],
        postgresql_using='btree'
    )
    
    # Semantic items performance indexes
    # Composite index for thread + status queries
    op.create_index(
        'idx_semantic_items_thread_status',
        'semantic_items',
        ['thread_id', 'status'],
        postgresql_using='btree'
    )
    
    # Composite index for status + kind for accepted items
    op.create_index(
        'idx_semantic_items_status_kind',
        'semantic_items',
        ['status', 'kind'],
        postgresql_using='btree'
    )
    
    # Composite index for thread + created_at for timeline queries
    op.create_index(
        'idx_semantic_items_thread_created_at',
        'semantic_items',
        ['thread_id', 'created_at'],
        postgresql_using='btree'
    )
    
    # Episodic items performance indexes
    # Composite index for thread + created_at
    op.create_index(
        'idx_episodic_items_thread_created_at',
        'episodic_items',
        ['thread_id', 'created_at'],
        postgresql_using='btree'
    )
    
    # Composite index for thread + kind
    op.create_index(
        'idx_episodic_items_thread_kind',
        'episodic_items',
        ['thread_id', 'kind'],
        postgresql_using='btree'
    )
    
    # API keys performance indexes
    # Index for workspace + active status
    op.create_index(
        'idx_api_keys_workspace_active',
        'api_keys',
        ['workspace_id', 'active'],
        postgresql_using='btree'
    )
    
    # Model catalog performance indexes
    # Composite index for provider + status
    op.create_index(
        'idx_model_catalog_provider_status',
        'model_catalog',
        ['provider', 'status'],
        postgresql_using='btree'
    )
    
    # Composite index for embeddings + status
    op.create_index(
        'idx_model_catalog_embeddings_status',
        'model_catalog',
        ['embeddings', 'status'],
        postgresql_using='btree'
    )
    
    # Threads performance indexes
    # Index for workspace queries
    op.create_index(
        'idx_threads_workspace_created_at',
        'threads',
        ['workspace_id', 'created_at'],
        postgresql_using='btree'
    )
    
    # Embedding records performance indexes (if table exists)
    try:
        op.create_index(
            'idx_embedding_records_thread_created_at',
            'embedding_records',
            ['thread_id', 'created_at'],
            postgresql_using='btree'
        )
    except Exception:
        # Table might not exist yet, skip
        pass


def downgrade() -> None:
    """Remove performance indexes."""
    
    # Remove usage ledger indexes
    op.drop_index('idx_usage_ledger_api_key_created_at', 'usage_ledger')
    op.drop_index('idx_usage_ledger_workspace_created_at', 'usage_ledger')
    op.drop_index('idx_usage_ledger_api_key_direction', 'usage_ledger')
    op.drop_index('idx_usage_ledger_model_created_at', 'usage_ledger')
    
    # Remove semantic items indexes
    op.drop_index('idx_semantic_items_thread_status', 'semantic_items')
    op.drop_index('idx_semantic_items_status_kind', 'semantic_items')
    op.drop_index('idx_semantic_items_thread_created_at', 'semantic_items')
    
    # Remove episodic items indexes
    op.drop_index('idx_episodic_items_thread_created_at', 'episodic_items')
    op.drop_index('idx_episodic_items_thread_kind', 'episodic_items')
    
    # Remove API keys indexes
    op.drop_index('idx_api_keys_workspace_active', 'api_keys')
    
    # Remove model catalog indexes
    op.drop_index('idx_model_catalog_provider_status', 'model_catalog')
    op.drop_index('idx_model_catalog_embeddings_status', 'model_catalog')
    
    # Remove threads indexes
    op.drop_index('idx_threads_workspace_created_at', 'threads')
    
    # Remove embedding records indexes (if they exist)
    try:
        op.drop_index('idx_embedding_records_thread_created_at', 'embedding_records')
    except Exception:
        # Index might not exist, skip
        pass