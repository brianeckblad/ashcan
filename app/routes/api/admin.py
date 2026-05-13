"""Admin routes - Application defaults and settings management.

This module handles:
- Getting admin default values for form fields
- Saving custom default values
- S3 backup of admin settings

All functions include type hints and comprehensive docstrings for better IDE support
and code maintainability.
"""
from flask import request, jsonify, current_app, Response
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required, admin_required
from app.services.s3_service import s3_service
from app.utils.defaults_helpers import get_app_defaults
from app.utils.logging_utils import safe_error_message, get_log_prefix
from app.utils.user_context import get_user_sku_file, get_current_username
from pathlib import Path
from datetime import datetime
import json


@api_bp.route('/admin/defaults', methods=['GET'])
@login_required
def get_admin_defaults() -> Response:
    """Get custom default values for form fields.

    Retrieves admin default settings from local storage or S3 backup.
    Falls back to built-in defaults if no custom values exist.

    The defaults include:
    - eBay listing settings (format, duration, mode, environment)
    - Condition details template
    - Description template
    - Photo details template
    - Shipping details template
    - Signoff message template

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether the operation succeeded
            - defaults (dict): Dictionary of default values
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved defaults
        500: Server error occurred

    Example Response:
        {
            "success": true,
            "defaults": {
                "ebay_format": "FixedPrice",
                "ebay_duration": "GTC",
                "ebay_listing_mode": "list",
                "condition_details": "NM – Like New...",
                ...
            }
        }

    Note:
        - First attempts to download from S3 if configured
        - Falls back to local file if S3 unavailable
        - Returns built-in defaults if no custom values found
    """
    try:
        # Try to restore from S3 first (for persistence across deployments)
        defaults_file = Path(current_app.instance_path) / 'app_defaults.json'

        # Check if S3 version exists and download if needed (only if S3 is configured)
        if current_app.config.get('S3_BUCKET') and current_app.config.get('S3_FOLDER'):
            try:
                s3_key = f'{current_app.config["S3_FOLDER"]}/config/app_defaults.json'
                # Try to download from S3 if file doesn't exist locally
                if not defaults_file.exists():
                    if s3_service.download_file(s3_key, str(defaults_file)):
                        pass
            except Exception as s3_err:
                # S3 restore failed, continue with local file or built-in defaults
                pass

        # Use the helper function to get defaults
        defaults = get_app_defaults()

        return jsonify({'success': True, 'defaults': defaults})
    except Exception as e:
        current_app.logger.error(f"Error loading app defaults: {e}", exc_info=True)
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/admin/defaults', methods=['POST'])
@login_required
@admin_required
@csrf_required
def save_admin_defaults() -> Response:
    """Save custom default values for form fields.

    Saves admin default settings to local storage and backs up to S3 (if configured).
    These defaults will be applied when creating new comic entries.

    Request Body (JSON):
        {
            "defaults": {
                "ebay_format": str,
                "ebay_duration": str,
                "ebay_listing_mode": str,
                "ebay_environment": str,
                "condition_details": str,
                "description": str,
                "photos_details": str,
                "shipping_details": str,
                "signoff": str
            }
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether the save succeeded
            - message (str): Success message
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully saved defaults
        500: Server error occurred

    Example Response:
        {
            "success": true,
            "message": "Defaults saved successfully"
        }

    Note:
        - Saves to instance/app_defaults.json
        - Automatically backs up to S3 if configured
        - S3 backup failure won't prevent local save
    """
    try:
        data = request.get_json()
        defaults = data.get('defaults', {})

        # Save to instance folder
        defaults_file = Path(current_app.instance_path) / 'app_defaults.json'
        defaults_file.parent.mkdir(parents=True, exist_ok=True)

        with open(defaults_file, 'w') as f:
            json.dump(defaults, f, indent=2)

        # Backup to S3 for persistence across deployments (only if S3 is configured)
        if current_app.config.get('S3_BUCKET') and current_app.config.get('S3_FOLDER'):
            try:
                s3_key = f'{current_app.config["S3_FOLDER"]}/config/app_defaults.json'
                s3_service.client().upload_file(
                    str(defaults_file),
                    current_app.config['S3_BUCKET'],
                    s3_key
                )
            except Exception as s3_err:
                current_app.logger.warning(f"⚠️  Failed to backup app_defaults to S3: {s3_err}")

        return jsonify({'success': True, 'message': 'Defaults saved successfully'})

    except Exception as e:
        current_app.logger.error(f"Error saving app defaults: {e}")
        return jsonify({'success': False, 'error': 'Failed to save defaults'}), 500


# ============================================================================
# Security Administration Endpoints
# ============================================================================

