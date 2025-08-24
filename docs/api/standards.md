# API Standards and Best Practices

## Overview
This document defines the API standards, conventions, and best practices for the Context Memory Gateway. All API endpoints should follow these guidelines to ensure consistency, reliability, and ease of use.

## Response Format Standards

### Envelope Pattern
All API responses should use a consistent envelope structure:

```json
{
  "success": boolean,
  "data": object | array | null,
  "error": {
    "code": string,
    "message": string,
    "details": object
  } | null,
  "meta": {
    "timestamp": "ISO8601",
    "request_id": "uuid",
    "version": "string",
    "pagination": {
      "page": number,
      "per_page": number,
      "total": number,
      "total_pages": number,
      "has_next": boolean,
      "has_prev": boolean
    } | null
  }
}
```

### Success Response Example
```json
{
  "success": true,
  "data": {
    "id": "ctx_123",
    "content": "Sample context data",
    "created_at": "2024-01-15T10:30:00Z"
  },
  "error": null,
  "meta": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "version": "v1"
  }
}
```

### Error Response Example
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input parameters",
    "details": {
      "field": "content",
      "reason": "Content cannot be empty"
    }
  },
  "meta": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "version": "v1"
  }
}
```

## Pagination Standards

### Query Parameters
- `page`: Page number (1-based, default: 1)
- `per_page`: Items per page (default: 20, max: 100)
- `sort`: Sort field (default varies by endpoint)
- `order`: Sort order ('asc' or 'desc', default: 'desc')

### Response Pagination Metadata
```json
{
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 150,
    "total_pages": 8,
    "has_next": true,
    "has_prev": false
  }
}
```

### Example Paginated Response
```json
{
  "success": true,
  "data": [
    {"id": 1, "content": "Item 1"},
    {"id": 2, "content": "Item 2"}
  ],
  "error": null,
  "meta": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "version": "v1",
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total": 150,
      "total_pages": 8,
      "has_next": true,
      "has_prev": false
    }
  }
}
```

## Filtering Standards

### Query Parameters
- Field-specific filters: `filter[field_name]=value`
- Date range filters: `filter[created_after]=2024-01-01&filter[created_before]=2024-01-31`
- Text search: `q=search_term`
- Status filters: `filter[status]=active`

### Supported Filter Operators
- `eq`: Equal (default)
- `ne`: Not equal
- `gt`: Greater than
- `gte`: Greater than or equal
- `lt`: Less than
- `lte`: Less than or equal
- `in`: In list (comma-separated values)
- `like`: Text contains (case-insensitive)

### Filter Examples
```
GET /api/v1/context?filter[user_id]=123&filter[status]=active
GET /api/v1/context?filter[created_at][gte]=2024-01-01&filter[created_at][lt]=2024-02-01
GET /api/v1/context?q=machine%20learning&filter[tags][in]=ai,ml
```

## HTTP Status Codes

### Success Codes
- `200 OK`: Successful GET, PUT, PATCH requests
- `201 Created`: Successful POST requests
- `204 No Content`: Successful DELETE requests

### Client Error Codes
- `400 Bad Request`: Invalid request format or parameters
- `401 Unauthorized`: Authentication required
- `403 Forbidden`: Access denied
- `404 Not Found`: Resource not found
- `409 Conflict`: Resource conflict (e.g., duplicate)
- `422 Unprocessable Entity`: Validation errors
- `429 Too Many Requests`: Rate limit exceeded

### Server Error Codes
- `500 Internal Server Error`: Unexpected server error
- `502 Bad Gateway`: Upstream service error
- `503 Service Unavailable`: Service temporarily unavailable
- `504 Gateway Timeout`: Upstream service timeout

## Error Code Standards

### Error Code Format
Error codes should follow the pattern: `CATEGORY_SPECIFIC_ERROR`

### Categories
- `VALIDATION_ERROR`: Input validation failures
- `AUTHENTICATION_ERROR`: Authentication failures
- `AUTHORIZATION_ERROR`: Permission/access errors
- `RESOURCE_ERROR`: Resource-related errors (not found, conflict)
- `RATE_LIMIT_ERROR`: Rate limiting errors
- `SYSTEM_ERROR`: Internal system errors
- `INTEGRATION_ERROR`: External service integration errors

### Common Error Codes
```json
{
  "VALIDATION_ERROR": "Invalid input parameters",
  "AUTHENTICATION_ERROR": "Invalid or missing authentication credentials",
  "AUTHORIZATION_ERROR": "Insufficient permissions for this operation",
  "RESOURCE_NOT_FOUND": "The requested resource was not found",
  "RESOURCE_CONFLICT": "Resource already exists or conflicts with existing data",
  "RATE_LIMIT_EXCEEDED": "API request rate limit exceeded",
  "SYSTEM_ERROR": "An internal system error occurred",
  "INTEGRATION_ERROR": "External service integration failed"
}
```

## Request Standards

### Content Types
- Request bodies should use `application/json`
- File uploads should use `multipart/form-data`
- Query parameters should be URL-encoded

### Headers
Required headers:
- `Content-Type`: Request content type
- `Accept`: Expected response content type
- `X-API-Key` or `Authorization`: Authentication

Optional headers:
- `X-Request-ID`: Client-provided request ID
- `X-Correlation-ID`: For distributed tracing
- `X-Client-Version`: Client application version

### Request ID Handling
- If client provides `X-Request-ID`, use it
- Otherwise, generate UUID for request tracking
- Include in response `meta.request_id`
- Use for logging and debugging

## Versioning Standards

### URL Versioning
All API endpoints should include version in the URL path:
```
/api/v1/context
/api/v2/llm/chat
```

### Version Header Support
Alternative versioning via headers:
```
Accept: application/json; version=v1
X-API-Version: v1
```

### Backward Compatibility
- Maintain backward compatibility within major versions
- Deprecate features gradually with proper notices
- Provide migration guides for breaking changes

## Rate Limiting

### Headers
All responses should include rate limit headers:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1640995200
X-RateLimit-Window: 3600
```

