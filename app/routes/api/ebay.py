"""eBay routes - eBay listing operations and integration.

This module handles:
- Listing comics on eBay
- Updating eBay listings
- Ending eBay listings
- Unlinking from eBay
- Verifying eBay listings
- Updating eBay item IDs
- WhatNot status updates
- Trading API status checks
- OAuth token info
- Marketplace account deletion webhook

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import request, jsonify, current_app, Response
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required
from app.services.comic_service import comic_service
from app.services.ebay_service import ebay_service, EbayDuplicateListingError
from app.utils.ebay_helpers import resolve_ebay_context, validate_ebay_item_id
from app.utils.helpers import is_giveaway
from app.config import get_secret
from datetime import datetime

import hashlib
import time
import os


def _sanitize_error(exc):
    """Return a user-friendly error string, stripping raw eBay API noise.

    The service layer already simplifies Trading API errors, but network
    errors, timeouts, and other unexpected exceptions can still be verbose.
    This is the final safety net before the message reaches the browser.
    """
    msg = str(exc)

    # Connection / network errors
    if 'ConnectionError' in type(exc).__name__ or 'timeout' in msg.lower():
        return 'Could not reach eBay — please check your connection and try again'
    if 'ConnectionRefused' in msg or 'Connection refused' in msg:
        return 'eBay is not responding — please try again later'

    # Already-clean messages from our service layer (RuntimeError, ValueError)
    if isinstance(exc, (RuntimeError, ValueError)):
        # Truncate if somehow still very long
        return msg[:200] if len(msg) > 200 else msg

    # Generic fallback: strip Python exception class name prefix and truncate
    class_name = type(exc).__name__
    if msg.startswith(class_name):
        msg = msg[len(class_name):].lstrip(':').strip()

    if len(msg) > 200:
        msg = msg[:197] + '...'

    return msg or 'An unexpected error occurred'


def _duplicate_error_response(exc: "EbayDuplicateListingError") -> dict:
    """Build a consistent error payload for duplicate-listing conflicts."""
    safe_message = _sanitize_error(exc)
    detail: dict = {
        'error': 'Duplicate listing detected',
        'message': safe_message,
        'is_duplicate': True,
    }
    if exc.existing_item_id:
        detail['existing_item_id'] = exc.existing_item_id
    if getattr(exc, 'existing_title', None):
        detail['existing_title'] = exc.existing_title
    return detail


@api_bp.route('/comic/<sku>/ebay/list', methods=['POST'])
@login_required
@csrf_required
def list_comic_on_ebay(sku: str) -> Response:
    """List comic on eBay marketplace.

    Creates new eBay listing from comic data. Supports immediate listing
    or scheduled future listing. Handles duplicate detection.

    Path Parameters:
        sku (str): Comic SKU to list

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether listing succeeded
            - ebay_item_id (str): eBay Item ID
            - listing_url (str): eBay listing URL
            - message (str): Confirmation message
            - error (str, optional): Error if failed

    Status Codes:
        200: Listed successfully
        400: Invalid comic data
        404: Comic not found
        409: Duplicate listing detected
        500: eBay API error

    Example Response:
        {
            "success": true,
            "ebay_item_id": "123456789012",
            "listing_url": "https://ebay.com/itm/123456789012",
            "message": "Listed successfully"
        }

    Note:
        - Validates all required eBay fields
        - Uploads images to eBay
        - Handles GTC (Good 'Til Cancelled) duration
        - Supports scheduled listings
        - Detects and prevents duplicate listings
        - Updates local inventory with eBay Item ID
    """
    comic = comic_service.get_comic(sku)
    if not comic:
        return jsonify({'success': False, 'error': 'Comic not found'}), 404

    # If the comic is already linked to an eBay item (e.g. imported from a draft),
    # try to end the old item first so the new listing replaces it.
    if comic.ebay_item_id:
        old_item_id = comic.ebay_item_id
        try:
            payload_peek = request.get_json(silent=True) or {}
            env_peek, _, _, _ = resolve_ebay_context(payload_peek)
            ebay_service.end_item_by_id(old_item_id, environment=env_peek)
            current_app.logger.info(
                f"Ended linked eBay item {old_item_id} (draft/unsold) before creating new listing for SKU {sku}"
            )
        except Exception as end_exc:
            current_app.logger.warning(
                f"Could not end linked eBay item {old_item_id} for SKU {sku}: {end_exc}"
            )
        # Clear the old ID so the new listing proceeds
        comic.ebay_item_id = ''
        comic_service.save_comic(comic)
        # Re-fetch comic to get the saved state
        comic = comic_service.get_comic(sku)

    try:
        # Note: request.get_json() is cached by Flask, safe to call multiple times
        payload = request.get_json(silent=True) or {}

        # Read eBay listing settings from the comic object itself
        # (these were saved to CSV from the eBay Settings tab)
        comic_listing_mode = comic.extra_fields.get('eBay Listing Mode', None)
        comic_schedule_date = comic.extra_fields.get('eBay Schedule Date', None)

        # Merge comic settings into payload (comic settings take precedence)
        if comic_listing_mode:
            payload['mode'] = comic_listing_mode
        if comic_schedule_date:
            payload['schedule_time'] = comic_schedule_date

        environment, listing_mode, overrides, schedule_time = resolve_ebay_context(payload)
        item_id = ebay_service.list_comic(
            comic,
            environment=environment,
            mode=listing_mode,
            overrides=overrides,
            schedule_time=schedule_time
        )
        if not item_id:
            raise RuntimeError('eBay did not return an ItemID')
        comic.ebay_item_id = item_id
        comic_service.save_comic(comic)
        return jsonify({'success': True, 'item_id': item_id, 'environment': environment, 'mode': listing_mode})
    except EbayDuplicateListingError as exc:
        current_app.logger.warning(f"Duplicate listing detected for SKU {sku}: {exc}")
        return jsonify({'success': False, **_duplicate_error_response(exc)}), 409
    except Exception as exc:
        current_app.logger.error(f"Failed to list {sku} on eBay: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/ebay/update', methods=['POST'])
@login_required
@csrf_required
def update_comic_on_ebay(sku: str) -> Response:
    """Update existing eBay listing.

    Updates eBay listing with new data. Limited fields can be changed
    after listing is active.

    Path Parameters:
        sku (str): Comic SKU of listing to update

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether update succeeded
            - message (str): Confirmation message

    Status Codes:
        200: Updated successfully
        400: Invalid update or comic not listed
        404: Comic or eBay listing not found
        500: eBay API error

    Note:
        - Price, quantity, description can be updated
        - Title and category cannot be changed
        - Images cannot be modified (end and relist instead)
        - Updates eBay listings cache
    """
    comic = comic_service.get_comic(sku)
    if not comic:
        return jsonify({'success': False, 'error': 'Comic not found'}), 404
    if not comic.ebay_item_id:
        return jsonify({'success': False, 'error': 'Comic is not listed on eBay'}), 400
    try:
        payload = request.get_json(silent=True) or {}

        # Mirror list_comic_on_ebay: read the comic's saved eBay listing mode
        # and schedule date from the CSV so an "Update" action pushes ALL of the
        # listing's data to eBay — including the scheduled go-live date — not
        # just price/description/images. The request payload still wins if the
        # caller explicitly supplies `mode` or `schedule_time` (e.g. the
        # Reschedule-only button).
        comic_listing_mode = comic.extra_fields.get('eBay Listing Mode', None)
        comic_schedule_date = comic.extra_fields.get('eBay Schedule Date', None)

        # Normalize the frontend's generic "update" mode — the eBay payload
        # builder only understands 'list' / 'future' / 'schedule'. For a plain
        # update, fall through to whatever the comic has saved.
        incoming_mode = payload.get('mode')
        if incoming_mode in (None, '', 'update'):
            payload.pop('mode', None)
            if comic_listing_mode:
                payload['mode'] = comic_listing_mode

        if 'schedule_time' not in payload or not payload.get('schedule_time'):
            if comic_schedule_date:
                payload['schedule_time'] = comic_schedule_date

        environment, listing_mode, overrides, schedule_time = resolve_ebay_context(payload)
        current_app.logger.info(
            f"[update_comic_on_ebay] SKU {sku}: mode={listing_mode}, "
            f"schedule_time={schedule_time or '(none)'}"
        )

        item_id = ebay_service.update_listing(
            comic,
            environment=environment,
            overrides=overrides,
            mode=listing_mode,
            schedule_time=schedule_time
        )
        comic.ebay_item_id = item_id or comic.ebay_item_id
        comic_service.save_comic(comic)
        return jsonify({
            'success': True,
            'item_id': comic.ebay_item_id,
            'environment': environment,
            'mode': listing_mode,
            'schedule_time': schedule_time
        })
    except EbayDuplicateListingError as exc:
        # Handle duplicate listing error with user-friendly message
        current_app.logger.warning(f"Duplicate listing detected while updating SKU {sku}: {exc}")
        return jsonify({'success': False, **_duplicate_error_response(exc)}), 409
    except Exception as exc:
        current_app.logger.error(f"Failed to update eBay listing for {sku}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/ebay/end', methods=['POST'])
@login_required
@csrf_required
def end_comic_on_ebay(sku: str) -> Response:
    """End eBay listing early.

    Terminates active eBay listing before natural expiration.

    Path Parameters:
        sku (str): Comic SKU of listing to end

    Request Body (JSON):
        {
            "reason": str  # End reason (e.g., "NotAvailable", "LostOrBroken")
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether listing ended
            - message (str): Confirmation message

    Status Codes:
        200: Listing ended successfully
        400: Comic not listed or invalid reason
        404: Comic or eBay listing not found
        500: eBay API error

    Valid Reasons:
        - NotAvailable
        - LostOrBroken
        - Incorrect
        - OtherListingError

    Note:
        - Listing removed from eBay immediately
        - Local inventory retains eBay Item ID
        - Use unlink to remove eBay Item ID
    """
    comic = comic_service.get_comic(sku)
    if not comic:
        return jsonify({'success': False, 'error': 'Comic not found'}), 404
    if not comic.ebay_item_id:
        return jsonify({'success': False, 'error': 'Comic is not listed on eBay'}), 400
    data = request.get_json(silent=True) or {}
    reason = data.get('reason', 'NotAvailable')
    try:
        environment, _, _, _ = resolve_ebay_context(data)
        ebay_service.end_listing(comic, reason=reason, environment=environment)
        comic.ebay_item_id = ''
        comic_service.save_comic(comic)
        return jsonify({'success': True, 'environment': environment, 'mode': 'end'})
    except Exception as exc:
        current_app.logger.error(f"Failed to end eBay listing for {sku}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/ebay/relist', methods=['POST'])
@login_required
@csrf_required
def relist_comic_on_ebay(sku: str) -> Response:
    """Relist a comic on eBay with the app's generated description.

    Ends any existing listing (active or draft), then creates a fresh listing
    using the comic's current data. The description is regenerated from the
    template, preventing stale or duplicate content.

    Path Parameters:
        sku (str): Comic SKU to relist

    Request Body (JSON):
        {
            "delete_draft_id": str  # Optional: eBay Item ID of a draft to delete
        }

    Returns:
        Response: JSON with new eBay Item ID

    Status Codes:
        200: Relisted successfully
        404: Comic not found
        500: eBay API error
    """
    comic = comic_service.get_comic(sku)
    if not comic:
        return jsonify({'success': False, 'error': 'Comic not found'}), 404

    try:
        payload = request.get_json(silent=True) or {}
        environment, listing_mode, overrides, schedule_time = resolve_ebay_context(payload)

        # If a draft ID is provided, delete it first
        delete_draft_id = payload.get('delete_draft_id')
        if delete_draft_id:
            try:
                ebay_service.end_item_by_id(delete_draft_id, reason='NotAvailable', environment=environment)
                current_app.logger.info(f"Deleted eBay draft {delete_draft_id} before relist")
            except Exception as e:
                current_app.logger.warning(f"Could not delete draft {delete_draft_id}: {e}")

        new_item_id = ebay_service.relist_item(
            comic,
            environment=environment,
            overrides=overrides,
            mode=listing_mode,
            schedule_time=schedule_time
        )

        if not new_item_id:
            raise RuntimeError('eBay did not return an ItemID')

        comic.ebay_item_id = new_item_id
        comic_service.save_comic(comic)

        # Clear listings cache so fresh data is fetched
        cache_key = f'ebay_listings_{environment}'
        if hasattr(current_app, 'ebay_cache') and cache_key in current_app.ebay_cache:
            del current_app.ebay_cache[cache_key]

        return jsonify({
            'success': True,
            'item_id': new_item_id,
            'environment': environment,
            'mode': listing_mode,
            'message': 'Relisted successfully with updated description'
        })
    except EbayDuplicateListingError as exc:
        current_app.logger.warning(f"Duplicate listing detected while relisting SKU {sku}: {exc}")
        return jsonify({'success': False, **_duplicate_error_response(exc)}), 409
    except Exception as exc:
        current_app.logger.error(f"Failed to relist {sku} on eBay: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/ebay/item/<item_id>/end', methods=['POST'])
@login_required
@csrf_required
def end_ebay_item_by_id(item_id: str) -> Response:
    """End/delete an eBay listing by item ID (no local comic required).

    Useful for deleting drafts or ending orphaned listings that aren't
    linked to a local inventory item.

    Path Parameters:
        item_id (str): eBay Item ID to end

    Request Body (JSON):
        {
            "reason": str  # Optional end reason (default: NotAvailable)
        }

    Status Codes:
        200: Listing ended
        500: eBay API error
    """
    try:
        payload = request.get_json(silent=True) or {}
        reason = payload.get('reason', 'NotAvailable')
        environment, _, _, _ = resolve_ebay_context(payload)

        ebay_service.end_item_by_id(item_id, reason=reason, environment=environment)

        # Clear listings cache
        cache_key = f'ebay_listings_{environment}'
        if hasattr(current_app, 'ebay_cache') and cache_key in current_app.ebay_cache:
            del current_app.ebay_cache[cache_key]

        return jsonify({'success': True, 'item_id': item_id, 'message': 'Listing ended'})
    except Exception as exc:
        current_app.logger.error(f"Failed to end eBay item {item_id}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/ebay/item/<item_id>/details', methods=['GET'])
@login_required
def get_ebay_item_full_details(item_id: str) -> Response:
    """Get full item details from eBay for the clone / import flow.

    Returns comprehensive metadata including title, description, item
    specifics, category, condition, and picture URLs — everything needed
    to populate the add-comic form from an existing eBay listing.

    Path Parameters:
        item_id (str): eBay Item ID

    Status Codes:
        200: Details retrieved
        404: Item not found
        500: eBay API error
    """
    try:
        environment = request.args.get('environment', 'production')
        details = ebay_service.get_item_details(item_id, environment=environment)

        if not details:
            return jsonify({'success': False, 'error': 'Item not found on eBay'}), 404

        return jsonify({'success': True, **details})

    except Exception as exc:
        current_app.logger.error(f"Failed to get eBay item details for {item_id}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/ebay/unlink', methods=['POST'])
@login_required
@csrf_required
def unlink_comic_from_ebay(sku: str) -> Response:
    """Unlink comic from eBay (local only).

    Removes eBay Item ID from local inventory without affecting eBay listing.
    Used when listing was deleted externally or to break connection.

    Path Parameters:
        sku (str): Comic SKU to unlink

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether unlink succeeded
            - message (str): Confirmation message

    Status Codes:
        200: Unlinked successfully
        400: Comic not linked
        404: Comic not found
        500: Server error

    Note:
        - Does NOT affect eBay listing
        - Only removes local eBay Item ID
        - Use end_comic_on_ebay to end listing first
        - Updates eBay listings cache
    """
    comic = comic_service.get_comic(sku)
    if not comic:
        return jsonify({'success': False, 'error': 'Comic not found'}), 404
    if not comic.ebay_item_id:
        return jsonify({'success': False, 'error': 'Comic is not linked to eBay'}), 400
    try:
        # Store the old item ID for logging
        old_item_id = comic.ebay_item_id

        # Clear the eBay Item ID
        comic.ebay_item_id = ''
        comic_service.save_comic(comic)

        current_app.logger.info(f"Unlinked {sku} from eBay (removed Item ID: {old_item_id})")
        return jsonify({'success': True, 'sku': sku, 'old_item_id': old_item_id})
    except Exception as exc:
        current_app.logger.error(f"Failed to unlink {sku} from eBay: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/ebay/verify', methods=['GET'])
@login_required
def verify_comic_on_ebay(sku: str) -> Response:
    """Verify eBay listing status.

    Checks if comic's eBay listing still exists and is active.

    Path Parameters:
        sku (str): Comic SKU to verify

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether verification succeeded
            - exists (bool): If listing exists on eBay
            - active (bool): If listing is active
            - status (str): Listing status
            - error (str, optional): Error if failed

    Status Codes:
        200: Verification complete
        400: Comic not linked
        404: Comic not found
        500: eBay API error

    Example Response:
        {
            "success": true,
            "exists": true,
            "active": true,
            "status": "Active"
        }
    """
    comic = comic_service.get_comic(sku)
    if not comic:
        return jsonify({'success': False, 'error': 'Comic not found'}), 404

    if not comic.ebay_item_id:
        return jsonify({
            'success': True,
            'is_listed': False,
            'status': 'no_item_id',
            'message': 'No eBay Item ID stored'
        })

    try:
        # Get environment from query params
        environment = request.args.get('environment', 'production')

        # Verify the item exists on eBay
        item_info = ebay_service.get_item(comic.ebay_item_id, environment=environment)

        if item_info:
            listing_status = item_info.get('ListingStatus', 'Unknown')

            # Check if listing is actually active
            # Active statuses: 'Active', 'Scheduled' (future start)
            # Inactive statuses: 'Completed', 'Ended', 'Canceled'
            if listing_status in ['Active', 'Scheduled']:
                return jsonify({
                    'success': True,
                    'is_listed': True,
                    'status': 'active',
                    'item_id': comic.ebay_item_id,
                    'title': item_info.get('Title'),
                    'listing_status': listing_status,
                    'quantity_available': item_info.get('Quantity'),
                    'environment': environment
                })
            else:
                # Listing exists but is not active (Completed, Ended, etc.)
                current_app.logger.info(f"eBay item {comic.ebay_item_id} has status '{listing_status}' - treating as not listed")
                return jsonify({
                    'success': True,
                    'is_listed': False,
                    'status': 'not_found',
                    'item_id': comic.ebay_item_id,
                    'message': f'Listing has ended (status: {listing_status})',
                    'listing_status': listing_status,
                    'suggest_clear': True
                })
        else:
            # Item not found on eBay - should we clear the ID?
            return jsonify({
                'success': True,
                'is_listed': False,
                'status': 'not_found',
                'item_id': comic.ebay_item_id,
                'message': 'Item ID exists in CSV but not found on eBay',
                'suggest_clear': True
            })

    except Exception as exc:
        current_app.logger.error(f"Failed to verify eBay listing for {sku}: {exc}")
        # If verification fails, we don't know the status
        return jsonify({
            'success': False,
            'error': _sanitize_error(exc),
            'item_id': comic.ebay_item_id,
            'status': 'unknown'
        }), 500


@api_bp.route('/comic/<sku>/ebay/item-id', methods=['POST'])
@login_required
@csrf_required
def update_comic_ebay_item_id(sku: str) -> Response:
    """Manually set eBay Item ID for comic.

    Links comic to existing eBay listing by Item ID. Used for manual linking.

    Path Parameters:
        sku (str): Comic SKU to link

    Request Body (JSON):
        {
            "ebay_item_id": str  # eBay Item ID (12 digits)
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether link succeeded
            - message (str): Confirmation message

    Status Codes:
        200: Linked successfully
        400: Invalid Item ID format
        404: Comic not found
        500: Server error

    Note:
        - Does not validate Item ID exists on eBay
        - Updates eBay listings cache
        - Used for manual repair/linking
    """
    try:
        data = request.get_json() or {}
        # Accept both 'ebay_item_id' (new) and 'item_id' (legacy) for backward compatibility
        item_id = (data.get('ebay_item_id') or data.get('item_id') or '').strip()
        comic = comic_service.get_comic(sku)
        if not comic:
            return jsonify({'success': False, 'error': 'Comic not found'}), 404

        # If item_id is empty, we're unlinking - allow it
        if item_id:
            # Prevent linking giveaway items to eBay
            if is_giveaway(comic.title, comic.listing_type):
                return jsonify({'success': False, 'error': 'Cannot link giveaway items to eBay. Please remove the "G-" or "G " prefix from the title if this should be a for-sale item.'}), 400

            # Only validate if we're setting a value (not unlinking)
            is_valid, error_msg = validate_ebay_item_id(item_id)
            if not is_valid:
                return jsonify({'success': False, 'error': error_msg}), 400

        # Set or clear the eBay item ID
        comic.ebay_item_id = item_id
        comic_service.save_comic(comic)
        return jsonify({'success': True, 'item_id': item_id})
    except Exception as exc:
        current_app.logger.error(f"Failed to update eBay ItemID for {sku}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/whatnot/status', methods=['POST'])
@login_required
@csrf_required
def update_comic_whatnot_status(sku: str) -> Response:
    """Toggle WhatNot listing status.

    Marks comic as listed/not listed on WhatNot platform.

    Path Parameters:
        sku (str): Comic SKU

    Request Body (JSON):
        {
            "whatnot_listed": bool  # True if listed on WhatNot
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether update succeeded
            - message (str): Confirmation message

    Status Codes:
        200: Status updated
        404: Comic not found
        500: Server error

    Note:
        - Simple boolean toggle
        - Backs up CSV to S3
    """
    try:
        data = request.get_json() or {}
        is_listed = data.get('is_listed', False)

        comic = comic_service.get_comic(sku)
        if not comic:
            return jsonify({'success': False, 'error': 'Comic not found'}), 404


        # Set to "TRUE" or "FALSE"
        comic.whatnot_item_id = 'TRUE' if is_listed else 'FALSE'
        comic_service.save_comic(comic)

        return jsonify({
            'success': True,
            'whatnot_item_id': comic.whatnot_item_id,
            'is_listed': (comic.whatnot_item_id == 'TRUE')
        })
    except Exception as exc:
        current_app.logger.error(f"Failed to update WhatNot status for {sku}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/comic/<sku>/giveaway/status', methods=['POST'])
@login_required
@csrf_required
def update_comic_giveaway_status(sku: str) -> Response:
    """Toggle WhatNot Giveaway status for a comic.

    Sets or clears the Giveaway listing type.  When added to a giveaway the
    ``listing_type`` is set to ``'Giveaway'`` and ``whatnot_item_id`` to
    ``'TRUE'``.  When removed the item reverts to ``'For Sale'`` and
    ``whatnot_item_id`` is cleared.

    Path Parameters:
        sku (str): Comic SKU

    Request Body (JSON):
        {
            "is_giveaway": bool  # True to add to giveaway, False to remove
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether update succeeded
            - listing_type (str): Updated listing_type value
            - is_giveaway (bool): Current giveaway state

    Status Codes:
        200: Status updated
        404: Comic not found
        500: Server error
    """
    try:
        data = request.get_json() or {}
        is_giveaway_flag = bool(data.get('is_giveaway', False))

        comic = comic_service.get_comic(sku)
        if not comic:
            return jsonify({'success': False, 'error': 'Comic not found'}), 404

        if is_giveaway_flag:
            comic.listing_type = 'Giveaway'
            comic.whatnot_item_id = 'TRUE'
        else:
            comic.listing_type = 'For Sale'
            comic.whatnot_item_id = 'FALSE'

        comic_service.save_comic(comic)

        return jsonify({
            'success': True,
            'listing_type': comic.listing_type,
            'is_giveaway': is_giveaway_flag,
        })
    except Exception as exc:
        current_app.logger.error(f"Failed to update giveaway status for {sku}: {exc}")
        return jsonify({'success': False, 'error': _sanitize_error(exc)}), 500


@api_bp.route('/ebay/trading-api-status', methods=['GET'])
@login_required
def ebay_trading_api_status() -> Response:
    """Check eBay Trading API credentials status.

    Verifies Trading API credentials are configured and valid.

    Returns:
        Response: Flask JSON response containing:
            - configured (bool): If credentials exist
            - valid (bool, optional): If credentials work
            - error (str, optional): Error message

    Status Codes:
        200: Status retrieved
        500: Check failed

    Example Response:
        {
            "configured": true,
            "valid": true
        }
    """
    try:
        # Check if user token is set
        if ebay_service.environment == 'sandbox':
            token = os.getenv('EBAY_SANDBOX_TOKEN') or current_app.config.get('EBAY_SANDBOX_TOKEN')
            dev_id = os.getenv('EBAY_SANDBOX_DEV_ID') or current_app.config.get('EBAY_SANDBOX_DEV_ID')
            app_id = os.getenv('EBAY_SANDBOX_APP_ID') or current_app.config.get('EBAY_SANDBOX_APP_ID')
            cert_id = os.getenv('EBAY_SANDBOX_CERT_ID') or current_app.config.get('EBAY_SANDBOX_CERT_ID')
        else:
            token = os.getenv('EBAY_PRODUCTION_TOKEN') or current_app.config.get('EBAY_PRODUCTION_TOKEN')
            dev_id = os.getenv('EBAY_PRODUCTION_DEV_ID') or current_app.config.get('EBAY_PRODUCTION_DEV_ID')
            app_id = os.getenv('EBAY_PRODUCTION_APP_ID') or current_app.config.get('EBAY_PRODUCTION_APP_ID')
            cert_id = os.getenv('EBAY_PRODUCTION_CERT_ID') or current_app.config.get('EBAY_PRODUCTION_CERT_ID')

        # Check what's available
        has_token = bool(token)
        has_dev_id = bool(dev_id)
        has_app_id = bool(app_id)
        has_cert_id = bool(cert_id)

        # Trading API only needs these three
        trading_api_ready = has_token and has_dev_id and has_cert_id and has_app_id

        status = {
            'success': True,
            'environment': ebay_service.environment,
            'trading_api_ready': trading_api_ready,
            'credentials': {
                'user_token': 'SET ({}...)'.format(token[:15]) if has_token else 'MISSING',
                'dev_id': 'SET ({})'.format(dev_id) if has_dev_id else 'MISSING',
                'app_id': 'SET ({})'.format(app_id[:25] + '...' if len(app_id) > 25 else app_id) if has_app_id else 'MISSING',
                'cert_id': 'SET ({})'.format(cert_id[:15] + '...') if has_cert_id else 'MISSING'
            }
        }

        if not trading_api_ready:
            missing = []
            if not has_token:
                missing.append('EBAY_{}_TOKEN'.format(ebay_service.environment.upper()))
            if not has_dev_id:
                missing.append('EBAY_{}_DEV_ID'.format(ebay_service.environment.upper()))
            if not has_app_id:
                missing.append('EBAY_{}_APP_ID'.format(ebay_service.environment.upper()))
            if not has_cert_id:
                missing.append('EBAY_{}_CERT_ID'.format(ebay_service.environment.upper()))
            status['missing_credentials'] = missing
            status['message'] = 'Trading API cannot authenticate - missing credentials'
        else:
            status['message'] = 'Trading API credentials are configured'

        return jsonify(status)

    except Exception as e:
        current_app.logger.error(f"Error checking Trading API status: {e}")
        return jsonify({'success': False, 'error': _sanitize_error(e)}), 500


@api_bp.route('/ebay/token-info', methods=['GET'])
@login_required
def ebay_token_info() -> Response:
    """Get eBay OAuth token information.

    Returns current OAuth token status and expiration.

    Returns:
        Response: Flask JSON response containing:
            - has_token (bool): If token exists
            - expires_at (str, optional): Expiration datetime
            - expired (bool): If token expired
            - error (str, optional): Error message

    Status Codes:
        200: Token info retrieved
        500: Error getting info

    Example Response:
        {
            "has_token": true,
            "expires_at": "2026-02-28T10:30:00Z",
            "expired": false
        }
    """
    try:

        # Check which credentials are available
        environment = ebay_service.environment
        app_id = ebay_service._get_app_id()
        cert_id = ebay_service._get_cert_id()

        # Determine which env vars to check based on environment
        if environment == 'sandbox':
            app_id_var = 'EBAY_SANDBOX_APP_ID'
            cert_id_var = 'EBAY_SANDBOX_CERT_ID'
        else:
            app_id_var = 'EBAY_PRODUCTION_APP_ID'
            cert_id_var = 'EBAY_PRODUCTION_CERT_ID'

        # Check if credentials are missing
        missing_creds = []
        if not app_id:
            missing_creds.append(app_id_var)
        if not cert_id:
            missing_creds.append(cert_id_var)

        if missing_creds:
            return jsonify({
                'success': False,
                'error': f'Missing eBay credentials for {environment}: {", ".join(missing_creds)}',
                'environment': environment,
                'app_id': app_id,
                'oauth_url': ebay_service.oauth_url,
                'missing_variables': missing_creds,
                'help': f'Please set these environment variables in your .env file or system environment.'
            })

        # Get current token (will generate if needed)
        token = ebay_service._get_oauth_token()

        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to obtain OAuth token. Credentials may be invalid.',
                'environment': environment,
                'app_id': app_id[:20] + '...' if app_id and len(app_id) > 20 else app_id,
                'oauth_url': ebay_service.oauth_url,
                'help': 'Check that your App ID and Cert ID are correct for the selected environment.'
            })

        # Calculate expiration info
        expires_timestamp = ebay_service.token_expires
        now = time.time()
        seconds_until_expiry = int(expires_timestamp - now)
        expires_at = datetime.fromtimestamp(expires_timestamp).strftime('%Y-%m-%d %H:%M:%S')

        return jsonify({
            'success': True,
            'token_preview': token[:20] + '...' + token[-20:] if len(token) > 40 else token,  # Truncate for security
            'expires_at': expires_at,
            'seconds_until_expiry': seconds_until_expiry,
            'environment': ebay_service.environment,
            'app_id': app_id[:20] + '...' if app_id and len(app_id) > 20 else app_id,
            'oauth_url': ebay_service.oauth_url
        })

    except Exception as e:
        current_app.logger.error(f"Error getting eBay token info: {e}")
        return jsonify({'success': False, 'error': _sanitize_error(e)}), 500


@api_bp.route('/ebay/marketplace-account-deletion', methods=['POST', 'GET'])
def ebay_marketplace_deletion() -> Response:
    """Handle eBay marketplace account deletion webhook.

    Receives and processes eBay's marketplace account deletion notifications
    as required by eBay's API compliance.

    Request Body (JSON):
        eBay deletion notification payload

    Returns:
        Response: Plain text "OK" response

    Status Codes:
        200: Notification received

    Note:
        - Required by eBay API compliance
        - No authentication required (webhook)
        - Logs notification for compliance
        - Does not delete local data
    """
    # Required by eBay for app activation.
    # This endpoint receives notifications when eBay users delete their accounts.
    if request.method == 'GET':
        # eBay verification challenge
        challenge_code = request.args.get('challenge_code')
        if challenge_code:
            # According to eBay docs, the response should be:
            # hash = SHA256(challengeCode + verificationToken + endpointUrl)
            verification_token = get_secret('EBAY_VERIFICATION_TOKEN', 'your-verification-token-here')
            endpoint_url = request.base_url

            combined_string = f"{challenge_code}{verification_token}{endpoint_url}"
            challenge_response = hashlib.sha256(combined_string.encode()).hexdigest()

            response_data = {
                'challengeResponse': challenge_response
            }
            current_app.logger.info(f"eBay verification challenge responded: {challenge_code}")
            return jsonify(response_data), 200

        return jsonify({'status': 'eBay Marketplace Account Deletion endpoint active'}), 200

    elif request.method == 'POST':
        # Handle deletion notification
        try:
            notification = request.get_json()

            # Only log username for brevity (eBay sends test notifications frequently)
            username = notification.get('notification', {}).get('data', {}).get('username', 'unknown')
            # In a production app, you would:
            # 1. Verify the notification signature
            # 2. Delete user data from your database
            # 3. Log the deletion for compliance

            # For this app, we just acknowledge it since we don't store eBay user data
            return jsonify({'status': 'accepted'}), 200

        except Exception as e:
            current_app.logger.error(f"Error processing eBay deletion notification: {e}")
            return jsonify({'error': 'Internal server error'}), 500
