"""
Configuration management for Self-Healing API Vault
Handles environment variables, defaults, and environment-specific configs
"""

import os
from dotenv import load_dotenv
from datetime import timedelta

# Load environment variables
load_dotenv()


class Config:
    """Base configuration"""
    
    # Flask
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Server
    HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    PORT = int(os.getenv('FLASK_PORT', 5000))
    ENVIRONMENT = os.getenv('FLASK_ENV', 'production')
    
    # Vault Configuration
    VAULT_ADDR = os.getenv('VAULT_ADDR', 'http://localhost:8200')
    VAULT_TOKEN = os.getenv('VAULT_TOKEN', '')
    VAULT_NAMESPACE = os.getenv('VAULT_NAMESPACE', '')
    VAULT_KV_PATH = os.getenv('VAULT_KV_PATH', 'secret')
    VAULT_HEALTH_CHECK_TIMEOUT = int(os.getenv('VAULT_HEALTH_CHECK_TIMEOUT', 10))
    MOCK_VAULT = os.getenv('MOCK_VAULT', 'False').lower() == 'true'
    
    # Cache Configuration (in seconds)
    CACHE_TTL = int(os.getenv('CACHE_TTL', 3600))  # 1 hour
    CACHE_MAX_SIZE = int(os.getenv('CACHE_MAX_SIZE', 1000))
    
    # Rotation Configuration (in seconds)
    ROTATION_INTERVAL = int(os.getenv('ROTATION_INTERVAL', 1800))  # 30 minutes
    GRACE_PERIOD = int(os.getenv('GRACE_PERIOD', 600))  # 10 minutes
    
    # Services to Auto-Rotate
    SERVICES_TO_ROTATE = os.getenv('SERVICES_TO_ROTATE', 'github,slack,stripe').split(',')
    SERVICES_TO_ROTATE = [s.strip() for s in SERVICES_TO_ROTATE]
    
    # Logging Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = os.getenv('LOG_FORMAT', 'json')
    LOG_FILE = os.getenv('LOG_FILE', 'logs/vault-api.log')
    
    # Retry Configuration
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    RETRY_BACKOFF_BASE = int(os.getenv('RETRY_BACKOFF_BASE', 2))
    
    # Health Check Configuration
    HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', 60))  # 60 seconds
    
    # Security
    JWT_SECRET = os.getenv('JWT_SECRET', 'dev-jwt-secret-change-in-production')
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRATION = timedelta(hours=1)
    
    # API Rate Limiting
    RATE_LIMIT_ENABLED = os.getenv('RATE_LIMIT_ENABLED', 'False').lower() == 'true'
    RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', 100))
    RATE_LIMIT_PERIOD = int(os.getenv('RATE_LIMIT_PERIOD', 60))  # 60 seconds
    
    # Database Configuration (for audit logging)
    DATABASE_URL = os.getenv(
        'DATABASE_URL',
        'sqlite:///vault_audit.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # Redis Configuration (optional)
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    USE_REDIS = os.getenv('USE_REDIS', 'False').lower() == 'true'
    
    # APScheduler Configuration
    SCHEDULER_TIMEZONE = os.getenv('SCHEDULER_TIMEZONE', 'UTC')
    SCHEDULER_JOB_DEFAULTS_COALESCE = os.getenv('SCHEDULER_JOB_DEFAULTS_COALESCE', 'True').lower() == 'true'
    SCHEDULER_JOB_DEFAULTS_MAX_INSTANCES = int(os.getenv('SCHEDULER_JOB_DEFAULTS_MAX_INSTANCES', 1))
    
    # Alert/Notification Configuration
    ALERT_SLACK_WEBHOOK = os.getenv('ALERT_SLACK_WEBHOOK', '')
    ALERT_EMAIL = os.getenv('ALERT_EMAIL', '')
    SEND_ALERTS = bool(ALERT_SLACK_WEBHOOK or ALERT_EMAIL)
    
    # CORS Configuration
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
    CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS]
    CORS_ALLOW_HEADERS = ['Content-Type', 'Authorization']
    CORS_ALLOW_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']
    
    # Security Headers
    SECURE_HEADERS_ENABLED = os.getenv('SECURE_HEADERS_ENABLED', 'True').lower() == 'true'
    SECURITY_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'
    }


