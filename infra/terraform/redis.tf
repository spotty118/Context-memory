# Redis Database Cluster for caching and queues
resource "digitalocean_database_cluster" "redis" {
  name       = "${var.project_name}-redis-${var.environment}"
  engine     = "redis"
  version    = "7"
  size       = var.redis_size
  region     = var.do_region
  node_count = 1  # Redis clusters typically start with 1 node
  
  private_network_uuid = digitalocean_vpc.main.id
  
  tags = var.tags
  
  # Enable maintenance window during low-traffic hours
  maintenance_window {
    day  = "sunday"
    hour = "05:00:00"
  }
  
  # Redis doesn't support backup_restore like PostgreSQL
  # but DigitalOcean provides automatic backups
}

# Firewall rule to allow App Platform access to Redis
resource "digitalocean_database_firewall" "redis" {
  cluster_id = digitalocean_database_cluster.redis.id
  
  # Allow access from the VPC
  rule {
    type  = "ip_addr"
    value = var.vpc_ip_range
  }
  
  # Allow access from App Platform
  rule {
    type  = "app"
    value = digitalocean_app.main.id
  }
}

# Store Redis credentials in a local file for reference
resource "local_file" "redis_credentials" {
  content = templatefile("${path.module}/templates/redis_credentials.tpl", {
    host           = digitalocean_database_cluster.redis.host
    port           = digitalocean_database_cluster.redis.port
    password       = digitalocean_database_cluster.redis.password
    connection_url = "redis://:${digitalocean_database_cluster.redis.password}@${digitalocean_database_cluster.redis.host}:${digitalocean_database_cluster.redis.port}"
  })
  
  filename = "${path.module}/outputs/redis_credentials.txt"
  
  # Make file readable only by owner
  file_permission = "0600"
}

