# Optional Qdrant vector database droplet (fallback from pgvector)
resource "digitalocean_droplet" "qdrant" {
  count = var.enable_qdrant ? 1 : 0
  
  image    = "ubuntu-22-04-x64"
  name     = "${var.project_name}-qdrant-${var.environment}"
  region   = var.do_region
  size     = var.qdrant_droplet_size
  vpc_uuid = digitalocean_vpc.main.id
  
  tags = concat(var.tags, ["qdrant"])
  
  # SSH key for access (optional)
  # ssh_keys = [digitalocean_ssh_key.main.id]
  
  # User data script to install and configure Qdrant
  user_data = templatefile("${path.module}/templates/qdrant_setup.sh", {
    environment = var.environment
  })
  
  # Monitoring
  monitoring = var.enable_monitoring
  
  # Backup policy
  backup = var.enable_database_backups
}

# Reserved IP for Qdrant (optional, for static access)
resource "digitalocean_reserved_ip" "qdrant" {
  count  = var.enable_qdrant ? 1 : 0
  region = var.do_region
  type   = "assign"
  
  droplet_id = digitalocean_droplet.qdrant[0].id
}

# Volume for Qdrant data persistence
resource "digitalocean_volume" "qdrant" {
  count                   = var.enable_qdrant ? 1 : 0
  region                  = var.do_region
  name                    = "${var.project_name}-qdrant-data-${var.environment}"
  size                    = 10  # GB
  initial_filesystem_type = "ext4"
  description             = "Qdrant data volume for ${var.project_name}"
  
  tags = var.tags
}

# Attach volume to Qdrant droplet
resource "digitalocean_volume_attachment" "qdrant" {
  count      = var.enable_qdrant ? 1 : 0
  droplet_id = digitalocean_droplet.qdrant[0].id
  volume_id  = digitalocean_volume.qdrant[0].id
}

# Load balancer for Qdrant (optional, for high availability)
resource "digitalocean_loadbalancer" "qdrant" {
  count = var.enable_qdrant && var.environment == "production" ? 1 : 0
  
  name   = "${var.project_name}-qdrant-lb-${var.environment}"
  region = var.do_region
  
  vpc_uuid = digitalocean_vpc.main.id
  
  forwarding_rule {
    entry_protocol  = "http"
    entry_port      = 80
    target_protocol = "http"
    target_port     = 6333
  }
  
  forwarding_rule {
    entry_protocol  = "https"
    entry_port      = 443
    target_protocol = "http"
    target_port     = 6333
    tls_passthrough = false
  }
  
  healthcheck {
    protocol               = "http"
    port                   = 6333
    path                   = "/health"
    check_interval_seconds = 10
    response_timeout_seconds = 5
    unhealthy_threshold    = 3
    healthy_threshold      = 2
  }
  
  droplet_ids = [digitalocean_droplet.qdrant[0].id]
  
  tags = var.tags
}

# Store Qdrant connection information
resource "local_file" "qdrant_credentials" {
  count = var.enable_qdrant ? 1 : 0
  
  content = templatefile("${path.module}/templates/qdrant_credentials.tpl", {
    droplet_ip     = digitalocean_droplet.qdrant[0].ipv4_address
    private_ip     = digitalocean_droplet.qdrant[0].ipv4_address_private
    reserved_ip    = var.enable_qdrant ? digitalocean_reserved_ip.qdrant[0].ip_address : ""
    lb_ip          = var.enable_qdrant && var.environment == "production" ? digitalocean_loadbalancer.qdrant[0].ip : ""
    http_url       = "http://${digitalocean_droplet.qdrant[0].ipv4_address_private}:6333"
    grpc_url       = "http://${digitalocean_droplet.qdrant[0].ipv4_address_private}:6334"
  })
  
  filename = "${path.module}/outputs/qdrant_credentials.txt"
  file_permission = "0600"
}

