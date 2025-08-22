#!/usr/bin/env python3
"""
Test runner script for Context Memory Gateway.
"""
import sys
import subprocess
import argparse
from pathlib import Path


def run_command(command, description):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(command)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(command, check=True, capture_output=False)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed with exit code {e.returncode}")
        return False


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description="Run tests for Context Memory Gateway")
    
    parser.add_argument(
        "--type",
        choices=["unit", "integration", "e2e", "worker", "all"],
        default="all",
        help="Type of tests to run"
    )
    
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run with coverage reporting"
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )
    
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip slow tests"
    )
    
    parser.add_argument(
        "--parallel",
        "-n",
        type=int,
        help="Run tests in parallel (requires pytest-xdist)"
    )
    
    parser.add_argument(
        "--pattern",
        "-k",
        help="Run tests matching pattern"
    )
    
    parser.add_argument(
        "--file",
        help="Run specific test file"
    )
    
    args = parser.parse_args()
    
    # Base pytest command
    cmd = ["python", "-m", "pytest"]
    
    # Add test type selection
    if args.type == "unit":
        cmd.append("tests/unit/")
    elif args.type == "integration":
        cmd.append("tests/integration/")
    elif args.type == "e2e":
        cmd.append("tests/e2e/")
    elif args.type == "worker":
        cmd.extend(["-m", "worker"])
    elif args.file:
        cmd.append(args.file)
    else:
        cmd.append("tests/")
    
    # Add coverage if requested
    if args.coverage:
        cmd.extend([
            "--cov=app",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
            "--cov-report=xml",
            "--cov-fail-under=80"
        ])
    
    # Add verbosity
    if args.verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")
    
    # Skip slow tests if requested
    if args.fast:
        cmd.extend(["-m", "not slow"])
    
    # Add parallel execution
    if args.parallel:
        cmd.extend(["-n", str(args.parallel)])
    
    # Add pattern matching
    if args.pattern:
        cmd.extend(["-k", args.pattern])
    
    # Add other useful options
    cmd.extend([
        "--tb=short",
        "--strict-markers",
        "--disable-warnings"
    ])
    
    print("Context Memory Gateway Test Runner")
    print(f"Test type: {args.type}")
    print(f"Coverage: {'enabled' if args.coverage else 'disabled'}")
    print(f"Parallel: {args.parallel if args.parallel else 'disabled'}")
    
    # Run the tests
    success = run_command(cmd, f"{args.type} tests")
    
    if success:
        print(f"\n🎉 All {args.type} tests passed!")
        
        if args.coverage:
            print("\n📊 Coverage report generated:")
            print("  - Terminal: displayed above")
            print("  - HTML: htmlcov/index.html")
            print("  - XML: coverage.xml")
    else:
        print(f"\n💥 Some {args.type} tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()

