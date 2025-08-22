"""
Tests for the performance benchmarking system.
Tests benchmark functionality, configuration, and metrics calculation.
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.core.benchmarks import (
    PerformanceBenchmark, BenchmarkConfig, BenchmarkEndpoint,
    BenchmarkType, BenchmarkResult, BenchmarkMetrics
)


@pytest.mark.asyncio
class TestBenchmarkEndpoint:
    """Test benchmark endpoint configuration."""
    
    def test_endpoint_creation(self):
        """Test creating a benchmark endpoint."""
        def payload_gen():
            return {"test": "data"}
        
        endpoint = BenchmarkEndpoint(
            name="test_endpoint",
            path="/api/test",
            method="POST",
            payload_generator=payload_gen,
            headers={"Content-Type": "application/json"},
            expected_status=201
        )
        
        assert endpoint.name == "test_endpoint"
        assert endpoint.path == "/api/test"
        assert endpoint.method == "POST"
        assert endpoint.expected_status == 201
        assert endpoint.generate_payload() == {"test": "data"}
    
    def test_endpoint_without_payload(self):
        """Test endpoint without payload generator."""
        endpoint = BenchmarkEndpoint("simple", "/health", "GET")
        
        assert endpoint.name == "simple"
        assert endpoint.method == "GET"
        assert endpoint.generate_payload() is None


@pytest.mark.asyncio
class TestBenchmarkConfig:
    """Test benchmark configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = BenchmarkConfig()
        
        assert config.base_url == "http://localhost:8000"
        assert config.concurrent_requests == 10
        assert config.total_requests == 100
        assert config.request_timeout == 30
        assert config.warm_up_requests == 10
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = BenchmarkConfig(
            base_url="http://example.com",
            concurrent_requests=20,
            total_requests=200,
            api_key="test_key"
        )
        
        assert config.base_url == "http://example.com"
        assert config.concurrent_requests == 20
        assert config.total_requests == 200
        assert config.api_key == "test_key"


@pytest.mark.asyncio
class TestBenchmarkResult:
    """Test benchmark result data structure."""
    
    def test_result_creation(self):
        """Test creating a benchmark result."""
        result = BenchmarkResult(
            endpoint="test_endpoint",
            method="GET",
            status_code=200,
            response_time_ms=150.5,
            payload_size_bytes=100,
            response_size_bytes=500
        )
        
        assert result.endpoint == "test_endpoint"
        assert result.method == "GET"
        assert result.status_code == 200
        assert result.response_time_ms == 150.5
        assert result.error is None
        assert isinstance(result.timestamp, datetime)
    
    def test_result_with_error(self):
        """Test result with error."""
        result = BenchmarkResult(
            endpoint="failing_endpoint",
            method="POST",
            status_code=500,
            response_time_ms=1000.0,
            payload_size_bytes=200,
            response_size_bytes=0,
            error="Internal server error"
        )
        
        assert result.error == "Internal server error"
        assert result.status_code == 500


