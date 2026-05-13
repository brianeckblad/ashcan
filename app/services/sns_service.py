"""Service for sending notifications via AWS SNS."""
import boto3
from flask import current_app
import os


class SNSService:
    """Send notifications via AWS SNS."""

    def __init__(self):
        self.client = None
        self.topic_arn = None

    def _get_client(self):
        """Get or create boto3 SNS client."""
        if self.client is None:
            try:
                self.client = boto3.client('sns')
                # Get topic ARN from config or environment
                if current_app:
                    self.topic_arn = current_app.config.get('SNS_TOPIC_ARN') or os.getenv('SNS_TOPIC_ARN')
                else:
                    self.topic_arn = os.getenv('SNS_TOPIC_ARN')
            except Exception as e:
                if current_app:
                    current_app.logger.warning(f"Could not initialize SNS client: {e}")
        return self.client

    def send_alert(self, subject, message, severity='INFO'):
        """
        Send an alert notification.

        Args:
            subject (str): Email subject line
            message (str): Message body
            severity (str): INFO, WARNING, ERROR, CRITICAL
        """
        if not self.topic_arn:
            return

        try:
            client = self._get_client()
            if not client:
                return

            client.publish(
                TopicArn=self.topic_arn,
                Subject=f"[{severity}] {subject}",
                Message=message
            )
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Failed to send SNS alert: {e}")


# Singleton instance
sns_service = SNSService()

