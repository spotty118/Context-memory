# Context Memory + LLM Gateway API Documentation

Complete API reference for the Context Memory + LLM Gateway service.

## Base URL

- **Development**: `http://localhost:8000`
- **Production**: `https://your-domain.com`

## Authentication

All API requests require authentication using an API key in the Authorization header:

```http
Authorization: Bearer cmg_your_api_key_here
```

### API Key Format

API keys follow the format: `cmg_` followed by 32 alphanumeric characters.

Example: `cmg_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p`

## Rate Limiting

API requests are rate-limited per API key:

- **Default**: 100 requests per minute
- **Burst**: Up to 200 requests in a short burst
- **Headers**: Rate limit information is returned in response headers

```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1642781234
```

## Response Format

All API responses follow a consistent format:

### Success Response
```json
{
  "status": "success",
  "data": { ... },
  "metadata": {
    "request_id": "req_1234567890",
    "timestamp": "2025-01-20T10:00:00Z",
    "processing_time_ms": 125
  }
}
```

### Error Response
```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "The request is invalid",
    "details": {
      "field": "model",
      "issue": "Model not found"
    }
  },
  "request_id": "req_1234567890",
  "timestamp": "2025-01-20T10:00:00Z"
}
```

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_REQUEST` | 400 | Request validation failed |
| `UNAUTHORIZED` | 401 | Invalid or missing API key |
| `FORBIDDEN` | 403 | Access denied |
| `NOT_FOUND` | 404 | Resource not found |
| `RATE_LIMITED` | 429 | Rate limit exceeded |
| `QUOTA_EXCEEDED` | 429 | Usage quota exceeded |
| `INTERNAL_ERROR` | 500 | Internal server error |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily unavailable |

---

## Health Check Endpoints

### Basic Health Check

Check if the service is running.

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-01-20T10:00:00Z"
}
```

### Detailed Health Check

Get detailed system status including dependencies.

```http
GET /health/detailed
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-01-20T10:00:00Z",
  "services": {
    "database": {
      "status": "healthy",
      "response_time_ms": 5
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 2
    },
    "openrouter": {
      "status": "healthy",
      "response_time_ms": 150
    }
  }
}
```

---

## Model Management

### List Models

Get all available AI models.

```http
GET /v1/models
Authorization: Bearer <api_key>
```

**Query Parameters:**
- `provider` (optional): Filter by provider (e.g., `openai`, `anthropic`)
- `supports_streaming` (optional): Filter by streaming support (`true`/`false`)
- `supports_functions` (optional): Filter by function calling support (`true`/`false`)

**Response:**
```json
{
  "status": "success",
  "data": {
    "models": [
      {
        "id": "openai/gpt-4",
        "name": "GPT-4",
        "provider": "openai",
        "description": "Most capable GPT-4 model",
        "context_length": 8192,
        "input_price": 0.03,
        "output_price": 0.06,
        "supports_streaming": true,
        "supports_functions": true,
        "status": "available"
      }
    ],
    "total": 1
  }
}
```

### Get Model Details

Get detailed information about a specific model.

```http
GET /v1/models/{model_id}
Authorization: Bearer <api_key>
```

