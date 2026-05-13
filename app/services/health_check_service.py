"""Health check service to verify CSV integrity and S3/local image consistency."""
from pathlib import Path
from flask import current_app
from app.services.csv_service import CSVService
from app.services.s3_service import s3_service
from app.utils.logging_utils import log_cleanup_info, log_cleanup_warning, log_app_error, get_cleanup_logger, safe_error_message
import glob


class HealthCheckService:
    """
    Performs health checks on the application data and storage.

    Verifies that:
    1. All images referenced in CSV exist in S3/local storage
    2. All images in S3/local storage are referenced in CSV (removes orphans)
    3. No broken image URLs in CSV

    Multi-user support: Checks all user CSV files in instance/data/
    """

    def __init__(self, csv_file_path=None, instance_path=None):
        """
        Initialize the health check service.

        Args:
            csv_file_path (str/Path, optional): Path to default CSV file (legacy)
            instance_path (str/Path): Path to the instance directory
        """
        if instance_path:
            self.instance_path = Path(instance_path)
        else:
            self.instance_path = Path(current_app.instance_path)

        if csv_file_path:
            self.csv_file = Path(csv_file_path)
        else:
            self.csv_file = self.instance_path / 'items.csv'

        self.images_dir = self.instance_path / 'images'
        self.results = {
            'success': True,
            'csv_valid': True,
            'orphaned_s3_deleted': 0,
            'orphaned_local_deleted': 0,
            'missing_images': [],
            'broken_urls': [],
            'errors': [],
            'users_checked': 0
        }

    def run(self):
        """
        Run the full health check across all users.

        Returns:
            dict: Health check results
        """
        try:
            # Step 1: Read all CSV files (default + all users) and collect image URLs
            csv_image_urls = self._collect_all_csv_image_urls()
            local_image_files = self._collect_local_images()
            s3_image_urls = self._collect_s3_images()

            # Step 2: Find and delete orphaned images in S3
            # Exclude thumbnails from orphan detection - they are generated from original images
            orphaned_s3 = s3_image_urls - csv_image_urls
            orphaned_s3_non_thumbs = {url for url in orphaned_s3 if '_thumb.' not in url}
            self.results['orphaned_s3_deleted'] = self._delete_orphaned_s3_images(orphaned_s3_non_thumbs)

            # Step 3: Find and delete orphaned images in local storage
            orphaned_local = local_image_files - csv_image_urls
            self.results['orphaned_local_deleted'] = self._delete_orphaned_local_images(orphaned_local)

            # Step 4: Check for missing images (referenced in CSV but not in storage)
            self.results['missing_images'] = list(csv_image_urls - s3_image_urls - local_image_files)

            # Log results
            self._log_results()

            return self.results

        except Exception as e:
            log_app_error(f"Health check failed: {e}", exc_info=True)
            self.results['success'] = False
            self.results['errors'].append(safe_error_message(e))
            return self.results

    def _collect_all_csv_image_urls(self):
        """
        Collect all image URLs referenced in ALL CSV files (default + all users).

        Returns:
            set: Set of image filenames from all CSV files
        """
        image_urls = set()
        users_checked = 0

        try:
            # Check default CSV file if it exists
            if self.csv_file.exists():
                urls = self._collect_csv_image_urls_from_file(self.csv_file)
                image_urls.update(urls)
                users_checked += 1
                log_cleanup_info(f"Checked default CSV: {len(urls)} images")

            # Check all user CSV files in data directory
            data_dir = self.instance_path / 'data'
            if data_dir.exists():
                # Find all *-items.csv files
                user_csv_files = glob.glob(str(data_dir / '*-items.csv'))
                for csv_path in user_csv_files:
                    csv_file = Path(csv_path)
                    username = csv_file.stem.replace('-items', '')
                    try:
                        urls = self._collect_csv_image_urls_from_file(csv_file)
                        image_urls.update(urls)
                        users_checked += 1
                        log_cleanup_info(f"Checked user '{username}' CSV: {len(urls)} images")
                    except Exception as e:
                        log_cleanup_warning(f"Error checking CSV for user '{username}': {e}")
                        self.results['errors'].append(f"User '{username}': {safe_error_message(e)}")

            self.results['users_checked'] = users_checked
            log_cleanup_info(f"Total users checked: {users_checked}, Total unique images: {len(image_urls)}")

        except Exception as e:
            log_app_error(f"Error collecting CSV image URLs: {e}")
            self.results['errors'].append(f"CSV collection error: {safe_error_message(e)}")

        return image_urls

    def _collect_csv_image_urls_from_file(self, csv_file):
        """
        Collect all image URLs referenced in a specific CSV file.

        Args:
            csv_file (Path): Path to CSV file

        Returns:
            set: Set of image filenames from CSV
        """
        image_urls = set()
        try:
            csv_service = CSVService(str(csv_file))
            comics = csv_service.read_all()

            for comic in comics:
                # The Comic model stores images in image_urls list
                if hasattr(comic, 'image_urls') and comic.image_urls:
                    for url in comic.image_urls:
                        if url and url.strip():
                            # Extract filename from URL
                            filename = self._extract_filename(url)
                            if filename:
                                image_urls.add(filename)

                # Also check the extra_fields dict for image URLs (for backwards compatibility)
                if hasattr(comic, 'extra_fields') and comic.extra_fields:
                    for i in range(1, 9):
                        field_name = f'Image URL {i}'
                        url = comic.extra_fields.get(field_name)
                        if url and url.strip():
                            filename = self._extract_filename(url)
                            if filename:
                                image_urls.add(filename)

        except Exception as e:
            log_app_error(f"Error reading CSV for health check: {e}")
            self.results['errors'].append(f"CSV read error: {safe_error_message(e)}")

        return image_urls

    def _collect_local_images(self):
        """
        Collect all local image files in the images directory.

        Returns:
            set: Set of local image filenames
        """
        local_files = set()
        try:
            if self.images_dir.exists():
                for image_file in self.images_dir.rglob('*'):
                    if image_file.is_file():
                        # Store just the filename for comparison
                        local_files.add(image_file.name)
        except Exception as e:
            log_cleanup_warning(f"Error reading local images: {e}")

        return local_files

    def _collect_s3_images(self):
        """
        Collect all image files in S3.

        Returns:
            set: Set of S3 image filenames/URLs
        """
        s3_files = set()
        try:
            # Get list of all files in S3 under the user's images folder
            # Deferred import: see HealthCheckService.__init__ for rationale.
            from app.utils.user_context import get_user_s3_images_prefix
            prefix = get_user_s3_images_prefix()

            # Use the s3_service to list objects with this prefix
            # This requires the service to have a method to list objects
            s3_files = s3_service.list_images_in_s3(prefix)

        except Exception as e:
            log_cleanup_warning(f"Error reading S3 images: {e}")

        return s3_files

    def _extract_filename(self, url):
        """
        Extract filename from a URL or path.

        Args:
            url (str): Full URL or filename

        Returns:
            str: Extracted filename, or None if invalid
        """
        try:
            if url.startswith('http'):
                # Extract from URL: https://bucket.s3.region.amazonaws.com/folder/filename
                return url.split('/')[-1]
            else:
                # Already a filename
                return url
        except Exception:
            return None

    def _delete_orphaned_s3_images(self, orphaned_urls):
        """
        Delete orphaned images from S3.

        Note: Thumbnails are NOT deleted during health checks as they are
        automatically generated from original images. Only original image files
        that are not referenced in the CSV are deleted.

        Args:
            orphaned_urls (set): Set of orphaned S3 filenames/URLs (excluding thumbnails)

        Returns:
            int: Number of images deleted
        """
        deleted_count = 0
        try:
            for url in orphaned_urls:
                try:
                    # Skip thumbnails - they should be preserved
                    if '_thumb.' in url:
                        log_cleanup_info(f"Skipping thumbnail during orphan cleanup: {url}")
                        continue

                    # Try to delete if it's a full URL
                    if url.startswith('http'):
                        s3_service.delete_file(url, delete_thumbnail=False)  # Don't auto-delete thumbnails
                    else:
                        # It's just a filename, construct the proper HTTPS S3 URL
                        s3_bucket = current_app.config.get('S3_BUCKET')
                        # Deferred import: see above.
                        from app.utils.user_context import get_user_s3_images_prefix
                        user_images_prefix = get_user_s3_images_prefix()
                        # Construct HTTPS URL: https://bucket.s3.amazonaws.com/users/{user}/images/filename
                        constructed_url = f"https://{s3_bucket}.s3.amazonaws.com/{user_images_prefix}{url}"
                        s3_service.delete_file(constructed_url, delete_thumbnail=False)  # Don't auto-delete thumbnails

                    deleted_count += 1
                    log_cleanup_info(f"Deleted orphaned S3 image: {url}")

                except Exception as img_err:
                    log_cleanup_warning(f"Failed to delete orphaned S3 image {url}: {img_err}")

        except Exception as e:
            log_app_error(f"Error deleting orphaned S3 images: {e}")

        return deleted_count

    def _delete_orphaned_local_images(self, orphaned_files):
        """
        Delete orphaned local image files.

        Skips deletion of thumbnail files (_thumb.webp, _thumb.jpg) if their
        corresponding original image exists, since thumbnails are automatically
        generated from original images.

        Args:
            orphaned_files (set): Set of orphaned local filenames

        Returns:
            int: Number of files deleted
        """
        deleted_count = 0
        try:
            for filename in orphaned_files:
                try:
                    # Skip thumbnail files - they are automatically generated from original images
                    # Only delete a thumbnail if the original image is NOT in the system
                    if '_thumb.' in filename:
                        # Extract the base filename (without _thumb.extension)
                        base_filename = filename.split('_thumb.')[0]

                        # Check if the original image exists in any form
                        original_exists = False
                        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
                            original_file = f"{base_filename}{ext}"
                            if original_file not in orphaned_files:
                                # Original image is in CSV (not orphaned), keep the thumbnail
                                original_exists = True
                                break

                        if original_exists:
                            # Skip this thumbnail since its original image exists
                            # Log at DEBUG level to avoid log spam (reduced from INFO)
                            get_cleanup_logger().debug(f"Preserving thumbnail {filename} (original image exists)")
                            continue

                    # Find and delete the file
                    for image_path in self.images_dir.rglob(filename):
                        if image_path.is_file():
                            image_path.unlink()
                            deleted_count += 1
                            log_cleanup_info(f"Deleted orphaned local image: {filename}")

                except Exception as file_err:
                    log_cleanup_warning(f"Failed to delete orphaned local image {filename}: {file_err}")

        except Exception as e:
            log_app_error(f"Error deleting orphaned local images: {e}")

        return deleted_count

    def _log_results(self):
        """Log the health check results."""
        summary = (
            f"Health Check Results:\n"
            f"  - S3 orphaned images deleted: {self.results['orphaned_s3_deleted']}\n"
            f"  - Local orphaned images deleted: {self.results['orphaned_local_deleted']}\n"
            f"  - Missing images (CSV refs but not in storage): {len(self.results['missing_images'])}\n"
            f"  - Errors: {len(self.results['errors'])}"
        )
        log_cleanup_info(summary)

        if self.results['missing_images']:
            log_cleanup_warning(
                f"Missing images: {', '.join(self.results['missing_images'][:10])}"
                f"{'...' if len(self.results['missing_images']) > 10 else ''}"
            )

        if self.results['errors']:
            for error in self.results['errors']:
                log_cleanup_warning(f"Health check error: {error}")


# Singleton instance
_health_check_service = None


def get_health_check_service():
    """Get or create the health check service instance.

    Note: Health check is system-wide, not user-specific.
    CSV_FILE points to instance path for directory checks only.
    """
    global _health_check_service
    if _health_check_service is None:
        # Use instance path directly - health check is system-wide
        instance_path = Path(current_app.instance_path)
        # Use a dummy CSV path since health check doesn't actually read CSV
        csv_path = instance_path / 'items.csv'
        _health_check_service = HealthCheckService(
            str(csv_path),
            str(instance_path)
        )
    return _health_check_service
