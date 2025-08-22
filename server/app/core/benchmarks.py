"""
Performance benchmarking system for Context Memory Gateway.
Establishes baseline metrics for API response times and throughput.
"""
import asyncio
import time
import statistics
import json
from typing import Dict, Any, List, Optional, Callable, NamedTuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
import concurrent.futures
import aiohttp
import structlog
from contextlib import asynccontextmanager

from app.core.config import settings


logger = structlog.get_logger(__name__)


class BenchmarkType(Enum):
    """Types of performance benchmarks."""
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    LOAD_TEST = "load_test"
    STRESS_TEST = "stress_test"
    ENDURANCE = "endurance"


class BenchmarkStatus(Enum):
    """Benchmark execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BenchmarkResult:
    """Single benchmark test result."""
    endpoint: str
    method: str
    status_code: int
    response_time_ms: float
    payload_size_bytes: int
    response_size_bytes: int
    error: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class BenchmarkMetrics:
    """Aggregated benchmark metrics."""
    endpoint: str
    test_type: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time_ms: float
    median_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    requests_per_second: float
    errors_per_second: float
    error_rate_percent: float
    throughput_mbps: float
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark tests."""
    base_url: str = "http://localhost:8000"
    api_key: Optional[str] = None
    concurrent_requests: int = 10
    total_requests: int = 100
    request_timeout: int = 30
    warm_up_requests: int = 10
    test_duration_seconds: Optional[int] = None
    rate_limit_rps: Optional[int] = None
    payload_size_kb: int = 1
    enable_detailed_logging: bool = False


