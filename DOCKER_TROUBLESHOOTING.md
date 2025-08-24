# Docker Troubleshooting Guide

## ContainerConfig KeyError - Complete Solution

### Problem Description
The error `KeyError: 'ContainerConfig'` typically occurs when Docker Compose cannot properly access container image configuration, often due to:

1. **Volume mount issues** - Missing directories or incorrect paths
2. **Docker version compatibility** - Outdated Docker or Docker Compose versions  
3. **Corrupted container state** - Dangling containers or networks
4. **Build context problems** - Missing files referenced in Dockerfile

### Immediate Fix Steps

#### 1. Run the Fix Script
```bash
./fix-docker-issues.sh
```

#### 2. Test with Minimal Setup
Start with just the databases:
```bash
docker-compose -f docker-compose.minimal.yml up -d
```

#### 3. Test with Limited Services
Use the test configuration:
```bash
docker-compose -f docker-compose.test.yml up --build
```

#### 4. Full Deployment (after testing)
```bash
docker-compose up --build
```

### Root Cause Analysis

#### Fixed Issues in docker-compose.yml:

1. **Incorrect volume paths:**
   - ❌ `./config/nginx.conf` → ✅ `./infra/nginx/nginx.conf`  
   - ❌ `./config/prometheus.yml` → ✅ `./infra/prometheus/prometheus.yml`
   - ❌ Missing grafana config → ✅ Removed non-existent mounts

2. **Redis health check issues:**
   - ❌ `--raw incr ping` → ✅ `-a password ping`
   - ❌ Short timeouts → ✅ Reasonable intervals

3. **Missing directories:**
   - Created: `logs/`, `data/`, `config/`
   - Fixed permissions

#### Fixed Issues in Dockerfile:

1. **Incorrect alembic.ini copy:**
   - ❌ `COPY server/alembic.ini ./` → ✅ Already in server/ directory

### Testing Strategy

#### Phase 1: Databases Only
```bash
docker-compose -f docker-compose.minimal.yml up
```
**Validates:** Basic Docker functionality, image pulling, volume mounting

#### Phase 2: Core Services  
```bash
docker-compose -f docker-compose.test.yml up --build
```
**Validates:** Application build, database connections, health checks

#### Phase 3: Full Stack
```bash
docker-compose up --build
```
**Validates:** All services, monitoring, reverse proxy

### Alternative Approaches

#### Option 1: Use docker-compose.local.yml
This file has different (potentially working) configurations:
```bash
docker-compose -f docker-compose.local.yml up --build
```

#### Option 2: Use Supabase Version
For Supabase-based deployment:
```bash
docker-compose -f docker-compose.supabase.yml up --build
```

### Environment Variables

Ensure you have proper environment variables set. Copy from example:
```bash
cp .env.example .env
```

Required variables:
- `OPENROUTER_API_KEY`
- `SECRET_KEY`
- `JWT_SECRET_KEY`
- Database credentials (if different from defaults)

### Common Error Solutions

#### "Cannot connect to Docker daemon"
```bash
# Start Docker Desktop or Docker daemon
sudo systemctl start docker  # Linux
# Or restart Docker Desktop on macOS/Windows
```

#### "network not found"
```bash
docker network create context-memory-gateway
```

#### "Port already in use"
```bash
# Find and kill processes using the port
lsof -ti:8000 | xargs kill -9
# Or change ports in docker-compose.yml
```

#### "Volume mount failed"
```bash
# Check directory exists and has correct permissions
ls -la logs/ data/
chmod 755 logs/ data/
```

### Advanced Debugging

#### Check Docker Compose version
```bash
docker-compose version
# Recommended: >= 1.29.0
```

#### Inspect failed containers
```bash
docker-compose ps
docker logs cmg-app
docker inspect cmg-app
```

#### Check volume mounts
```bash
docker exec -it cmg-app ls -la /app/
docker exec -it cmg-app ls -la /app/logs/
```

### Performance Optimization

#### Reduce resource usage:
```yaml
# In docker-compose.yml, add to each service:
deploy:
  resources:
    limits:
      memory: 512M
      cpus: '0.5'
```

#### Speed up builds:
```bash
# Use build cache
docker-compose build --parallel

# Multi-stage builds already optimized in Dockerfile
```

### Final Validation

After successful startup, verify:

1. **Health endpoints:**
   ```bash
   curl http://localhost:8000/health
   ```

2. **Database connectivity:**
   ```bash
   docker exec -it cmg-postgres psql -U cmg_user -d context_memory_gateway -c "SELECT version();"
   ```

3. **Redis connectivity:**
   ```bash
   docker exec -it cmg-redis redis-cli ping
   ```

4. **Application logs:**
   ```bash
   docker-compose logs -f app
   ```

### Still Having Issues?

1. **Update Docker:** Ensure Docker Desktop is latest version
2. **Clear everything:** `docker system prune -a --volumes` (⚠️ removes all data)
3. **Check system resources:** Ensure sufficient RAM/disk space
4. **Report specific error:** Include full error messages and system info

### Quick Reference Commands

```bash
# Clean restart
docker-compose down --remove-orphans && docker-compose up --build

# View logs
docker-compose logs -f [service-name]

# Shell into container
docker exec -it cmg-app bash

# Database shell
docker exec -it cmg-postgres psql -U cmg_user -d context_memory_gateway

# Redis shell  
docker exec -it cmg-redis redis-cli
```