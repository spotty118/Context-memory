"""
API versioning strategy for Context Memory Gateway.
Provides version management and routing for future API compatibility.
"""
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, date
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog
from functools import wraps

logger = structlog.get_logger(__name__)


class APIVersion(str, Enum):
    """Supported API versions."""
    V1 = "v1"
    V2 = "v2"  # Future version
    
    @classmethod
    def get_latest(cls) -> "APIVersion":
        """Get the latest API version."""
        return cls.V1
    
    @classmethod
    def get_supported(cls) -> List["APIVersion"]:
        """Get all supported API versions."""
        return [cls.V1, cls.V2]
    
    @classmethod
    def is_supported(cls, version: str) -> bool:
        """Check if a version is supported."""
        try:
            return cls(version) in cls.get_supported()
        except ValueError:
            return False


class APIVersionInfo(BaseModel):
    """API version information model."""
    version: str
    status: str  # "current", "deprecated", "sunset", "planned"
    release_date: date
    deprecation_date: Optional[date] = None
    sunset_date: Optional[date] = None
    breaking_changes: List[str] = []
    new_features: List[str] = []
    documentation_url: Optional[str] = None


class VersionCompatibility(BaseModel):
    """Version compatibility information."""
    source_version: str
    target_version: str
    compatible: bool
    migration_guide_url: Optional[str] = None
    breaking_changes: List[str] = []
    recommended_migration_date: Optional[date] = None


class APIVersionRegistry:
    """Registry for managing API versions and their metadata."""
    
    def __init__(self):
        self._versions: Dict[str, APIVersionInfo] = {}
        self._compatibility_matrix: Dict[str, Dict[str, VersionCompatibility]] = {}
        self._routers: Dict[str, APIRouter] = {}
        self._init_default_versions()
    
    def _init_default_versions(self):
        """Initialize default version information."""
        # Version 1.0 - Current stable version
        self.register_version(APIVersionInfo(
            version="v1",
            status="current",
            release_date=date(2025, 1, 20),
            new_features=[
                "Context Memory system with semantic and episodic items",
                "LLM Gateway with OpenRouter integration",
                "Working sets with token budget management",
                "Background workers and job scheduling",
                "Admin interface with comprehensive monitoring",
                "Rate limiting with Redis token bucket",
                "JWT authentication for admin interface"
            ],
            documentation_url="/docs"
        ))
        
        # Version 2.0 - Future version (planned)
        self.register_version(APIVersionInfo(
            version="v2",
            status="planned",
            release_date=date(2025, 6, 1),  # Planned release
            new_features=[
                "Enhanced context scoring algorithm",
                "Multi-modal context support (images, audio)",
                "Real-time collaboration features",
                "Advanced caching mechanisms",
                "GraphQL API endpoints",
                "Enhanced admin analytics"
            ],
            documentation_url="/docs/v2"
        ))
    
    def register_version(self, version_info: APIVersionInfo) -> None:
        """Register a new API version."""
        self._versions[version_info.version] = version_info
        logger.info("api_version_registered", version=version_info.version, status=version_info.status)
    
    def get_version_info(self, version: str) -> Optional[APIVersionInfo]:
        """Get information about a specific version."""
        return self._versions.get(version)
    
    def get_all_versions(self) -> Dict[str, APIVersionInfo]:
        """Get information about all registered versions."""
        return self._versions.copy()
    
    def register_router(self, version: str, router: APIRouter) -> None:
        """Register a router for a specific version."""
        self._routers[version] = router
        logger.info("api_router_registered", version=version)
    
    def get_router(self, version: str) -> Optional[APIRouter]:
        """Get router for a specific version."""
        return self._routers.get(version)
    
    def add_compatibility(self, compatibility: VersionCompatibility) -> None:
        """Add version compatibility information."""
        source = compatibility.source_version
        target = compatibility.target_version
        
        if source not in self._compatibility_matrix:
            self._compatibility_matrix[source] = {}
        
        self._compatibility_matrix[source][target] = compatibility
    
    def check_compatibility(self, source_version: str, target_version: str) -> Optional[VersionCompatibility]:
        """Check compatibility between two versions."""
        return self._compatibility_matrix.get(source_version, {}).get(target_version)
    
    def deprecate_version(self, version: str, deprecation_date: date, sunset_date: date) -> None:
        """Mark a version as deprecated."""
        if version in self._versions:
            self._versions[version].status = "deprecated"
            self._versions[version].deprecation_date = deprecation_date
            self._versions[version].sunset_date = sunset_date
            logger.warning("api_version_deprecated", version=version, sunset_date=sunset_date.isoformat())


