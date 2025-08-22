"""
CLI tool for running performance benchmarks on Context Memory Gateway.
Provides easy-to-use command line interface for testing API performance.
"""
import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any
import structlog

from app.core.benchmarks import (
    PerformanceBenchmark, BenchmarkConfig, BenchmarkEndpoint, 
    BenchmarkType, get_default_endpoints
)


logger = structlog.get_logger(__name__)


class BenchmarkCLI:
    """Command line interface for performance benchmarks."""
    
    def __init__(self):
        self.parser = self._create_parser()
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Create command line argument parser."""
        parser = argparse.ArgumentParser(
            description="Performance benchmarking tool for Context Memory Gateway",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Run basic latency test
  python benchmark_cli.py --type latency --requests 100

  # Run throughput test with high concurrency
  python benchmark_cli.py --type throughput --concurrent 50 --requests 500

  # Run load test with custom API key
  python benchmark_cli.py --type load_test --api-key your_api_key_here

  # Run stress test and save results
  python benchmark_cli.py --type stress_test --output results.json

  # Run endurance test for 10 minutes
  python benchmark_cli.py --type endurance --duration 600

  # Test specific endpoints only
  python benchmark_cli.py --endpoints health_check,list_models --requests 50

  # Run with custom base URL
  python benchmark_cli.py --base-url http://your-server.com --type latency
            """
        )
        
        # Basic configuration
        parser.add_argument(
            "--base-url",
            default="http://localhost:8000",
            help="Base URL of the API server (default: http://localhost:8000)"
        )
        
        parser.add_argument(
            "--api-key",
            help="API key for authentication (optional)"
        )
        
        # Test configuration
        parser.add_argument(
            "--type",
            choices=["latency", "throughput", "load_test", "stress_test", "endurance"],
            default="latency",
            help="Type of benchmark to run (default: latency)"
        )
        
        parser.add_argument(
            "--requests",
            type=int,
            default=100,
            help="Total number of requests to make (default: 100)"
        )
        
        parser.add_argument(
            "--concurrent",
            type=int,
            default=10,
            help="Number of concurrent requests (default: 10)"
        )
        
        parser.add_argument(
            "--duration",
            type=int,
            help="Test duration in seconds (for endurance tests)"
        )
        
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Request timeout in seconds (default: 30)"
        )
        
        parser.add_argument(
            "--warm-up",
            type=int,
            default=10,
            help="Number of warm-up requests (default: 10)"
        )
        
        parser.add_argument(
            "--rate-limit",
            type=int,
            help="Rate limit in requests per second (for endurance tests)"
        )
        
        # Endpoint selection
        parser.add_argument(
            "--endpoints",
            help="Comma-separated list of endpoint names to test (default: all)"
        )
        
        parser.add_argument(
            "--exclude",
            help="Comma-separated list of endpoint names to exclude"
        )
        
        # Output options
        parser.add_argument(
            "--output",
            help="Output file path for results (JSON format)"
        )
        
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Enable detailed logging"
        )
        
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress progress output"
        )
        
        parser.add_argument(
            "--summary-only",
            action="store_true",
            help="Show only summary metrics"
        )
        
        # Advanced options
        parser.add_argument(
            "--payload-size",
            type=int,
            default=1,
            help="Payload size in KB for POST requests (default: 1)"
        )
        
        parser.add_argument(
            "--repeat",
            type=int,
            default=1,
            help="Number of times to repeat the benchmark (default: 1)"
        )
        
        parser.add_argument(
            "--delay",
            type=int,
            default=0,
            help="Delay between repeated runs in seconds (default: 0)"
        )
        
        return parser
    
    async def run(self, args: List[str] = None) -> int:
        """Run the benchmark CLI."""
        try:
            parsed_args = self.parser.parse_args(args)
            
            # Configure logging
            if parsed_args.verbose:
                structlog.configure(
                    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
                )
            elif parsed_args.quiet:
                structlog.configure(
                    wrapper_class=structlog.make_filtering_bound_logger(40),  # ERROR level
                )
            
            # Create benchmark configuration
            config = BenchmarkConfig(
                base_url=parsed_args.base_url,
                api_key=parsed_args.api_key,
                concurrent_requests=parsed_args.concurrent,
                total_requests=parsed_args.requests,
                request_timeout=parsed_args.timeout,
                warm_up_requests=parsed_args.warm_up,
                test_duration_seconds=parsed_args.duration,
                rate_limit_rps=parsed_args.rate_limit,
                payload_size_kb=parsed_args.payload_size,
                enable_detailed_logging=parsed_args.verbose
            )
            
            # Get endpoints to test
            endpoints = self._get_endpoints(parsed_args)
            if not endpoints:
                print("No endpoints to test!")
                return 1
            
            # Convert benchmark type
            benchmark_type = BenchmarkType(parsed_args.type)
            
            # Run benchmarks
            all_results = []
            
            for run_number in range(parsed_args.repeat):
                if parsed_args.repeat > 1:
                    print(f"\n=== Run {run_number + 1}/{parsed_args.repeat} ===")
                
                # Create and run benchmark
                benchmark = PerformanceBenchmark(config)
                metrics = await benchmark.run_benchmark(endpoints, benchmark_type)
                
                # Store results
                run_results = {
                    "run_number": run_number + 1,
                    "config": config.__dict__,
                    "metrics": {name: metric.to_dict() for name, metric in metrics.items()},
                    "raw_results": [result.__dict__ for result in benchmark.results]
                }
                all_results.append(run_results)
                
                # Display results
                if not parsed_args.quiet:
                    self._display_results(metrics, parsed_args.summary_only)
                
                # Delay between runs
                if run_number < parsed_args.repeat - 1 and parsed_args.delay > 0:
                    print(f"Waiting {parsed_args.delay} seconds before next run...")
                    await asyncio.sleep(parsed_args.delay)
            
            # Save results if requested
            if parsed_args.output:
                self._save_results(all_results, parsed_args.output)
                print(f"\nResults saved to {parsed_args.output}")
            
            # Display summary for multiple runs
            if parsed_args.repeat > 1 and not parsed_args.quiet:
                self._display_multi_run_summary(all_results)
            
            return 0
            
        except KeyboardInterrupt:
            print("\nBenchmark interrupted by user")
            return 130
        except Exception as e:
            print(f"Error: {e}")
            if parsed_args.verbose if 'parsed_args' in locals() else False:
                import traceback
                traceback.print_exc()
            return 1
    
    def _get_endpoints(self, args) -> List[BenchmarkEndpoint]:
        """Get list of endpoints to test based on arguments."""
        all_endpoints = get_default_endpoints()
        
        # Filter by included endpoints
        if args.endpoints:
            included_names = [name.strip() for name in args.endpoints.split(",")]
            all_endpoints = [ep for ep in all_endpoints if ep.name in included_names]
        
        # Filter out excluded endpoints
        if args.exclude:
            excluded_names = [name.strip() for name in args.exclude.split(",")]
            all_endpoints = [ep for ep in all_endpoints if ep.name not in excluded_names]
        
        return all_endpoints
    
    def _display_results(self, metrics: Dict[str, Any], summary_only: bool = False):
        """Display benchmark results."""
        print("\n" + "="*80)
        print("BENCHMARK RESULTS")
        print("="*80)
        
        for endpoint_name, metric in metrics.items():
            print(f"\nEndpoint: {endpoint_name}")
            print("-" * 40)
            
            if summary_only:
                print(f"  Requests: {metric.total_requests} ({metric.successful_requests} successful)")
                print(f"  Avg Response Time: {metric.avg_response_time_ms:.2f}ms")
                print(f"  Throughput: {metric.requests_per_second:.2f} req/s")
                print(f"  Error Rate: {metric.error_rate_percent:.1f}%")
            else:
                print(f"  Total Requests: {metric.total_requests}")
                print(f"  Successful: {metric.successful_requests}")
                print(f"  Failed: {metric.failed_requests}")
                print(f"  Error Rate: {metric.error_rate_percent:.1f}%")
                print()
                print(f"  Response Time (ms):")
                print(f"    Average: {metric.avg_response_time_ms:.2f}")
                print(f"    Median: {metric.median_response_time_ms:.2f}")
                print(f"    95th percentile: {metric.p95_response_time_ms:.2f}")
                print(f"    99th percentile: {metric.p99_response_time_ms:.2f}")
                print(f"    Min: {metric.min_response_time_ms:.2f}")
                print(f"    Max: {metric.max_response_time_ms:.2f}")
                print()
                print(f"  Throughput:")
                print(f"    Requests/sec: {metric.requests_per_second:.2f}")
                print(f"    Data: {metric.throughput_mbps:.2f} MB/s")
                print()
                print(f"  Duration: {metric.duration_seconds:.2f} seconds")
    
    def _display_multi_run_summary(self, all_results: List[Dict[str, Any]]):
        """Display summary for multiple benchmark runs."""
        print("\n" + "="*80)
        print("MULTI-RUN SUMMARY")
        print("="*80)
        
        # Aggregate metrics across runs
        endpoint_metrics = {}
        
        for result in all_results:
            for endpoint_name, metric_dict in result["metrics"].items():
                if endpoint_name not in endpoint_metrics:
                    endpoint_metrics[endpoint_name] = []
                endpoint_metrics[endpoint_name].append(metric_dict)
        
        for endpoint_name, metrics_list in endpoint_metrics.items():
            print(f"\nEndpoint: {endpoint_name}")
            print("-" * 40)
            
            # Calculate aggregated statistics
            avg_response_times = [m["avg_response_time_ms"] for m in metrics_list]
            throughputs = [m["requests_per_second"] for m in metrics_list]
            error_rates = [m["error_rate_percent"] for m in metrics_list]
            
            print(f"  Average Response Time:")
            print(f"    Mean: {sum(avg_response_times) / len(avg_response_times):.2f}ms")
            print(f"    Min: {min(avg_response_times):.2f}ms")
            print(f"    Max: {max(avg_response_times):.2f}ms")
            
            print(f"  Throughput:")
            print(f"    Mean: {sum(throughputs) / len(throughputs):.2f} req/s")
            print(f"    Min: {min(throughputs):.2f} req/s")
            print(f"    Max: {max(throughputs):.2f} req/s")
            
            print(f"  Error Rate:")
            print(f"    Mean: {sum(error_rates) / len(error_rates):.1f}%")
            print(f"    Min: {min(error_rates):.1f}%")
            print(f"    Max: {max(error_rates):.1f}%")
    
    def _save_results(self, results: List[Dict[str, Any]], output_path: str):
        """Save benchmark results to file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)


def main():
    """Main entry point for CLI."""
    cli = BenchmarkCLI()
    return asyncio.run(cli.run())


if __name__ == "__main__":
    sys.exit(main())