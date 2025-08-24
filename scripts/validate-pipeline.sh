#!/bin/bash

# Pipeline Configuration Validator
# Validates CI/CD pipeline setup and configuration

set -e

echo "🔍 Context Memory Gateway - CI/CD Pipeline Validator"
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track validation results
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

check_result() {
    local test_name="$1"
    local result="$2"
    local message="$3"
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    if [ "$result" -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} $test_name"
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    else
        echo -e "  ${RED}✗${NC} $test_name: $message"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
    fi
}

# Check 1: Repository Structure
echo -e "\n📁 Checking Repository Structure..."

# Check for required directories
[ -d ".github/workflows" ] && github_workflows=0 || github_workflows=1
check_result "GitHub Workflows directory exists" $github_workflows "Missing .github/workflows/"

[ -d "server/app" ] && server_app=0 || server_app=1
check_result "Server application directory exists" $server_app "Missing server/app/"

[ -d "server/tests" ] && server_tests=0 || server_tests=1
check_result "Tests directory exists" $server_tests "Missing server/tests/"

[ -d "docs" ] && docs_dir=0 || docs_dir=1
check_result "Documentation directory exists" $docs_dir "Missing docs/"

# Check 2: Required Configuration Files
echo -e "\n⚙️  Checking Configuration Files..."

[ -f "pyproject.toml" ] && pyproject=0 || pyproject=1
check_result "pyproject.toml exists" $pyproject "Missing pyproject.toml"

[ -f "requirements.txt" ] && requirements=0 || requirements=1
check_result "requirements.txt exists" $requirements "Missing requirements.txt"

[ -f "requirements-dev.txt" ] && requirements_dev=0 || requirements_dev=1
check_result "requirements-dev.txt exists" $requirements_dev "Missing requirements-dev.txt"

[ -f ".env.example" ] && env_example=0 || env_example=1
check_result ".env.example exists" $env_example "Missing .env.example"

[ -f "docker-compose.yml" ] && docker_compose=0 || docker_compose=1
check_result "docker-compose.yml exists" $docker_compose "Missing docker-compose.yml"

[ -f "Dockerfile" ] && dockerfile=0 || dockerfile=1
check_result "Dockerfile exists" $dockerfile "Missing Dockerfile"

# Check 3: CI/CD Workflow Files
echo -e "\n🚀 Checking CI/CD Workflow Files..."

[ -f ".github/workflows/ci-pipeline.yml" ] && ci_pipeline=0 || ci_pipeline=1
check_result "CI Pipeline workflow exists" $ci_pipeline "Missing .github/workflows/ci-pipeline.yml"

[ -f ".github/workflows/security-scan.yml" ] && security_scan=0 || security_scan=1
check_result "Security scanning workflow exists" $security_scan "Missing .github/workflows/security-scan.yml"

[ -f ".github/workflows/performance-monitoring.yml" ] && perf_monitor=0 || perf_monitor=1
check_result "Performance monitoring workflow exists" $perf_monitor "Missing .github/workflows/performance-monitoring.yml"

# Check 4: GitHub Configuration Files
echo -e "\n🔧 Checking GitHub Configuration..."

[ -f ".github/CODEOWNERS" ] && codeowners=0 || codeowners=1
check_result "CODEOWNERS file exists" $codeowners "Missing .github/CODEOWNERS"

[ -f ".github/pull_request_template.md" ] && pr_template=0 || pr_template=1
check_result "PR template exists" $pr_template "Missing .github/pull_request_template.md"

[ -d ".github/ISSUE_TEMPLATE" ] && issue_templates=0 || issue_templates=1
check_result "Issue templates directory exists" $issue_templates "Missing .github/ISSUE_TEMPLATE/"

# Check 5: Code Quality Configuration
echo -e "\n📋 Checking Code Quality Configuration..."

[ -f ".pre-commit-config.yaml" ] && precommit=0 || precommit=1
check_result "Pre-commit configuration exists" $precommit "Missing .pre-commit-config.yaml"

[ -f ".secrets.baseline" ] && secrets_baseline=0 || secrets_baseline=1
check_result "Secrets baseline exists" $secrets_baseline "Missing .secrets.baseline"

# Check if pyproject.toml has required sections
if [ -f "pyproject.toml" ]; then
    grep -q "\[tool.black\]" pyproject.toml && black_config=0 || black_config=1
    check_result "Black configuration in pyproject.toml" $black_config "Missing [tool.black] section"
    
    grep -q "\[tool.ruff\]" pyproject.toml && ruff_config=0 || ruff_config=1
    check_result "Ruff configuration in pyproject.toml" $ruff_config "Missing [tool.ruff] section"
    
    grep -q "\[tool.pytest" pyproject.toml && pytest_config=0 || pytest_config=1
    check_result "Pytest configuration in pyproject.toml" $pytest_config "Missing [tool.pytest] section"
    
    grep -q "\[tool.bandit\]" pyproject.toml && bandit_config=0 || bandit_config=1
    check_result "Bandit configuration in pyproject.toml" $bandit_config "Missing [tool.bandit] section"
