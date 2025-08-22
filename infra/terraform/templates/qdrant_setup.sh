#!/bin/bash
# Qdrant Vector Database Setup Script
# Environment: ${environment}

set -e

# Update system
apt-get update
apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
systemctl enable docker
systemctl start docker

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create qdrant user
useradd -m -s /bin/bash qdrant
usermod -aG docker qdrant

# Create directories
mkdir -p /opt/qdrant/data
mkdir -p /opt/qdrant/config
chown -R qdrant:qdrant /opt/qdrant

# Create Qdrant configuration
cat > /opt/qdrant/config/config.yaml << 'EOF'
service:
  host: 0.0.0.0
  http_port: 6333
  grpc_port: 6334
  enable_cors: true

storage:
  storage_path: /qdrant/storage
  snapshots_path: /qdrant/snapshots
  on_disk_payload: true

cluster:
  enabled: false

telemetry:
  disabled: true
EOF

# Create Docker Compose file
cat > /opt/qdrant/docker-compose.yml << 'EOF'
version: '3.8'

services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./data:/qdrant/storage
      - ./config/config.yaml:/qdrant/config/production.yaml
    environment:
      - QDRANT__SERVICE__HTTP_PORT=6333
      - QDRANT__SERVICE__GRPC_PORT=6334
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
EOF

# Set ownership
chown -R qdrant:qdrant /opt/qdrant

# Create systemd service
cat > /etc/systemd/system/qdrant.service << 'EOF'
[Unit]
Description=Qdrant Vector Database
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/qdrant
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
User=qdrant
Group=qdrant

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
systemctl daemon-reload
systemctl enable qdrant
systemctl start qdrant

# Install monitoring tools
apt-get install -y htop curl jq

# Create health check script
cat > /usr/local/bin/qdrant-health << 'EOF'
#!/bin/bash
curl -s http://localhost:6333/health | jq '.'
EOF
chmod +x /usr/local/bin/qdrant-health

# Setup log rotation
cat > /etc/logrotate.d/qdrant << 'EOF'
/opt/qdrant/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 qdrant qdrant
}
EOF

# Install fail2ban for security
apt-get install -y fail2ban

# Configure firewall
ufw allow ssh
ufw allow 6333/tcp
ufw allow 6334/tcp
ufw --force enable

echo "Qdrant setup completed successfully!"
echo "Health check: curl http://localhost:6333/health"
echo "Service status: systemctl status qdrant"

