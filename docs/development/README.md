# Development Guide

Complete guide for developers working on the Context Memory + LLM Gateway service.

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Git
- OpenRouter API key

### Local Development Setup

1. **Clone Repository**
   ```bash
   git clone <repository-url>
   cd context-memory-gateway
   ```

2. **Environment Setup**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start Development Environment**
   ```bash
   ./scripts/dev.sh setup
   ```

4. **Verify Installation**
   ```bash
   curl http://localhost:8000/health
   ```

## Project Structure

```
context-memory-gateway/
├── server/                     # Main application
│   ├── app/                   # FastAPI application
│   │   ├── api/              # API endpoints
│   │   ├── core/             # Core functionality
│   │   ├── db/               # Database models and migrations
│   │   ├── services/         # Business logic services
│   │   ├── workers/          # Background workers
│   │   ├── admin/            # Admin interface
│   │   └── telemetry/        # Monitoring and logging
│   ├── tests/                # Test suite
│   ├── alembic.ini           # Database migration config
│   ├── requirements.txt      # Python dependencies
│   └── Makefile             # Development commands
├── docs/                     # Documentation
├── infra/                    # Infrastructure as code
│   ├── terraform/           # Terraform configurations
│   ├── nginx/               # Nginx configurations
│   └── sql/                 # Database initialization
├── scripts/                  # Development scripts
├── docker-compose.local.yml  # Local development
├── Dockerfile               # Production container
└── README.md               # Main documentation
```

## Development Workflow

### Daily Development

1. **Start Services**
   ```bash
   ./scripts/dev.sh start
   ```

2. **View Logs**
   ```bash
   ./scripts/dev.sh logs app
   ```

3. **Run Tests**
   ```bash
   make test
   ```

4. **Database Operations**
   ```bash
   # Create migration
   ./scripts/dev.sh create-migration "Add new feature"
   
   # Run migrations
   ./scripts/dev.sh migrate
   ```

5. **Stop Services**
   ```bash
   ./scripts/dev.sh stop
   ```

### Code Style

- **Python**: Follow PEP 8 with Black formatting
- **Line Length**: 100 characters maximum
- **Import Order**: isort with black profile
- **Type Hints**: Use type hints for all functions

```bash
# Format code
make format

# Lint code
make lint
```

### Git Workflow

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**
   - Write code with tests
   - Follow coding standards
   - Update documentation

3. **Test Changes**
   ```bash
   make test
   make lint
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/your-feature-name
   ```

## Architecture Overview

### Core Components

1. **FastAPI Application** (`app/main.py`)
   - Main application entry point
   - Middleware configuration
   - Route registration

2. **API Endpoints** (`app/api/`)
   - REST API implementations
   - Request/response handling
   - Authentication and validation

3. **Services** (`app/services/`)
   - Business logic implementation
   - External API integrations
   - Context memory processing

4. **Database Layer** (`app/db/`)
   - SQLAlchemy models
   - Database sessions
   - Alembic migrations

5. **Background Workers** (`app/workers/`)
   - Redis Queue job processing
   - Scheduled tasks
   - Async operations

### Request Flow

```
Client Request
      ↓
   Nginx Proxy
      ↓
  FastAPI App
      ↓
  Middleware Stack
  • CORS
  • Authentication
  • Rate Limiting
  • Logging
      ↓
  API Endpoint
      ↓
  Service Layer
      ↓
  Database/Redis
      ↓
  Response
```

## Database Development

### Models

SQLAlchemy models are defined in `app/db/models.py`:

```python
from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ContextItem(Base):
    __tablename__ = "context_items"
    
    id = Column(String, primary_key=True)
    workspace_id = Column(String, nullable=False)
    thread_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    item_type = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
```

### Migrations

Create and run database migrations:

```bash
# Create new migration
alembic revision --autogenerate -m "Add new table"

# Run migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

### Database Sessions

Use dependency injection for database sessions:

```python
from app.db.session import get_db

@app.get("/items")
def get_items(db: Session = Depends(get_db)):
    return db.query(ContextItem).all()
```

## API Development

### Endpoint Structure

Follow consistent patterns for API endpoints:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()

class ItemRequest(BaseModel):
    name: str
    description: str

class ItemResponse(BaseModel):
    id: str
    name: str
    description: str

@router.post("/items", response_model=ItemResponse)
async def create_item(
    request: ItemRequest,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    # Implementation
    pass
```

