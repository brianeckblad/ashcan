"""
Application security middleware and protection.

Provides:
- IP-based rate limiting and blocking
- Attack pattern detection (.env, config files, SQL injection, etc.)
- Automatic IP banning for malicious activity
- Request validation and sanitization
- Security headers
"""
import time
import re
from collections import defaultdict
from datetime import datetime
from flask import request, abort, g, current_app
from functools import wraps
from pathlib import Path
from typing import Optional
import json


class IPBlocklist:
    """
    Manages blocked IPs with expiration times.

    Stores blocked IPs in memory and optionally persists to disk.
    Supports automatic expiration and manual unblocking.
    """

    def __init__(self, storage_path=None):
        """
        Initialize the blocklist.

        Args:
            storage_path: Optional path to persist blocklist (e.g., 'instance/blocked_ips.json')
        """
        self.blocked_ips = {}  # {ip: expiration_timestamp}
        self.storage_path = Path(storage_path) if storage_path else None
        self._load_from_disk()

    def _load_from_disk(self):
        """Load blocked IPs from disk if storage path is configured."""
        if self.storage_path and self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    # Only load non-expired blocks
                    now = time.time()
                    self.blocked_ips = {
                        ip: exp for ip, exp in data.items()
                        if exp > now
                    }
            except Exception as e:
                print(f"Warning: Could not load IP blocklist: {e}")

    def _save_to_disk(self):
        """Save blocked IPs to disk if storage path is configured."""
        if self.storage_path:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.storage_path, 'w') as f:
                    json.dump(self.blocked_ips, f, indent=2)
            except Exception as e:
                print(f"Warning: Could not save IP blocklist: {e}")

    def block_ip(self, ip, duration_hours=24):
        """
        Block an IP address for specified duration.

        Args:
            ip: IP address to block
            duration_hours: How long to block (default: 24 hours)
        """
        expiration = time.time() + (duration_hours * 3600)
        self.blocked_ips[ip] = expiration
        self._save_to_disk()

        try:
            current_app.logger.warning(
                f"🚫 IP BLOCKED: {ip} for {duration_hours} hours (expires: {datetime.fromtimestamp(expiration)})"
            )
        except RuntimeError:
            print(f"🚫 IP BLOCKED: {ip} for {duration_hours} hours")

    def is_blocked(self, ip):
        """
        Check if an IP is currently blocked.

        Args:
            ip: IP address to check

        Returns:
            bool: True if blocked and not expired
        """
        if ip not in self.blocked_ips:
            return False

        # Check if block has expired
        if time.time() > self.blocked_ips[ip]:
            del self.blocked_ips[ip]
            self._save_to_disk()
            return False

        return True

    def unblock_ip(self, ip):
        """
        Manually unblock an IP address.

        Args:
            ip: IP address to unblock
        """
        if ip in self.blocked_ips:
            del self.blocked_ips[ip]
            self._save_to_disk()

    def get_blocked_ips(self):
        """
        Get all currently blocked IPs with expiration times.

        Returns:
            dict: {ip: expiration_datetime}
        """
        now = time.time()
        return {
            ip: datetime.fromtimestamp(exp)
            for ip, exp in self.blocked_ips.items()
            if exp > now
        }

    def cleanup_expired(self):
        """Remove all expired blocks."""
        now = time.time()
        expired = [ip for ip, exp in self.blocked_ips.items() if exp <= now]
        for ip in expired:
            del self.blocked_ips[ip]
        if expired:
            self._save_to_disk()


