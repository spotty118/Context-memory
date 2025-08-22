"""
Database session management and connection handling.
"""
from contextlib import asynccontextmanager
from contextlib import contextmanager
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker as sa_sessionmaker, Session as SyncSession

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
import structlog

from app.core.config import settings
from app.db.models import Base

logger = structlog.get_logger(__name__)

# Global engine and session maker
engine = None
async_session_maker = None


def create_engine():
    """Create the SQLAlchemy async engine."""
    global engine

    if engine is None:
        db_url = settings.DATABASE_URL
        if db_url.startswith("postgresql://"):
            async_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            async_url = db_url
        engine = create_async_engine(
            async_url,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=settings.is_development and settings.DEBUG,
            poolclass=NullPool if settings.ENVIRONMENT == "serverless" else None,
        )

        logger.info(
            "database_engine_created",
            url=settings.DATABASE_URL.split("@")[-1],  # Hide credentials
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
        )

    return engine


def create_session_maker():
    """Create the async session maker."""
    global async_session_maker

    if async_session_maker is None:
        engine = create_engine()
        async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("database_session_maker_created")

    return async_session_maker


def get_session_maker():
    """Alias for create_session_maker for backwards compatibility."""
    return create_session_maker()


async def init_db():
    """Initialize database tables and extensions."""
    engine = create_engine()

    async with engine.begin() as conn:
        # Enable pgvector extension
        if settings.VECTOR_BACKEND == "pgvector":
            try:
                from sqlalchemy import text
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                logger.info("pgvector_extension_enabled")
            except Exception as e:
                logger.exception("pgvector_extension_failed")

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_created")


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session.

    Usage:
        async with get_db() as db:
            # Use db session
            result = await db.execute(select(Model))
            await db.commit()
    """
    session_maker = create_session_maker()

    async with session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_dependency() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Usage:
        @app.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db_dependency)):
            # Use db session
    """
    async with get_db() as session:
        yield session


async def close_db():
    """Close database connections."""
    global engine
    if engine:
        await engine.dispose()
        logger.info("database_connections_closed")

# Minimal sync session helper for RQ worker code paths only
@contextmanager
def get_db_session() -> SyncSession:
    """Yield a short-lived synchronous SQLAlchemy session.

    This is used only by RQ worker functions that are synchronous. It creates
    a dedicated sync engine/session independent of the async engine.
    """
    # Derive a sync URL from the configured DATABASE_URL
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgresql+asyncpg://"):
        sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    else:
        sync_url = db_url

    engine = sa_create_engine(sync_url, pool_pre_ping=True, future=True)
    SessionLocal = sa_sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()

