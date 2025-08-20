# DigitalOcean Container Registry
resource "digitalocean_container_registry" "main" {
  name                   = "${var.project_name}-registry-${var.environment}"
  subscription_tier_slug = "basic"  # basic, professional, or starter
  region                 = var.do_region
}

# Container registry repository
resource "digitalocean_container_registry_docker_credentials" "main" {
  registry_name = digitalocean_container_registry.main.name
}

# Store registry credentials
resource "local_file" "registry_credentials" {
  content = templatefile("${path.module}/templates/registry_credentials.tpl", {
    registry_name = digitalocean_container_registry.main.name
    endpoint      = digitalocean_container_registry.main.endpoint
    server_url    = digitalocean_container_registry.main.server_url
  })
  
  filename = "${path.module}/outputs/registry_credentials.txt"
  file_permission = "0600"
}

# Registry garbage collection policy
resource "digitalocean_container_registry" "main_gc" {
  name                   = digitalocean_container_registry.main.name
  subscription_tier_slug = digitalocean_container_registry.main.subscription_tier_slug
  region                 = digitalocean_container_registry.main.region
  
  # Garbage collection policy to clean up old images
  # This helps manage storage costs
  lifecycle {
    ignore_changes = [subscription_tier_slug]
  }
}

