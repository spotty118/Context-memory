#!/bin/bash

# Context Memory Gateway - Deployment Automation Script
# This script automates deployment to Kubernetes environments

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NAMESPACE="context-memory-gateway"
ENVIRONMENT="${1:-staging}"
IMAGE_TAG="${2:-latest}"
REGISTRY="ghcr.io"
IMAGE_NAME="context-memory-gateway"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if kubectl is installed
    if ! command -v kubectl &> /dev/null; then
        error "kubectl is not installed or not in PATH"
    fi
    
    # Check if helm is installed
    if ! command -v helm &> /dev/null; then
        error "helm is not installed or not in PATH"
    fi
    
    # Check if docker is installed
    if ! command -v docker &> /dev/null; then
        error "docker is not installed or not in PATH"
    fi
    
    # Check kubectl connectivity
    if ! kubectl cluster-info &> /dev/null; then
        error "Cannot connect to Kubernetes cluster"
    fi
    
    success "Prerequisites check passed"
}

# Create namespace if it doesn't exist
create_namespace() {
    log "Creating namespace '$NAMESPACE' if it doesn't exist..."
    
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        kubectl create namespace "$NAMESPACE"
        success "Namespace '$NAMESPACE' created"
    else
        log "Namespace '$NAMESPACE' already exists"
    fi
}

# Deploy secrets
deploy_secrets() {
    log "Deploying secrets for environment '$ENVIRONMENT'..."
    
    # Check if secrets file exists
    SECRETS_FILE="$PROJECT_ROOT/k8s/secrets-$ENVIRONMENT.yaml"
    if [[ -f "$SECRETS_FILE" ]]; then
        kubectl apply -f "$SECRETS_FILE" -n "$NAMESPACE"
        success "Secrets deployed"
    else
        warn "Secrets file not found: $SECRETS_FILE"
    fi
}

# Deploy ConfigMaps
deploy_configmaps() {
    log "Deploying ConfigMaps..."
    
    # Apply all ConfigMap files
    for config_file in "$PROJECT_ROOT"/k8s/configmap-*.yaml; do
        if [[ -f "$config_file" ]]; then
            kubectl apply -f "$config_file" -n "$NAMESPACE"
        fi
    done
    
    success "ConfigMaps deployed"
}

