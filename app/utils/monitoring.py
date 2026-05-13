"""Monitoring decorators and utilities."""
from functools import wraps
from time import time
from flask import request, current_app
from app.services.cloudwatch_service import cloudwatch_service


def monitor_endpoint(metric_prefix='API'):
    """
    Decorator to monitor endpoint performance.

    Tracks response time and request count with status.

    Args:
        metric_prefix (str): Prefix for metric names
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            start_time = time()
            status = 'success'

            try:
                result = f(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                # Calculate response time
                response_time = (time() - start_time) * 1000  # Convert to ms

                # Get endpoint info
                endpoint = request.endpoint or 'unknown'
                method = request.method

                # Send metrics
                try:
                    cloudwatch_service.log_metric(
                        f'{metric_prefix}ResponseTime',
                        response_time,
                        unit='Milliseconds',
                        dimensions={
                            'endpoint': endpoint,
                            'method': method,
                            'status': status
                        }
                    )

                    cloudwatch_service.log_metric(
                        f'{metric_prefix}RequestCount',
                        1,
                        dimensions={
                            'endpoint': endpoint,
                            'method': method,
                            'status': status
                        }
                    )
                except Exception as metric_error:
                    current_app.logger.debug(f"Failed to send metrics: {metric_error}")

        return wrapper
    return decorator


def track_user_action(action_name, **extra_dimensions):
    """
    Track a user action in CloudWatch.

    Args:
        action_name (str): Name of the action (e.g., 'login', 'upload', 'export')
        **extra_dimensions: Additional dimensions to track
    """
    try:
        from app.utils.user_context import get_current_username

        dimensions = {
            'action': action_name,
            'username': get_current_username() or 'anonymous'
        }
        dimensions.update(extra_dimensions)

        cloudwatch_service.log_metric(
            'UserAction',
            1,
            dimensions=dimensions
        )
    except Exception as e:
        if current_app:
            current_app.logger.debug(f"Failed to track user action: {e}")

