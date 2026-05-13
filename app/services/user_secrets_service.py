"""Service for managing user-specific secrets in AWS Secrets Manager."""
import json
import boto3
import os
from botocore.exceptions import ClientError
from flask import current_app
from app.utils.logging_utils import safe_error_message


class UserSecretsService:
    """
    Service for managing user-specific secrets in AWS Secrets Manager.

    Each user can have their own eBay API credentials stored securely
    in AWS Secrets Manager under the pattern: {app_prefix}/users/{username}

    The app_prefix is derived from the SECRET_NAME environment variable
    (e.g., SECRET_NAME='dockyard/production' → prefix='dockyard'), which keeps
    user secrets under the same IAM policy as the main app secret.
    """

    def __init__(self):
        """Initialize the secrets service."""
        self.region_name = os.environ.get('AWS_REGION', 'us-east-2')
        self.client = None

    def _get_client(self):
        """Get or create boto3 Secrets Manager client."""
        if self.client is None:
            session = boto3.session.Session()
            self.client = session.client(
                service_name='secretsmanager',
                region_name=self.region_name
            )
        return self.client

    def _get_app_prefix(self):
        """
        Get the app prefix from SECRET_NAME env var.

        Extracts the first path component from the main secret name
        so user secrets share the same IAM policy prefix.

        Returns:
            str: App prefix (e.g., 'dockyard' from 'dockyard/production')
        """
        secret_name = os.environ.get('SECRET_NAME', 'dockyard/production')
        return secret_name.split('/')[0]

    def get_user_secret_name(self, username):
        """
        Get the secret name for a user.

        Args:
            username (str): The username

        Returns:
            str: Secret name (e.g., 'dockyard/users/brian')
        """
        prefix = self._get_app_prefix()
        return f"{prefix}/users/{username}"

    def get_user_ebay_credentials(self, username):
        """
        Get eBay credentials for a specific user.

        Args:
            username (str): The username

        Returns:
            dict: eBay credentials or None if not found
        """
        secret_name = self.get_user_secret_name(username)
        client = self._get_client()

        try:
            response = client.get_secret_value(SecretId=secret_name)
            secrets = json.loads(response['SecretString'])

            return {
                'EBAY_PRODUCTION_APP_ID': secrets.get('EBAY_PRODUCTION_APP_ID'),
                'EBAY_PRODUCTION_CERT_ID': secrets.get('EBAY_PRODUCTION_CERT_ID'),
                'EBAY_PRODUCTION_DEV_ID': secrets.get('EBAY_PRODUCTION_DEV_ID'),
                'EBAY_PRODUCTION_TOKEN': secrets.get('EBAY_PRODUCTION_TOKEN'),
                'EBAY_SANDBOX_APP_ID': secrets.get('EBAY_SANDBOX_APP_ID'),
                'EBAY_SANDBOX_CERT_ID': secrets.get('EBAY_SANDBOX_CERT_ID'),
                'EBAY_SANDBOX_DEV_ID': secrets.get('EBAY_SANDBOX_DEV_ID'),
                'EBAY_SANDBOX_TOKEN': secrets.get('EBAY_SANDBOX_TOKEN'),
            }
        except client.exceptions.ResourceNotFoundException:
            current_app.logger.info(f"[User: {username}] No eBay credentials found in Secrets Manager")
            return None
        except Exception as e:
            current_app.logger.error(f"[User: {username}] Error fetching eBay credentials: {e}")
            return None

    def save_user_ebay_credentials(self, username, credentials):
        """
        Save or update eBay credentials for a specific user.

        Args:
            username (str): The username
            credentials (dict): eBay credentials to save

        Returns:
            tuple: (success: bool, message: str)
        """
        secret_name = self.get_user_secret_name(username)
        client = self._get_client()

        try:
            # Check if secret exists
            try:
                client.get_secret_value(SecretId=secret_name)
                secret_exists = True
            except client.exceptions.ResourceNotFoundException:
                secret_exists = False

            # Prepare secret data
            secret_data = {
                'EBAY_PRODUCTION_APP_ID': credentials.get('production_app_id', ''),
                'EBAY_PRODUCTION_CERT_ID': credentials.get('production_cert_id', ''),
                'EBAY_PRODUCTION_DEV_ID': credentials.get('production_dev_id', ''),
                'EBAY_PRODUCTION_TOKEN': credentials.get('production_token', ''),
                'EBAY_SANDBOX_APP_ID': credentials.get('sandbox_app_id', ''),
                'EBAY_SANDBOX_CERT_ID': credentials.get('sandbox_cert_id', ''),
                'EBAY_SANDBOX_DEV_ID': credentials.get('sandbox_dev_id', ''),
                'EBAY_SANDBOX_TOKEN': credentials.get('sandbox_token', ''),
            }

            secret_string = json.dumps(secret_data)

            if secret_exists:
                # Update existing secret
                client.put_secret_value(
                    SecretId=secret_name,
                    SecretString=secret_string
                )
                current_app.logger.info(f"[User: {username}] Updated eBay credentials in Secrets Manager")
                return True, "eBay credentials updated successfully"
            else:
                # Create new secret
                app_name = os.getenv('APP_NAME', 'app-item-listing-tool')
                client.create_secret(
                    Name=secret_name,
                    Description=f"eBay API credentials for user: {username}",
                    SecretString=secret_string,
                    Tags=[
                        {'Key': 'Application', 'Value': app_name},
                        {'Key': 'Username', 'Value': username},
                        {'Key': 'Type', 'Value': 'ebay-credentials'}
                    ]
                )
                current_app.logger.info(f"[User: {username}] Created eBay credentials in Secrets Manager")
                return True, "eBay credentials saved successfully"

        except Exception as e:
            current_app.logger.error(f"[User: {username}] Error saving eBay credentials: {e}")
            return False, f"Error saving credentials: {safe_error_message(e)}"

    def delete_user_ebay_credentials(self, username):
        """
        Delete eBay credentials for a specific user.

        Args:
            username (str): The username

        Returns:
            tuple: (success: bool, message: str)
        """
        secret_name = self.get_user_secret_name(username)
        client = self._get_client()

        try:
            client.delete_secret(
                SecretId=secret_name,
                ForceDeleteWithoutRecovery=True
            )
            current_app.logger.info(f"[User: {username}] Deleted eBay credentials from Secrets Manager")
            return True, "eBay credentials deleted successfully"
        except client.exceptions.ResourceNotFoundException:
            return True, "No credentials found to delete"
        except Exception as e:
            current_app.logger.error(f"[User: {username}] Error deleting eBay credentials: {e}")
            return False, f"Error deleting credentials: {safe_error_message(e)}"

    def check_credentials_exist(self, username):
        """
        Check if user has eBay credentials stored.

        Args:
            username (str): The username

        Returns:
            bool: True if credentials exist, False otherwise
        """
        secret_name = self.get_user_secret_name(username)
        client = self._get_client()

        try:
            client.get_secret_value(SecretId=secret_name)
            return True
        except client.exceptions.ResourceNotFoundException:
            return False
        except Exception as e:
            current_app.logger.error(f"[User: {username}] Error checking credentials: {e}")
            return False


# Singleton instance
user_secrets_service = UserSecretsService()

