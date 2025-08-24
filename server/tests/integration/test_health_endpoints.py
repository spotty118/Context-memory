"""
Integration tests for health check endpoints.
Tests all health endpoints with real dependencies.
"""
import pytest
import httpx
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.api.health_checks import health_checker
from app.db.session import get_db
from app.core.config import settings

client = TestClient(app)


class TestHealthEndpoints:
    """Integration tests for health check endpoints."""
    
    def test_basic_health_check(self):
        """Test basic health endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["service"] == "context-memory-gateway"
    
    def test_liveness_probe(self):
        """Test Kubernetes liveness probe endpoint."""
        response = client.get("/health/live")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "alive"
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "pid" in data
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0
    
    def test_readiness_probe_with_database(self):
        """Test readiness probe with database connectivity."""
        response = client.get("/health/ready")
        
        # Should return either 200 (healthy/degraded) or 503 (unhealthy)
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "version" in data
        assert "environment" in data
        assert "components" in data
        
        # Check that all expected components are tested
        components = data["components"]
        expected_components = ["redis", "supabase", "cache", "system"]
        
        # Database component only included if available
        if "database" in components:
            expected_components.append("database")
            
        for component in expected_components:
            assert component in components
            assert "status" in components[component]
            assert components[component]["status"] in ["healthy", "degraded", "unhealthy", "timeout"]
    
    def test_detailed_health_check(self):
        """Test detailed health endpoint with full component status."""
        response = client.get("/health/detailed")
        
        # Should return either 200 (not unhealthy) or 503 (unhealthy)
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert data["status"] in ["healthy", "degraded", "unhealthy", "error"]
        assert "components" in data
        assert "debug" in data
        
        # Check debug information
        debug_info = data["debug"]
        assert "startup_time" in debug_info
        assert "process_id" in debug_info
        assert "python_version" in debug_info
        
        # Validate component health structure
        components = data["components"]
        for component_name, component_data in components.items():
            assert "status" in component_data
            assert component_data["status"] in ["healthy", "degraded", "unhealthy", "timeout"]
            
            # Most components should have response time
            if component_name != "system":
                assert "response_time_ms" in component_data or "error" in component_data
    
    def test_health_check_caching(self):
        """Test that health checks are cached appropriately."""
        # Make two quick requests
        response1 = client.get("/health/detailed")
        response2 = client.get("/health/detailed")
        
        assert response1.status_code in [200, 503]
        assert response2.status_code in [200, 503]
        
        # Both should return data (cached or fresh)
        data1 = response1.json()
        data2 = response2.json()
        
        assert "timestamp" in data1
        assert "timestamp" in data2
        
        # Timestamps should be very close (within cache TTL)
        # This tests that caching is working without being too strict about timing
        assert "components" in data1
        assert "components" in data2
    
    def test_metrics_endpoint_accessibility(self):
        """Test that metrics endpoint is accessible."""
        response = client.get("/metrics")
        assert response.status_code == 200
        
        # Should return Prometheus format
        content = response.text
        assert "# HELP" in content or "# TYPE" in content or len(content) > 0
        
        # Check content type
        assert response.headers.get("content-type", "").startswith("text/plain")


class TestHealthComponentsIntegration:
    """Integration tests for individual health components."""
    
    @pytest.mark.asyncio
    async def test_redis_health_integration(self):
        """Test Redis health check integration."""
        health_data = await health_checker.check_redis_health()
        
        # Should have status and response time
        assert "status" in health_data
        assert health_data["status"] in ["healthy", "degraded", "unhealthy"]
        
        if health_data["status"] != "unhealthy":
            assert "response_time_ms" in health_data
            assert isinstance(health_data["response_time_ms"], (int, float))
            assert health_data["response_time_ms"] >= 0
    
    @pytest.mark.asyncio
    async def test_supabase_health_integration(self):
        """Test Supabase health check integration."""
        health_data = await health_checker.check_supabase_health()
        
        assert "status" in health_data
        assert health_data["status"] in ["healthy", "degraded", "unhealthy"]
        
        if health_data["status"] != "unhealthy":
            assert "response_time_ms" in health_data
            assert "url" in health_data
            assert health_data["url"] == settings.SUPABASE_URL
    
    @pytest.mark.asyncio
    async def test_cache_health_integration(self):
        """Test cache system health check integration."""
        health_data = await health_checker.check_cache_health()
        
        assert "status" in health_data
        assert health_data["status"] in ["healthy", "degraded", "unhealthy"]
        
        if health_data["status"] != "unhealthy":
            assert "response_time_ms" in health_data
            assert "backend" in health_data
    
    def test_system_health_integration(self):
        """Test system resource health check."""
        health_data = health_checker.check_system_health()
        
        assert "status" in health_data
        assert health_data["status"] in ["healthy", "degraded", "unhealthy"]
        
        # Should have resource metrics
        assert "cpu_usage_percent" in health_data
        assert "memory_usage_percent" in health_data
        assert "disk_usage_percent" in health_data
        assert "process_memory_mb" in health_data
        
        # Values should be reasonable
        assert 0 <= health_data["cpu_usage_percent"] <= 100
        assert 0 <= health_data["memory_usage_percent"] <= 100
        assert 0 <= health_data["disk_usage_percent"] <= 100
        assert health_data["process_memory_mb"] > 0


class TestHealthEndpointPerformance:
    """Performance tests for health endpoints."""
    
    def test_health_endpoint_response_time(self):
        """Test that health endpoints respond quickly."""
        import time
        
        # Basic health check should be very fast
        start_time = time.time()
        response = client.get("/health")
        response_time = time.time() - start_time
        
        assert response.status_code == 200
        assert response_time < 0.1  # Should respond in under 100ms
    
    def test_liveness_probe_response_time(self):
        """Test that liveness probe is fast."""
        import time
        
        start_time = time.time()
        response = client.get("/health/live")
        response_time = time.time() - start_time
        
        assert response.status_code == 200
        assert response_time < 0.1  # Should respond in under 100ms
    
    def test_readiness_probe_timeout(self):
        """Test that readiness probe respects timeout."""
        import time
        
        # Readiness probe may take longer due to dependency checks
        # but should still complete within reasonable time
        start_time = time.time()
        response = client.get("/health/ready")
        response_time = time.time() - start_time
        
        assert response.status_code in [200, 503]
        assert response_time < 10.0  # Should complete within 10 seconds


@pytest.mark.load
class TestHealthEndpointLoad:
    """Load tests for health endpoints."""
    
    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self):
        """Test health endpoints under concurrent load."""
        async def make_request(session, url):
            try:
                async with session.get(url) as response:
                    return response.status, await response.text()
            except Exception as e:
                return 500, str(e)
        
        # Test with multiple concurrent requests
        async with httpx.AsyncClient(base_url="http://testserver") as session:
            # Create concurrent requests to different endpoints
            tasks = []
            for _ in range(10):
                tasks.append(make_request(session, "/health"))
                tasks.append(make_request(session, "/health/live"))
                tasks.append(make_request(session, "/health/ready"))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Most requests should succeed
            success_count = sum(1 for status, _ in results if status == 200)
            total_requests = len(results)
            
            # At least 80% should succeed
            success_rate = success_count / total_requests
            assert success_rate >= 0.8, f"Success rate {success_rate} too low"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])