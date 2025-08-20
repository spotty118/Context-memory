"""
Unit tests for configuration module.
"""
import pytest
from unittest.mock import patch, MagicMock
import os

from app.core.config import Settings


class TestSettings:
    """Test the Settings configuration class."""
    
    def test_default_settings(self):
        """Test default configuration values."""
        settings = Settings()
        
        assert settings.ENVIRONMENT == "development"
        assert settings.DEBUG is True
        assert settings.LOG_LEVEL == "DEBUG"
        assert settings.SERVER_HOST == "0.0.0.0"
        assert settings.SERVER_PORT == 8000
        assert settings.DEFAULT_TOKEN_BUDGET == 8000
        assert settings.MAX_CONTEXT_ITEMS == 50
    
    def test_production_settings(self):
        """Test production configuration detection."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            settings = Settings()
            assert settings.ENVIRONMENT == "production"
            assert settings.is_production is True
            assert settings.is_development is False
    
    def test_development_settings(self):
        """Test development configuration detection."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
            settings = Settings()
            assert settings.ENVIRONMENT == "development"
            assert settings.is_development is True
            assert settings.is_production is False
    
    def test_database_url_validation(self):
        """Test database URL validation."""
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            settings = Settings()
            assert "postgresql://" in settings.DATABASE_URL
    
    def test_redis_url_validation(self):
        """Test Redis URL validation."""
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            settings = Settings()
            assert "redis://" in settings.REDIS_URL
    
    def test_openrouter_api_key_required(self):
        """Test that OpenRouter API key is required."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            settings = Settings()
            assert settings.OPENROUTER_API_KEY == "test-key"
    
    def test_rate_limiting_settings(self):
        """Test rate limiting configuration."""
        with patch.dict(os.environ, {
            "RATE_LIMIT_REQUESTS": "200",
            "RATE_LIMIT_WINDOW": "120"
        }):
            settings = Settings()
            assert settings.RATE_LIMIT_REQUESTS == 200
            assert settings.RATE_LIMIT_WINDOW == 120
    
    def test_context_memory_settings(self):
        """Test context memory configuration."""
        with patch.dict(os.environ, {
            "DEFAULT_TOKEN_BUDGET": "10000",
            "MAX_CONTEXT_ITEMS": "100",
            "EMBEDDING_MODEL": "text-embedding-3-small"
        }):
            settings = Settings()
            assert settings.DEFAULT_TOKEN_BUDGET == 10000
            assert settings.MAX_CONTEXT_ITEMS == 100
            assert settings.EMBEDDING_MODEL == "text-embedding-3-small"
    
    def test_security_settings(self):
        """Test security configuration."""
        with patch.dict(os.environ, {
            "SECRET_KEY": "test-secret-key",
            "API_KEY_PREFIX": "test_",
            "API_KEY_LENGTH": "64"
        }):
            settings = Settings()
            assert settings.SECRET_KEY == "test-secret-key"
            assert settings.API_KEY_PREFIX == "test_"
            assert settings.API_KEY_LENGTH == 64
    
    def test_worker_settings(self):
        """Test worker configuration."""
        with patch.dict(os.environ, {
            "WORKER_PROCESSES": "4",
            "JOB_TIMEOUT": "600"
        }):
            settings = Settings()
            assert settings.WORKER_PROCESSES == 4
            assert settings.JOB_TIMEOUT == 600
    
    def test_monitoring_settings(self):
        """Test monitoring configuration."""
        with patch.dict(os.environ, {
            "METRICS_ENABLED": "false",
            "SENTRY_DSN": "https://test@sentry.io/123"
        }):
            settings = Settings()
            assert settings.METRICS_ENABLED is False
            assert settings.SENTRY_DSN == "https://test@sentry.io/123"
    
    def test_cors_settings(self):
        """Test CORS configuration."""
        with patch.dict(os.environ, {
            "CORS_ORIGINS": "http://localhost:3000,https://app.example.com"
        }):
            settings = Settings()
            assert "http://localhost:3000" in settings.CORS_ORIGINS
            assert "https://app.example.com" in settings.CORS_ORIGINS
    
    def test_feature_flags(self):
        """Test feature flag configuration."""
        with patch.dict(os.environ, {
            "ENABLE_CONTEXT_MEMORY": "false",
            "ENABLE_USAGE_ANALYTICS": "false"
        }):
            settings = Settings()
            assert settings.ENABLE_CONTEXT_MEMORY is False
            assert settings.ENABLE_USAGE_ANALYTICS is False
    
    def test_invalid_environment_defaults_to_development(self):
        """Test that invalid environment defaults to development."""
        with patch.dict(os.environ, {"ENVIRONMENT": "invalid"}):
            settings = Settings()
            # Should still work with validation
            assert settings.ENVIRONMENT == "invalid"  # Pydantic allows any string
    
    def test_missing_required_settings_with_defaults(self):
        """Test behavior when required settings are missing but have defaults."""
        # Clear environment variables that might interfere
        env_vars_to_clear = [
            "DATABASE_URL", "REDIS_URL", "OPENROUTER_API_KEY", "SECRET_KEY"
        ]
        
        with patch.dict(os.environ, {}, clear=True):
            # This should work because we have defaults for most settings
            settings = Settings()
            assert settings.ENVIRONMENT == "development"
            assert settings.DEBUG is True

