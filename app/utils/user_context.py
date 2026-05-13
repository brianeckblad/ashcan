"""
User context utilities for multi-user support.

Provides functions to get user-specific file paths and settings.
Each user has their own CSV file, SKU counter, and can optionally
have their own eBay API credentials.
"""
import re
from pathlib import Path
from flask import session, current_app, has_request_context
import os


# Defence-in-depth: the same allow-list as auth.validate_username. Duplicated
# here to avoid a circular import at module-load time.
_SAFE_USERNAME_RE = re.compile(r'^[A-Za-z0-9_\-]{3,32}$')


def _assert_safe_username(username):
    """Raise ValueError if the username is not allow-listed.

    Any code path that constructs filesystem paths or S3 prefixes from a
    username goes through this guard so a crafted value (``../``, slashes,
    NULs, control chars) cannot escape the user data directory.
    """
    if username == 'default':
        return
    if not isinstance(username, str) or not _SAFE_USERNAME_RE.match(username):
        raise ValueError(f"Unsafe username: {username!r}")


def _safe_user_subpath(base_dir: Path, username: str) -> Path:
    """Return ``base_dir / 'data' / username`` after verifying containment.

    Uses ``Path.resolve()`` + ``is_relative_to`` to ensure the resolved
    directory lives inside ``base_dir``. Raises ``ValueError`` if escape is
    detected (belt-and-braces alongside the regex).
    """
    _assert_safe_username(username)
    base_resolved = base_dir.resolve()
    target = (base_dir / 'data' / username).resolve()
    # Python 3.9+: Path.is_relative_to; fall back to string compare if older.
    try:
        ok = target.is_relative_to(base_resolved)
    except AttributeError:  # pragma: no cover - Python <3.9 fallback
        ok = str(target).startswith(str(base_resolved) + os.sep)
    if not ok:
        raise ValueError(f"Refusing to use user path outside data dir: {target}")
    return target


def get_current_username():
    """
    Get the current logged-in username from session.

    Returns:
        str: The username, or 'default' if not logged in or outside request context
    """
    if not has_request_context():
        return 'default'
    return session.get('username', 'default')


def get_user_csv_file(username=None):
    """
    Get the CSV file path for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's items CSV file (e.g., instance/data/brian/items.csv)
    """
    if username is None:
        username = get_current_username()

    # For backward compatibility, 'default' user uses items.csv
    if username == 'default':
        return Path(current_app.config['CSV_FILE'])

    # Multi-user: data/{username}/items.csv
    base_dir = Path(current_app.config['CSV_FILE']).parent
    user_dir = _safe_user_subpath(base_dir, username)
    user_dir.mkdir(exist_ok=True, parents=True)

    return user_dir / "items.csv"


def get_user_sku_file(username=None):
    """
    Get the SKU counter file path for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's SKU counter file (e.g., instance/data/brian/sku.txt)
    """
    if username is None:
        username = get_current_username()

    # For backward compatibility, 'default' user uses sku.txt
    if username == 'default':
        return Path(current_app.config['SKU_FILE'])

    # Multi-user: data/{username}/sku.txt
    base_dir = Path(current_app.config['SKU_FILE']).parent
    user_dir = _safe_user_subpath(base_dir, username)
    user_dir.mkdir(exist_ok=True, parents=True)

    return user_dir / "sku.txt"


def get_user_secret_name(username=None):
    """
    Get the AWS Secrets Manager secret name for a user's eBay credentials.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: Secret name (e.g., 'dockyard/users/brian' or 'dockyard/production')
    """
    if username is None:
        username = get_current_username()

    # For backward compatibility, 'default' user uses app-level secret
    if username == 'default':
        app_name = os.environ.get('APP_NAME', 'app-item-listing-tool')
        return os.environ.get('SECRET_NAME', f'{app_name}/production')

    _assert_safe_username(username)
    # Multi-user: {app_prefix}/users/{username}
    # Keeps user secrets under the same IAM policy prefix as the main app secret
    secret_name = os.environ.get('SECRET_NAME', 'dockyard/production')
    prefix = secret_name.split('/')[0]
    return f"{prefix}/users/{username}"


