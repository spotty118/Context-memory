"""
Security module for API key authentication and authorization.
"""
import hashlib
import secrets
from typing import Optional
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog

from app.core.config import settings
from app.db.session import get_db
from app.db.models import APIKey


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
    api_key_value = await get_api_key_from_header(request)
    
    if not api_key_value:
        logger.warning("missing_api_key", client_ip=request.client.host if request.client else None)
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
        logger.warning(
            "invalid_api_key",
            key_hash=key_hash[:8] + "...",  # Log partial hash for debugging
            client_ip=request.client.host if request.client else None,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not api_key_record.active:
        logger.warning(
            "inactive_api_key",
            key_hash=key_hash[:8] + "...",
            workspace_id=api_key_record.workspace_id,
        )
        raise HTTPException(
            status_code=401,
            detail="API key is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.debug(
        "api_key_authenticated",
        workspace_id=api_key_record.workspace_id,
        key_name=api_key_record.name,
    )
    
    return api_key_record


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

