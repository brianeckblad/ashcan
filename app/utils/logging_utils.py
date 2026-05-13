"""Logging utilities for services."""
from flask import current_app, has_request_context, session
import logging


def get_log_prefix():
    """
    Get a log prefix with user context for multi-user logging.

    Returns:
        str: Log prefix like "[User: brian] " or "" if no user context
    """
    try:
        if not has_request_context():
            return ""
        username = session.get('username', 'default')
        if username and username != 'default':
            return f"[User: {username}] "
        return ""
    except Exception:
        return ""


def get_service_logger():
    """
    Get the appropriate logger for service operations.

    Returns the service logger if available, otherwise returns the app logger.
    Falls back to a basic logger if outside Flask context.

    Returns:
        logging.Logger: The appropriate logger for service operations
    """
    try:
        # Try to get service logger from Flask app
        if hasattr(current_app, 'service_logger'):
            return current_app.service_logger
        else:
            return current_app.logger
    except RuntimeError:
        # Outside Flask context, return a basic logger
        return logging.getLogger('service')


def log_service_info(message):
    """Log informational service message."""
    get_service_logger().info(message)


def log_service_warning(message):
    """Log warning service message."""
    get_service_logger().warning(message)


def log_service_error(message):
    """Log error service message."""
    get_service_logger().error(message)


def log_app_error(message, exc_info=False):
    """Log application error to app logger (not service logger)."""
    try:
        current_app.logger.error(message, exc_info=exc_info)
    except RuntimeError:
        logging.getLogger('app').error(message, exc_info=exc_info)


def get_cleanup_logger():
    """
    Get the appropriate logger for cleanup operations (health check, trash cleanup, etc).

    Returns the cleanup logger if available, otherwise returns the app logger.
    Falls back to a basic logger if outside Flask context.

    Returns:
        logging.Logger: The appropriate logger for cleanup operations
    """
    try:
        # Try to get cleanup logger from Flask app
        if hasattr(current_app, 'cleanup_logger'):
            return current_app.cleanup_logger
        else:
            return current_app.logger
    except RuntimeError:
        # Outside Flask context, return a basic logger
        return logging.getLogger('cleanup')


def log_cleanup_info(message):
    """Log informational cleanup message."""
    get_cleanup_logger().info(message)


def log_cleanup_warning(message):
    """Log warning cleanup message."""
    get_cleanup_logger().warning(message)


def log_cleanup_error(message):
    """Log error cleanup message."""
    get_cleanup_logger().error(message)


def safe_error_message(exc, default="An internal error occurred"):
    """
    Return an error string safe to send to API clients.

    In ``debug`` mode the full ``str(exc)`` is returned to aid local
    troubleshooting. In production we return a generic message so that
    internal filesystem paths, SQL fragments, or stack details do not leak
    to remote callers — the original exception should already have been
    logged at the call site.

    Args:
        exc (BaseException): The raised exception.
        default (str): Generic message used in production.

    Returns:
        str: A message suitable for inclusion in a JSON error response.
    """
    try:
        if current_app and current_app.debug:
            return str(exc) or default
    except RuntimeError:
        pass
    return default
