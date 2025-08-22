# Deployment Guide

Complete guide for deploying the Context Memory + LLM Gateway service to production.

## Deployment Options

1. **DigitalOcean App Platform** (Recommended)
2. **Docker Containers**
3. **Kubernetes**
4. **Traditional VPS**

---

## DigitalOcean App Platform (Recommended)

The service is designed for optimal deployment on DigitalOcean App Platform with managed services.

### Prerequisites

- DigitalOcean account
- `doctl` CLI tool installed and configured
- Terraform installed (for infrastructure)
- OpenRouter API key

### Infrastructure Setup

1. **Clone and Configure**
   ```bash
   git clone <repository-url>
   cd context-memory-gateway/infra/terraform
   ```

2. **Create Terraform Variables**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

   Edit `terraform.tfvars`:
   ```hcl
   # Project Configuration
   project_name = "context-memory-gateway"
   environment = "production"
   region = "nyc3"
   
   # Database Configuration
   postgres_size = "db-s-2vcpu-4gb"
   postgres_version = "15"
   
   # Redis Configuration
   redis_size = "db-s-1vcpu-1gb"
   
   # App Platform Configuration
   app_instance_count = 2
   app_instance_size = "professional-xs"
   
   # Worker Configuration
   worker_instance_count = 1
   worker_instance_size = "basic-xxs"
   
   # Domain Configuration (optional)
   domain_name = "your-domain.com"
   ```

3. **Deploy Infrastructure**
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

   This creates:
   - VPC with public/private subnets
   - Managed PostgreSQL database with pgvector
   - Managed Redis cluster
   - DigitalOcean Spaces for storage
   - Container Registry
   - App Platform application

4. **Configure Secrets**
   
   The Terraform output will provide commands to set up secrets:
   ```bash
   # Set OpenRouter API key
   doctl apps create-deployment <app-id> --spec .do/app.yaml
   
   # Update environment variables
   doctl apps update <app-id> --spec .do/app.yaml
   ```

### Application Deployment

1. **Build and Push Container**
   ```bash
   # Build container
   docker build -t registry.digitalocean.com/<registry-name>/context-memory-gateway:latest .
   
   # Push to registry
   docker push registry.digitalocean.com/<registry-name>/context-memory-gateway:latest
   ```

2. **Deploy Application**
   ```bash
   # Deploy via App Platform
   doctl apps create --spec .do/app.yaml
   ```

3. **Run Database Migrations**
   ```bash
   # Connect to app console
   doctl apps exec <app-id> --component app -- alembic upgrade head
   ```

### Monitoring Setup

1. **Configure Alerts**
   ```bash
   # Create uptime check
   doctl monitoring alert policy create \
     --type uptime \
     --description "Context Memory Gateway Uptime" \
     --compare GreaterThan \
     --value 1 \
     --window 5m \
     --entities <app-id>
   ```

2. **Set up Log Forwarding**
   Configure log forwarding to your preferred logging service in the DigitalOcean control panel.

---

## Docker Deployment

For deployment on other platforms using Docker.

### Prerequisites

- Docker and Docker Compose
- PostgreSQL database with pgvector
- Redis instance
- Reverse proxy (nginx/traefik)

### Production Docker Setup

1. **Create Production Environment**
   ```bash
   cp .env.example .env.production
   ```

   Configure production values:
   ```env
   ENVIRONMENT=production
   DEBUG=false
   
   # Database
   DATABASE_URL=postgresql://user:pass@db-host:5432/cmg_prod
   REDIS_URL=redis://redis-host:6379/0
   
   # Security
   SECRET_KEY=your-super-secret-key-here
   
   # OpenRouter
   OPENROUTER_API_KEY=your-openrouter-key
   
   # Rate Limiting
   RATE_LIMIT_REQUESTS=1000
   RATE_LIMIT_WINDOW=60
   ```

2. **Production Docker Compose**
   ```yaml
   # docker-compose.prod.yml
   version: '3.8'
   
   services:
     app:
       image: context-memory-gateway:latest
       restart: unless-stopped
       env_file: .env.production
       ports:
         - "8000:8000"
       depends_on:
         - postgres
         - redis
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
         interval: 30s
         timeout: 10s
         retries: 3
   
     worker:
       image: context-memory-gateway:latest
       restart: unless-stopped
       env_file: .env.production
       command: python -m app.workers.worker --queues default high low embeddings sync cleanup analytics
       depends_on:
         - postgres
         - redis
   
     scheduler:
       image: context-memory-gateway:latest
       restart: unless-stopped
       env_file: .env.production
       command: python -m app.workers.worker --with-scheduler --queues default
       depends_on:
         - postgres
         - redis
   
     postgres:
       image: pgvector/pgvector:pg15
       restart: unless-stopped
       environment:
         POSTGRES_DB: cmg_prod
         POSTGRES_USER: cmg_user
         POSTGRES_PASSWORD: secure_password
       volumes:
         - postgres_data:/var/lib/postgresql/data
         - ./infra/sql/init.sql:/docker-entrypoint-initdb.d/init.sql
       ports:
         - "5432:5432"
   
     redis:
       image: redis:7-alpine
       restart: unless-stopped
       command: redis-server --appendonly yes
       volumes:
         - redis_data:/data
       ports:
         - "6379:6379"
   
     nginx:
       image: nginx:alpine
       restart: unless-stopped
       ports:
         - "80:80"
         - "443:443"
       volumes:
         - ./infra/nginx/nginx.conf:/etc/nginx/nginx.conf
         - ./infra/nginx/conf.d:/etc/nginx/conf.d
         - ./ssl:/etc/nginx/ssl
       depends_on:
         - app
   
   volumes:
     postgres_data:
     redis_data:
   ```

