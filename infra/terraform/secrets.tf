# Generate random secrets if not provided
resource "random_password" "auth_api_key_salt" {
  count   = var.auth_api_key_salt == "" ? 1 : 0
  length  = 32
  special = true
}

resource "random_password" "jwt_secret_key" {
  count   = var.jwt_secret_key == "" ? 1 : 0
  length  = 64
  special = true
}

# Local values for secrets
locals {
  auth_api_key_salt = var.auth_api_key_salt != "" ? var.auth_api_key_salt : random_password.auth_api_key_salt[0].result
  jwt_secret_key    = var.jwt_secret_key != "" ? var.jwt_secret_key : random_password.jwt_secret_key[0].result
}

# Store all secrets in a secure file
resource "local_sensitive_file" "secrets" {
  content = templatefile("${path.module}/templates/secrets.tpl", {
    openrouter_api_key = var.openrouter_api_key
    auth_api_key_salt  = local.auth_api_key_salt
    jwt_secret_key     = local.jwt_secret_key
    sentry_dsn         = var.sentry_dsn
    spaces_access_key  = random_id.spaces_access_key.hex
    spaces_secret_key  = random_password.spaces_secret_key.result
    postgres_password  = digitalocean_database_user.app_user.password
    redis_password     = digitalocean_database_cluster.redis.password
  })
  
  filename = "${path.module}/outputs/secrets.env"
  file_permission = "0600"
}

# Create a .env file for local development
resource "local_file" "env_example" {
  content = templatefile("${path.module}/templates/env_example.tpl", {
    server_port           = "8080"
    environment          = "development"
    database_url         = "postgresql+asyncpg://user:password@localhost:5432/context_memory_gateway"
    redis_url            = "redis://localhost:6379"
    spaces_endpoint      = "https://${var.do_region}.digitaloceanspaces.com"
    spaces_region        = var.do_region
    spaces_bucket        = digitalocean_spaces_bucket.main.name
    openrouter_base      = "https://openrouter.ai/api"
    embeddings_provider  = "openrouter"
    vector_backend       = "pgvector"
    default_daily_quota  = "200000"
    rate_limit_rpm       = "60"
    debug_log_prompts    = "false"
    log_level           = "INFO"
    metrics_enabled     = "true"
  })
  
  filename = "${path.module}/outputs/.env.example"
  file_permission = "0644"
}