### Error Handling

Use consistent error responses:

```python
from app.core.exceptions import APIException

class ItemNotFound(APIException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code="ITEM_NOT_FOUND",
            message="Item not found"
        )
```

### Authentication

Protect endpoints with API key authentication:

```python
from app.core.security import get_api_key, get_workspace

@router.get("/protected")
async def protected_endpoint(
    api_key: str = Depends(get_api_key),
    workspace: Workspace = Depends(get_workspace)
):
    # Endpoint implementation
    pass
```

## Service Development

### Service Pattern

Implement business logic in service classes:

```python
from typing import List, Optional
from app.db.models import ContextItem

class ContextService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_item(self, workspace_id: str, content: str) -> ContextItem:
        item = ContextItem(
            workspace_id=workspace_id,
            content=content
        )
        self.db.add(item)
        self.db.commit()
        return item
    
    def get_items(self, workspace_id: str) -> List[ContextItem]:
        return self.db.query(ContextItem).filter(
            ContextItem.workspace_id == workspace_id
        ).all()
```

### External API Integration

Use consistent patterns for external APIs:

```python
import httpx
from typing import Dict, Any

class OpenRouterService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient()
    
    async def chat_completion(self, request: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = await self.client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=request,
            headers=headers
        )
        
        response.raise_for_status()
        return response.json()
```

## Worker Development

### Job Implementation

Create background jobs using RQ:

```python
from rq import Queue
from app.workers.queue import get_queue

def process_embeddings(item_ids: List[str]) -> Dict[str, Any]:
    """Background job to process embeddings."""
    # Job implementation
    return {"processed": len(item_ids)}

# Enqueue job
queue = get_queue("embeddings")
job = queue.enqueue(process_embeddings, ["item1", "item2"])
```

### Scheduled Tasks

Use RQ Scheduler for periodic tasks:

```python
from rq_scheduler import Scheduler
from datetime import timedelta

scheduler = Scheduler(connection=redis_conn)

# Schedule recurring job
scheduler.schedule(
    scheduled_time=datetime.utcnow(),
    func=sync_model_catalog,
    interval=timedelta(hours=1),
    repeat=None  # Repeat indefinitely
)
```

## Testing

### Test Structure

Organize tests by type:

```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
├── e2e/           # End-to-end tests
├── fixtures/      # Test data
└── conftest.py    # Pytest configuration
```

### Writing Tests

Use pytest with comprehensive fixtures:

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def api_key(db_session):
    # Create test API key
    pass

def test_create_item(client, api_key):
    response = client.post(
        "/v1/items",
        json={"name": "test", "description": "test item"},
        headers={"Authorization": f"Bearer {api_key}"}
    )
    assert response.status_code == 201
    assert response.json()["name"] == "test"
```

### Running Tests

```bash
# All tests
make test

# Specific test file
pytest tests/unit/test_api.py -v

# With coverage
make test-coverage

# Fast tests only
make test-fast
```

## Debugging

### Local Debugging

1. **Application Logs**
   ```bash
   ./scripts/dev.sh logs app
   ```

2. **Database Access**
   ```bash
   ./scripts/dev.sh shell postgres
   psql -U cmg_user -d cmg_dev
   ```

3. **Redis Access**
   ```bash
   ./scripts/dev.sh shell redis
   redis-cli
   ```

4. **Interactive Shell**
   ```bash
   ./scripts/dev.sh shell app
   python -c "from app.main import app; print('App loaded')"
   ```

### Debug Configuration

Enable debug mode in development:

```python
# .env
DEBUG=true
LOG_LEVEL=DEBUG

# app/core/config.py
class Settings(BaseSettings):
    debug: bool = False
    log_level: str = "INFO"
```

### Performance Profiling

Use built-in profiling tools:

```python
import cProfile
import pstats

def profile_function():
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Your code here
    
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats()
```

## Configuration Management

### Environment Variables

Use pydantic-settings for configuration:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    openrouter_api_key: str
    secret_key: str
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Feature Flags

Implement feature flags for gradual rollouts:

```python
class FeatureFlags(BaseSettings):
    enable_context_memory: bool = True
    enable_usage_analytics: bool = True
    enable_new_feature: bool = False

flags = FeatureFlags()

if flags.enable_new_feature:
    # New feature code
    pass
