# VPC for network isolation
resource "digitalocean_vpc" "main" {
  name     = "${var.project_name}-vpc-${var.environment}"
  region   = var.do_region
  ip_range = var.vpc_ip_range
  
  description = "VPC for ${var.project_name} ${var.environment} environment"
}

# Project for organizing resources
resource "digitalocean_project" "main" {
  name        = "${var.project_name}-${var.environment}"
  description = "Context Memory + LLM Gateway ${var.environment} environment"
  purpose     = "Web Application"
  environment = title(var.environment)
  
  resources = [
    digitalocean_vpc.main.urn,
    digitalocean_database_cluster.postgres.urn,
    digitalocean_database_cluster.redis.urn,
    digitalocean_spaces_bucket.main.urn,
    digitalocean_container_registry.main.urn,
    digitalocean_app.main.urn,
  ]
}

# Firewall rules for database access
resource "digitalocean_firewall" "database" {
  name = "${var.project_name}-database-${var.environment}"
  
  tags = var.tags
  
  # Allow inbound connections from VPC
  inbound_rule {
    protocol         = "tcp"
    port_range       = "5432"
    source_addresses = [var.vpc_ip_range]
  }
  
  inbound_rule {
    protocol         = "tcp"
    port_range       = "6379"
    source_addresses = [var.vpc_ip_range]
  }
  
  # Allow all outbound traffic
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  
  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  
  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

# Optional: Qdrant droplet firewall
resource "digitalocean_firewall" "qdrant" {
  count = var.enable_qdrant ? 1 : 0
  
  name = "${var.project_name}-qdrant-${var.environment}"
  
  droplet_ids = [digitalocean_droplet.qdrant[0].id]
  
  # Allow HTTP/HTTPS from App Platform
  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = [var.vpc_ip_range]
  }
  
  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = [var.vpc_ip_range]
  }
  
  inbound_rule {
    protocol         = "tcp"
    port_range       = "6333"
    source_addresses = [var.vpc_ip_range]
  }
  
  # SSH access (optional, for debugging)
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0"]
  }
  
  # Allow all outbound traffic
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  
  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  
  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

