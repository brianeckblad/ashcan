"""Comic service for business logic."""
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, session
from PIL import Image

from app.models.comic import Comic
from app.models.trash_item import TrashItem
from app.services.csv_service import CSVService
from app.services.s3_service import s3_service
from app.services.trash_service import trash_service  # Deferred: avoids circular import at module level — trash_service does not import comic_service
from app.utils.helpers import generate_unique_filename, is_giveaway
from app.utils.logging_utils import log_service_info, log_service_warning, log_app_error, safe_error_message
from app.utils.mass_deletion_protection import get_protection, check_csv_health_before_cleanup
from app.utils.user_context import get_user_csv_file, get_user_sku_file, get_current_username, get_user_s3_images_prefix
from app.utils.whatnot_validators import allowed_file, WHATNOT_FIELD_NAMES, METADATA_FIELD_NAMES
import fcntl
import os
import time


class ComicService:
    """
    Service for managing comic book business logic and operations.
    
    This service acts as an orchestration layer between the models, CSV storage,
    S3 image storage, and the web routes. It handles SKU management (with race 
    condition protection), comic creation, searching, updates, and deletion
    logic (including trash management).

    Multi-user support: Each user has their own CSV file and SKU counter.
    """
    
    def __init__(self):
        """Initialize the ComicService with lazy-loaded dependencies."""
        self.csv_service = None
        self.sku_file = None
        self._current_user = None

    def _get_csv_service(self):
        """
        Get the CSV service instance, initializing it if necessary.
        Uses user-specific CSV file based on logged-in user.

        Returns:
            CSVService: The active CSV service instance.
        """
        current_user = get_current_username()

        # Reinitialize if user changed
        if self.csv_service is None or self._current_user != current_user:
            user_csv_file = get_user_csv_file(current_user)
            self.csv_service = CSVService(user_csv_file)
            self.csv_service.initialize()
            self._current_user = current_user
            log_service_info(f"Initialized CSV service for user: {current_user} ({user_csv_file})")

        return self.csv_service
    
    def _get_sku_file(self):
        """
        Get the SKU counter file path for the current user.

        Returns:
            Path: Path to the user's SKU tracker file.
        """
        return get_user_sku_file()

    def get_next_sku(self):
        """
        Generate the next available SKU and increment the counter.

        Uses file locking (fcntl) to prevent race conditions during concurrent
        requests. S3 reconciliation happens INSIDE the lock and takes the
        higher of (local, S3) to defend against clock skew and split-brain
        between workers.

        Returns:
            str: The next unique SKU number.

        Raises:
            IOError: If the SKU file cannot be accessed or locked.
        """
        sku_file = self._get_sku_file()

        # Ensure parent directory exists
        sku_file.parent.mkdir(parents=True, exist_ok=True)

        # Seed the local file if it doesn't exist so the r+ open below works.
        # The actual value reconciliation happens under lock below.
        if not sku_file.exists():
            sku_file.write_text("1000\n")

        max_retries = 5
        retry_delay = 0.1  # 100ms

        for attempt in range(max_retries):
            try:
                with open(sku_file, 'r+') as f:
                    # Acquire exclusive lock BEFORE any read/reconcile so two
                    # workers can't both pre-seed the file to the same value.
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)

                    try:
                        # Read current local SKU (under lock)
                        content = f.read().strip()
                        try:
                            local_sku = int(content) if content else 1000
                        except ValueError:
                            local_sku = 1000

                        # Reconcile with S3 under lock. Use max() rather than
                        # mtime — a rolled-back S3 value must not lower the
                        # counter, and clock skew must not matter.
                        try:
                            sku_from_s3 = s3_service.restore_sku_from_s3()
                        except Exception as s3_err:
                            log_service_warning(f"S3 SKU restore failed, using local only: {s3_err}")
                            sku_from_s3 = None

                        if sku_from_s3 and isinstance(sku_from_s3.get('sku'), int):
                            current_sku = max(local_sku, sku_from_s3['sku'])
                            if current_sku != local_sku:
                                log_service_info(
                                    f"SKU reconciled with S3: local={local_sku} s3={sku_from_s3['sku']} -> {current_sku}"
                                )
                        else:
                            current_sku = local_sku

                        next_sku = current_sku + 1

                        # Write new SKU
                        f.seek(0)
                        f.write(f"{next_sku}\n")
                        f.truncate()
                        f.flush()
                        os.fsync(f.fileno())

                        # Backup to S3 immediately
                        try:
                            s3_service.backup_sku_to_s3(next_sku)
                        except Exception as s3_err:
                            log_service_warning(f"S3 SKU backup failed (non-fatal): {s3_err}")

                        return str(next_sku)
                    finally:
                        # Release lock
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            except (IOError, ValueError) as e:
                if attempt < max_retries - 1:
                    log_service_warning(f"SKU file lock attempt {attempt + 1} failed, retrying: {e}")
                    time.sleep(retry_delay)
                else:
                    log_app_error(f"Failed to get next SKU after {max_retries} attempts: {e}")
                    raise
    
    def get_current_sku(self):
        """
        Retrieve the current SKU number without incrementing it.
        
        Ensures the local SKU is in sync with S3 before returning.
        
        Returns:
            str: The current SKU number.
        """
        sku_file = self._get_sku_file()

        # Always check S3 to ensure we use the most recent SKU
        sku_from_s3 = s3_service.restore_sku_from_s3()
        local_sku = None
        local_mtime = None

        # Check if local file exists and get its modification time
        if sku_file.exists():
            try:
                local_mtime = sku_file.stat().st_mtime
                with open(sku_file, 'r') as f:
                    local_sku = int(f.read().strip())
            except (IOError, ValueError):
                local_sku = None

        # Determine which SKU to use based on modification time
        if sku_from_s3 and local_sku:
            s3_mtime = sku_from_s3['last_modified'].replace(tzinfo=timezone.utc).timestamp()

            # Use the most recently modified SKU
            if s3_mtime > local_mtime:
                sku_file.parent.mkdir(parents=True, exist_ok=True)
                with open(sku_file, 'w') as f:
                    f.write(f"{sku_from_s3['sku']}\n")
                return str(sku_from_s3['sku'] + 1)
            else:
                return str(local_sku + 1)
        elif sku_from_s3:
            sku_file.parent.mkdir(parents=True, exist_ok=True)
            with open(sku_file, 'w') as f:
                f.write(f"{sku_from_s3['sku']}\n")
            return str(sku_from_s3['sku'] + 1)
        elif local_sku:
            return str(local_sku + 1)
        else:
            # No SKU found anywhere, start from default
            return "1001"

    def _rollback_sku(self, expected_sku=None):
        """
        Conditionally roll back the SKU counter by 1.

        Only decrements when the file still stores ``expected_sku``. If
        another worker has already advanced the counter past that value
        (a common race between concurrent add + failure), the rollback
        is a safe no-op, preventing a future duplicate-SKU collision.

        Args:
            expected_sku: The SKU we allocated and want to give back.
                Accepts int or str. If None, behavior falls back to the
                legacy "decrement whatever is there" semantics (only safe
                in single-worker deployments).
        """
        sku_file = self._get_sku_file()

        try:
            with open(sku_file, 'r+') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    content = f.read().strip()
                    current_sku = int(content) if content else 1000

                    # Coerce expected_sku for the comparison
                    exp = None
                    if expected_sku is not None:
                        try:
                            exp = int(expected_sku)
                        except (TypeError, ValueError):
                            exp = None

                    # If we know which SKU to give back, only decrement
                    # when the counter still points at it (i.e. our +1).
                    if exp is not None and current_sku != exp + 1:
                        log_service_info(
                            f"Skipping SKU rollback: counter={current_sku} but expected={exp}+1 "
                            "(another worker has advanced past it)"
                        )
                        return

                    rolled_back_sku = max(1000, current_sku - 1)

                    f.seek(0)
                    f.write(f"{rolled_back_sku}\n")
                    f.truncate()
                    f.flush()
                    os.fsync(f.fileno())

                    try:
                        s3_service.backup_sku_to_s3(rolled_back_sku)
                    except Exception as s3_err:
                        log_service_warning(f"S3 SKU backup failed during rollback: {s3_err}")
                    log_service_info(f"Rolled back SKU from {current_sku} to {rolled_back_sku}")
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            log_app_error(f"Error rolling back SKU: {e}")

    def get_all_comics(self, page=None, per_page=None):
        """
        Retrieve all comics, with optional pagination.
        
        Args:
            page (int, optional): The page number to retrieve.
            per_page (int, optional): The number of items per page.
            
        Returns:
            list or dict: A list of Comic objects if not paginated, 
                          or a paginated result dictionary.
        """
        if page and per_page:
            return self.get_comics_paginated(page=page, per_page=per_page)
        
        csv_service = self._get_csv_service()
        return csv_service.read_all()

    def get_comics_paginated(self, page=1, per_page=20, search_term='', listing_type='', sort_by='sku_asc', not_listed_subfilter='both'):
        """
        Retrieve paginated comics with optional filtering, search, and sorting.

        Args:
            page (int): The 1-indexed page number. Defaults to 1.
            per_page (int): Items per page. Defaults to 20.
            search_term (str): Text to search for across multiple fields.
            listing_type (str): Filter by 'Giveaway', 'Not Listed', 'For Sale eBay', 'WhatNot', or None.
            sort_by (str): Sort order - 'sku_asc' or 'sku_desc'. Defaults to 'sku_asc'.
            not_listed_subfilter (str): When listing_type is 'Not Listed', filter by:
                - 'both': Items not listed on both eBay and WhatNot (default)
                - 'ebay': Items missing from eBay only
                - 'whatnot': Items missing from WhatNot only

        Returns:
            dict: Paginated results and filtered statistics.
        """
        csv_service = self._get_csv_service()
        all_comics = csv_service.read_all()

        filtered_comics = all_comics

        def is_giveaway_comic(comic):
            return is_giveaway(comic.title, comic.listing_type)

        # 1. Apply search filter
        if search_term:
            search_lower = search_term.lower()
            filtered_comics = [
                comic for comic in filtered_comics
                if (search_lower in (comic.sku or '').lower() or
                    search_lower in (comic.title or '').lower() or
                    search_lower in (comic.comic_type or '').lower() or
                    search_lower in (comic.condition or '').lower())
            ]

        # 2. Apply listing type filter
        if listing_type:
            if listing_type == 'Giveaway':
                filtered_comics = [
                    comic for comic in filtered_comics
                    if is_giveaway_comic(comic)
                ]
            elif listing_type == 'Not Listed':
                # Filter for items NOT listed on platforms (excluding giveaways)
                # First exclude giveaways
                non_giveaway_comics = [
                    comic for comic in filtered_comics
                    if not is_giveaway_comic(comic)
                ]

                # Then apply sub-filter based on platform listings
                if not_listed_subfilter == 'both':
                    # Items not listed on BOTH eBay AND WhatNot
                    filtered_comics = [
                        comic for comic in non_giveaway_comics
                        if not (comic.ebay_item_id or '').strip()
                        and (comic.whatnot_item_id or '').strip().upper() != 'TRUE'
                    ]
                elif not_listed_subfilter == 'ebay':
                    # Items missing from eBay only (may or may not be on WhatNot)
                    filtered_comics = [
                        comic for comic in non_giveaway_comics
                        if not (comic.ebay_item_id or '').strip()
                    ]
                elif not_listed_subfilter == 'whatnot':
                    # Items missing from WhatNot only (may or may not be on eBay)
                    filtered_comics = [
                        comic for comic in non_giveaway_comics
                        if (comic.whatnot_item_id or '').strip().upper() != 'TRUE'
                    ]
                elif not_listed_subfilter == 'giveaway':
                    # Items not in giveaway (reverse of the Giveaway filter)
                    filtered_comics = non_giveaway_comics
                else:
                    # Default to 'both' if invalid sub-filter
                    filtered_comics = [
                        comic for comic in non_giveaway_comics
                        if not (comic.ebay_item_id or '').strip()
                        and (comic.whatnot_item_id or '').strip().upper() != 'TRUE'
                    ]
            elif listing_type == 'For Sale eBay':
                # Filter for items that have an eBay Item ID
                filtered_comics = [
                    comic for comic in filtered_comics
                    if (comic.ebay_item_id or '').strip() and not is_giveaway_comic(comic)
                ]
            elif listing_type == 'WhatNot':
                # Filter for items that are listed on WhatNot (exclude giveaways)
                filtered_comics = [
                    comic for comic in filtered_comics
                    if (comic.whatnot_item_id or '').strip().upper() == 'TRUE'
                    and not is_giveaway_comic(comic)
                ]

        # 2.5. Apply sorting
        if sort_by == 'sku_desc':
            filtered_comics = sorted(filtered_comics, key=lambda c: int(c.sku) if (c.sku and c.sku.isdigit()) else 0, reverse=True)
        elif sort_by == 'title_asc':
            filtered_comics = sorted(filtered_comics, key=lambda c: (c.title or '').strip().lower())
        elif sort_by == 'title_desc':
            filtered_comics = sorted(filtered_comics, key=lambda c: (c.title or '').strip().lower(), reverse=True)
        elif sort_by == 'price_asc':
            def _price_key(c):
                try:
                    return float(str(c.price or '0').replace('$', '').replace(',', ''))
                except (ValueError, TypeError):
                    return 0.0
            filtered_comics = sorted(filtered_comics, key=_price_key)
        elif sort_by == 'price_desc':
            def _price_key_desc(c):
                try:
                    return float(str(c.price or '0').replace('$', '').replace(',', ''))
                except (ValueError, TypeError):
                    return 0.0
            filtered_comics = sorted(filtered_comics, key=_price_key_desc, reverse=True)
        else:  # default: sku_asc
            filtered_comics = sorted(filtered_comics, key=lambda c: int(c.sku) if (c.sku and c.sku.isdigit()) else 0)

        # 3. Calculate stats for the filtered set
        total_value = 0
        giveaway_count = 0
        for comic in filtered_comics:
            if is_giveaway_comic(comic):
                giveaway_count += 1
            else:
                try:
                    price_str = str(comic.price or '0').replace('$', '').replace(',', '')
                    price = float(price_str)
                    quantity = int(comic.quantity or 1)
                    total_value += (price * quantity)
                except (ValueError, TypeError):
                    continue

        # 4. Paginate results
        total = len(filtered_comics)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_comics = filtered_comics[start:end]

        return {
            'comics': paginated_comics,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page,
                'has_next': end < total,
                'has_prev': page > 1,
                'total_value': total_value,
                'giveaway_count': giveaway_count
            }
        }

    def get_comic(self, sku):
        """
        Retrieve a single comic by its SKU.
        
        Args:
            sku (str): The unique identifier of the comic.
            
        Returns:
            Comic or None: The Comic instance if found, else None.
        """
        csv_service = self._get_csv_service()
        return csv_service.find_by_sku(sku)
    
    def create_comic(self, comic_data, image_files=None, duplicate_image_urls=None):
        """
        Create and save a new comic listing.
        
        This process includes:
        1) Generating a new SKU.
        2) Handling image duplication if requested.
        3) Uploading and processing new images to S3.
        4) Validating the comic data.
        5) Saving to the CSV inventory.
        6) Triggering an S3 backup of the inventory.
        
        Args:
            comic_data (dict): Dictionary of comic attributes.
            image_files (list, optional): List of file-like objects for images.
            duplicate_image_urls (list, optional): List of S3 URLs to duplicate.
            
        Returns:
            tuple: (bool, Comic or str) Success status and the created Comic 
                   instance or an error message.
        """
        sku = None
        try:
            # 1. Generate SKU
            sku = self.get_next_sku()
            comic_data['sku'] = sku

            image_urls = []

            # 2. Handle image duplication if requested
            if duplicate_image_urls:
                log_service_info(f"Duplicating {len(duplicate_image_urls)} images for new SKU {sku}")
                new_duplicated_urls = s3_service.duplicate_images(sku, duplicate_image_urls)
                image_urls.extend(new_duplicated_urls)

            # 3. Upload new images if provided
            if image_files:
                # Adjust start_index if we already have duplicated images
                start_idx = len(image_urls) + 1
                new_urls = self._upload_images(sku, image_files, start_index=start_idx)
                image_urls.extend(new_urls)

            comic_data['image_urls'] = image_urls

            # 4. Create comic object
            comic = Comic.from_dict(comic_data)

            # 5. Validate
            is_valid, error = comic.validate()
            if not is_valid:
                # Rollback SKU on validation failure
                if sku:
                    self._rollback_sku(expected_sku=sku)
                return False, error

            # 6. Save to CSV
            csv_service = self._get_csv_service()
            if csv_service.add(comic):
                # Backup CSV to S3 for state sync (use user-specific CSV)
                user_csv = get_user_csv_file()
                s3_service.backup_main_csv_to_s3(str(user_csv))
                return True, comic
            else:
                # Rollback SKU on save failure
                if sku:
                    self._rollback_sku(expected_sku=sku)
                return False, "Failed to save comic to CSV"

        except Exception as e:
            log_app_error(f"Error creating comic: {e}")
            # Rollback SKU on exception
            if sku:
                self._rollback_sku(expected_sku=sku)
            return False, safe_error_message(e)
    
    def update_comic(self, sku, comic_data, new_image_files=None, removed_image_urls=None, reordered_image_urls=None):
        """
        Update an existing comic listing.
        
        This method supports updating comic metadata, uploading new images,
        deleting removed images from S3, and preserving the order of existing
        images if they were rearranged by the user.
        
        Args:
            sku (str): The unique SKU of the comic to update.
            comic_data (dict): Dictionary of updated comic attributes.
            new_image_files (list, optional): List of new image files to upload.
            removed_image_urls (list, optional): List of S3 URLs to be deleted.
            reordered_image_urls (list, optional): List of existing S3 URLs in their 
                                                  target display order.
            
        Returns:
            tuple: (bool, Comic or str) Success status and the updated Comic 
                   instance or an error message.
        """
        try:
            csv_service = self._get_csv_service()

            # Get existing comic
            existing_comic = csv_service.find_by_sku(sku)
            if not existing_comic:
                return False, f"Comic with SKU {sku} not found"

             # Handle removed images
            if removed_image_urls:

                # SAFETY CHECK: Prevent mass deletion if suspicious
                protection = get_protection()
                total_images = len(existing_comic.image_urls) if existing_comic.image_urls else 0

                is_safe, reason = protection.check_deletion_safety(
                    deletion_count=len(removed_image_urls),
                    total_count=total_images,
                    operation_name=f"update_comic_SKU_{sku}"
                )

                if not is_safe:
                    log_app_error(f"Image deletion blocked for SKU {sku}: {reason}")
                    # Don't fail the entire update - just skip the deletions and log warning
                    log_app_error(f"Skipping image deletions for safety - keeping all existing images")
                    removed_image_urls = []  # Clear the removal list
                else:
                    # Safe to delete
                    for url in removed_image_urls:
                        s3_service.delete_file(url, delete_thumbnail=True)

                    # Record deletion
                    if len(removed_image_urls) > 0:
                        protection.record_deletion(len(removed_image_urls))

            # Start with reordered existing images (if provided), otherwise use existing order
            if reordered_image_urls is not None:
                final_image_urls = reordered_image_urls.copy()
            else:
                # Fallback: keep existing images that weren't removed
                final_image_urls = [url for url in existing_comic.image_urls if url not in (removed_image_urls or [])]

            # Upload new images and append to the end
            if new_image_files:
                start_index = len(final_image_urls) + 1
                new_urls = self._upload_images(sku, new_image_files, start_index=start_index)
                final_image_urls.extend(new_urls)

            # Update comic data
            comic_data[WHATNOT_FIELD_NAMES['SKU']] = sku
            comic_data['image_urls'] = final_image_urls


            # Update metadata fields
            comic_data[METADATA_FIELD_NAMES['LAST_MODIFIED']] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # If this comic doesn't have added_by or date_added, set them now
            if not comic_data.get(METADATA_FIELD_NAMES['ADDED_BY']):
                comic_data[METADATA_FIELD_NAMES['ADDED_BY']] = session.get('username', 'unknown')
            if not comic_data.get(METADATA_FIELD_NAMES['DATE_ADDED']):
                comic_data[METADATA_FIELD_NAMES['DATE_ADDED']] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            updated_comic = Comic.from_dict(comic_data)

            # Validate
            is_valid, error = updated_comic.validate()
            if not is_valid:
                return False, error
            
            # Save to CSV
            if csv_service.update(sku, updated_comic):
                # Backup CSV to S3 for state sync (use user-specific CSV)
                user_csv = get_user_csv_file()
                s3_service.backup_main_csv_to_s3(str(user_csv))
                return True, updated_comic
            else:
                return False, "Failed to update comic in CSV"

        except Exception as e:
            log_app_error(f"Error updating comic: {e}")
            return False, safe_error_message(e)
    
    def delete_comic(self, sku):
        """
        Move a single comic listing to the trash.
        
        The comic is removed from active inventory and preserved in the
        trash system for a 30-day retention period before final deletion.
        
        Args:
            sku (str): The SKU of the comic to delete.
            
        Returns:
            tuple: (bool, str) Success status and a descriptive message.
        """
        try:

            csv_service = self._get_csv_service()

            # Get the comic before deletion
            comic = csv_service.find_by_sku(sku)
            if not comic:
                return False, f"Comic with SKU {sku} not found"

            # Create trash item from comic
            trash_item = TrashItem.from_comic(comic)

            # Add to trash
            if not trash_service.add(trash_item):
                return False, "Failed to move comic to trash"

            # Delete from CSV
            success, deleted_comic = csv_service.delete(sku)
            if not success:
                # Rollback trash addition if CSV deletion fails
                trash_service.delete(sku)
                return False, f"Failed to delete comic from inventory"

            # Backup CSV to S3 for state sync (use user-specific CSV)
            s3_service.backup_main_csv_to_s3(str(get_user_csv_file()))

            # Images stay in production folder (not deleted)
            log_service_info(f"Moved comic {sku} to trash (30-day retention)")

            return True, f"Comic with SKU {sku} moved to trash"

        except Exception as e:
            log_app_error(f"Error moving comic to trash: {e}")
            return False, safe_error_message(e)

    def delete_all_comics(self):
        """
        Move all comics in the current inventory to the trash.
        
        Clears the entire working CSV file and creates a trash entry for 
        each item. Images are preserved in the production storage.
        
        Returns:
            dict: Summary containing 'comics_deleted' count and a status 'message'.
        """
        try:

            csv_service = self._get_csv_service()

            # Get all comics BEFORE clearing
            all_comics = csv_service.read_all()
            comics_deleted = len(all_comics)

            if comics_deleted == 0:
                return {
                    'comics_deleted': 0,
                    'message': 'No comics to delete'
                }

            log_service_info(f"Moving {comics_deleted} comics to trash")

            # Add each comic to trash
            for comic in all_comics:
                trash_item = TrashItem.from_comic(comic)
                trash_service.add(trash_item)

            # Clear CSV after all items are in trash
            csv_service.clear_all()

            # Backup empty CSV to S3 for state sync (use user-specific CSV)
            s3_service.backup_main_csv_to_s3(str(get_user_csv_file()))

            # Images stay in production folder
            log_service_info(f"Moved {comics_deleted} comics to trash (30-day retention)")

            return {
                'comics_deleted': comics_deleted,
                'images_deleted': 0,
                'message': f"Successfully moved {comics_deleted} comics to trash"
            }

        except Exception as e:
            log_app_error(f"Error moving all comics to trash: {e}")
            raise

    def bulk_update_comics(self, skus, updates):
        """
        Update multiple comics with specified field values.

        Args:
            skus (list): List of unique SKUs to be updated.
            updates (dict): Dictionary of field names and values to update.

        Returns:
            int: The total count of comics successfully updated.
        """
        try:
            csv_service = self._get_csv_service()
            updated_count = 0

            for sku in skus:
                # Get comic by SKU
                comic = csv_service.find_by_sku(sku)
                if not comic:
                    log_service_warning(f"Comic {sku} not found, skipping")
                    continue

                # Convert comic to dict for updates
                comic_dict = comic.to_dict()

                # Apply updates
                for field, value in updates.items():
                    comic_dict[field] = value

                # Update last modified timestamp
                comic_dict[METADATA_FIELD_NAMES['LAST_MODIFIED']] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Convert back to Comic object
                updated_comic = Comic.from_dict(comic_dict)

                # Update in CSV
                success = csv_service.update(sku, updated_comic)
                if success:
                    updated_count += 1
                else:
                    log_service_warning(f"Failed to update comic {sku} in CSV")

            # Backup CSV to S3 for state sync if any were updated
            if updated_count > 0:
                s3_service.backup_main_csv_to_s3(str(get_user_csv_file()))
                log_service_info(f"Bulk updated {updated_count} comics")

            return updated_count

        except Exception as e:
            log_app_error(f"Error in bulk_update_comics: {e}")
            raise

    def delete_selected_comics(self, skus):
        """
        Move a specific list of comics to the trash.

        Args:
            skus (list): List of unique SKUs to be moved to trash.

        Returns:
            tuple: (int, str) The total count of comics successfully deleted
                   and a status message.
        """
        try:

            csv_service = self._get_csv_service()
            deleted_count = 0

            for sku in skus:
                # Get comic before deletion
                comic = csv_service.find_by_sku(sku)
                if not comic:
                    log_service_warning(f"Comic {sku} not found, skipping")
                    continue

                # Create trash item
                trash_item = TrashItem.from_comic(comic)
                trash_service.add(trash_item)

                # Delete from CSV
                success, deleted_comic = csv_service.delete(sku)
                if success:
                    deleted_count += 1

            # Backup CSV to S3 for state sync if any were deleted
            if deleted_count > 0:
                s3_service.backup_main_csv_to_s3(str(get_user_csv_file()))
                log_service_info(f"Moved {deleted_count} comics to trash (30-day retention)")

            return deleted_count, f"Successfully moved {deleted_count} comics to trash"

        except Exception as e:
            log_app_error(f"Error moving selected comics to trash: {e}")
            raise

    def get_comic_stats(self):
        """
        Calculate summary statistics for the entire comic inventory.
        
        Computes total count, total dollar value (excluding giveaways),
        and the count of giveaway items based on title prefixes.
        
        Returns:
            dict: Dictionary containing 'total_count', 'total_value', 
                  and 'giveaway_count'.
        """
        try:
            csv_service = self._get_csv_service()
            all_comics = csv_service.read_all()
            
            total_value = 0
            giveaway_count = 0

            for comic in all_comics:
                if is_giveaway(comic.title, comic.listing_type):
                    giveaway_count += 1
                else:
                    try:
                        price_str = str(comic.price or '0').replace('$', '').replace(',', '')
                        price = float(price_str)
                        quantity = int(comic.quantity or 1)
                        total_value += (price * quantity)
                    except (ValueError, TypeError):
                        continue
                        
            return {
                'total_count': len(all_comics),
                'total_value': total_value,
                'giveaway_count': giveaway_count
            }
        except Exception as e:
            log_app_error(f"Error getting comic stats: {e}")
            return {'total_count': 0, 'total_value': 0, 'giveaway_count': 0}

    def get_comic_count(self):
        """
        Get the total number of comics in the active inventory.
        
        Returns:
            int: The total count of items in the CSV file.
        """
        try:
            csv_service = self._get_csv_service()
            return len(csv_service.read_all())
        except Exception as e:
            log_app_error(f"Error getting comic count: {e}")
            return 0

    def get_selected_comics(self, skus):
        """
        Retrieve a specific set of comics by their SKUs.

        Args:
            skus (list): List of SKUs to fetch.

        Returns:
            list: List of Comic objects found matching the SKUs.
        """
        try:
            csv_service = self._get_csv_service()
            all_comics = csv_service.read_all()
            return [comic for comic in all_comics if str(comic.sku) in [str(sku) for sku in skus]]
        except Exception as e:
            log_app_error(f"Error getting selected comics: {e}")
            return []

    def _upload_images(self, sku, image_files, start_index=1):
        """
        Helper method to upload and process multiple images for a comic.
        
        Saves images temporarily, uploads them to S3 with SKU-based naming,
        generates thumbnails, and cleans up temporary files. If any upload 
        fails, it attempts to roll back already uploaded images for consistency.
        
        Args:
            sku (str): The SKU prefix for the image filenames.
            image_files (list): List of file-like objects to upload.
            start_index (int): The starting number for image suffix (e.g., SKU_1.jpg).
            
        Returns:
            list: List of full-size S3 URLs for the uploaded images.
            
        Raises:
            Exception: If any part of the upload process fails.
        """
        image_urls = []
        upload_folder = Path(current_app.config['UPLOAD_FOLDER'])
        upload_folder.mkdir(parents=True, exist_ok=True)

        try:
            for idx, image_file in enumerate(image_files, start=start_index):
                if image_file and allowed_file(image_file.filename, current_app.config.get('ALLOWED_EXTENSIONS')):
                    # Save temporarily
                    filename = generate_unique_filename(image_file.filename)
                    file_path = upload_folder / filename
                    image_file.save(str(file_path))
                    
                    # Validate that the file was saved properly and is a valid image
                    try:
                        with Image.open(str(file_path)) as img:
                            img.verify()
                        # Need to reopen after verify() as it closes the file
                        with Image.open(str(file_path)) as img:
                            pass  # Just verify it can be opened
                    except Exception as validate_error:
                        # File is corrupted or not a valid image - clean up and skip
                        try:
                            os.remove(str(file_path))
                        except Exception:
                            pass
                        log_service_warning(f"Uploaded file for image {idx} is corrupted or invalid: {validate_error}")
                        raise Exception(f"Image {idx} failed validation - file may be corrupted or incomplete")

                    # Upload to S3
                    s3_key = f"{sku}_{idx}.jpg"
                    result = s3_service.upload_file(str(file_path), s3_key, create_thumb=True)

                    if result and result.get('full'):
                        image_urls.append(result['full'])
                    else:
                        # Upload failed - clean up temporary file and raise exception
                        try:
                            os.remove(str(file_path))
                        except Exception:
                            pass
                        raise Exception(f"Failed to upload image {idx} to S3")

                    # Clean up temporary file
                    try:
                        os.remove(str(file_path))
                    except Exception as e:
                        log_service_warning(f"Could not delete temp file {file_path}: {e}")

            return image_urls

        except Exception as e:
            # If any upload failed, clean up all successfully uploaded images for this SKU
            log_app_error(f"Image upload failed for SKU {sku}, cleaning up {len(image_urls)} uploaded images: {e}")
            for image_url in image_urls:
                try:
                    s3_service.delete_file(image_url, delete_thumbnail=True)
                    log_service_info(f"Cleaned up image: {image_url}")
                except Exception as cleanup_error:
                    log_app_error(f"Error cleaning up image {image_url}: {cleanup_error}")
            # Re-raise the exception after cleanup
            raise

    def save_comic(self, comic):
        """Persist an updated Comic instance back to CSV and refresh S3 backup."""
        csv_service = self._get_csv_service()
        if not csv_service.update(comic.sku, comic):
            raise RuntimeError(f"Failed to save comic {comic.sku}")
        s3_service.backup_main_csv_to_s3(str(get_user_csv_file()))
        return comic

    def cleanup_orphaned_images(self):
        """
        Identify and remove images from S3 and local storage that are no
        longer associated with any active or trashed comic.

        Returns:
            dict: Summary of the cleanup operation results.
        """
        try:

            log_service_info("Starting orphaned image cleanup")

            # 1. Get all valid SKUs (Active + Trash)
            active_comics = self.get_all_comics()
            active_skus = {str(comic.sku) for comic in active_comics}

            trash_items = trash_service.list_all()
            trash_skus = {str(item.sku) for item in trash_items}

            all_valid_skus = active_skus | trash_skus
            log_service_info(f"Found {len(active_skus)} active SKUs and {len(trash_skus)} trash SKUs")

            # SAFETY CHECK 1: CSV health check - prevent cleanup if CSV appears empty
            total_comics = len(active_skus) + len(trash_skus)
            try:
                check_csv_health_before_cleanup(total_comics, "cleanup_orphaned_images")
            except ValueError as e:
                log_app_error(f"Orphaned image cleanup blocked by safety check: {e}")
                return {
                    'success': False,
                    'error': f"Safety check failed: {safe_error_message(e)}",
                    'total_images': 0,
                    'deleted_count': 0,
                    'preserved_count': 0
                }

            # 2. Get all images from S3
            bucket_name = s3_service.bucket_name
            if not bucket_name:
                return {'success': False, 'error': 'S3 bucket not configured'}

            paginator = s3_service.client().get_paginator('list_objects_v2')
            images_prefix = get_user_s3_images_prefix()
            pages = paginator.paginate(Bucket=bucket_name, Prefix=images_prefix)

            all_s3_keys = []
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        # Skip the folder itself
                        if key != images_prefix and not key.endswith('/'):
                            all_s3_keys.append(key)

            log_service_info(f"Found {len(all_s3_keys)} images in S3")

            # 3. Count orphaned images BEFORE deleting (for safety check)
            orphaned_keys = []
            for image_key in all_s3_keys:
                filename = image_key.split('/')[-1]

                # Extract SKU from filename (handle regular and thumbnails)
                if '_thumb.' in filename:
                    sku = filename.split('_thumb.')[0].rsplit('_', 1)[0]
                else:
                    sku = filename.rsplit('_', 1)[0].split('.')[0]

                # If SKU is NOT valid, mark as orphan
                if sku not in all_valid_skus:
                    orphaned_keys.append(image_key)

            log_service_info(f"Found {len(orphaned_keys)} orphaned images to delete")

            # SAFETY CHECK 2: Prevent mass deletion
            protection = get_protection()
            is_safe, reason = protection.check_deletion_safety(
                deletion_count=len(orphaned_keys),
                total_count=len(all_s3_keys),
                operation_name="cleanup_orphaned_images"
            )

            if not is_safe:
                log_app_error(f"Orphaned image cleanup blocked: {reason}")
                return {
                    'success': False,
                    'error': f"Safety check failed: {reason}",
                    'total_images': len(all_s3_keys),
                    'would_delete_count': len(orphaned_keys),
                    'deleted_count': 0,
                    'preserved_count': len(all_s3_keys)
                }

            # 4. Delete orphaned images (safety checks passed)
            s3_deleted_count = 0
            local_deleted_count = 0
            preserved_count = len(all_s3_keys) - len(orphaned_keys)

            instance_path = Path(current_app.instance_path)
            local_images_dir = instance_path / 'images'

            for image_key in orphaned_keys:
                # Extract filename from key (e.g., "production/images/1001_1.jpg")
                filename = image_key.split('/')[-1]

                # Delete from S3
                try:
                    s3_service.client().delete_object(Bucket=bucket_name, Key=image_key)
                    s3_deleted_count += 1
                    log_service_info(f"Deleted orphaned S3 image: {image_key}")
                except Exception as e:
                    log_app_error(f"Failed to delete orphaned S3 image {image_key}: {e}")

                # Also delete from local if exists
                local_path = local_images_dir / filename
                if local_path.exists():
                    try:
                        local_path.unlink()
                        local_deleted_count += 1
                        log_service_info(f"Deleted orphaned local image: {local_path}")
                    except Exception as e:
                        log_app_error(f"Failed to delete orphaned local image {local_path}: {e}")

            # Record deletion for rate limiting
            if s3_deleted_count > 0:
                protection.record_deletion(s3_deleted_count)

            return {
                'success': True,
                'total_images': len(all_s3_keys),
                'deleted_count': s3_deleted_count,
                'local_deleted_count': local_deleted_count,
                'preserved_count': preserved_count
            }

        except Exception as e:
            log_app_error(f"Error in orphaned image cleanup: {e}")
            return {'success': False, 'error': safe_error_message(e)}


