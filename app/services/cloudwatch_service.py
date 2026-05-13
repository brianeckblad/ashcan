"""Service for sending custom metrics to AWS CloudWatch."""
import boto3
import os
from datetime import datetime, timezone
from flask import current_app


class CloudWatchService:
    """Send custom metrics to AWS CloudWatch."""

    def __init__(self):
        self.client = None
        # Use environment variable for namespace, default to 'dockyard'
        # This can be set in deployment configs or .env file
        self.namespace = os.environ.get('CLOUDWATCH_NAMESPACE', 'dockyard')

    def _get_client(self):
        """Get or create boto3 CloudWatch client."""
        if self.client is None:
            try:
                self.client = boto3.client('cloudwatch')
            except Exception as e:
                if current_app:
                    current_app.logger.warning(f"Could not initialize CloudWatch client: {e}")
        return self.client

    def log_metric(self, metric_name, value, unit='Count', dimensions=None):
        """
        Send a metric to CloudWatch.

        Args:
            metric_name (str): Name of the metric
            value (float): Metric value
            unit (str): Unit type (Count, Milliseconds, Bytes, etc.)
            dimensions (dict): Optional dimensions for filtering
        """
        try:
            client = self._get_client()
            if not client:
                return

            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit,
                'Timestamp': datetime.now(timezone.utc)
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': str(v)} for k, v in dimensions.items()
                ]

            client.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data]
            )
        except Exception as e:
            # Don't fail the request if CloudWatch fails
            if current_app:
                current_app.logger.debug(f"Failed to send CloudWatch metric: {e}")


# Singleton instance
cloudwatch_service = CloudWatchService()

