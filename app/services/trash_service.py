"""Service for managing trash (deleted comics)."""
import fcntl
import os
from pathlib import Path
from datetime import datetime
from flask import current_app
from app.models.trash_item import TrashItem
from app.utils.logging_utils import log_service_info, log_service_warning, log_app_error
from app.utils.user_context import get_current_username


class TrashService:
    """
    Service for managing the application's trash and retention system.
    
    This service handles moving deleted comics to a temporary 'trash' state,
    where they are preserved for 30 days before permanent deletion. It supports
    listing trashed items, restoring them to inventory, and automatic cleanup
    of expired items.
    """

    def __init__(self, trash_path=None):
        """
        Initialize the trash service.
        
        Args:
            trash_path (str or Path, optional): Path to the trash directory.
        """
        self._trash_path = trash_path
        self._cached_path = None

    @property
    def trash_path(self):
        """
        Get or initialize the trash directory path with user-specific location.

        Returns:
            Path: The validated path to the user's trash directory.
        """
        if self._cached_path is None:
            if self._trash_path:
                self._cached_path = Path(self._trash_path)
            else:
                # Deferred import: this service is instantiated at module level before
                # the Flask app context is ready; user_context requires app context.
                from app.utils.user_context import get_user_trash_dir
                user_trash = get_user_trash_dir()
                self._cached_path = user_trash / 'recent'

            # Ensure trash directory exists
            self._cached_path.mkdir(parents=True, exist_ok=True)

        return self._cached_path

    def add(self, trash_item):
        """
        Add a comic listing to the trash.
        
        Args:
            trash_item (TrashItem): The trash item to add.
            
        Returns:
            bool: True if the item was added successfully.
        """
        try:
            filename = f"comic_{trash_item.sku}.json"
            file_path = self.trash_path / filename

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(trash_item.to_json())

            return True

        except Exception as e:
            log_app_error(f"Error adding to trash: {e}")
            return False

    def get(self, sku):
        """
        Retrieve a trash item by SKU.
        
        Args:
            sku (str): The SKU of the trashed comic.
            
        Returns:
            TrashItem or None: The TrashItem if found, else None.
        """
        try:
            filename = f"comic_{sku}.json"
            file_path = self.trash_path / filename

            if not file_path.exists():
                return None

            with open(file_path, 'r', encoding='utf-8') as f:
                return TrashItem.from_json(f.read())

        except Exception as e:
            log_app_error(f"Error getting from trash: {e}")
            return None

    def list_all(self):
        """
        List all items currently in the trash.
        
        Returns:
            list: A list of TrashItem objects, sorted by deletion date (newest first).
        """
        try:
            items = []
            for file_path in self.trash_path.glob('comic_*.json'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        item = TrashItem.from_json(f.read())
                        items.append(item)
                except Exception as e:
                    log_service_warning(f"Error reading trash item {file_path}: {e}")

            # Sort by deleted_at string (ISO format strings sort correctly alphabetically)
            # Use days_in_trash() for sorting which handles timezone issues
            def get_sort_key(item):
                try:
                    return -item.days_in_trash()  # Negative so newer items come first
                except Exception:
                    return 0

            items.sort(key=get_sort_key)
            return items

        except Exception as e:
            log_app_error(f"Error listing trash: {e}")
            return []

    def restore(self, sku):
        """
        Retrieve a trash item and remove it from trash for restoration.
        
        Args:
            sku (str): The SKU of the comic to restore.
            
        Returns:
            TrashItem or None: The TrashItem instance if found and removed.
        """
        try:
            item = self.get(sku)
            if not item:
                return None

            # Delete from trash
            filename = f"comic_{sku}.json"
            file_path = self.trash_path / filename
            file_path.unlink()

            return item

        except Exception as e:
            log_app_error(f"Error restoring from trash: {e}")
            return None

    def delete(self, sku):
        """
        Permanently delete an item from the trash, including S3 images.

        Args:
            sku (str): The SKU of the item to delete.
            
        Returns:
            bool: True if deletion was successful.
        """
        try:
            # Get the trash item to retrieve image URLs before deletion
            item = self.get(sku)

            # Delete images from S3 if they exist
            if item and item.image_urls:
                try:
                    from app.services.s3_service import s3_service  # Deferred: avoids circular import
                    for image_url in item.image_urls:
                        if image_url and image_url.strip():
                            # Pass the full S3 URL to delete_file
                            try:
                                s3_service.delete_file(image_url, delete_thumbnail=True)
                            except Exception as img_err:
                                log_service_warning(f"Failed to delete S3 image {image_url}: {img_err}")
                except Exception as s3_err:
                    log_service_warning(f"Failed to access S3 service for SKU {sku}: {s3_err}")

            # Delete the trash JSON file. ``missing_ok=True`` makes a
            # double-cleanup (e.g. two workers racing on cleanup_expired) a
            # safe no-op rather than an exception.
            filename = f"comic_{sku}.json"
            file_path = self.trash_path / filename

            if file_path.exists():
                try:
                    file_path.unlink()
                except FileNotFoundError:
                    pass  # another worker beat us to it — still a success
                return True

            return False

        except Exception as e:
            log_app_error(f"Error deleting from trash: {e}")
            return False

    def empty(self):
        """
        Permanently delete all items from the trash.
        
        Returns:
            int: The number of items deleted.
        """
        try:
            items = self.list_all()
            count = 0

            for item in items:
                if self.delete(item.sku):
                    count += 1

            return count

        except Exception as e:
            log_app_error(f"Error emptying trash: {e}")
            return 0

    def cleanup_expired(self, retention_days=30):
        """
        Identify and remove trash items that have exceeded the retention period.

        Cross-worker safe: holds a non-blocking ``fcntl`` lock on
        ``<trash_path>/.cleanup.lock`` so that if two workers fire the same
        scheduled cleanup, only one runs and the other returns 0 immediately
        rather than racing on every JSON file and S3 delete.

        Args:
            retention_days (int): Maximum age in days. Defaults to 30.

        Returns:
            int: The number of items permanently deleted (0 if another
                worker is already running cleanup).
        """
        # Acquire a non-blocking cross-process lock
        self.trash_path.mkdir(parents=True, exist_ok=True)
        lock_path = self.trash_path / '.cleanup.lock'
        lock_fd = None
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                # Another worker is already cleaning up — bail quietly
                log_service_info("Trash cleanup skipped: another worker holds the lock")
                return 0

            items = self.list_all()
            count = 0

            for item in items:
                if item.is_expired(retention_days):
                    if self.delete(item.sku):
                        count += 1

            return count

        except Exception as e:
            log_app_error(f"Error cleaning up trash: {e}")
            return 0
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    try:
                        os.close(lock_fd)
                    except OSError:
                        pass

    def get_stats(self):
        """
        Get trash statistics.

        Returns:
            dict: Statistics about trash
        """
        try:
            items = self.list_all()
            today = []
            this_week = []
            this_month = []

            for item in items:
                days = item.days_in_trash()
                if days == 0:
                    today.append(item)
                if days <= 7:
                    this_week.append(item)
                if days <= 30:
                    this_month.append(item)

            return {
                'total': len(items),
                'today': len(today),
                'this_week': len(this_week),
                'this_month': len(this_month)
            }

        except Exception as e:
            username = get_current_username()
            current_app.logger.error(f"[User: {username}] Error getting trash stats: {e}")
            return {'total': 0, 'today': 0, 'this_week': 0, 'this_month': 0}


# Singleton instance
trash_service = TrashService()