**Path Parameters:**
- `model_id`: Model identifier (e.g., `openai/gpt-4`)

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "openai/gpt-4",
    "name": "GPT-4",
    "provider": "openai",
    "description": "Most capable GPT-4 model",
    "context_length": 8192,
    "input_price": 0.03,
    "output_price": 0.06,
    "supports_streaming": true,
    "supports_functions": true,
    "status": "available",
    "usage_stats": {
      "total_requests": 1500,
      "total_tokens": 750000,
      "avg_response_time_ms": 1250
    }
  }
}
```

---

## LLM Gateway

### Chat Completions

Generate chat completions using AI models.

```http
POST /v1/chat/completions
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "model": "openai/gpt-4",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user", 
      "content": "Hello, how are you?"
    }
  ],
  "max_tokens": 150,
  "temperature": 0.7,
  "top_p": 1,
  "frequency_penalty": 0,
  "presence_penalty": 0,
  "stream": false,
  "stop": null,
  "functions": null,
  "function_call": null
}
```

**Optional Context Memory Parameters:**
```json
{
  "thread_id": "session-123",
  "inject_context": true,
  "context_purpose": "Continue discussion about project requirements",
  "context_token_budget": 2000
}
```

**Response (Non-streaming):**
```json
{
  "id": "chatcmpl-1234567890",
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
    "prompt_tokens": 20,
    "completion_tokens": 15,
    "total_tokens": 35
  },
  "context_injection": {
    "items_injected": 3,
    "tokens_used": 450,
    "items": ["S001", "S002", "E001"]
  }
}
```

### Streaming Chat Completions

For streaming responses, set `"stream": true` in the request body.

**Response (Streaming):**
```
data: {"id":"chatcmpl-1234567890","object":"chat.completion.chunk","created":1642781234,"model":"openai/gpt-4","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-1234567890","object":"chat.completion.chunk","created":1642781234,"model":"openai/gpt-4","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-1234567890","object":"chat.completion.chunk","created":1642781234,"model":"openai/gpt-4","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":null}]}

