"""Flask application factory."""
from flask import Flask, has_request_context, g
import csv
import hashlib
import os
import subprocess
import threading
import traceback
from dotenv import load_dotenv
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler, WatchedFileHandler
import time
import json

# Track application start time
APP_START_TIME = time.time()

# ============================================================================
# ENVIRONMENT VARIABLE LOADING
# ============================================================================
# This code handles BOTH local development AND production deployment:
#
# LOCAL DEVELOPMENT:
#   1. User runs: python scripts/local_dev_setup_env.py
#   2. This generates: .env file (auto-generated from vault.yml)
#   3. App loads .env via load_dotenv() below
#   4. Secrets come from .env file (Secrets Manager fallback)
#
# PRODUCTION DEPLOYMENT:
#   1. No .env file exists on the server
#   2. Systemd service sets environment variables:
#      - SECRET_NAME, AWS_REGION, APP_SERVICE_NAME,
#        COMIC_IMAGE_PATH, CLOUDWATCH_NAMESPACE
#   3. App skips load_dotenv() (file doesn't exist)
#   4. Secrets come from AWS Secrets Manager (via config.py)
#
# The load_dotenv() call is INTENTIONALLY optional:
# - If .env exists (local dev): loads it
# - If .env doesn't exist (production): skips silently
# ============================================================================
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    # Local development: .env file exists from local_dev_setup_env.py
    load_dotenv(dotenv_path=env_path)
else:
    # Production: .env doesn't exist
    # Secrets come from AWS Secrets Manager via config.py
    # which reads SECRET_NAME and AWS_REGION from systemd environment
    pass


class UserContextFilter(logging.Filter):
    """
    Logging filter that adds the current username to log records.
    
    This filter checks if a request context is available and attempts to
    retrieve the username from Flask's 'g' object. If no user is logged in
    or if called outside a request context, it defaults to 'anonymous'
    or 'system'.
    """
    def filter(self, record):
        """
        Add username attribute to the log record.
        
        Args:
            record: The log record to be filtered.
            
        Returns:
            bool: Always True to allow the record to be logged.
        """
        if has_request_context():
            # Try to get username from g (set by login_required decorator)
            record.username = getattr(g, 'username', 'anonymous')
        else:
            record.username = 'system'
        return True


def _setup_dedicated_logger(app, config_name, logger_name, log_filename, attr_name):
    """
    Setup a dedicated rotating-file logger and attach it to the app.

    Args:
        app: Flask application instance
        config_name: Current configuration name ('production' or 'development')
        logger_name: Name for the Python logger (e.g. 'service', 'cleanup')
        log_filename: Log file name (e.g. 'service.log', 'cleanup.log')
        attr_name: Attribute name to set on app (e.g. 'service_logger')
    """
    try:
        # Determine log path based on environment.
        # In production, LOG_DIR is created by the deployment
        # playbook (setup.yml) *before* the app starts — never try to mkdir
        # it here since the runtime user lacks permission to create dirs under
        # the shared system log root. Fall back to instance/ only in development.
        if config_name == 'production':
            app_name = os.environ.get('APP_SERVICE_NAME', os.environ.get('APP_NAME', 'app'))
            log_dir = Path(os.environ.get('LOG_DIR', f'/var/log/apps/{app_name}'))
            if not log_dir.exists() or not os.access(log_dir, os.W_OK):
                app.logger.warning(
                    f"Production log directory {log_dir} does not exist or is not "
                    f"writable. Falling back to app logger for {logger_name}. "
                    f"Run the setup.yml playbook to create it."
                )
                setattr(app, attr_name, app.logger)
                return
        else:
            log_dir = Path(app.instance_path)
            log_dir.mkdir(parents=True, exist_ok=True)

        log_path = log_dir / log_filename

        # Create logger
        dedicated_logger = logging.getLogger(logger_name)
        dedicated_logger.setLevel(logging.DEBUG)
        dedicated_logger.propagate = False

        # Remove any existing handlers
        dedicated_logger.handlers = []

        # Main handler: all messages → dedicated log file
        if config_name == 'production':
            handler = WatchedFileHandler(str(log_path))
        else:
            handler = RotatingFileHandler(
                str(log_path),
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=10
            )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
        ))
        dedicated_logger.addHandler(handler)

        # Error handler: ERROR+ also → error.log (production only)
        if config_name == 'production':
            error_path = log_dir / 'error.log'
            error_handler = WatchedFileHandler(str(error_path))
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(logging.Formatter(
                '[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
            ))
            dedicated_logger.addHandler(error_handler)

        # Store reference on app for easy access
        setattr(app, attr_name, dedicated_logger)

    except Exception as e:
        app.logger.warning(f"Could not set up {logger_name} logger: {e}")
        # Fallback: use the main app logger so the attribute always exists
        setattr(app, attr_name, app.logger)