def get_ebay_credentials(username=None):
    """
    Get eBay API credentials for a specific user.

    Tries to load user-specific credentials from AWS Secrets Manager.
    Falls back to app-level credentials if user-specific ones don't exist.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        dict: eBay credentials or None if not found
    """
    from app.config import get_secret  # Deferred: avoids circular import (config ← utils ← services)

    if username is None:
        username = get_current_username()

    # Try user-specific secret first using the new service
    if username != 'default':
        try:
            from app.services.user_secrets_service import user_secrets_service  # Deferred: avoids circular import
            user_creds = user_secrets_service.get_user_ebay_credentials(username)
            if user_creds:
                return user_creds
        except Exception as e:
            current_app.logger.warning(f"Could not fetch user-specific eBay credentials for {username}: {e}")

    # Fall back to app-level credentials (from main secret)
    return {
        'EBAY_PRODUCTION_APP_ID': get_secret('EBAY_PRODUCTION_APP_ID'),
        'EBAY_PRODUCTION_CERT_ID': get_secret('EBAY_PRODUCTION_CERT_ID'),
        'EBAY_PRODUCTION_DEV_ID': get_secret('EBAY_PRODUCTION_DEV_ID'),
        'EBAY_PRODUCTION_TOKEN': get_secret('EBAY_PRODUCTION_TOKEN'),
        'EBAY_SANDBOX_APP_ID': get_secret('EBAY_SANDBOX_APP_ID'),
        'EBAY_SANDBOX_CERT_ID': get_secret('EBAY_SANDBOX_CERT_ID'),
        'EBAY_SANDBOX_DEV_ID': get_secret('EBAY_SANDBOX_DEV_ID'),
        'EBAY_SANDBOX_TOKEN': get_secret('EBAY_SANDBOX_TOKEN'),
    }


def get_user_s3_prefix(username=None):
    """
    Get the S3 prefix (folder) for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 prefix (e.g., 'users/brian/' or 'users/sarah/')
    """
    if username is None:
        username = get_current_username()

    # For backward compatibility, 'default' user uses root/production prefix
    if username == 'default':
        s3_folder = os.environ.get('S3_FOLDER', 'production')
        return f"{s3_folder}/"

    _assert_safe_username(username)
    # Multi-user: users/{username}/
    return f"users/{username}/"


def get_user_s3_images_prefix(username=None):
    """
    Get the S3 prefix for user's images.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 images prefix (e.g., 'users/brian/images/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}images/"


def get_user_s3_csv_prefix(username=None):
    """
    Get the S3 prefix for user's CSV files.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 CSV prefix (e.g., 'users/brian/csv/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}csv/"


def get_user_s3_sku_prefix(username=None):
    """
    Get the S3 prefix for user's SKU file.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 SKU prefix (e.g., 'users/brian/sku/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}sku/"


def get_user_s3_config_prefix(username=None):
    """
    Get the S3 prefix for user's config files.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 config prefix (e.g., 'users/brian/config/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}config/"