@api_bp.route('/admin/security/blocked-ips', methods=['GET'])
@login_required
@admin_required
def get_blocked_ips() -> Response:
    """Get list of currently blocked IP addresses.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether the operation succeeded
            - blocked_ips (list): List of blocked IPs with expiration times
            - count (int): Number of blocked IPs
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved blocked IPs
        500: Server error occurred
    """
    try:
        from app.security import ip_blocklist  # Deferred: avoids circular import

        if not ip_blocklist:
            return jsonify({'success': False, 'error': 'Security module not initialized'}), 500

        blocked = ip_blocklist.get_blocked_ips()

        return jsonify({
            'success': True,
            'blocked_ips': [
                {
                    'ip': ip,
                    'expires': exp.isoformat(),
                    'expires_in_hours': round((exp - datetime.now()).total_seconds() / 3600, 1)
                }
                for ip, exp in blocked.items()
            ],
            'count': len(blocked)
        })

    except Exception as e:
        current_app.logger.error(f"Error getting blocked IPs: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve blocked IPs'}), 500


@api_bp.route('/admin/security/unblock-ip', methods=['POST'])
@login_required
@admin_required
@csrf_required
def unblock_ip() -> Response:
    """Unblock a specific IP address.

    Request Body:
        {
            "ip": "192.168.1.1"
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether the operation succeeded
            - message (str): Success/error message
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully unblocked IP
        400: Invalid request
        500: Server error occurred
    """
    try:
        from app.security import ip_blocklist  # Deferred: avoids circular import

        if not ip_blocklist:
            return jsonify({'success': False, 'error': 'Security module not initialized'}), 500

        data = request.get_json()
        ip = data.get('ip')

        if not ip:
            return jsonify({'success': False, 'error': 'IP address required'}), 400

        ip_blocklist.unblock_ip(ip)
        current_app.logger.info(f"✓ IP unblocked by admin: {ip}")

        return jsonify({'success': True, 'message': f'IP {ip} has been unblocked'})

    except Exception as e:
        current_app.logger.error(f"Error unblocking IP: {e}")
        return jsonify({'success': False, 'error': 'Failed to unblock IP'}), 500


@api_bp.route('/admin/security/rate-limit/<ip>', methods=['GET'])
@login_required
@admin_required
def check_rate_limit(ip: str) -> Response:
    """Check rate limit status for a specific IP address.

    Args:
        ip: IP address to check

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether the operation succeeded
            - ip (str): IP address checked
            - requests_last_minute (int): Number of requests in last minute
            - is_rate_limited (bool): Whether IP is currently rate limited
            - limit (int): Maximum requests allowed per minute
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully checked rate limit
        500: Server error occurred
    """
    try:
        from app.security import rate_limiter  # Deferred: avoids circular import

        if not rate_limiter:
            return jsonify({'success': False, 'error': 'Security module not initialized'}), 500

        count = rate_limiter.get_request_count(ip, 60)
        is_limited = rate_limiter.is_rate_limited(ip, max_requests=100, window_seconds=60)

        return jsonify({
            'success': True,
            'ip': ip,
            'requests_last_minute': count,
            'is_rate_limited': is_limited,
            'limit': 100
        })

    except Exception as e:
        current_app.logger.error(f"Error checking rate limit: {e}")
        return jsonify({'success': False, 'error': 'Failed to check rate limit'}), 500


@api_bp.route('/admin/security/stats', methods=['GET'])
@login_required
@admin_required
def get_security_stats() -> Response:
    """Get overall security statistics.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether the operation succeeded
            - stats (dict): Security statistics including:
                - blocked_ips_count (int): Number of currently blocked IPs
                - total_requests_tracked (int): Total IPs being tracked
                - attack_patterns_count (int): Number of attack patterns detected
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved stats
        500: Server error occurred
    """
    try:
        from app.security import ip_blocklist, rate_limiter, ATTACK_PATTERNS  # Deferred: avoids circular import

        stats = {}

        if ip_blocklist:
            stats['blocked_ips_count'] = len(ip_blocklist.get_blocked_ips())
        else:
            stats['blocked_ips_count'] = 0

        if rate_limiter:
            stats['total_requests_tracked'] = len(rate_limiter.requests)
        else:
            stats['total_requests_tracked'] = 0

        stats['attack_patterns_count'] = len(ATTACK_PATTERNS)

        return jsonify({
            'success': True,
            'stats': stats
        })

    except Exception as e:
        current_app.logger.error(f"Error getting security stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve security stats'}), 500


@api_bp.route('/admin/sku/current', methods=['GET'])
@login_required
def get_current_sku() -> Response:
    """Get the current SKU value for the logged-in user.

    Returns:
        Response: JSON with current SKU value
    """
    try:

        username = get_current_username()
        sku_file = get_user_sku_file()

        if sku_file.exists():
            with open(sku_file, 'r') as f:
                current_sku = int(f.read().strip())
        else:
            current_sku = 1000  # Default

        return jsonify({
            'success': True,
            'sku': current_sku,
            'username': username
        })
    except Exception as e:
        current_app.logger.error(f"Error getting current SKU: {e}")
        return jsonify({'success': False, 'error': 'Failed to get current SKU'}), 500


@api_bp.route('/admin/sku/update', methods=['POST'])
@login_required
@csrf_required
def update_sku() -> Response:
    """Update the SKU starting value for the logged-in user.

    Request Body:
        {
            "sku": 2000  // New SKU value (integer)
        }

    Returns:
        Response: JSON with success status
    """
    try:
        username = get_current_username()
        data = request.get_json()

        if not data or 'sku' not in data:
            return jsonify({'success': False, 'error': 'SKU value required'}), 400

        try:
            new_sku = int(data['sku'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'SKU must be a valid integer'}), 400

        if new_sku < 1:
            return jsonify({'success': False, 'error': 'SKU must be greater than 0'}), 400

        # Update SKU file
        sku_file = get_user_sku_file()
        sku_file.parent.mkdir(parents=True, exist_ok=True)

        # Read current value for logging
        old_sku = 1000
        if sku_file.exists():
            try:
                with open(sku_file, 'r') as f:
                    old_sku = int(f.read().strip())
            except (ValueError, IOError):
                pass

        # Write new value
        with open(sku_file, 'w') as f:
            f.write(f'{new_sku}\n')

        # Backup to S3
        s3_service.backup_sku_to_s3(sku_file)

        current_app.logger.info(f"{get_log_prefix()}Updated SKU from {old_sku} to {new_sku}")

        return jsonify({
            'success': True,
            'message': f'SKU updated to {new_sku}',
            'old_sku': old_sku,
            'new_sku': new_sku
        })

    except Exception as e:
        current_app.logger.error(f"{get_log_prefix()}Error updating SKU: {e}")
        return jsonify({'success': False, 'error': 'Failed to update SKU'}), 500

