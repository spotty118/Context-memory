# Application outputs
output "app_url" {
  description = "URL of the deployed application"
  value       = "https://${digitalocean_app.main.live_url}"
}

output "app_id" {
  description = "DigitalOcean App Platform app ID"
  value       = digitalocean_app.main.id
}

output "app_urn" {
  description = "DigitalOcean App Platform app URN"
  value       = digitalocean_app.main.urn
}

# Database outputs
output "postgres_host" {
  description = "PostgreSQL database host"
  value       = digitalocean_database_cluster.postgres.host
  sensitive   = true
}

output "postgres_port" {
  description = "PostgreSQL database port"
  value       = digitalocean_database_cluster.postgres.port
}

output "postgres_database" {
  description = "PostgreSQL database name"
  value       = digitalocean_database_db.main.name
}

output "postgres_user" {
  description = "PostgreSQL database user"
  value       = digitalocean_database_user.app_user.name
}

output "postgres_connection_pool_host" {
  description = "PostgreSQL connection pool host"
  value       = digitalocean_database_connection_pool.app_pool.host
  sensitive   = true
}

output "postgres_connection_pool_port" {
  description = "PostgreSQL connection pool port"
  value       = digitalocean_database_connection_pool.app_pool.port
}

# Redis outputs
output "redis_host" {
  description = "Redis host"
  value       = digitalocean_database_cluster.redis.host
  sensitive   = true
}

output "redis_port" {
  description = "Redis port"
  value       = digitalocean_database_cluster.redis.port
}

# Spaces outputs
output "spaces_bucket_name" {
  description = "DigitalOcean Spaces bucket name"
  value       = digitalocean_spaces_bucket.main.name
}

output "spaces_bucket_domain" {
  description = "DigitalOcean Spaces bucket domain"
  value       = digitalocean_spaces_bucket.main.bucket_domain_name
}

output "spaces_endpoint" {
  description = "DigitalOcean Spaces endpoint"
  value       = "https://${var.do_region}.digitaloceanspaces.com"
}

# Container Registry outputs
output "registry_endpoint" {
  description = "Container registry endpoint"
  value       = digitalocean_container_registry.main.endpoint
}

output "registry_server_url" {
  description = "Container registry server URL"
  value       = digitalocean_container_registry.main.server_url
}

# VPC outputs
output "vpc_id" {
  description = "VPC ID"
  value       = digitalocean_vpc.main.id
}

output "vpc_ip_range" {
  description = "VPC IP range"
  value       = digitalocean_vpc.main.ip_range
}

# Qdrant outputs (if enabled)
output "qdrant_droplet_ip" {
  description = "Qdrant droplet public IP"
  value       = var.enable_qdrant ? digitalocean_droplet.qdrant[0].ipv4_address : null
}

output "qdrant_private_ip" {
  description = "Qdrant droplet private IP"
  value       = var.enable_qdrant ? digitalocean_droplet.qdrant[0].ipv4_address_private : null
  sensitive   = true
}

output "qdrant_reserved_ip" {
  description = "Qdrant reserved IP"
  value       = var.enable_qdrant ? digitalocean_reserved_ip.qdrant[0].ip_address : null
}

# Project outputs
output "project_id" {
  description = "DigitalOcean project ID"
  value       = digitalocean_project.main.id
}

# Environment information
output "environment" {
  description = "Deployment environment"
  value       = var.environment
}

output "region" {
  description = "DigitalOcean region"
  value       = var.do_region
}

# Health check URLs
output "health_check_url" {
  description = "Application health check URL"
  value       = "https://${digitalocean_app.main.live_url}/healthz"
}

output "readiness_check_url" {
  description = "Application readiness check URL"
  value       = "https://${digitalocean_app.main.live_url}/readyz"
}

output "metrics_url" {
  description = "Application metrics URL"
  value       = "https://${digitalocean_app.main.live_url}/metrics"
}

output "admin_url" {
  description = "Admin interface URL"
  value       = "https://${digitalocean_app.main.live_url}/admin"
}

# API endpoints
output "api_base_url" {
  description = "API base URL"
  value       = "https://${digitalocean_app.main.live_url}/v1"
}

output "models_endpoint" {
  description = "Models API endpoint"
  value       = "https://${digitalocean_app.main.live_url}/v1/models"
}

output "chat_endpoint" {
  description = "Chat completions endpoint"
  value       = "https://${digitalocean_app.main.live_url}/v1/llm/chat"
}

output "embeddings_endpoint" {
  description = "Embeddings endpoint"
  value       = "https://${digitalocean_app.main.live_url}/v1/embeddings"
}

# Summary output
output "deployment_summary" {
  description = "Deployment summary"
  value = {
    app_url           = "https://${digitalocean_app.main.live_url}"
    environment       = var.environment
    region           = var.do_region
    postgres_enabled = true
    redis_enabled    = true
    qdrant_enabled   = var.enable_qdrant
    monitoring       = var.enable_monitoring
    backup_enabled   = var.enable_database_backups
  }
}

