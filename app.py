"""
Self-Healing API Vault - Flask Application
Main entry point for the zero-downtime credential rotation system
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
import hvac
import os
from dotenv import load_dotenv
import threading
import logging
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
app.config['VAULT_ADDR'] = os.getenv('VAULT_ADDR', 'http://localhost:8200')
app.config['VAULT_TOKEN'] = os.getenv('VAULT_TOKEN', '')
app.config['CACHE_TTL'] = int(os.getenv('CACHE_TTL', 3600))  # 1 hour default
app.config['ROTATION_INTERVAL'] = int(os.getenv('ROTATION_INTERVAL', 1800))  # 30 mins
app.config['GRACE_PERIOD'] = int(os.getenv('GRACE_PERIOD', 600))  # 10 mins


# ==================== VAULT CLIENT ====================
class VaultClient:
    """
    Handles all communication with HashiCorp Vault
    """
    def __init__(self, vault_addr, vault_token):
        self.vault_addr = vault_addr
        self.vault_token = vault_token
        self.client = hvac.Client(url=vault_addr, token=vault_token)
        logger.info(f"VaultClient initialized with address: {vault_addr}")
    
    def is_healthy(self):
        """Check if Vault is accessible and unsealed"""
        try:
            sealed_status = self.client.sys.is_sealed()
            return not sealed_status
        except Exception as e:
            logger.error(f"Vault health check failed: {e}")
            return False
    
    def get_secret(self, secret_path):
        """
        Fetch secret from Vault using KV v2 secrets engine
        
        Args:
            secret_path: Path to secret (e.g., 'api-keys/github')
        
        Returns:
            Dict containing secret data and metadata
        """
        try:
            response = self.client.secrets.kv.v2.read_data(path=secret_path)
            logger.info(f"Successfully retrieved secret: {secret_path}")
            return response
        except Exception as e:
            logger.error(f"Failed to retrieve secret {secret_path}: {e}")
            raise
    
    def rotate_secret(self, secret_path, secret_dict):
        """
        Create or update secret in Vault with new data
        
        Args:
            secret_path: Path to secret
            secret_dict: Dictionary containing secret data
        
        Returns:
            Response from Vault
        """
        try:
            response = self.client.secrets.kv.v2.create_or_update_secret(
                path=secret_path,
                secret_dict=secret_dict
            )
            logger.info(f"Successfully rotated secret: {secret_path}")
            return response
        except Exception as e:
            logger.error(f"Failed to rotate secret {secret_path}: {e}")
            raise
    
    def list_secrets(self, secret_path):
        """List all secrets at a given path"""
        try:
            response = self.client.secrets.kv.v2.list_secrets(path=secret_path)
            return response
        except Exception as e:
            logger.error(f"Failed to list secrets at {secret_path}: {e}")
            raise


# ==================== TTL CACHE LAYER ====================
class CredentialCache:
    """
    In-memory cache for credentials with TTL (Time-To-Live)
    Reduces load on Vault and improves response times
    Thread-safe using locks
    """
    def __init__(self, ttl_seconds=3600):
        self.cache = {}
        self.ttl = ttl_seconds
        self.lock = threading.Lock()
        logger.info(f"CredentialCache initialized with TTL: {ttl_seconds}s")
    
    def get(self, key):
        """
        Retrieve cached credential if not expired
        
        Args:
            key: Service name or credential key
        
        Returns:
            Cached value if valid, None if expired or not found
        """
        with self.lock:
            if key not in self.cache:
                return None
            
            entry = self.cache[key]
            if datetime.now() > entry['expires_at']:
                logger.info(f"Cache expired for key: {key}")
                del self.cache[key]
                return None
            
            logger.debug(f"Cache hit for key: {key}")
            return entry['value']
    
    def set(self, key, value):
        """
        Store credential with TTL expiration
        
        Args:
            key: Service name or credential key
            value: Credential data to cache
        """
        with self.lock:
            self.cache[key] = {
                'value': value,
                'expires_at': datetime.now() + timedelta(seconds=self.ttl),
                'created_at': datetime.now()
            }
            logger.debug(f"Cached credential for key: {key}, expires in {self.ttl}s")
    
    def is_expired(self, key):
        """Check if credential is expired"""
        with self.lock:
            if key not in self.cache:
                return True
            return datetime.now() > self.cache[key]['expires_at']
    
    def invalidate(self, key):
        """Manually invalidate cache entry"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                logger.info(f"Invalidated cache for key: {key}")
    
    def clear_all(self):
        """Clear entire cache"""
        with self.lock:
            self.cache.clear()
            logger.info("Cache cleared")
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            return {
                'total_entries': len(self.cache),
                'ttl_seconds': self.ttl,
                'entries': list(self.cache.keys())
            }


