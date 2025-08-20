"""Initial database schema

Revision ID: 001
Revises: 
Create Date: 2025-01-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Create model_catalog table
    op.create_table('model_catalog',
        sa.Column('model_id', sa.Text(), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.Column('context_window', sa.Integer(), nullable=True),
        sa.Column('input_price_per_1k', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('output_price_per_1k', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('supports_tools', sa.Boolean(), nullable=True),
        sa.Column('supports_vision', sa.Boolean(), nullable=True),
        sa.Column('supports_json_mode', sa.Boolean(), nullable=True),
        sa.Column('embeddings', sa.Boolean(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("status IN ('active','deprecated','unavailable')", name='model_catalog_status_check'),
        sa.PrimaryKeyConstraint('model_id')
    )
    op.create_index('idx_model_catalog_embeddings', 'model_catalog', ['embeddings'], unique=False)
    op.create_index('idx_model_catalog_provider', 'model_catalog', ['provider'], unique=False)
    op.create_index('idx_model_catalog_status', 'model_catalog', ['status'], unique=False)

    # Create settings table
    op.create_table('settings',
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )

    # Create api_keys table
    op.create_table('api_keys',
        sa.Column('key_hash', sa.Text(), nullable=False),
        sa.Column('workspace_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('daily_quota_tokens', sa.Integer(), nullable=True),
        sa.Column('rpm_limit', sa.Integer(), nullable=True),
        sa.Column('model_allowlist', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('model_blocklist', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('default_model', sa.Text(), nullable=True),
        sa.Column('default_embed_model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('key_hash')
    )
    op.create_index('idx_api_keys_active', 'api_keys', ['active'], unique=False)
    op.create_index('idx_api_keys_workspace', 'api_keys', ['workspace_id'], unique=False)

    # Create usage_ledger table
    op.create_table('usage_ledger',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('api_key_hash', sa.Text(), nullable=False),
        sa.Column('workspace_id', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('direction', sa.Text(), nullable=False),
        sa.Column('tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("direction IN ('prompt','completion','embedding')", name='usage_ledger_direction_check'),
        sa.ForeignKeyConstraint(['api_key_hash'], ['api_keys.key_hash'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_usage_ledger_api_key_date', 'usage_ledger', ['api_key_hash', 'created_at'], unique=False)
    op.create_index('idx_usage_ledger_direction', 'usage_ledger', ['direction'], unique=False)
    op.create_index('idx_usage_ledger_model', 'usage_ledger', ['model'], unique=False)
    op.create_index('idx_usage_ledger_workspace_date', 'usage_ledger', ['workspace_id', 'created_at'], unique=False)

    # Create idempotency table
    op.create_table('idempotency',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('api_key_hash', sa.Text(), nullable=False),
        sa.Column('request_hash', sa.Text(), nullable=False),
        sa.Column('response', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_idempotency_api_key', 'idempotency', ['api_key_hash'], unique=False)
    op.create_index('idx_idempotency_created', 'idempotency', ['created_at'], unique=False)

    # Create threads table
    op.create_table('threads',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('workspace_id', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_threads_workspace', 'threads', ['workspace_id'], unique=False)

    # Create globals table
    op.create_table('globals',
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('mission', sa.Text(), nullable=True),
        sa.Column('scope', sa.Text(), nullable=True),
        sa.Column('constraints', sa.JSON(), nullable=True),
        sa.Column('runbook', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('thread_id')
    )

    # Create semantic_items table
    op.create_table('semantic_items',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('links', sa.JSON(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('supersedes', sa.JSON(), nullable=True),
        sa.Column('salience', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=True),
        sa.Column('rehearsal_due', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("kind IN ('decision','requirement','contract','constraint','task','glossary')", name='semantic_items_kind_check'),
        sa.CheckConstraint("status IN ('accepted','provisional','superseded')", name='semantic_items_status_check'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_semantic_items_kind', 'semantic_items', ['kind'], unique=False)
    op.create_index('idx_semantic_items_salience', 'semantic_items', ['salience'], unique=False)
    op.create_index('idx_semantic_items_status', 'semantic_items', ['status'], unique=False)
    op.create_index('idx_semantic_items_thread', 'semantic_items', ['thread_id'], unique=False)

    # Create episodic_items table
    op.create_table('episodic_items',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('snippet', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('hash', sa.Text(), nullable=True),
        sa.Column('salience', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("kind IN ('test_fail','stack','chat','log','diff')", name='episodic_items_kind_check'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_episodic_items_hash', 'episodic_items', ['hash'], unique=False)
    op.create_index('idx_episodic_items_kind', 'episodic_items', ['kind'], unique=False)
    op.create_index('idx_episodic_items_salience', 'episodic_items', ['salience'], unique=False)
    op.create_index('idx_episodic_items_thread', 'episodic_items', ['thread_id'], unique=False)

    # Create artifacts table
    op.create_table('artifacts',
        sa.Column('ref', sa.Text(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.Text(), nullable=True),
        sa.Column('hash', sa.Text(), nullable=True),
        sa.Column('neighbors', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('ref')
    )
    op.create_index('idx_artifacts_hash', 'artifacts', ['hash'], unique=False)
    op.create_index('idx_artifacts_thread', 'artifacts', ['thread_id'], unique=False)

    # Create edges table
    op.create_table('edges',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('src_ref', sa.Text(), nullable=False),
        sa.Column('dst_ref', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_edges_dst', 'edges', ['dst_ref'], unique=False)
    op.create_index('idx_edges_kind', 'edges', ['kind'], unique=False)
    op.create_index('idx_edges_src', 'edges', ['src_ref'], unique=False)
    op.create_index('idx_edges_thread', 'edges', ['thread_id'], unique=False)

    # Create embeddings table
    op.create_table('embeddings',
        sa.Column('item_id', sa.Text(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('space', sa.Text(), nullable=False),
        sa.Column('vector', Vector(1536), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("space IN ('text','code')", name='embeddings_space_check'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('item_id')
    )
    op.create_index('idx_embeddings_space', 'embeddings', ['space'], unique=False)
    op.create_index('idx_embeddings_thread', 'embeddings', ['thread_id'], unique=False)

    # Create events table
    op.create_table('events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("type IN ('ingest','update','retrieval','feedback','llm_call','admin')", name='events_type_check'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_events_created', 'events', ['created_at'], unique=False)
    op.create_index('idx_events_thread', 'events', ['thread_id'], unique=False)
    op.create_index('idx_events_type', 'events', ['type'], unique=False)

    # Create usage_stats table
    op.create_table('usage_stats',
        sa.Column('item_id', sa.Text(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=True),
        sa.Column('references', sa.Integer(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ),
        sa.PrimaryKeyConstraint('item_id')
    )
    op.create_index('idx_usage_stats_last_used', 'usage_stats', ['last_used_at'], unique=False)
    op.create_index('idx_usage_stats_thread', 'usage_stats', ['thread_id'], unique=False)


def downgrade() -> None:
    # Drop all tables in reverse order
    op.drop_table('usage_stats')
    op.drop_table('events')
    op.drop_table('embeddings')
    op.drop_table('edges')
    op.drop_table('artifacts')
    op.drop_table('episodic_items')
    op.drop_table('semantic_items')
    op.drop_table('globals')
    op.drop_table('threads')
    op.drop_table('idempotency')
    op.drop_table('usage_ledger')
    op.drop_table('api_keys')
    op.drop_table('settings')
    op.drop_table('model_catalog')
    
    # Drop pgvector extension
    op.execute('DROP EXTENSION IF EXISTS vector')

