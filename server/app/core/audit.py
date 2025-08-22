"""
Security audit logging module for comprehensive security event tracking.
"""
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import structlog

from app.core.config import settings


logger = structlog.get_logger(__name__)


class SecurityEventType(Enum):
    """Security event types for categorization."""
    
    # Authentication events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    TOKEN_EXPIRED = "token_expired"
    INVALID_TOKEN = "invalid_token"
    
    # API key events
    API_KEY_SUCCESS = "api_key_success"
    API_KEY_INVALID = "api_key_invalid"
    API_KEY_INACTIVE = "api_key_inactive"
    API_KEY_MISSING = "api_key_missing"
    API_KEY_GENERATED = "api_key_generated"
    API_KEY_REVOKED = "api_key_revoked"
    
    # Access control events
    ADMIN_ACCESS_GRANTED = "admin_access_granted"
    ADMIN_ACCESS_DENIED = "admin_access_denied"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    PERMISSION_DENIED = "permission_denied"
    
    # Security violations
    REQUEST_SIZE_EXCEEDED = "request_size_exceeded"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
    
    # Data access events
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    DATA_EXPORT = "data_export"
    CONFIGURATION_CHANGE = "configuration_change"


class SecurityRisk(Enum):
    """Security risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def log_security_event(
    event_type: SecurityEventType,
    risk_level: SecurityRisk = SecurityRisk.LOW,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    path: Optional[str] = None,
    method: Optional[str] = None,
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> None:
    """
    Log a security event with comprehensive details.
    
    Args:
        event_type: Type of security event
        risk_level: Risk level of the event
        user_id: User identifier (API key hash, admin username, etc.)
        username: Human-readable username
        client_ip: Client IP address
        user_agent: User agent string
        path: Request path
        method: HTTP method
        success: Whether the event was successful
        details: Additional event-specific details
        error_message: Error message if applicable
        correlation_id: Request correlation ID for tracing
    """
    event_data = {
        "event_type": event_type.value,
        "risk_level": risk_level.value,
        "timestamp": datetime.utcnow().isoformat(),
        "success": success,
        "service": "context-memory-gateway",
        "environment": settings.ENVIRONMENT,
    }
    
    # Add user information
    if user_id:
        event_data["user_id"] = user_id
    if username:
        event_data["username"] = username
    
    # Add request information
    if client_ip:
        event_data["client_ip"] = client_ip
    if user_agent:
        event_data["user_agent"] = user_agent
    if path:
        event_data["path"] = path
    if method:
        event_data["method"] = method
    
    # Add error information
    if error_message:
        event_data["error_message"] = error_message
    
    # Add correlation ID for request tracing
    if correlation_id:
        event_data["correlation_id"] = correlation_id
    
    # Add additional details
    if details:
        event_data["details"] = details
    
    # Log based on risk level
    if risk_level in [SecurityRisk.HIGH, SecurityRisk.CRITICAL]:
        logger.error("security_event", **event_data)
    elif risk_level == SecurityRisk.MEDIUM:
        logger.warning("security_event", **event_data)
    else:
        logger.info("security_event", **event_data)
    
    # For critical events, also log to a separate security log
    if risk_level == SecurityRisk.CRITICAL:
        logger.critical("critical_security_event", **event_data)


def log_authentication_event(
    success: bool,
    username: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    method: str = "password",
    error_message: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Log authentication events."""
    event_type = SecurityEventType.LOGIN_SUCCESS if success else SecurityEventType.LOGIN_FAILURE
    risk_level = SecurityRisk.LOW if success else SecurityRisk.MEDIUM
    
    log_security_event(
        event_type=event_type,
        risk_level=risk_level,
        username=username,
        client_ip=client_ip,
        user_agent=user_agent,
        success=success,
        details={"auth_method": method},
        error_message=error_message,
        correlation_id=correlation_id
    )


def log_api_key_event(
    success: bool,
    key_hash: Optional[str] = None,
    workspace_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    path: Optional[str] = None,
    error_message: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Log API key authentication events."""
    if success:
        event_type = SecurityEventType.API_KEY_SUCCESS
        risk_level = SecurityRisk.LOW
    else:
        event_type = SecurityEventType.API_KEY_INVALID
        risk_level = SecurityRisk.MEDIUM
    
    log_security_event(
        event_type=event_type,
        risk_level=risk_level,
        user_id=key_hash[:8] + "..." if key_hash else None,
        client_ip=client_ip,
        path=path,
        success=success,
        details={"workspace_id": workspace_id} if workspace_id else None,
        error_message=error_message,
        correlation_id=correlation_id
    )


def log_admin_access_event(
    success: bool,
    username: Optional[str] = None,
    client_ip: Optional[str] = None,
    path: Optional[str] = None,
    action: Optional[str] = None,
    error_message: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Log admin access events."""
    event_type = SecurityEventType.ADMIN_ACCESS_GRANTED if success else SecurityEventType.ADMIN_ACCESS_DENIED
    risk_level = SecurityRisk.LOW if success else SecurityRisk.HIGH
    
    log_security_event(
        event_type=event_type,
        risk_level=risk_level,
        username=username,
        client_ip=client_ip,
        path=path,
        success=success,
        details={"action": action} if action else None,
        error_message=error_message,
        correlation_id=correlation_id
    )


def log_rate_limit_event(
    client_ip: Optional[str] = None,
    api_key_hash: Optional[str] = None,
    path: Optional[str] = None,
    limit_type: str = "requests_per_minute",
    correlation_id: Optional[str] = None
) -> None:
    """Log rate limiting events."""
    log_security_event(
        event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
        risk_level=SecurityRisk.MEDIUM,
        user_id=api_key_hash[:8] + "..." if api_key_hash else None,
        client_ip=client_ip,
        path=path,
        success=False,
        details={"limit_type": limit_type},
        correlation_id=correlation_id
    )


def log_suspicious_activity(
    activity_type: str,
    client_ip: Optional[str] = None,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Log suspicious activity."""
    log_security_event(
        event_type=SecurityEventType.SUSPICIOUS_ACTIVITY,
        risk_level=SecurityRisk.HIGH,
        user_id=user_id,
        client_ip=client_ip,
        success=False,
        details={
            "activity_type": activity_type,
            **(details or {})
        },
        correlation_id=correlation_id
    )


def log_configuration_change(
    username: Optional[str] = None,
    client_ip: Optional[str] = None,
    setting_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Log configuration changes."""
    # Redact sensitive values
    if old_value and any(sensitive in setting_name.lower() for sensitive in ["key", "secret", "password"]):
        old_value = "[REDACTED]"
    if new_value and any(sensitive in setting_name.lower() for sensitive in ["key", "secret", "password"]):
        new_value = "[REDACTED]"
    
    log_security_event(
        event_type=SecurityEventType.CONFIGURATION_CHANGE,
        risk_level=SecurityRisk.MEDIUM,
        username=username,
        client_ip=client_ip,
        success=True,
        details={
            "setting_name": setting_name,
            "old_value": old_value,
            "new_value": new_value
        },
        correlation_id=correlation_id
    )