```

## Monitoring & Observability

### Logging

Use structured logging throughout the application:

```python
import logging
import json

logger = logging.getLogger(__name__)

def log_api_request(request_id: str, endpoint: str, duration_ms: int):
    logger.info(json.dumps({
        "event": "api_request",
        "request_id": request_id,
        "endpoint": endpoint,
        "duration_ms": duration_ms
    }))
```

### Metrics

Expose Prometheus metrics:

```python
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests')
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')

@REQUEST_DURATION.time()
def handle_request():
    REQUEST_COUNT.inc()
    # Handle request
```

### Health Checks

Implement comprehensive health checks:

```python
@app.get("/health/detailed")
async def detailed_health():
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "openrouter": await check_openrouter()
    }
    
    overall_status = "healthy" if all(checks.values()) else "unhealthy"
    
    return {
        "status": overall_status,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }
```

## Performance Optimization

### Database Optimization

- Use database indexes effectively
- Implement connection pooling
- Use async database operations
- Optimize query patterns

```python
# Add database indexes
class ContextItem(Base):
    __tablename__ = "context_items"
    
    id = Column(String, primary_key=True)
    workspace_id = Column(String, nullable=False, index=True)
    thread_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, index=True)
```

### Caching

Implement Redis caching for frequently accessed data:

```python
import redis
import json
from functools import wraps

redis_client = redis.Redis.from_url(settings.redis_url)

def cache_result(expiry: int = 300):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            # Try to get from cache
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            redis_client.setex(cache_key, expiry, json.dumps(result))
            
            return result
        return wrapper
    return decorator
```

### Async Operations

Use async/await for I/O operations:

```python
import asyncio
import httpx

async def fetch_multiple_models():
    async with httpx.AsyncClient() as client:
        tasks = [
            client.get(f"https://api.openrouter.ai/models/{model_id}")
            for model_id in model_ids
        ]
        responses = await asyncio.gather(*tasks)
        return [r.json() for r in responses]
```

## Security Considerations

### Input Validation

Always validate and sanitize inputs:

```python
from pydantic import BaseModel, validator

class UserInput(BaseModel):
    content: str
    
    @validator('content')
    def validate_content(cls, v):
        if len(v) > 10000:
            raise ValueError('Content too long')
        
        # Sanitize content
        return html.escape(v)
```

### Authentication

Implement proper authentication checks:

```python
from app.core.security import verify_api_key

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    
    api_key = authorization[7:]  # Remove "Bearer " prefix
    user = await verify_api_key(api_key)
    
    if not user:
        raise HTTPException(401, "Invalid API key")
    
    return user
```

### Data Protection

Implement data redaction for sensitive information:

```python
import re

def redact_sensitive_data(content: str) -> str:
    # Redact email addresses
    content = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 
                     '[REDACTED_EMAIL]', content)
    
    # Redact API keys
    content = re.sub(r'\b[A-Za-z0-9]{20,}\b', '[REDACTED_API_KEY]', content)
    
    return content
```

## Contributing Guidelines

### Code Review Process

1. Create feature branch
2. Implement changes with tests
3. Submit pull request
4. Address review feedback
5. Merge after approval

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

### Release Process

1. Update version numbers
2. Update CHANGELOG.md
3. Create release branch
4. Run full test suite
5. Deploy to staging
6. Create release tag
7. Deploy to production

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   ```bash
   # Check database status
   ./scripts/dev.sh logs postgres
   
   # Reset database
   ./scripts/dev.sh reset-db
   ```

2. **Redis Connection Issues**
   ```bash
   # Check Redis status
   ./scripts/dev.sh logs redis
   
   # Clear Redis cache
   docker-compose exec redis redis-cli FLUSHALL
   ```

3. **Import Errors**
   ```bash
   # Check Python path
   export PYTHONPATH=/app:$PYTHONPATH
   
   # Reinstall dependencies
   pip install -r requirements.txt
   ```

4. **Port Conflicts**
   ```bash
   # Check port usage
   lsof -i :8000
   
   # Kill process using port
   kill -9 <PID>
   ```

### Getting Help

- **Documentation**: Check the docs/ directory
- **Issues**: Create GitHub issue
- **Discussions**: Use GitHub Discussions
- **Team Chat**: Internal team channels

This development guide should help you get started with contributing to the Context Memory + LLM Gateway service. For specific questions, please refer to the relevant documentation sections or reach out to the development team.

