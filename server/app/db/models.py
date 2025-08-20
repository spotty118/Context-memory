"""
SQLAlchemy database models for Context Memory + LLM Gateway.
"""
import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, DateTime, Date, JSON, Text, 
    ForeignKey, CheckConstraint, Index, BigInteger, ARRAY, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ModelCatalog(Base, TimestampMixin):
    """Model catalog synced from OpenRouter."""
    __tablename__ = 'model_catalog'
    
    model_id = Column(Text, primary_key=True)  # e.g., "openai/gpt-4o-mini"
    provider = Column(Text, nullable=False)    # e.g., "openai"
    display_name = Column(Text)
    context_window = Column(Integer)
    input_price_per_1k = Column(Numeric(10, 6))
    output_price_per_1k = Column(Numeric(10, 6))
    supports_tools = Column(Boolean, default=False)
    supports_vision = Column(Boolean, default=False)
    supports_json_mode = Column(Boolean, default=False)
    embeddings = Column(Boolean, default=False)
    status = Column(
        Text, 
        CheckConstraint("status IN ('active','deprecated','unavailable')"), 
        default='active'
    )
    last_seen_at = Column(DateTime(timezone=True))
    metadata = Column(JSON)
    
    # Indexes
    __table_args__ = (
        Index('idx_model_catalog_provider', 'provider'),
        Index('idx_model_catalog_status', 'status'),
        Index('idx_model_catalog_embeddings', 'embeddings'),
    )


class Settings(Base, TimestampMixin):
    """Global application settings."""
    __tablename__ = 'settings'
    
    key = Column(Text, primary_key=True)
    value = Column(JSON, nullable=False)
    
    # Common settings keys:
    # - "global_default_model": {"model_id": "openai/gpt-4o-mini"}
    # - "global_embed_model": {"model_id": "openai/text-embedding-3-large"}
    # - "model_allowlist_global": ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", ...]
    # - "model_blocklist_global": []


class APIKey(Base, TimestampMixin):
    """API keys for client authentication."""
    __tablename__ = 'api_keys'
    
    key_hash = Column(Text, primary_key=True)  # SHA-256 hash of the actual key
    workspace_id = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    daily_quota_tokens = Column(Integer)  # NULL means use global default
    rpm_limit = Column(Integer)           # NULL means use global default
    model_allowlist = Column(ARRAY(Text)) # NULL means use global allowlist
    model_blocklist = Column(ARRAY(Text)) # NULL means no per-key blocklist
    default_model = Column(Text)          # NULL means use global default
    default_embed_model = Column(Text)    # NULL means use global default
    
    # Relationships
    usage_records = relationship("UsageLedger", back_populates="api_key")
    
    # Indexes
    __table_args__ = (
        Index('idx_api_keys_workspace', 'workspace_id'),
        Index('idx_api_keys_active', 'active'),
    )


class UsageLedger(Base, TimestampMixin):
    """Token usage tracking ledger."""
    __tablename__ = 'usage_ledger'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    api_key_hash = Column(Text, ForeignKey('api_keys.key_hash'), nullable=False)
    workspace_id = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    direction = Column(
        Text, 
        CheckConstraint("direction IN ('prompt','completion','embedding')"), 
        nullable=False
    )
    tokens = Column(Integer, nullable=False)
    cost_usd = Column(Numeric(10, 6), default=0)
    metadata = Column(JSON)  # Additional context like thread_id, purpose, etc.
    
    # Relationships
    api_key = relationship("APIKey", back_populates="usage_records")
    
    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_usage_ledger_api_key_date', 'api_key_hash', 'created_at'),
        Index('idx_usage_ledger_workspace_date', 'workspace_id', 'created_at'),
        Index('idx_usage_ledger_model', 'model'),
        Index('idx_usage_ledger_direction', 'direction'),
    )


class IdempotencyRecord(Base, TimestampMixin):
    """Idempotency records for chat completions."""
    __tablename__ = 'idempotency'
    
    id = Column(Text, primary_key=True)  # Idempotency-Key header value
    api_key_hash = Column(Text, nullable=False)
    request_hash = Column(Text, nullable=False)  # Hash of request body
    response = Column(JSON, nullable=False)      # Cached response
    
    # TTL: records expire after 24 hours
    __table_args__ = (
        Index('idx_idempotency_api_key', 'api_key_hash'),
        Index('idx_idempotency_created', 'created_at'),
    )


# Context Memory Models

class Thread(Base, TimestampMixin):
    """Context memory threads."""
    __tablename__ = 'threads'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text)
    workspace_id = Column(Text, nullable=False)  # Link to workspace
    
    # Relationships
    globals_record = relationship("GlobalsRecord", back_populates="thread", uselist=False)
    semantic_items = relationship("SemanticItem", back_populates="thread")
    episodic_items = relationship("EpisodicItem", back_populates="thread")
    artifacts = relationship("Artifact", back_populates="thread")
    edges = relationship("Edge", back_populates="thread")
    embeddings = relationship("EmbeddingRecord", back_populates="thread")
    events = relationship("Event", back_populates="thread")
    
    # Indexes
    __table_args__ = (
        Index('idx_threads_workspace', 'workspace_id'),
    )


class GlobalsRecord(Base, TimestampMixin):
    """Global context for threads (mission, scope, constraints, runbook)."""
    __tablename__ = 'globals'
    
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), primary_key=True)
    mission = Column(Text)
    scope = Column(Text)
    constraints = Column(JSON)
    runbook = Column(JSON)
    
    # Relationships
    thread = relationship("Thread", back_populates="globals_record")


