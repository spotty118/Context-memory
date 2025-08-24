# Makefile for Context Memory Gateway

.PHONY: help test test-unit test-integration test-e2e test-worker test-coverage test-fast clean install lint format

# Default target
help:
	@echo "Context Memory Gateway - Available Commands:"
	@echo ""
	@echo "Testing:"
	@echo "  test              - Run all tests"
	@echo "  test-unit         - Run unit tests only"
	@echo "  test-integration  - Run integration tests only"
	@echo "  test-e2e          - Run end-to-end tests only"
	@echo "  test-worker       - Run worker tests only"
	@echo "  test-coverage     - Run tests with coverage report"
	@echo "  test-fast         - Run tests excluding slow ones"
	@echo ""
	@echo "Development:"
	@echo "  install           - Install dependencies"
	@echo "  lint              - Run code linting"
	@echo "  format            - Format code"
	@echo "  clean             - Clean up generated files"
	@echo ""
	@echo "Database:"
	@echo "  migrate           - Run database migrations"
	@echo "  migrate-create    - Create new migration"
	@echo ""
	@echo "Workers:"
	@echo "  worker            - Start worker process"
	@echo "  scheduler         - Start scheduler"
	@echo ""

# Testing targets
test:
	python run_tests.py --type all

test-unit:
	python run_tests.py --type unit

test-integration:
	python run_tests.py --type integration

test-e2e:
	python run_tests.py --type e2e

test-worker:
	python run_tests.py --type worker

test-coverage:
	python run_tests.py --type all --coverage

test-fast:
	python run_tests.py --type all --fast

# Development targets
install:
	pip install -r requirements.txt

lint:
	@echo "Running flake8..."
	@flake8 app/ tests/ --max-line-length=100 --ignore=E203,W503 || echo "flake8 not installed, skipping..."
	@echo "Running mypy..."
	@mypy app/ --ignore-missing-imports || echo "mypy not installed, skipping..."

format:
	@echo "Running black..."
	@black app/ tests/ --line-length=100 || echo "black not installed, skipping..."
	@echo "Running isort..."
	@isort app/ tests/ --profile black || echo "isort not installed, skipping..."

clean:
	@echo "Cleaning up generated files..."
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -delete
	@rm -rf htmlcov/
	@rm -f coverage.xml
	@rm -f .coverage
	@rm -rf .pytest_cache/
	@rm -rf .mypy_cache/
	@echo "Clean complete."

# Database targets
migrate:
	alembic upgrade head

migrate-create:
	@read -p "Enter migration message: " message; \
	alembic revision --autogenerate -m "$$message"

# Worker targets
worker:
	python -m app.workers.worker --queues default high low

worker-all:
	python -m app.workers.worker --queues default high low embeddings sync cleanup analytics

scheduler:
	python -m app.workers.worker --with-scheduler --queues default

# Development server
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production server
prod:
	gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Docker targets
docker-build:
	docker build -t context-memory-gateway .

docker-run:
	docker run -p 8000:8000 context-memory-gateway

# Quick development setup
setup: install migrate
	@echo "Development setup complete!"
	@echo "Run 'make dev' to start the development server"

# CI/CD targets
ci-install:
	pip install -r ../requirements.txt -r ../requirements-dev.txt

ci-lint:
	@echo "Running code quality checks..."
	black --check --diff app/
	isort --check-only --diff app/
	ruff check app/ --format=github
	mypy app/ --ignore-missing-imports

ci-security:
	@echo "Running security scans..."
	bandit -r app/ -f json -o bandit-report.json
	safety check --json --output safety-report.json || true

ci-test: ci-install ci-lint test-coverage
	@echo "CI tests complete"

ci-performance:
	@echo "Running performance tests..."
	python scripts/benchmark_cli.py --base-url http://localhost:8000 --endpoints health --concurrent-requests 5 --total-requests 50
	python scripts/performance_report.py benchmark-results.json

ci-full: ci-install ci-lint ci-security test-coverage ci-performance
	@echo "Full CI pipeline complete"

# Health check
health:
	@curl -f http://localhost:8000/health || echo "Service not running"

# Show test coverage
coverage-report:
	@if [ -f htmlcov/index.html ]; then \
		echo "Opening coverage report..."; \
		python -m webbrowser htmlcov/index.html; \
	else \
		echo "No coverage report found. Run 'make test-coverage' first."; \
	fi