class RateLimiter:
    """
    Rate limiting tracker for IPs.

    Tracks request counts per IP and triggers blocking for excessive requests.
    """

    def __init__(self):
        """Initialize rate limiter."""
        self.requests = defaultdict(list)  # {ip: [timestamp, timestamp, ...]}
        self.last_cleanup = time.time()

    def _cleanup_old_requests(self):
        """Remove requests older than 1 hour to prevent memory bloat."""
        if time.time() - self.last_cleanup < 300:  # Cleanup every 5 minutes
            return

        cutoff = time.time() - 3600  # 1 hour ago
        for ip in list(self.requests.keys()):
            self.requests[ip] = [ts for ts in self.requests[ip] if ts > cutoff]
            if not self.requests[ip]:
                del self.requests[ip]

        self.last_cleanup = time.time()

    def record_request(self, ip):
        """
        Record a request from an IP.

        Args:
            ip: IP address making the request
        """
        self.requests[ip].append(time.time())
        self._cleanup_old_requests()

    def get_request_count(self, ip, window_seconds=60):
        """
        Get number of requests from IP in time window.

        Args:
            ip: IP address to check
            window_seconds: Time window in seconds (default: 60)

        Returns:
            int: Number of requests in window
        """
        if ip not in self.requests:
            return 0

        cutoff = time.time() - window_seconds
        recent = [ts for ts in self.requests[ip] if ts > cutoff]
        self.requests[ip] = recent  # Clean up old timestamps
        return len(recent)

    def is_rate_limited(self, ip, max_requests=100, window_seconds=60):
        """
        Check if IP has exceeded rate limit.

        Args:
            ip: IP address to check
            max_requests: Maximum allowed requests
            window_seconds: Time window for rate limit

        Returns:
            bool: True if rate limit exceeded
        """
        return self.get_request_count(ip, window_seconds) > max_requests


# Global instances (initialized in init_security_middleware)
ip_blocklist: Optional[IPBlocklist] = None
rate_limiter: Optional[RateLimiter] = None


# Suspicious patterns that indicate attack attempts
# NOTE: nginx already blocks most attack paths (wp-admin, phpmyadmin, .env, etc.)
# These patterns are a secondary check for requests that reach Flask.
# Do NOT include paths the app itself uses (e.g., /admin/analytics).
ATTACK_PATTERNS = [
    # Config/environment file access attempts
    r'\.env$',
    r'\.git/',
    r'\.aws/',
    r'config\.php',
    r'wp-config',
    r'\.htaccess',
    r'web\.config',

    # Common vulnerability scanners / CMS probes
    r'/phpmyadmin',
    r'/phpMyAdmin',
    r'/mysql',
    r'/dbadmin',
    r'/wp-admin',
    r'/wp-login\.php',
    r'/xmlrpc\.php',
    r'/administrator',

    # Path traversal
    r"\.\./",
    r"\.\.\\",

    # SQL injection (query-string only — checked separately)
    r"union.*select",
    r"concat\(.*\)",
    r"--\s",
]

# Compile patterns for performance
COMPILED_ATTACK_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in ATTACK_PATTERNS]


def is_attack_attempt(request_path, query_string=''):
    """
    Check if request appears to be an attack attempt.

    Args:
        request_path: The request path
        query_string: Query string parameters

    Returns:
        tuple: (is_attack: bool, matched_pattern: str or None)
    """
    combined = f"{request_path}?{query_string}"

    for pattern in COMPILED_ATTACK_PATTERNS:
        if pattern.search(combined):
            return True, pattern.pattern

    return False, None


def get_real_ip(request):
    """
    Get the real client IP, accounting for reverse proxies.

    Priority order:
    1. X-Forwarded-For (first IP, from proxy)
    2. X-Real-IP
    3. request.remote_addr

    Args:
        request: Flask request object

    Returns:
        str: Client IP address
    """
    # Proxies set X-Forwarded-For
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        # Get first IP (client), not last (proxy)
        return x_forwarded_for.split(',')[0].strip()

    # Fallback to X-Real-IP
    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip:
        return x_real_ip.strip()

    # Final fallback to remote_addr
    return request.remote_addr


def security_middleware():
    """
    Main security middleware - runs before every request.

    Checks:
    1. IP blocklist (only for previously banned repeat offenders)
    2. Attack pattern detection (rejects request, does NOT auto-block)
    3. Rate limiting (rejects request, does NOT auto-block)
    """
    # Get real client IP
    client_ip = get_real_ip(request)
    g.client_ip = client_ip

    # Check if IP is blocked
    if ip_blocklist and ip_blocklist.is_blocked(client_ip):
        current_app.logger.warning(f"Blocked IP attempted access: {client_ip} - {request.path}")
        abort(403, description="Access denied")

    # Record request for rate limiting
    if rate_limiter:
        rate_limiter.record_request(client_ip)

    # Check for attack patterns — reject but do NOT auto-block
    is_attack, pattern = is_attack_attempt(request.path, request.query_string.decode('utf-8', errors='replace'))
    if is_attack:
        current_app.logger.warning(
            f"ATTACK DETECTED from {client_ip}: {request.method} {request.path} "
            f"(matched: {pattern})"
        )
        # Only block if this IP has triggered 5+ attack patterns in the last minute
        if rate_limiter:
            attack_key = f"attack_{client_ip}"
            rate_limiter.requests[attack_key].append(time.time())
            attack_count = rate_limiter.get_request_count(attack_key, 60)
            if attack_count >= 5 and ip_blocklist:
                ip_blocklist.block_ip(client_ip, duration_hours=1)
                current_app.logger.warning(f"IP blocked after {attack_count} attack attempts: {client_ip}")

        abort(403, description="Access denied")

    # Rate limiting: 600 requests per minute per IP — just 429, no auto-block
    if rate_limiter and rate_limiter.is_rate_limited(client_ip, max_requests=600, window_seconds=60):
        current_app.logger.warning(
            f"Rate limit exceeded: {client_ip} - {rate_limiter.get_request_count(client_ip, 60)} req/min"
        )

        abort(429, description="Too many requests")