# ==================== DUAL-KEY ROTATION MANAGER ====================
class DualKeyRotationManager:
    """
    Implements zero-downtime credential rotation using dual-key pattern
    
    Process:
    1. Generate new key
    2. Store both current and new key in Vault
    3. Allow grace period for clients to switch
    4. Deactivate old key
    """
    def __init__(self, vault_client, cache, grace_period_seconds=600):
        self.vault_client = vault_client
        self.cache = cache
        self.grace_period = grace_period_seconds
        self.rotation_history = {}
        logger.info(f"DualKeyRotationManager initialized with grace period: {grace_period_seconds}s")
    
    def rotate_key(self, secret_path, new_key_value):
        """
        Execute dual-key rotation cycle
        
        Args:
            secret_path: Path in Vault to the secret
            new_key_value: The new API key/credential
        
        Returns:
            Dict with rotation status and details
        """
        try:
            logger.info(f"Starting rotation for: {secret_path}")
            
            # Step 1: Fetch current secret
            current = self.vault_client.get_secret(secret_path)
            current_data = current['data']['data']
            old_key = current_data.get('api_key')
            version = current['data']['metadata']['version']
            
            # Step 2: Prepare dual-key payload
            dual_key_payload = {
                'api_key': new_key_value,           # Current/active key
                'previous_key': old_key,             # Old key (for grace period)
                'rotation_timestamp': datetime.now().isoformat(),
                'status': 'active',
                'version': version + 1,
                'grace_period_until': (
                    datetime.now() + timedelta(seconds=self.grace_period)
                ).isoformat()
            }
            
            # Step 3: Store in Vault
            self.vault_client.rotate_secret(secret_path, dual_key_payload)
            
            # Step 4: Invalidate cache to force refresh
            service_name = secret_path.split('/')[-1]
            self.cache.invalidate(service_name)
            
            # Step 5: Record rotation in history
            self.rotation_history[secret_path] = {
                'timestamp': datetime.now(),
                'new_key': new_key_value,
                'old_key': old_key,
                'grace_period': self.grace_period
            }
            
            logger.info(f"Successfully rotated: {secret_path}")
            
            return {
                'status': 'success',
                'message': 'Credential rotated with dual-key overlap',
                'secret_path': secret_path,
                'new_key_active': True,
                'previous_key_active': True,
                'grace_period_seconds': self.grace_period,
                'grace_period_until': dual_key_payload['grace_period_until']
            }
        
        except Exception as e:
            logger.error(f"Rotation failed for {secret_path}: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'secret_path': secret_path
            }
    
    def finalize_rotation(self, secret_path):
        """
        Finalize rotation after grace period
        Remove old key from dual-key setup
        """
        try:
            logger.info(f"Finalizing rotation for: {secret_path}")
            
            current = self.vault_client.get_secret(secret_path)
            current_data = current['data']['data']
            
            # Remove previous_key, keep only current key
            finalized_payload = {
                'api_key': current_data['api_key'],
                'rotation_timestamp': current_data.get('rotation_timestamp'),
                'status': 'stable',
                'version': current['data']['metadata']['version'] + 1
            }
            
            self.vault_client.rotate_secret(secret_path, finalized_payload)
            
            logger.info(f"Rotation finalized for: {secret_path}")
            
            return {'status': 'success', 'message': 'Old key removed, rotation complete'}
        
        except Exception as e:
            logger.error(f"Finalization failed for {secret_path}: {e}")
            return {'status': 'failed', 'error': str(e)}