fi

# Check 6: Test Structure
echo -e "\n🧪 Checking Test Structure..."

[ -d "server/tests/unit" ] && unit_tests=0 || unit_tests=1
check_result "Unit tests directory exists" $unit_tests "Missing server/tests/unit/"

[ -d "server/tests/integration" ] && integration_tests=0 || integration_tests=1
check_result "Integration tests directory exists" $integration_tests "Missing server/tests/integration/"

[ -d "server/tests/load" ] && load_tests=0 || load_tests=1
check_result "Load tests directory exists" $load_tests "Missing server/tests/load/"

[ -f "server/tests/conftest.py" ] && conftest=0 || conftest=1
check_result "Pytest conftest.py exists" $conftest "Missing server/tests/conftest.py"

# Check 7: Scripts and Tools
echo -e "\n🛠️  Checking Scripts and Tools..."

[ -f "server/scripts/performance_report.py" ] && perf_report=0 || perf_report=1
check_result "Performance report script exists" $perf_report "Missing server/scripts/performance_report.py"

[ -f "server/Makefile" ] && makefile=0 || makefile=1
check_result "Makefile exists" $makefile "Missing server/Makefile"

# Check 8: Docker Configuration
echo -e "\n🐳 Checking Docker Configuration..."

if [ -f "Dockerfile" ]; then
    grep -q "FROM python:" Dockerfile && dockerfile_python=0 || dockerfile_python=1
    check_result "Dockerfile uses Python base image" $dockerfile_python "Dockerfile doesn't specify Python base image"
    
    grep -q "COPY requirements" Dockerfile && dockerfile_requirements=0 || dockerfile_requirements=1
    check_result "Dockerfile copies requirements" $dockerfile_requirements "Dockerfile doesn't copy requirements files"
fi

if [ -f "docker-compose.yml" ]; then
    grep -q "postgres" docker-compose.yml && compose_postgres=0 || compose_postgres=1
    check_result "Docker Compose includes PostgreSQL" $compose_postgres "Docker Compose missing PostgreSQL service"
    
    grep -q "redis" docker-compose.yml && compose_redis=0 || compose_redis=1
    check_result "Docker Compose includes Redis" $compose_redis "Docker Compose missing Redis service"
fi

# Check 9: Environment Configuration Validation
echo -e "\n🔐 Checking Environment Configuration..."

if [ -f ".env.example" ]; then
    grep -q "DATABASE_URL" .env.example && env_database=0 || env_database=1
    check_result "Environment template has DATABASE_URL" $env_database "Missing DATABASE_URL in .env.example"
    
    grep -q "REDIS_URL" .env.example && env_redis=0 || env_redis=1
    check_result "Environment template has REDIS_URL" $env_redis "Missing REDIS_URL in .env.example"
    
    grep -q "SECRET_KEY" .env.example && env_secret=0 || env_secret=1
    check_result "Environment template has SECRET_KEY" $env_secret "Missing SECRET_KEY in .env.example"
    
    grep -q "OPENROUTER_API_KEY" .env.example && env_openrouter=0 || env_openrouter=1
    check_result "Environment template has OPENROUTER_API_KEY" $env_openrouter "Missing OPENROUTER_API_KEY in .env.example"
fi

# Check 10: Documentation
echo -e "\n📚 Checking Documentation..."

[ -f "README.md" ] && readme=0 || readme=1
check_result "README.md exists" $readme "Missing README.md"

[ -f "docs/architecture/cicd-pipeline-design.md" ] && cicd_docs=0 || cicd_docs=1
check_result "CI/CD pipeline documentation exists" $cicd_docs "Missing CI/CD pipeline documentation"

# Check 11: Python Dependencies Validation
echo -e "\n🐍 Checking Python Dependencies..."

if command -v python3 &> /dev/null; then
    if [ -f "requirements.txt" ]; then
        python3 -m pip check &> /dev/null && pip_check=0 || pip_check=1
        check_result "Python dependencies are consistent" $pip_check "Dependency conflicts detected"
    fi
fi

# Final Summary
echo -e "\n📊 Validation Summary"
echo "==================="
echo -e "Total Checks: $TOTAL_CHECKS"
echo -e "${GREEN}Passed: $PASSED_CHECKS${NC}"
echo -e "${RED}Failed: $FAILED_CHECKS${NC}"

if [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "\n${GREEN}🎉 All checks passed! Your CI/CD pipeline is properly configured.${NC}"
    exit 0
else
    echo -e "\n${YELLOW}⚠️  Some checks failed. Please address the issues above before proceeding.${NC}"
    
    # Provide guidance for common issues
    echo -e "\n💡 Common Solutions:"
    echo "- Missing files: Create them based on the repository template"
    echo "- Configuration issues: Check the CI/CD pipeline documentation"
    echo "- Dependency conflicts: Update requirements.txt and run pip install"
    echo "- Missing directories: Create them with proper structure"
    
    exit 1
fi