# Deploy persistent volumes
deploy_storage() {
    log "Deploying storage resources..."
    
    # Apply PVC files
    for pvc_file in "$PROJECT_ROOT"/k8s/*pvc*.yaml; do
        if [[ -f "$pvc_file" ]]; then
            kubectl apply -f "$pvc_file" -n "$NAMESPACE"
        fi
    done
    
    success "Storage resources deployed"
}

# Deploy database components
deploy_database() {
    log "Deploying database components..."
    
    # Check if PostgreSQL deployment exists
    if [[ -f "$PROJECT_ROOT/k8s/postgres.yaml" ]]; then
        kubectl apply -f "$PROJECT_ROOT/k8s/postgres.yaml" -n "$NAMESPACE"
        
        # Wait for PostgreSQL to be ready
        kubectl wait --for=condition=available --timeout=300s deployment/postgres -n "$NAMESPACE"
        success "PostgreSQL deployed and ready"
    fi
    
    # Check if Redis deployment exists
    if [[ -f "$PROJECT_ROOT/k8s/redis.yaml" ]]; then
        kubectl apply -f "$PROJECT_ROOT/k8s/redis.yaml" -n "$NAMESPACE"
        
        # Wait for Redis to be ready
        kubectl wait --for=condition=available --timeout=300s deployment/redis -n "$NAMESPACE"
        success "Redis deployed and ready"
    fi
}

# Deploy application
deploy_application() {
    log "Deploying Context Memory Gateway application..."
    
    # Update image tag in deployment
    local deployment_file="$PROJECT_ROOT/k8s/deployment.yaml"
    local temp_file=$(mktemp)
    
    # Replace image tag
    sed "s|image: .*context-memory-gateway:.*|image: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG|g" \
        "$deployment_file" > "$temp_file"
    
    # Apply deployment
    kubectl apply -f "$temp_file" -n "$NAMESPACE"
    
    # Clean up temp file
    rm "$temp_file"
    
    # Apply service
    if [[ -f "$PROJECT_ROOT/k8s/service.yaml" ]]; then
        kubectl apply -f "$PROJECT_ROOT/k8s/service.yaml" -n "$NAMESPACE"
    fi
    
    # Apply ingress
    if [[ -f "$PROJECT_ROOT/k8s/ingress-$ENVIRONMENT.yaml" ]]; then
        kubectl apply -f "$PROJECT_ROOT/k8s/ingress-$ENVIRONMENT.yaml" -n "$NAMESPACE"
    elif [[ -f "$PROJECT_ROOT/k8s/ingress.yaml" ]]; then
        kubectl apply -f "$PROJECT_ROOT/k8s/ingress.yaml" -n "$NAMESPACE"
    fi
    
    # Wait for deployment to be ready
    kubectl wait --for=condition=available --timeout=600s deployment/context-memory-gateway -n "$NAMESPACE"
    
    success "Application deployed and ready"
}

# Deploy monitoring
deploy_monitoring() {
    log "Deploying monitoring components..."
    
    if [[ -f "$PROJECT_ROOT/k8s/monitoring.yaml" ]]; then
        kubectl apply -f "$PROJECT_ROOT/k8s/monitoring.yaml" -n "$NAMESPACE"
        success "Monitoring components deployed"
    else
        warn "Monitoring configuration not found"
    fi
}

# Run database migrations
run_migrations() {
    log "Running database migrations..."
    
    # Create a migration job
    cat <<EOF | kubectl apply -f - -n "$NAMESPACE"
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration-$(date +%s)
  namespace: $NAMESPACE
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migration
        image: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG
        command: ["sh", "-c"]
        args:
          - |
            cd /app/server
            alembic upgrade head
        envFrom:
        - secretRef:
            name: context-memory-gateway-secrets
        - configMapRef:
            name: context-memory-gateway-config
      backoffLimit: 3
EOF
    
    # Wait for migration job to complete
    kubectl wait --for=condition=complete --timeout=300s job -l job-name=db-migration -n "$NAMESPACE"
    
    success "Database migrations completed"
}

# Health check
health_check() {
    log "Performing health check..."
    
    # Get service endpoint
    local service_port=$(kubectl get service context-memory-gateway -n "$NAMESPACE" -o jsonpath='{.spec.ports[0].port}')
    
    # Port forward to test health endpoint
    kubectl port-forward service/context-memory-gateway "$service_port:$service_port" -n "$NAMESPACE" &
    local port_forward_pid=$!
    
    sleep 5
    
    # Test health endpoint
    if curl -f "http://localhost:$service_port/health" &> /dev/null; then
        success "Health check passed"
    else
        error "Health check failed"
    fi
    
    # Clean up port forward
    kill $port_forward_pid 2>/dev/null || true
}

# Rollback function
rollback() {
    log "Rolling back deployment..."
    
    kubectl rollout undo deployment/context-memory-gateway -n "$NAMESPACE"
    kubectl rollout status deployment/context-memory-gateway -n "$NAMESPACE"
    
    success "Rollback completed"
}

# Cleanup function
cleanup() {
    log "Cleaning up deployment resources..."
    
    # Delete all resources in namespace
    kubectl delete all --all -n "$NAMESPACE"
    
    # Optionally delete namespace
    read -p "Delete namespace '$NAMESPACE'? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kubectl delete namespace "$NAMESPACE"
        success "Namespace deleted"
    fi
}

# Show deployment status
show_status() {
    log "Deployment status for environment '$ENVIRONMENT':"
    echo
    
    kubectl get all -n "$NAMESPACE"
    echo
    
    log "Pod logs (last 20 lines):"
    kubectl logs -l app=context-memory-gateway --tail=20 -n "$NAMESPACE"
}

# Main deployment function
deploy() {
    log "Starting deployment to '$ENVIRONMENT' environment with image tag '$IMAGE_TAG'"
    
    check_prerequisites
    create_namespace
    deploy_secrets
    deploy_configmaps
    deploy_storage
    deploy_database
    run_migrations
    deploy_application
    deploy_monitoring
    health_check
    
    success "Deployment completed successfully!"
    echo
    show_status
}

# Script usage
usage() {
    echo "Usage: $0 <command> [environment] [image_tag]"
    echo
    echo "Commands:"
    echo "  deploy      Deploy to specified environment (default: staging)"
    echo "  rollback    Rollback last deployment"
    echo "  status      Show deployment status"
    echo "  cleanup     Clean up deployment resources"
    echo "  health      Perform health check"
    echo
    echo "Environments: staging, production"
    echo "Image tag: Docker image tag to deploy (default: latest)"
    echo
    echo "Examples:"
    echo "  $0 deploy staging v1.2.3"
    echo "  $0 deploy production latest"
    echo "  $0 rollback production"
    echo "  $0 status staging"
}

# Main script logic
case "${1:-}" in
    deploy)
        deploy
        ;;
    rollback)
        rollback
        ;;
    status)
        show_status
        ;;
    cleanup)
        cleanup
        ;;
    health)
        health_check
        ;;
    *)
        usage
        exit 1
        ;;
esac