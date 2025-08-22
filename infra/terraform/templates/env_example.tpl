# Environment Configuration Example
# Copy this file to .env and fill in your actual values

# Server Configuration
SERVER_PORT=${server_port}
ENVIRONMENT=${environment}
DEBUG=false

# Database Configuration
DATABASE_URL=${database_url}
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# Redis Configuration
REDIS_URL=${redis_url}

# DigitalOcean Spaces Configuration
SPACES_ENDPOINT=${spaces_endpoint}
SPACES_REGION=${spaces_region}
SPACES_BUCKET=${spaces_bucket}
SPACES_ACCESS_KEY=your_spaces_access_key
SPACES_SECRET_KEY=your_spaces_secret_key

# OpenRouter Configuration
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_BASE=${openrouter_base}
OPENROUTER_EMBED_MODEL=openai/text-embedding-3-large

# Embeddings Configuration
EMBEDDINGS_PROVIDER=${embeddings_provider}
VECTOR_BACKEND=${vector_backend}
QDRANT_URL=http://localhost:6333

# Authentication Configuration
AUTH_API_KEY_SALT=your_random_salt_here
JWT_SECRET_KEY=your_jwt_secret_key_here
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# Rate Limiting and Quotas
DEFAULT_DAILY_QUOTA_TOKENS=${default_daily_quota}
RATE_LIMIT_RPM=${rate_limit_rpm}
MAX_OUTPUT_TOKENS=4096
MAX_TEMPERATURE=2.0

# Logging and Debugging
DEBUG_LOG_PROMPTS=${debug_log_prompts}
LOG_LEVEL=${log_level}

# Observability
SENTRY_DSN=your_sentry_dsn_here
METRICS_ENABLED=${metrics_enabled}

# Context Memory Configuration
DEFAULT_WORKING_SET_TOKEN_BUDGET=4000
EMBEDDING_DIMENSION=1536

# Model Sync Configuration
MODEL_SYNC_INTERVAL_HOURS=24
MODEL_DEPRECATION_DAYS=30

# Development Notes:
# - Use 'postgresql+asyncpg://' for async database connections
# - Redis URL format: 'redis://localhost:6379' or 'redis://:password@host:port'
# - Generate secure random values for AUTH_API_KEY_SALT and JWT_SECRET_KEY
# - Set DEBUG_LOG_PROMPTS=true only in development (security risk in production)
# - Use environment-specific values for each deployment