def initialize_sku_file(sku_file_path):
    """
    Ensure the SKU counter file exists and is populated.
    
    If the file is missing, it attempts to initialize it with a default 
    value (1000).
    
    Args:
        sku_file_path (str or Path): Path where the SKU file should reside.
    """
    sku_file = Path(sku_file_path)
    if not sku_file.exists():
        sku_file.parent.mkdir(parents=True, exist_ok=True)

        # Try to restore from S3 first
        sku_from_s3 = s3_service.restore_sku_from_s3()
        if sku_from_s3 is not None:
            # s3_service.restore_sku_from_s3() returns {'sku': int, 'last_modified': datetime}
            sku_val = None
            if isinstance(sku_from_s3, dict) and 'sku' in sku_from_s3:
                sku_val = sku_from_s3['sku']
            else:
                # Fallback: if it's a plain numeric/string value
                try:
                    sku_val = int(sku_from_s3)
                except Exception:
                    sku_val = None

            if sku_val is not None:
                with open(sku_file, 'w') as f:
                    f.write(f"{int(sku_val)}\n")
            else:
                # Unexpected format from S3, fall back to default
                with open(sku_file, 'w') as f:
                    f.write("1000\n")
        else:
            # No backup found, start from default
            with open(sku_file, 'w') as f:
                f.write("1000\n")


# Singleton instance - created on demand
_comic_service_instance = None

def get_comic_service():
    """Get or create the singleton ComicService instance."""
    global _comic_service_instance
    if _comic_service_instance is None:
        _comic_service_instance = ComicService()
    return _comic_service_instance

# For backwards compatibility, also export as comic_service
comic_service = get_comic_service()
