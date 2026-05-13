"""Utility helper functions for common tasks."""
import time
import secrets
from pathlib import Path
from flask import session
from werkzeug.utils import secure_filename


def generate_unique_filename(original_filename):
    """
    Create a unique filename by appending a timestamp to the base name.

    This ensures that multiple uploads of files with the same name don't
    overwrite each other. Sanitizes the original filename to prevent
    directory traversal attacks or invalid character issues.

    Args:
        original_filename (str): The original filename provided by the user.

    Returns:
        str: A unique filename with timestamp appended before the extension.
    """
    # Get current time in milliseconds for uniqueness
    timestamp = str(int(time.time() * 1000))
    # Sanitize the filename to prevent security issues (directory traversal,
    # NUL bytes, leading dots, etc.). ``secure_filename`` may return an empty
    # string for input that is entirely non-ASCII or punctuation, so we fall
    # back to a generic stem.
    filename = secure_filename(original_filename or '') or 'upload'
    # Split into name and extension; clamp the extension to a short
    # alphanumeric tail so a crafted filename like "x.<200KB of dots>" cannot
    # blow up filesystem path limits.
    if '.' in filename:
        name, ext = filename.rsplit('.', 1)
    else:
        name, ext = filename, ''
    name = (name or 'upload')[:100]
    ext = ''.join(c for c in ext if c.isalnum())[:8].lower()
    return f"{name}_{timestamp}.{ext}" if ext else f"{name}_{timestamp}"


def get_directory_size(path):
    """
    Calculate the total size of all files in a directory.

    Recursively walks the directory tree and sums the size of all files.
    Returns 0 if the directory doesn't exist or is inaccessible.

    Args:
        path (str or Path): Path to the directory to measure.

    Returns:
        int: Total size in bytes.
    """
    path = Path(path)
    total = 0
    try:
        # Check if path exists and is a directory
        if path.exists() and path.is_dir():
            # Recursively iterate through all files
            for item in path.rglob('*'):
                # Only count files, not directories
                if item.is_file():
                    total += item.stat().st_size
    except Exception:
        # Silently return 0 if any error occurs (e.g., permission denied)
        pass
    return total


def generate_csrf_token():
    """
    Generate and store a CSRF token in the user's session.

    If a token already exists in the session, returns that token.
    Otherwise, generates a new cryptographically secure token and stores it.

    Returns:
        str: The CSRF token (existing or newly generated).
    """
    # Check if token already exists in session
    if '_csrf_token' not in session:
        # Generate new secure token using secrets module
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def is_giveaway(title, listing_type=None):
    """Return True when an item should be treated as a giveaway.

    Canonical detection uses ``Listing Type == 'Giveaway'``. For backwards
    compatibility with older rows, the legacy title-prefix convention
    (``'G-'`` or ``'G - '``) is still honored as a fallback.

    Args:
        title (str): Comic title.
        listing_type (str, optional): Canonical listing type value.

    Returns:
        bool: True if the item is a giveaway.
    """
    if str(listing_type or '').strip().lower() == 'giveaway':
        return True

    upper = (title or '').upper()
    return upper.startswith('G-') or upper.startswith('G - ')

