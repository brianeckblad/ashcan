"""System routes - System stats, validation, cleanup, and utilities.

This module handles:
- System statistics for dashboard
- Validation data for forms
- Next SKU generation
- Image cleanup operations
- Backup download

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import jsonify, current_app, send_file, Response
from app.utils.logging_utils import safe_error_message
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required
from app.services.comic_service import comic_service
from app.services.s3_service import s3_service
from app.services.csv_service import CSVService
from app.utils.whatnot_validators import WHATNOT_FIELD_VALIDATION, WHATNOT_FIELD_NAMES as WFN, METADATA_FIELD_NAMES as MFN
from app.utils.ebay_helpers import get_ebay_validation_data
from app.utils.helpers import get_directory_size, is_giveaway as _is_giveaway
from app.utils.user_context import get_user_trash_dir, get_user_snapshots_dir, get_user_csv_file, get_user_s3_images_prefix, get_current_username
from pathlib import Path
import io
import shutil
import time
import platform
import zipfile
from datetime import datetime
from app import APP_START_TIME


@api_bp.route('/next-sku')
@login_required
def next_sku() -> Response:
    """Get the next available SKU number for new comics.

    Returns the current SKU counter value which will be used for the next
    comic added to inventory. SKU counter automatically increments after use.

    Returns:
        Response: Flask JSON response containing:
            - sku (str): Next available SKU number

    Status Codes:
        200: Successfully retrieved SKU
        500: Server error (unlikely)

    Example Response:
        {
            "sku": "1051"
        }

    Note:
        - SKU is stored in instance/sku.txt
        - Auto-increments when new comic is added
        - Can be manually adjusted in admin settings
    """
    return jsonify({'sku': comic_service.get_current_sku()})


@api_bp.route('/validation-data')
@login_required
def get_validation_data() -> Response:
    """Get WhatNot field validation metadata for form building.

    Provides validation rules, field types, and allowed values for all
    WhatNot form fields. Used by frontend to build dynamic forms with
    proper validation.

    Returns:
        Response: Flask JSON response with validation metadata for fields:
            - Type (required, options)
            - Category (required, options)
            - Sub-Category (required, options based on Category)
            - Condition (required, options)
            - Price (required, numeric)
            - Title (required, max length)
            - Description (optional, max length)
            - Offerable (boolean)
            - Image URLs (required, 1-8 images)

    Status Codes:
        200: Successfully retrieved validation data

    Example Response:
        {
            "Type": {
                "required": true,
                "type": "select",
                "options": ["Buy it Now", "Auction"]
            },
            "Category": {
                "required": true,
                "type": "select",
                "options": ["Comics & Manga", "Toys", ...]
            },
            ...
        }

    Note:
        - Used for frontend form validation
        - Matches WhatNot platform requirements
        - Sub-category options depend on selected category
    """
    return jsonify(WHATNOT_FIELD_VALIDATION)


@api_bp.route('/validation-data/ebay')
@login_required
def get_ebay_validation_data_route() -> Response:
    """Get eBay field validation metadata for form building.

    Provides validation rules, field types, and allowed values for all
    eBay listing fields. Used by frontend to build eBay listing forms.

    Returns:
        Response: Flask JSON response with eBay validation metadata:
            - Format (required: FixedPrice, Auction, etc.)
            - Duration (required: GTC, Days_7, etc.)
            - Condition (required: condition IDs)
            - Category (required: category search)
            - Item Specifics (optional: key-value pairs)
            - Shipping profiles (required)
            - Return policies (required)
            - Payment policies (required)

    Status Codes:
        200: Successfully retrieved validation data

    Example Response:
        {
            "format": {
                "options": ["FixedPrice", "Chinese", "StoresFixedPrice"],
                "labels": {
                    "FixedPrice": "Fixed Price",
                    "Chinese": "Auction"
                }
            },
            "duration": {
                "FixedPrice": ["GTC", "Days_30", "Days_7"],
                "Chinese": ["Days_1", "Days_3", "Days_5", "Days_7"]
            },
            ...
        }

    Note:
        - Duration options depend on selected format
        - Category requires search via eBay Taxonomy API
        - Condition IDs map to eBay's condition system
    """
    return jsonify(get_ebay_validation_data())


@api_bp.route('/system-stats')
@login_required
def system_stats() -> Response:
    """Get comprehensive system statistics for dashboard display.

    Aggregates statistics from multiple sources including inventory, storage,
    eBay listings, and system health metrics. Used for main dashboard display.

    Returns:
        Response: Flask JSON response containing:
            - comic_count (int): Total comics in inventory
            - inventory_value (float): Total $ value of for-sale items
            - giveaway_value (float): Total $ value of giveaway items
            - comics_for_sale_value (float): Value of items marked for sale
            - ebay_listings_count (int): Active eBay listings
            - ebay_listings_value (float): Total value of eBay listings
            - image_count (int): Total images in S3
            - total_image_size (int): Total image storage in bytes
            - trash_size (int): Trash storage size in bytes
            - snapshots_size (int): Snapshots storage size in bytes
            - total_backup_size (int): Combined backup storage
            - disk_free_percent (float): Available disk space %
            - app_uptime_seconds (int): Application uptime
            - server_uptime_seconds (int, optional): Server uptime (Unix only)

    Status Codes:
        200: Successfully retrieved statistics
        500: Server error (partial data may be returned)

    Example Response:
        {
            "comic_count": 37,
            "inventory_value": 1845.50,
            "giveaway_value": 125.00,
            "comics_for_sale_value": 1720.50,
            "ebay_listings_count": 15,
            "ebay_listings_value": 675.00,
            "image_count": 245,
            "total_image_size": 52428800,
            "trash_size": 1048576,
            "snapshots_size": 2097152,
            "total_backup_size": 3145728,
            "disk_free_percent": 78.5,
            "app_uptime_seconds": 86400,
            "server_uptime_seconds": 604800
        }

    Note:
        - Inventory value calculated from Price field
        - Giveaways identified by "G-" or "G " prefix
        - eBay count includes only items with eBay Item IDs
        - Disk space measured on instance folder location
        - Server uptime only available on Unix-like systems
        - All monetary values in USD
    """
    try:
        # Get comic stats
        comic_stats = comic_service.get_comic_stats()

        # Get S3 image stats
        s3_stats = s3_service.get_storage_stats()
        image_count = s3_stats['image_count']
        total_image_size = s3_stats['total_image_size']

        # Get backup folder sizes (user-specific trash + snapshots)
        trash_size = get_directory_size(get_user_trash_dir())
        snapshots_size = get_directory_size(get_user_snapshots_dir())
        total_backup_size = trash_size + snapshots_size

        # Get disk space percentage (root / instance path)
        instance_path = Path(current_app.instance_path)
        disk_usage = shutil.disk_usage(instance_path)
        disk_free_percent = (disk_usage.free / disk_usage.total) * 100 if disk_usage.total > 0 else 0
        root_disk_used_percent = round(100 - disk_free_percent, 1)

        # Get app-specific disk usage (/opt/apps/)
        app_disk_used_percent = None
        try:
            app_disk_usage = shutil.disk_usage('/opt/apps/')
            app_disk_used_percent = round(
                (app_disk_usage.used / app_disk_usage.total) * 100, 1
            ) if app_disk_usage.total > 0 else 0
        except OSError:
            pass

        # Calculate application uptime
        app_uptime_seconds = int(time.time() - APP_START_TIME)

        # Get server uptime (Unix-like systems)
        server_uptime_seconds = None
        try:
            if platform.system() != 'Windows':
                with open('/proc/uptime', 'r') as f:
                    server_uptime_seconds = int(float(f.readline().split()[0]))
        except (OSError, ValueError):
            pass

        # Get eBay listings stats and calculate values from inventory by reading CSV
        ebay_listings_count = 0
        ebay_listings_value = 0
        giveaway_value = 0
        comics_for_sale_value = 0

        # Calculate values from inventory by reading user-specific CSV
        try:
            user_csv_file = get_user_csv_file()
            csv_service = CSVService(str(user_csv_file))
            comics = csv_service.read_all()

            for comic in comics:
                try:
                    # Use to_dict() if available, otherwise fall back to direct attribute access
                    if hasattr(comic, 'to_dict'):
                        comic_dict = comic.to_dict()
                    else:
                        comic_dict = comic.__dict__ if hasattr(comic, '__dict__') else {}

                    title = (comic_dict.get(WFN['TITLE']) or comic_dict.get('title') or '').upper()
                    is_giveaway = _is_giveaway(title)

                    price = float(comic_dict.get(WFN['PRICE']) or comic_dict.get('price') or 0)
                    quantity = int(comic_dict.get(WFN['QUANTITY']) or comic_dict.get('quantity') or 1)
                    item_value = price * quantity

                    if is_giveaway:
                        # Giveaways use "Cost Per Item" field for value calculation
                        cost_per_item = float(comic_dict.get(WFN['COST_PER_ITEM']) or comic_dict.get('cost_per_item') or 0)
                        giveaway_value += (cost_per_item * quantity)
                    else:
                        comics_for_sale_value += item_value

                        # Check if this item has an eBay Item ID (it's listed on eBay)
                        ebay_item_id = (comic_dict.get(MFN['EBAY_ITEM_ID']) or comic_dict.get('ebay_item_id') or '').strip()
                        if ebay_item_id:
                            ebay_listings_count += 1
                            ebay_listings_value += item_value
                except (ValueError, TypeError, AttributeError) as e:
                    current_app.logger.debug(f"Error processing comic in stats: {e}")
                    continue
        except Exception as e:
            # If CSV read fails, use stats from comic_service
            current_app.logger.warning(f"Error reading CSV for stats: {e}")
            comics_for_sale_value = (comic_stats['total_value'] or 0)

        return jsonify({
            'success': True,
            'stats': {
                'comic_count': comic_stats['total_count'],
                'giveaway_count': comic_stats['giveaway_count'],
                'inventory_value': comics_for_sale_value,
                'giveaway_value': giveaway_value,
                'ebay_listings_count': ebay_listings_count,
                'ebay_listings_value': ebay_listings_value,
                'image_count': image_count,
                'total_image_size': total_image_size,
                'total_backup_size': total_backup_size,
                'disk_free_percent': round(disk_free_percent, 1),
                'root_disk_used_percent': root_disk_used_percent,
                'app_disk_used_percent': app_disk_used_percent,
                'app_uptime_seconds': app_uptime_seconds,
                'server_uptime_seconds': server_uptime_seconds,
                'disk_used': disk_usage.used,
                'disk_total': disk_usage.total
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error getting system stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve system statistics'}), 500


@api_bp.route('/cleanup-orphaned-images', methods=['POST'])
@login_required
@csrf_required
def cleanup_orphaned_images() -> Response:
    """Clean up orphaned images from S3 and local storage.

    Identifies and deletes images that exist in storage but are not referenced
    by any comic in the inventory. Also identifies images referenced in CSV
    but missing from storage.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether cleanup succeeded
            - s3_orphans_deleted (int): Images deleted from S3
            - local_orphans_deleted (int): Images deleted locally
            - missing_images (int): Images in CSV but not in storage
            - missing_image_list (list, optional): List of missing image names
            - errors (int): Number of errors encountered
            - error (str, optional): Error message if failed

    Status Codes:
        200: Cleanup completed (check success for partial failures)
        500: Server error prevented cleanup

    Example Response:
        {
            "success": true,
            "s3_orphans_deleted": 12,
            "local_orphans_deleted": 3,
            "missing_images": 0,
            "errors": 0
        }

    Warning:
        - Permanently deletes orphaned images
        - Cannot be undone
        - Review missing images before running

    Note:
        - Also deletes associated thumbnails
        - Logs all deletions for audit trail
        - Safe to run periodically for maintenance
        - Won't delete images referenced in CSV
    """
    try:
        # Import a fresh ComicService instance (not the module-level singleton)
        # so this cleanup run uses the current user context.
        from app.services.comic_service import ComicService  # Deferred: requires app context
        fresh_service = ComicService()
        result = fresh_service.cleanup_orphaned_images()
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error in cleanup_orphaned_images route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/backup-download', methods=['POST'])
@login_required
@csrf_required
def backup_download() -> Response:
    """Create and download complete inventory backup as ZIP file.

    Generates a comprehensive backup containing the CSV inventory file,
    SKU counter, and all images. Useful for manual backups before major
    changes or for transferring to another system.

    Returns:
        Response: ZIP archive file download

    Status Codes:
        200: Backup created successfully
        404: CSV file not found
        500: Server error during backup creation

    ZIP Contents:
        - comics_export.csv (main inventory)
        - images/ (all comic images from S3)
    """
    try:

        username = get_current_username()
        current_app.logger.info(f"[User: {username}] Starting backup and download...")

        # Get user-specific CSV file
        csv_file_path = get_user_csv_file()
        if not Path(csv_file_path).exists():
            return jsonify({'success': False, 'error': 'CSV file not found'}), 404

        # Create ZIP in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add CSV file
            zipf.write(str(csv_file_path), 'comics_export.csv')
            current_app.logger.info(f"[User: {username}] Added CSV to ZIP")

            # Get all images from user's S3 folder
            bucket_name = current_app.config.get('S3_BUCKET')
            s3_images_prefix = get_user_s3_images_prefix()
            if bucket_name:
                current_app.logger.info(f"[User: {username}] Downloading images from S3 prefix: {s3_images_prefix}")

                # List all objects in user's images folder
                paginator = s3_service.client().get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_images_prefix)

                downloaded = 0
                for page in pages:
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            s3_key = obj['Key']

                            # Skip the folder itself
                            if s3_key == s3_images_prefix:
                                continue

                            filename = s3_key.split('/')[-1]

                            try:
                                # Download from S3
                                response = s3_service.client().get_object(Bucket=bucket_name, Key=s3_key)
                                image_data = response['Body'].read()

                                # Add to ZIP in images/ folder
                                zipf.writestr(f'images/{filename}', image_data)
                                downloaded += 1

                                if downloaded % 50 == 0:
                                    current_app.logger.info(f"Downloaded {downloaded} images...")

                            except Exception as e:
                                current_app.logger.warning(f"Error downloading {filename}: {e}")
                                continue

                current_app.logger.info(f"Added {downloaded} images to ZIP")

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'inventory_backup_{timestamp}.zip'

        # Seek to beginning of BytesIO buffer
        zip_buffer.seek(0)

        current_app.logger.info(f"Backup complete: {filename}")

        # Return ZIP file
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        current_app.logger.error(f"Error creating backup download: {e}", exc_info=True)
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500
