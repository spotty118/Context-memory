# PostgreSQL Database Cluster
resource "digitalocean_database_cluster" "postgres" {
  name       = "${var.project_name}-postgres-${var.environment}"
  engine     = "pg"
  version    = var.postgres_version
  size       = var.postgres_size
  region     = var.do_region
  node_count = var.postgres_node_count
  
  private_network_uuid = digitalocean_vpc.main.id
  
  tags = var.tags
  
  # Enable maintenance window during low-traffic hours
  maintenance_window {
    day  = "sunday"
    hour = "04:00:00"
  }
  
  # Enable backups
  backup_restore {
    database_name = "${var.project_name}_${var.environment}"
  }
}

# Database for the application
resource "digitalocean_database_db" "main" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "${var.project_name}_${var.environment}"
}

# Database user for the application
resource "digitalocean_database_user" "app_user" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "${var.project_name}_app"
}

# Connection pool for better performance
resource "digitalocean_database_connection_pool" "app_pool" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "${var.project_name}-pool"
  mode       = "transaction"
  size       = 20
  db_name    = digitalocean_database_db.main.name
  user       = digitalocean_database_user.app_user.name
}

# Firewall rule to allow App Platform access
resource "digitalocean_database_firewall" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id
  
  # Allow access from the VPC
  rule {
    type  = "ip_addr"
    value = var.vpc_ip_range
  }
  
  # Allow access from App Platform (DigitalOcean's internal network)
  rule {
    type  = "app"
    value = digitalocean_app.main.id
  }
}

# Random password for database operations
resource "random_password" "postgres_admin" {
  length  = 32
  special = true
}

# Store database credentials in a local file for reference
resource "local_file" "database_credentials" {
  content = templatefile("${path.module}/templates/database_credentials.tpl", {
    host           = digitalocean_database_cluster.postgres.host
    port           = digitalocean_database_cluster.postgres.port
    database       = digitalocean_database_db.main.name
    username       = digitalocean_database_user.app_user.name
    password       = digitalocean_database_user.app_user.password
    pool_host      = digitalocean_database_connection_pool.app_pool.host
    pool_port      = digitalocean_database_connection_pool.app_pool.port
    ssl_mode       = "require"
    connection_url = "postgresql+asyncpg://${digitalocean_database_user.app_user.name}:${digitalocean_database_user.app_user.password}@${digitalocean_database_connection_pool.app_pool.host}:${digitalocean_database_connection_pool.app_pool.port}/${digitalocean_database_db.main.name}?sslmode=require"
  })
  
  filename = "${path.module}/outputs/database_credentials.txt"
  
  # Make file readable only by owner
  file_permission = "0600"
}