@pytest.mark.asyncio
class TestPerformanceBenchmark:
    """Test main benchmark functionality."""
    
    @pytest.fixture
    def benchmark_config(self):
        """Create test benchmark configuration."""
        return BenchmarkConfig(
            base_url="http://localhost:8000",
            total_requests=10,
            concurrent_requests=2,
            warm_up_requests=2,
            request_timeout=5
        )
    
    @pytest.fixture
    def test_endpoints(self):
        """Create test endpoints."""
        return [
            BenchmarkEndpoint("health", "/health", "GET"),
            BenchmarkEndpoint("models", "/v1/models", "GET")
        ]
    
    async def test_benchmark_initialization(self, benchmark_config):
        """Test benchmark initialization."""
        benchmark = PerformanceBenchmark(benchmark_config)
        
        assert benchmark.config == benchmark_config
        assert benchmark.results == []
        assert benchmark.status.value == "pending"
    
    @patch('aiohttp.ClientSession.request')
    async def test_make_request_success(self, mock_request, benchmark_config, test_endpoints):
        """Test making a successful request."""
        # Mock successful response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"status": "ok"}'
        mock_request.return_value.__aenter__.return_value = mock_response
        
        benchmark = PerformanceBenchmark(benchmark_config)
        
        # Create a mock session
        session = AsyncMock()
        session.request.return_value.__aenter__.return_value = mock_response
        
        result = await benchmark._make_request(session, test_endpoints[0])
        
        assert result.endpoint == "health"
        assert result.method == "GET"
        assert result.status_code == 200
        assert result.response_time_ms > 0
        assert result.error is None
    
    @patch('aiohttp.ClientSession.request')
    async def test_make_request_timeout(self, mock_request, benchmark_config, test_endpoints):
        """Test request timeout handling."""
        # Mock timeout
        mock_request.side_effect = asyncio.TimeoutError()
        
        benchmark = PerformanceBenchmark(benchmark_config)
        session = AsyncMock()
        session.request.side_effect = asyncio.TimeoutError()
        
        result = await benchmark._make_request(session, test_endpoints[0])
        
        assert result.endpoint == "health"
        assert result.status_code == 0
        assert result.error == "Request timeout"
    
    async def test_calculate_metrics(self, benchmark_config):
        """Test metrics calculation."""
        benchmark = PerformanceBenchmark(benchmark_config)
        
        # Create test results
        results = [
            BenchmarkResult("test", "GET", 200, 100.0, 0, 100),
            BenchmarkResult("test", "GET", 200, 200.0, 0, 100),
            BenchmarkResult("test", "GET", 200, 150.0, 0, 100),
            BenchmarkResult("test", "GET", 500, 300.0, 0, 100, error="Server error"),
        ]
        
        # Set timestamps for duration calculation
        base_time = datetime.utcnow()
        for i, result in enumerate(results):
            result.timestamp = base_time.replace(second=i)
        
        metrics = benchmark._calculate_metrics("test", "latency", results)
        
        assert metrics.endpoint == "test"
        assert metrics.test_type == "latency"
        assert metrics.total_requests == 4
        assert metrics.successful_requests == 3
        assert metrics.failed_requests == 1
        assert metrics.error_rate_percent == 25.0
        assert metrics.avg_response_time_ms == 150.0  # (100+200+150)/3
        assert metrics.median_response_time_ms == 150.0
        assert metrics.min_response_time_ms == 100.0
        assert metrics.max_response_time_ms == 200.0
    
    @patch('app.core.benchmarks.PerformanceBenchmark._make_request')
    @patch('app.core.benchmarks.PerformanceBenchmark._warm_up')
    async def test_latency_benchmark(self, mock_warm_up, mock_make_request, benchmark_config, test_endpoints):
        """Test latency benchmark execution."""
        mock_warm_up.return_value = None
        
        # Mock successful requests
        mock_results = []
        for i in range(benchmark_config.total_requests):
            result = BenchmarkResult("health", "GET", 200, 100.0 + i * 10, 0, 100)
            mock_results.append(result)
        
        mock_make_request.side_effect = mock_results
        
        benchmark = PerformanceBenchmark(benchmark_config)
        
        with patch.object(benchmark, '_create_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()
            
            metrics = await benchmark._run_latency_benchmark([test_endpoints[0]])
        
        assert "health" in metrics
        assert mock_make_request.call_count == benchmark_config.total_requests
        assert mock_warm_up.called
    
    @patch('app.core.benchmarks.PerformanceBenchmark._make_request')
    @patch('app.core.benchmarks.PerformanceBenchmark._warm_up')
    async def test_throughput_benchmark(self, mock_warm_up, mock_make_request, benchmark_config, test_endpoints):
        """Test throughput benchmark execution."""
        mock_warm_up.return_value = None
        
        # Mock successful requests
        async def mock_request_func(*args, **kwargs):
            await asyncio.sleep(0.01)  # Small delay to simulate work
            return BenchmarkResult("health", "GET", 200, 50.0, 0, 100)
        
        mock_make_request.side_effect = mock_request_func
        
        benchmark = PerformanceBenchmark(benchmark_config)
        
        with patch.object(benchmark, '_create_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()
            
            metrics = await benchmark._run_throughput_benchmark([test_endpoints[0]])
        
        assert "health" in metrics
        assert mock_make_request.call_count == benchmark_config.total_requests
        assert metrics["health"].requests_per_second > 0


@pytest.mark.asyncio
class TestBenchmarkMetricsCalculation:
    """Test metrics calculation edge cases."""
    
    def test_empty_results(self):
        """Test metrics calculation with empty results."""
        benchmark = PerformanceBenchmark(BenchmarkConfig())
        
        with pytest.raises(ValueError, match="No results to calculate metrics from"):
            benchmark._calculate_metrics("test", "latency", [])
    
    def test_all_failed_requests(self):
        """Test metrics with all failed requests."""
        benchmark = PerformanceBenchmark(BenchmarkConfig())
        
        results = [
            BenchmarkResult("test", "GET", 500, 0, 0, 0, error="Error 1"),
            BenchmarkResult("test", "GET", 404, 0, 0, 0, error="Error 2"),
        ]
        
        base_time = datetime.utcnow()
        for i, result in enumerate(results):
            result.timestamp = base_time.replace(second=i)
        
        metrics = benchmark._calculate_metrics("test", "stress", results)
        
        assert metrics.total_requests == 2
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 2
        assert metrics.error_rate_percent == 100.0
        assert metrics.avg_response_time_ms == 0
        assert metrics.requests_per_second > 0  # Based on time difference
    
    def test_mixed_success_failure(self):
        """Test metrics with mixed success and failure."""
        benchmark = PerformanceBenchmark(BenchmarkConfig())
        
        results = [
            BenchmarkResult("test", "GET", 200, 100.0, 0, 100),
            BenchmarkResult("test", "GET", 500, 200.0, 0, 0, error="Server error"),
            BenchmarkResult("test", "GET", 200, 150.0, 0, 100),
        ]
        
        base_time = datetime.utcnow()
        for i, result in enumerate(results):
            result.timestamp = base_time.replace(second=i)
        
        metrics = benchmark._calculate_metrics("test", "load", results)
        
        assert metrics.total_requests == 3
        assert metrics.successful_requests == 2
        assert metrics.failed_requests == 1
        assert metrics.error_rate_percent == pytest.approx(33.33, rel=1e-2)
        assert metrics.avg_response_time_ms == 125.0  # (100+150)/2


@pytest.mark.asyncio 
class TestBenchmarkTypes:
    """Test different benchmark types."""
    
    @pytest.fixture
    def quick_config(self):
        """Quick test configuration."""
        return BenchmarkConfig(
            total_requests=5,
            concurrent_requests=2,
            warm_up_requests=1,
            test_duration_seconds=2
        )
    
    @pytest.fixture
    def simple_endpoint(self):
        """Simple test endpoint."""
        return BenchmarkEndpoint("simple", "/health", "GET")
    
    async def test_benchmark_type_enum(self):
        """Test benchmark type enumeration."""
        assert BenchmarkType.LATENCY.value == "latency"
        assert BenchmarkType.THROUGHPUT.value == "throughput"
        assert BenchmarkType.LOAD_TEST.value == "load_test"
        assert BenchmarkType.STRESS_TEST.value == "stress_test"
        assert BenchmarkType.ENDURANCE.value == "endurance"
    
    @patch('app.core.benchmarks.PerformanceBenchmark._run_latency_benchmark')
    async def test_run_benchmark_latency(self, mock_latency, quick_config, simple_endpoint):
        """Test running latency benchmark."""
        mock_latency.return_value = {"simple": MagicMock()}
        
        benchmark = PerformanceBenchmark(quick_config)
        
        result = await benchmark.run_benchmark([simple_endpoint], BenchmarkType.LATENCY)
        
        assert mock_latency.called
        assert benchmark.status.value == "completed"
        assert benchmark.start_time is not None
        assert benchmark.end_time is not None
    
    @patch('app.core.benchmarks.PerformanceBenchmark._run_throughput_benchmark')
    async def test_run_benchmark_throughput(self, mock_throughput, quick_config, simple_endpoint):
        """Test running throughput benchmark."""
        mock_throughput.return_value = {"simple": MagicMock()}
        
        benchmark = PerformanceBenchmark(quick_config)
        
        result = await benchmark.run_benchmark([simple_endpoint], BenchmarkType.THROUGHPUT)
        
        assert mock_throughput.called
        assert benchmark.status.value == "completed"


if __name__ == "__main__":
    pytest.main([__file__])