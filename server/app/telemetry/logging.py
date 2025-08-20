"""
Structured logging configuration using structlog.
"""
import logging
import sys
from typing import Any, Dict, Optional
import structlog
from structlog.types import EventDict

from app.core.config import settings


def add_correlation_id(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add correlation ID to log events if available."""
    # This can be enhanced to extract correlation IDs from request context
    return event_dict


def add_service_info(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add service information to log events."""
    event_dict["service"] = "context-memory-gateway"
    event_dict["environment"] = settings.ENVIRONMENT
    return event_dict


def filter_sensitive_data(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Filter sensitive data from log events."""
    sensitive_keys = {
        "password", "token", "key", "secret", "authorization",
        "x-api-key", "openrouter_api_key", "jwt_secret_key"
    }
    
    # Recursively filter sensitive data
    def filter_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        filtered = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                if isinstance(value, str):
                    filtered[key] = f"[REDACTED:{len(value)} chars]"
                else:
                    filtered[key] = "[REDACTED]"
            elif isinstance(value, dict):
                filtered[key] = filter_dict(value)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                filtered[key] = [filter_dict(item) for item in value]
            else:
                filtered[key] = value
        return filtered
    
    # Filter the event dict
    for key, value in list(event_dict.items()):
        if isinstance(value, dict):
            event_dict[key] = filter_dict(value)
        elif key.lower() in sensitive_keys:
            if isinstance(value, str):
                event_dict[key] = f"[REDACTED:{len(value)} chars]"
            else:
                event_dict[key] = "[REDACTED]"
    
    return event_dict


def setup_logging() -> None:
    """Configure structured logging for the application."""
    
    # Configure log level
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    # Configure structlog
    processors = [
        # Add service information
        add_service_info,
        # Add correlation ID if available
        add_correlation_id,
        # Filter sensitive data
        filter_sensitive_data,
        # Add timestamp
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if settings.is_development:
        # Pretty console output for development
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON output for production
        processors.append(structlog.processors.JSONRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    
    # Set log levels for third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    # Enable SQL query logging in development
    if settings.is_development and settings.DEBUG:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)

