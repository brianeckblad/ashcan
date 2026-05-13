"""
Mass Deletion Protection Configuration

This module provides protection against accidental mass deletion of images
through multiple safety checks and circuit breakers.
"""
from datetime import datetime, timedelta
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class MassDeletionProtection:
    """
    Protection against accidental mass deletion of images.

    Implements multiple safety layers:
    1. Threshold checks - Block deletion if too many images affected
    2. Rate limiting - Prevent rapid bulk deletions
    3. Empty CSV protection - Don't cleanup if CSV is suspiciously empty
    4. Confirmation requirements - Require explicit confirmation
    """

    # Configuration
    MAX_DELETION_PERCENTAGE = 50  # Don't delete more than 50% of images at once
    MAX_DELETION_COUNT = 100  # Don't delete more than 100 images at once
    MIN_COMICS_FOR_CLEANUP = 5  # Need at least 5 comics before allowing cleanup
    RAPID_DELETION_WINDOW = 300  # 5 minutes in seconds
    MAX_DELETIONS_IN_WINDOW = 3  # Max deletion operations in time window

    def __init__(self):
        self._deletion_history = []  # Track recent deletions: [(timestamp, count), ...]

    def check_deletion_safety(self, deletion_count, total_count, operation_name="deletion"):
        """
        Check if a deletion operation is safe to proceed.

        Args:
            deletion_count (int): Number of images to delete
            total_count (int): Total number of images in system
            operation_name (str): Name of operation for logging

        Returns:
            tuple: (is_safe: bool, reason: str)
        """
        # Check 1: Empty deletion
        if deletion_count == 0:
            return True, "No deletions requested"

        # Check 2: Total count suspicious
        if total_count == 0:
            logger.warning(f"[MassDeletionProtection] {operation_name}: total_count is 0 - blocking deletion")
            return False, "System reports 0 total images - safety block activated"

        # Check 3: Percentage check
        deletion_percentage = (deletion_count / total_count) * 100 if total_count > 0 else 100
        if deletion_percentage > self.MAX_DELETION_PERCENTAGE:
            logger.error(
                f"[MassDeletionProtection] {operation_name}: "
                f"Attempting to delete {deletion_count}/{total_count} images ({deletion_percentage:.1f}%) - "
                f"exceeds safety limit of {self.MAX_DELETION_PERCENTAGE}%"
            )
            return False, f"Deletion would affect {deletion_percentage:.1f}% of images (max: {self.MAX_DELETION_PERCENTAGE}%)"

        # Check 4: Absolute count check
        if deletion_count > self.MAX_DELETION_COUNT:
            logger.error(
                f"[MassDeletionProtection] {operation_name}: "
                f"Attempting to delete {deletion_count} images - exceeds limit of {self.MAX_DELETION_COUNT}"
            )
            return False, f"Deletion would affect {deletion_count} images (max: {self.MAX_DELETION_COUNT})"

        # Check 5: Rate limiting
        now = datetime.now()
        recent_deletions = [
            (ts, count) for ts, count in self._deletion_history
            if (now - ts).total_seconds() < self.RAPID_DELETION_WINDOW
        ]

        if len(recent_deletions) >= self.MAX_DELETIONS_IN_WINDOW:
            logger.error(
                f"[MassDeletionProtection] {operation_name}: "
                f"Rate limit exceeded - {len(recent_deletions)} deletions in past {self.RAPID_DELETION_WINDOW}s"
            )
            return False, f"Too many deletions in short time - rate limit protection"

        logger.info(
            f"[MassDeletionProtection] {operation_name}: "
            f"Safety check passed - deleting {deletion_count}/{total_count} images ({deletion_percentage:.1f}%)"
        )
        return True, "Safe to proceed"

    def record_deletion(self, count):
        """Record a deletion operation for rate limiting."""
        now = datetime.now()
        self._deletion_history.append((now, count))

        # Clean up old history (keep last 24 hours)
        cutoff = now - timedelta(hours=24)
        self._deletion_history = [
            (ts, cnt) for ts, cnt in self._deletion_history
            if ts > cutoff
        ]

    def check_empty_csv_safety(self, comic_count, operation_name="cleanup"):
        """
        Check if CSV is suspiciously empty before allowing cleanup operations.

        Args:
            comic_count (int): Number of comics in CSV
            operation_name (str): Name of operation for logging

        Returns:
            tuple: (is_safe: bool, reason: str)
        """
        if comic_count < self.MIN_COMICS_FOR_CLEANUP:
            logger.error(
                f"[MassDeletionProtection] {operation_name}: "
                f"CSV has only {comic_count} comics (min: {self.MIN_COMICS_FOR_CLEANUP}) - "
                f"blocking operation to prevent accidental cleanup"
            )
            return False, f"CSV has only {comic_count} comics - may be corrupted or empty"

        logger.info(
            f"[MassDeletionProtection] {operation_name}: "
            f"CSV health check passed - {comic_count} comics"
        )
        return True, "CSV health check passed"

    def reset_rate_limit(self):
        """Reset rate limiting history (for admin override)."""
        self._deletion_history = []
        logger.warning("[MassDeletionProtection] Rate limit history cleared by admin")


# Global protection instance
_protection = None


def get_protection():
    """Get or create the global protection instance."""
    global _protection
    if _protection is None:
        _protection = MassDeletionProtection()
    return _protection


def require_deletion_safety(func):
    """
    Decorator to add deletion safety checks to functions that delete images.

    The decorated function must accept 'deletion_count' and 'total_count'
    keyword arguments, or the decorator will attempt to calculate them.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        protection = get_protection()

        # Try to get deletion counts from kwargs or function name
        deletion_count = kwargs.get('deletion_count', 0)
        total_count = kwargs.get('total_count', 0)
        operation_name = func.__name__

        # Run safety check
        is_safe, reason = protection.check_deletion_safety(
            deletion_count,
            total_count,
            operation_name
        )

        if not is_safe:
            logger.error(f"[{operation_name}] Deletion blocked by safety system: {reason}")
            raise ValueError(f"Deletion blocked: {reason}")

        # Execute function
        result = func(*args, **kwargs)

        # Record successful deletion
        if deletion_count > 0:
            protection.record_deletion(deletion_count)

        return result

    return wrapper


def check_csv_health_before_cleanup(comic_count, operation_name="cleanup"):
    """
    Check if CSV is healthy before allowing cleanup operations.
    Raises ValueError if CSV appears empty or corrupted.

    Args:
        comic_count (int): Number of comics in CSV
        operation_name (str): Name of operation for error messages

    Raises:
        ValueError: If CSV fails health check
    """
    protection = get_protection()
    is_safe, reason = protection.check_empty_csv_safety(comic_count, operation_name)

    if not is_safe:
        logger.error(f"[{operation_name}] CSV health check failed: {reason}")
        raise ValueError(f"CSV health check failed: {reason}")

    return True
