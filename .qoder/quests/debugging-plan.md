# Context Memory Gateway - Debugging Plan

## Overview

This debugging plan provides a comprehensive strategy for troubleshooting and debugging issues in the Context Memory Gateway, a FastAPI-based LLM gateway service with context memory capabilities. The plan covers debugging methodologies for different components, common issue patterns, and monitoring strategies.

## Architecture Overview

The Context Memory Gateway is a microservices architecture built with:
- **FastAPI**: Main application framework
- **PostgreSQL + pgvector**: Relational data and vector storage
- **Redis**: Rate limiting and task queuing
- **Structlog**: Structured logging
- **Sentry**: Error tracking (production)
- **Prometheus**: Metrics collection
- **OpenRouter**: LLM provider proxy

```mermaid
graph TB
    Client[Client Applications] --> Gateway[FastAPI Gateway]
    Gateway --> Auth[Authentication Layer]
    Gateway --> RateLimit[Rate Limiting - Redis]
    Gateway --> LLM[LLM Proxy - OpenRouter]
    Gateway --> Context[Context Memory - PostgreSQL]
    Gateway --> Queue[Background Tasks - Redis Queue]
    Gateway --> Admin[Admin Interface]
    
    subgraph Monitoring
        Logs[Structured Logs - structlog]
        Metrics[Prometheus Metrics]
        Errors[Sentry Error Tracking]
    end
    
    Gateway --> Logs
    Gateway --> Metrics
    Gateway --> Errors
```

## Debugging Levels

### 1. Application Layer Debugging

#### Request/Response Flow
- **Entry Point**: HTTP requests through FastAPI middleware
- **Authentication**: API key validation and workspace isolation
- **Rate Limiting**: Redis-based token bucket implementation
- **Business Logic**: Context memory operations and LLM proxying
- **Response**: JSON responses with proper error handling

#### Common Issues:
- Authentication failures
- Rate limiting triggers
- Request validation errors
- Business logic exceptions
- Response formatting issues

### 2. Service Layer Debugging

#### Context Memory Service
- **Ingestion**: Processing and storing context data
- **Recall**: Vector similarity search and token budgeting
- **Working Sets**: Context aggregation and optimization
- **Embeddings**: Vector generation and storage

#### LLM Gateway Service
- **Model Routing**: Selecting appropriate LLM models
- **Request Proxying**: Forwarding to OpenRouter
- **Stream Handling**: Managing streaming responses
- **Usage Tracking**: Recording token usage and quotas

#### Common Issues:
- Database connection problems
- Vector search failures
- Embedding generation errors
- External API timeouts
- Token budget miscalculations

### 3. Infrastructure Layer Debugging

#### Database Layer
- **PostgreSQL**: Connection pooling and query performance
- **pgvector**: Vector operations and indexing
- **Migrations**: Schema changes and data integrity

#### Caching Layer
- **Redis**: Connection health and memory usage
- **Rate Limiting**: Token bucket state consistency
- **Task Queue**: Background job processing

#### Common Issues:
- Connection pool exhaustion
- Slow query performance
- Redis memory pressure
- Queue processing delays
- Migration failures

## Debugging Tools and Techniques

### 1. Structured Logging

#### Configuration
```python
# Production: JSON format
{
    "timestamp": "2025-01-20T10:30:00.000Z",
    "level": "error",
    "logger_name": "app.api.llm_gateway",
    "service": "context-memory-gateway",
    "environment": "production",
    "method": "POST",
    "url": "/v1/chat/completions",
    "status_code": 500,
    "exception": "ConnectionError",
    "client_ip": "192.168.1.100"
}

# Development: Human-readable format
[2025-01-20 10:30:00] ERROR app.api.llm_gateway: Connection error in chat completion
```

#### Key Log Categories
- **Request Flow**: `request_started`, `request_completed`
- **Authentication**: `auth_success`, `auth_failure`
- **Rate Limiting**: `rate_limit_applied`, `rate_limit_exceeded`
- **Database**: `db_query_slow`, `db_connection_error`
- **External APIs**: `openrouter_request`, `openrouter_error`
- **Background Tasks**: `job_started`, `job_completed`, `job_failed`

#### Sensitive Data Filtering
- Automatic redaction of API keys, tokens, passwords
- PII filtering in context data
- Configurable debug logging for development

### 2. Error Tracking with Sentry

#### Error Categories
- **Application Errors**: Unhandled exceptions and business logic failures
- **Integration Errors**: External API failures and timeouts
- **Infrastructure Errors**: Database connectivity and Redis issues
- **Validation Errors**: Request parsing and data validation failures

