#!/bin/bash

# Script to fix Docker Compose ContainerConfig issues
# Context Memory Gateway - Docker Fix Script

echo "=== Context Memory Gateway Docker Fix Script ==="
echo "Fixing ContainerConfig KeyError and related issues..."

# 1. Stop and remove any existing containers
echo "1. Cleaning up existing containers and networks..."
docker-compose -f docker-compose.yml down --remove-orphans 2>/dev/null || true
docker-compose -f docker-compose.local.yml down --remove-orphans 2>/dev/null || true
docker-compose -f docker-compose.supabase.yml down --remove-orphans 2>/dev/null || true

# 2. Remove dangling containers with context-memory prefix
echo "2. Removing any dangling containers..."
docker ps -aq --filter "name=context-memory" | xargs -r docker rm -f 2>/dev/null || true
docker ps -aq --filter "name=cmg-" | xargs -r docker rm -f 2>/dev/null || true

# 3. Clean up dangling images and networks
echo "3. Cleaning up Docker system..."
docker system prune -f 2>/dev/null || true
docker network prune -f 2>/dev/null || true

# 4. Remove any problematic volumes if they exist
echo "4. Cleaning up volumes (optional - comment out if you want to keep data)..."
# docker volume rm context-memory-main_postgres_data 2>/dev/null || true
# docker volume rm context-memory-main_redis_data 2>/dev/null || true

# 5. Create required directories
echo "5. Creating required directories..."
mkdir -p logs data config/grafana/provisioning config/grafana/dashboards

# 6. Fix permissions
echo "6. Setting correct permissions..."
chmod 755 logs data
chmod -R 755 config 2>/dev/null || true

# 7. Pull required images
echo "7. Pulling required Docker images..."
docker pull pgvector/pgvector:pg15
docker pull redis:7-alpine
docker pull python:3.11-slim

echo "=== Docker environment cleaned up ==="
echo ""
echo "Next steps:"
echo "1. Use docker-compose.test.yml for testing: docker-compose -f docker-compose.test.yml up --build"
echo "2. Or use the main compose file: docker-compose up --build"
echo "3. Check logs if issues persist: docker-compose logs -f"
echo ""
echo "If you still get ContainerConfig errors, try:"
echo "- Update Docker Desktop to latest version"
echo "- Restart Docker Desktop completely"
echo "- Run: docker system prune -a (removes all unused images)"