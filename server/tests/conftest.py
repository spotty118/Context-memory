"""
Pytest configuration and fixtures for Context Memory Gateway tests.
"""
import asyncio
import os
import tempfile
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import redis
from rq import Queue

from app.main import app
from app.core.config import settings
from app.db.models import Base
from app.db.session import get_db_session
from app.workers.queue import redis_conn


# Test database setup
TEST_DATABASE_URL = "sqlite:///./test.db"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def test_engine():
    """Create test database engine."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def test_db_session(test_engine):
    """Create a test database session."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def override_get_db(test_db_session):
    """Override the get_db_session dependency."""
    def _override_get_db():
        try:
            yield test_db_session
        finally:
            pass
    
    app.dependency_overrides[get_db_session] = _override_get_db
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def client(override_get_db):
    """Create a test client."""
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture
def mock_redis():
    """Mock Redis connection for tests."""
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = True
    mock_redis.exists.return_value = False
    mock_redis.incr.return_value = 1
    mock_redis.expire.return_value = True
    return mock_redis

@pytest.fixture
def mock_queue(mock_redis):
    """Mock RQ queue for tests."""
    mock_queue = MagicMock(spec=Queue)
    mock_queue.connection = mock_redis
    mock_queue.enqueue.return_value = MagicMock(id="test-job-id")
    return mock_queue

