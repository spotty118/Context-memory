terraform {
  required_version = ">= 1.0"
  
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.34"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.4"
    }
  }
  
  # Configure remote state storage (optional)
  # backend "s3" {
  #   endpoint                    = "https://nyc3.digitaloceanspaces.com"
  #   key                         = "terraform/context-memory-gateway.tfstate"
  #   bucket                      = "your-terraform-state-bucket"
  #   region                      = "us-east-1"  # Required for S3 compatibility
  #   skip_credentials_validation = true
  #   skip_metadata_api_check     = true
  # }
}

# Configure the DigitalOcean Provider
provider "digitalocean" {
  token = var.do_token
}

# Random provider for generating secrets
provider "random" {}

# Data sources for available options
data "digitalocean_regions" "available" {}

data "digitalocean_sizes" "available" {}

data "digitalocean_database_cluster" "postgres_versions" {
  name = "temp-cluster-for-versions"
  lifecycle {
    ignore_changes = all
  }
}

