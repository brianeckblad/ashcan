"""Trash routes - Trash management and restore operations.

This module handles:
- Listing items in trash with statistics
- Restoring items from trash back to inventory
- Permanently deleting trash items (empty trash)

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import jsonify, current_app, Response
from app.utils.logging_utils import safe_error_message
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required
from app.services.s3_service import s3_service
from app.services.csv_service import CSVService
from app.utils.user_context import get_user_csv_file, get_current_username
from datetime import datetime, timezone, timedelta


@api_bp.route('/trash/list')
@login_required
def list_trash() -> Response:
    """Get list of items in trash with time-based statistics.

    Retrieves all deleted comics with their metadata and calculates statistics
    for items deleted today, this week, and this month.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether retrieval succeeded
            - items (list): List of trash item objects with:
                - sku (str): Comic SKU
                - title (str): Comic title
                - deleted_at (str): ISO datetime when deleted
                - deleted_by (str): User who deleted it
                - image_urls (list): Associated images
            - stats (dict): Statistics with counts:
                - total (int): Total items in trash
                - today (int): Items deleted today
                - this_week (int): Items deleted this week
                - this_month (int): Items deleted this month
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved trash list
        500: Server error occurred

    Example Response:
        {
            "success": true,
            "items": [
                {
                    "sku": "1001",
                    "title": "Amazing Spider-Man #1",
                    "deleted_at": "2026-01-30T10:30:00Z",
                    "deleted_by": "admin",
                    "image_urls": ["https://..."]
                }
            ],
            "stats": {
                "total": 5,
                "today": 2,
                "this_week": 4,
                "this_month": 5
            }
        }

    Note:
        - Items remain in trash until explicitly emptied
        - Statistics use UTC timezone
        - Images are not deleted when items are trashed
    """
    try:
        from app.services.trash_service import trash_service  # Deferred: requires app context

        items = trash_service.list_all()

        # Calculate stats - use timezone-aware UTC datetimes
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)

        today_count = 0
        week_count = 0
        month_count = 0

        for item in items:
            try:
                # Handle various date formats including 'Z' suffix
                deleted_at_str = item.deleted_at.replace('Z', '+00:00') if item.deleted_at else None
                if not deleted_at_str:
                    continue
                deleted_at = datetime.fromisoformat(deleted_at_str)
                # Ensure timezone-aware (assume UTC if naive)
                if deleted_at.tzinfo is None:
                    deleted_at = deleted_at.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                # Skip items with invalid dates
                continue
            if deleted_at >= today_start:
                today_count += 1
            if deleted_at >= week_start:
                week_count += 1
            if deleted_at >= month_start:
                month_count += 1

        return jsonify({
            'success': True,
            'items': [item.to_dict() for item in items],
            'stats': {
                'total': len(items),
                'today': today_count,
                'this_week': week_count,
                'this_month': month_count
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error listing trash: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/trash/restore/<sku>', methods=['POST'])
@login_required
@csrf_required
def restore_from_trash(sku: str) -> Response:
    """Restore a comic from trash back to active inventory.

    Moves a comic from trash back to the main inventory CSV file. Images are
    preserved during the restore operation.

    Path Parameters:
        sku (str): SKU of comic to restore

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether restore succeeded
            - message (str): Confirmation message
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully restored comic
        400: Comic SKU already exists in inventory
        404: Comic not found in trash
        500: Server error during restore

    Example Request:
        POST /trash/restore/1001

    Example Response:
        {
            "success": true,
            "message": "Comic 1001 restored successfully"
        }

    Note:
        - Automatically backs up CSV to S3 after restore
        - Cannot restore if SKU already exists in inventory
        - Images remain in S3 during entire process
        - Removes item from trash after successful restore
    """
    try:
        from app.services.trash_service import trash_service  # Deferred: requires app context

        # Get item from trash
        trash_item = trash_service.get(sku)
        if not trash_item:
            return jsonify({'success': False, 'error': f'Item {sku} not found in trash'}), 404

        # Convert to comic and add back to inventory
        # Use user-specific CSV file
        user_csv_file = get_user_csv_file()
        username = get_current_username()

        comic = trash_item.to_comic()
        csv_service = CSVService(str(user_csv_file))
        csv_service.initialize()

        # Check if SKU already exists in inventory
        existing = csv_service.find_by_sku(sku)
        if existing:
            return jsonify({'success': False, 'error': f'Comic with SKU {sku} already exists in inventory'}), 400

        # Add to inventory
        if csv_service.add(comic):
            # Remove from trash (restore only removes the JSON, preserves S3 images)
            trash_service.restore(sku)

            # Backup CSV to S3 (user-specific)
            s3_service.backup_main_csv_to_s3(str(user_csv_file))

            current_app.logger.info(f"[User: {username}] Restored comic {sku} from trash")
            return jsonify({'success': True, 'message': f'Comic {sku} restored successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to add comic to inventory'}), 500

    except Exception as e:
        current_app.logger.error(f"Error restoring from trash: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/trash/empty', methods=['POST'])
@login_required
@csrf_required
def empty_trash() -> Response:
    """Permanently delete all items in trash.

    Deletes all trash items and their associated images from S3. This operation
    cannot be undone.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether operation succeeded
            - message (str): Confirmation message
            - deleted_count (int): Number of items deleted
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully emptied trash
        500: Server error occurred

    Example Response:
        {
            "success": true,
            "message": "Trash emptied successfully",
            "deleted_count": 5
        }

    Warning:
        - This operation is PERMANENT and cannot be undone
        - Deletes both trash metadata and S3 images
        - Consider backing up before emptying trash

    Note:
        - Individual image deletion failures are logged but don't fail the operation
        - Returns success with count 0 if trash is already empty
    """
    try:
        from app.services.trash_service import trash_service  # Deferred: requires app context

        items = trash_service.list_all()
        count = len(items)

        if count == 0:
            return jsonify({'success': True, 'message': 'Trash is already empty', 'deleted_count': 0})

        # Delete all trash items (trash_service.delete() also handles S3 image cleanup)
        deleted_count = 0
        for item in items:
            if trash_service.delete(item.sku):
                deleted_count += 1


        current_app.logger.info(f"Emptied trash: {deleted_count} items permanently deleted")
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} items from trash',
            'deleted_count': deleted_count
        })

    except Exception as e:
        current_app.logger.error(f"Error emptying trash: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500
