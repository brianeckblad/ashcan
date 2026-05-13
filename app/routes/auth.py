"""Authentication routes and decorators."""
import re
import shutil
import time
from pathlib import Path
from functools import wraps
from urllib.parse import urlparse, urljoin

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, g, jsonify, current_app,
)
from app.models.user import user_manager

auth_bp = Blueprint('auth', __name__)


# Strict username format — alphanumeric, underscore, hyphen only; 3-32 chars.
# Prevents path traversal (/, \, .., :, NUL) and shell metacharacters when the
# username is used to build filesystem paths or S3 keys.
USERNAME_REGEX = re.compile(r'^[A-Za-z0-9_\-]{3,32}$')


def validate_username(username):
    """Return (True, normalized) if username is safe, otherwise (False, error_message).

    Applies a strict allow-list regex. Any username that fails here must never
    be used to construct a filesystem path, S3 key, or AWS Secrets Manager name.
    """
    if not isinstance(username, str):
        return False, "Username must be a string"
    candidate = username.strip()
    if not candidate:
        return False, "Username is required"
    if not USERNAME_REGEX.match(candidate):
        return False, ("Username must be 3-32 characters and contain only "
                       "letters, numbers, underscores, or hyphens")
    return True, candidate


def login_required(f):
    """
    Decorator that restricts access to authenticated users only.

    Checks if the user is logged in and their session is still valid.
    If not logged in, redirects to the login page. If the session was created
    before the application last restarted, invalidates the session for security.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        """Inner function that handles the login check logic."""
        from app import APP_START_TIME  # Deferred: avoids circular import

        # Check if user is logged in via session cookie
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                # For API requests, return JSON error instead of redirect
                return jsonify({'success': False, 'error': 'Session expired. Please log in again.'}), 401
            # For web pages, show login page
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))

        # Security check: Invalidate sessions that existed before app restart
        # This ensures stale sessions don't persist across deployments
        session_created = session.get('session_created', 0)
        if session_created < APP_START_TIME:
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Session expired after server restart. Please log in again.'}), 401
            flash('Your session expired after server restart. Please log in again.', 'warning')
            return redirect(url_for('auth.login'))

        # Store username in Flask's g object for use in logging and other contexts
        g.username = session.get('username', 'unknown')
        return f(*args, **kwargs)
    return decorated_function


def is_safe_url(target):
    """
    Verify that a redirect URL is safe and points to the same host.

    Prevents open redirect vulnerabilities by ensuring the target URL
    is on the same host as the current request.

    Args:
        target (str): The URL to validate.

    Returns:
        bool: True if the URL is safe, False otherwise.
    """
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    # Check that scheme and netloc match the current request
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc


def csrf_required(f):
    """
    Decorator that validates CSRF token for state-changing requests.

    Checks for a valid CSRF token in the session and compares it with
    the token provided in the request (via header or form). Only applies
    to POST, PUT, and DELETE requests which modify state.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        """Inner function that handles CSRF token validation."""
        # Only validate on state-changing requests
        if request.method in ['POST', 'PUT', 'DELETE']:
            # Get the stored token from the user's session
            token = session.get('_csrf_token')
            # Check for token in request headers (AJAX) or form data
            header_token = request.headers.get('X-CSRF-Token')
            form_token = request.form.get('_csrf_token')
            
            # Use either header or form token (provided_token)
            provided_token = header_token or form_token
            
            # Reject if token is missing or doesn't match
            if not token or token != provided_token:
                return jsonify({'success': False, 'error': 'Invalid or missing CSRF token'}), 403
                
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """
    Decorator that restricts access to admin users only.

    Must be layered AFTER login_required. Returns 403 if the current user
    is not flagged as admin. See ``UserManager.is_admin`` for the admin rule
    (explicit ``is_admin`` flag, single-user bootstrap, or first-created user).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = session.get('username')
        if not username or not user_manager.is_admin(username):
            current_app.logger.warning(
                f"Admin-only endpoint denied for user={username!r} path={request.path}"
            )
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Administrator privileges required'}), 403
            flash('Administrator privileges required.', 'error')
            return redirect(url_for('main.landing'))
        return f(*args, **kwargs)
    return decorated_function


def sync_not_locked(f):
    """
    Decorator that prevents operations during an active backup sync.

    Some operations like editing or deleting items should not be allowed
    while a backup sync is in progress to prevent data consistency issues.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from app.utils.sync_state import sync_state  # Deferred: avoids circular import
        # If a sync is currently running, reject the request
        if sync_state.is_locked():
            return jsonify({
                'success': False,
                'message': 'Operation unavailable - backup sync in progress. Please wait.'
            }), 503
        return f(*args, **kwargs)
    return decorated_function