#### Error Context
- Request metadata (method, URL, headers)
- User context (workspace, API key hash)
- Application state (database connections, Redis status)
- Custom tags for categorization

### 3. Metrics and Monitoring

#### Prometheus Metrics
- **Request Metrics**: Request rate, response time, error rate
- **Authentication Metrics**: API key usage, authentication failures
- **Rate Limiting Metrics**: Token consumption, rate limit hits
- **Database Metrics**: Connection pool usage, query performance
- **External API Metrics**: OpenRouter response times and errors

#### Health Checks
- **Application Health**: `/health` endpoint status
- **Database Health**: PostgreSQL connection and query tests
- **Redis Health**: Cache connectivity and operation tests
- **External Dependencies**: OpenRouter API availability

### 4. Development Debugging

#### Local Development Setup
```bash
# Enable debug mode
export DEBUG=true
export LOG_LEVEL=DEBUG

# Start with debugging
./scripts/dev.sh start

# View application logs
./scripts/dev.sh logs app

# Access application shell
./scripts/dev.sh shell app
```

#### IDE Debugging
- **VS Code**: Python debugger with FastAPI support
- **PyCharm**: Remote debugging capabilities
- **Breakpoints**: Strategic placement in request flow
- **Variable Inspection**: Real-time state examination

## Common Debugging Scenarios

### 1. Authentication Issues

#### Symptoms
- 401 Unauthorized responses
- "Invalid API key" errors
- Workspace isolation failures

#### Debugging Steps
1. **Verify API Key Format**
   ```bash
   # Check API key prefix and length
   echo $API_KEY | grep "^ctx_" | wc -c
   ```

2. **Check Database Records**
   ```sql
   SELECT key_hash, workspace_id, active, created_at 
   FROM api_keys 
   WHERE key_hash = '<hashed_key>';
   ```

3. **Review Authentication Logs**
   ```bash
   # Search for authentication events
   grep "auth_failure" /var/log/app.log
   ```

#### Common Solutions
- Regenerate API keys with proper format
- Verify workspace associations
- Check API key expiration and status
- Review CORS configuration for frontend apps

### 2. Rate Limiting Problems

#### Symptoms
- 429 Too Many Requests responses
- Unexpected rate limit triggers
- Token bucket inconsistencies

#### Debugging Steps
1. **Check Redis State**
   ```bash
   redis-cli GET "rate_limit:api_key:<key_hash>"
   redis-cli GET "quota:daily:<workspace_id>"
   ```

2. **Review Rate Limit Configuration**
   ```python
   # Check current limits
   print(f"RPM Limit: {settings.RATE_LIMIT_REQUESTS}")
   print(f"Window: {settings.RATE_LIMIT_WINDOW}")
   print(f"Daily Quota: {settings.DEFAULT_DAILY_QUOTA_TOKENS}")
   ```

3. **Analyze Usage Patterns**
   ```sql
   SELECT SUM(tokens_used), COUNT(*) 
   FROM usage_events 
   WHERE workspace_id = '<workspace_id>' 
   AND created_at >= NOW() - INTERVAL '1 day';
   ```

#### Common Solutions
- Adjust rate limit configuration
- Clear Redis cache for testing
- Implement quota reset mechanisms
- Review client request patterns

### 3. Context Memory Failures

#### Symptoms
- Empty recall results
- Slow vector search performance
- Embedding generation errors

#### Debugging Steps
1. **Verify Vector Data**
   ```sql
   SELECT COUNT(*) FROM context_items 
   WHERE workspace_id = '<workspace_id>' 
   AND embedding IS NOT NULL;
   ```

2. **Test Vector Search**
   ```sql
   SELECT title, content, similarity 
   FROM context_items 
   WHERE workspace_id = '<workspace_id>'
   ORDER BY embedding <=> '<query_embedding>' 
   LIMIT 10;
   ```

3. **Check Embedding Service**
   ```bash
   # Test OpenRouter embeddings
   curl -X POST "https://openrouter.ai/api/v1/embeddings" \
   -H "Authorization: Bearer $OPENROUTER_API_KEY" \
   -d '{"input": "test", "model": "text-embedding-3-small"}'
   ```

#### Common Solutions
- Regenerate embeddings for corrupted data
- Optimize vector indexes
- Verify embedding model availability
- Implement embedding fallback strategies

### 4. LLM Gateway Issues

#### Symptoms
- Connection timeouts to OpenRouter
- Model availability errors
- Streaming response failures

#### Debugging Steps
1. **Test External Connectivity**
   ```bash
   curl -I https://openrouter.ai/api/v1/models
   ```