def get_user_s3_exports_prefix(username=None):
    """
    Get the S3 prefix for user's exports.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 exports prefix (e.g., 'users/brian/exports/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}exports/"


def _get_user_subdir(dirname, username=None):
    """
    Get a user-specific subdirectory under the instance data path.

    Handles the default-user fallback and ensures the directory exists.

    Args:
        dirname (str): Subdirectory name (e.g. 'snapshots', 'trash', 'exports')
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's subdirectory
    """
    if username is None:
        username = get_current_username()

    csv_file = Path(current_app.config['CSV_FILE'])

    # For backward compatibility, 'default' user uses root-level directories
    if username == 'default':
        result = csv_file.parent / dirname
    else:
        base_dir = _safe_user_subpath(csv_file.parent, username)
        base_dir.mkdir(exist_ok=True, parents=True)
        result = base_dir / dirname

    result.mkdir(exist_ok=True, parents=True)
    return result


def get_user_snapshots_dir(username=None):
    """
    Get the local snapshots directory for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's snapshots directory
    """
    return _get_user_subdir('snapshots', username)


def get_user_trash_dir(username=None):
    """
    Get the local trash directory for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's trash directory
    """
    return _get_user_subdir('trash', username)


def get_user_analytics_dir(username=None):
    """
    Get the local analytics directory for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's analytics directory
    """
    return _get_user_subdir('analytics', username)


def get_user_exports_dir(username=None):
    """
    Get the local exports directory for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's exports directory
    """
    return _get_user_subdir('exports', username)


def get_user_uploads_dir(username=None):
    """
    Get the local uploads directory for a specific user.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's uploads directory (temporary files)
    """
    return _get_user_subdir('uploads', username)


def get_user_images_dir(username=None):
    """
    Get the local images directory for a specific user (if not using S3).

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        Path: Path to user's local images directory
    """
    return _get_user_subdir('images', username)


def get_user_s3_snapshots_prefix(username=None):
    """
    Get the S3 prefix for user's snapshots.

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 snapshots prefix (e.g., 'users/brian/snapshots/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}snapshots/"


def get_user_s3_trash_prefix(username=None):
    """
    Get the S3 prefix for user's trash (deleted items).

    Args:
        username (str, optional): Username. If None, uses current session user.

    Returns:
        str: S3 trash prefix (e.g., 'users/brian/trash/')
    """
    base_prefix = get_user_s3_prefix(username)
    return f"{base_prefix}trash/"


def ensure_user_data_directory():
    """
    Ensure the user data directory exists.

    Creates instance/data/ if it doesn't exist.
    """
    csv_file = Path(current_app.config['CSV_FILE'])
    data_dir = csv_file.parent / 'data'
    data_dir.mkdir(exist_ok=True, parents=True)


def migrate_legacy_user_files(app=None):
    """
    Migrate legacy flat-file user data to subdirectory structure.

    Moves files like data/brian-items.csv → data/brian/items.csv
    and data/brian-sku.txt → data/brian/sku.txt.

    Safe to call multiple times; skips files that don't exist or
    have already been migrated.

    Args:
        app: Flask app instance. If None, uses current_app (requires app context).
    """
    import shutil
    import logging
    logger = logging.getLogger(__name__)

    if app is None:
        app = current_app._get_current_object()

    csv_file = Path(app.config['CSV_FILE'])
    data_dir = csv_file.parent / 'data'

    if not data_dir.exists():
        return

    # Strict pattern: only migrate <safe-username>-items.csv — reject crafted
    # names that could become directory-traversal targets.
    legacy_csv_re = re.compile(r'^(?P<u>[A-Za-z0-9_]{3,32})-items\.csv$')
    legacy_sku_re = re.compile(r'^(?P<u>[A-Za-z0-9_]{3,32})-sku\.txt$')

    # Find legacy files matching {username}-items.csv pattern
    for legacy_csv in data_dir.glob('*-items.csv'):
        m = legacy_csv_re.match(legacy_csv.name)
        if not m:
            logger.warning(f"Skipping legacy file with unsafe name: {legacy_csv.name}")
            continue
        username = m.group('u')

        user_dir = data_dir / username
        user_dir.mkdir(exist_ok=True, parents=True)
        new_csv = user_dir / 'items.csv'

        if not new_csv.exists():
            shutil.move(str(legacy_csv), str(new_csv))
            logger.info(f"Migrated {legacy_csv.name} → {username}/items.csv")
        else:
            logger.info(f"Skipping migration of {legacy_csv.name} — {username}/items.csv already exists")

        # Also move the .bak file if present
        legacy_bak = legacy_csv.with_suffix('.csv.bak')
        if legacy_bak.exists():
            new_bak = user_dir / 'items.csv.bak'
            if not new_bak.exists():
                shutil.move(str(legacy_bak), str(new_bak))

    # Find legacy SKU files matching {username}-sku.txt
    for legacy_sku in data_dir.glob('*-sku.txt'):
        m = legacy_sku_re.match(legacy_sku.name)
        if not m:
            logger.warning(f"Skipping legacy SKU file with unsafe name: {legacy_sku.name}")
            continue
        username = m.group('u')

        user_dir = data_dir / username
        user_dir.mkdir(exist_ok=True, parents=True)
        new_sku = user_dir / 'sku.txt'

        if not new_sku.exists():
            shutil.move(str(legacy_sku), str(new_sku))
            logger.info(f"Migrated {legacy_sku.name} → {username}/sku.txt")
        else:
            logger.info(f"Skipping migration of {legacy_sku.name} — {username}/sku.txt already exists")


