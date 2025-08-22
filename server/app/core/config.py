"""
Core configuration module using pydantic-settings for environment variable management.
"""
import os
from typing import List, Optional, Literal, Union
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=None,  # Set dynamically below
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Server Configuration
    SERVER_HOST: str = Field(default="0.0.0.0", description="Server host")
    SERVER_PORT: int = Field(default=8000, description="Server port")
    DEBUG: bool = Field(default=True, description="Debug mode")
    LOG_LEVEL: str = Field(default="DEBUG", description="Logging level")
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = Field(
        default="development", description="Environment"
    )
    
    # Database Configuration
    DATABASE_URL: str = Field(
        default="postgresql://user:pass@localhost/db",
        description="PostgreSQL database URL with asyncpg driver"
    )
    DATABASE_POOL_SIZE: int = Field(default=10, description="Database connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, description="Database max overflow connections")
    
    # Fix CORS_ORIGINS to handle comma-separated strings from .env
    CORS_ORIGINS: Union[str, List[str]] = Field(default="", description="Allowed CORS origins")

    
    # Redis Configuration
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis URL for caching and queues")
    
    # DigitalOcean Spaces Configuration
    SPACES_ENDPOINT: str = Field(default="", description="DigitalOcean Spaces endpoint")
    SPACES_REGION: str = Field(default="", description="DigitalOcean Spaces region")
    SPACES_BUCKET: str = Field(default="", description="DigitalOcean Spaces bucket name")
    SPACES_ACCESS_KEY: str = Field(default="", description="DigitalOcean Spaces access key")
    SPACES_SECRET_KEY: str = Field(default="", description="DigitalOcean Spaces secret key")
    
    # OpenRouter Configuration
    OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API key")
    OPENROUTER_API_BASE: str = Field(
        default="https://openrouter.ai/api",
        description="OpenRouter API base URL"
    )
    OPENROUTER_EMBED_MODEL: str = Field(
        default="openai/text-embedding-3-large",
        description="Default OpenRouter embedding model"
    )
    OPENROUTER_DEFAULT_MODEL: Optional[str] = Field(
        default=None,
        description="Fallback default model if not set in database"
    )
    EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small",
        description="Embedding model identifier"
    )
    
    # Embeddings Configuration
    EMBEDDINGS_PROVIDER: Literal["openrouter", "sbert"] = Field(
        default="openrouter",
        description="Embeddings provider"
    )
    VECTOR_BACKEND: Literal["pgvector", "qdrant"] = Field(
        default="pgvector",
        description="Vector database backend"
    )
    QDRANT_URL: Optional[str] = Field(
        default=None,
        description="Qdrant URL if using qdrant backend"
    )
    
    # Authentication Configuration
    AUTH_API_KEY_SALT: str = Field(default="dev-salt", description="Salt for API key hashing")
    JWT_SECRET_KEY: str = Field(default="dev-jwt-secret", description="JWT secret key for admin sessions")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_EXPIRE_MINUTES: int = Field(default=1440, description="JWT expiration in minutes")
    SECRET_KEY: str = Field(default="dev-secret-key", description="Application secret key")
    API_KEY_PREFIX: str = Field(default="ctx_", description="Generated API key prefix")
    API_KEY_LENGTH: int = Field(default=48, description="Generated API key length")
    
    # Rate Limiting and Quotas
    DEFAULT_DAILY_QUOTA_TOKENS: int = Field(
        default=200000,
        description="Default daily token quota per API key"
    )
    RATE_LIMIT_REQUESTS: int = Field(default=60, description="Rate limit: requests allowed")
    RATE_LIMIT_WINDOW: int = Field(default=60, description="Rate limit window in seconds")
    MAX_OUTPUT_TOKENS: int = Field(
        default=4096,
        description="Maximum output tokens per request"
    )
    MAX_TEMPERATURE: float = Field(
        default=2.0,
        description="Maximum temperature allowed"
    )
    
    # Request size limits
    MAX_REQUEST_SIZE: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="Maximum request body size in bytes"
    )
    MAX_JSON_SIZE: int = Field(
        default=5 * 1024 * 1024,  # 5MB
        description="Maximum JSON payload size in bytes"
    )
    
    # Logging and Debugging
    DEBUG_LOG_PROMPTS: bool = Field(
        default=False,
        description="Whether to log raw prompts (security risk)"
    )

    ENABLE_CONTEXT_MEMORY: bool = Field(default=True, description="Enable context memory features")
    ENABLE_USAGE_ANALYTICS: bool = Field(default=True, description="Enable usage analytics recording")
    
    # Observability
    SENTRY_DSN: Optional[str] = Field(
        default=None,
        description="Sentry DSN for error tracking"
    )
    METRICS_ENABLED: bool = Field(
        default=True,
        description="Enable Prometheus metrics"
    )

    DEFAULT_TOKEN_BUDGET: int = Field(default=8000, description="Default token budget for recalls")
    MAX_CONTEXT_ITEMS: int = Field(default=50, description="Maximum number of context items")

    WORKER_PROCESSES: int = Field(default=2, description="Number of worker processes")
    JOB_TIMEOUT: int = Field(default=300, description="Job timeout in seconds")
    
    # Context Memory Configuration
    DEFAULT_WORKING_SET_TOKEN_BUDGET: int = Field(
        default=4000,
        description="Default token budget for working sets"
    )
    EMBEDDING_DIMENSION: int = Field(
        default=1536,
        description="Embedding vector dimension"
    )
    
    # Model Sync Configuration
    MODEL_SYNC_INTERVAL_HOURS: int = Field(
        default=24,
        description="Hours between automatic model catalog syncs"
    )
    MODEL_DEPRECATION_DAYS: int = Field(
        default=30,
        description="Days before unseen models are marked deprecated"
    )
    
    @field_validator("OPENROUTER_API_KEY")
    @classmethod
    def validate_openrouter_key(cls, v):
        """Validate OpenRouter API key format."""
        if v and not v.startswith("sk-or-"):
            raise ValueError("OPENROUTER_API_KEY must start with 'sk-or-'")
        if v and len(v) < 20:  # Minimum reasonable length
            raise ValueError("OPENROUTER_API_KEY appears to be too short")
        return v
    
    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v):
        """Validate JWT secret key strength."""
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters for security")
        return v
    
    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v):
        """Validate application secret key strength."""
        if len(v) < 16:
            raise ValueError("SECRET_KEY must be at least 16 characters for security")
        return v
    
    @field_validator("MAX_REQUEST_SIZE", "MAX_JSON_SIZE")
    @classmethod
    def validate_size_limits(cls, v):
        """Validate size limits are reasonable."""
        if v < 1024:  # 1KB minimum
            raise ValueError("Size limits must be at least 1KB")
        if v > 100 * 1024 * 1024:  # 100MB maximum
            raise ValueError("Size limits must not exceed 100MB")
        return v
    
    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            if not v:
                return []
            return [s.strip() for s in v.split(",") if s.strip()]
        return v if v else []

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v):
        """Ensure database URL uses postgres and allow asyncpg normalization."""
        if not (v.startswith("postgresql://") or v.startswith("postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must start with postgresql:// or postgresql+asyncpg://")
        return v

    @field_validator("REDIS_URL")
    @classmethod
    def validate_redis_url(cls, v):
        """Ensure Redis URL is properly formatted."""
        if not v.startswith("redis://"):
            raise ValueError("REDIS_URL must start with redis://")
        return v
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == "development"


# Global settings instance
def get_settings():
    env_file = ".env.test" if os.getenv("ENVIRONMENT") == "test" else ".env"
    return Settings(_env_file=env_file)

settings = get_settings()