# Global version registry
version_registry = APIVersionRegistry()


def get_version_from_request(request: Request) -> str:
    """Extract API version from request."""
    # Try path-based versioning first (e.g., /v1/models)
    path_parts = request.url.path.strip('/').split('/')
    if path_parts and path_parts[0].startswith('v') and path_parts[0][1:].isdigit():
        return path_parts[0]
    
    # Try header-based versioning
    version_header = request.headers.get("API-Version") or request.headers.get("Accept-Version")
    if version_header:
        return version_header
    
    # Try query parameter
    version_param = request.query_params.get("version")
    if version_param:
        return version_param
    
    # Default to latest version
    return APIVersion.get_latest().value


def create_version_middleware():
    """Create middleware for API version handling."""
    
    async def version_middleware(request: Request, call_next):
        """Middleware to handle API versioning."""
        
        # Extract version from request
        api_version = get_version_from_request(request)
        
        # Check if version is supported
        if not APIVersion.is_supported(api_version):
            logger.warning(
                "unsupported_api_version_requested",
                requested_version=api_version,
                supported_versions=[v.value for v in APIVersion.get_supported()],
                path=request.url.path
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": "UNSUPPORTED_API_VERSION",
                    "message": f"API version '{api_version}' is not supported",
                    "supported_versions": [v.value for v in APIVersion.get_supported()],
                    "latest_version": APIVersion.get_latest().value,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
        
        # Store version in request state
        request.state.api_version = api_version
        
        # Check for deprecated versions
        version_info = version_registry.get_version_info(api_version)
        if version_info and version_info.status == "deprecated":
            logger.warning(
                "deprecated_api_version_used",
                version=api_version,
                deprecation_date=version_info.deprecation_date.isoformat() if version_info.deprecation_date else None,
                sunset_date=version_info.sunset_date.isoformat() if version_info.sunset_date else None
            )
        
        response = await call_next(request)
        
        # Add version headers to response
        response.headers["API-Version"] = api_version
        response.headers["API-Supported-Versions"] = ",".join([v.value for v in APIVersion.get_supported()])
        response.headers["API-Latest-Version"] = APIVersion.get_latest().value
        
        # Add deprecation headers if applicable
        if version_info and version_info.status == "deprecated":
            response.headers["API-Deprecation"] = "true"
            if version_info.sunset_date:
                response.headers["API-Sunset"] = version_info.sunset_date.isoformat()
        
        return response
    
    return version_middleware


def create_versioned_router(version: str, prefix: str = "", **kwargs) -> APIRouter:
    """Create a versioned API router."""
    router = APIRouter(prefix=f"/{version}{prefix}", **kwargs)
    version_registry.register_router(version, router)
    return router


# Version-specific request/response models
class VersionedResponse(BaseModel):
    """Base response model with version information."""
    api_version: str
    timestamp: datetime
    
    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class APIVersionsResponse(BaseModel):
    """Response model for API versions endpoint."""
    current_version: str
    supported_versions: List[str]
    version_info: Dict[str, APIVersionInfo]
    compatibility_matrix: Dict[str, Dict[str, bool]]


def create_version_endpoints() -> APIRouter:
    """Create version information endpoints."""
    router = APIRouter(tags=["API Versioning"])
    
    @router.get("/versions", response_model=APIVersionsResponse)
    async def get_api_versions() -> APIVersionsResponse:
        """Get information about all API versions."""
        supported_versions = [v.value for v in APIVersion.get_supported()]
        version_info = version_registry.get_all_versions()
        
        # Build compatibility matrix
        compatibility_matrix = {}
        for source_version in supported_versions:
            compatibility_matrix[source_version] = {}
            for target_version in supported_versions:
                compat = version_registry.check_compatibility(source_version, target_version)
                compatibility_matrix[source_version][target_version] = (
                    compat.compatible if compat else source_version == target_version
                )
        
        return APIVersionsResponse(
            current_version=APIVersion.get_latest().value,
            supported_versions=supported_versions,
            version_info=version_info,
            compatibility_matrix=compatibility_matrix
        )
    
    @router.get("/versions/{version}", response_model=APIVersionInfo)
    async def get_version_info(version: str) -> APIVersionInfo:
        """Get detailed information about a specific API version."""
        version_info = version_registry.get_version_info(version)
        
        if not version_info:
            raise HTTPException(
                status_code=404,
                detail=f"API version '{version}' not found"
            )
        
        return version_info
    
    @router.get("/versions/{source_version}/compatibility/{target_version}")
    async def get_version_compatibility(source_version: str, target_version: str) -> VersionCompatibility:
        """Get compatibility information between two API versions."""
        compatibility = version_registry.check_compatibility(source_version, target_version)
        
        if not compatibility:
            # Default compatibility (same version is always compatible)
            if source_version == target_version:
                compatibility = VersionCompatibility(
                    source_version=source_version,
                    target_version=target_version,
                    compatible=True
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Compatibility information not found for {source_version} -> {target_version}"
                )
        
        return compatibility
    
    return router


# Utility functions for version-aware request handling
def _extract_request(args, kwargs) -> Optional[Request]:
    """Extract FastAPI Request object from args/kwargs for decorator use."""
    # Common kwarg names first
    req = kwargs.get("request") or kwargs.get("http_request")
    if isinstance(req, Request):
        return req
    # Any kwarg that is a Request
    for v in kwargs.values():
        if isinstance(v, Request):
            return v
    # Positional args
    for a in args:
        if isinstance(a, Request):
            return a
    return None


def require_version(required_version: str) -> Callable:
    """Decorator to require a specific API version."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            current_version = getattr(request.state, "api_version", None) if request else None
            
            if current_version != required_version:
                raise HTTPException(
                    status_code=400,
                    detail=f"This endpoint requires API version {required_version}, "
                           f"but {current_version} was provided"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def min_version(minimum_version: str) -> Callable:
    """Decorator to require a minimum API version."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            current_version = getattr(request.state, "api_version", None) if request else None
            
            # Simple version comparison (assumes vN format)
            current_num = int(current_version[1:]) if current_version and current_version.startswith('v') else 0
            min_num = int(minimum_version[1:]) if minimum_version.startswith('v') else 0
            
            if current_num < min_num:
                raise HTTPException(
                    status_code=400,
                    detail=f"This endpoint requires API version {minimum_version} or higher, "
                           f"but {current_version} was provided"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def version_aware_response(data: Any, request: Request) -> Dict[str, Any]:
    """Create a version-aware response with metadata."""
    api_version = getattr(request.state, "api_version", APIVersion.get_latest().value)
    
    response_data = {
        "data": data,
        "meta": {
            "api_version": api_version,
            "timestamp": datetime.utcnow().isoformat(),
            "supported_versions": [v.value for v in APIVersion.get_supported()],
            "latest_version": APIVersion.get_latest().value
        }
    }
    
    return response_data


# Version-specific feature flags
VERSION_FEATURES = {
    "v1": {
        "context_memory": True,
        "llm_gateway": True,
        "admin_interface": True,
        "background_workers": True,
        "rate_limiting": True,
        "metrics": True,
        "graphql": False,  # Not available in v1
        "realtime_collaboration": False,  # Not available in v1
        "multimodal_context": False,  # Not available in v1
    },
    "v2": {  # Future version
        "context_memory": True,
        "llm_gateway": True,
        "admin_interface": True,
        "background_workers": True,
        "rate_limiting": True,
        "metrics": True,
        "graphql": True,  # New in v2
        "realtime_collaboration": True,  # New in v2
        "multimodal_context": True,  # New in v2
        "enhanced_scoring": True,  # New in v2
        "advanced_caching": True,  # New in v2
    }
}


def is_feature_available(feature: str, version: str = None) -> bool:
    """Check if a feature is available in a specific version."""
    if version is None:
        version = APIVersion.get_latest().value
    
    return VERSION_FEATURES.get(version, {}).get(feature, False)


def require_feature(feature_name: str) -> Callable:
    """Decorator to require a specific feature to be available."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            api_version = (
                getattr(request.state, "api_version", APIVersion.get_latest().value)
                if request else APIVersion.get_latest().value
            )
            
            if not is_feature_available(feature_name, api_version):
                raise HTTPException(
                    status_code=404,
                    detail=f"Feature '{feature_name}' is not available in API version {api_version}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator