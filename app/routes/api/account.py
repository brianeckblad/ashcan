"""Account routes - User account management and preferences.

This module handles:
- Password changes with verification
- Username changes with password verification
- User preferences (get/update)
- User CRUD operations (list, create, delete)
- User debugging and cache management

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import request, jsonify, current_app, session, Response
import traceback
from app.utils.logging_utils import safe_error_message
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required, admin_required
from app.models.user import user_manager, force_reload_global_user_manager
from app.config import get_secret
# Deferred import: user_secrets_service depends on AWS SDK which may not be
# available at startup; import lazily where used to avoid startup-time errors.
# from app.services.user_secrets_service import user_secrets_service


@api_bp.route('/account/change-password', methods=['POST'])
@login_required
@csrf_required
def change_password() -> Response:
    """Change user password with current password verification.

    Allows authenticated users to change their password by providing their
    current password for verification. Requires minimum 8 characters.

    Request Body (JSON):
        {
            "currentPassword": str,  # Current password for verification
            "newPassword": str       # New password (min 8 characters)
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether password change succeeded
            - message (str): Confirmation or error message
            - error (str, optional): Detailed error if failed

    Status Codes:
        200: Password changed successfully
        400: Missing fields or password too short
        401: Current password incorrect
        500: Server error during password change

    Example Request:
        {
            "currentPassword": "oldpass123",
            "newPassword": "newpass456"
        }

    Example Response:
        {
            "success": true,
            "message": "Password changed successfully"
        }

    Note:
        - Requires authentication (login_required)
        - Requires CSRF token
        - Password must be at least 8 characters
        - Current password must match for security
    """
    username = None
    try:
        data = request.get_json()
        current_password = data.get('currentPassword')
        new_password = data.get('newPassword')
        username = session.get('username')

        if not current_password or not new_password or not username:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # Validate new password length
        if len(new_password) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400

        # Change password using user_manager
        success, message = user_manager.change_password(username, current_password, new_password)

        if success:
            current_app.logger.info(f"[User: {username}] Password changed successfully")
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 401

    except Exception as e:
        current_app.logger.error(f"[User: {username if 'username' in locals() else 'unknown'}] Error changing password: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while changing password'}), 500


@api_bp.route('/account/change-username', methods=['POST'])
@login_required
@csrf_required
def change_username() -> Response:
    """Change username with password verification.

    Allows users to change their username. Requires password verification
    for security. Updates session with new username on success.

    Request Body (JSON):
        {
            "newUsername": str,  # Desired new username (min 3 characters)
            "password": str      # Current password for verification
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether username change succeeded
            - message (str): Confirmation message
            - newUsername (str): New username (on success)
            - error (str, optional): Error message if failed

    Status Codes:
        200: Username changed successfully
        400: Missing required fields
        401: Password incorrect or username taken
        500: Server error

    Example Request:
        {
            "newUsername": "newusername",
            "password": "mypassword"
        }

    Example Response:
        {
            "success": true,
            "message": "Username changed successfully",
            "newUsername": "newusername"
        }

    Note:
        - Password verification required
        - Username must be unique
        - Session automatically updated with new username
        - Minimum 3 characters for username
    """
    current_username = None
    try:
        data = request.get_json()
        new_username = data.get('newUsername')
        password = data.get('password')
        current_username = session.get('username')

        if not new_username or not password or not current_username:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # Change username using user manager (handles verification)
        success, message = user_manager.change_username(current_username, password, new_username)

        if success:
            # Update session with new username
            session['username'] = new_username
            current_app.logger.info(f"[User: {current_username}] Username changed to {new_username}")
            return jsonify({'success': True, 'message': message, 'newUsername': new_username}), 200
        else:
            return jsonify({'success': False, 'error': message}), 401

    except Exception as e:
        current_app.logger.error(f"[User: {current_username if 'current_username' in locals() else 'unknown'}] Error changing username: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while changing username'}), 500


@api_bp.route('/account/preferences', methods=['GET'])
@login_required
def get_preferences() -> Response:
    """Get user preferences for authenticated user.

    Retrieves all saved preferences for the current user including display
    settings, eBay defaults, and pagination preferences.

    Returns:
        Response: Flask JSON response containing:
            - timezone (str): User timezone
            - mobile_per_page (int): Items per page on mobile
            - desktop_per_page (int): Items per page on desktop
            - default_sort (str): Default sort order
            - micro_card_size (int): Bulk action card size (40-100%)
            - ebay_format (str): Default eBay listing format
            - ebay_duration (str): Default eBay duration
            - ebay_listing_mode (str): Default listing mode
            - ebay_environment (str): eBay environment (production/sandbox)
            - ebay_location (str): Ship from location
            - ebay_postal_code (str): Postal code

    Status Codes:
        200: Successfully retrieved preferences
        500: Server error

    Example Response:
        {
            "timezone": "America/New_York",
            "mobile_per_page": 12,
            "desktop_per_page": 24,
            "default_sort": "sku_asc",
            "ebay_format": "FixedPrice",
            "ebay_duration": "GTC",
            "ebay_listing_mode": "list",
            "ebay_environment": "production",
            "ebay_location": "New York, NY",
            "ebay_postal_code": "10001"
        }

    Note:
        - Returns default values if no preferences saved
        - Preferences are user-specific
        - Used to populate settings forms
    """
    """Get user preferences."""
    try:
        username = session.get('username')
        if not username:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401

        preferences = user_manager.get_preferences(username)
        if preferences is None:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        return jsonify({'success': True, 'preferences': preferences}), 200

    except Exception as e:
        username = session.get('username', 'unknown')
        current_app.logger.error(f"[User: {username}] Error getting preferences: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while getting preferences'}), 500


@api_bp.route('/account/preferences', methods=['POST'])
@login_required
@csrf_required
def update_preferences() -> Response:
    """Update user preferences for authenticated user.

    Saves user preferences including display settings, eBay defaults,
    and pagination settings. Merged with existing preferences.

    Request Body (JSON):
        {
            "preferences": {
                "timezone": str,
                "mobile_per_page": int,
                "desktop_per_page": int,
                "default_sort": str,
                "micro_card_size": int (40-100),
                "ebay_format": str,
                "ebay_duration": str,
                "ebay_listing_mode": str,
                "ebay_environment": str,
                "ebay_location": str,
                "ebay_postal_code": str
            }
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether update succeeded
            - message (str): Confirmation message
            - error (str, optional): Error if failed

    Status Codes:
        200: Preferences updated successfully
        400: Invalid request data
        401: Not authenticated
        500: Server error

    Example Request:
        {
            "preferences": {
                "desktop_per_page": 50,
                "ebay_environment": "sandbox"
            }
        }

    Example Response:
        {
            "success": true,
            "message": "Preferences updated successfully"
        }

    Note:
        - Only provided fields are updated (partial update)
        - Invalid fields are ignored
        - Changes apply immediately to user session
    """
    try:
        data = request.get_json()
        preferences = data.get('preferences')
        username = session.get('username')

        if not preferences or not username:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # Validate preferences
        valid_keys = ['timezone', 'mobile_per_page', 'desktop_per_page', 'default_sort',
                      'default_view', 'micro_card_size', 'ebay_format', 'ebay_duration',
                      'ebay_listing_mode', 'ebay_environment', 'ebay_location', 'ebay_postal_code']
        filtered_prefs = {k: v for k, v in preferences.items() if k in valid_keys}

        if not filtered_prefs:
            return jsonify({'success': False, 'error': 'No valid preferences provided'}), 400

        # Validate timezone
        if 'timezone' in filtered_prefs and filtered_prefs['timezone'] not in ['local', 'utc']:
            return jsonify({'success': False, 'error': 'Invalid timezone value'}), 400

        # Validate default_sort (must match account.html options)
        if 'default_sort' in filtered_prefs and filtered_prefs['default_sort'] not in [
            'sku_asc',
            'sku_desc',
            'title_asc',
            'title_desc',
            'price_asc',
            'price_desc',
        ]:
            return jsonify({'success': False, 'error': 'Invalid default_sort value'}), 400

        # Validate default_view
        if 'default_view' in filtered_prefs and filtered_prefs['default_view'] not in ['grid', 'list']:
            return jsonify({'success': False, 'error': 'Invalid default_view value'}), 400

        # Validate micro_card_size
        if 'micro_card_size' in filtered_prefs:
            try:
                size = int(filtered_prefs['micro_card_size'])
                if size < 40 or size > 100:
                    return jsonify({'success': False, 'error': 'Micro card size must be between 40 and 100'}), 400
                filtered_prefs['micro_card_size'] = size
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid micro card size value'}), 400

        # Validate eBay fields
        if 'ebay_format' in filtered_prefs:
            if filtered_prefs['ebay_format'] not in ['Auction', 'FixedPrice', 'StoresFixedPrice']:
                return jsonify({'success': False, 'error': 'Invalid eBay format'}), 400
        if 'ebay_duration' in filtered_prefs:
            if filtered_prefs['ebay_duration'] not in ['Days_1', 'Days_3', 'Days_5', 'Days_7', 'Days_10', 'Days_30', 'GTC']:
                return jsonify({'success': False, 'error': 'Invalid eBay duration'}), 400
        if 'ebay_listing_mode' in filtered_prefs:
            if filtered_prefs['ebay_listing_mode'] not in ['list', 'future']:
                return jsonify({'success': False, 'error': 'Invalid eBay listing mode'}), 400
        if 'ebay_environment' in filtered_prefs:
            if filtered_prefs['ebay_environment'] not in ['production', 'sandbox']:
                return jsonify({'success': False, 'error': 'Invalid eBay environment'}), 400
        if 'ebay_location' in filtered_prefs:
            if not filtered_prefs['ebay_location'] or len(filtered_prefs['ebay_location']) > 200:
                return jsonify({'success': False, 'error': 'Invalid eBay location'}), 400
        if 'ebay_postal_code' in filtered_prefs:
            if not filtered_prefs['ebay_postal_code'] or len(filtered_prefs['ebay_postal_code']) > 20:
                return jsonify({'success': False, 'error': 'Invalid eBay postal code'}), 400

        # Update preferences
        success, message = user_manager.update_preferences(username, filtered_prefs)

        if success:
            current_app.logger.info(f"[User: {username}] Preferences updated")
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 400

    except Exception as e:
        username = session.get('username', 'unknown')
        current_app.logger.error(f"[User: {username}] Error updating preferences: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while updating preferences'}), 500


@api_bp.route('/account/users', methods=['GET'])
@login_required
@admin_required
def list_users() -> Response:
    """List all users in the system.

    Returns list of all usernames and identifies current user.
    Used for user management and admin functions.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether list was retrieved
            - users (list): List of all usernames
            - currentUsername (str): Currently logged-in user
            - error (str, optional): Error if failed

    Status Codes:
        200: Successfully retrieved user list
        500: Server error

    Example Response:
        {
            "success": true,
            "users": ["admin", "user1", "user2"],
            "currentUsername": "admin"
        }

    Note:
        - Requires authentication
        - Used by admin interface
        - Shows all users regardless of permissions
    """
    try:
        users = user_manager.list_users()
        current_username = session.get('username')

        return jsonify({
            'success': True,
            'users': users,
            'currentUsername': current_username
        }), 200

    except Exception as e:
        current_username = session.get('username', 'unknown')
        current_app.logger.error(f"[User: {current_username}] Error listing users: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while listing users'}), 500


@api_bp.route('/account/users', methods=['POST'])
@login_required
@admin_required
@csrf_required
def create_user() -> Response:
    """Create a new user account.

    Creates new user with username and password. Username must be unique.
    Password must meet minimum length requirements.

    Request Body (JSON):
        {
            "username": str,  # Min 3 characters, unique
            "password": str   # Min 8 characters
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether user was created
            - message (str): Confirmation message
            - error (str, optional): Error if failed

    Status Codes:
        200: User created successfully
        400: Invalid username/password or user exists
        500: Server error

    Example Request:
        {
            "username": "newuser",
            "password": "securepass123"
        }

    Example Response:
        {
            "success": true,
            "message": "User created successfully"
        }

    Note:
        - Username must be at least 3 characters
        - Password must be at least 8 characters
        - Username must be unique
        - User data saved to instance/users.json
    """
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and password required'}), 400

        if len(username) < 3:
            return jsonify({'success': False, 'error': 'Username must be at least 3 characters'}), 400

        if len(password) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400

        success, message = user_manager.create_user(username, password)

        if success:
            admin_user = session.get('username', 'admin')
            current_app.logger.info(f"[Admin: {admin_user}] User {username} created")
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 400

    except Exception as e:
        admin_user = session.get('username', 'unknown')
        current_app.logger.error(f"[Admin: {admin_user}] Error creating user: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while creating user'}), 500


@api_bp.route('/account/users/<username>', methods=['DELETE'])
@login_required
@admin_required
@csrf_required
def delete_user(username: str) -> Response:
    """Delete a user account permanently.

    Removes user from system. Cannot delete your own account for safety.

    Path Parameters:
        username (str): Username to delete

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether deletion succeeded
            - message (str): Confirmation message
            - error (str, optional): Error if failed

    Status Codes:
        200: User deleted successfully
        400: Cannot delete self or invalid request
        404: User not found
        500: Server error

    Example Request:
        DELETE /account/users/olduser

    Example Response:
        {
            "success": true,
            "message": "User deleted successfully"
        }

    Warning:
        - This operation is permanent
        - Cannot delete your own account
        - No undo functionality

    Note:
        - Logged action for audit trail
        - Updates users.json immediately
        - Session remains valid for other users
    """
    try:
        current_username = session.get('username')

        # Prevent deleting yourself
        if username.lower() == current_username.lower():
            return jsonify({'success': False, 'error': 'Cannot delete your own account'}), 400

        success, message = user_manager.delete_user(username)

        if success:
            current_app.logger.info(f"[Admin: {current_username}] User {username} deleted")
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 400

    except Exception as e:
        current_username = session.get('username', 'unknown')
        current_app.logger.error(f"[Admin: {current_username}] Error deleting user: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while deleting user'}), 500


@api_bp.route('/account/debug-users', methods=['GET'])
@login_required
@admin_required
def debug_users() -> Response:
    """Debug endpoint to inspect user state and cache.

    Returns internal debug information about user manager state.
    Used for troubleshooting user authentication issues.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether debug info retrieved
            - debug (dict): Debug information including:
                - loaded_users: User data structure
                - cache_state: Cache information
                - file_stats: Users file information
            - error (str, optional): Error if failed

    Status Codes:
        200: Debug info retrieved
        500: Error getting debug info

    Example Response:
        {
            "success": true,
            "debug": {
                "loaded_users": {"admin": {...}},
                "cache_state": "active",
                "file_path": "/instance/users.json"
            }
        }

    Note:
        - For development/debugging only
        - May contain sensitive information
        - Should be restricted in production
    """
    try:
        debug_info = user_manager.debug_users()
        return jsonify({'success': True, 'debug': debug_info}), 200
    except Exception as e:
        admin_user = session.get('username', 'unknown')
        current_app.logger.error(f"[Admin: {admin_user}] Error debugging users: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/account/cleanup-admin', methods=['POST'])
@login_required
@admin_required
@csrf_required
def cleanup_default_admin() -> Response:
    """Manually trigger cleanup of default admin user.

    Removes the default 'admin' user if it exists with default password.
    Safety feature to ensure default credentials aren't left active.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether cleanup succeeded
            - message (str): Result message

    Status Codes:
        200: Cleanup completed (admin removed or didn't exist)
        400: Cleanup failed or admin has custom password
        500: Server error

    Example Response:
        {
            "success": true,
            "message": "Default admin removed successfully"
        }

    Note:
        - Only removes admin with default password
        - Safe to run multiple times
        - Logged for security audit
        - Custom admin passwords are preserved
    """
    try:
        admin_user = session.get('username', 'system')
        success, message = user_manager.cleanup_default_admin()
        if success:
            current_app.logger.info(f"[Admin: {admin_user}] Default admin cleanup: {message}")
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        admin_user = session.get('username', 'unknown')
        current_app.logger.error(f"[Admin: {admin_user}] Error cleaning up admin: {e}")
        return jsonify({'success': False, 'error': 'An error occurred during cleanup'}), 500


@api_bp.route('/account/clear-cache', methods=['POST'])
@login_required
@admin_required
@csrf_required
def clear_user_cache() -> Response:
    """Force clear user cache and reload from disk.

    Reloads user data from users.json file. Used when users.json is
    modified externally or cache becomes stale.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether cache was cleared
            - message (str): Confirmation with user count
            - users (list): List of usernames after reload
            - error (str, optional): Error if failed

    Status Codes:
        200: Cache cleared and reloaded
        500: Error reloading users

    Example Response:
        {
            "success": true,
            "message": "Global user cache cleared and reloaded. Current users: ['admin', 'user1']",
            "users": ["admin", "user1"]
        }

    Note:
        - Forces reload from disk
        - Updates global user manager instance
        - All sessions remain valid
        - Useful after manual users.json edits
    """
    try:

        # Force reload the global instance
        force_reload_global_user_manager()

        # Get fresh user data
        users = user_manager._load_users()

        return jsonify({
            'success': True,
            'message': f'Global user cache cleared and reloaded. Current users: {list(users.keys())}',
            'users': list(users.keys())
        }), 200
    except Exception as e:
        admin_user = session.get('username', 'unknown')
        current_app.logger.error(f"[Admin: {admin_user}] Error clearing cache: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/account/ebay-credentials', methods=['GET'])
@login_required
def get_ebay_credentials() -> Response:
    """Get eBay credentials status for the current user.

    Returns whether the user has eBay credentials configured and
    shows masked versions (last 4 characters only) for security.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether request succeeded
            - has_credentials (bool): Whether user has any credentials
            - production (dict): Production credential status
            - sandbox (dict): Sandbox credential status
            - error (str, optional): Error if failed

    Status Codes:
        200: Successfully retrieved credential status
        500: Server error

    Example Response:
        {
            "success": true,
            "has_credentials": true,
            "production": {
                "app_id": "****1234",
                "cert_id": "****5678",
                "dev_id": "****9abc",
                "token": "****def0"
            },
            "sandbox": {
                "app_id": "",
                "cert_id": "",
                "dev_id": "",
                "token": ""
            }
        }

    Note:
        - Only shows last 4 characters of credentials
        - Empty string if credential not set
        - Does not expose full credential values
    """
    try:
        from app.services.user_secrets_service import user_secrets_service  # Deferred: requires app context (AWS SDK)

        username = session.get('username')
        if not username:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401

        # Check if user-specific credentials exist
        has_user_credentials = user_secrets_service.check_credentials_exist(username)

        credentials = None
        source = None

        if has_user_credentials:
            # User has their own credentials in Secrets Manager
            credentials = user_secrets_service.get_user_ebay_credentials(username)
            source = 'user'
        else:
            # Fall back to app-level credentials (from main secret)
            app_creds = {
                'EBAY_PRODUCTION_APP_ID': get_secret('EBAY_PRODUCTION_APP_ID'),
                'EBAY_PRODUCTION_CERT_ID': get_secret('EBAY_PRODUCTION_CERT_ID'),
                'EBAY_PRODUCTION_DEV_ID': get_secret('EBAY_PRODUCTION_DEV_ID'),
                'EBAY_PRODUCTION_TOKEN': get_secret('EBAY_PRODUCTION_TOKEN'),
                'EBAY_SANDBOX_APP_ID': get_secret('EBAY_SANDBOX_APP_ID'),
                'EBAY_SANDBOX_CERT_ID': get_secret('EBAY_SANDBOX_CERT_ID'),
                'EBAY_SANDBOX_DEV_ID': get_secret('EBAY_SANDBOX_DEV_ID'),
                'EBAY_SANDBOX_TOKEN': get_secret('EBAY_SANDBOX_TOKEN'),
            }
            # Only treat as "has credentials" if at least one value is set
            if any(v for v in app_creds.values()):
                credentials = app_creds
                source = 'app'

        if not credentials:
            return jsonify({
                'success': True,
                'has_credentials': False,
                'production': {'app_id': '', 'cert_id': '', 'dev_id': '', 'token': ''},
                'sandbox': {'app_id': '', 'cert_id': '', 'dev_id': '', 'token': ''}
            }), 200

        def mask_credential(value):
            """Mask credential showing only last 4 characters."""
            if not value or len(value) < 4:
                return ''
            return '****' + value[-4:]

        return jsonify({
            'success': True,
            'has_credentials': True,
            'source': source,
            'production': {
                'app_id': mask_credential(credentials.get('EBAY_PRODUCTION_APP_ID')),
                'cert_id': mask_credential(credentials.get('EBAY_PRODUCTION_CERT_ID')),
                'dev_id': mask_credential(credentials.get('EBAY_PRODUCTION_DEV_ID')),
                'token': mask_credential(credentials.get('EBAY_PRODUCTION_TOKEN'))
            },
            'sandbox': {
                'app_id': mask_credential(credentials.get('EBAY_SANDBOX_APP_ID')),
                'cert_id': mask_credential(credentials.get('EBAY_SANDBOX_CERT_ID')),
                'dev_id': mask_credential(credentials.get('EBAY_SANDBOX_DEV_ID')),
                'token': mask_credential(credentials.get('EBAY_SANDBOX_TOKEN'))
            }
        }), 200

    except Exception as e:
        username = session.get('username', 'unknown')
        current_app.logger.error(f"[User: {username}] Error getting eBay credentials: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while getting eBay credentials'}), 500


@api_bp.route('/account/ebay-credentials', methods=['POST'])
@login_required
@csrf_required
def save_ebay_credentials() -> Response:
    """Save eBay API credentials for the current user.

    Securely stores user's eBay API credentials in AWS Secrets Manager.
    Only non-empty fields are updated (allows partial updates).

    Request Body (JSON):
        {
            "production": {
                "app_id": str (optional),
                "cert_id": str (optional),
                "dev_id": str (optional),
                "token": str (optional)
            },
            "sandbox": {
                "app_id": str (optional),
                "cert_id": str (optional),
                "dev_id": str (optional),
                "token": str (optional)
            }
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether save succeeded
            - message (str): Confirmation message
            - error (str, optional): Error if failed

    Status Codes:
        200: Credentials saved successfully
        400: Invalid request data
        401: Not authenticated
        500: Server error

    Example Request:
        {
            "production": {
                "app_id": "MyApp-12345",
                "cert_id": "abcd1234...",
                "dev_id": "dev1234...",
                "token": "v^1.1#..."
            },
            "sandbox": {}
        }

    Example Response:
        {
            "success": true,
            "message": "eBay credentials saved successfully"
        }

    Note:
        - Credentials stored in AWS Secrets Manager
        - Empty fields are not updated (preserves existing values)
        - Previous credentials retained if not provided
        - Invalidates eBay service credential cache for this user
    """
    try:
        from app.services.user_secrets_service import user_secrets_service  # Deferred: requires app context (AWS SDK)

        data = request.get_json()
        username = session.get('username')

        if not username:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401

        if not data:
            return jsonify({'success': False, 'error': 'Missing request data'}), 400

        production = data.get('production', {})
        sandbox = data.get('sandbox', {})

        # Get existing credentials if any
        existing = user_secrets_service.get_user_ebay_credentials(username) or {}

        # Build credentials dict, only updating non-empty fields
        credentials = {
            'production_app_id': production.get('app_id') if production.get('app_id') else existing.get('EBAY_PRODUCTION_APP_ID', ''),
            'production_cert_id': production.get('cert_id') if production.get('cert_id') else existing.get('EBAY_PRODUCTION_CERT_ID', ''),
            'production_dev_id': production.get('dev_id') if production.get('dev_id') else existing.get('EBAY_PRODUCTION_DEV_ID', ''),
            'production_token': production.get('token') if production.get('token') else existing.get('EBAY_PRODUCTION_TOKEN', ''),
            'sandbox_app_id': sandbox.get('app_id') if sandbox.get('app_id') else existing.get('EBAY_SANDBOX_APP_ID', ''),
            'sandbox_cert_id': sandbox.get('cert_id') if sandbox.get('cert_id') else existing.get('EBAY_SANDBOX_CERT_ID', ''),
            'sandbox_dev_id': sandbox.get('dev_id') if sandbox.get('dev_id') else existing.get('EBAY_SANDBOX_DEV_ID', ''),
            'sandbox_token': sandbox.get('token') if sandbox.get('token') else existing.get('EBAY_SANDBOX_TOKEN', ''),
        }

        # Save to AWS Secrets Manager
        success, message = user_secrets_service.save_user_ebay_credentials(username, credentials)

        if success:
            # Invalidate eBay service cache for this user
            try:
                from app.services.ebay_service import ebay_service  # Deferred: requires app context (AWS SDK)
                with ebay_service._cache_lock:
                    ebay_service._user_credentials_cache.pop(username, None)
                    ebay_service._user_tokens_cache.pop(username, None)
                current_app.logger.info(f"[User: {username}] Invalidated eBay credential cache")
            except Exception as cache_error:
                current_app.logger.warning(f"[User: {username}] Could not invalidate eBay cache: {cache_error}")

            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 500

    except Exception as e:
        username = session.get('username', 'unknown')
        current_app.logger.error(f"[User: {username}] Error saving eBay credentials: {e}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'An error occurred while saving eBay credentials'}), 500


@api_bp.route('/account/ebay-credentials', methods=['DELETE'])
@login_required
@csrf_required
def delete_ebay_credentials() -> Response:
    """Delete eBay API credentials for the current user.

    Removes all stored eBay credentials from AWS Secrets Manager.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether deletion succeeded
            - message (str): Confirmation message
            - error (str, optional): Error if failed

    Status Codes:
        200: Credentials deleted successfully
        401: Not authenticated
        500: Server error

    Example Response:
        {
            "success": true,
            "message": "eBay credentials deleted successfully"
        }

    Note:
        - Permanently deletes credentials from AWS
        - Cannot be undone
        - Clears eBay service credential cache
        - User will need to re-enter credentials to use eBay features
    """
    try:
        from app.services.user_secrets_service import user_secrets_service  # Deferred: requires app context (AWS SDK)

        username = session.get('username')

        if not username:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401

        # Delete from AWS Secrets Manager
        success, message = user_secrets_service.delete_user_ebay_credentials(username)

        if success:
            # Invalidate eBay service cache for this user
            try:
                from app.services.ebay_service import ebay_service  # Deferred: requires app context (AWS SDK)
                with ebay_service._cache_lock:
                    ebay_service._user_credentials_cache.pop(username, None)
                    ebay_service._user_tokens_cache.pop(username, None)
                current_app.logger.info(f"[User: {username}] Invalidated eBay credential cache after deletion")
            except Exception as cache_error:
                current_app.logger.warning(f"[User: {username}] Could not invalidate eBay cache: {cache_error}")

            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'success': False, 'error': message}), 500

    except Exception as e:
        username = session.get('username', 'unknown')
        current_app.logger.error(f"[User: {username}] Error deleting eBay credentials: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while deleting eBay credentials'}), 500

