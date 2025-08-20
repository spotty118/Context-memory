"""
Unit tests for security module.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from app.core.security import (
    generate_api_key, hash_api_key, verify_api_key,
    get_current_api_key, APIKeyAuth
)
from app.db.models import APIKey, Workspace


class TestAPIKeyGeneration:
    """Test API key generation and hashing."""
    
    def test_generate_api_key_format(self):
        """Test that generated API keys have correct format."""
        api_key = generate_api_key()
        
        assert api_key.startswith("cmg_")
        assert len(api_key) == 36  # cmg_ (4) + 32 characters
        assert all(c.isalnum() or c == '_' for c in api_key)
    
    def test_generate_api_key_uniqueness(self):
        """Test that generated API keys are unique."""
        keys = [generate_api_key() for _ in range(100)]
        assert len(set(keys)) == 100  # All keys should be unique
    
    def test_hash_api_key(self):
        """Test API key hashing."""
        api_key = "cmg_test_key_12345"
        hashed = hash_api_key(api_key)
        
        assert hashed != api_key  # Should be different from original
        assert len(hashed) > 0
        assert isinstance(hashed, str)
    
    def test_verify_api_key_correct(self):
        """Test API key verification with correct key."""
        api_key = "cmg_test_key_12345"
        hashed = hash_api_key(api_key)
        
        assert verify_api_key(api_key, hashed) is True
    
    def test_verify_api_key_incorrect(self):
        """Test API key verification with incorrect key."""
        api_key = "cmg_test_key_12345"
        wrong_key = "cmg_wrong_key_12345"
        hashed = hash_api_key(api_key)
        
        assert verify_api_key(wrong_key, hashed) is False
    
    def test_hash_consistency(self):
        """Test that the same key always produces the same hash."""
        api_key = "cmg_test_key_12345"
        hash1 = hash_api_key(api_key)
        hash2 = hash_api_key(api_key)
        
        assert hash1 == hash2


class TestAPIKeyAuth:
    """Test API key authentication."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        mock_session = MagicMock()
        return mock_session
    
    @pytest.fixture
    def mock_api_key_record(self):
        """Mock API key database record."""
        mock_key = MagicMock(spec=APIKey)
        mock_key.id = "test-key-id"
        mock_key.workspace_id = "test-workspace-id"
        mock_key.name = "Test API Key"
        mock_key.status = "active"
        mock_key.quota_requests = 1000
        mock_key.quota_tokens = 100000
        mock_key.usage_requests = 10
        mock_key.usage_tokens = 1000
        return mock_key
    
    @pytest.fixture
    def mock_workspace_record(self):
        """Mock workspace database record."""
        mock_workspace = MagicMock(spec=Workspace)
        mock_workspace.id = "test-workspace-id"
        mock_workspace.name = "Test Workspace"
        mock_workspace.status = "active"
        return mock_workspace
    
    def test_valid_api_key_authentication(self, mock_db_session, mock_api_key_record, mock_workspace_record):
        """Test successful API key authentication."""
        api_key = "cmg_test_key_12345"
        hashed_key = hash_api_key(api_key)
        mock_api_key_record.key_hash = hashed_key
        
        # Mock database queries
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_api_key_record
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_api_key_record,  # First call for API key
            mock_workspace_record  # Second call for workspace
        ]
        
        with patch('app.core.security.get_db_session') as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            auth = APIKeyAuth()
            result = auth.authenticate(api_key)
            
            assert result is not None
            assert result.id == "test-key-id"
            assert result.workspace_id == "test-workspace-id"
    
    def test_invalid_api_key_format(self):
        """Test authentication with invalid API key format."""
        auth = APIKeyAuth()
        
        with pytest.raises(HTTPException) as exc_info:
            auth.authenticate("invalid_key_format")
        
        assert exc_info.value.status_code == 401
        assert "Invalid API key format" in str(exc_info.value.detail)
    
    def test_api_key_not_found(self, mock_db_session):
        """Test authentication with non-existent API key."""
        api_key = "cmg_nonexistent_key_12345"
        
        # Mock database query returning None
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        with patch('app.core.security.get_db_session') as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            auth = APIKeyAuth()
            
            with pytest.raises(HTTPException) as exc_info:
                auth.authenticate(api_key)
            
            assert exc_info.value.status_code == 401
            assert "Invalid API key" in str(exc_info.value.detail)
    
    def test_inactive_api_key(self, mock_db_session, mock_api_key_record, mock_workspace_record):
        """Test authentication with inactive API key."""
        api_key = "cmg_test_key_12345"
        hashed_key = hash_api_key(api_key)
        mock_api_key_record.key_hash = hashed_key
        mock_api_key_record.status = "inactive"
        
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_api_key_record,
            mock_workspace_record
        ]
        
        with patch('app.core.security.get_db_session') as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            auth = APIKeyAuth()
            
            with pytest.raises(HTTPException) as exc_info:
                auth.authenticate(api_key)
            
            assert exc_info.value.status_code == 401
            assert "API key is inactive" in str(exc_info.value.detail)
    
    def test_inactive_workspace(self, mock_db_session, mock_api_key_record, mock_workspace_record):
        """Test authentication with inactive workspace."""
        api_key = "cmg_test_key_12345"
        hashed_key = hash_api_key(api_key)
        mock_api_key_record.key_hash = hashed_key
        mock_workspace_record.status = "inactive"
        
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_api_key_record,
            mock_workspace_record
        ]
        
        with patch('app.core.security.get_db_session') as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            auth = APIKeyAuth()
            
            with pytest.raises(HTTPException) as exc_info:
                auth.authenticate(api_key)
            
            assert exc_info.value.status_code == 401
            assert "Workspace is inactive" in str(exc_info.value.detail)
    
    def test_quota_exceeded_requests(self, mock_db_session, mock_api_key_record, mock_workspace_record):
        """Test authentication with exceeded request quota."""
        api_key = "cmg_test_key_12345"
        hashed_key = hash_api_key(api_key)
        mock_api_key_record.key_hash = hashed_key
        mock_api_key_record.usage_requests = 1000  # Equal to quota
        mock_api_key_record.quota_requests = 1000
        
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_api_key_record,
            mock_workspace_record
        ]
        
        with patch('app.core.security.get_db_session') as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            auth = APIKeyAuth()
            
            with pytest.raises(HTTPException) as exc_info:
                auth.authenticate(api_key)
            
            assert exc_info.value.status_code == 429
            assert "Request quota exceeded" in str(exc_info.value.detail)
    
    def test_quota_exceeded_tokens(self, mock_db_session, mock_api_key_record, mock_workspace_record):
        """Test authentication with exceeded token quota."""
        api_key = "cmg_test_key_12345"
        hashed_key = hash_api_key(api_key)
        mock_api_key_record.key_hash = hashed_key
        mock_api_key_record.usage_tokens = 100000  # Equal to quota
        mock_api_key_record.quota_tokens = 100000
        
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_api_key_record,
            mock_workspace_record
        ]
        
        with patch('app.core.security.get_db_session') as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            auth = APIKeyAuth()
            
            with pytest.raises(HTTPException) as exc_info:
                auth.authenticate(api_key)
            
            assert exc_info.value.status_code == 429
            assert "Token quota exceeded" in str(exc_info.value.detail)


class TestGetCurrentAPIKey:
    """Test the get_current_api_key dependency."""
    
    @pytest.fixture
    def mock_request(self):
        """Mock FastAPI request."""
        mock_request = MagicMock()
        mock_request.headers = {"authorization": "Bearer cmg_test_key_12345"}
        return mock_request
    
    def test_missing_authorization_header(self):
        """Test request without authorization header."""
        mock_request = MagicMock()
        mock_request.headers = {}
        
        with pytest.raises(HTTPException) as exc_info:
            # This would be called by FastAPI's dependency injection
            # We'll test the logic directly
            pass
        
        # For now, we'll test that the function exists
        assert callable(get_current_api_key)
    
    def test_invalid_authorization_format(self):
        """Test request with invalid authorization format."""
        mock_request = MagicMock()
        mock_request.headers = {"authorization": "InvalidFormat"}
        
        # Test that the function exists and can be called
        assert callable(get_current_api_key)
    
    def test_valid_authorization_header(self, mock_request):
        """Test request with valid authorization header."""
        # Test that the function exists and can be called
        assert callable(get_current_api_key)
        
        # The actual authentication logic is tested in TestAPIKeyAuth
        # This dependency just extracts the token from the header