data: {"id":"chatcmpl-1234567890","object":"chat.completion.chunk","created":1642781234,"model":"openai/gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

---

## Context Memory

### Ingest Content

Add content to the context memory system.

```http
POST /v1/ingest
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "thread_id": "project-auth-123",
  "content_type": "chat",
  "content": "User: We need to implement user authentication for the web app.\nAssistant: I recommend using JWT tokens for session management and bcrypt for password hashing.\nUser: Great! Let's also add OAuth integration with Google and GitHub.",
  "metadata": {
    "source": "chat_session",
    "timestamp": "2025-01-20T10:00:00Z",
    "user_id": "user_123",
    "session_id": "session_456"
  }
}
```

**Content Types:**
- `chat`: Conversation content
- `diff`: Code changes and diffs
- `logs`: Error logs and debug output

**Response:**
```json
{
  "status": "success",
  "data": {
    "thread_id": "project-auth-123",
    "items_created": {
      "semantic_items": 3,
      "episodic_items": 0,
      "artifacts": 0
    },
    "processing_time_ms": 250,
    "items": [
      {
        "id": "S001",
        "type": "semantic",
        "item_type": "decision",
        "content": "Use JWT tokens for session management",
        "salience": 0.85
      },
      {
        "id": "S002", 
        "type": "semantic",
        "item_type": "requirement",
        "content": "Implement user authentication for web app",
        "salience": 0.90
      },
      {
        "id": "S003",
        "type": "semantic", 
        "item_type": "requirement",
        "content": "Add OAuth integration with Google and GitHub",
        "salience": 0.80
      }
    ]
  }
}
```

### Recall Context

Retrieve relevant context for a given purpose.

```http
POST /v1/recall
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "thread_id": "project-auth-123",
  "purpose": "Continue implementing authentication system with OAuth",
  "token_budget": 4000,
  "include_artifacts": true,
  "focus_areas": ["authentication", "oauth", "security"],
  "max_items": 20
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "context_items": {
      "semantic_items": [
        {
          "id": "S001",
          "item_type": "decision",
          "content": "Use JWT tokens for session management",
          "salience": 0.85,
          "score": 0.92,
          "usage_count": 5,
          "last_accessed": "2025-01-20T09:30:00Z"
        }
      ],
      "episodic_items": [],
      "artifacts": [
        {
          "id": "CODE001",
          "title": "Authentication middleware",
          "file_path": "/src/middleware/auth.js",
          "content": "// JWT authentication middleware...",
          "usage_count": 3
        }
      ]
    },
    "total_items": 5,
    "tokens_used": 3850,
    "tokens_available": 150
  }
}
```

### Get Working Set

Generate a structured working set for a specific purpose.

```http
POST /v1/workingset
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "thread_id": "project-auth-123",
  "purpose": "Implement OAuth authentication with JWT tokens",
  "token_budget": 8000,
  "include_artifacts": true,
  "focus_areas": ["authentication", "oauth", "jwt", "security"]
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "working_set": {
      "mission": "Implement OAuth authentication with JWT tokens for the web application to enable secure user login via Google and GitHub providers.",
      "constraints": [
        "Must support both Google and GitHub OAuth providers",
        "Use JWT tokens for session management",
        "Implement secure token storage and validation",
        "Follow OAuth 2.0 security best practices"
      ],
      "focus_decisions": [
        "Use JWT tokens for session management",
        "Implement OAuth2 flows for Google and GitHub",
        "Store refresh tokens securely"
      ],
      "focus_tasks": [
        "Set up OAuth2 client credentials for Google and GitHub",
        "Implement JWT token generation and validation utilities",
        "Create OAuth2 authorization and callback endpoints",
        "Add authentication middleware to protect routes",
        "Implement token refresh mechanism"
      ],
      "runbook": [
        "1. Register OAuth applications with Google and GitHub",
        "2. Configure OAuth2 client credentials in environment",
        "3. Install and configure OAuth2 client library",
        "4. Implement JWT utilities (generate, verify, refresh)",
        "5. Create OAuth2 authorization endpoints (/auth/google, /auth/github)",
        "6. Implement OAuth2 callback handlers (/auth/callback/google, /auth/callback/github)",
        "7. Set up secure token storage (httpOnly cookies)",
        "8. Add authentication middleware to protect API routes",
        "9. Test OAuth flows with both providers",
        "10. Implement logout and token revocation"
      ],
      "artifacts": [
        {
          "id": "CODE001",
          "title": "Authentication middleware",
          "description": "JWT authentication middleware for Express.js"
        },
        {
          "id": "CODE002",
          "title": "OAuth2 configuration",
          "description": "OAuth2 client configuration for Google and GitHub"
        }
      ],
      "citations": {
        "semantic": ["S001", "S002", "S003"],
        "episodic": [],
        "artifacts": ["CODE001", "CODE002"]
      },
      "open_questions": [
        "Should we implement automatic token refresh or require manual re-authentication?",
        "How long should JWT access tokens be valid?",
        "Should we support multiple concurrent sessions per user?",
        "Do we need to implement OAuth scope management for different permission levels?"
      ]
    },
    "tokens_used": 7850,
    "tokens_available": 150
  }
}
```

### Expand by ID

Get detailed information about a specific context item.

```http
GET /v1/expand/{item_id}
Authorization: Bearer <api_key>
```

**Path Parameters:**
- `item_id`: Context item ID (e.g., `S001`, `E001`, `CODE001`)

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "S001",
    "type": "semantic",
    "item_type": "decision",
    "content": "Use JWT tokens for session management in the authentication system",
    "salience": 0.85,
    "usage_count": 5,
    "created_at": "2025-01-20T10:00:00Z",
    "last_accessed_at": "2025-01-20T11:30:00Z",
    "thread_id": "project-auth-123",
    "metadata": {
      "source": "chat_session",
      "confidence": 0.92,
      "related_items": ["S002", "S003"]
    },
    "embedding": null
  }
}
```

### Get Raw Content

Get the raw content of a context item without metadata.

```http
GET /v1/expand/{item_id}/raw
Authorization: Bearer <api_key>
```

**Response:**
```
Use JWT tokens for session management in the authentication system
```

### Provide Feedback

Provide feedback on context items to improve relevance.

```http
POST /v1/feedback
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "item_id": "S001",
  "feedback_type": "helpful",
  "value": 1.0,
  "comment": "This decision was very relevant for the current task"
}
```

**Feedback Types:**
- `helpful`: Item was useful (value: 0.0 to 1.0)
- `not_helpful`: Item was not useful (value: -1.0 to 0.0)
- `outdated`: Item is no longer relevant (value: -1.0)
- `duplicate`: Item is a duplicate (value: -0.5)

**Response:**
```json
{
  "status": "success",
  "data": {
    "item_id": "S001",
    "feedback_recorded": true,
    "previous_salience": 0.85,
    "updated_salience": 0.90,
    "salience_change": 0.05
  }
}
```

---

## Worker Management

### Get Queue Statistics

Get statistics for all background job queues.

```http
GET /v1/workers/queues/stats
Authorization: Bearer <api_key>
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "queues": {
      "default": {
        "length": 5,
        "failed_count": 0,
        "processed_count": 1250,
        "workers": 2
      },
      "embeddings": {
        "length": 12,
        "failed_count": 1,
        "processed_count": 450,
        "workers": 1
      },
      "sync": {
        "length": 0,
        "failed_count": 0,
        "processed_count": 25,
        "workers": 1
      }
    }
  }
}
```

### Enqueue Job

Enqueue a background job for processing.

```http
POST /v1/workers/jobs
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "job_type": "sync_model_catalog",
  "parameters": {
    "force_update": true
  },
  "queue_name": "sync",
  "job_timeout": 300
}
```

**Available Job Types:**
- `sync_model_catalog`: Sync model catalog from OpenRouter
- `cleanup_deprecated_models`: Clean up deprecated models
- `generate_embeddings`: Generate embeddings for context items
- `batch_generate_embeddings`: Generate embeddings in batch
- `cleanup_old_context_items`: Clean up old context items
- `cleanup_old_request_logs`: Clean up old request logs
- `aggregate_daily_usage_stats`: Aggregate usage statistics
- `calculate_context_memory_stats`: Calculate context memory statistics

**Response:**
```json
{
  "status": "success",
  "data": {
    "job_id": "job_1234567890",
    "status": "queued",
    "queue": "sync",
    "created_at": "2025-01-20T10:00:00Z"
  }
}
```

### Get Job Status

Get the status of a background job.

```http
GET /v1/workers/jobs/{job_id}
Authorization: Bearer <api_key>
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "job_1234567890",
    "status": "finished",
    "queue": "sync",
    "created_at": "2025-01-20T10:00:00Z",
    "started_at": "2025-01-20T10:00:05Z",
    "finished_at": "2025-01-20T10:02:30Z",
    "result": {
      "models_synced": 50,
      "models_updated": 5,
      "models_added": 2,
      "processing_time_ms": 145000
    }
  }
}
```

**Job Statuses:**
- `queued`: Job is waiting to be processed
- `started`: Job is currently being processed
- `finished`: Job completed successfully
- `failed`: Job failed with an error
- `cancelled`: Job was cancelled

### Cancel Job

Cancel a background job.

```http
DELETE /v1/workers/jobs/{job_id}
Authorization: Bearer <api_key>
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "job_id": "job_1234567890",
    "status": "cancelled",
    "message": "Job cancelled successfully"
  }
}
```

---

## Convenience Endpoints

### Trigger Model Sync

Immediately trigger model catalog synchronization.

```http
POST /v1/workers/sync/models
Authorization: Bearer <api_key>
```

### Trigger Embedding Generation

Generate embeddings for specific context items.

```http
POST /v1/workers/embeddings/generate
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Request Body:**
```json
{
  "item_type": "semantic",
  "item_ids": ["S001", "S002", "S003"]
}
```