# ==================== SELF-HEALING MANAGER ====================
class SelfHealingManager:
    """
    Handles errors and implements self-healing logic
    - Retry with exponential backoff
    - Fallback to cached values
    - Automatic recovery
    """
    def __init__(self, vault_client, cache):
        self.vault_client = vault_client
        self.cache = cache
        self.retry_attempts = {}
        self.max_retries = 3
        logger.info("SelfHealingManager initialized")
    
    def handle_vault_error(self, service_name, error):
        """
        Handle Vault connectivity errors with self-healing
        
        Args:
            service_name: Name of the service
            error: The exception that occurred
        
        Returns:
            Cached value if available, raises if no fallback exists
        """
        if service_name not in self.retry_attempts:
            self.retry_attempts[service_name] = 0
        
        self.retry_attempts[service_name] += 1
        
        logger.warning(
            f"Vault error for {service_name} "
            f"(attempt {self.retry_attempts[service_name]}/{self.max_retries}): {error}"
        )
        
        # Try cached value as fallback
        cached = self.cache.get(service_name)
        if cached:
            logger.info(f"Using stale cache for {service_name} (self-healing)")
            return cached
        
        # Check if we can retry
        if self.retry_attempts[service_name] < self.max_retries:
            delay = 2 ** self.retry_attempts[service_name]  # Exponential backoff
            logger.info(f"Will retry {service_name} in {delay}s")
            return None
        else:
            logger.error(f"Max retries exceeded for {service_name}")
            self.retry_attempts[service_name] = 0
            raise Exception(
                f"Self-healing failed for {service_name}: "
                f"Max retries exceeded and no cached value available"
            )
    
    def reset_retries(self, service_name):
        """Reset retry counter after successful operation"""
        self.retry_attempts[service_name] = 0
        logger.debug(f"Reset retry counter for {service_name}")


# ==================== INITIALIZE MANAGERS ====================
vault_client = VaultClient(app.config['VAULT_ADDR'], app.config['VAULT_TOKEN'])
credential_cache = CredentialCache(app.config['CACHE_TTL'])
rotation_manager = DualKeyRotationManager(vault_client, credential_cache, app.config['GRACE_PERIOD'])
healing_manager = SelfHealingManager(vault_client, credential_cache)

app.config['vault_client'] = vault_client
app.config['cache'] = credential_cache
app.config['rotation_manager'] = rotation_manager
app.config['healing_manager'] = healing_manager


# ==================== BACKGROUND SCHEDULER ====================
scheduler = BackgroundScheduler()

def auto_rotate_credentials():
    """
    Background job: Auto-rotate configured credentials
    Runs at intervals defined by ROTATION_INTERVAL
    """
    services = os.getenv('SERVICES_TO_ROTATE', 'github,slack,stripe').split(',')
    
    for service in services:
        service = service.strip()
        try:
            # In production, new keys would be generated from the actual API
            # For now, this is a placeholder that would call the service's API
            logger.info(f"Auto-rotating credentials for: {service}")
            
            # Example: generate_new_key_from_service(service)
            # Then call: rotation_manager.rotate_key(path, new_key)
        
        except Exception as e:
            logger.error(f"Auto-rotation failed for {service}: {e}")

def health_check():
    """
    Background job: Monitor Vault health and cache status
    Triggers healing if issues detected
    """
    try:
        if vault_client.is_healthy():
            logger.debug("Vault health check passed")
        else:
            logger.warning("Vault appears to be sealed or unreachable")
    except Exception as e:
        logger.error(f"Health check failed: {e}")

# Schedule background jobs
scheduler.add_job(
    func=auto_rotate_credentials,
    trigger="interval",
    seconds=app.config['ROTATION_INTERVAL'],
    id='auto_rotate_job'
)

scheduler.add_job(
    func=health_check,
    trigger="interval",
    seconds=60,
    id='health_check_job'
)

scheduler.start()

# Shutdown scheduler on app exit
atexit.register(lambda: scheduler.shutdown())


# ==================== REST API ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint - verify app and Vault status"""
    vault_healthy = vault_client.is_healthy()
    
    return jsonify({
        'status': 'healthy' if vault_healthy else 'degraded',
        'timestamp': datetime.now().isoformat(),
        'vault': {
            'status': 'connected' if vault_healthy else 'disconnected',
            'address': app.config['VAULT_ADDR']
        },
        'cache': credential_cache.get_stats()
    }), 200 if vault_healthy else 503


