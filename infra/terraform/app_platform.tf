# DigitalOcean App Platform application
resource "digitalocean_app" "main" {
  spec {
    name   = "${var.project_name}-app-${var.environment}"
    region = var.do_region
    
    # Main API service
    service {
      name               = "api-service"
      instance_count     = var.app_instance_count
      instance_size_slug = var.app_instance_size
      http_port          = 8080
      
      # Docker image from container registry
      image {
        registry_type = "DOCR"
        registry      = digitalocean_container_registry.main.name
        repository    = "${var.project_name}-api"
        tag           = var.image_tag
      }
      
      # Health check configuration
      health_check {
        http_path                = "/healthz"
        initial_delay_seconds    = 30
        period_seconds          = 10
        timeout_seconds         = 5
        success_threshold       = 1
        failure_threshold       = 3
      }
      
      # Autoscaling configuration
      autoscaling {
        min_instance_count = var.app_min_instances
        max_instance_count = var.app_max_instances
        metrics {
          cpu {
            percent = 70
          }
        }
      }
      
      # Environment variables
      env {
        key   = "SERVER_PORT"
        value = "8080"
      }
      
      env {
        key   = "ENVIRONMENT"
        value = var.environment
      }
      
      env {
        key   = "DATABASE_URL"
        value = "postgresql+asyncpg://${digitalocean_database_user.app_user.name}:${digitalocean_database_user.app_user.password}@${digitalocean_database_connection_pool.app_pool.host}:${digitalocean_database_connection_pool.app_pool.port}/${digitalocean_database_db.main.name}?sslmode=require"
      }
      
      env {
        key   = "REDIS_URL"
        value = "redis://:${digitalocean_database_cluster.redis.password}@${digitalocean_database_cluster.redis.host}:${digitalocean_database_cluster.redis.port}"
      }
      
      env {
        key   = "SPACES_ENDPOINT"
        value = "https://${var.do_region}.digitaloceanspaces.com"
      }
      
      env {
        key   = "SPACES_REGION"
        value = var.do_region
      }
      
      env {
        key   = "SPACES_BUCKET"
        value = digitalocean_spaces_bucket.main.name
      }
      
      env {
        key   = "SPACES_ACCESS_KEY"
        value = random_id.spaces_access_key.hex
      }
      
      env {
        key   = "OPENROUTER_BASE"
        value = "https://openrouter.ai/api"
      }
      
      env {
        key   = "EMBEDDINGS_PROVIDER"
        value = "openrouter"
      }
      
      env {
        key   = "VECTOR_BACKEND"
        value = var.enable_qdrant ? "qdrant" : "pgvector"
      }
      
      env {
        key   = "QDRANT_URL"
        value = var.enable_qdrant ? "http://${digitalocean_droplet.qdrant[0].ipv4_address_private}:6333" : ""
      }
      
      env {
        key   = "METRICS_ENABLED"
        value = var.enable_monitoring ? "true" : "false"
      }
      
      env {
        key   = "LOG_LEVEL"
        value = var.environment == "production" ? "INFO" : "DEBUG"
      }
      
      # Sensitive environment variables (secrets)
      env {
        key   = "OPENROUTER_API_KEY"
        value = var.openrouter_api_key
        type  = "SECRET"
      }
      
      env {
        key   = "AUTH_API_KEY_SALT"
        value = var.auth_api_key_salt
        type  = "SECRET"
      }
      
      env {
        key   = "JWT_SECRET_KEY"
        value = var.jwt_secret_key
        type  = "SECRET"
      }
      
      env {
        key   = "SPACES_SECRET_KEY"
        value = random_password.spaces_secret_key.result
        type  = "SECRET"
      }
      
      env {
        key   = "SENTRY_DSN"
        value = var.sentry_dsn
        type  = "SECRET"
      }
      
      # Resource limits
      cpu_kind = "shared"
      
      # Routing configuration
      routes {
        path = "/"
      }
    }
    
    # Optional worker service for background tasks
    worker {
      name               = "worker-service"
      instance_count     = 1
      instance_size_slug = "basic-xxs"
      
      # Use the same image as the API service
      image {
        registry_type = "DOCR"
        registry      = digitalocean_container_registry.main.name
        repository    = "${var.project_name}-api"
        tag           = var.image_tag
      }
      
      # Override the command to run worker instead of web server
      run_command = "python -m rq worker --url $REDIS_URL"
      
      # Same environment variables as API service
      env {
        key   = "ENVIRONMENT"
        value = var.environment
      }
      
      env {
        key   = "DATABASE_URL"
        value = "postgresql+asyncpg://${digitalocean_database_user.app_user.name}:${digitalocean_database_user.app_user.password}@${digitalocean_database_connection_pool.app_pool.host}:${digitalocean_database_connection_pool.app_pool.port}/${digitalocean_database_db.main.name}?sslmode=require"
      }
      
      env {
        key   = "REDIS_URL"
        value = "redis://:${digitalocean_database_cluster.redis.password}@${digitalocean_database_cluster.redis.host}:${digitalocean_database_cluster.redis.port}"
      }
      
      env {
        key   = "OPENROUTER_API_KEY"
        value = var.openrouter_api_key
        type  = "SECRET"
      }
    }
    
    # Database connections
    database {
      name         = "db"
      cluster_name = digitalocean_database_cluster.postgres.name
      db_name      = digitalocean_database_db.main.name
      db_user      = digitalocean_database_user.app_user.name
      engine       = "PG"
    }
    
    database {
      name         = "cache"
      cluster_name = digitalocean_database_cluster.redis.name
      engine       = "REDIS"
    }
    
    # Domain configuration (optional)
    # domain {
    #   name = "api.yourdomain.com"
    #   type = "PRIMARY"
    # }
  }
  
  # Lifecycle management
  lifecycle {
    ignore_changes = [
      spec[0].service[0].image[0].tag,  # Allow CI/CD to update image tags
    ]
  }
}

# App Platform domain (if custom domain is needed)
# resource "digitalocean_app_domain" "main" {
#   app_id = digitalocean_app.main.id
#   domain = "api.yourdomain.com"
#   type   = "PRIMARY"
# }

