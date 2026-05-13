"""Application configuration."""
import os
import json
import boto3
from pathlib import Path
from datetime import timedelta
from botocore.exceptions import ClientError


basedir = Path(__file__).parent.parent


def get_secrets_from_aws():
    """
    Fetch secrets from AWS Secrets Manager.

    Returns dict of secrets or empty dict if unavailable.
    Falls back to environment variables if Secrets Manager is not accessible.
    """
    secret_name = os.environ.get('SECRET_NAME', 'dockyard/production')
    region_name = os.environ.get('AWS_REGION', 'us-east-2')

    # Try to fetch from Secrets Manager
    try:
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name
        )

        response = client.get_secret_value(SecretId=secret_name)

        if 'SecretString' in response:
            return json.loads(response['SecretString'])
        else:
            # Decode binary secret (if stored as binary)
            import base64
            return json.loads(base64.b64decode(response['SecretBinary']))

    except ClientError as e:
        # Secrets Manager not available - fall back to environment variables
        error_code = e.response['Error']['Code']
        if error_code in ['ResourceNotFoundException', 'AccessDeniedException']:
            print(f"Warning: Secrets Manager not available ({error_code}), using environment variables")
            return {}
        else:
            print(f"Warning: Error accessing Secrets Manager: {e}")
            return {}
    except Exception as e:
        print(f"Warning: Unexpected error accessing Secrets Manager: {e}")
        return {}


# Fetch secrets from AWS Secrets Manager (if available)
_secrets = get_secrets_from_aws()


def get_secret(key, default=None):
    """
    Get secret from AWS Secrets Manager or environment variable.

    Priority:
    1. AWS Secrets Manager
    2. Environment variable
    3. Default value

    Uses ``is not None`` checks so empty-string, ``"0"``, or ``"false"``
    values intentionally set by an operator are preserved rather than
    silently falling through to the next tier.
    """
    v = _secrets.get(key)
    if v is not None:
        return v
    v = os.environ.get(key)
    if v is not None:
        return v
    return default


class Config:
    """
    Base configuration class containing default settings.
    
    This class defines common settings used across all environments, 
    including security keys, file paths, upload limits, and service 
    integrations like AWS S3 and eBay.

    Secrets are fetched from AWS Secrets Manager (if available) or
    fall back to environment variables for development.
    """
    # Application identity (configurable)
    APP_NAME = get_secret('APP_NAME', os.environ.get('APP_NAME', 'app-item-listing-tool'))

    SECRET_KEY = get_secret('SECRET_KEY', 'dev-secret-key-change-in-production')

    @classmethod
    def init_app(cls, app):
        """
        Initialize the application with this configuration.
        
        Args:
            app (Flask): The Flask application instance.
        """
        pass

    # Session configuration
    SESSION_COOKIE_SECURE = False  # Set to True when using HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)  # 24 hours

    # File paths
    UPLOAD_FOLDER = basedir / 'instance' / 'uploads'
    CSV_FILE = basedir / 'instance' / 'items.csv'
    SKU_FILE = basedir / 'instance' / 'sku.txt'

    # Upload settings
    # Allow up to 8 images x 10 MB = 80 MB per request + overhead.
    # Matches the per-file 10 MB cap enforced in app/routes/api/comics.py.
    MAX_CONTENT_LENGTH = 96 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # AWS S3 Configuration
    # Prefer IAM roles (no keys needed in production)
    # Only use explicit keys if provided (for development/local testing)
    AWS_ACCESS_KEY_ID = get_secret('AWS_ACCESS_KEY_ID')  # Optional - IAM role preferred
    AWS_SECRET_ACCESS_KEY = get_secret('AWS_SECRET_ACCESS_KEY')  # Optional - IAM role preferred
    AWS_REGION = get_secret('AWS_REGION', 'us-east-1')
    S3_BUCKET = get_secret('S3_BUCKET_NAME') or get_secret('S3_BUCKET')
    S3_FOLDER = get_secret('S3_FOLDER', 'production')  # Default to production folder


    # SNS Configuration (optional - for notifications)
    SNS_TOPIC_ARN = get_secret('SNS_TOPIC_ARN')

    # Pagination
    COMICS_PER_PAGE = 20
    MAX_PER_PAGE = 100

    # System Stats Polling (in milliseconds)
    SYSTEM_STATS_INTERVAL = 60000  # 60 seconds

    # eBay Settings
    EBAY_CACHE_TTL = 3600
    EBAY_DAILY_LIMIT = 5000
    EBAY_PRODUCTION_APP_ID = get_secret('EBAY_PRODUCTION_APP_ID')
    EBAY_PRODUCTION_CERT_ID = get_secret('EBAY_PRODUCTION_CERT_ID')
    EBAY_PRODUCTION_DEV_ID = get_secret('EBAY_PRODUCTION_DEV_ID')
    EBAY_PRODUCTION_TOKEN = get_secret('EBAY_PRODUCTION_TOKEN')
    EBAY_SANDBOX_APP_ID = get_secret('EBAY_SANDBOX_APP_ID')
    EBAY_SANDBOX_CERT_ID = get_secret('EBAY_SANDBOX_CERT_ID')
    EBAY_SANDBOX_DEV_ID = get_secret('EBAY_SANDBOX_DEV_ID')
    EBAY_SANDBOX_TOKEN = get_secret('EBAY_SANDBOX_TOKEN')


class DevelopmentConfig(Config):
    """
    Configuration for the development environment.
    
    Enables debug mode, automatic template reloading, and generates
    a unique secret key on each restart to clear active sessions.
    """
    DEBUG = True
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0
    # Regenerate secret key on each restart in dev mode to clear sessions
    SECRET_KEY = os.urandom(24).hex()


class ProductionConfig(Config):
    """
    Configuration for the production environment.

    Disables debug mode, enforces secure session cookies by default,
    and requires the SECRET_KEY to be explicitly set via Secrets
    Manager or environment variables.

    Secure cookies can be explicitly disabled for local HTTPS-less
    smoke tests by setting ``ALLOW_INSECURE_COOKIES=1``.
    """
    DEBUG = False
    # Default to Secure=True in production. An operator running behind
    # plain HTTP for a one-off test can opt out with ALLOW_INSECURE_COOKIES=1.
    SESSION_COOKIE_SECURE = os.environ.get('ALLOW_INSECURE_COOKIES', '').lower() not in ('1', 'true', 'yes')

    @classmethod
    def init_app(cls, app):
        """
        Initialize production-specific application settings.
        
        Args:
            app (Flask): The Flask application instance.
            
        Raises:
            RuntimeError: If SECRET_KEY is not set via Secrets Manager or environment.
        """
        secret_key = app.config.get('SECRET_KEY')
        if not secret_key or secret_key == 'dev-secret-key-change-in-production':
            raise RuntimeError(
                "SECRET_KEY must be set in production (via Secrets Manager or environment variable)!"
            )


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