class SemanticItem(Base, TimestampMixin):
    """Semantic items (decisions, requirements, tasks, etc.)."""
    __tablename__ = 'semantic_items'
    
    id = Column(Text, primary_key=True)  # e.g., 'S1', 'S2', etc.
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    kind = Column(
        Text,
        CheckConstraint("kind IN ('decision','requirement','contract','constraint','task','glossary')"),
        nullable=False
    )
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    tags = Column(JSON)
    links = Column(JSON)  # References to other items
    status = Column(
        Text,
        CheckConstraint("status IN ('accepted','provisional','superseded')"),
        default='provisional'
    )
    supersedes = Column(JSON)  # IDs of items this supersedes
    salience = Column(Numeric(5, 4), default=0.5)  # Importance score 0-1
    usage_count = Column(Integer, default=0)
    rehearsal_due = Column(Date)  # For spaced repetition
    
    # Relationships
    thread = relationship("Thread", back_populates="semantic_items")
    
    # Indexes
    __table_args__ = (
        Index('idx_semantic_items_thread', 'thread_id'),
        Index('idx_semantic_items_kind', 'kind'),
        Index('idx_semantic_items_status', 'status'),
        Index('idx_semantic_items_salience', 'salience'),
    )


class EpisodicItem(Base, TimestampMixin):
    """Episodic items (test failures, stack traces, chat logs, diffs)."""
    __tablename__ = 'episodic_items'
    
    id = Column(Text, primary_key=True)  # e.g., 'E1', 'E2', etc.
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    kind = Column(
        Text,
        CheckConstraint("kind IN ('test_fail','stack','chat','log','diff')"),
        nullable=False
    )
    title = Column(Text, nullable=False)
    snippet = Column(Text, nullable=False)  # Brief excerpt
    source = Column(Text)  # Original source/file
    hash = Column(Text)    # Content hash for deduplication
    salience = Column(Numeric(5, 4), default=0.5)
    
    # Relationships
    thread = relationship("Thread", back_populates="episodic_items")
    
    # Indexes
    __table_args__ = (
        Index('idx_episodic_items_thread', 'thread_id'),
        Index('idx_episodic_items_kind', 'kind'),
        Index('idx_episodic_items_hash', 'hash'),
        Index('idx_episodic_items_salience', 'salience'),
    )


class Artifact(Base, TimestampMixin):
    """Code artifacts and file references."""
    __tablename__ = 'artifacts'
    
    ref = Column(Text, primary_key=True)  # e.g., 'CODE:path/file.py#L10-L20'
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    role = Column(Text)  # Role/purpose of this artifact
    hash = Column(Text)  # Content hash
    neighbors = Column(JSON)  # Related artifacts
    
    # Relationships
    thread = relationship("Thread", back_populates="artifacts")
    
    # Indexes
    __table_args__ = (
        Index('idx_artifacts_thread', 'thread_id'),
        Index('idx_artifacts_hash', 'hash'),
    )


class Edge(Base, TimestampMixin):
    """Relationships between items."""
    __tablename__ = 'edges'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    src_ref = Column(Text, nullable=False)  # Source item reference
    dst_ref = Column(Text, nullable=False)  # Destination item reference
    kind = Column(Text, nullable=False)     # Relationship type
    
    # Relationships
    thread = relationship("Thread", back_populates="edges")
    
    # Indexes
    __table_args__ = (
        Index('idx_edges_thread', 'thread_id'),
        Index('idx_edges_src', 'src_ref'),
        Index('idx_edges_dst', 'dst_ref'),
        Index('idx_edges_kind', 'kind'),
    )


class EmbeddingRecord(Base, TimestampMixin):
    """Vector embeddings for semantic search."""
    __tablename__ = 'embeddings'
    
    item_id = Column(Text, primary_key=True)  # References semantic/episodic items
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    space = Column(
        Text,
        CheckConstraint("space IN ('text','code')"),
        nullable=False
    )
    vector = Column(Vector(1536))  # OpenAI embedding dimension
    
    # Relationships
    thread = relationship("Thread", back_populates="embeddings")
    
    # Indexes
    __table_args__ = (
        Index('idx_embeddings_thread', 'thread_id'),
        Index('idx_embeddings_space', 'space'),
    )


class Event(Base, TimestampMixin):
    """Event log for context memory operations."""
    __tablename__ = 'events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    type = Column(
        Text,
        CheckConstraint("type IN ('ingest','update','retrieval','feedback','llm_call','admin')"),
        nullable=False
    )
    payload = Column(JSON, nullable=False)
    
    # Relationships
    thread = relationship("Thread", back_populates="events")
    
    # Indexes
    __table_args__ = (
        Index('idx_events_thread', 'thread_id'),
        Index('idx_events_type', 'type'),
        Index('idx_events_created', 'created_at'),
    )


class UsageStats(Base, TimestampMixin):
    """Usage statistics for items."""
    __tablename__ = 'usage_stats'
    
    item_id = Column(Text, primary_key=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey('threads.id'), nullable=False)
    clicks = Column(Integer, default=0)
    references = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True))
    
    # Indexes
    __table_args__ = (
        Index('idx_usage_stats_thread', 'thread_id'),
        Index('idx_usage_stats_last_used', 'last_used_at'),
    )

