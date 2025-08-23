"""
Custom exception hierarchy for Context Memory Gateway.

This module defines specific exceptions for different types of errors
that can occur in the application, providing better error handling
and more informative error messages.
"""
from typing import Optional, Dict, Any
from datetime import datetime


class ContextMemoryError(Exception):
    """Base exception for all Context Memory Gateway errors."""
    
    def __init__(
        self, 
        message: str, 
        error_code: str = "GENERAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.status_code = status_code
        self.timestamp = datetime.utcnow()
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "status_code": self.status_code
        }


# Authentication and Authorization Errors

class AuthenticationError(ContextMemoryError):
    """Base class for authentication-related errors."""
    
    def __init__(self, message: str = "Authentication failed", **kwargs):
        code = kwargs.pop("error_code", "AUTHENTICATION_FAILED")
        status = kwargs.pop("status_code", 401)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class InvalidAPIKeyError(AuthenticationError):
    """Raised when an invalid API key is provided."""
    
    def __init__(self, message: str = "Invalid API key", **kwargs):
        super().__init__(message, error_code="INVALID_API_KEY", **kwargs)


class InactiveAPIKeyError(AuthenticationError):
    """Raised when an inactive API key is used."""
    
    def __init__(self, message: str = "API key is inactive", **kwargs):
        super().__init__(message, error_code="INACTIVE_API_KEY", **kwargs)


class MissingAPIKeyError(AuthenticationError):
    """Raised when no API key is provided."""
    
    def __init__(self, message: str = "API key required", **kwargs):
        super().__init__(message, error_code="MISSING_API_KEY", **kwargs)


class AuthorizationError(ContextMemoryError):
    """Base class for authorization-related errors."""
    
    def __init__(self, message: str = "Access denied", **kwargs):
        code = kwargs.pop("error_code", "ACCESS_DENIED")
        status = kwargs.pop("status_code", 403)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class InsufficientPermissionsError(AuthorizationError):
    """Raised when user lacks required permissions."""
    
    def __init__(self, message: str = "Insufficient permissions", **kwargs):
        super().__init__(message, error_code="INSUFFICIENT_PERMISSIONS", **kwargs)


# Resource and Rate Limiting Errors

class ResourceError(ContextMemoryError):
    """Base class for resource-related errors."""
    
    def __init__(self, message: str, **kwargs):
        code = kwargs.pop("error_code", "RESOURCE_ERROR")
        status = kwargs.pop("status_code", 400)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class TokenBudgetExceededError(ResourceError):
    """Raised when token budget is exceeded."""
    
    def __init__(
        self, 
        message: str = "Token budget exceeded", 
        requested_tokens: Optional[int] = None,
        available_tokens: Optional[int] = None,
        **kwargs
    ):
        details = {}
        if requested_tokens is not None:
            details["requested_tokens"] = requested_tokens
        if available_tokens is not None:
            details["available_tokens"] = available_tokens
        
        super().__init__(
            message, 
            error_code="TOKEN_BUDGET_EXCEEDED", 
            details=details,
            status_code=429,
            **kwargs
        )


