"""User authentication and profile management."""
import json
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app


def _log_user_message(message, level='info'):
    """
    Log a message using Flask logger if available, otherwise print to stdout.

    Args:
        message (str): The message to log
        level (str): Log level - 'info', 'warning', or 'error'
    """
    try:
        logger = current_app.logger
        if level == 'warning':
            logger.warning(message)
        elif level == 'error':
            logger.error(message)
        else:
            logger.info(message)
    except RuntimeError:
        # Not in Flask context (e.g., during app initialization)
        print(message)


class UserManager:
    """
    Manages user authentication, credentials, and user preferences.

    Handles loading and saving user credentials from a persistent JSON file,
    password hashing and verification, and user preference management. Includes
    a caching mechanism to reduce file I/O while still detecting external changes.
    """

    DEFAULT_PREFERENCES = {
        'timezone': 'local',
        'mobile_per_page': 8,
        'desktop_per_page': 24,
        'default_sort': 'sku_asc',
        'default_view': 'grid',  # Default view layout: 'grid' or 'list'
        'micro_card_size': 60,  # 60% of normal card size (40% smaller as default)
        'ebay_format': 'FixedPrice',
        'ebay_duration': 'GTC',
        'ebay_listing_mode': 'future',
        'ebay_environment': 'production',
        'ebay_location': 'Highlands Ranch, CO',
        'ebay_postal_code': '80129'
    }

    def __init__(self):
        """Initialize the UserManager with an empty cache."""
        self.users_file = None
        self._users_cache = None
        self._last_modified = None

    def _get_users_file(self):
        """
        Get the path to the user_preferences.json file, creating directories as needed.

        Returns:
            Path: Path object pointing to the user_preferences.json file in the instance folder.
        """
        if self.users_file is None:
            try:
                # Try to get Flask's instance path if in app context
                instance_path = Path(current_app.instance_path)
            except RuntimeError:
                # Outside Flask app context - use fallback path
                instance_path = Path(__file__).parent.parent.parent / 'instance'

            # Ensure the instance directory exists
            instance_path.mkdir(parents=True, exist_ok=True)
            self.users_file = instance_path / 'user_preferences.json'

        return self.users_file

    def _load_users(self):
        """
        Load users from the JSON file, using cache if file hasn't changed.

        Implements intelligent caching by checking the file's modification
        time. If the file hasn't changed since the last load, returns the
        cached data without re-reading. Falls back to environment variables
        if the file doesn't exist.

        Returns:
            dict: Dictionary of users keyed by lowercase username.
        """
        users_file = self._get_users_file()

        # Check if file exists and get its modification time
        if users_file.exists():
            current_mtime = users_file.stat().st_mtime

            # Only reload from disk if file has changed or cache is empty
            if self._users_cache is None or self._last_modified != current_mtime:
                try:
                    with open(users_file, 'r') as f:
                        self._users_cache = json.load(f)
                    self._last_modified = current_mtime
                except (json.JSONDecodeError, IOError) as e:
                    _log_user_message(f"Error loading users file: {e}", level='error')
                    self._users_cache = {}

            # If file exists but has zero users, re-initialize from secrets/env.
            # This handles the case where a previous failed boot created an empty file.
            if not self._users_cache:
                _log_user_message("⚠️  user_preferences.json exists but has no users - re-initializing from secrets", level='warning')
                self._initialize_from_env()
        else:
            # File doesn't exist yet
            if self._users_cache and len(self._users_cache) > 0:
                # We have cached data in memory from web-created users
                _log_user_message("⚠️  user_preferences.json not found but cache available - recreating file", level='warning')
                # Recreate the file from cache to persist web-created users
                self._save_users(self._users_cache)
                return self._users_cache
            else:
                # No cache and no file - initialize from environment (only creates default if no USERS env var)
                _log_user_message("⚠️  user_preferences.json not found and no cache - initializing from environment", level='warning')
                self._initialize_from_env()

        return self._users_cache or {}

    def _default_preferences(self):
        """
        Get a fresh copy of the default user preferences.

        Returns:
            dict: A copy of DEFAULT_PREFERENCES for a new user.
        """
        return self.DEFAULT_PREFERENCES.copy()

    def _initialize_from_env(self):
        """
        Initialize the user_preferences.json file from the USERS secret or environment variable.

        Checks AWS Secrets Manager first (via config.get_secret), then falls
        back to the USERS environment variable.

        Expected format: 'username:password,user2:pass2'
        If no USERS value exists, this method will NOT create any default users
        to prevent admin user recreation issues.
        """
        from app.config import get_secret
        users_env = get_secret('USERS', '') or ''

        if not users_env:
            # SECURITY FIX: Do not create default admin user to prevent persistence issues
            # Users must be created explicitly via web interface or USERS environment variable
            _log_user_message("ℹ️  No USERS environment variable set - no users will be created automatically")
            self._users_cache = {}
            return

        _log_user_message(f"Initializing users from USERS environment variable")

        users = {}
        # Parse comma-separated user:password pairs
        for user_entry in users_env.split(','):
            if ':' in user_entry:
                username, password = user_entry.strip().split(':', 1)
                # Store username in lowercase for case-insensitive lookup
                users[username.lower()] = {
                    'username': username,  # Preserve original case for display
                    'password_hash': generate_password_hash(password),
                    'preferences': self._default_preferences()
                }

                # Initialize user data files and directories
                self._initialize_user_data(username)

        # Persist the initialized users to file
        self._save_users(users)
        self._users_cache = users

    def _initialize_user_data(self, username):
        """
        Initialize data files and directories for a new user.

        Creates:
        - User CSV file (empty)
        - User SKU file (starting at 1000)
        - User directories (snapshots, trash, analytics, etc.)

        Args:
            username (str): The username to initialize
        """
        try:
            from app.utils.user_context import (
                get_user_csv_file, get_user_sku_file,
                get_user_snapshots_dir, get_user_trash_dir,
                get_user_analytics_dir, get_user_exports_dir,
                get_user_uploads_dir, get_user_images_dir
            )

            # Create CSV file if it doesn't exist
            csv_file = get_user_csv_file(username)
            if not csv_file.exists():
                csv_file.parent.mkdir(parents=True, exist_ok=True)
                csv_file.touch()
                _log_user_message(f"Created CSV file for user {username}: {csv_file}")

            # Create SKU file with starting value of 1000
            sku_file = get_user_sku_file(username)
            if not sku_file.exists():
                sku_file.parent.mkdir(parents=True, exist_ok=True)
                with open(sku_file, 'w') as f:
                    f.write('1000\n')
                _log_user_message(f"Created SKU file for user {username}: {sku_file} (starting at 1000)")

            # Create all user directories
            get_user_snapshots_dir(username)
            get_user_trash_dir(username)
            get_user_analytics_dir(username)
            get_user_exports_dir(username)
            get_user_uploads_dir(username)
            get_user_images_dir(username)

            _log_user_message(f"✅ Initialized all data directories for user {username}")

        except Exception as e:
            _log_user_message(f"⚠️  Error initializing user data for {username}: {e}", level='warning')

    def _save_users(self, users):
        """
        Write the users dictionary to the JSON storage file and backup to S3.

        Updates the internal modification time tracking after successful write.
        Also backs up to S3 for persistence across deployments.

        Args:
            users (dict): The users dictionary to save.

        Raises:
            IOError: If writing to the file fails.
        """
        users_file = self._get_users_file()

        try:
            with open(users_file, 'w') as f:
                json.dump(users, f, indent=2)
            # Update the cached modification time
            if users_file.exists():
                self._last_modified = users_file.stat().st_mtime

            # Backup to S3 immediately for persistence across deployments
            try:
                from flask import current_app
                from app.services.s3_service import s3_service
                if current_app and current_app.config.get('S3_BUCKET'):
                    s3_service.backup_user_preferences_to_s3(users_file)
                    _log_user_message(f"✅ User preferences backed up to S3")
            except Exception as s3_error:
                _log_user_message(f"⚠️  Warning: Could not backup user preferences to S3: {s3_error}", level='warning')
                # Don't fail the save operation if S3 backup fails

        except IOError as e:
            _log_user_message(f"Error saving users file: {e}", level='error')
            raise


    def get_user(self, username):
        """
        Retrieve a user dictionary by username.
        
        Args:
            username (str): The username to look up (case-insensitive).
            
        Returns:
            dict or None: The user data if found, otherwise None.
        """
        users = self._load_users()
        return users.get(username.lower())

    def verify_password(self, username, password):
        """
        Verify if the provided password matches the stored hash for a user.
        
        Args:
            username (str): The username to verify.
            password (str): The plain-text password to check.
            
        Returns:
            bool: True if verification succeeds, False otherwise.
        """
        user = self.get_user(username)
        if user:
            return check_password_hash(user['password_hash'], password)
        return False

    def change_password(self, username, current_password, new_password):
        """
        Change a user's password after verifying their current one.
        
        Args:
            username (str): The user's username.
            current_password (str): Their current plain-text password.
            new_password (str): The new plain-text password to set.
            
        Returns:
            tuple: (bool, str) success status and message.
        """
        # Verify current password
        if not self.verify_password(username, current_password):
            return False, "Current password is incorrect"

        # Load current users
        users = self._load_users()
        username_lower = username.lower()

        if username_lower not in users:
            return False, "User not found"

        # Update password
        users[username_lower]['password_hash'] = generate_password_hash(new_password)

        # Save to file
        try:
            self._save_users(users)
            # Force cache update
            self._users_cache = users
            return True, "Password changed successfully"
        except Exception as e:
            return False, f"Error saving password: {e}"

    def change_username(self, old_username, password, new_username):
        """
        Change a user's username after verifying their password.
        
        Args:
            old_username (str): The user's current username.
            password (str): Their plain-text password for verification.
            new_username (str): The new username to set.
            
        Returns:
            tuple: (bool, str) success status and message.
        """
        # Validate the new username against the strict allow-list
        from app.routes.auth import validate_username
        ok, normalized = validate_username(new_username)
        if not ok:
            return False, normalized
        new_username = normalized

        # Verify password
        if not self.verify_password(old_username, password):
            return False, "Password is incorrect"

        # Load current users
        users = self._load_users()
        old_username_lower = old_username.lower()
        new_username_lower = new_username.lower()

        if old_username_lower not in users:
            return False, "User not found"

        if new_username_lower in users:
            return False, "Username already exists"

        # Move user data to new username
        user_data = users[old_username_lower]
        user_data['username'] = new_username  # Update display name
        users[new_username_lower] = user_data
        del users[old_username_lower]

        # Save to file
        try:
            self._save_users(users)
            # Force cache update
            self._users_cache = users
            return True, "Username changed successfully"
        except Exception as e:
            return False, f"Error saving username: {e}"

    def list_users(self):
        """
        Get a list of all registered usernames.
        
        Returns:
            list: List of usernames in their original casing.
        """
        users = self._load_users()
        return [user['username'] for user in users.values()]

    def create_user(self, username, password):
        """
        Create a new user with the given username and password.
        
        Args:
            username (str): The username for the new user.
            password (str): The plain-text password for the new user.
            
        Returns:
            tuple: (bool, str) success status and message.
        """
        # Strict username validation (prevents path traversal and shell chars)
        from app.routes.auth import validate_username
        ok, normalized = validate_username(username)
        if not ok:
            return False, normalized
        username = normalized

        users = self._load_users()
        username_lower = username.lower()

        if username_lower in users:
            return False, "Username already exists"

        # Check if this is the first user being created (other than default admin)
        should_remove_default_admin = False
        if len(users) == 1 and 'admin' in users:
            # Only admin user exists - check if it's the default one
            admin_user = users.get('admin', {})
            if admin_user and self._is_default_admin_user(admin_user):
                should_remove_default_admin = True
                _log_user_message(f"🔄 Replacing default admin user with new user: {username}")

        # Also check if we have multiple users but one is default admin (cleanup opportunity)
        elif len(users) > 1 and 'admin' in users:
            admin_user = users.get('admin', {})
            if admin_user and self._is_default_admin_user(admin_user):
                # We have other users and a default admin - remove the default admin
                should_remove_default_admin = True
                _log_user_message(f"🧹 Removing default admin user - keeping existing users and adding: {username}")

        # Add new user
        users[username_lower] = {
            'username': username,
            'password_hash': generate_password_hash(password),
            'preferences': self._default_preferences()
        }

        # Remove default admin if this is the first real user
        if should_remove_default_admin:
            del users['admin']
            _log_user_message(f"✅ Removed default admin user - {username} is now the primary user")

        # Save to file
        try:
            self._save_users(users)
            self._users_cache = users
            if should_remove_default_admin:
                return True, f"User {username} created successfully (replaced default admin user)"
            else:
                return True, "User created successfully"
        except Exception as e:
            return False, f"Error creating user: {e}"

    def _is_default_admin_user(self, user):
        """
        Check if a user appears to be the default admin user.

        Args:
            user (dict): User dictionary to check

        Returns:
            bool: True if this looks like the default admin user
        """
        if not user:
            return False

        # Check if this user was created with default preferences and admin123 password
        username = user.get('username', '').lower()
        preferences = user.get('preferences', {})
        password_hash = user.get('password_hash', '')

        # Default admin characteristics
        is_admin_username = username == 'admin'
        has_default_prefs = preferences == self._default_preferences()

        # Additional check: verify if password is admin123
        is_default_password = False
        if password_hash:
            try:
                is_default_password = check_password_hash(password_hash, 'admin123')
            except Exception:
                is_default_password = False

        # All three must match for default admin
        return is_admin_username and has_default_prefs and is_default_password

    def delete_user(self, username):
        """
        Permanently delete a user.

        Args:
            username (str): The username of the user to delete.

        Returns:
            tuple: (bool, str) success status and message.
        """
        users = self._load_users()
        username_lower = username.lower()

        if username_lower not in users:
            return False, "User not found"

        # Prevent deleting the last user
        if len(users) <= 1:
            return False, "Cannot delete the last user"

        # Delete user
        del users[username_lower]

        # Save to file
        try:
            self._save_users(users)
            self._users_cache = users
            return True, "User deleted successfully"
        except Exception as e:
            return False, f"Error deleting user: {e}"

    def get_preferences(self, username):
        """
        Get user preferences.

        Args:
            username (str): The username to get preferences for.

        Returns:
            dict: User preferences with defaults if not set.
        """
        user = self.get_user(username)
        if user:
            prefs = user.get('preferences', {}).copy()
            for key, value in self.DEFAULT_PREFERENCES.items():
                prefs.setdefault(key, value)
            return prefs
        return None

    def update_preferences(self, username, preferences):
        """
        Update user preferences.

        Args:
            username (str): The username to update preferences for.
            preferences (dict): Dictionary of preference key-value pairs.

        Returns:
            tuple: (bool, str) success status and message.
        """
        users = self._load_users()
        username_lower = username.lower()

        if username_lower not in users:
            return False, "User not found"

        # Initialize preferences if not present
        if 'preferences' not in users[username_lower]:
            users[username_lower]['preferences'] = self._default_preferences()

        # Update only provided preferences
        users[username_lower]['preferences'].update(preferences)

        # Save to file
        try:
            self._save_users(users)
            self._users_cache = users
            return True, "Preferences updated successfully"
        except Exception as e:
            return False, f"Error saving preferences: {e}"

    def cleanup_default_admin(self):
        """
        Manually remove the default admin user if it exists alongside other users.

        Returns:
            tuple: (bool, str) success status and message.
        """
        users = self._load_users()

        _log_user_message(f"🔍 Checking for default admin cleanup. Current users: {list(users.keys())}")

        if 'admin' not in users:
            return False, "No admin user found"

        admin_user = users.get('admin', {})
        if not self._is_default_admin_user(admin_user):
            return False, "Admin user exists but is not the default admin (has custom password/preferences)"

        if len(users) <= 1:
            return False, "Cannot remove admin user - it's the only user"

        # Remove default admin
        del users['admin']
        _log_user_message(f"🧹 Removing default admin user. Remaining users: {list(users.keys())}")

        try:
            self._save_users(users)
            self._users_cache = users
            return True, f"Default admin user removed. Remaining users: {[u['username'] for u in users.values()]}"
        except Exception as e:
            return False, f"Error removing admin user: {e}"

    def debug_users(self):
        """
        Debug method to inspect current user state.

        Returns:
            dict: Debug information about current users.
        """
        users = self._load_users()
        debug_info = {
            'total_users': len(users),
            'user_keys': list(users.keys()),
            'users_detail': {}
        }

        for key, user in users.items():
            is_default = self._is_default_admin_user(user) if key == 'admin' else False
            debug_info['users_detail'][key] = {
                'username': user.get('username', 'N/A'),
                'has_default_prefs': user.get('preferences', {}) == self._default_preferences(),
                'is_default_admin': is_default
            }

        return debug_info

    def clear_cache(self):
        """
        Clear the user cache and force reload from disk on next access.

        Use this when the user file has been modified externally.
        """
        self._users_cache = None
        self._last_modified = None
        _log_user_message("🔄 User cache cleared - will reload from disk")

    def is_admin(self, username):
        """Return True if ``username`` has administrator privileges.

        Admin rule (evaluated in order):
        1. User has ``is_admin: True`` in their stored record, OR
        2. No user has ``is_admin`` set AND this is the only user
           (single-tenant bootstrap), OR
        3. No user has ``is_admin`` set AND this is the alphabetically-first
           username (legacy deployments before the flag existed).

        Returns False for an unknown username or when outside both rules.
        """
        if not username:
            return False
        users = self._load_users()
        key = username.lower()
        user = users.get(key)
        if not user:
            return False

        # Rule 1: explicit flag takes precedence
        if user.get('is_admin') is True:
            return True

        # If any user carries the flag, only flagged users are admins
        any_flagged = any(u.get('is_admin') is True for u in users.values())
        if any_flagged:
            return False

        # Rule 2: single-user deployment — that user is admin
        if len(users) == 1:
            return True

        # Rule 3: legacy fallback — first user sorted by lowercase key
        first_key = sorted(users.keys())[0]
        return key == first_key

    def set_admin(self, username, is_admin=True):
        """Grant or revoke admin on a user.

        Returns (bool, str).
        """
        users = self._load_users()
        key = (username or '').lower()
        if key not in users:
            return False, "User not found"
        users[key]['is_admin'] = bool(is_admin)
        try:
            self._save_users(users)
            self._users_cache = users
            return True, ("Granted admin" if is_admin else "Revoked admin")
        except Exception as e:
            return False, f"Error updating admin flag: {e}"


# Global user manager instance
user_manager = UserManager()

# Note: Cache clear removed from module level to prevent initialization issues

def force_reload_global_user_manager():
    """
    Force the global user_manager instance to reload user data from disk.

    This is useful when the user_preferences.json file has been modified externally
    and we need to clear any cached data.
    """
    global user_manager
    user_manager.clear_cache()
    # Force a fresh load
    user_manager._load_users()
    _log_user_message("🔄 Global user_manager cache cleared and reloaded from disk")
