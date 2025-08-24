"""
Load testing for Context Memory Gateway API endpoints.
Tests performance under various load conditions.
"""
import asyncio
import time
import statistics
from typing import List, Dict, Any
import pytest
import httpx
import json
from concurrent.futures import ThreadPoolExecutor
import logging

# Configure logging for load tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LoadTestConfig:
    """Configuration for load tests."""
    BASE_URL = "http://localhost:8000"
    MAX_CONCURRENT_REQUESTS = 50
    TEST_DURATION_SECONDS = 60
    RAMP_UP_SECONDS = 10
    TARGET_SUCCESS_RATE = 0.95  # 95% success rate
    MAX_RESPONSE_TIME_P95 = 2.0  # 95th percentile under 2 seconds
    MAX_RESPONSE_TIME_P99 = 5.0  # 99th percentile under 5 seconds


class LoadTestResults:
    """Container for load test results."""
    
    def __init__(self):
        self.response_times: List[float] = []
        self.status_codes: List[int] = []
        self.errors: List[str] = []
        self.start_time: float = 0
        self.end_time: float = 0
        
    def add_result(self, response_time: float, status_code: int, error: str = None):
        """Add a test result."""
        self.response_times.append(response_time)
        self.status_codes.append(status_code)
        if error:
            self.errors.append(error)
    
    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculate performance metrics from results."""
        if not self.response_times:
            return {"error": "No results to analyze"}
        
        success_codes = [code for code in self.status_codes if 200 <= code < 400]
        success_rate = len(success_codes) / len(self.status_codes)
        
        return {
            "total_requests": len(self.response_times),
            "success_rate": success_rate,
            "error_rate": 1 - success_rate,
            "test_duration": self.end_time - self.start_time,
            "requests_per_second": len(self.response_times) / (self.end_time - self.start_time),
            "response_times": {
                "min": min(self.response_times),
                "max": max(self.response_times),
                "mean": statistics.mean(self.response_times),
                "median": statistics.median(self.response_times),
                "p95": self._percentile(self.response_times, 95),
                "p99": self._percentile(self.response_times, 99),
            },
            "status_code_distribution": self._count_status_codes(),
            "error_count": len(self.errors),
            "errors": self.errors[:10]  # First 10 errors for analysis
        }
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of response times."""
        sorted_data = sorted(data)
        index = int(percentile / 100.0 * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def _count_status_codes(self) -> Dict[int, int]:
        """Count occurrences of each status code."""
        counts = {}
        for code in self.status_codes:
            counts[code] = counts.get(code, 0) + 1
        return counts


class LoadTester:
    """Main load testing class."""
    
    def __init__(self, base_url: str = LoadTestConfig.BASE_URL):
        self.base_url = base_url
        
    async def single_request(self, session: httpx.AsyncClient, endpoint: str, 
                           method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        """Make a single request and measure performance."""
        start_time = time.time()
        error_message = None
        
        try:
            if method == "GET":
                response = await session.get(endpoint)
            elif method == "POST":
                response = await session.post(endpoint, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response_time = time.time() - start_time
            return {
                "response_time": response_time,
                "status_code": response.status_code,
                "error": None
            }
            
        except Exception as e:
            response_time = time.time() - start_time
            return {
                "response_time": response_time,
                "status_code": 500,
                "error": str(e)
            }
    
    async def load_test_endpoint(self, endpoint: str, concurrent_users: int, 
                               duration_seconds: int, method: str = "GET", 
                               data: Dict = None) -> LoadTestResults:
        """Run load test against a specific endpoint."""
        results = LoadTestResults()
        results.start_time = time.time()
        
        logger.info(f"Starting load test: {endpoint} with {concurrent_users} concurrent users for {duration_seconds}s")
        
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as session:
            # Create semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(concurrent_users)
            
            async def bounded_request():
                async with semaphore:
                    return await self.single_request(session, endpoint, method, data)
            
            # Generate requests for the specified duration
            tasks = []
            end_time = time.time() + duration_seconds
            
            while time.time() < end_time:
                task = asyncio.create_task(bounded_request())
                tasks.append(task)
                
                # Small delay to prevent overwhelming the system
                await asyncio.sleep(0.01)
            
            # Wait for all requests to complete
            logger.info(f"Waiting for {len(tasks)} requests to complete...")
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in task_results:
                if isinstance(result, Exception):
                    results.add_result(0, 500, str(result))
                else:
                    results.add_result(
                        result["response_time"],
                        result["status_code"],
                        result["error"]
                    )
        
        results.end_time = time.time()
        return results


@pytest.mark.load
class TestAPIPerformance:
    """Load tests for API performance."""
    
    def setup_method(self):
        """Setup for each test method."""
        self.load_tester = LoadTester()
    
    @pytest.mark.asyncio
    async def test_health_endpoint_load(self):
        """Load test the basic health endpoint."""
        results = await self.load_tester.load_test_endpoint(
            "/health",
            concurrent_users=20,
            duration_seconds=30
        )
        
        metrics = results.calculate_metrics()
        logger.info(f"Health endpoint metrics: {json.dumps(metrics, indent=2)}")
        
        # Assertions
        assert metrics["success_rate"] >= LoadTestConfig.TARGET_SUCCESS_RATE
        assert metrics["response_times"]["p95"] <= LoadTestConfig.MAX_RESPONSE_TIME_P95
        assert metrics["response_times"]["p99"] <= LoadTestConfig.MAX_RESPONSE_TIME_P99
        assert metrics["requests_per_second"] > 50  # Should handle at least 50 RPS
    
    @pytest.mark.asyncio
    async def test_metrics_endpoint_load(self):
        """Load test the Prometheus metrics endpoint."""
        results = await self.load_tester.load_test_endpoint(
            "/metrics",
            concurrent_users=10,
            duration_seconds=20
        )
        
        metrics = results.calculate_metrics()
        logger.info(f"Metrics endpoint metrics: {json.dumps(metrics, indent=2)}")
        
        # Metrics endpoint should be very reliable
        assert metrics["success_rate"] >= 0.99
        assert metrics["response_times"]["p95"] <= 1.0  # Faster than regular endpoints
    
    @pytest.mark.asyncio
    async def test_readiness_probe_load(self):
        """Load test the readiness probe under load."""
        results = await self.load_tester.load_test_endpoint(
            "/health/ready",
            concurrent_users=15,
            duration_seconds=30
        )
        
        metrics = results.calculate_metrics()
        logger.info(f"Readiness probe metrics: {json.dumps(metrics, indent=2)}")
        
        # Readiness probe may be slower due to dependency checks
        assert metrics["success_rate"] >= 0.90
        assert metrics["response_times"]["p95"] <= 5.0
        assert metrics["response_times"]["mean"] <= 2.0
    
    @pytest.mark.asyncio
    async def test_api_v1_models_load(self):
        """Load test the models API endpoint."""
        results = await self.load_tester.load_test_endpoint(
            "/v1/models",
            concurrent_users=25,
            duration_seconds=45
        )
        
        metrics = results.calculate_metrics()
        logger.info(f"Models API metrics: {json.dumps(metrics, indent=2)}")
        
        assert metrics["success_rate"] >= LoadTestConfig.TARGET_SUCCESS_RATE
        assert metrics["response_times"]["p95"] <= LoadTestConfig.MAX_RESPONSE_TIME_P95
        assert metrics["requests_per_second"] > 30
    
    @pytest.mark.asyncio
    async def test_mixed_endpoint_load(self):
        """Test mixed load across multiple endpoints."""
        endpoints = [
            "/health",
            "/health/live",
            "/metrics",
            "/v1/models"
        ]
        
        # Run concurrent tests on different endpoints
        tasks = []
        for endpoint in endpoints:
            task = self.load_tester.load_test_endpoint(
                endpoint,
                concurrent_users=10,
                duration_seconds=30
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # Analyze combined results
        total_requests = sum(r.calculate_metrics()["total_requests"] for r in results)
        overall_success_rate = (
            sum(r.calculate_metrics()["success_rate"] * r.calculate_metrics()["total_requests"] 
                for r in results) / total_requests
        )
        
        logger.info(f"Mixed load test - Total requests: {total_requests}, Success rate: {overall_success_rate}")
        
        # Overall system should handle mixed load well
        assert overall_success_rate >= 0.90
        assert total_requests > 1000  # Should handle significant volume


@pytest.mark.stress
class TestStressLimits:
    """Stress tests to find system limits."""
    
    def setup_method(self):
        """Setup for each test method."""
        self.load_tester = LoadTester()
    
    @pytest.mark.asyncio
    async def test_find_max_concurrent_users(self):
        """Find the maximum number of concurrent users the system can handle."""
        concurrent_levels = [10, 25, 50, 75, 100, 150, 200]
        results = {}
        
        for concurrent_users in concurrent_levels:
            logger.info(f"Testing with {concurrent_users} concurrent users...")
            
            test_results = await self.load_tester.load_test_endpoint(
                "/health",
                concurrent_users=concurrent_users,
                duration_seconds=20
            )
            
            metrics = test_results.calculate_metrics()
            results[concurrent_users] = metrics
            
            logger.info(f"  Success rate: {metrics['success_rate']:.2f}")
            logger.info(f"  P95 response time: {metrics['response_times']['p95']:.2f}s")
            logger.info(f"  RPS: {metrics['requests_per_second']:.1f}")
            
            # Stop if performance degrades significantly
            if (metrics["success_rate"] < 0.80 or 
                metrics["response_times"]["p95"] > 10.0):
                logger.warning(f"Performance degradation detected at {concurrent_users} users")
                break
        
        # Find the maximum sustainable load
        max_sustainable = 0
        for users, metrics in results.items():
            if (metrics["success_rate"] >= LoadTestConfig.TARGET_SUCCESS_RATE and 
                metrics["response_times"]["p95"] <= LoadTestConfig.MAX_RESPONSE_TIME_P95):
                max_sustainable = users
        
        logger.info(f"Maximum sustainable concurrent users: {max_sustainable}")
        assert max_sustainable >= 25  # Should handle at least 25 concurrent users
    
    @pytest.mark.asyncio
    async def test_sustained_load(self):
        """Test system performance under sustained load."""
        # Run sustained load for longer period
        results = await self.load_tester.load_test_endpoint(
            "/health",
            concurrent_users=30,
            duration_seconds=120  # 2 minutes
        )
        
        metrics = results.calculate_metrics()
        logger.info(f"Sustained load metrics: {json.dumps(metrics, indent=2)}")
        
        # System should maintain performance over time
        assert metrics["success_rate"] >= 0.95
        assert metrics["response_times"]["p95"] <= 3.0
        assert metrics["requests_per_second"] > 40


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "load"])