3. **Deploy**
   ```bash
   # Build production image
   docker build -t context-memory-gateway:latest .
   
   # Start services
   docker-compose -f docker-compose.prod.yml up -d
   
   # Run migrations
   docker-compose -f docker-compose.prod.yml exec app alembic upgrade head
   ```

### SSL/TLS Setup

1. **Using Let's Encrypt**
   ```bash
   # Install certbot
   sudo apt install certbot python3-certbot-nginx
   
   # Get certificate
   sudo certbot --nginx -d your-domain.com
   ```

2. **Update Nginx Configuration**
   ```nginx
   server {
       listen 443 ssl http2;
       server_name your-domain.com;
       
       ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
       
       location / {
           proxy_pass http://app:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

---

## Kubernetes Deployment

For large-scale deployments using Kubernetes.

### Prerequisites

- Kubernetes cluster (1.20+)
- kubectl configured
- Helm 3.x
- External PostgreSQL and Redis (or operators)

### Kubernetes Manifests

1. **Namespace**
   ```yaml
   # k8s/namespace.yaml
   apiVersion: v1
   kind: Namespace
   metadata:
     name: context-memory-gateway
   ```

2. **ConfigMap**
   ```yaml
   # k8s/configmap.yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: cmg-config
     namespace: context-memory-gateway
   data:
     ENVIRONMENT: "production"
     LOG_LEVEL: "INFO"
     RATE_LIMIT_REQUESTS: "1000"
     RATE_LIMIT_WINDOW: "60"
     DEFAULT_TOKEN_BUDGET: "8000"
     MAX_CONTEXT_ITEMS: "50"
   ```

3. **Secret**
   ```yaml
   # k8s/secret.yaml
   apiVersion: v1
   kind: Secret
   metadata:
     name: cmg-secrets
     namespace: context-memory-gateway
   type: Opaque
   data:
     DATABASE_URL: <base64-encoded-url>
     REDIS_URL: <base64-encoded-url>
     OPENROUTER_API_KEY: <base64-encoded-key>
     SECRET_KEY: <base64-encoded-secret>
   ```

4. **Deployment**
   ```yaml
   # k8s/deployment.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: cmg-app
     namespace: context-memory-gateway
   spec:
     replicas: 3
     selector:
       matchLabels:
         app: cmg-app
     template:
       metadata:
         labels:
           app: cmg-app
       spec:
         containers:
         - name: app
           image: context-memory-gateway:latest
           ports:
           - containerPort: 8000
           envFrom:
           - configMapRef:
               name: cmg-config
           - secretRef:
               name: cmg-secrets
           livenessProbe:
             httpGet:
               path: /health
               port: 8000
             initialDelaySeconds: 30
             periodSeconds: 10
           readinessProbe:
             httpGet:
               path: /health
               port: 8000
             initialDelaySeconds: 5
             periodSeconds: 5
           resources:
             requests:
               memory: "256Mi"
               cpu: "250m"
             limits:
               memory: "512Mi"
               cpu: "500m"
   ```

5. **Service**
   ```yaml
   # k8s/service.yaml
   apiVersion: v1
   kind: Service
   metadata:
     name: cmg-service
     namespace: context-memory-gateway
   spec:
     selector:
       app: cmg-app
     ports:
     - port: 80
       targetPort: 8000
     type: ClusterIP
   ```

6. **Ingress**
   ```yaml
   # k8s/ingress.yaml
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: cmg-ingress
     namespace: context-memory-gateway
     annotations:
       kubernetes.io/ingress.class: nginx
       cert-manager.io/cluster-issuer: letsencrypt-prod
   spec:
     tls:
     - hosts:
       - your-domain.com
       secretName: cmg-tls
     rules:
     - host: your-domain.com
       http:
         paths:
         - path: /
           pathType: Prefix
           backend:
             service:
               name: cmg-service
               port:
                 number: 80
   ```

### Deploy to Kubernetes

```bash
# Apply manifests
kubectl apply -f k8s/

# Check deployment
kubectl get pods -n context-memory-gateway