class DevelopmentConfig(Config):
    """Development environment configuration"""
    
    DEBUG = True
    TESTING = False
    FLASK_ENV = 'development'
    LOG_LEVEL = 'DEBUG'
    SQLALCHEMY_ECHO = True
    
    # Use mock Vault in development
    MOCK_VAULT = os.getenv('MOCK_VAULT', 'True').lower() == 'true'


class TestingConfig(Config):
    """Testing environment configuration"""
    
    TESTING = True
    DEBUG = True
    FLASK_ENV = 'testing'
    
    # Use in-memory SQLite for testing
    DATABASE_URL = 'sqlite:///:memory:'
    SQLALCHEMY_ECHO = False
    
    # Shorter timeouts for tests
    CACHE_TTL = 1
    ROTATION_INTERVAL = 10
    GRACE_PERIOD = 5
    
    # Mock Vault
    MOCK_VAULT = True
    
    # Disable rate limiting in tests
    RATE_LIMIT_ENABLED = False
    
    # Disable alerts in tests
    SEND_ALERTS = False


class ProductionConfig(Config):
    """Production environment configuration"""
    
    DEBUG = False
    TESTING = False
    FLASK_ENV = 'production'
    LOG_LEVEL = 'INFO'
    SQLALCHEMY_ECHO = False
    
    # Ensure critical settings are configured
    @classmethod
    def validate(cls):
        """Validate production configuration"""
        errors = []
        
        if not cls.VAULT_TOKEN:
            errors.append('VAULT_TOKEN must be set in production')
        
        if cls.SECRET_KEY == 'dev-secret-key-change-in-production':
            errors.append('SECRET_KEY must be changed from default in production')
        
        if cls.JWT_SECRET == 'dev-jwt-secret-change-in-production':
            errors.append('JWT_SECRET must be changed from default in production')
        
        if errors:
            raise ValueError('Production configuration errors:\n' + '\n'.join(errors))
        
        return True


# Configuration factory
def get_config(env=None):
    """
    Get configuration based on environment
    
    Args:
        env: Environment name (development, testing, production)
    
    Returns:
        Configuration class
    """
    if env is None:
        env = os.getenv('FLASK_ENV', 'production')
    
    configs = {
        'development': DevelopmentConfig,
        'testing': TestingConfig,
        'production': ProductionConfig
    }
    
    config_class = configs.get(env.lower(), ProductionConfig)
    
    # Validate production config
    if env.lower() == 'production':
        config_class.validate()
    
    return config_class


# Default configuration
default_config = get_config()


# Convenience function to get config values
def get_config_value(key, default=None):
    """
    Get a config value by key
    
    Args:
        key: Configuration key
        default: Default value if key doesn't exist
    
    Returns:
        Configuration value
    """
    return getattr(default_config, key, default)


# API Response Codes
API_RESPONSE_CODES = {
    'SUCCESS': 200,
    'CREATED': 201,
    'ACCEPTED': 202,
    'BAD_REQUEST': 400,
    'UNAUTHORIZED': 401,
    'FORBIDDEN': 403,
    'NOT_FOUND': 404,
    'CONFLICT': 409,
    'INTERNAL_ERROR': 500,
    'SERVICE_UNAVAILABLE': 503
}


# Error Messages
ERROR_MESSAGES = {
    'VAULT_UNAVAILABLE': 'Vault service is unavailable',
    'INVALID_CREDENTIALS': 'Invalid credentials provided',
    'ROTATION_FAILED': 'Credential rotation failed',
    'CACHE_ERROR': 'Cache operation failed',
    'INVALID_SERVICE': 'Service not found',
    'AUTHENTICATION_REQUIRED': 'Authentication required',
    'UNAUTHORIZED': 'Unauthorized access',
    'INTERNAL_ERROR': 'Internal server error'
}


# Success Messages
SUCCESS_MESSAGES = {
    'CREDENTIALS_RETRIEVED': 'Credentials retrieved successfully',
    'ROTATION_INITIATED': 'Credential rotation initiated',
    'CACHE_CLEARED': 'Cache cleared successfully',
    'HEALTH_CHECK_PASSED': 'Health check passed'
}