def create_app(config_name='development'):
    """
    Flask application factory.
    
    This function initializes the Flask application, loads configuration,
    sets up logging, ensures required directories exist, synchronizes
    initial state from S3, and registers blueprints and background tasks.
    
    Args:
        config_name (str): The configuration environment to use 
                          ('development', 'production', or 'testing').
                          Defaults to 'development'.
                          
    Returns:
        Flask: The configured Flask application instance.
    """
    # Use standard Flask structure (static/ and templates/ in app/ folder)
    # Flask automatically looks for these folders in the same directory as __init__.py
    app = Flask(__name__)

    # Load configuration
    from app.config import config
    app.config.from_object(config[config_name])

    # Configure logging
    if config_name == 'production':
        # In production, try to log to LOG_DIR/app.log
        # The directory should be created by deployment scripts
        try:
            # Get app name from environment (required in production)
            app_name = os.environ.get('APP_SERVICE_NAME', os.environ.get('APP_NAME', 'app'))
            log_dir = Path(os.environ.get('LOG_DIR', f'/var/log/apps/{app_name}'))

            # Only set up file logging if directory exists and is writable
            if log_dir.exists() and os.access(log_dir, os.W_OK):
                log_file = log_dir / 'app.log'

                # Main handler: INFO+ → app.log (all application messages)
                file_handler = WatchedFileHandler(str(log_file))
                file_handler.setLevel(logging.INFO)
                file_handler.setFormatter(logging.Formatter(
                    '[%(asctime)s] %(username)s - %(levelname)s in %(module)s: %(message)s'
                ))
                file_handler.addFilter(UserContextFilter())
                app.logger.addHandler(file_handler)

                # Error handler: ERROR+ → error.log (errors only)
                error_file = log_dir / 'error.log'
                error_handler = WatchedFileHandler(str(error_file))
                error_handler.setLevel(logging.ERROR)
                error_handler.setFormatter(logging.Formatter(
                    '[%(asctime)s] %(username)s - %(levelname)s in %(module)s: %(message)s'
                ))
                error_handler.addFilter(UserContextFilter())
                app.logger.addHandler(error_handler)

                app.logger.setLevel(logging.INFO)
                app.logger.propagate = False  # Prevent propagation to gunicorn's logger
                app.logger.addFilter(UserContextFilter())

                # Also attach handlers to the 'app' package logger so that
                # logging.getLogger(__name__) in app.services.*, app.utils.*, etc.
                # writes to app.log / error.log instead of Gunicorn's stderr (error.log).
                package_logger = logging.getLogger('app')
                package_logger.setLevel(logging.INFO)
                package_logger.addHandler(file_handler)
                package_logger.addHandler(error_handler)
                package_logger.propagate = False  # Don't bubble up to root/Gunicorn
            else:
                # Just use default logging to stderr/stdout (captured by supervisor)
                app.logger.setLevel(logging.INFO)
                app.logger.propagate = False
        except Exception as e:
            # Fallback to stderr if can't create log file
            print(f"Warning: Could not set up file logging: {e}", flush=True)
            app.logger.setLevel(logging.INFO)
    else:
        # In development, log to console AND file for consistency
        app.logger.setLevel(logging.DEBUG)

        # Also write to instance/app.log for easier debugging
        try:
            dev_log_file = Path(app.instance_path) / 'app.log'
            dev_log_file.parent.mkdir(parents=True, exist_ok=True)

            dev_file_handler = RotatingFileHandler(
                str(dev_log_file),
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5
            )
            dev_file_handler.setLevel(logging.DEBUG)
            dev_file_handler.setFormatter(logging.Formatter(
                '[%(asctime)s] %(username)s - %(levelname)s in %(module)s: %(message)s'
            ))
            dev_file_handler.addFilter(UserContextFilter())
            app.logger.addHandler(dev_file_handler)
        except Exception as e:
            print(f"Warning: Could not set up development file logging: {e}", flush=True)

    # Configure service logger (for S3 sync, health checks, etc.)
    _setup_dedicated_logger(app, config_name, 'service', 'service.log', 'service_logger')
    # Configure cleanup logger (for health checks, trash cleanup, orphaned files)
    _setup_dedicated_logger(app, config_name, 'cleanup', 'cleanup.log', 'cleanup_logger')

    # Initialize security middleware (DDoS protection, attack detection, rate limiting)
    from app.security import init_security_middleware
    init_security_middleware(app)

    # Use SECRET_KEY from config (loaded from .env file)
    # All workers must use the same SECRET_KEY for sessions to work with Gunicorn

    # Ensure required directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['CSV_FILE']), exist_ok=True)
    os.makedirs(os.path.dirname(app.config['SKU_FILE']), exist_ok=True)

    # Create multi-user data directory for user-specific CSV and SKU files
    data_dir = os.path.join(os.path.dirname(app.config['CSV_FILE']), 'data')
    os.makedirs(data_dir, exist_ok=True)
    app.logger.info(f"Multi-user data directory ensured: {data_dir}")

    # Migrate legacy flat-file user data (e.g., brian-items.csv → brian/items.csv)
    from app.utils.user_context import migrate_legacy_user_files
    migrate_legacy_user_files(app)

    # Sync User Preferences and S3 data on startup
    from app.services.s3_service import s3_service
    from datetime import timezone

    # 1. Sync User Preferences FIRST (needed to know which users exist)
    user_prefs_file = Path(app.instance_path) / 'user_preferences.json'
    local_prefs_mtime = None
    local_user_count = 0

    # Check local file status
    if user_prefs_file.exists():
        local_prefs_mtime = user_prefs_file.stat().st_mtime
        try:
            with open(user_prefs_file, 'r') as f:
                local_prefs = json.load(f)
                local_user_count = len(local_prefs)
        except (json.JSONDecodeError, IOError, TypeError):
            local_user_count = 0

    prefs_data_from_s3 = s3_service.restore_user_preferences_from_s3()

    if prefs_data_from_s3:
        s3_prefs_mtime = prefs_data_from_s3['last_modified'].replace(tzinfo=timezone.utc).timestamp()
        s3_user_count = len(prefs_data_from_s3['content'])

        if not local_prefs_mtime:
            # Local doesn't exist - download from S3
            app.logger.info(f"📥 Downloading user preferences from S3 ({s3_user_count} users)")
            user_prefs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(user_prefs_file, 'w') as f:
                json.dump(prefs_data_from_s3['content'], f, indent=2)
        elif s3_prefs_mtime > local_prefs_mtime:
            # S3 is newer - but check if local has more users (safety check)
            if local_user_count > s3_user_count and local_user_count > 1:
                app.logger.warning(f"⚠️  S3 has newer timestamp but local has more users ({local_user_count} vs {s3_user_count})")
                app.logger.warning(f"⚠️  Keeping local users and uploading to S3 instead")
                s3_service.backup_user_preferences_to_s3(user_prefs_file)
            else:
                # Safe to download from S3
                app.logger.info(f"📥 S3 user preferences newer - downloading ({s3_user_count} users)")
                user_prefs_file.parent.mkdir(parents=True, exist_ok=True)
                with open(user_prefs_file, 'w') as f:
                    json.dump(prefs_data_from_s3['content'], f, indent=2)
        elif local_prefs_mtime > s3_prefs_mtime:
            # Local is newer - upload to S3
            app.logger.info(f"📤 Local user preferences newer - uploading to S3 ({local_user_count} users)")
            s3_service.backup_user_preferences_to_s3(user_prefs_file)
        else:
            # Same timestamp - no sync needed
            app.logger.info(f"✅ User preferences in sync ({local_user_count} users)")
    else:
        # S3 is missing the user preferences - upload local if it exists
        if user_prefs_file.exists():
            app.logger.info(f"📤 No S3 user preferences found - uploading local ({local_user_count} users)")
            s3_service.backup_user_preferences_to_s3(user_prefs_file)
        else:
            app.logger.info("ℹ️  No user preferences found locally or in S3 - will create on first login")

    # Initialize user authentication system AFTER S3 sync to ensure clean data
    from app.models.user import user_manager
    with app.app_context():
        users = user_manager._load_users()
        user_count = len(users)
        registered_usernames = []
        if user_count > 0:
            registered_usernames = [user['username'] for user in users.values()]
            app.logger.info(f"✅ User authentication initialized with {user_count} user(s): {', '.join(registered_usernames)}")
        else:
            app.logger.warning("⚠️  No users found - create users via web interface or set USERS environment variable")

    # 2. Sync SKU and CSV per user (after users are loaded so we know usernames)
    from app.services.csv_service import initialize_csv
    from app.utils.user_context import get_user_csv_file, get_user_sku_file

    with app.app_context():
        for username in registered_usernames:
            try:
                sku_file = get_user_sku_file(username)
                csv_file = get_user_csv_file(username)

                # Sync SKU — highest value wins
                local_sku = None
                if sku_file.exists() and sku_file.stat().st_size > 0:
                    try:
                        with open(sku_file, 'r') as f:
                            local_sku = int(f.read().strip())
                    except (ValueError, IOError):
                        local_sku = None

                sku_data_from_s3 = s3_service.restore_sku_from_s3(username)
                final_sku = None

                if sku_data_from_s3 and local_sku:
                    s3_sku = sku_data_from_s3['sku']
                    final_sku = max(s3_sku, local_sku)
                    if local_sku > s3_sku:
                        s3_service.backup_sku_to_s3(local_sku, username)
                elif sku_data_from_s3:
                    final_sku = sku_data_from_s3['sku']
                elif local_sku:
                    final_sku = local_sku
                    s3_service.backup_sku_to_s3(local_sku, username)
                else:
                    final_sku = 1000

                if local_sku != final_sku:
                    sku_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(sku_file, 'w') as f:
                        f.write(f"{final_sku}\n")

                # Sync CSV — newer file wins (download or upload)
                local_csv_mtime = None
                local_csv_size = 0
                if csv_file.exists():
                    local_csv_mtime = csv_file.stat().st_mtime
                    local_csv_size = csv_file.stat().st_size

                csv_data_from_s3 = s3_service.restore_main_csv_from_s3(username)

                if csv_data_from_s3:
                    s3_csv_mtime = csv_data_from_s3['last_modified'].replace(tzinfo=timezone.utc).timestamp()
                    if not local_csv_mtime or s3_csv_mtime > local_csv_mtime:
                        csv_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(csv_file, 'wb') as f:
                            f.write(csv_data_from_s3['content'])
                    elif local_csv_mtime > s3_csv_mtime and local_csv_size > 300:
                        s3_service.backup_main_csv_to_s3(csv_file, username)
                    elif local_csv_mtime > s3_csv_mtime and local_csv_size <= 300:
                        csv_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(csv_file, 'wb') as f:
                            f.write(csv_data_from_s3['content'])
                else:
                    if csv_file.exists() and local_csv_size > 300:
                        s3_service.backup_main_csv_to_s3(csv_file, username)

                # Initialize CSV with headers if it still doesn't exist
                initialize_csv(csv_file)
                app.logger.info(f"✅ Synced data for user: {username}")

            except Exception as e:
                app.logger.error(f"Error syncing data for user {username}: {e}")

    # Cleanup expired trash items on startup (for all registered users)
    with app.app_context():
        from app.services.trash_service import TrashService
        from app.utils.user_context import get_user_trash_dir
        for username in registered_usernames:
            try:
                user_trash_dir = get_user_trash_dir(username)
                user_trash_service = TrashService(trash_path=user_trash_dir / 'recent')
                user_trash_service.cleanup_expired()
            except Exception as e:
                app.logger.error(f"Error cleaning up trash for {username} on startup: {e}")

    # Sync backups from S3 to local storage on startup (in background thread)
    # NOTE: Health check runs AFTER sync to ensure local images exist first
    from app.utils.sync_state import sync_state

    def sync_backups_background():
        """
        Background thread function to sync backups and images from S3.
        
        This function handles bi-directional synchronization of images and exports
        between the local instance directory and the S3 bucket. It prevents multiple
        concurrent syncs and respects the SKIP_S3_SYNC configuration setting.

        After sync completes, runs a health check to verify CSV integrity and
        delete orphaned images that aren't referenced in the CSV.
        """
        # Check if sync is disabled by configuration
        if app.config.get('SKIP_S3_SYNC', False):
            return

        with app.app_context():
            try:
                # Ensure INSTANCE_PATH is absolute
                instance_abs_path = os.path.abspath(app.instance_path)
                os.environ['INSTANCE_PATH'] = instance_abs_path

                # Check for sync lock FIRST (works across processes)
                if sync_state.is_locked():
                    return

                # Acquire cross-worker lock; if another worker is already
                # syncing, skip this run entirely (returns False non-blocking).
                if not sync_state.lock_sync():
                    app.logger.info("Another worker is running the S3 sync; skipping.")
                    return

                # Sync images and exports for each registered user
                for username in registered_usernames:
                    try:
                        # 1. Sync Images (Bi-directional)
                        s3_service.sync_images_from_s3(username=username)

                        # 2. Sync Exports (Bi-directional)
                        s3_service.sync_exports_from_s3(username=username)
                    except Exception as user_err:
                        app.logger.error(f"Error syncing data for {username}: {user_err}")

                # 3. Run health check AFTER sync completes
                # This ensures local images are downloaded from S3 before checking for orphans
                # Health check now supports multi-user by checking all CSV files
                from app.services.health_check_service import HealthCheckService
                try:
                    health_check = HealthCheckService(instance_path=app.instance_path)
                    results = health_check.run()
                    if results['success']:
                        app.service_logger.info(
                            f"✓ Health check passed - "
                            f"Users checked: {results['users_checked']}, "
                            f"S3 orphans deleted: {results['orphaned_s3_deleted']}, "
                            f"Local orphans deleted: {results['orphaned_local_deleted']}"
                        )
                    else:
                        app.logger.warning(f"Health check completed with errors: {results['errors']}")
                except Exception as health_err:
                    app.logger.error(f"Error running health check after sync: {health_err}")

            except Exception as e:
                app.logger.error(f"Error in background sync: {e}")
                sync_state.fail_sync(str(e))
            finally:
                # Release the lock so other processes can sync later if needed
                sync_state.unlock_sync()

    # Start backup sync in background thread
    sync_thread = threading.Thread(target=sync_backups_background, daemon=True)
    sync_thread.start()

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    # Register template globals
    from app.utils.helpers import generate_csrf_token
    app.jinja_env.globals['csrf_token'] = generate_csrf_token

    # Initialize cache for eBay listings (guarded by a lock because every
    # worker thread mutates it via the before_request hook below).
    app.ebay_cache = {}
    app.ebay_cache_lock = threading.Lock()
    app.logger.info("✓ eBay listings cache initialized")

    # Initialize eBay category cache (must run within app context)
    try:
        with app.app_context():
            from app.services.ebay_service import ebay_service
            ebay_service.initialize_category_cache()
            app.logger.info("✓ eBay category cache initialized")
    except Exception as e:
        app.logger.warning(f"⚠ Failed to initialize eBay category cache: {e}")
        app.logger.debug(traceback.format_exc())

    @app.before_request
    def check_ebay_cache_expiry():
        """Check and clear expired cache entries before each request."""
        from datetime import datetime, timedelta

        # Snapshot under the lock so we can iterate safely even while other
        # threads mutate app.ebay_cache; then remove expired keys under the
        # lock to avoid RuntimeError: dictionary changed size during iteration.
        with app.ebay_cache_lock:
            items_snapshot = list(app.ebay_cache.items())

        expired_keys = []
        for key, data in items_snapshot:
            try:
                fetched_at = datetime.fromisoformat(data['fetched_at'])
                if datetime.now() - fetched_at > timedelta(hours=1):
                    expired_keys.append(key)
            except (KeyError, ValueError):
                expired_keys.append(key)

        if expired_keys:
            with app.ebay_cache_lock:
                for key in expired_keys:
                    if key in app.ebay_cache:
                        app.logger.info(f"Clearing expired eBay cache: {key}")
                        del app.ebay_cache[key]

    @app.context_processor

    def inject_version():
        """
        Inject application version information into the Jinja2 template context.

        This processor attempts to determine the version in the following priority:
        1) Read 'instance/app_version' file (generated during deployment).
        2) Query Git for the total commit count on the current branch.
        3) Fall back to 'unavailable' if both methods fail.

        Returns:
            dict: A dictionary containing version details used globally in templates.
        """
        def _version_dict(build):
            app_stage = 'Private'
            return {
                'app_version': f'vP.{build}',
                'app_stage': app_stage,
                'app_version_display': f'{app_stage} (Build {build})'
            }

        try:
            # 1) Check for an instance/app_version file written by the deployment script
            try:
                version_path = Path(app.instance_path) / 'app_version'
            except Exception:
                version_path = Path(__file__).parent.parent / 'instance' / 'app_version'

            if version_path.exists():
                try:
                    raw = version_path.read_text(encoding='utf-8').strip()
                    if raw:
                        return _version_dict(raw)
                except Exception:
                    pass

            # 2) Fallback: try to compute from git commit count
            try:
                commit_count = subprocess.check_output(
                    ['git', 'rev-list', '--count', 'HEAD'],
                    cwd=Path(__file__).parent.parent,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).decode('utf-8').strip()
                build_number = int(commit_count) + 850
                return _version_dict(str(build_number))
            except Exception:
                pass

            # 3) Give a safe 'unavailable' response
            return _version_dict('unavailable')
        except Exception as e:
            try:
                app.logger.error(f"Unexpected error when injecting version: {e}")
            except Exception:
                pass
            return _version_dict('unavailable')

    # Startup Health Check: Validate CSV integrity
    # Startup CSV health check — verify per-user CSV files
    with app.app_context():
        for username in registered_usernames:
            try:
                csv_path = get_user_csv_file(username)
                if csv_path.exists():
                    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                        comic_count = sum(1 for _ in csv.DictReader(f))

                    if comic_count == 0:
                        app.logger.warning(f"⚠️  STARTUP WARNING: CSV for {username} is empty! Mass deletion protection activated.")
                    elif comic_count < 5:
                        app.logger.warning(f"⚠️  STARTUP WARNING: Only {comic_count} comics for {username} - below safety threshold (5)")
                    else:
                        app.logger.info(f"✓ CSV health check passed for {username} - {comic_count} comics")
                else:
                    app.logger.info(f"ℹ️  No CSV file yet for {username} — will be created on first use")
            except Exception as e:
                app.logger.error(f"CSV health check failed for {username}: {e}")

    # Auto-regenerate analytics page mockup images if the generation script
    # has changed since the last run, or if any expected PNG is missing.
    _check_analytics_images(app)

    return app


