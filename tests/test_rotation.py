"""
Unit tests for DualKeyRotationManager
"""

import pytest
from datetime import datetime
from app import DualKeyRotationManager


class TestDualKeyRotationManager:
    """Test suite for DualKeyRotationManager class"""
    
    def test_rotation_manager_initialization(self, rotation_manager):
        """Test rotation manager is initialized correctly"""
        assert rotation_manager.grace_period == 600
        assert rotation_manager.rotation_history == {}
    
    def test_rotate_key_success(self, rotation_manager, mock_vault_client, cache):
        """Test successful key rotation"""
        new_key = 'sk_new_123456789'
        secret_path = 'api-keys/github'
        
        result = rotation_manager.rotate_key(secret_path, {'api_key': new_key})
        
        assert result['status'] == 'success'
        assert result['new_key_active'] is True
        assert result['previous_key_active'] is True
        assert result['grace_period_seconds'] == 600
    
    def test_rotate_key_updates_history(self, rotation_manager, mock_vault_client):
        """Test rotation history is recorded"""
        secret_path = 'api-keys/github'
        new_key = 'sk_new_123456789'
        
        rotation_manager.rotate_key(secret_path, {'api_key': new_key})
        
        assert secret_path in rotation_manager.rotation_history
        assert rotation_manager.rotation_history[secret_path]['new_key'] == new_key
    
    def test_rotate_key_invalidates_cache(self, rotation_manager, mock_vault_client, cache):
        """Test cache is invalidated after rotation"""
        cache.set('github', {'api_key': 'old-key'})
        assert cache.get('github') is not None
        
        secret_path = 'api-keys/github'
        rotation_manager.rotate_key(secret_path, {'api_key': 'new-key'})
        
        # Cache should be invalidated (but we need to check service name extraction)
        # In this case, the service is extracted from the path
        service_name = secret_path.split('/')[-1]
        assert cache.get(service_name) is None
    
    def test_rotate_key_failure(self, rotation_manager, mock_vault_client):
        """Test rotation failure handling"""
        mock_vault_client.get_secret.side_effect = Exception("Vault connection failed")
        
        result = rotation_manager.rotate_key('api-keys/github', {'api_key': 'new-key'})
        
        assert result['status'] == 'failed'
        assert 'error' in result
    
    def test_finalize_rotation_success(self, rotation_manager, mock_vault_client):
        """Test finalizing rotation after grace period"""
        secret_path = 'api-keys/github'
        
        result = rotation_manager.finalize_rotation(secret_path)
        
        assert result['status'] == 'success'
        assert 'old key removed' in result['message'].lower()
    
    def test_finalize_rotation_failure(self, rotation_manager, mock_vault_client):
        """Test finalize rotation failure"""
        mock_vault_client.get_secret.side_effect = Exception("Vault error")
        
        result = rotation_manager.finalize_rotation('api-keys/github')
        
        assert result['status'] == 'failed'
        assert 'error' in result
    
    def test_grace_period_stored(self, rotation_manager, mock_vault_client):
        """Test grace period is stored in rotation result"""
        result = rotation_manager.rotate_key('api-keys/github', {'api_key': 'new-key'})
        
        assert 'grace_period_until' in result
        # Grace period should be in future
        grace_time = datetime.fromisoformat(result['grace_period_until'])
        assert grace_time > datetime.now()