class BenchmarkEndpoint:
    """Defines an endpoint to benchmark."""
    
    def __init__(
        self,
        name: str,
        path: str,
        method: str = "GET",
        payload_generator: Optional[Callable[[], Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None,
        expected_status: int = 200
    ):
        self.name = name
        self.path = path
        self.method = method.upper()
        self.payload_generator = payload_generator
        self.headers = headers or {}
        self.expected_status = expected_status
    
    def generate_payload(self) -> Optional[Dict[str, Any]]:
        """Generate test payload."""
        return self.payload_generator() if self.payload_generator else None


class PerformanceBenchmark:
    """
    Main performance benchmarking class.
    Provides comprehensive testing for API endpoints.
    """
    
    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.results: List[BenchmarkResult] = []
        self.status = BenchmarkStatus.PENDING
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        
    async def run_benchmark(
        self,
        endpoints: List[BenchmarkEndpoint],
        benchmark_type: BenchmarkType = BenchmarkType.LATENCY
    ) -> Dict[str, BenchmarkMetrics]:
        """
        Run comprehensive benchmark tests.
        
        Args:
            endpoints: List of endpoints to test
            benchmark_type: Type of benchmark to run
            
        Returns:
            Dictionary of metrics per endpoint
        """
        logger.info(
            "benchmark_starting",
            type=benchmark_type.value,
            endpoints=len(endpoints),
            config=asdict(self.config)
        )
        
        self.status = BenchmarkStatus.RUNNING
        self.start_time = datetime.utcnow()
        
        try:
            if benchmark_type == BenchmarkType.LATENCY:
                metrics = await self._run_latency_benchmark(endpoints)
            elif benchmark_type == BenchmarkType.THROUGHPUT:
                metrics = await self._run_throughput_benchmark(endpoints)
            elif benchmark_type == BenchmarkType.LOAD_TEST:
                metrics = await self._run_load_test(endpoints)
            elif benchmark_type == BenchmarkType.STRESS_TEST:
                metrics = await self._run_stress_test(endpoints)
            elif benchmark_type == BenchmarkType.ENDURANCE:
                metrics = await self._run_endurance_test(endpoints)
            else:
                raise ValueError(f"Unsupported benchmark type: {benchmark_type}")
            
            self.status = BenchmarkStatus.COMPLETED
            
        except Exception as e:
            self.status = BenchmarkStatus.FAILED
            logger.error("benchmark_failed", error=str(e))
            raise
        
        finally:
            self.end_time = datetime.utcnow()
        
        logger.info(
            "benchmark_completed",
            status=self.status.value,
            duration_seconds=(self.end_time - self.start_time).total_seconds(),
            total_results=len(self.results)
        )
        
        return metrics
    
    async def _run_latency_benchmark(
        self, 
        endpoints: List[BenchmarkEndpoint]
    ) -> Dict[str, BenchmarkMetrics]:
        """Run latency-focused benchmark."""
        metrics = {}
        
        for endpoint in endpoints:
            logger.info("testing_endpoint_latency", endpoint=endpoint.name)
            
            # Warm-up requests
            await self._warm_up(endpoint)
            
            # Collect latency data
            endpoint_results = []
            
            async with self._create_session() as session:
                for i in range(self.config.total_requests):
                    result = await self._make_request(session, endpoint)
                    endpoint_results.append(result)
                    
                    if self.config.enable_detailed_logging and i % 10 == 0:
                        logger.debug(
                            "latency_progress",
                            endpoint=endpoint.name,
                            progress=f"{i+1}/{self.config.total_requests}",
                            avg_latency=statistics.mean([r.response_time_ms for r in endpoint_results])
                        )
            
            metrics[endpoint.name] = self._calculate_metrics(endpoint.name, "latency", endpoint_results)
        
        return metrics
    
    async def _run_throughput_benchmark(
        self, 
        endpoints: List[BenchmarkEndpoint]
    ) -> Dict[str, BenchmarkMetrics]:
        """Run throughput-focused benchmark."""
        metrics = {}
        
        for endpoint in endpoints:
            logger.info("testing_endpoint_throughput", endpoint=endpoint.name)
            
            await self._warm_up(endpoint)
            
            start_time = time.time()
            endpoint_results = []
            
            async with self._create_session() as session:
                # Create semaphore for concurrency control
                semaphore = asyncio.Semaphore(self.config.concurrent_requests)
                
                async def make_concurrent_request():
                    async with semaphore:
                        return await self._make_request(session, endpoint)
                
                # Create all tasks
                tasks = [
                    make_concurrent_request() 
                    for _ in range(self.config.total_requests)
                ]
                
                # Execute with progress tracking
                for i, task in enumerate(asyncio.as_completed(tasks)):
                    result = await task
                    endpoint_results.append(result)
                    
                    if self.config.enable_detailed_logging and i % 20 == 0:
                        elapsed = time.time() - start_time
                        current_rps = (i + 1) / elapsed if elapsed > 0 else 0
                        logger.debug(
                            "throughput_progress",
                            endpoint=endpoint.name,
                            completed=i+1,
                            current_rps=round(current_rps, 2)
                        )
            
            metrics[endpoint.name] = self._calculate_metrics(endpoint.name, "throughput", endpoint_results)
        
        return metrics
    
    async def _run_load_test(
        self, 
        endpoints: List[BenchmarkEndpoint]
    ) -> Dict[str, BenchmarkMetrics]:
        """Run load test with gradual ramp-up."""
        metrics = {}
        
        for endpoint in endpoints:
            logger.info("load_testing_endpoint", endpoint=endpoint.name)
            
            await self._warm_up(endpoint)
            
            endpoint_results = []
            
            # Gradual ramp-up pattern
            ramp_steps = [
                (10, 25),   # 10 concurrent for 25 requests
                (25, 50),   # 25 concurrent for 50 requests
                (50, 75),   # 50 concurrent for 75 requests
                (100, 100)  # 100 concurrent for 100 requests
            ]
            
            async with self._create_session() as session:
                for concurrency, request_count in ramp_steps:
                    logger.info(
                        "load_test_step",
                        endpoint=endpoint.name,
                        concurrency=concurrency,
                        requests=request_count
                    )
                    
                    semaphore = asyncio.Semaphore(concurrency)
                    
                    async def make_load_request():
                        async with semaphore:
                            return await self._make_request(session, endpoint)
                    
                    tasks = [make_load_request() for _ in range(request_count)]
                    step_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Filter out exceptions and add successful results
                    valid_results = [r for r in step_results if isinstance(r, BenchmarkResult)]
                    endpoint_results.extend(valid_results)
                    
                    # Log step completion
                    step_success_rate = len(valid_results) / request_count * 100
                    logger.info(
                        "load_test_step_completed",
                        endpoint=endpoint.name,
                        concurrency=concurrency,
                        success_rate=f"{step_success_rate:.1f}%"
                    )
            
            metrics[endpoint.name] = self._calculate_metrics(endpoint.name, "load_test", endpoint_results)
        
        return metrics
    
    async def _run_stress_test(
        self, 
        endpoints: List[BenchmarkEndpoint]
    ) -> Dict[str, BenchmarkMetrics]:
        """Run stress test with very high concurrency."""
        metrics = {}
        
        for endpoint in endpoints:
            logger.info("stress_testing_endpoint", endpoint=endpoint.name)
            
            await self._warm_up(endpoint)
            
            # Stress test with high concurrency
            stress_concurrency = self.config.concurrent_requests * 5  # 5x normal
            endpoint_results = []
            
            async with self._create_session() as session:
                semaphore = asyncio.Semaphore(stress_concurrency)
                
                async def make_stress_request():
                    try:
                        async with semaphore:
                            return await self._make_request(session, endpoint)
                    except Exception as e:
                        # Return error result for stress testing
                        return BenchmarkResult(
                            endpoint=endpoint.name,
                            method=endpoint.method,
                            status_code=0,
                            response_time_ms=0,
                            payload_size_bytes=0,
                            response_size_bytes=0,
                            error=str(e)
                        )
                
                tasks = [make_stress_request() for _ in range(self.config.total_requests)]
                endpoint_results = await asyncio.gather(*tasks)
            
            metrics[endpoint.name] = self._calculate_metrics(endpoint.name, "stress_test", endpoint_results)
        
        return metrics
    
    async def _run_endurance_test(
        self, 
        endpoints: List[BenchmarkEndpoint]
    ) -> Dict[str, BenchmarkMetrics]:
        """Run endurance test over extended period."""
        metrics = {}
        test_duration = self.config.test_duration_seconds or 300  # Default 5 minutes
        
        for endpoint in endpoints:
            logger.info(
                "endurance_testing_endpoint",
                endpoint=endpoint.name,
                duration_seconds=test_duration
            )
            
            await self._warm_up(endpoint)
            
            endpoint_results = []
            start_time = time.time()
            request_count = 0
            
            async with self._create_session() as session:
                while (time.time() - start_time) < test_duration:
                    # Rate limiting if specified
                    if self.config.rate_limit_rps:
                        await asyncio.sleep(1.0 / self.config.rate_limit_rps)
                    
                    result = await self._make_request(session, endpoint)
                    endpoint_results.append(result)
                    request_count += 1
                    
                    # Progress logging every minute
                    if request_count % 60 == 0:
                        elapsed = time.time() - start_time
                        current_rps = request_count / elapsed
                        logger.info(
                            "endurance_progress",
                            endpoint=endpoint.name,
                            elapsed_minutes=round(elapsed / 60, 1),
                            requests_completed=request_count,
                            current_rps=round(current_rps, 2)
                        )
            
            metrics[endpoint.name] = self._calculate_metrics(endpoint.name, "endurance", endpoint_results)
        
        return metrics
    
    async def _warm_up(self, endpoint: BenchmarkEndpoint):
        """Perform warm-up requests."""
        if self.config.warm_up_requests <= 0:
            return
        
        logger.debug("warming_up_endpoint", endpoint=endpoint.name, requests=self.config.warm_up_requests)
        
        async with self._create_session() as session:
            warm_up_tasks = [
                self._make_request(session, endpoint) 
                for _ in range(self.config.warm_up_requests)
            ]
            await asyncio.gather(*warm_up_tasks, return_exceptions=True)
    
    @asynccontextmanager
    async def _create_session(self):
        """Create HTTP session with proper configuration."""
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
        connector = aiohttp.TCPConnector(limit=self.config.concurrent_requests * 2)
        
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers
        ) as session:
            yield session
    
    async def _make_request(
        self, 
        session: aiohttp.ClientSession, 
        endpoint: BenchmarkEndpoint
    ) -> BenchmarkResult:
        """Make a single HTTP request and measure performance."""
        url = f"{self.config.base_url}{endpoint.path}"
        payload = endpoint.generate_payload()
        
        # Calculate payload size
        payload_size = 0
        if payload:
            payload_size = len(json.dumps(payload).encode('utf-8'))
        
        start_time = time.time()
        error = None
        status_code = 0
        response_size = 0
        
        try:
            # Prepare request parameters
            request_kwargs = {
                'headers': endpoint.headers,
                'timeout': aiohttp.ClientTimeout(total=self.config.request_timeout)
            }
            
            if payload and endpoint.method in ['POST', 'PUT', 'PATCH']:
                request_kwargs['json'] = payload
            
            # Make request
            async with session.request(endpoint.method, url, **request_kwargs) as response:
                status_code = response.status
                response_text = await response.text()
                response_size = len(response_text.encode('utf-8'))
                
                # Validate expected status
                if status_code != endpoint.expected_status:
                    error = f"Expected status {endpoint.expected_status}, got {status_code}"
        
        except asyncio.TimeoutError:
            error = "Request timeout"
        except Exception as e:
            error = str(e)
        
        response_time_ms = (time.time() - start_time) * 1000
        
        result = BenchmarkResult(
            endpoint=endpoint.name,
            method=endpoint.method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            payload_size_bytes=payload_size,
            response_size_bytes=response_size,
            error=error
        )
        
        self.results.append(result)
        return result
    
    def _calculate_metrics(
        self, 
        endpoint_name: str, 
        test_type: str, 
        results: List[BenchmarkResult]
    ) -> BenchmarkMetrics:
        """Calculate aggregated metrics from results."""
        if not results:
            raise ValueError("No results to calculate metrics from")
        
        # Filter successful requests
        successful_results = [r for r in results if r.error is None]
        failed_results = [r for r in results if r.error is not None]
        
        # Response time statistics
        response_times = [r.response_time_ms for r in successful_results]
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            median_response_time = statistics.median(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            
            # Percentiles
            response_times_sorted = sorted(response_times)
            p95_response_time = response_times_sorted[int(len(response_times_sorted) * 0.95)] if response_times_sorted else 0
            p99_response_time = response_times_sorted[int(len(response_times_sorted) * 0.99)] if response_times_sorted else 0
        else:
            avg_response_time = median_response_time = min_response_time = max_response_time = 0
            p95_response_time = p99_response_time = 0
        
        # Time range
        start_time = min(r.timestamp for r in results)
        end_time = max(r.timestamp for r in results)
        duration_seconds = (end_time - start_time).total_seconds()
        
        # Throughput calculations
        requests_per_second = len(results) / duration_seconds if duration_seconds > 0 else 0
        errors_per_second = len(failed_results) / duration_seconds if duration_seconds > 0 else 0
        error_rate_percent = (len(failed_results) / len(results)) * 100 if results else 0
        
        # Data throughput (MB/s)
        total_bytes = sum(r.response_size_bytes for r in successful_results)
        throughput_mbps = (total_bytes / (1024 * 1024)) / duration_seconds if duration_seconds > 0 else 0
        
        return BenchmarkMetrics(
            endpoint=endpoint_name,
            test_type=test_type,
            total_requests=len(results),
            successful_requests=len(successful_results),
            failed_requests=len(failed_results),
            avg_response_time_ms=avg_response_time,
            median_response_time_ms=median_response_time,
            p95_response_time_ms=p95_response_time,
            p99_response_time_ms=p99_response_time,
            min_response_time_ms=min_response_time,
            max_response_time_ms=max_response_time,
            requests_per_second=requests_per_second,
            errors_per_second=errors_per_second,
            error_rate_percent=error_rate_percent,
            throughput_mbps=throughput_mbps,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds
        )
    
    def export_results(self, format_type: str = "json") -> str:
        """Export benchmark results in specified format."""
        if format_type == "json":
            return json.dumps([asdict(result) for result in self.results], default=str, indent=2)
        else:
            raise ValueError(f"Unsupported export format: {format_type}")


# Predefined endpoint configurations for Context Memory Gateway
def get_default_endpoints() -> List[BenchmarkEndpoint]:
    """Get default endpoints for benchmarking Context Memory Gateway."""
    
    def generate_chat_payload():
        return {
            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "Hello, how are you today?"}
            ],
            "max_tokens": 100
        }
    
    def generate_ingest_payload():
        return {
            "thread_id": f"benchmark_thread_{int(time.time())}",
            "content": "This is a benchmark test for context memory ingestion. " * 10,
            "metadata": {"source": "benchmark", "timestamp": time.time()}
        }
    
    def generate_recall_payload():
        return {
            "thread_id": "benchmark_thread",
            "query": "benchmark test",
            "limit": 10
        }
    
    return [
        # Health endpoints
        BenchmarkEndpoint("health_check", "/health", "GET"),
        BenchmarkEndpoint("detailed_health", "/health/detailed", "GET"),
        
        # Model endpoints
        BenchmarkEndpoint("list_models", "/v1/models", "GET"),
        BenchmarkEndpoint("get_model", "/v1/models/openai/gpt-4o-mini", "GET"),
        
        # LLM Gateway endpoints
        BenchmarkEndpoint(
            "chat_completion", 
            "/v1/chat/completions", 
            "POST",
            generate_chat_payload
        ),
        
        # Context Memory endpoints
        BenchmarkEndpoint(
            "context_ingest",
            "/v1/ingest",
            "POST",
            generate_ingest_payload
        ),
        BenchmarkEndpoint(
            "context_recall",
            "/v1/recall",
            "POST",
            generate_recall_payload
        ),
        
        # Cache endpoints
        BenchmarkEndpoint("cache_status", "/v1/cache/status", "GET"),
        
        # Worker endpoints
        BenchmarkEndpoint("worker_status", "/v1/workers/status", "GET"),
    ]


# Export main components
__all__ = [
    "PerformanceBenchmark",
    "BenchmarkConfig",
    "BenchmarkEndpoint", 
    "BenchmarkType",
    "BenchmarkMetrics",
    "get_default_endpoints"
]