# Run migrations
kubectl exec -it deployment/cmg-app -n context-memory-gateway -- alembic upgrade head
```

---

## Environment-Specific Configurations

### Development
- Single instance
- Local databases
- Debug logging enabled
- Hot reloading

### Staging
- 2 app instances
- Managed databases
- Production-like configuration
- Reduced quotas

### Production
- 3+ app instances
- High-availability databases
- Comprehensive monitoring
- Full security hardening

---

## Database Setup

### PostgreSQL with pgvector

1. **Install pgvector Extension**
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

2. **Create Database User**
   ```sql
   CREATE USER cmg_user WITH PASSWORD 'secure_password';
   GRANT ALL PRIVILEGES ON DATABASE cmg_prod TO cmg_user;
   ```

3. **Run Migrations**
   ```bash
   alembic upgrade head
   ```

### Redis Configuration

```redis
# redis.conf
maxmemory 1gb
maxmemory-policy allkeys-lru
appendonly yes
appendfsync everysec
```

---

## Monitoring and Observability

### Health Checks

Configure health checks for:
- Application: `GET /health`
- Detailed: `GET /health/detailed`
- Database connectivity
- Redis connectivity
- OpenRouter API connectivity

### Metrics

The application exposes Prometheus metrics at `/metrics`:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'context-memory-gateway'
    static_configs:
      - targets: ['app:8000']
    metrics_path: /metrics
    scrape_interval: 15s
```

### Logging

Configure structured logging:

```json
{
  "timestamp": "2025-01-20T10:00:00Z",
  "level": "INFO",
  "logger": "app.api.llm_gateway",
  "message": "chat_completion_request",
  "request_id": "req_123",
  "model": "openai/gpt-4",
  "tokens": 150,
  "duration_ms": 1250
}
```

### Alerting

Set up alerts for:
- High error rates (>5%)
- High response times (>2s p95)
- Database connection failures
- Queue backlog buildup
- Memory/CPU usage spikes

---

## Security Considerations

### Network Security
- Use HTTPS/TLS for all connections
- Implement proper firewall rules
- Use VPC/private networks
- Enable DDoS protection

### Application Security
- Rotate API keys regularly
- Use strong secrets
- Enable rate limiting
- Implement request validation
- Use secure headers

### Database Security
- Use connection pooling
- Enable SSL connections
- Regular security updates
- Backup encryption

### Monitoring Security
- Log all authentication attempts
- Monitor for suspicious patterns
- Set up security alerts
- Regular security audits

---

## Backup and Recovery

### Database Backups

```bash
# Automated backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump $DATABASE_URL > backup_$DATE.sql
aws s3 cp backup_$DATE.sql s3://your-backup-bucket/
```

### Application State

- Configuration backups
- API key exports (encrypted)
- Usage statistics archives

### Recovery Procedures

1. **Database Recovery**
   ```bash
   # Restore from backup
   psql $DATABASE_URL < backup_20250120_100000.sql
   
   # Run migrations if needed
   alembic upgrade head
   ```

2. **Application Recovery**
   - Redeploy from known good image
   - Restore configuration
   - Verify health checks

---

## Performance Optimization

### Application Level
- Enable connection pooling
- Use async/await properly
- Implement caching strategies
- Optimize database queries

### Infrastructure Level
- Use CDN for static assets
- Implement load balancing
- Scale horizontally
- Optimize database configuration

### Monitoring Performance
- Track response times
- Monitor database performance
- Watch memory usage
- Monitor queue lengths

---

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   ```bash
   # Check database connectivity
   psql $DATABASE_URL -c "SELECT 1;"
   
   # Check connection pool
   curl http://localhost:8000/health/detailed
   ```

2. **Redis Connection Issues**
   ```bash
   # Test Redis connection
   redis-cli -u $REDIS_URL ping
   
   # Check Redis memory usage
   redis-cli -u $REDIS_URL info memory
   ```

3. **High Memory Usage**
   ```bash
   # Check application memory
   docker stats
   
   # Check for memory leaks
   curl http://localhost:8000/metrics | grep memory
   ```

4. **Queue Backlog**
   ```bash
   # Check queue status
   curl -H "Authorization: Bearer $API_KEY" \
        http://localhost:8000/v1/workers/queues/stats
   
   # Scale workers
   docker-compose up --scale worker=3
   ```

### Log Analysis

```bash
# Search for errors
grep "ERROR" /var/log/app.log

# Check response times
grep "request_completed" /var/log/app.log | jq '.duration_ms'

# Monitor authentication failures
grep "authentication_failed" /var/log/app.log
```

---

## Maintenance

### Regular Tasks
- Update dependencies
- Rotate secrets
- Clean up old data
- Review security logs
- Update documentation

### Scheduled Maintenance
- Database maintenance (VACUUM, ANALYZE)
- Log rotation
- Backup verification
- Security patches
- Performance reviews

---

## Support

For deployment issues:
- Check the troubleshooting section
- Review application logs
- Consult the monitoring dashboard
- Create an issue in the repository