class QuotaExceededError(ResourceError):
    """Raised when usage quota is exceeded."""
    
    def __init__(
        self, 
        message: str = "Usage quota exceeded", 
        quota_type: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if quota_type:
            details["quota_type"] = quota_type
        
        super().__init__(
            message, 
            error_code="QUOTA_EXCEEDED", 
            details=details,
            status_code=429,
            **kwargs
        )


class RateLimitExceededError(ResourceError):
    """Raised when rate limit is exceeded."""
    
    def __init__(
        self, 
        message: str = "Rate limit exceeded", 
        retry_after: Optional[int] = None,
        **kwargs
    ):
        details = {}
        if retry_after is not None:
            details["retry_after_seconds"] = retry_after
        
        super().__init__(
            message, 
            error_code="RATE_LIMIT_EXCEEDED", 
            details=details,
            status_code=429,
            **kwargs
        )


# Model and Provider Errors

class ModelError(ContextMemoryError):
    """Base class for model-related errors."""
    
    def __init__(self, message: str, **kwargs):
        code = kwargs.pop("error_code", "MODEL_ERROR")
        status = kwargs.pop("status_code", 400)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class ModelNotAvailableError(ModelError):
    """Raised when a requested model is not available."""
    
    def __init__(
        self, 
        message: str = "Model not available", 
        model_id: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if model_id:
            details["model_id"] = model_id
        
        super().__init__(
            message, 
            error_code="MODEL_NOT_AVAILABLE", 
            details=details,
            status_code=404,
            **kwargs
        )


class ModelPermissionError(ModelError):
    """Raised when user doesn't have permission to use a model."""
    
    def __init__(
        self, 
        message: str = "Model access denied", 
        model_id: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if model_id:
            details["model_id"] = model_id
        
        super().__init__(
            message, 
            error_code="MODEL_PERMISSION_DENIED", 
            details=details,
            status_code=403,
            **kwargs
        )


class ProviderError(ContextMemoryError):
    """Base class for external provider errors."""
    
    def __init__(self, message: str, provider: Optional[str] = None, **kwargs):
        details = {}
        if provider:
            details["provider"] = provider
        
        code = kwargs.pop("error_code", "PROVIDER_ERROR")
        status = kwargs.pop("status_code", 502)
        super().__init__(
            message, 
            error_code=code, 
            details=details,
            status_code=status,
            **kwargs
        )


class OpenRouterError(ProviderError):
    """Raised when OpenRouter API returns an error."""
    
    def __init__(
        self, 
        message: str = "OpenRouter API error", 
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        details = {"provider": "openrouter"}
        if status_code is not None:
            details["upstream_status_code"] = status_code
        if response_data:
            details["upstream_response"] = response_data
        
        super().__init__(
            message, 
            error_code="OPENROUTER_ERROR", 
            details=details,
            status_code=status_code or 502,
            **kwargs
        )


# Context Memory Errors

class ContextMemoryServiceError(ContextMemoryError):
    """Base class for context memory service errors."""
    
    def __init__(self, message: str, **kwargs):
        code = kwargs.pop("error_code", "CONTEXT_MEMORY_ERROR")
        status = kwargs.pop("status_code", 500)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class ContextNotFoundError(ContextMemoryServiceError):
    """Raised when requested context is not found."""
    
    def __init__(
        self, 
        message: str = "Context not found", 
        thread_id: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if thread_id:
            details["thread_id"] = thread_id
        
        super().__init__(
            message, 
            error_code="CONTEXT_NOT_FOUND", 
            details=details,
            status_code=404,
            **kwargs
        )


class ContextIngestionError(ContextMemoryServiceError):
    """Raised when context ingestion fails."""
    
    def __init__(
        self, 
        message: str = "Context ingestion failed", 
        reason: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if reason:
            details["reason"] = reason
        
        super().__init__(
            message, 
            error_code="CONTEXT_INGESTION_FAILED", 
            details=details,
            **kwargs
        )


class WorkingSetGenerationError(ContextMemoryServiceError):
    """Raised when working set generation fails."""
    
    def __init__(
        self, 
        message: str = "Working set generation failed", 
        reason: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if reason:
            details["reason"] = reason
        
        super().__init__(
            message, 
            error_code="WORKING_SET_GENERATION_FAILED", 
            details=details,
            **kwargs
        )


# Validation Errors

class ValidationError(ContextMemoryError):
    """Base class for validation errors."""
    
    def __init__(self, message: str, field: Optional[str] = None, **kwargs):
        details = {}
        if field:
            details["field"] = field
        
        code = kwargs.pop("error_code", "VALIDATION_ERROR")
        status = kwargs.pop("status_code", 400)
        super().__init__(
            message, 
            error_code=code, 
            details=details,
            status_code=status,
            **kwargs
        )


class InvalidRequestError(ValidationError):
    """Raised when request data is invalid."""
    
    def __init__(self, message: str = "Invalid request", **kwargs):
        super().__init__(message, error_code="INVALID_REQUEST", **kwargs)


class RequestTooLargeError(ValidationError):
    """Raised when request payload is too large."""
    
    def __init__(
        self, 
        message: str = "Request too large", 
        size: Optional[int] = None,
        max_size: Optional[int] = None,
        **kwargs
    ):
        details = {}
        if size is not None:
            details["request_size"] = size
        if max_size is not None:
            details["max_allowed_size"] = max_size
        
        super().__init__(
            message, 
            error_code="REQUEST_TOO_LARGE", 
            details=details,
            status_code=413,
            **kwargs
        )


# Database and Infrastructure Errors

class DatabaseError(ContextMemoryError):
    """Base class for database-related errors."""
    
    def __init__(self, message: str = "Database error", **kwargs):
        code = kwargs.pop("error_code", "DATABASE_ERROR")
        status = kwargs.pop("status_code", 500)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class ConnectionError(DatabaseError):
    """Raised when database connection fails."""
    
    def __init__(self, message: str = "Database connection failed", **kwargs):
        super().__init__(message, error_code="DATABASE_CONNECTION_FAILED", **kwargs)


class RedisError(ContextMemoryError):
    """Base class for Redis-related errors."""
    
    def __init__(self, message: str = "Redis error", **kwargs):
        code = kwargs.pop("error_code", "REDIS_ERROR")
        status = kwargs.pop("status_code", 500)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class CacheError(RedisError):
    """Raised when cache operations fail."""
    
    def __init__(self, message: str = "Cache operation failed", **kwargs):
        super().__init__(message, error_code="CACHE_ERROR", **kwargs)


# Configuration Errors

class ConfigurationError(ContextMemoryError):
    """Base class for configuration-related errors."""
    
    def __init__(self, message: str = "Configuration error", **kwargs):
        code = kwargs.pop("error_code", "CONFIGURATION_ERROR")
        status = kwargs.pop("status_code", 500)
        super().__init__(message, error_code=code, status_code=status, **kwargs)


class MissingConfigurationError(ConfigurationError):
    """Raised when required configuration is missing."""
    
    def __init__(
        self, 
        message: str = "Missing configuration", 
        config_key: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if config_key:
            details["config_key"] = config_key
        
        super().__init__(
            message, 
            error_code="MISSING_CONFIGURATION", 
            details=details,
            **kwargs
        )


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration is invalid."""
    
    def __init__(
        self, 
        message: str = "Invalid configuration", 
        config_key: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if config_key:
            details["config_key"] = config_key
        
        super().__init__(
            message, 
            error_code="INVALID_CONFIGURATION", 
            details=details,
            **kwargs
        )
