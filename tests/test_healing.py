"""
Unit tests for SelfHealingManager
"""

import pytest
from app import SelfHealingManager


class TestSelfHealingManager:
    """Test suite for SelfHealingManager class"""
    
    def test_healing_manager_initialization(self, healing_manager):
        """Test healing manager is initialized correctly"""
        assert healing_manager.max_retries == 3
        assert healing_manager.retry_attempts == {}
    
    def test_handle_vault_error_with_cache_fallback(self, healing_manager, cache):
        """Test error handling with cache fallback"""
        # Set cached value
        cache.set('github', {'api_key': 'cached-key-123'})
        
        # Simulate Vault error
        error = Exception("Vault connection failed")
        result = healing_manager.handle_vault_error('github', error)
        
        # Should return cached value
        assert result is not None
        assert result['api_key'] == 'cached-key-123'
    
    def test_handle_vault_error_no_cache(self, healing_manager):
        """Test error handling when no cache available"""
        error = Exception("Vault connection failed")
        
        # First attempt
        result = healing_manager.handle_vault_error('github', error)
        assert result is None
        assert healing_manager.retry_attempts['github'] == 1
        
        # Second attempt
        result = healing_manager.handle_vault_error('github', error)
        assert result is None
        assert healing_manager.retry_attempts['github'] == 2
    
    def test_max_retries_exceeded(self, healing_manager):
        """Test max retries exceeded exception"""
        error = Exception("Vault error")
        
        # Simulate max retries
        healing_manager.retry_attempts['github'] = 3
        healing_manager.max_retries = 3
        
        with pytest.raises(Exception) as exc_info:
            healing_manager.handle_vault_error('github', error)
        
        assert 'Max retries exceeded' in str(exc_info.value)
    
    def test_reset_retries(self, healing_manager):
        """Test resetting retry counter after successful operation"""
        healing_manager.retry_attempts['github'] = 2
        
        healing_manager.reset_retries('github')
        
        assert healing_manager.retry_attempts['github'] == 0
    
    def test_exponential_backoff_delay(self, healing_manager):
        """Test exponential backoff calculation"""
        error = Exception("Vault error")
        
        # First attempt
        healing_manager.handle_vault_error('service1', error)
        assert healing_manager.retry_attempts['service1'] == 1
        
        # Second attempt
        healing_manager.handle_vault_error('service1', error)
        assert healing_manager.retry_attempts['service1'] == 2
        # Backoff should be 2^2 = 4 seconds
        
        # Third attempt
        healing_manager.handle_vault_error('service1', error)
        assert healing_manager.retry_attempts['service1'] == 3
        # Backoff should be 2^3 = 8 seconds
    
    def test_different_services_tracked_separately(self, healing_manager, cache):
        """Test that different services have separate retry counters"""
        cache.set('github', {'api_key': 'github-key'})
        cache.set('slack', {'api_key': 'slack-key'})
        
        error1 = Exception("Error 1")
        error2 = Exception("Error 2")
        
        healing_manager.handle_vault_error('github', error1)
        healing_manager.handle_vault_error('slack', error2)
        
        assert healing_manager.retry_attempts['github'] == 1
        assert healing_manager.retry_attempts['slack'] == 1
