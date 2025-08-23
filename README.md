# Context Memory + LLM Gateway

A cloud-hosted service providing LLM gateway functionality with advanced context memory capabilities. Built with FastAPI, PostgreSQL, Redis, and deployed on DigitalOcean.

## 🚀 Features

### Core Functionality
- **LLM Gateway**: Proxy to OpenRouter with 100+ AI models
- **Context Memory**: Intelligent context ingestion, storage, and retrieval
- **Working Sets**: Structured context delivery with token budget management
- **Admin Interface**: Comprehensive web UI for management and monitoring

### Technical Features
- **Authentication**: API key-based authentication with workspace isolation
- **Rate Limiting**: Redis-based token bucket rate limiting
- **Usage Tracking**: Comprehensive usage analytics and quota management
- **Streaming Support**: Real-time streaming for chat completions
- **Vector Search**: Semantic similarity search with pgvector
- **Background Workers**: Async task processing with Redis Queue

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Client Apps   │    │  Admin Web UI   │    │   Monitoring    │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    ┌─────────────┴───────────┐
                    │      Nginx Proxy       │
                    └─────────────┬───────────┘
                                  │
                    ┌─────────────┴───────────┐
                    │   FastAPI Gateway      │
                    │  (Context Memory +     │
                    │   LLM Proxy)           │
                    └─────────────┬───────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
┌─────────┴───────┐    ┌─────────┴───────┐    ┌─────────┴───────┐
│   PostgreSQL    │    │      Redis      │    │   OpenRouter    │
│  (+ pgvector)   │    │   (Cache +      │    │   (AI Models)   │
│                 │    │  Rate Limit)    │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🛠️ Local Development

### Prerequisites

- Docker and Docker Compose
- Git
- OpenRouter API key ([get one here](https://openrouter.ai/keys))

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Context-memory
   ```

2. **Setup environment**
   ```bash
   cp .env.example .env
   # Edit .env with your OpenRouter API key and other settings
   ```

3. **Start development environment**
   ```bash
   ./scripts/dev.sh setup
   ```

4. **Access the application**
   - API: http://localhost:8000
   - Admin Interface: http://localhost:8000/admin
   - API Documentation: http://localhost:8000/docs
   - Grafana (optional): http://localhost:3000

### Development Commands

The `./scripts/dev.sh` script provides convenient commands for development:

```bash
# Start services
./scripts/dev.sh start

# View logs
./scripts/dev.sh logs app

# Run database migrations
./scripts/dev.sh migrate

# Create new migration
./scripts/dev.sh create-migration "Add new feature"

# Open shell in container
./scripts/dev.sh shell app

# Run tests
./scripts/dev.sh test

# Stop services
./scripts/dev.sh stop

# Reset database (destroys all data)
./scripts/dev.sh reset-db

# Clean up Docker resources
./scripts/dev.sh clean
```

### Services

The development environment includes:

- **app**: Main FastAPI application
- **postgres**: PostgreSQL database with pgvector extension
- **redis**: Redis for caching and rate limiting
- **qdrant**: Vector database (optional)
- **worker**: Background task worker
- **nginx**: Reverse proxy (optional)
- **prometheus**: Metrics collection (optional)
- **grafana**: Monitoring dashboard (optional)

## ⚙️ Troubleshooting

- First run fails because .env is missing
  - The dev script expects a .env file. Create one from the template:
    - cp .env.example .env
    - Set at least SECRET_KEY and, if you want to fetch models, OPENROUTER_API_KEY.

- Admin login doesn’t persist
  - Make sure you’re accessing over http://localhost (not file://) so the httponly cookie can be set.
  - Cookie name is admin_token in this build; clearing cookies for localhost can help during dev.

- Workers page shows errors when Redis is down
  - Redis is required for queue metrics. Start via ./scripts/dev.sh start (brings up redis) or docker-compose -f docker-compose.local.yml up redis.
  - The page should render with zeros even if Redis is unavailable.

- Models fetch returns 500
  - This requires a valid OPENROUTER_API_KEY in your .env. Without it, the /admin/models/fetch endpoint will respond with an error JSON, but the rest of the UI will continue to work.

- Healthcheck failing for app container
  - Ensure postgres and redis services are healthy first. The app depends on both becoming healthy.
  - Run ./scripts/dev.sh status to inspect container health.


## 📚 API Documentation

### Authentication

All API requests require an API key in the header:

```bash
curl -H "Authorization: Bearer cmg_your_api_key_here" \
     http://localhost:8000/v1/models
```

### Core Endpoints

#### LLM Gateway
```bash
# List available models
GET /v1/models

# Chat completion
POST /v1/chat/completions
{
  "model": "openai/gpt-4",
  "messages": [{"role": "user", "content": "Hello!"}],
  "stream": false
}

# Chat completion with streaming
POST /v1/chat/completions
{
  "model": "anthropic/claude-3.5-sonnet",
  "messages": [{"role": "user", "content": "Write a story"}],
  "stream": true,
  "max_tokens": 1000,
  "temperature": 0.8
}

# Embeddings
POST /v1/embeddings
{
  "model": "openai/text-embedding-3-large",
  "input": "This is a test sentence for embeddings"
}

# Get specific model details
GET /v1/models/openai/gpt-4
```</search>

#### Context Memory
```bash
# Ingest context
POST /v1/ingest
{
  "thread_id": "session-123",
  "materials": {
    "chat": "User: How do I implement authentication?\nAssistant: You can use JWT tokens with FastAPI...",
    "diffs": "@@ -1,5 +1,7 @@\n+from fastapi import Depends\n+from fastapi.security import HTTPBearer",
    "logs": "2025-01-20 10:30:00 ERROR: Authentication failed for user@example.com"
  }
}

# Recall context with advanced options
POST /v1/recall
{
  "thread_id": "session-123",
  "purpose": "Help user implement secure authentication",
  "token_budget": 4000
}

# Get working set for complex task
POST /v1/workingset
{
  "thread_id": "session-123",
  "purpose": "Implement end-to-end authentication system",
  "token_budget": 8000
}

# Expand specific item with raw content
GET /v1/expand/S123/raw

# Provide detailed feedback
POST /v1/feedback
{
  "item_id": "S123",
  "feedback_type": "helpful",
  "value": 1.0,
  "comment": "This helped resolve the authentication issue"
}
```

#### Workers API
```bash
# Get queue statistics
GET /v1/workers/queues/stats

# Enqueue background job
POST /v1/workers/jobs
{
  "queue_name": "embeddings",
  "job_type": "generate_embeddings",
  "payload": {
    "item_ids": ["S123", "E456"],
    "priority": "high"
  }
}

# Check job status
GET /v1/workers/jobs/job_12345

# Cancel running job
DELETE /v1/workers/jobs/job_12345

# Trigger model sync
POST /v1/workers/sync/models

# Get scheduler status
GET /v1/workers/scheduler/status
```

#### Health & Monitoring
```bash
# Health checks
GET /healthz              # Basic health
GET /readyz               # Readiness check
GET /metrics              # Prometheus metrics

# Admin interface (web UI)
GET /admin                # Dashboard
GET /admin/api-keys       # Manage API keys
GET /admin/models         # View models
GET /admin/usage          # Usage analytics
```</search>

## 🔧 Configuration

### Environment Variables

Key configuration options in `.env`:

```bash
# Core settings
ENVIRONMENT=development
DEBUG=true
SECRET_KEY=your-secret-key

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
REDIS_URL=redis://localhost:6379/0

# OpenRouter
OPENROUTER_API_KEY=your-api-key
DEFAULT_MODEL=openai/gpt-4

# Rate limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Context memory
DEFAULT_TOKEN_BUDGET=8000
MAX_CONTEXT_ITEMS=50
```

### Database Migrations

The application uses Alembic for database migrations:

```bash
# Run migrations
./scripts/dev.sh migrate

# Create new migration
./scripts/dev.sh create-migration "Description of changes"

# View migration history
docker-compose exec app alembic history

# Rollback migration
docker-compose exec app alembic downgrade -1
```

## 🧪 Testing

Run the test suite:

```bash
# Run all tests
./scripts/dev.sh test

# Run specific test file
docker-compose exec app python -m pytest tests/test_api.py -v

# Run with coverage
docker-compose exec app python -m pytest --cov=app tests/
```

## 📊 Monitoring

### Metrics

The application exposes Prometheus metrics at `/metrics`:

- Request counts and latencies
- Database connection pool stats
- Redis cache hit rates
- Context memory usage
- Error rates and types

### Logging

Structured logging with JSON format:

```json
{
  "timestamp": "2025-01-20T10:30:00Z",
  "level": "INFO",
  "logger": "app.api.llm_gateway",
  "message": "chat_completion_request",
  "model": "openai/gpt-4",
  "tokens": 150,
  "duration_ms": 1250
}
```

### Health Checks

- `/health`: Basic health check
- `/health/detailed`: Detailed system status

## 🚀 Deployment

### DigitalOcean App Platform

The application is designed for deployment on DigitalOcean App Platform using the included Terraform configuration.

1. **Setup infrastructure**
   ```bash
   cd infra/terraform
   terraform init
   terraform plan
   terraform apply
   ```

2. **Deploy application**
   The App Platform will automatically build and deploy from your Git repository.

### Docker Production

For other deployment targets:

```bash
# Build production image
docker build -t context-memory-gateway .

# Run with production settings
docker run -d \
  --name cmg-app \
  -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e DATABASE_URL=your-db-url \
  -e REDIS_URL=your-redis-url \
  -e OPENROUTER_API_KEY=your-key \
  context-memory-gateway
```

## 🔒 Security

### API Keys

- Generated with cryptographically secure random bytes
- Stored as hashed values in database
- Support for workspace isolation
- Configurable quotas and rate limits

### Data Protection

- All sensitive data encrypted at rest
- PII redaction in context memory
- Secure headers and CORS configuration
- Input validation and sanitization

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

### Development Workflow

```bash
# Setup development environment
./scripts/dev.sh setup

# Make changes to code
# ...

# Run tests
./scripts/dev.sh test

# Create migration if needed
./scripts/dev.sh create-migration "Add new feature"

# Commit changes
git add .
git commit -m "Add new feature"
git push origin feature-branch
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

- **Documentation**: Check the `/docs` endpoint when running locally
- **Issues**: Create an issue in the repository
- **Discussions**: Use GitHub Discussions for questions

## 🗺️ Roadmap

- [ ] Multi-tenant support
- [ ] Advanced analytics dashboard
- [ ] Custom model fine-tuning
- [ ] Webhook integrations
- [ ] GraphQL API
- [ ] Mobile SDK

