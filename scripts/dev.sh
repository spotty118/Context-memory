#!/bin/bash

# Context Memory Gateway - Development Script
# Usage: ./scripts/dev.sh [command]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.local.yml"
PROJECT_NAME="context-memory-gateway"

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

# Check if .env file exists
check_env() {
    if [ ! -f .env ]; then
        log_warning ".env file not found. Creating from template..."
        cp .env.example .env
        log_info "Please edit .env file with your configuration before continuing."
        exit 1
    fi
}

# Load environment variables
load_env() {
    if [ -f .env ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
}

# Start services
start() {
    log_info "Starting Context Memory Gateway development environment..."
    check_docker
    check_env
    load_env
    
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME up -d
    
    log_success "Services started successfully!"
    log_info "Application: http://localhost:8000"
    log_info "Admin Interface: http://localhost:8000/admin"
    log_info "API Documentation: http://localhost:8000/docs"
    log_info "PostgreSQL: localhost:5432"
    log_info "Redis: localhost:6379"
    log_info "Qdrant: http://localhost:6333"
}

# Stop services
stop() {
    log_info "Stopping Context Memory Gateway services..."
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME down
    log_success "Services stopped successfully!"
}

# Restart services
restart() {
    log_info "Restarting Context Memory Gateway services..."
    stop
    start
}

# View logs
logs() {
    local service=${1:-app}
    log_info "Showing logs for service: $service"
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME logs -f $service
}

# Check service status
status() {
    log_info "Service status:"
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME ps
}

# Run database migrations
migrate() {
    log_info "Running database migrations..."
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME exec app alembic upgrade head
    log_success "Database migrations completed!"
}

# Create new migration
create_migration() {
    local message=${1:-"Auto migration"}
    log_info "Creating new migration: $message"
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME exec app alembic revision --autogenerate -m "$message"
    log_success "Migration created successfully!"
}

# Reset database
reset_db() {
    log_warning "This will destroy all data in the database. Are you sure? (y/N)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        log_info "Resetting database..."
        docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME down -v
        docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME up -d postgres redis
        sleep 5
        migrate
        log_success "Database reset completed!"
    else
        log_info "Database reset cancelled."
    fi
}

# Run tests
test() {
    log_info "Running tests..."
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME exec app python -m pytest tests/ -v
}

# Open shell in container
shell() {
    local service=${1:-app}
    log_info "Opening shell in $service container..."
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME exec $service /bin/bash
}

# Build images
build() {
    log_info "Building Docker images..."
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME build --no-cache
    log_success "Images built successfully!"
}

# Clean up
clean() {
    log_info "Cleaning up Docker resources..."
    docker-compose -f $COMPOSE_FILE -p $PROJECT_NAME down -v --remove-orphans
    docker system prune -f
    log_success "Cleanup completed!"
}

# Setup development environment
setup() {
    log_info "Setting up development environment..."
    
    # Check prerequisites
    check_docker
    
    # Create .env file if it doesn't exist
    if [ ! -f .env ]; then
        cp .env.example .env
        log_info "Created .env file from template. Please edit it with your configuration."
    fi
    
    # Build and start services
    build
    start
    
    # Wait for services to be ready
    log_info "Waiting for services to be ready..."
    sleep 10
    
    # Run migrations
    migrate
    
    log_success "Development environment setup completed!"
    log_info "You can now access the application at http://localhost:8000"
}

# Show help
help() {
    echo "Context Memory Gateway - Development Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  setup           Setup development environment from scratch"
    echo "  start           Start all services"
    echo "  stop            Stop all services"
    echo "  restart         Restart all services"
    echo "  status          Show service status"
    echo "  logs [service]  Show logs (default: app)"
    echo "  migrate         Run database migrations"
    echo "  create-migration [message]  Create new migration"
    echo "  reset-db        Reset database (destroys all data)"
    echo "  test            Run tests"
    echo "  shell [service] Open shell in container (default: app)"
    echo "  build           Build Docker images"
    echo "  clean           Clean up Docker resources"
    echo "  help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup                    # Initial setup"
    echo "  $0 start                    # Start services"
    echo "  $0 logs app                 # View app logs"
    echo "  $0 shell postgres           # Open PostgreSQL shell"
    echo "  $0 create-migration \"Add new table\""
}

# Main command dispatcher
case "${1:-help}" in
    setup)
        setup
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs $2
        ;;
    migrate)
        migrate
        ;;
    create-migration)
        create_migration "$2"
        ;;
    reset-db)
        reset_db
        ;;
    test)
        test
        ;;
    shell)
        shell $2
        ;;
    build)
        build
        ;;
    clean)
        clean
        ;;
    help|--help|-h)
        help
        ;;
    *)
        log_error "Unknown command: $1"
        help
        exit 1
        ;;
esac