def _check_analytics_images(app) -> None:
    """Regenerate analytics page mockup PNGs if the script changed or images are missing.

    Computes an MD5 hash of ``util_generate_page_images.py`` and compares it
    against a hash stored in ``app/static/analytics/.gen_hash``.  If the hash
    differs, or if any expected PNG is absent, the images are regenerated and
    the hash file is updated so subsequent restarts skip the work.
    """

    script_path = Path(__file__).parent / 'scripts' / 'util_generate_page_images.py'
    analytics_dir = Path(__file__).parent / 'static' / 'analytics'
    hash_file = analytics_dir / '.gen_hash'

    # Read the generation script
    try:
        script_bytes = script_path.read_bytes()
        current_hash = hashlib.md5(script_bytes).hexdigest()
    except Exception as exc:
        app.logger.warning(f"⚠ Analytics image check: could not read generation script: {exc}")
        return

    # Read the stored hash (empty string if missing)
    stored_hash = ''
    if hash_file.exists():
        try:
            stored_hash = hash_file.read_text(encoding='utf-8').strip()
        except Exception:
            pass

    # Determine which PNGs are expected
    try:
        # Deferred: requires script to be importable; guard against import errors
        from app.scripts.util_generate_page_images import EXPECTED_PNGS  # noqa: PLC0415
    except Exception:
        # Fallback list if import fails for any reason
        EXPECTED_PNGS = [
            'home.png', 'browse.png', 'add.png', 'add-from-image.png',
            'account.png', 'price-lookup.png', 'trash.png', 'ebay-listings.png',
        ]

    missing = [p for p in EXPECTED_PNGS if not (analytics_dir / p).exists()]

    if current_hash == stored_hash and not missing:
        app.logger.debug("✓ Analytics page images are up-to-date")
        return

    reason = 'script changed' if current_hash != stored_hash else f'{len(missing)} image(s) missing'
    app.logger.info(f"↻ Regenerating analytics page images ({reason})…")

    try:
        from app.scripts.util_generate_page_images import generate_all_pages  # noqa: PLC0415
        results = generate_all_pages(str(analytics_dir))
        ok = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)
        app.logger.info(f"✓ Analytics images regenerated: {ok} created, {failed} failed")

        # Persist the new hash so the next restart skips this work
        try:
            analytics_dir.mkdir(parents=True, exist_ok=True)
            hash_file.write_text(current_hash, encoding='utf-8')
        except Exception as exc:
            app.logger.warning(f"⚠ Could not write analytics image hash: {exc}")

    except Exception as exc:
        app.logger.warning(f"⚠ Failed to regenerate analytics images: {exc}")
