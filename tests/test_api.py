"""
Integration tests for REST API endpoints
"""

import pytest
import json
from datetime import datetime


class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_check_success(self, client, mocker):
        """Test health check endpoint returns healthy status"""
        # Mock Vault client
        mocker.patch('app.vault_client.is_healthy', return_value=True)
        
        response = client.get('/health')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['status'] == 'healthy'
        assert 'vault' in data
        assert data['vault']['status'] == 'connected'
    
    def test_health_check_vault_down(self, client, mocker):
        """Test health check when Vault is down"""
        mocker.patch('app.vault_client.is_healthy', return_value=False)
        
        response = client.get('/health')
        data = json.loads(response.data)
        
        assert response.status_code == 503
        assert data['status'] == 'degraded'
        assert data['vault']['status'] == 'disconnected'


class TestGetCredentialsEndpoint:
    """Test GET /api/credentials/<service_name> endpoint"""
    
    def test_get_credentials_from_cache(self, client, mocker):
        """Test retrieving credentials from cache"""
        mock_vault = mocker.patch('app.vault_client')
        mock_cache = mocker.patch('app.credential_cache')
        
        cached_creds = {
            'api_key': 'sk_test_123',
            'status': 'active'
        }
        mock_cache.get.return_value = cached_creds
        
        response = client.get('/api/credentials/github')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['status'] == 'success'
        assert data['source'] == 'cache'
        assert data['credentials'] == cached_creds
    
    def test_get_credentials_from_vault(self, client, mocker):
        """Test retrieving credentials from Vault"""
        mock_vault = mocker.patch('app.vault_client')
        mock_cache = mocker.patch('app.credential_cache')
        
        mock_cache.get.return_value = None  # No cache hit
        
        mock_vault.get_secret.return_value = {
            'data': {
                'data': {
                    'api_key': 'sk_vault_456',
                    'status': 'active'
                },
                'metadata': {
                    'version': 1
                }
            }
        }
        
        response = client.get('/api/credentials/github')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['status'] == 'success'
        assert data['source'] == 'vault'
        assert 'api_key' in data['credentials']
    
    def test_get_credentials_include_previous_key(self, client, mocker):
        """Test including previous key in rotation grace period"""
        mock_vault = mocker.patch('app.vault_client')
        mock_cache = mocker.patch('app.credential_cache')
        
        mock_cache.get.return_value = None
        
        mock_vault.get_secret.return_value = {
            'data': {
                'data': {
                    'api_key': 'sk_new_789',
                    'previous_key': 'sk_old_123',
                    'status': 'active',
                    'grace_period_until': '2026-08-21T10:00:00Z'
                },
                'metadata': {
                    'version': 2
                }
            }
        }
        
        response = client.get('/api/credentials/github?include_previous=true')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert 'previous_key' in data['credentials']
        assert data['credentials']['previous_key'] == 'sk_old_123'
    
    def test_get_credentials_vault_error_with_fallback(self, client, mocker):
        """Test Vault error with cache fallback"""
        mock_vault = mocker.patch('app.vault_client')
        mock_cache = mocker.patch('app.credential_cache')
        mock_healing = mocker.patch('app.healing_manager')
        
        # No cache hit, Vault error
        mock_cache.get.side_effect = [None, {'api_key': 'fallback-key'}]
        mock_vault.get_secret.side_effect = Exception("Vault down")
        mock_healing.handle_vault_error.return_value = {'api_key': 'fallback-key'}
        
        response = client.get('/api/credentials/github')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['source'] == 'cache_fallback'


class TestRotateCredentialsEndpoint:
    """Test POST /api/rotate/<service_name> endpoint"""
    
    def test_rotate_credentials_success(self, client, mocker):
        """Test successful credential rotation"""
        mock_rotation = mocker.patch('app.rotation_manager')
        mock_cache = mocker.patch('app.credential_cache')
        
        mock_rotation.rotate_key.return_value = {
            'status': 'success',
            'message': 'Credential rotated',
            'new_key_active': True,
            'previous_key_active': True
        }
        
        response = client.post(
            '/api/rotate/github',
            data=json.dumps({'new_key': 'sk_new_999'}),
            content_type='application/json'
        )
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['status'] == 'success'
        mock_cache.invalidate.assert_called_once_with('github')
    
    def test_rotate_credentials_missing_new_key(self, client):
        """Test rotation with missing new_key field"""
        response = client.post(
            '/api/rotate/github',
            data=json.dumps({}),
            content_type='application/json'
        )
        data = json.loads(response.data)
        
        assert response.status_code == 400
        assert data['status'] == 'error'
        assert 'new_key' in data['message'].lower()
    
    def test_rotate_credentials_failure(self, client, mocker):
        """Test rotation failure"""
        mock_rotation = mocker.patch('app.rotation_manager')
        
        mock_rotation.rotate_key.return_value = {
            'status': 'failed',
            'error': 'Vault connection failed'
        }
        
        response = client.post(
            '/api/rotate/github',
            data=json.dumps({'new_key': 'sk_new_999'}),
            content_type='application/json'
        )
        data = json.loads(response.data)
        
        assert response.status_code == 500


class TestStatusEndpoint:
    """Test GET /api/status/<service_name> endpoint"""
    
    def test_get_status_success(self, client, mocker):
        """Test getting credential status"""
        mock_vault = mocker.patch('app.vault_client')
        mock_cache = mocker.patch('app.credential_cache')
        
        mock_vault.get_secret.return_value = {
            'data': {
                'data': {
                    'api_key': 'sk_123',
                    'status': 'active',
                    'rotation_timestamp': '2026-08-21T08:00:00Z',
                    'previous_key': None
                },
                'metadata': {
                    'version': 5
                }
            }
        }
        mock_cache.cache = {'github': {}}
        
        response = client.get('/api/status/github')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['service'] == 'github'
        assert data['version'] == 5
        assert data['status'] == 'active'
        assert data['cached'] is True


class TestCacheStatsEndpoint:
    """Test GET /api/cache/stats endpoint"""
    
    def test_cache_stats_success(self, client, mocker):
        """Test getting cache statistics"""
        mock_cache = mocker.patch('app.credential_cache')
        mock_rotation = mocker.patch('app.rotation_manager')
        
        mock_cache.get_stats.return_value = {
            'total_entries': 5,
            'ttl_seconds': 3600,
            'entries': ['github', 'slack', 'stripe', 'api1', 'api2']
        }
        mock_rotation.rotation_history = {}
        
        response = client.get('/api/cache/stats')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['cache']['total_entries'] == 5


class TestCacheClearEndpoint:
    """Test POST /api/cache/clear endpoint"""
    
    def test_cache_clear_success(self, client, mocker):
        """Test clearing cache"""
        mock_cache = mocker.patch('app.credential_cache')
        
        response = client.post('/api/cache/clear')
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data['status'] == 'success'
        mock_cache.clear_all.assert_called_once()


class TestErrorHandling:
    """Test error handling"""
    
    def test_404_endpoint_not_found(self, client):
        """Test 404 error for non-existent endpoint"""
        response = client.get('/api/nonexistent')
        data = json.loads(response.data)
        
        assert response.status_code == 404
        assert data['status'] == 'error'
        assert 'not found' in data['message'].lower()