### Trigger Context Cleanup

Clean up old context memory items.

```http
POST /v1/workers/cleanup/context?days_old=30
Authorization: Bearer <api_key>
```

### Trigger Usage Aggregation

Aggregate usage statistics for a specific date.

```http
POST /v1/workers/analytics/aggregate?date=2025-01-20
Authorization: Bearer <api_key>
```

---

## Webhooks (Future)

*Webhook functionality is planned for future releases.*

### Webhook Events

- `context.item.created`: New context item created
- `context.item.updated`: Context item updated
- `usage.quota.warning`: Usage quota warning (80% reached)
- `usage.quota.exceeded`: Usage quota exceeded
- `model.sync.completed`: Model catalog sync completed
- `worker.job.failed`: Background job failed

---

## SDKs and Libraries

Official SDKs are planned for:

- Python
- JavaScript/TypeScript
- Go
- Java

Community SDKs and integrations are welcome!

---

## API Versioning

The API uses URL-based versioning:

- Current version: `v1`
- Base path: `/v1/`

Breaking changes will result in a new API version. Non-breaking changes (new fields, new endpoints) will be added to the current version.

---

## Support

- **API Issues**: Create an issue in the GitHub repository
- **Feature Requests**: Use GitHub Discussions
- **Documentation**: Contribute improvements via pull requests

