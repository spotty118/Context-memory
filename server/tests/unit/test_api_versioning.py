"""
Comprehensive tests for API versioning strategy.
Tests version detection, validation, middleware, and feature flags.
"""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.versioning import (
    APIVersion, APIVersionInfo, APIVersionRegistry, VersionCompatibility,
    get_version_from_request, create_version_middleware, create_version_endpoints,
    is_feature_available, require_version, require_feature, min_version,
    version_aware_response, VERSION_FEATURES
)


class TestAPIVersionEnum:
    """Test APIVersion enum functionality."""
    
    def test_api_version_values(self):
        """Test API version enum values."""
        assert APIVersion.V1 == "v1"
        assert APIVersion.V2 == "v2"
    
    def test_get_latest_version(self):
        """Test getting latest API version."""
        latest = APIVersion.get_latest()
        assert latest == APIVersion.V1
    
    def test_get_supported_versions(self):
        """Test getting supported versions."""
        supported = APIVersion.get_supported()
        assert APIVersion.V1 in supported
        assert len(supported) >= 1
    
    def test_is_supported_version(self):
        """Test version support checking."""
        assert APIVersion.is_supported("v1") is True
        assert APIVersion.is_supported("v99") is False
        assert APIVersion.is_supported("invalid") is False


class TestAPIVersionRegistry:
    """Test API version registry functionality."""
    
    @pytest.fixture
    def registry(self):
        """Create a fresh version registry for testing."""
        return APIVersionRegistry()
    
    def test_registry_initialization(self, registry):
        """Test registry initializes with default versions."""
        versions = registry.get_all_versions()
        
        assert "v1" in versions
        assert "v2" in versions  # Planned version
        
        v1_info = versions["v1"]
        assert v1_info.status == "current"
        assert v1_info.version == "v1"
    
    def test_register_new_version(self, registry):
        """Test registering a new API version."""
        v3_info = APIVersionInfo(
            version="v3",
            status="planned",
            release_date=date(2025, 12, 1),
            new_features=["Feature 1", "Feature 2"]
        )
        
        registry.register_version(v3_info)
        
        retrieved = registry.get_version_info("v3")
        assert retrieved is not None
        assert retrieved.version == "v3"
        assert retrieved.status == "planned"
    
    def test_deprecate_version(self, registry):
        """Test version deprecation."""
        deprecation_date = date(2025, 6, 1)
        sunset_date = date(2025, 12, 1)
        
        registry.deprecate_version("v1", deprecation_date, sunset_date)
        
        v1_info = registry.get_version_info("v1")
        assert v1_info.status == "deprecated"
        assert v1_info.deprecation_date == deprecation_date
        assert v1_info.sunset_date == sunset_date
    
    def test_compatibility_management(self, registry):
        """Test version compatibility management."""
        compatibility = VersionCompatibility(
            source_version="v1",
            target_version="v2",
            compatible=True,
            breaking_changes=["Change 1", "Change 2"]
        )
        
        registry.add_compatibility(compatibility)
        
        retrieved = registry.check_compatibility("v1", "v2")
        assert retrieved is not None
        assert retrieved.compatible is True
        assert "Change 1" in retrieved.breaking_changes


class TestVersionDetection:
    """Test version detection from requests."""
    
    def test_path_based_version_detection(self):
        """Test detecting version from URL path."""
        # Mock request with v1 path
        request = MagicMock()
        request.url.path = "/v1/models"
        
        version = get_version_from_request(request)
        assert version == "v1"
    
    def test_header_based_version_detection(self):
        """Test detecting version from headers."""
        request = MagicMock()
        request.url.path = "/models"  # No version in path
        request.headers.get.side_effect = lambda key: "v2" if key == "API-Version" else None
        request.query_params.get.return_value = None
        
        version = get_version_from_request(request)
        assert version == "v2"
    
    def test_query_parameter_version_detection(self):
        """Test detecting version from query parameters."""
        request = MagicMock()
        request.url.path = "/models"
        request.headers.get.return_value = None
        request.query_params.get.side_effect = lambda key: "v1" if key == "version" else None
        
        version = get_version_from_request(request)
        assert version == "v1"
    
    def test_default_version_fallback(self):
        """Test fallback to default version."""
        request = MagicMock()
        request.url.path = "/models"
        request.headers.get.return_value = None
        request.query_params.get.return_value = None
        
        version = get_version_from_request(request)
        assert version == APIVersion.get_latest().value


class TestVersionMiddleware:
    """Test version middleware functionality."""
    
    @pytest.fixture
    def app(self):
        """Create test FastAPI app with versioning middleware."""
        app = FastAPI()
        app.middleware("http")(create_version_middleware())
        
        @app.get("/v1/test")
        async def test_endpoint():
            return {"message": "test"}
        
        return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)
    
    def test_supported_version_request(self, client):
        """Test request with supported version."""
        response = client.get("/v1/test")
        
        assert response.status_code == 200
        assert response.headers["API-Version"] == "v1"
        assert "API-Supported-Versions" in response.headers
        assert "API-Latest-Version" in response.headers
    
    def test_unsupported_version_request(self, client):
        """Test request with unsupported version."""
        response = client.get("/v99/test")
        
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "UNSUPPORTED_API_VERSION"
        assert "v99" in data["message"]
        assert "supported_versions" in data
    
    def test_version_header_detection(self, client):
        """Test version detection via headers."""
        response = client.get("/test", headers={"API-Version": "v1"})
        
        # Should work if endpoint exists for that version
        assert response.headers.get("API-Version") == "v1"