2. **Verify Model Availability**
   ```bash
   # Check model catalog sync
   tail -f /var/log/app.log | grep "model_sync"
   ```

3. **Monitor Request Proxying**
   ```bash
   # Track OpenRouter requests
   grep "openrouter_request" /var/log/app.log | tail -20
   ```

#### Common Solutions
- Implement circuit breakers for external APIs
- Add model fallback mechanisms
- Optimize connection pooling
- Review proxy configuration

## Testing and Validation

### 1. Unit Testing Strategy

#### Test Categories
- **Service Layer Tests**: Business logic validation
- **API Endpoint Tests**: Request/response handling
- **Database Tests**: Model and query testing
- **Authentication Tests**: Security mechanism validation

#### Test Configuration
```python
# Minimal test fixtures with mocked dependencies
@pytest.fixture
def mock_db():
    return FakeAsyncDB()

@pytest.fixture 
def auth_headers():
    return {"Authorization": "Bearer cmg_test_api_key_12345"}
```

### 2. Integration Testing

#### Database Integration
- Connection pooling under load
- Transaction isolation and rollback
- Migration compatibility testing

#### External API Integration
- OpenRouter API mocking and error simulation
- Network timeout and retry handling
- Rate limiting compliance testing

### 3. End-to-End Testing

#### Critical User Flows
- API key creation and authentication
- Context ingestion and recall workflows
- LLM completion requests with context
- Admin interface operations

#### Performance Testing
- Load testing with realistic traffic patterns
- Memory usage monitoring under stress
- Database performance benchmarking

## Monitoring and Alerting

### 1. Application Metrics

#### Key Performance Indicators
- **Response Time**: P50, P95, P99 latencies
- **Error Rate**: 4xx and 5xx response percentages
- **Throughput**: Requests per second
- **Token Usage**: Daily quota consumption rates

#### Custom Metrics
- Context recall effectiveness
- Embedding generation latency
- OpenRouter API response times
- Background job processing rates

### 2. Infrastructure Metrics

#### Database Monitoring
- Connection pool utilization
- Query execution times
- Vector search performance
- Storage usage growth

#### Redis Monitoring
- Memory usage and eviction rates
- Connection count and latency
- Queue depth and processing times
- Cache hit rates

### 3. Alert Configuration

#### Critical Alerts
- Application down or unhealthy
- Database connection failures
- High error rates (>5%)
- External API unavailability

#### Warning Alerts
- High response times (>2s P95)
- Memory usage above 80%
- Queue processing delays
- Quota approaching limits

## Recovery Procedures

### 1. Service Recovery

#### Application Restart
```bash
# Graceful restart with health checks
./scripts/dev.sh restart app
./scripts/dev.sh health-check
```

#### Database Recovery
```bash
# Connection pool reset
./scripts/dev.sh shell app
python -c "from app.db.session import engine; engine.dispose()"
```

#### Cache Recovery
```bash
# Redis cache flush (if safe)
redis-cli FLUSHDB
```

### 2. Data Recovery

#### Backup Restoration
- PostgreSQL point-in-time recovery
- Redis persistence restoration
- Context data re-ingestion procedures

#### Consistency Checks
- Workspace data integrity validation
- API key hash verification
- Usage quota reconciliation

### 3. Monitoring Recovery

#### Service Health Validation
- All health checks passing
- Metrics collection resumed
- Error rates normalized
- Response times within SLA

## Best Practices

### 1. Debugging Approach

#### Systematic Investigation
1. **Reproduce**: Create minimal reproduction cases
2. **Isolate**: Identify affected components
3. **Analyze**: Review logs, metrics, and traces
4. **Hypothesize**: Form testable theories
5. **Validate**: Test fixes in controlled environment
6. **Monitor**: Verify resolution effectiveness

### 2. Log Analysis

#### Structured Query Patterns
```bash
# Error correlation
jq 'select(.level == "error") | {timestamp, logger_name, exception}' app.log

# Performance analysis
jq 'select(.status_code >= 400) | {url, method, status_code, response_time}' app.log

# Authentication patterns
jq 'select(.message | contains("auth")) | {timestamp, client_ip, workspace_id}' app.log
```

### 3. Prevention Strategies

#### Code Quality
- Comprehensive error handling
- Input validation and sanitization
- Resource cleanup and connection management
- Circuit breakers for external dependencies

#### Monitoring
- Proactive alerting thresholds
- Regular health check validation
- Performance regression detection
- Capacity planning based on metrics

#### Documentation
- Runbook maintenance for common issues
- Architecture decision recording
- Debugging guide updates
- Team knowledge sharing