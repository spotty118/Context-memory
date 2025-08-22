# Context Memory Gateway - Deployment Guide

This document provides comprehensive instructions for deploying the Context Memory Gateway in various environments.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Configuration](#environment-configuration)
3. [Development Deployment](#development-deployment)
4. [Staging Deployment](#staging-deployment)
5. [Production Deployment](#production-deployment)
6. [Kubernetes Deployment](#kubernetes-deployment)
7. [Monitoring and Maintenance](#monitoring-and-maintenance)
8. [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Software

- **Docker** (v20.10 or later)
- **Docker Compose** (v2.0 or later)
- **Kubernetes** (v1.24 or later) - for K8s deployment
- **kubectl** - for K8s management
- **Helm** (v3.0 or later) - optional, for advanced K8s deployment

### Required Services

- **PostgreSQL** (v15 or later) with pgvector extension
- **Redis** (v7 or later)
- **Container Registry** (e.g., GitHub Container Registry, Docker Hub)

### Minimum System Requirements

| Environment | CPU | Memory | Storage | Network |
|-------------|-----|--------|---------|---------|
| Development | 2 cores | 4 GB | 20 GB | 1 Gbps |
| Staging | 4 cores | 8 GB | 50 GB | 1 Gbps |
| Production | 8 cores | 16 GB | 100 GB | 10 Gbps |

## Environment Configuration

### 1. Copy Environment Files

```bash
# For development
cp .env.development .env

# For production
cp .env.production .env.prod
```

### 2. Configure Environment Variables

Edit the `.env` file to match your environment:

**Critical Settings to Change:**
- `SECRET_KEY` - Application secret key
- `JWT_SECRET_KEY` - JWT signing key
- `POSTGRES_PASSWORD` - Database password
- `REDIS_PASSWORD` - Redis password
- `ADMIN_PASSWORD` - Admin interface password
- `OPENROUTER_API_KEY` - External API key

## Development Deployment

### Using Docker Compose

1. **Start Services**
   ```bash
   # Start all services
   docker-compose up -d
   
   # Start with monitoring (optional)
   docker-compose --profile monitoring up -d
   ```

2. **Run Database Migrations**
   ```bash
   docker-compose --profile migration up migrate
   ```

3. **Verify Deployment**
   ```bash
   # Check service status
   docker-compose ps
   
   # Check application health
   curl http://localhost:8000/health
   ```

4. **Access Services**
   - **Application**: http://localhost:8000
   - **API Documentation**: http://localhost:8000/docs
   - **Grafana** (if enabled): http://localhost:3000
   - **Prometheus** (if enabled): http://localhost:9090

### Using Local Python Environment

1. **Install Dependencies**
   ```bash
   cd server
   pip install -r requirements.txt
   ```

2. **Start External Services**
   ```bash
   docker-compose up postgres redis -d
   ```

3. **Run Migrations**
   ```bash
   cd server
   alembic upgrade head
   ```

4. **Start Application**
   ```bash
   cd server
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## Staging Deployment

### Docker Compose Staging

1. **Configure Environment**
   ```bash
   cp .env.development .env.staging
   # Edit .env.staging with staging-specific values
   ```

2. **Deploy with Production Profile**
   ```bash
   docker-compose -f docker-compose.yml --profile production --env-file .env.staging up -d
   ```

3. **Run Health Checks**
   ```bash
   # Application health
   curl https://staging.yourdomain.com/health
   
   # Detailed status
   curl https://staging.yourdomain.com/health/detailed
   ```

## Production Deployment

### Option 1: Docker Compose Production

1. **Prepare Environment**
   ```bash
   # Copy and configure production environment
   cp .env.production .env.prod
   # Edit all security-sensitive values
   ```

2. **Deploy with Full Monitoring**
   ```bash
   docker-compose -f docker-compose.yml \
     --profile production \
     --profile monitoring \
     --env-file .env.prod \
     up -d
   ```

3. **Configure SSL/TLS**
   ```bash
   # Copy SSL certificates
   cp /path/to/certs/* ./config/ssl/
   
   # Update nginx configuration
   # Edit config/nginx.conf for SSL settings
   ```

### Option 2: Kubernetes Production

See [Kubernetes Deployment](#kubernetes-deployment) section.

## Kubernetes Deployment

### Prerequisites

1. **Kubernetes Cluster** (GKE, EKS, AKS, or self-managed)
2. **kubectl** configured for your cluster
3. **Container Registry** access

### Deployment Steps

1. **Prepare Deployment Script**
   ```bash
   chmod +x scripts/deploy.sh
   ```

2. **Create Secrets**
   ```bash
   # Create secrets from environment file
   kubectl create secret generic context-memory-gateway-secrets \
     --from-env-file=.env.production \
     --namespace=context-memory-gateway
   ```

3. **Deploy to Staging**
   ```bash
   ./scripts/deploy.sh deploy staging v1.0.0
   ```

4. **Deploy to Production**
   ```bash
   ./scripts/deploy.sh deploy production v1.0.0
   ```

5. **Monitor Deployment**
   ```bash
   # Check deployment status
   ./scripts/deploy.sh status production
   
   # Watch pods
   kubectl get pods -n context-memory-gateway -w
   ```

### Manual Kubernetes Deployment

1. **Apply Configuration**
   ```bash
   # Create namespace
   kubectl create namespace context-memory-gateway
   
   # Apply all manifests
   kubectl apply -f k8s/ -n context-memory-gateway
   ```

2. **Verify Deployment**
   ```bash
   kubectl get all -n context-memory-gateway
   ```

## Monitoring and Maintenance

### Health Monitoring

1. **Application Health Endpoints**
   - `/health` - Basic health check
   - `/health/detailed` - Detailed system status
   - `/metrics` - Prometheus metrics

2. **Grafana Dashboards**
   - Access Grafana at configured port
   - Import provided dashboards from `config/grafana/dashboards/`

3. **Log Monitoring**
   ```bash
   # Docker Compose logs
   docker-compose logs -f app
   
   # Kubernetes logs
   kubectl logs -f deployment/context-memory-gateway -n context-memory-gateway
   ```

### Performance Monitoring

1. **Run Performance Benchmarks**
   ```bash
   # Using benchmark CLI
   cd server
   python scripts/benchmark_cli.py --type throughput --requests 1000 --concurrent 10
   
   # Generate performance report
   python scripts/performance_report.py results.json -o report.html
   ```

2. **Cache Monitoring**
   ```bash
   # Check cache status
   curl http://localhost:8000/cache/status
   ```

### Backup and Recovery

1. **Database Backup**
   ```bash
   # Manual backup
   docker exec cmg-postgres pg_dump -U cmg_user context_memory_gateway > backup.sql
   
   # Automated backup (configured in environment)
   # Check BACKUP_ENABLED settings
   ```

2. **Configuration Backup**
   ```bash
   # Backup Kubernetes configurations
   kubectl get all -n context-memory-gateway -o yaml > k8s-backup.yaml
   ```

## Troubleshooting

### Common Issues

1. **Database Connection Issues**
   ```bash
   # Check database connectivity
   docker exec cmg-app pg_isready -h postgres -p 5432 -U cmg_user
   
   # Check database logs
   docker-compose logs postgres
   ```

2. **Redis Connection Issues**
   ```bash
   # Test Redis connectivity
   docker exec cmg-app redis-cli -h redis -p 6379 ping
   
   # Check Redis logs
   docker-compose logs redis
   ```

3. **Application Startup Issues**
   ```bash
   # Check application logs
   docker-compose logs app
   
   # Check environment variables
   docker exec cmg-app env | grep -E "(DATABASE|REDIS|SECRET)"
   ```

4. **Performance Issues**
   ```bash
   # Check resource usage
   docker stats
   
   # Run performance diagnostics
   curl http://localhost:8000/cache/health
   ```

### Recovery Procedures

1. **Rollback Deployment**
   ```bash
   # Kubernetes rollback
   ./scripts/deploy.sh rollback production
   
   # Docker Compose rollback
   docker-compose pull && docker-compose up -d
   ```

2. **Database Recovery**
   ```bash
   # Restore from backup
   docker exec -i cmg-postgres psql -U cmg_user context_memory_gateway < backup.sql
   ```

3. **Cache Recovery**
   ```bash
   # Clear and warm cache
   curl -X DELETE http://localhost:8000/cache/clear
   curl -X POST http://localhost:8000/cache/warm
   ```

### Support and Logging

1. **Enable Debug Logging**
   ```bash
   # Set LOG_LEVEL=DEBUG in environment
   docker-compose restart app
   ```

2. **Collect Diagnostic Information**
   ```bash
   # Health check
   curl http://localhost:8000/health/detailed
   
   # System metrics
   curl http://localhost:8000/metrics
   
   # Cache status
   curl http://localhost:8000/cache/status
   ```

## Security Considerations

1. **Change Default Passwords**
   - Update all passwords in environment files
   - Use strong, unique passwords for production

2. **Network Security**
   - Configure firewalls appropriately
   - Use TLS/SSL for all communications
   - Implement network policies in Kubernetes

3. **Access Control**
   - Configure RBAC in Kubernetes
   - Limit admin interface access
   - Regular security audits

4. **Secrets Management**
   - Use Kubernetes secrets or external secret management
   - Rotate secrets regularly
   - Never commit secrets to version control

## Performance Optimization

1. **Resource Allocation**
   - Monitor resource usage
   - Adjust CPU/memory limits
   - Configure horizontal pod autoscaling

2. **Database Optimization**
   - Regular VACUUM and ANALYZE
   - Monitor query performance
   - Optimize connection pooling

3. **Cache Optimization**
   - Monitor cache hit rates
   - Adjust TTL values
   - Implement cache warming strategies

For additional support, please refer to the API documentation at `/docs` endpoint or contact the development team.