def disk_space_required(min_percent=15):
    """
    Decorator that ensures sufficient disk space before allowing an operation.

    Checks the available disk space and rejects the request if available space
    falls below the specified percentage threshold. This prevents operations
    that could fail due to running out of disk space.

    Args:
        min_percent (int): Minimum required free disk percentage. Defaults to 15%.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get disk usage statistics
            instance_path = Path(current_app.instance_path)
            disk_usage = shutil.disk_usage(instance_path)
            # Calculate percentage of disk that is free
            disk_free_percent = (disk_usage.free / disk_usage.total) * 100 if disk_usage.total > 0 else 0

            # Reject if free space is below threshold
            if disk_free_percent < min_percent:
                return jsonify({
                    'success': False,
                    'message': f'Operation unavailable - disk space critically low ({disk_free_percent:.1f}% free).'
                }), 507
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handle login page display and authentication.

    GET: Display the login form.
    POST: Authenticate user credentials and create session.

    Brute-force defence: 10 failed attempts per IP per 15 minutes get a
    429 response. Successful logins reset the counter for that IP.
    """
    if request.method == 'POST':
        # Validate CSRF token on form submission
        token = session.get('_csrf_token')
        form_token = request.form.get('_csrf_token')
        if not token or token != form_token:
            flash('Invalid session. Please try again.', 'error')
            return redirect(url_for('auth.login'))

        # Throttle per-IP login attempts to slow brute-force password guessing
        from app.security import rate_limiter, get_real_ip  # Deferred: avoids circular import
        client_ip = get_real_ip(request)
        login_key = f"login_attempts_{client_ip}"
        if rate_limiter and rate_limiter.is_rate_limited(
            login_key, max_requests=10, window_seconds=900
        ):
            flash('Too many failed login attempts. Try again in 15 minutes.', 'error')
            return redirect(url_for('auth.login'))

        # Get username and password from form
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Verify credentials using user manager (case-insensitive username)
        if user_manager.verify_password(username, password):
            user = user_manager.get_user(username)
            # Create session for authenticated user — normalize to lowercase
            # so downstream path/S3 helpers see a single canonical value.
            session['logged_in'] = True
            canonical = (user['username'] or '').lower()
            session['username'] = canonical
            session['session_created'] = time.time()  # Track session creation time
            session.permanent = True
            session.pop('_csrf_token', None)  # Clear old CSRF token
            # Reset the failed-attempts counter for this IP on success
            if rate_limiter and login_key in rate_limiter.requests:
                rate_limiter.requests.pop(login_key, None)
            flash('Login successful!', 'success')

            # Redirect to the page they were trying to access, or to landing page
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('main.landing'))
        else:
            # Authentication failed — record this attempt against the IP
            if rate_limiter:
                rate_limiter.record_request(login_key)
            flash('Invalid username or password.', 'error')
            return redirect(url_for('auth.login'))

    # GET request - show login page
    # If already logged in, redirect to landing page
    if session.get('logged_in'):
        return redirect(url_for('main.landing'))

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """Clear the user session and log them out."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