def add_security_headers(response):
    """
    Add security headers to all responses.

    Args:
        response: Flask response object

    Returns:
        response: Modified response with security headers
    """
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'

    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'

    # X-XSS-Protection is deprecated and ignored by modern browsers — rely on CSP instead.

    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Content Security Policy
    # NOTE: CSP is set by Nginx (deployment/templates/nginx.conf.j2) which is
    # the single source of truth. Setting it here too creates a double-header
    # problem — the browser enforces BOTH, so the most restrictive one wins.
    # Only set CSP in Flask for local development (no Nginx).
    if current_app.debug:
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "style-src-elem 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self' https://*.amazonaws.com https://*.ebayimg.com; "
            "manifest-src 'self';"
        )

    # HTTPS-only (in production)
    if current_app.config.get('SESSION_COOKIE_SECURE'):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    return response


def init_security_middleware(app):
    """
    Initialize security middleware for the Flask app.

    Sets up:
    - IP blocklist (persisted to disk)
    - Rate limiter
    - Before-request security checks
    - After-request security headers

    Args:
        app: Flask application instance
    """
    global ip_blocklist, rate_limiter

    # Initialize blocklist with persistence
    storage_path = Path(app.instance_path) / 'blocked_ips.json'
    ip_blocklist = IPBlocklist(storage_path=storage_path)

    # Initialize rate limiter
    rate_limiter = RateLimiter()

    # Register middleware
    app.before_request(security_middleware)
    app.after_request(add_security_headers)

    app.logger.info("✓ Security middleware initialized")
    app.logger.info(f"  - IP blocklist: {len(ip_blocklist.get_blocked_ips())} IPs currently blocked")
    app.logger.info("  - Rate limiting: 600 requests/minute per IP")
    app.logger.info("  - Attack pattern detection: Enabled")



# Admin endpoint to manage blocklist
def create_security_admin_blueprint():
    """
    Create Flask blueprint for security administration.

    Provides endpoints to:
    - View blocked IPs
    - Unblock IPs
    - View rate limit status

    Must be registered in a protected admin area!
    """
    from flask import Blueprint, jsonify

    bp = Blueprint('security_admin', __name__, url_prefix='/admin/security')

    @bp.route('/blocked-ips')
    def list_blocked_ips():
        """List all currently blocked IPs."""
        if not ip_blocklist:
            return jsonify({'error': 'Blocklist not initialized'}), 500

        blocked = ip_blocklist.get_blocked_ips()
        return jsonify({
            'blocked_ips': [
                {'ip': ip, 'expires': exp.isoformat()}
                for ip, exp in blocked.items()
            ],
            'count': len(blocked)
        })

    @bp.route('/unblock/<ip>', methods=['POST'])
    def unblock_ip(ip):
        """Unblock a specific IP address."""
        if not ip_blocklist:
            return jsonify({'error': 'Blocklist not initialized'}), 500

        ip_blocklist.unblock_ip(ip)
        current_app.logger.info(f"✓ IP unblocked by admin: {ip}")
        return jsonify({'status': 'success', 'message': f'IP {ip} unblocked'})

    @bp.route('/rate-limit/<ip>')
    def check_rate_limit(ip):
        """Check rate limit status for an IP."""
        if not rate_limiter:
            return jsonify({'error': 'Rate limiter not initialized'}), 500

        count = rate_limiter.get_request_count(ip, 60)
        is_limited = rate_limiter.is_rate_limited(ip)

        return jsonify({
            'ip': ip,
            'requests_last_minute': count,
            'is_rate_limited': is_limited,
            'limit': 100
        })

    return bp

