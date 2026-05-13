"""Snapshot routes - Inventory snapshot management.

This module handles:
- Creating inventory snapshots (point-in-time backups)
- Listing available snapshots with metadata
- Restoring inventory from snapshots
- Deleting old snapshots

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import request, jsonify, current_app, Response
from app.utils.logging_utils import safe_error_message
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required


@api_bp.route('/snapshots/create', methods=['POST'])
@login_required
@csrf_required
def create_snapshot() -> Response:
    """Create a new point-in-time inventory snapshot.

    Creates a timestamped backup of the current inventory state, including
    the CSV file and SKU counter. Useful for creating restore points before
    major changes.

    Request Body (JSON):
        {
            "name": str,                    # Snapshot name
            "description": Optional[str]    # Optional description
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether snapshot was created
            - snapshot_id (str): ID of created snapshot
            - message (str): Confirmation message
            - error (str, optional): Error message if failed

    Status Codes:
        200: Snapshot created successfully
        400: Invalid request data
        500: Server error during creation

    Example Request:
        {
            "name": "Before bulk delete",
            "description": "Safety backup before removing old inventory"
        }

    Example Response:
        {
            "success": true,
            "snapshot_id": "20260130_103045",
            "message": "Snapshot created successfully"
        }

    Note:
        - Snapshots include CSV data and SKU counter
        - Stored in instance/snapshots/ directory
        - Each snapshot is ~100KB to 10MB depending on inventory size
    """
    try:
        from app.services.snapshot_service import snapshot_service  # Deferred: requires app context

        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()

        if not name:
            return jsonify({'success': False, 'error': 'Snapshot name is required'}), 400

        snapshot_id = snapshot_service.create(name, description)

        current_app.logger.info(f"Created snapshot: {snapshot_id}")
        return jsonify({
            'success': True,
            'message': f'Snapshot "{name}" created successfully',
            'snapshot_id': snapshot_id
        })

    except Exception as e:
        current_app.logger.error(f"Error creating snapshot: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/snapshots/list')
@login_required
def list_snapshots() -> Response:
    """List all available inventory snapshots.

    Retrieves metadata for all stored snapshots including name, description,
    creation date, and size.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether listing succeeded
            - snapshots (list): List of snapshot objects with:
                - snapshot_id (str): Unique snapshot ID
                - name (str): Snapshot name
                - description (str): Snapshot description
                - created_at (str): ISO datetime when created
                - created_by (str): User who created it
                - size_bytes (int): Snapshot file size
                - comic_count (int): Number of comics in snapshot
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved snapshot list
        500: Server error occurred

    Example Response:
        {
            "success": true,
            "snapshots": [
                {
                    "snapshot_id": "20260130_103045",
                    "name": "Before bulk delete",
                    "description": "Safety backup",
                    "created_at": "2026-01-30T10:30:45Z",
                    "created_by": "admin",
                    "size_bytes": 524288,
                    "comic_count": 37
                }
            ]
        }
    """
    try:
        from app.services.snapshot_service import snapshot_service  # Deferred: requires app context

        snapshots = snapshot_service.list_all()

        return jsonify({
            'success': True,
            'snapshots': [s.to_dict() for s in snapshots]
        })

    except Exception as e:
        current_app.logger.error(f"Error listing snapshots: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/snapshots/restore/<snapshot_id>', methods=['POST'])
@login_required
@csrf_required
def restore_snapshot(snapshot_id: str) -> Response:
    """Restore inventory from a snapshot.

    Replaces or merges the current inventory with data from a snapshot.
    This operation can be destructive if using "replace" mode.

    Path Parameters:
        snapshot_id (str): ID of snapshot to restore

    Request Body (JSON):
        {
            "mode": str  # "replace" or "merge"
        }

    Modes:
        - "replace": Completely replaces current inventory (destructive)
        - "merge": Adds snapshot comics, keeping existing ones

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether restore succeeded
            - message (str): Confirmation message
            - restored_count (int): Number of comics restored
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully restored snapshot
        400: Invalid request data or snapshot not found
        500: Server error during restore

    Example Request:
        {
            "mode": "replace"
        }

    Example Response:
        {
            "success": true,
            "message": "Snapshot restored successfully",
            "restored_count": 37
        }

    Warning:
        - "replace" mode deletes current inventory
        - Consider creating a new snapshot before restoring
        - SKU counter is also restored from snapshot
    """
    try:
        from app.services.snapshot_service import snapshot_service  # Deferred: requires app context

        data = request.get_json() or {}
        mode = data.get('mode', 'replace')

        snapshot_service.restore(snapshot_id, mode)

        current_app.logger.info(f"Restored snapshot: {snapshot_id} (mode: {mode})")
        return jsonify({
            'success': True,
            'message': f'Snapshot restored successfully'
        })

    except Exception as e:
        current_app.logger.error(f"Error restoring snapshot: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500


@api_bp.route('/snapshots/delete/<snapshot_id>', methods=['DELETE'])
@login_required
@csrf_required
def delete_snapshot(snapshot_id: str) -> Response:
    """Delete a snapshot permanently.

    Removes a snapshot file from storage. This operation cannot be undone.

    Path Parameters:
        snapshot_id (str): ID of snapshot to delete

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether deletion succeeded
            - message (str): Confirmation message
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully deleted snapshot
        404: Snapshot not found
        500: Server error during deletion

    Example Response:
        {
            "success": true,
            "message": "Snapshot deleted successfully"
        }

    Note:
        - This operation is permanent
        - Snapshot files are removed from disk
        - Does not affect current inventory
    """
    try:
        from app.services.snapshot_service import snapshot_service  # Deferred: requires app context

        snapshot_service.delete(snapshot_id)

        current_app.logger.info(f"Deleted snapshot: {snapshot_id}")
        return jsonify({
            'success': True,
            'message': 'Snapshot deleted successfully'
        })

    except Exception as e:
        current_app.logger.error(f"Error deleting snapshot: {e}")
        return jsonify({'success': False, 'error': safe_error_message(e)}), 500
