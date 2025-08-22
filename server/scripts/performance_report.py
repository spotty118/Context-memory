"""
Performance report generator for Context Memory Gateway.
Creates comprehensive performance reports from benchmark data.
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import argparse


class PerformanceReportGenerator:
    """Generates comprehensive performance reports from benchmark data."""
    
    def __init__(self, benchmark_data: Dict[str, Any]):
        self.data = benchmark_data
        self.report_time = datetime.utcnow()
    
    def generate_html_report(self) -> str:
        """Generate HTML performance report."""
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Context Memory Gateway - Performance Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1, h2, h3 {{
            color: #2c3e50;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #3498db;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .metric-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border-left: 4px solid #3498db;
        }}
        .metric-value {{
            font-size: 2em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metric-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .endpoint-section {{
            margin-bottom: 40px;
        }}
        .endpoint-card {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            background: #fff;
        }}
        .endpoint-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}
        .endpoint-name {{
            font-size: 1.3em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .status-badge {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }}
        .status-success {{
            background: #d4edda;
            color: #155724;
        }}
        .status-warning {{
            background: #fff3cd;
            color: #856404;
        }}
        .status-error {{
            background: #f8d7da;
            color: #721c24;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .metric-item {{
            text-align: center;
        }}
        .metric-item strong {{
            display: block;
            font-size: 1.2em;
            color: #2c3e50;
        }}
        .performance-chart {{
            margin: 20px 0;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .recommendations {{
            background: #e3f2fd;
            padding: 20px;
            border-radius: 8px;
            margin-top: 30px;
        }}
        .recommendations h3 {{
            color: #1976d2;
        }}
        .recommendation {{
            margin: 10px 0;
            padding: 10px;
            background: white;
            border-radius: 4px;
            border-left: 3px solid #2196f3;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: bold;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #7f8c8d;
        }}
    </style>
</head>
<body>
    <div class="container">
        {self._generate_header()}
        {self._generate_summary()}
        {self._generate_endpoint_details()}
        {self._generate_performance_analysis()}
        {self._generate_recommendations()}
        {self._generate_footer()}
    </div>
</body>
</html>
"""
        return html
    
    def _generate_header(self) -> str:
        """Generate report header."""
        return f"""
        <div class="header">
            <h1>Performance Benchmark Report</h1>
            <h2>Context Memory Gateway</h2>
            <p><strong>Generated:</strong> {self.report_time.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Test Type:</strong> {self.data.get('benchmark_type', 'Unknown').title()}</p>
        </div>
        """
    
    def _generate_summary(self) -> str:
        """Generate summary metrics."""
        summary = self.data.get('summary', {})
        
        return f"""
        <div class="summary">
            <div class="metric-card">
                <div class="metric-value">{summary.get('total_requests', 0)}</div>
                <div class="metric-label">Total Requests</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.get('overall_success_rate', 0):.1f}%</div>
                <div class="metric-label">Success Rate</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.get('avg_response_time_ms', 0):.1f}ms</div>
                <div class="metric-label">Avg Response Time</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{summary.get('total_throughput_rps', 0):.1f}</div>
                <div class="metric-label">Total Throughput (req/s)</div>
            </div>
        </div>
        """
    
    def _generate_endpoint_details(self) -> str:
        """Generate detailed endpoint metrics."""
        metrics = self.data.get('metrics', {})
        html = '<div class="endpoint-section"><h2>Endpoint Performance Details</h2>'
        
        for endpoint_name, endpoint_data in metrics.items():
            status_class = self._get_status_class(endpoint_data)
            status_text = self._get_status_text(endpoint_data)
            
            html += f"""
            <div class="endpoint-card">
                <div class="endpoint-header">
                    <div class="endpoint-name">{endpoint_name}</div>
                    <div class="status-badge {status_class}">{status_text}</div>
                </div>
                <div class="metrics-grid">
                    <div class="metric-item">
                        <strong>{endpoint_data.get('avg_response_time_ms', 0):.2f}ms</strong>
                        <span>Average Response Time</span>
                    </div>
                    <div class="metric-item">
                        <strong>{endpoint_data.get('requests_per_second', 0):.2f}</strong>
                        <span>Requests/Second</span>
                    </div>
                    <div class="metric-item">
                        <strong>{endpoint_data.get('error_rate_percent', 0):.1f}%</strong>
                        <span>Error Rate</span>
                    </div>
                    <div class="metric-item">
                        <strong>{endpoint_data.get('p95_response_time_ms', 0):.2f}ms</strong>
                        <span>95th Percentile</span>
                    </div>
                    <div class="metric-item">
                        <strong>{endpoint_data.get('successful_requests', 0)}</strong>
                        <span>Successful Requests</span>
                    </div>
                    <div class="metric-item">
                        <strong>{endpoint_data.get('throughput_mbps', 0):.2f}MB/s</strong>
                        <span>Data Throughput</span>
                    </div>
                </div>
            </div>
            """
        
        html += '</div>'
        return html
    
    def _generate_performance_analysis(self) -> str:
        """Generate performance analysis section."""
        metrics = self.data.get('metrics', {})
        
        # Find fastest and slowest endpoints
        if metrics:
            fastest = min(metrics.items(), key=lambda x: x[1].get('avg_response_time_ms', float('inf')))
            slowest = max(metrics.items(), key=lambda x: x[1].get('avg_response_time_ms', 0))
            
            # Calculate statistics
            response_times = [m.get('avg_response_time_ms', 0) for m in metrics.values()]
            throughputs = [m.get('requests_per_second', 0) for m in metrics.values()]
            error_rates = [m.get('error_rate_percent', 0) for m in metrics.values()]
            
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            total_throughput = sum(throughputs)
            avg_error_rate = sum(error_rates) / len(error_rates) if error_rates else 0
        else:
            fastest = ("N/A", {"avg_response_time_ms": 0})
            slowest = ("N/A", {"avg_response_time_ms": 0})
            avg_response_time = 0
            total_throughput = 0
            avg_error_rate = 0
        
        return f"""
        <div class="performance-chart">
            <h2>Performance Analysis</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                    <th>Assessment</th>
                </tr>
                <tr>
                    <td>Fastest Endpoint</td>
                    <td>{fastest[0]} ({fastest[1].get('avg_response_time_ms', 0):.2f}ms)</td>
                    <td>{self._assess_response_time(fastest[1].get('avg_response_time_ms', 0))}</td>
                </tr>
                <tr>
                    <td>Slowest Endpoint</td>
                    <td>{slowest[0]} ({slowest[1].get('avg_response_time_ms', 0):.2f}ms)</td>
                    <td>{self._assess_response_time(slowest[1].get('avg_response_time_ms', 0))}</td>
                </tr>
                <tr>
                    <td>Average Response Time</td>
                    <td>{avg_response_time:.2f}ms</td>
                    <td>{self._assess_response_time(avg_response_time)}</td>
                </tr>
                <tr>
                    <td>Total Throughput</td>
                    <td>{total_throughput:.2f} req/s</td>
                    <td>{self._assess_throughput(total_throughput)}</td>
                </tr>
                <tr>
                    <td>Average Error Rate</td>
                    <td>{avg_error_rate:.1f}%</td>
                    <td>{self._assess_error_rate(avg_error_rate)}</td>
                </tr>
            </table>
        </div>
        """
    
    def _generate_recommendations(self) -> str:
        """Generate performance recommendations."""
        recommendations = self._analyze_and_recommend()
        
        html = '''
        <div class="recommendations">
            <h3>🎯 Performance Recommendations</h3>
        '''
        
        for recommendation in recommendations:
            html += f'<div class="recommendation">{recommendation}</div>'
        
        html += '</div>'
        return html
    
    def _generate_footer(self) -> str:
        """Generate report footer."""
        config = self.data.get('config', {})
        
        return f"""
        <div class="footer">
            <h3>Test Configuration</h3>
            <p><strong>Total Requests:</strong> {config.get('total_requests', 'N/A')}</p>
            <p><strong>Concurrent Requests:</strong> {config.get('concurrent_requests', 'N/A')}</p>
            <p><strong>Request Timeout:</strong> {config.get('request_timeout', 'N/A')}s</p>
            <p><strong>Warm-up Requests:</strong> {config.get('warm_up_requests', 'N/A')}</p>
            <hr>
            <p>Report generated by Context Memory Gateway Performance Benchmarking Tool</p>
        </div>
        """
    
    def _get_status_class(self, endpoint_data: Dict[str, Any]) -> str:
        """Get CSS class for endpoint status."""
        error_rate = endpoint_data.get('error_rate_percent', 0)
        response_time = endpoint_data.get('avg_response_time_ms', 0)
        
        if error_rate > 5 or response_time > 1000:
            return 'status-error'
        elif error_rate > 1 or response_time > 500:
            return 'status-warning'
        else:
            return 'status-success'
    
    def _get_status_text(self, endpoint_data: Dict[str, Any]) -> str:
        """Get status text for endpoint."""
        error_rate = endpoint_data.get('error_rate_percent', 0)
        response_time = endpoint_data.get('avg_response_time_ms', 0)
        
        if error_rate > 5 or response_time > 1000:
            return 'Needs Attention'
        elif error_rate > 1 or response_time > 500:
            return 'Acceptable'
        else:
            return 'Excellent'
    
    def _assess_response_time(self, response_time: float) -> str:
        """Assess response time performance."""
        if response_time < 100:
            return "🟢 Excellent"
        elif response_time < 300:
            return "🟡 Good"
        elif response_time < 1000:
            return "🟠 Acceptable"
        else:
            return "🔴 Needs Improvement"
    
    def _assess_throughput(self, throughput: float) -> str:
        """Assess throughput performance."""
        if throughput > 100:
            return "🟢 Excellent"
        elif throughput > 50:
            return "🟡 Good"
        elif throughput > 20:
            return "🟠 Acceptable"
        else:
            return "🔴 Needs Improvement"
    
    def _assess_error_rate(self, error_rate: float) -> str:
        """Assess error rate."""
        if error_rate < 0.1:
            return "🟢 Excellent"
        elif error_rate < 1:
            return "🟡 Good"
        elif error_rate < 5:
            return "🟠 Acceptable"
        else:
            return "🔴 Needs Improvement"
    
    def _analyze_and_recommend(self) -> List[str]:
        """Analyze performance and generate recommendations."""
        recommendations = []
        metrics = self.data.get('metrics', {})
        summary = self.data.get('summary', {})
        
        # Check overall error rate
        overall_error_rate = summary.get('overall_success_rate', 100)
        if overall_error_rate < 95:
            recommendations.append(
                f"⚠️ Overall success rate is {overall_error_rate:.1f}%. "
                "Investigate failing endpoints and add error handling."
            )
        
        # Check response times
        avg_response_time = summary.get('avg_response_time_ms', 0)
        if avg_response_time > 500:
            recommendations.append(
                f"🐌 Average response time is {avg_response_time:.1f}ms. "
                "Consider optimizing database queries, adding caching, or scaling infrastructure."
            )
        
        # Check throughput
        total_throughput = summary.get('total_throughput_rps', 0)
        if total_throughput < 50:
            recommendations.append(
                f"📈 Total throughput is {total_throughput:.1f} req/s. "
                "Consider increasing server resources or optimizing application performance."
            )
        
        # Check individual endpoints
        slow_endpoints = []
        error_prone_endpoints = []
        
        for endpoint_name, endpoint_data in metrics.items():
            if endpoint_data.get('avg_response_time_ms', 0) > 1000:
                slow_endpoints.append(endpoint_name)
            
            if endpoint_data.get('error_rate_percent', 0) > 5:
                error_prone_endpoints.append(endpoint_name)
        
        if slow_endpoints:
            recommendations.append(
                f"⏱️ Slow endpoints detected: {', '.join(slow_endpoints)}. "
                "Focus optimization efforts on these endpoints."
            )
        
        if error_prone_endpoints:
            recommendations.append(
                f"❌ High error rate endpoints: {', '.join(error_prone_endpoints)}. "
                "Investigate and fix issues in these endpoints."
            )
        
        # Cache recommendations
        if any('cache' in name.lower() for name in metrics.keys()):
            cache_metrics = [m for name, m in metrics.items() if 'cache' in name.lower()]
            if cache_metrics and all(m.get('avg_response_time_ms', 0) < 50 for m in cache_metrics):
                recommendations.append(
                    "✅ Cache performance is excellent. Consider expanding caching to other endpoints."
                )
        
        # General recommendations
        if not recommendations:
            recommendations.append(
                "✅ Overall performance looks good! Continue monitoring and consider load testing "
                "with higher concurrency to identify bottlenecks."
            )
        
        recommendations.append(
            "📊 Set up continuous performance monitoring to track performance trends over time."
        )
        
        recommendations.append(
            "🔄 Run benchmarks regularly, especially before and after deployments."
        )
        
        return recommendations


def main():
    """Main entry point for report generator."""
    parser = argparse.ArgumentParser(description="Generate performance report from benchmark data")
    parser.add_argument("input_file", help="JSON file containing benchmark data")
    parser.add_argument("-o", "--output", help="Output HTML file (default: performance_report.html)")
    
    args = parser.parse_args()
    
    try:
        # Load benchmark data
        with open(args.input_file, 'r') as f:
            data = json.load(f)
        
        # Handle multiple runs data
        if isinstance(data, list) and len(data) > 0:
            # Use the most recent run
            data = data[-1]
        
        # Generate report
        generator = PerformanceReportGenerator(data)
        html_report = generator.generate_html_report()
        
        # Save report
        output_file = args.output or "performance_report.html"
        with open(output_file, 'w') as f:
            f.write(html_report)
        
        print(f"Performance report generated: {output_file}")
        
    except FileNotFoundError:
        print(f"Error: File '{args.input_file}' not found")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in '{args.input_file}'")
        sys.exit(1)
    except Exception as e:
        print(f"Error generating report: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()