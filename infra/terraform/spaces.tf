# DigitalOcean Spaces bucket for object storage
resource "digitalocean_spaces_bucket" "main" {
  name   = "${var.project_name}-storage-${var.environment}"
  region = var.do_region
  
  # Enable versioning for data protection
  versioning {
    enabled = true
  }
  
  # CORS configuration for web access
  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = ["*"]  # Configure with actual domains in production
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
  
  # Lifecycle configuration to manage old versions
  lifecycle_rule {
    id      = "delete_old_versions"
    enabled = true
    
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Spaces access key for application
resource "digitalocean_spaces_bucket_object" "readme" {
  region = digitalocean_spaces_bucket.main.region
  bucket = digitalocean_spaces_bucket.main.name
  key    = "README.txt"
  content = "Context Memory Gateway Storage Bucket - ${var.environment}"
  content_type = "text/plain"
}

# Generate Spaces access keys
resource "random_id" "spaces_access_key" {
  byte_length = 16
}

resource "random_password" "spaces_secret_key" {
  length  = 40
  special = true
}

# Store Spaces credentials
resource "local_file" "spaces_credentials" {
  content = templatefile("${path.module}/templates/spaces_credentials.tpl", {
    bucket_name   = digitalocean_spaces_bucket.main.name
    region        = digitalocean_spaces_bucket.main.region
    endpoint      = "https://${var.do_region}.digitaloceanspaces.com"
    access_key    = random_id.spaces_access_key.hex
    secret_key    = random_password.spaces_secret_key.result
    bucket_url    = "https://${digitalocean_spaces_bucket.main.name}.${var.do_region}.digitaloceanspaces.com"
  })
  
  filename = "${path.module}/outputs/spaces_credentials.txt"
  file_permission = "0600"
}