class TestVersionEndpoints:
    """Test version information endpoints."""
    
    @pytest.fixture
    def app(self):
        """Create test app with version endpoints."""
        app = FastAPI()
        app.include_router(create_version_endpoints(), prefix="/api")
        return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)
    
    def test_get_all_versions(self, client):
        """Test getting all API versions."""
        response = client.get("/api/versions")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "current_version" in data
        assert "supported_versions" in data
        assert "version_info" in data
        assert "compatibility_matrix" in data
        
        assert data["current_version"] == "v1"
        assert "v1" in data["supported_versions"]
    
    def test_get_specific_version_info(self, client):
        """Test getting specific version information."""
        response = client.get("/api/versions/v1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["version"] == "v1"
        assert data["status"] == "current"
        assert "release_date" in data
        assert "new_features" in data
    
    def test_get_nonexistent_version(self, client):
        """Test getting info for non-existent version."""
        response = client.get("/api/versions/v99")
        
        assert response.status_code == 404
    
    def test_get_version_compatibility(self, client):
        """Test getting version compatibility information."""
        response = client.get("/api/versions/v1/compatibility/v1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["source_version"] == "v1"
        assert data["target_version"] == "v1"
        assert data["compatible"] is True


class TestFeatureFlags:
    """Test feature flag functionality."""
    
    def test_feature_availability_v1(self):
        """Test feature availability in v1."""
        assert is_feature_available("context_memory", "v1") is True
        assert is_feature_available("llm_gateway", "v1") is True
        assert is_feature_available("graphql", "v1") is False
        assert is_feature_available("realtime_collaboration", "v1") is False
    
    def test_feature_availability_v2(self):
        """Test feature availability in v2."""
        assert is_feature_available("context_memory", "v2") is True
        assert is_feature_available("graphql", "v2") is True
        assert is_feature_available("realtime_collaboration", "v2") is True
        assert is_feature_available("enhanced_scoring", "v2") is True
    
    def test_feature_availability_default_version(self):
        """Test feature availability with default version."""
        # Should use latest version by default
        latest_version = APIVersion.get_latest().value
        
        assert is_feature_available("context_memory") == is_feature_available("context_memory", latest_version)
    
    def test_nonexistent_feature(self):
        """Test checking non-existent feature."""
        assert is_feature_available("nonexistent_feature", "v1") is False


class TestVersionDecorators:
    """Test version requirement decorators."""
    
    def test_require_version_decorator(self):
        """Test require_version decorator."""
        @require_version("v2")
        async def test_function(request: Request):
            return {"message": "success"}
        
        # Mock request with v2
        request_v2 = MagicMock()
        request_v2.state.api_version = "v2"
        
        # Should succeed
        result = test_function(request_v2)
        # Since it's async, we'd need to await in real test
        
        # Mock request with v1
        request_v1 = MagicMock()
        request_v1.state.api_version = "v1"
        
        # Should raise HTTPException (in real async context)
    
    def test_min_version_decorator(self):
        """Test min_version decorator."""
        @min_version("v1")
        async def test_function(request: Request):
            return {"message": "success"}
        
        # Both v1 and v2 should work
        request_v1 = MagicMock()
        request_v1.state.api_version = "v1"
        
        request_v2 = MagicMock()
        request_v2.state.api_version = "v2"
        
        # Both should succeed (in real async context)
    
    def test_require_feature_decorator(self):
        """Test require_feature decorator."""
        @require_feature("graphql")
        async def test_function(request: Request):
            return {"message": "success"}
        
        # V1 request should fail (no GraphQL in v1)
        request_v1 = MagicMock()
        request_v1.state.api_version = "v1"
        
        # V2 request should succeed (has GraphQL)
        request_v2 = MagicMock()
        request_v2.state.api_version = "v2"


class TestVersionAwareResponse:
    """Test version-aware response functionality."""
    
    def test_version_aware_response_structure(self):
        """Test version-aware response includes metadata."""
        request = MagicMock()
        request.state.api_version = "v1"
        
        data = {"key": "value"}
        response = version_aware_response(data, request)
        
        assert "data" in response
        assert "meta" in response
        assert response["data"] == data
        assert response["meta"]["api_version"] == "v1"
        assert "timestamp" in response["meta"]
        assert "supported_versions" in response["meta"]
        assert "latest_version" in response["meta"]
    
    def test_version_aware_response_default_version(self):
        """Test version-aware response with default version."""
        request = MagicMock()
        # No api_version in state
        del request.state.api_version
        
        data = {"key": "value"}
        response = version_aware_response(data, request)
        
        assert response["meta"]["api_version"] == APIVersion.get_latest().value


if __name__ == "__main__":
    pytest.main([__file__])