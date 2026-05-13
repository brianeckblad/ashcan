"""Service for managing inventory snapshots."""
from pathlib import Path
from datetime import datetime, timezone
from flask import current_app
import shutil
from app.models.snapshot import Snapshot
from app.utils.logging_utils import log_service_info, log_service_warning, log_app_error, safe_error_message


class SnapshotService:
    """
    Service for managing inventory snapshots (manual backups).
    
    A snapshot is a complete backup of the comic inventory (CSV and images)
    at a specific point in time. This service handles the creation, listing,
    restoration, and deletion of these snapshots, including synchronization 
    with S3 for long-term storage.
    """

    def __init__(self, snapshots_path=None, csv_file=None):
        """
        Initialize the snapshot service with user-specific paths.

        Args:
            snapshots_path (str or Path, optional): Path to snapshots directory.
            csv_file (str or Path, optional): Path to the inventory CSV file.
        """
        if snapshots_path:
            self.snapshots_path = Path(snapshots_path)
        else:
            # Deferred import: this service is instantiated at module level before
            # the Flask app context is ready; user_context requires app context.
            from app.utils.user_context import get_user_snapshots_dir
            self.snapshots_path = get_user_snapshots_dir()

        if csv_file:
            self.csv_file = Path(csv_file)
        else:
            # Deferred import: see above.
            from app.utils.user_context import get_user_csv_file
            self.csv_file = get_user_csv_file()

        # Ensure snapshots directory exists
        self.snapshots_path.mkdir(parents=True, exist_ok=True)

    def create(self, name, description="", include_images=True):
        """
        Create a new snapshot of current inventory.

        Copies the current CSV file and optionally associated images to a 
        timestamped directory and backs up to S3.

        Args:
            name (str): User-friendly name for snapshot.
            description (str, optional): Optional description. Defaults to "".
            include_images (bool): Whether to include images. Defaults to True.

        Returns:
            Snapshot: The created Snapshot object, or None if failed.
        """
        try:
            from app.services.csv_service import CSVService  # Deferred: avoids circular import

            # Generate snapshot ID (timestamp)
            snapshot_id = datetime.now().strftime('%Y%m%d_%H%M%S')
            snapshot_dir = self.snapshots_path / snapshot_id
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            # Read current comics
            csv_service = CSVService(str(self.csv_file))
            comics = csv_service.read_all()
            comic_count = len(comics)

            # Copy CSV file
            csv_dest = snapshot_dir / 'comics_export.csv'
            shutil.copy2(self.csv_file, csv_dest)

            # Copy images if requested
            if include_images:
                images_dir = snapshot_dir / 'images'
                images_dir.mkdir(exist_ok=True)

                from app.services.s3_service import s3_service  # Deferred: avoids circular import

                # Get all unique image URLs from comics
                image_urls = set()
                for comic in comics:
                    image_urls.update(comic.image_urls)

                # Copy images from S3 to snapshot
                images_copied = 0
                from app.utils.user_context import get_user_s3_images_prefix  # Deferred: see __init__
                images_prefix = get_user_s3_images_prefix()
                images_prefix_in_url = f'/{images_prefix}'
                for img_url in image_urls:
                    if img_url:
                        filename = ''
                        try:
                            # Extract filename
                            if images_prefix_in_url in img_url:
                                filename = img_url.split(images_prefix_in_url)[-1]
                            else:
                                filename = img_url.split('/')[-1]

                            # Download from S3 to snapshot
                            bucket_name = current_app.config.get('S3_BUCKET')
                            source_key = f'{images_prefix}{filename}'
                            dest_path = images_dir / filename

                            s3_service.client().download_file(
                                bucket_name,
                                source_key,
                                str(dest_path)
                            )
                            images_copied += 1

                        except Exception as img_error:
                            log_service_warning(f"Failed to copy image {filename}: {img_error}")


            # Create snapshot metadata
            snapshot = Snapshot(
                id=snapshot_id,
                name=name,
                comic_count=comic_count,
                created_at=datetime.now(timezone.utc).isoformat(),
                description=description
            )

            # Save metadata
            metadata_file = snapshot_dir / 'metadata.json'
            with open(metadata_file, 'w', encoding='utf-8') as f:
                f.write(snapshot.to_json())

            return snapshot

        except Exception as e:
            log_app_error(f"Error creating snapshot: {e}")
            return None

    def get(self, snapshot_id):
        """
        Retrieve a snapshot's metadata by its ID.

        Args:
            snapshot_id (str): The unique ID of the snapshot.

        Returns:
            Snapshot or None: The Snapshot metadata object, or None if not found.
        """
        try:
            snapshot_dir = self.snapshots_path / snapshot_id
            metadata_file = snapshot_dir / 'metadata.json'

            if not metadata_file.exists():
                return None

            with open(metadata_file, 'r', encoding='utf-8') as f:
                return Snapshot.from_json(f.read())

        except Exception as e:
            log_app_error(f"Error getting snapshot: {e}")
            return None

    def list_all(self):
        """
        List all available snapshots.

        Returns:
            list: A list of Snapshot metadata objects, sorted by date descending.
        """
        try:
            snapshots = []
            for snapshot_dir in self.snapshots_path.iterdir():
                if snapshot_dir.is_dir():
                    metadata_file = snapshot_dir / 'metadata.json'
                    if metadata_file.exists():
                        try:
                            with open(metadata_file, 'r', encoding='utf-8') as f:
                                snapshot = Snapshot.from_json(f.read())
                                snapshots.append(snapshot)
                        except Exception as e:
                            log_service_warning(f"Error reading snapshot {snapshot_dir.name}: {e}")

            # Sort by created_at (newest first)
            snapshots.sort(key=lambda x: x.created_at, reverse=True)
            return snapshots

        except Exception as e:
            log_app_error(f"Error listing snapshots: {e}")
            return []

    def restore(self, snapshot_id, mode='replace'):
        """
        Restore inventory from a snapshot.

        Restores the CSV file and optionally images from the snapshot directory.

        Args:
            snapshot_id (str): ID of the snapshot to restore.
            mode (str): Restore mode ('replace' or 'merge'). 
                        'replace' clears current inventory first. 
                        Defaults to 'replace'.

        Returns:
            dict: Summary containing 'success', 'comics_restored', and 'message'.
        """
        try:
            from app.services.csv_service import CSVService

            snapshot_dir = self.snapshots_path / snapshot_id
            snapshot_csv = snapshot_dir / 'comics_export.csv'

            if not snapshot_csv.exists():
                return {
                    'success': False,
                    'comics_restored': 0,
                    'message': 'Snapshot CSV not found'
                }

            # Read snapshot comics
            snapshot_csv_service = CSVService(str(snapshot_csv))
            snapshot_comics = snapshot_csv_service.read_all()

            # Get current CSV service
            current_csv_service = CSVService(str(self.csv_file))
            current_csv_service.initialize()

            if mode == 'replace':
                # Clear current inventory
                current_csv_service.clear_all()

            # Add comics from snapshot
            comics_restored = 0
            for comic in snapshot_comics:
                try:
                    if mode == 'merge':
                        # Check if comic already exists
                        existing = current_csv_service.find_by_sku(comic.sku)
                        if existing:
                            continue

                    current_csv_service.add(comic)
                    comics_restored += 1

                except Exception as e:
                    log_service_warning(f"Failed to restore comic {comic.sku}: {e}")

            # Copy images back to production if they exist in snapshot
            images_dir = snapshot_dir / 'images'
            if images_dir.exists():
                from app.services.s3_service import s3_service  # Deferred: avoids circular import
                from app.utils.user_context import get_user_s3_images_prefix  # Deferred: see __init__
                images_restored = 0
                images_prefix = get_user_s3_images_prefix()

                for image_file in images_dir.glob('*'):
                    if image_file.is_file():
                        try:
                            bucket_name = current_app.config.get('S3_BUCKET')
                            s3_key = f'{images_prefix}{image_file.name}'

                            s3_service.client().upload_file(
                                str(image_file),
                                bucket_name,
                                s3_key
                            )
                            images_restored += 1

                        except Exception as img_error:
                            log_service_warning(f"Failed to restore image {image_file.name}: {img_error}")


            # Sync CSV to S3
            from app.services.s3_service import s3_service  # Deferred: avoids circular import
            s3_service.backup_main_csv_to_s3(str(self.csv_file))

            mode_text = "replaced with" if mode == 'replace' else "merged from"
            return {
                'success': True,
                'comics_restored': comics_restored,
                'message': f'Successfully {mode_text} snapshot: {comics_restored} comics restored'
            }

        except Exception as e:
            log_app_error(f"Error restoring snapshot: {e}")
            return {
                'success': False,
                'comics_restored': 0,
                'message': safe_error_message(e)
            }

    def delete(self, snapshot_id):
        """
        Permanently delete a snapshot from local storage.

        Args:
            snapshot_id (str): ID of the snapshot to delete.

        Returns:
            bool: True if the snapshot was deleted successfully.
        """
        try:
            snapshot_dir = self.snapshots_path / snapshot_id

            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)
                return True

            return False

        except Exception as e:
            log_app_error(f"Error deleting snapshot: {e}")
            return False

    def cleanup_expired(self, retention_days=730):
        """
        Delete snapshots older than the retention period.

        Args:
            retention_days (int): Number of days to keep snapshots. 
                                  Defaults to 730 (2 years).

        Returns:
            int: Number of snapshots deleted.
        """
        try:
            snapshots = self.list_all()
            count = 0

            for snapshot in snapshots:
                if snapshot.is_expired(retention_days):
                    if self.delete(snapshot.id):
                        count += 1

            return count

        except Exception as e:
            log_app_error(f"Error cleaning up snapshots: {e}")
            return 0


# Singleton instance
snapshot_service = SnapshotService()