@app.route('/api/credentials/<service_name>', methods=['GET'])
def get_credential(service_name):
    """
    Fetch API key/credentials for a service
    
    Returns both current and previous key if in rotation grace period
    Implements TTL caching for performance
    
    Query params:
        - include_previous: bool (default: true) - include old key
    
    Response:
        - status: success/error
        - source: cache/vault
        - credentials: dict with api_key and optional previous_key
    """
    try:
        cache = app.config['cache']
        include_previous = request.args.get('include_previous', 'true').lower() == 'true'
        
        # Check cache first
        cached = cache.get(service_name)
        if cached:
            logger.info(f"Serving {service_name} from cache")
            return jsonify({
                'status': 'success',
                'source': 'cache',
                'service': service_name,
                'credentials': cached if include_previous else {'api_key': cached.get('api_key')},
                'cached_at': cached.get('created_at')
            }), 200
        
        # Fetch from Vault
        try:
            secret_path = f"api-keys/{service_name}"
            secret = app.config['vault_client'].get_secret(secret_path)
            
            credentials = {
                'api_key': secret['data']['data']['api_key'],
                'status': secret['data']['data'].get('status', 'active'),
                'version': secret['data']['metadata']['version']
            }
            
            # Include previous key if in grace period
            if include_previous and secret['data']['data'].get('previous_key'):
                credentials['previous_key'] = secret['data']['data']['previous_key']
                credentials['grace_period_until'] = secret['data']['data'].get('grace_period_until')
            
            # Cache the credentials
            cache.set(service_name, credentials)
            
            # Reset retry counter on success
            app.config['healing_manager'].reset_retries(service_name)
            
            return jsonify({
                'status': 'success',
                'source': 'vault',
                'service': service_name,
                'credentials': credentials
            }), 200
        
        except Exception as vault_error:
            # Try self-healing
            cached = app.config['healing_manager'].handle_vault_error(service_name, vault_error)
            if cached:
                return jsonify({
                    'status': 'success',
                    'source': 'cache_fallback',
                    'service': service_name,
                    'warning': 'Using cached credentials (Vault unavailable)',
                    'credentials': cached
                }), 200
            raise
    
    except Exception as e:
        logger.error(f"Failed to get credentials for {service_name}: {e}")
        return jsonify({
            'status': 'error',
            'service': service_name,
            'message': str(e)
        }), 500


@app.route('/api/rotate/<service_name>', methods=['POST'])
def rotate_credential(service_name):
    """
    Trigger manual credential rotation
    
    Request body:
        {
            "new_key": "new_api_key_value"
        }
    
    Initiates dual-key rotation cycle for zero-downtime transition
    """
    try:
        data = request.get_json()
        new_key = data.get('new_key')
        
        if not new_key:
            return jsonify({
                'status': 'error',
                'message': 'Missing required field: new_key'
            }), 400
        
        rotation_mgr = app.config['rotation_manager']
        result = rotation_mgr.rotate_key(f"api-keys/{service_name}", {'api_key': new_key})
        
        # Invalidate cache
        app.config['cache'].invalidate(service_name)
        
        status_code = 200 if result['status'] == 'success' else 500
        return jsonify(result), status_code
    
    except Exception as e:
        logger.error(f"Failed to rotate {service_name}: {e}")
        return jsonify({
            'status': 'error',
            'service': service_name,
            'message': str(e)
        }), 500


@app.route('/api/status/<service_name>', methods=['GET'])
def credential_status(service_name):
    """
    Get rotation status of a credential
    
    Returns:
        - version: current secret version
        - status: active/stable
        - rotation_timestamp: when last rotated
        - grace_period_until: when old key will be removed (if in rotation)
        - cached: whether credential is cached
    """
    try:
        secret = app.config['vault_client'].get_secret(f"api-keys/{service_name}")
        secret_data = secret['data']['data']
        
        return jsonify({
            'service': service_name,
            'version': secret['data']['metadata']['version'],
            'rotation_timestamp': secret_data.get('rotation_timestamp'),
            'status': secret_data.get('status', 'active'),
            'has_previous_key': 'previous_key' in secret_data,
            'grace_period_until': secret_data.get('grace_period_until'),
            'cached': service_name in app.config['cache'].cache
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to get status for {service_name}: {e}")
        return jsonify({
            'status': 'error',
            'service': service_name,
            'message': str(e)
        }), 500


@app.route('/api/cache/stats', methods=['GET'])
def cache_stats():
    """Get cache statistics and current entries"""
    return jsonify({
        'cache': app.config['cache'].get_stats(),
        'rotation_history': {
            k: {
                'timestamp': v['timestamp'].isoformat(),
                'grace_period': v['grace_period']
            } for k, v in app.config['rotation_manager'].rotation_history.items()
        }
    }), 200


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """Manually clear all cached credentials"""
    app.config['cache'].clear_all()
    return jsonify({'status': 'success', 'message': 'Cache cleared'}), 200


# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'status': 'error',
        'message': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'status': 'error',
        'message': 'Internal server error'
    }), 500


# ==================== ENTRY POINT ====================

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("Starting Self-Healing API Vault")
    logger.info(f"Vault Address: {app.config['VAULT_ADDR']}")
    logger.info(f"Cache TTL: {app.config['CACHE_TTL']}s")
    logger.info(f"Rotation Interval: {app.config['ROTATION_INTERVAL']}s")
    logger.info("=" * 50)
    
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', 5000)),
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    )
