"""
Security module for API key authentication and authorization.
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog
import jwt
from pydantic import BaseModel

from app.core.config import settings
from app.db.session import get_db
from app.db.models import APIKey
from app.core.audit import (
    log_authentication_event, log_api_key_event, log_admin_access_event,
    SecurityEventType, SecurityRisk, log_security_event
)


logger = structlog.get_logger(__name__)
security = HTTPBearer(auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256 with salt."""
    salted_key = f"{api_key}{settings.AUTH_API_KEY_SALT}"
    return hashlib.sha256(salted_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new secure API key."""
    # Generate a 32-byte random key and encode as hex
    return f"cmg_{secrets.token_hex(32)}"


def validate_api_key_format(api_key: str) -> bool:
    """Validate API key format and structure."""
    if not api_key:
        return False
    
    # Check for proper prefix
    if not api_key.startswith("cmg_"):
        return False
    
    # Check minimum length (cmg_ + 64 hex characters)
    if len(api_key) < 68:
        return False
    
    # Check that the part after prefix is valid hex
    key_part = api_key[4:]  # Remove 'cmg_' prefix
    try:
        int(key_part, 16)  # Validate hex format
        return True
    except ValueError:
        return False


def validate_openrouter_key_format(api_key: str) -> bool:
    """Validate OpenRouter API key format."""
    if not api_key:
        return False
    
    # OpenRouter keys start with 'sk-or-'
    if not api_key.startswith("sk-or-"):
        return False
    
    # Check minimum reasonable length
    if len(api_key) < 20:
        return False
    
    return True


async def get_api_key_from_header(request: Request) -> Optional[str]:
    """Extract API key from X-API-Key header."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        # Also check Authorization header as fallback
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header[7:]  # Remove "Bearer " prefix
    
    return api_key


async def get_api_key(
    request: Request,
    db = Depends(get_db)
) -> APIKey:
    """
    Dependency to get and validate API key from request headers.
    
    Raises:
        HTTPException: If API key is missing, invalid, or inactive.
    """
    # Extract correlation ID from request state
    correlation_id = getattr(request.state, "correlation_id", None)
    
    api_key_value = await get_api_key_from_header(request)
    
    if not api_key_value:
        log_api_key_event(
            success=False,
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
            error_message="API key missing",
            correlation_id=correlation_id
        )
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide via X-API-Key header or Authorization: Bearer <key>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Hash the provided key to look it up in database
    key_hash = hash_api_key(api_key_value)
    
    # Look up API key in database
    api_key_record = await db.get(APIKey, key_hash)
    
    if not api_key_record:
        log_api_key_event(
            success=False,
            key_hash=key_hash,
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
            error_message="Invalid API key",
            correlation_id=correlation_id
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not api_key_record.active:
        log_api_key_event(
            success=False,
            key_hash=key_hash,
            workspace_id=api_key_record.workspace_id,
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
            error_message="API key is inactive",
            correlation_id=correlation_id
        )
        raise HTTPException(
            status_code=401,
            detail="API key is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    log_api_key_event(
        success=True,
        key_hash=key_hash,
        workspace_id=api_key_record.workspace_id,
        client_ip=request.client.host if request.client else None,
        path=request.url.path,
        correlation_id=correlation_id
    )
    
    return api_key_record


# Compatibility alias for routes/tests expecting get_current_api_key
async def get_current_api_key(
    request: Request,
    db = Depends(get_db)
) -> APIKey:
    return await get_api_key(request, db)


async def get_optional_api_key(
    request: Request,
    db = Depends(get_db)
) -> Optional[APIKey]:
    """
    Optional dependency to get API key if present.
    Returns None if no API key provided or if invalid.
    """
    try:
        return await get_api_key(request, db)
    except HTTPException:
        return None


def check_model_permission(api_key: APIKey, model_id: str) -> bool:
    """
    Check if an API key has permission to use a specific model.
    
    Args:
        api_key: The API key record
        model_id: The model ID to check
        
    Returns:
        bool: True if allowed, False if blocked
    """
    # Check per-key blocklist first
    if api_key.model_blocklist and model_id in api_key.model_blocklist:
        return False
    
    # Check per-key allowlist if it exists
    if api_key.model_allowlist:
        return model_id in api_key.model_allowlist
    
    # If no per-key allowlist, check global settings
    # This will be implemented when we add the settings service
    return True


def redact_sensitive_data(data: dict) -> dict:
    """
    Redact sensitive information from request/response data for logging.
    
    Args:
        data: Dictionary that may contain sensitive data
        
    Returns:
        dict: Data with sensitive fields redacted
    """
    sensitive_fields = {
        "messages", "prompt", "input", "content", "text",
        "api_key", "authorization", "x-api-key", "password",
        "secret", "token", "key"
    }
    
    redacted_data = {}
    
    for key, value in data.items():
        key_lower = key.lower()
        
        if any(sensitive in key_lower for sensitive in sensitive_fields):
            if isinstance(value, str):
                redacted_data[key] = f"[REDACTED:{len(value)} chars]"
            elif isinstance(value, list):
                redacted_data[key] = f"[REDACTED:{len(value)} items]"
            else:
                redacted_data[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted_data[key] = redact_sensitive_data(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            redacted_data[key] = [redact_sensitive_data(item) for item in value]
        else:
            redacted_data[key] = value
    
    return redacted_data


# Admin Authentication Models and Functions

class AdminUser(BaseModel):
    """Admin user model for JWT authentication."""
    username: str
    is_admin: bool = True
    exp: Optional[datetime] = None


class AdminLoginRequest(BaseModel):
    """Admin login request model."""
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    """Admin login response model."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def create_admin_jwt(username: str) -> str:
    """Create a JWT token for admin authentication."""
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "username": username,
        "is_admin": True,
        "exp": expire,
        "iat": datetime.utcnow(),
        "iss": "context-memory-gateway"
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_admin_jwt(token: str) -> AdminUser:
    """Verify and decode admin JWT token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username = payload.get("username")
        is_admin = payload.get("is_admin", False)
        exp = payload.get("exp")
        
        if not username or not is_admin:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return AdminUser(
            username=username,
            is_admin=is_admin,
            exp=datetime.fromtimestamp(exp) if exp else None
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_admin_user(
    request: Request,
    admin_session: Optional[str] = Cookie(None)
) -> AdminUser:
    """Dependency to get and validate admin user from JWT token."""
    # Extract correlation ID from request state
    correlation_id = getattr(request.state, "correlation_id", None)
    
    token = None
    
    # Check for token in cookie
    if admin_session:
        token = admin_session
    
    # Check for token in Authorization header as fallback
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        log_admin_access_event(
            success=False,
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
            error_message="No authentication token provided",
            correlation_id=correlation_id
        )
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required. Please log in."
        )
    
    admin_user = verify_admin_jwt(token)
    
    log_admin_access_event(
        success=True,
        username=admin_user.username,
        client_ip=request.client.host if request.client else None,
        path=request.url.path,
        action="admin_access",
        correlation_id=correlation_id
    )
    
    return admin_user


async def authenticate_admin(username: str, password: str, correlation_id: Optional[str] = None) -> bool:
    """Authenticate admin credentials."""
    # For now, use simple hardcoded credentials
    # In production, this should use proper password hashing and database storage
    
    # Default admin credentials (should be changed in production)
    default_admin_user = "admin"
    default_admin_pass = "admin123"  # This should be configurable via environment
    
    # Check against environment variables first
    admin_user = settings.SECRET_KEY.split("-")[0] if "-" in settings.SECRET_KEY else default_admin_user
    admin_pass = settings.SECRET_KEY.split("-")[1] if "-" in settings.SECRET_KEY else default_admin_pass
    
    is_valid = username == admin_user and password == admin_pass
    
    log_authentication_event(
        success=is_valid,
        username=username,
        method="password",
        error_message=None if is_valid else "Invalid credentials",
        correlation_id=correlation_id
    )
    
    return is_valid