### Rate Limit Response
When rate limit is exceeded:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "API request rate limit exceeded",
    "details": {
      "limit": 1000,
      "window_seconds": 3600,
      "retry_after": 300
    }
  },
  "meta": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "version": "v1"
  }
}
```

## Security Standards

### Authentication
- Use API keys for service-to-service authentication
- Support JWT tokens for user authentication
- Include rate limiting per API key/user

### Input Validation
- Validate all input parameters
- Sanitize user inputs to prevent injection attacks
- Limit request payload sizes
- Validate content types

### CSRF Protection
- Use CSRF tokens for web interface requests
- Exempt API endpoints from CSRF protection
- Validate tokens on state-changing operations

## Monitoring and Observability

### Logging Standards
All API requests should log:
- Request ID
- HTTP method and path
- Status code
- Response time
- User/API key identifier
- Error details (if any)

### Metrics
Track key metrics:
- Request count by endpoint
- Response times (p50, p95, p99)
- Error rates by status code
- Rate limit violations
- Authentication failures

### Tracing
- Include correlation IDs in requests
- Trace requests across services
- Monitor external API calls
- Track database query performance

## Documentation Standards

### OpenAPI/Swagger
- Maintain OpenAPI specifications for all endpoints
- Include request/response examples
- Document all parameters and fields
- Provide clear descriptions

### Endpoint Documentation
Each endpoint should include:
- Purpose and functionality
- Authentication requirements
- Request parameters
- Response format
- Error scenarios
- Rate limiting information
- Code examples in multiple languages

## Testing Standards

### API Testing
- Unit tests for all endpoint handlers
- Integration tests for complete workflows
- Contract tests for API specifications
- Performance tests for critical endpoints

### Test Data
- Use realistic test data
- Test edge cases and error conditions
- Validate response format compliance
- Test rate limiting behavior

## Implementation Checklist

### For New Endpoints
- [ ] Follow URL naming conventions
- [ ] Implement standard response format
- [ ] Add proper error handling
- [ ] Include authentication/authorization
- [ ] Add rate limiting
- [ ] Implement input validation
- [ ] Add logging and metrics
- [ ] Write tests
- [ ] Update API documentation
- [ ] Add OpenAPI specification

### For Existing Endpoints
- [ ] Audit response format compliance
- [ ] Standardize error responses
- [ ] Add missing pagination support
- [ ] Implement proper filtering
- [ ] Add rate limiting headers
- [ ] Update documentation
- [ ] Add missing tests
- [ ] Verify security measures