@pytest.fixture
def mock_openrouter():
    """Mock OpenRouter API responses."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "id": "openai/gpt-4",
                "name": "GPT-4",
                "provider": "openai",
                "description": "GPT-4 model",
                "context_length": 8192,
                "pricing": {
                    "prompt": "0.03",
                    "completion": "0.06"
                },
                "supports_streaming": True,
                "supports_functions": True
            },
            {
                "id": "anthropic/claude-3-opus",
                "name": "Claude 3 Opus",
                "provider": "anthropic",
                "description": "Claude 3 Opus model",
                "context_length": 200000,
                "pricing": {
                    "prompt": "0.015",
                    "completion": "0.075"
                },
                "supports_streaming": True,
                "supports_functions": False
            }
        ]
    }
    return mock_response

@pytest.fixture
def sample_api_key():
    """Sample API key for testing."""
    return "cmg_test_api_key_12345"

@pytest.fixture
def auth_headers(sample_api_key):
    """Authentication headers for API requests."""
    return {"Authorization": f"Bearer {sample_api_key}"}

@pytest.fixture
def sample_workspace_data():
    """Sample workspace data for testing."""
    return {
        "id": "test-workspace-123",
        "name": "Test Workspace",
        "description": "A test workspace",
        "created_at": "2025-01-20T10:00:00Z",
        "updated_at": "2025-01-20T10:00:00Z"
    }

@pytest.fixture
def sample_api_key_data():
    """Sample API key data for testing."""
    return {
        "id": "test-key-123",
        "workspace_id": "test-workspace-123",
        "name": "Test API Key",
        "key_hash": "hashed_key_value",
        "status": "active",
        "quota_requests": 1000,
        "quota_tokens": 100000,
        "created_at": "2025-01-20T10:00:00Z",
        "updated_at": "2025-01-20T10:00:00Z"
    }

@pytest.fixture
def sample_chat_completion_request():
    """Sample chat completion request for testing."""
    return {
        "model": "openai/gpt-4",
        "messages": [
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "max_tokens": 100,
        "temperature": 0.7,
        "stream": False
    }

@pytest.fixture
def sample_chat_completion_response():
    """Sample chat completion response for testing."""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": 1642781234,
        "model": "openai/gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! I'm doing well, thank you for asking. How can I help you today?"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30
        }
    }

@pytest.fixture
def sample_context_ingest_request():
    """Sample context memory ingest request."""
    return {
        "thread_id": "test-thread-123",
        "content_type": "chat",
        "content": "User discussed project requirements for a new web application. Key requirements include user authentication, real-time messaging, and file upload capabilities.",
        "metadata": {
            "source": "chat_session",
            "timestamp": "2025-01-20T10:00:00Z"
        }
    }

@pytest.fixture
def sample_context_recall_request():
    """Sample context memory recall request."""
    return {
        "thread_id": "test-thread-123",
        "purpose": "Continue discussion about web application requirements",
        "token_budget": 4000,
        "include_artifacts": True
    }

@pytest.fixture
def sample_semantic_item():
    """Sample semantic context item."""
    return {
        "id": "S001",
        "thread_id": "test-thread-123",
        "item_type": "decision",
        "content": "Decided to use React for the frontend framework",
        "salience": 0.8,
        "usage_count": 5,
        "created_at": "2025-01-20T10:00:00Z",
        "last_accessed_at": "2025-01-20T11:00:00Z"
    }

@pytest.fixture
def sample_episodic_item():
    """Sample episodic context item."""
    return {
        "id": "E001",
        "thread_id": "test-thread-123",
        "item_type": "test_failure",
        "content": "Unit test failed: test_user_authentication - AssertionError: Expected status 200, got 401",
        "salience": 0.6,
        "usage_count": 2,
        "created_at": "2025-01-20T10:00:00Z",
        "last_accessed_at": "2025-01-20T10:30:00Z"
    }

@pytest.fixture
def sample_artifact():
    """Sample artifact."""
    return {
        "id": "CODE001",
        "thread_id": "test-thread-123",
        "title": "User Authentication Component",
        "file_path": "/src/components/Auth.jsx",
        "file_size": 2048,
        "content": "import React from 'react';\n\nconst Auth = () => {\n  // Authentication logic\n};\n\nexport default Auth;",
        "usage_count": 3,
        "created_at": "2025-01-20T10:00:00Z",
        "last_accessed_at": "2025-01-20T10:45:00Z"
    }

@pytest.fixture
def sample_working_set_request():
    """Sample working set request."""
    return {
        "thread_id": "test-thread-123",
        "purpose": "Implement user authentication feature",
        "token_budget": 8000,
        "include_artifacts": True,
        "focus_areas": ["authentication", "security", "frontend"]
    }

@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as f:
        f.write("Test file content")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)

@pytest.fixture
def mock_embedding_response():
    """Mock OpenAI embedding API response."""
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "embedding": [0.1] * 1536,  # Mock 1536-dimensional embedding
                "index": 0
            }
        ],
        "model": "text-embedding-ada-002",
        "usage": {
            "prompt_tokens": 5,
            "total_tokens": 5
        }
    }

@pytest.fixture
async def async_client():
    """Create an async test client."""
    from httpx import AsyncClient
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

# Test data factories
class TestDataFactory:
    """Factory for creating test data."""
    
    @staticmethod
    def create_workspace(**kwargs):
        """Create a test workspace."""
        default_data = {
            "id": "test-workspace",
            "name": "Test Workspace",
            "description": "Test workspace description"
        }
        default_data.update(kwargs)
        return default_data
    
    @staticmethod
    def create_api_key(**kwargs):
        """Create a test API key."""
        default_data = {
            "id": "test-api-key",
            "workspace_id": "test-workspace",
            "name": "Test API Key",
            "status": "active",
            "quota_requests": 1000,
            "quota_tokens": 100000
        }
        default_data.update(kwargs)
        return default_data
    
    @staticmethod
    def create_semantic_item(**kwargs):
        """Create a test semantic item."""
        default_data = {
            "id": "S001",
            "thread_id": "test-thread",
            "item_type": "decision",
            "content": "Test semantic content",
            "salience": 0.5,
            "usage_count": 0
        }
        default_data.update(kwargs)
        return default_data

@pytest.fixture
def test_factory():
    """Test data factory fixture."""
    return TestDataFactory

# Async test utilities
@pytest_asyncio.fixture
async def async_test_db():
    """Async database fixture for integration tests."""
    # This would set up an async database connection
    # For now, we'll use the sync version
    pass

# Performance test fixtures
@pytest.fixture
def performance_timer():
    """Timer for performance tests."""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.time()
        
        def stop(self):
            self.end_time = time.time()
            return self.end_time - self.start_time
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
    
    return Timer()

# Cleanup fixtures
@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Automatically cleanup test data after each test."""
    yield
    # Cleanup logic would go here
    pass

