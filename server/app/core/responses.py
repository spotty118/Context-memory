"""
Standardized API response utilities for Context Memory Gateway.
Implements consistent response envelope pattern across all endpoints.
"""
from datetime import datetime
from typing import Any, Dict, Optional, Union, List
from fastapi import Request
from fastapi.responses import JSONResponse
import uuid
from pydantic import BaseModel


class PaginationMeta(BaseModel):
    """Pagination metadata model."""
    page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ErrorDetail(BaseModel):
    """Error detail model."""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ResponseMeta(BaseModel):
    """Response metadata model."""
    timestamp: str
    request_id: str
    version: str
    pagination: Optional[PaginationMeta] = None


class StandardResponse(BaseModel):
    """Standard API response envelope."""
    success: bool
    data: Any = None
    error: Optional[ErrorDetail] = None
    meta: ResponseMeta


class APIResponseBuilder:
    """Builder for creating standardized API responses."""
    
    def __init__(self, request: Request):
        self.request = request
        self.request_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
        self.version = getattr(request.state, 'api_version', 'v1')
    
    def success(
        self,
        data: Any = None,
        pagination: Optional[PaginationMeta] = None,
        status_code: int = 200
    ) -> JSONResponse:
        """Create a success response."""
        
        response_data = StandardResponse(
            success=True,
            data=data,
            error=None,
            meta=ResponseMeta(
                timestamp=datetime.utcnow().isoformat() + "Z",
                request_id=self.request_id,
                version=self.version,
                pagination=pagination
            )
        )
        
        return JSONResponse(
            content=response_data.model_dump(),
            status_code=status_code
        )
    
    def error(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 400
    ) -> JSONResponse:
        """Create an error response."""
        
        response_data = StandardResponse(
            success=False,
            data=None,
            error=ErrorDetail(
                code=code,
                message=message,
                details=details
            ),
            meta=ResponseMeta(
                timestamp=datetime.utcnow().isoformat() + "Z",
                request_id=self.request_id,
                version=self.version
            )
        )
        
        return JSONResponse(
            content=response_data.model_dump(),
            status_code=status_code
        )
    
    def validation_error(
        self,
        message: str = "Invalid input parameters",
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create a validation error response."""
        return self.error(
            code="VALIDATION_ERROR",
            message=message,
            details=details,
            status_code=422
        )
    
    def not_found(
        self,
        resource: str = "resource",
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create a not found error response."""
        return self.error(
            code="RESOURCE_NOT_FOUND",
            message=f"The requested {resource} was not found",
            details=details,
            status_code=404
        )
    
    def unauthorized(
        self,
        message: str = "Authentication required",
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create an unauthorized error response."""
        return self.error(
            code="AUTHENTICATION_ERROR",
            message=message,
            details=details,
            status_code=401
        )
    
    def forbidden(
        self,
        message: str = "Access denied",
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create a forbidden error response."""
        return self.error(
            code="AUTHORIZATION_ERROR",
            message=message,
            details=details,
            status_code=403
        )
    
    def conflict(
        self,
        message: str = "Resource conflict",
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create a conflict error response."""
        return self.error(
            code="RESOURCE_CONFLICT",
            message=message,
            details=details,
            status_code=409
        )
    
    def rate_limit_exceeded(
        self,
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create a rate limit exceeded response."""
        return self.error(
            code="RATE_LIMIT_EXCEEDED",
            message="API request rate limit exceeded",
            details=details,
            status_code=429
        )
    
    def internal_error(
        self,
        message: str = "An internal system error occurred",
        details: Optional[Dict[str, Any]] = None
    ) -> JSONResponse:
        """Create an internal server error response."""
        return self.error(
            code="SYSTEM_ERROR",
            message=message,
            details=details,
            status_code=500
        )


def create_pagination_meta(
    page: int,
    per_page: int,
    total: int
) -> PaginationMeta:
    """Create pagination metadata."""
    total_pages = (total + per_page - 1) // per_page  # Ceiling division
    
    return PaginationMeta(
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
    )


def success_response(
    request: Request,
    data: Any = None,
    pagination: Optional[PaginationMeta] = None,
    status_code: int = 200
) -> JSONResponse:
    """Quick helper for success responses."""
    builder = APIResponseBuilder(request)
    return builder.success(data, pagination, status_code)


def error_response(
    request: Request,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    status_code: int = 400
) -> JSONResponse:
    """Quick helper for error responses."""
    builder = APIResponseBuilder(request)
    return builder.error(code, message, details, status_code)


# Legacy response helpers for backward compatibility
def create_success_response(data: Any = None, message: str = None) -> Dict[str, Any]:
    """Legacy helper - use APIResponseBuilder instead."""
    return {
        "success": True,
        "data": data,
        "message": message
    }


def create_error_response(message: str, code: str = None, details: Any = None) -> Dict[str, Any]:
    """Legacy helper - use APIResponseBuilder instead."""
    return {
        "success": False,
        "error": message,
        "code": code,
        "details": details
    }


class PaginationParams(BaseModel):
    """Standard pagination parameters."""
    page: int = 1
    per_page: int = 20
    
    @classmethod
    def from_query(
        cls,
        page: int = 1,
        per_page: int = 20,
        max_per_page: int = 100
    ) -> "PaginationParams":
        """Create pagination params from query parameters."""
        # Validate and constrain parameters
        page = max(1, page)
        per_page = max(1, min(per_page, max_per_page))
        
        return cls(page=page, per_page=per_page)
    
    @property
    def offset(self) -> int:
        """Calculate SQL offset for pagination."""
        return (self.page - 1) * self.per_page
    
    @property
    def limit(self) -> int:
        """Get SQL limit for pagination."""
        return self.per_page


class FilterParams(BaseModel):
    """Base class for filter parameters."""
    
    @classmethod
    def from_dict(cls, filters: Dict[str, Any]) -> "FilterParams":
        """Create filter params from dictionary."""
        return cls(**filters)
