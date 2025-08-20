# DigitalOcean Configuration
variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "do_region" {
  description = "DigitalOcean region"
  type        = string
  default     = "nyc3"
}

# Project Configuration
variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "context-memory-gateway"
}

variable "environment" {
  description = "Environment (development, staging, production)"
  type        = string
  default     = "production"
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

# VPC Configuration
variable "vpc_ip_range" {
  description = "IP range for the VPC"
  type        = string
  default     = "10.116.0.0/20"
}

# Database Configuration
variable "postgres_size" {
  description = "Size of the PostgreSQL cluster"
  type        = string
  default     = "db-s-1vcpu-1gb"
}

variable "postgres_node_count" {
  description = "Number of nodes in the PostgreSQL cluster"
  type        = number
  default     = 1
}

variable "postgres_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "15"
}

# Redis Configuration
variable "redis_size" {
  description = "Size of the Redis cluster"
  type        = string
  default     = "db-s-1vcpu-1gb"
}

# App Platform Configuration
variable "app_instance_count" {
  description = "Number of app instances"
  type        = number
  default     = 1
}

variable "app_instance_size" {
  description = "Size of app instances"
  type        = string
  default     = "professional-xs"
}

variable "app_min_instances" {
  description = "Minimum number of app instances for autoscaling"
  type        = number
  default     = 1
}

variable "app_max_instances" {
  description = "Maximum number of app instances for autoscaling"
  type        = number
  default     = 3
}

# Secrets
variable "openrouter_api_key" {
  description = "OpenRouter API key"
  type        = string
  sensitive   = true
}

variable "auth_api_key_salt" {
  description = "Salt for API key hashing"
  type        = string
  sensitive   = true
}

variable "jwt_secret_key" {
  description = "JWT secret key for admin sessions"
  type        = string
  sensitive   = true
}

variable "sentry_dsn" {
  description = "Sentry DSN for error tracking (optional)"
  type        = string
  default     = ""
  sensitive   = true
}

# Optional Qdrant Configuration
variable "enable_qdrant" {
  description = "Enable Qdrant vector database as fallback"
  type        = bool
  default     = false
}

variable "qdrant_droplet_size" {
  description = "Size of the Qdrant droplet"
  type        = string
  default     = "s-1vcpu-1gb"
}

# Monitoring Configuration
variable "enable_monitoring" {
  description = "Enable monitoring and alerting"
  type        = bool
  default     = true
}

# Backup Configuration
variable "enable_database_backups" {
  description = "Enable automatic database backups"
  type        = bool
  default     = true
}

# Tags
variable "tags" {
  description = "Tags to apply to all resources"
  type        = list(string)
  default     = ["context-memory-gateway", "terraform"]
}

