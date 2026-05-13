"""Comics routes - Main comic CRUD operations and management.

This module handles:
- Listing/searching/filtering comics with pagination
- Adding new comics with image upload
- Getting single comics by SKU
- Updating comics with image management
- Deleting comics (single and bulk operations)
- Quick title/price updates
- Bulk update operations
- CSV export for selected comics
- Comics available for eBay linking

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import request, jsonify, current_app, send_file, Response
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required, sync_not_locked, disk_space_required
from app.services.comic_service import comic_service
from app.services.ebay_service import ebay_service
from app.utils.defaults_helpers import apply_defaults_to_comic_data
from app.utils.logging_utils import safe_error_message
from app.utils.csv_sanitizer import sanitize_row
from app.utils.upload_security import validate_uploaded_image, UploadValidationError
from app.utils.helpers import is_giveaway
from app.utils.whatnot_validators import (
    WHATNOT_FIELD_NAMES,
    METADATA_FIELD_NAMES,
    build_whatnot_export_row,
    get_whatnot_export_fieldnames,
    is_whatnot_listed,
)
from io import StringIO, BytesIO
import csv
import re
import time
import math


def _get_active_platforms(comic) -> list[str]:
    """Return platform names the comic is currently listed on.

    Checks eBay (non-empty ``ebay_item_id``) and WhatNot (``whatnot_item_id``
    equals ``'TRUE'``).  Returns an empty list when the item is not actively
    listed on any external platform.

    Args:
        comic: A ``Comic`` instance returned by ``comic_service.get_comic``.

    Returns:
        list[str]: Platform names, e.g. ``['eBay', 'WhatNot']``.
    """
    platforms: list[str] = []
    if getattr(comic, 'ebay_item_id', '').strip():
        platforms.append('eBay')
    if str(getattr(comic, 'whatnot_item_id', '') or '').strip().upper() == 'TRUE':
        platforms.append('WhatNot')
    return platforms


def _normalize_giveaway_fields(comic_data: dict) -> None:
    """Persist canonical giveaway / WhatNot flags in ``comic_data``.

    The add/edit form currently drives giveaway selection via ``Type``. This
    helper derives the canonical fields the rest of the app expects:

    - ``Listing Type`` becomes ``'Giveaway'`` (or ``'For Sale'`` otherwise)
    - giveaway items are automatically tagged as listed on WhatNot by setting
      ``WhatNot Item ID`` to ``'TRUE'``

    The helper mutates ``comic_data`` in place.
    """
    type_value = str(
        comic_data.get(WHATNOT_FIELD_NAMES['TYPE'])
        or comic_data.get('type')
        or comic_data.get('Type')
        or ''
    ).strip()

    if not type_value:
        return

    comic_data[WHATNOT_FIELD_NAMES['LISTING_TYPE']] = (
        'Giveaway' if type_value == 'Giveaway' else 'For Sale'
    )

    if type_value == 'Giveaway':
        comic_data[METADATA_FIELD_NAMES['WHATNOT_ITEM_ID']] = 'TRUE'


@api_bp.route('/comics', methods=['GET'])
@login_required
def get_comics() -> Response:
    """List, search, and filter comics with pagination.

    Retrieves comics from inventory with support for searching, filtering by
    listing type, sorting, and pagination. Main endpoint for browse page.

    Query Parameters:
        page (int, optional): Page number (default: 1)
        per_page (int, optional): Items per page (max 100, default: 50)
        search (str, optional): Search term (searches SKU, Title, Description)
        listing_type (str, optional): Filter by type ("Not Listed", "For Sale eBay", "WhatNot", "Giveaway")
        sort_by (str, optional): Sort order ("sku_asc" or "sku_desc")
        not_listed_subfilter (str, optional): When listing_type is "Not Listed":
            - "both" (default): Items not on both eBay and WhatNot
            - "ebay": Items missing from eBay only
            - "whatnot": Items missing from WhatNot only

    Returns:
        Response: Flask JSON response containing:
            - comics (list): List of comic objects
            - total (int): Total matching comics
            - page (int): Current page number
            - per_page (int): Items per page
            - total_pages (int): Total pages available

    Status Codes:
        200: Successfully retrieved comics
        500: Server error

    Example Request:
        GET /comics?page=1&per_page=24&search=spider&listing_type=Not%20Listed&not_listed_subfilter=both&sort_by=sku_asc

    Example Response:
        {
            "comics": [{...}, {...}],
            "total": 156,
            "page": 1,
            "per_page": 24,
            "total_pages": 7
        }

    Note:
        - Search is case-insensitive
        - Pagination starts at page 1
        - Maximum 100 items per page
        - Results sorted by SKU by default
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', current_app.config.get('COMICS_PER_PAGE', 20), type=int)
        search = request.args.get('search', '', type=str).strip()
        listing_type = request.args.get('listing_type', '', type=str).strip()
        sort_by = request.args.get('sort_by', 'sku_asc', type=str).strip()
        not_listed_subfilter = request.args.get('not_listed_subfilter', 'both', type=str).strip()

        # Enforce pagination limits
        max_per_page = current_app.config.get('MAX_PER_PAGE', 100)
        if per_page > max_per_page:
            per_page = max_per_page
        if per_page < 1:
            per_page = 20
        if page < 1:
            page = 1

        # Validate sort_by
        valid_sorts = {'sku_asc', 'sku_desc', 'title_asc', 'title_desc', 'price_asc', 'price_desc'}
        if sort_by not in valid_sorts:
            sort_by = 'sku_asc'

        # Validate not_listed_subfilter
        if not_listed_subfilter not in ['both', 'ebay', 'whatnot']:
            not_listed_subfilter = 'both'

        # Use unified service method for filtering, stats, and pagination
        result = comic_service.get_comics_paginated(
            page=page,
            per_page=per_page,
            search_term=search,
            listing_type=listing_type,
            sort_by=sort_by,
            not_listed_subfilter=not_listed_subfilter
        )

        response = jsonify({
            'success': True,
            'comics': [comic.to_dict() for comic in result['comics']],
            'pagination': result['pagination']
        })
        # Prevent browser caching to ensure fresh data
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        current_app.logger.error(f"Error getting comics: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while retrieving comics'}), 500


@api_bp.route('/comic', methods=['POST'])
@login_required
@csrf_required
@sync_not_locked
@disk_space_required(min_percent=15)
def add_comic() -> Response:
    """Add a new comic with images to inventory.

    Creates a new comic entry with uploaded images. Supports image duplication
    from existing comics and applies user defaults. Maximum 8 images per comic.

    Form Data (multipart/form-data):
        SKU (str): Comic SKU (must be unique)
        Title (str): Comic title
        Description (str): Description text
        Condition (str): Condition (NM, VF, etc.)
        Price (float): Sale price
        Quantity (int): Available quantity
        images (files): Up to 8 image files (PNG, JPG, JPEG, GIF, WEBP)
        source_sku (str, optional): SKU to duplicate images from
        duplicate_image_urls (list, optional): URLs of images to copy
        ebayListingMode (str, optional): eBay listing mode (list/future)
        ebayScheduleDate (str, optional): Schedule date for future listings
        ebayAllowOffers (bool, optional): Allow best offers
        ebayOfferMin (float, optional): Minimum offer amount
        ebayOfferMax (float, optional): Maximum auto-accept offer

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether comic was added
            - message (str): Confirmation message
            - comic (dict): Created comic data
            - error (str, optional): Error message if failed

    Status Codes:
        200: Comic added successfully
        400: Validation error (duplicate SKU, invalid files, size limit)
        403: Disk space too low (< 15%)
        409: Sync operation in progress
        500: Server error during creation

    Example Form Data:
        SKU: "1051"
        Title: "Amazing Spider-Man #300"
        Price: "45.99"
        Condition: "NM"
        images: [file1.jpg, file2.jpg]

    Example Response:
        {
            "success": true,
            "message": "Comic added successfully",
            "comic": {...}
        }

    Note:
        - Maximum 8 images, 10MB each
        - Images uploaded to S3
        - Thumbnails auto-generated
        - User defaults applied automatically
        - Prevents duplicate SKUs
        - Requires 15% free disk space
        - eBay field names converted from camelCase
    """
    try:
        data = request.form.to_dict()
        files = request.files.getlist('images')

        # DEBUG: Log what's being received
        current_app.logger.debug(f"[add_comic] ========== NEW COMIC ==========")
        current_app.logger.debug(f"[add_comic] Form keys: {list(data.keys())}")
        if 'ebayListingMode' in data:
            current_app.logger.debug(f"[add_comic] ebayListingMode = '{data['ebayListingMode']}'")
        else:
            current_app.logger.debug(f"[add_comic] ebayListingMode NOT in form")


        # Check for duplicate SKU - prevent accidental duplicates
        if 'SKU' in data and data['SKU']:
            existing_comic = comic_service.get_comic(data['SKU'])
            if existing_comic:
                return jsonify({
                    'success': False,
                    'message': f'SKU {data["SKU"]} already exists. Use edit mode to update existing comics.'
                }), 400

        # Validate file uploads
        max_files = 8
        allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
        max_file_size = 10 * 1024 * 1024  # 10MB per file

        if len(files) > max_files:
            return jsonify({'success': False, 'message': f'Maximum {max_files} images allowed'}), 400

        for file in files:
            if file and file.filename:
                try:
                    validate_uploaded_image(
                        file,
                        allowed_extensions=allowed_extensions,
                        max_bytes=max_file_size,
                    )
                except UploadValidationError as exc:
                    return jsonify({'success': False, 'message': str(exc)}), exc.status_code

        # Handle image duplication if this is a duplicate request
        images_to_duplicate = request.form.getlist('duplicate_image_urls')

        # Convert camelCase eBay field names to proper CSV column names
        if 'ebayListingMode' in data:
            ebay_mode_value = data.pop('ebayListingMode')
            data['eBay Listing Mode'] = ebay_mode_value

        if 'ebayScheduleDate' in data:
            data['eBay Schedule Date'] = data.pop('ebayScheduleDate')

        # Convert eBay offer fields from camelCase to proper names
        if 'ebayAllowOffers' in data:
            data['eBay Allow Offers'] = data.pop('ebayAllowOffers')

        if 'ebayOfferMin' in data:
            data['eBay Offer Min'] = data.pop('ebayOfferMin')

        if 'ebayOfferMax' in data:
            data['eBay Offer Max'] = data.pop('ebayOfferMax')

        # Remove any other camelCase fields that shouldn't be in CSV
        camel_case_fields_to_remove = ['ebayAction', 'ebayCondition', 'ebayCategory',
                                       'ebayShippingProfile', 'ebayBestOfferAutoAccept',
                                       'ebayMinBestOffer', 'ebayBestOfferEnabled']
        for field in camel_case_fields_to_remove:
            data.pop(field, None)

        # Apply admin defaults to ensure all required fields have values
        data = apply_defaults_to_comic_data(data, is_new_comic=True)

        # Persist canonical giveaway / WhatNot flags based on the selected Type.
        _normalize_giveaway_fields(data)

        # Safety: prevent generated eBay listing template HTML from being saved
        # into the Description field (the full template has <strong>Title</strong>
        # section headers).  Simple rich-text tags (<div>, <br>, <b>, <i>, lists)
        # from the description editor are allowed through.
        if 'Description' in data:
            desc_val = data['Description']
            if desc_val and '<strong>' in desc_val and any(
                    label in desc_val for label in
                    ['<strong>Title</strong>', '<strong>Description</strong>',
                     '<strong>Condition</strong>', '<strong>Shipping</strong>']):
                # This looks like a full eBay listing template — strip it all
                data['Description'] = re.sub(r'</?(div|p|br|li|ul|ol)[^>]*/??>', '\n', desc_val, flags=re.IGNORECASE)
                data['Description'] = re.sub(r'<[^>]+>', '', data['Description'])
                data['Description'] = '\n'.join(l.strip() for l in data['Description'].split('\n'))
                data['Description'] = re.sub(r'\n{3,}', '\n\n', data['Description']).strip()
                current_app.logger.warning(f"[add_comic] Stripped eBay template HTML from Description field")

        # Create comic
        success, result = comic_service.create_comic(data, files, duplicate_image_urls=images_to_duplicate)

        if success:
            return jsonify({
                'success': True,
                'message': f'Comic added successfully! SKU: {result.sku}',
                'sku': result.sku
            })
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        current_app.logger.error(f"Error adding comic: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while adding the comic'}), 500


@api_bp.route('/comic/<sku>', methods=['GET'])
@login_required
def get_comic(sku):
    """Get a single comic by SKU."""
    try:
        comic = comic_service.get_comic(sku)
        if comic:
            comic_dict = comic.to_dict()
            response = jsonify({
                'success': True,
                'comic': comic_dict
            })
            # Prevent browser caching to ensure fresh data
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            return jsonify({'success': False, 'message': 'Comic not found'}), 404
    except Exception as e:
        current_app.logger.error(f"Error getting comic: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while retrieving the comic'}), 500


@api_bp.route('/comic/<sku>', methods=['PUT'])
@login_required
@csrf_required
@sync_not_locked
def update_comic(sku: str) -> Response:
    """Update existing comic with new data and images.

    Updates comic fields and manages images (add new, delete existing).
    Supports all comic fields and eBay metadata.

    Path Parameters:
        sku (str): Comic SKU to update

    Form Data (multipart/form-data):
        Any comic fields to update
        images (files, optional): New images to add
        delete_images (list, optional): Image URLs to delete
        ebayListingMode, ebayScheduleDate, etc. (optional): eBay fields

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether update succeeded
            - message (str): Confirmation message
            - comic (dict): Updated comic data
            - error (str, optional): Error if failed

    Status Codes:
        200: Comic updated successfully
        400: Validation error or invalid images
        404: Comic not found
        403: Disk space too low
        409: Sync in progress
        500: Server error

    Example Response:
        {
            "success": true,
            "message": "Comic updated successfully",
            "comic": {...}
        }

    Note:
        - Can add up to 8 total images
        - Deletes specified images from S3
        - Updates eBay cache if item linked
        - Backs up CSV to S3 after update
    """
    try:
        # Handle both JSON and form data
        # If Content-Type is application/json, use JSON data; otherwise use form data
        is_json = request.is_json
        data = request.get_json() if is_json else request.form.to_dict()
        new_files = [] if is_json else request.files.getlist('images')

        # Validate file uploads
        allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
        max_file_size = 10 * 1024 * 1024  # 10MB per file

        for file in new_files:
            if file and file.filename:
                try:
                    validate_uploaded_image(
                        file,
                        allowed_extensions=allowed_extensions,
                        max_bytes=max_file_size,
                    )
                except UploadValidationError as exc:
                    return jsonify({'success': False, 'message': str(exc)}), exc.status_code

        # Get existing images that should be kept
        existing_images = []
        has_existing_image_fields = False

        # Check for sentinel field that indicates user is explicitly managing images
        # This distinguishes "user deleted all images" from "view-mode save (don't touch images)"
        images_managed = data.get('images_managed') == 'true'

        for i in range(1, 9):
            field_name = f'existing_image_{i}'
            if field_name in data:
                has_existing_image_fields = True
            img_url = data.get(field_name, '').strip()
            if img_url:
                existing_images.append(img_url)

        # If images_managed=true, treat as explicit image management even if no existing_image_* fields
        if images_managed:
            has_existing_image_fields = True

        # Get comic to find removed images
        existing_comic = comic_service.get_comic(sku)
        if not existing_comic:
            return jsonify({'success': False, 'message': f'Comic with SKU {sku} not found'}), 404

        # Check that total images don't exceed 8
        total_images = len(existing_images) + len([f for f in new_files if f.filename])
        if total_images > 8:
            return jsonify({
                'success': False,
                'message': f'Maximum 8 images allowed (currently: {len(existing_images)} existing + {len([f for f in new_files if f.filename])} new)'
            }), 400

        # IMPORTANT: Only calculate removed images if we have existing_image fields in the request
        # If no existing_image fields are sent (e.g., from view mode), don't remove any images
        # SAFETY CHECK: If images_managed=true but no existing_image values were sent AND no new files,
        # this likely means a bug or page load issue - don't delete all images!
        if has_existing_image_fields:
            # Extra safety: If comic has images but we got zero existing_image values and zero new files,
            # this is suspicious - keep existing images to prevent accidental deletion
            has_new_files = any(f and f.filename for f in new_files)
            if existing_comic.image_urls and not existing_images and not has_new_files:
                # Suspicious: comic has images, but frontend sent no existing_image values and no new files
                # This could be a page load bug or race condition - DON'T delete all images!
                current_app.logger.warning(f"[update_comic] SKU {sku}: Prevented accidental image deletion - comic has {len(existing_comic.image_urls)} images but received empty existing_images with no new files")
                removed_images = []
                existing_images = existing_comic.image_urls  # Keep all existing images
            else:
                # Normal case: calculate which images to remove
                removed_images = [url for url in existing_comic.image_urls if url not in existing_images]
        else:
            # No existing_image fields sent - this is likely a view-mode save, keep all images
            removed_images = []
            existing_images = existing_comic.image_urls  # Keep all existing images

        # Filter out non-CSV fields (frontend-only fields)
        # NOTE: 'eBay Item ID' is excluded here because it must only be set/cleared by
        # the dedicated eBay routes (list, update, delist, unlink) — not by the general save form.
        non_csv_fields = ['sku', 'eBay Item ID',
                         'existing_image_1', 'existing_image_2', 'existing_image_3',
                         'existing_image_4', 'existing_image_5', 'existing_image_6',
                         'existing_image_7', 'existing_image_8', 'images_managed',
                         'ebayShippingProfile',
                         'ebayBestOfferAutoAccept', 'ebayMinBestOffer', 'ebayBestOfferEnabled',
                         'ebayAction', 'ebayCondition', 'ebayCategory',
                         'ebayListingMode', 'ebayScheduleDate', 'ebayAllowOffers',
                         'ebayOfferMin', 'ebayOfferMax']  # These get converted to proper CSV names below
        cleaned_data = {k: v for k, v in data.items() if k not in non_csv_fields}

        # Safety: prevent generated eBay listing template HTML from being saved
        # into the Description field.  Simple rich-text tags from the editor are OK.
        if 'Description' in cleaned_data:
            desc_val = cleaned_data['Description']
            if desc_val and '<strong>' in desc_val and any(
                    label in desc_val for label in
                    ['<strong>Title</strong>', '<strong>Description</strong>',
                     '<strong>Condition</strong>', '<strong>Shipping</strong>']):
                cleaned_data['Description'] = re.sub(r'</?(div|p|br|li|ul|ol)[^>]*/??>', '\n', desc_val, flags=re.IGNORECASE)
                cleaned_data['Description'] = re.sub(r'<[^>]+>', '', cleaned_data['Description'])
                cleaned_data['Description'] = '\n'.join(l.strip() for l in cleaned_data['Description'].split('\n'))
                cleaned_data['Description'] = re.sub(r'\n{3,}', '\n\n', cleaned_data['Description']).strip()
                current_app.logger.warning(f"[update_comic] SKU {sku}: Stripped eBay template HTML from Description field")

        # Handle eBay listing settings (these GO TO CSV)
        # Convert camelCase to proper CSV column names

        # IMPORTANT: Check if item is actively listed on eBay
        # If so, prevent changing the listing mode (mode is locked once active)
        if 'ebayListingMode' in data:
            new_listing_mode = data['ebayListingMode']

            # If comic has an eBay Item ID, check if it's actively listed
            if existing_comic.ebay_item_id:
                try:
                    # Verify if listing is active on eBay
                    item_info = ebay_service.get_item(existing_comic.ebay_item_id, environment='production')
                    if item_info:
                        listing_status = item_info.get('ListingStatus', 'Unknown')

                        # If listing is active or scheduled, prevent mode changes
                        if listing_status in ['Active', 'Scheduled']:
                            # Get existing mode from comic
                            existing_mode = existing_comic.extra_fields.get('eBay Listing Mode', None)

                            # If user is trying to change the mode, reject it
                            if existing_mode and new_listing_mode != existing_mode:
                                current_app.logger.warning(
                                    f"[update_comic] SKU {sku}: Attempted to change listing mode from '{existing_mode}' to '{new_listing_mode}' "
                                    f"while item is actively listed (status: {listing_status}). Change rejected."
                                )
                                return jsonify({
                                    'success': False,
                                    'message': f'Cannot change listing mode while item is actively listed on eBay (Status: {listing_status}). '
                                               f'The listing mode is locked once an item is listed. '
                                               f'To update other fields, use the "Update on eBay" button instead of changing the listing mode.'
                                }), 400
                except Exception as e:
                    # If verification fails, log but allow the update (fail open)
                    current_app.logger.warning(
                        f"[update_comic] SKU {sku}: Could not verify eBay listing status: {e}. Allowing mode change."
                    )

            cleaned_data['eBay Listing Mode'] = new_listing_mode

        if 'ebayScheduleDate' in data:
            cleaned_data['eBay Schedule Date'] = data['ebayScheduleDate']

        # Convert eBay offer fields from camelCase to proper names
        if 'ebayAllowOffers' in data:
            cleaned_data['eBay Allow Offers'] = data['ebayAllowOffers']

        if 'ebayOfferMin' in data:
            cleaned_data['eBay Offer Min'] = data['ebayOfferMin']

        if 'ebayOfferMax' in data:
            cleaned_data['eBay Offer Max'] = data['ebayOfferMax']

        # Convert Comic object to dict for merging
        existing_data = existing_comic.to_dict()

        # Debug logging for image management
        current_app.logger.debug(f"[update_comic] SKU {sku}: images_managed={images_managed}, has_existing_image_fields={has_existing_image_fields}")
        current_app.logger.debug(f"[update_comic] SKU {sku}: existing_comic has {len(existing_comic.image_urls)} images, received {len(existing_images)} existing_image values, {len(removed_images)} to remove")
        if removed_images:
            current_app.logger.debug(f"[update_comic] SKU {sku}: Removing images: {removed_images}")

        # IMPORTANT: Remove any camelCase field names that might have leaked into the CSV from previous save attempts
        # These should be converted to proper CSV column names (see conversions below)
        camel_case_fields_to_remove = ['ebayListingMode', 'ebayScheduleDate', 'ebayAction', 'ebayCondition',
                                       'ebayCategory', 'ebayShippingProfile', 'ebayBestOfferAutoAccept',
                                       'ebayMinBestOffer', 'ebayBestOfferEnabled', 'ebayAllowOffers',
                                       'ebayOfferMin', 'ebayOfferMax']
        for field in camel_case_fields_to_remove:
            existing_data.pop(field, None)

        # Merge form data with existing data: form data takes precedence, but preserve existing data for missing fields
        # This ensures fields not in the form (like eBay Category ID, Format, etc.) are not lost
        merged_data = existing_data.copy()
        merged_data.update(cleaned_data)

        # Persist canonical giveaway / WhatNot flags based on the selected Type.
        _normalize_giveaway_fields(merged_data)

        was_giveaway = is_giveaway(
            existing_data.get('Title', ''),
            existing_data.get(WHATNOT_FIELD_NAMES['LISTING_TYPE'])
        )
        is_now_giveaway = is_giveaway(
            merged_data.get('Title', ''),
            merged_data.get(WHATNOT_FIELD_NAMES['LISTING_TYPE'])
        )

        # If a listed comic is moved to Giveaway, end the live/scheduled eBay
        # listing first and clear the local linkage in the same save.
        if not was_giveaway and is_now_giveaway and existing_comic.ebay_item_id:
            try:
                listing_status = 'Unknown'
                item_info = ebay_service.get_item(existing_comic.ebay_item_id, environment='production')
                if item_info:
                    listing_status = item_info.get('ListingStatus', 'Unknown')

                if listing_status in ['Active', 'Scheduled']:
                    ebay_service.end_listing(existing_comic, reason='NotAvailable', environment='production')
                    current_app.logger.info(
                        "[update_comic] SKU %s: Auto-delisted eBay item %s while switching to Giveaway",
                        sku,
                        existing_comic.ebay_item_id,
                    )

                merged_data[METADATA_FIELD_NAMES['EBAY_ITEM_ID']] = ''
            except Exception as exc:
                current_app.logger.error(
                    "[update_comic] SKU %s: Failed to auto-delist eBay item %s during Giveaway transition: %s",
                    sku,
                    existing_comic.ebay_item_id,
                    exc,
                )
                return jsonify({
                    'success': False,
                    'message': (
                        'Could not move item to Giveaway because ending the eBay listing failed. '
                        f"{safe_error_message(exc)}"
                    )
                }), 500

        # NOTE: Do NOT apply defaults here - we're editing an existing comic.
        # The merge above already preserves existing values from the CSV.
        # Applying defaults would overwrite saved values (like 'eBay Listing Mode': 'list')
        # with admin defaults (like 'eBay Listing Mode': 'future').

        # Update comic - pass existing_images to preserve reordered position
        success, result = comic_service.update_comic(sku, merged_data, new_files, removed_images, existing_images)

        if success:
            return jsonify({
                'success': True,
                'message': f'Comic updated successfully! SKU: {sku}'
            })
        else:
            current_app.logger.error(f"[update_comic] Failed to update SKU {sku}: {result}")
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        current_app.logger.error(f"Error updating comic: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while updating the comic'}), 500


@api_bp.route('/comics/update-title-price', methods=['POST'])
@login_required
@csrf_required
@sync_not_locked
def update_comic_title_price() -> Response:
    """Quick update for title and price only.

    Fast endpoint for updating just Title and Price fields without
    full form validation. Used for quick edits.

    Request Body (JSON):
        {
            "sku": str,       # Comic SKU
            "title": str,     # New title
            "price": float    # New price
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether update succeeded
            - message (str): Confirmation message

    Status Codes:
        200: Updated successfully
        400: Missing required fields
        404: Comic not found
        500: Server error

    Example Request:
        {
            "sku": "1025",
            "title": "Amazing Spider-Man #300 NM",
            "price": "49.99"
        }

    Note:
        - Faster than full update
        - Only updates Title and Price
        - Backs up CSV to S3
    """
    try:
        data = request.get_json()
        sku = data.get('sku')
        title = data.get('title')
        price = data.get('price')

        if not sku:
            return jsonify({'success': False, 'error': 'SKU is required'}), 400

        if title is None and price is None:
            return jsonify({'success': False, 'error': 'Either title or price must be provided'}), 400

        # Get the existing comic
        comic = comic_service.get_comic(sku)
        if not comic:
            return jsonify({'success': False, 'error': 'Comic not found'}), 404

        # Update only the specified fields
        update_data = {}
        if title is not None:
            update_data['Title'] = title
        if price is not None:
            update_data['Price'] = math.ceil(float(price))

        # Use the comic service to update
        success, message = comic_service.update_comic(sku, update_data)

        if success:
            ebay_updated = False
            ebay_error = None

            # If price was changed and comic is listed on eBay, push the new price
            if price is not None:
                updated_comic = comic_service.get_comic(sku)
                ebay_item_id = (updated_comic.ebay_item_id if updated_comic else None) or comic.ebay_item_id
                if ebay_item_id:
                    try:
                        ebay_service.update_price_only(ebay_item_id, math.ceil(float(price)))
                        ebay_updated = True
                        current_app.logger.info(
                            "[update_comic_title_price] SKU %s: eBay price updated to %s (item %s)",
                            sku, math.ceil(float(price)), ebay_item_id,
                        )
                    except Exception as ebay_exc:
                        ebay_error = safe_error_message(ebay_exc)
                        current_app.logger.warning(
                            "[update_comic_title_price] SKU %s: eBay price update failed: %s",
                            sku, ebay_exc,
                        )

            response_body = {'success': True, 'message': 'Comic updated successfully', 'ebay_updated': ebay_updated}
            if ebay_error:
                response_body['ebay_error'] = ebay_error
            return jsonify(response_body)
        else:
            return jsonify({'success': False, 'error': message}), 500

    except Exception as e:
        current_app.logger.error(f"Error updating comic title/price: {e}")
        return jsonify({'success': False, 'error': 'Failed to update comic'}), 500


@api_bp.route('/comic/<sku>', methods=['DELETE'])
@login_required
@csrf_required
@sync_not_locked
def delete_comic(sku: str) -> Response:
    """Delete single comic and its images.

    Permanently deletes comic from inventory and moves images to trash.

    Path Parameters:
        sku (str): Comic SKU to delete

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether deletion succeeded
            - message (str): Confirmation message

    Status Codes:
        200: Comic deleted successfully
        404: Comic not found
        500: Server error during deletion

    Warning:
        - This operation is permanent
        - Images moved to trash (can be restored)
        - CSV backed up to S3 after deletion
    """
    try:
        # Block deletion if the item is still listed on an external platform.
        comic = comic_service.get_comic(sku)
        if comic is None:
            return jsonify({'success': False, 'message': f'Comic with SKU {sku} not found'}), 404

        platforms = _get_active_platforms(comic)
        if platforms:
            platform_str = ' and '.join(platforms)
            return jsonify({
                'success': False,
                'message': (
                    f'This item is still listed on {platform_str}. '
                    f'Please remove it from {platform_str} before deleting.'
                ),
                'listed_on': platforms,
            }), 409

        success, message = comic_service.delete_comic(sku)

        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 404

    except Exception as e:
        current_app.logger.error(f"Error deleting comic: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete comic'}), 500


@api_bp.route('/comics/delete-all', methods=['DELETE'])
@login_required
@csrf_required
@sync_not_locked
def delete_all_comics() -> Response:
    """Delete ALL comics from inventory with confirmation.

    Nuclear option - deletes entire inventory. Requires confirmation token.

    Request Body (JSON):
        {
            "confirmation": str  # Must be "DELETE_ALL_COMICS"
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether deletion succeeded
            - message (str): Confirmation with count
            - deleted_count (int): Number of comics deleted

    Status Codes:
        200: All comics deleted
        400: Missing or incorrect confirmation
        500: Server error

    Example Request:
        {
            "confirmation": "DELETE_ALL_COMICS"
        }

    Warning:
        - DELETES ALL INVENTORY
        - Cannot be undone
        - Images moved to trash
        - Requires exact confirmation string
        - Use with extreme caution
    """
    try:
        data = request.get_json() or {}
        confirmation = data.get('confirmation', '')

        # Require explicit confirmation token to prevent accidental deletion
        if confirmation != 'DELETE_ALL_COMICS':
            return jsonify({
                'success': False,
                'error': 'Confirmation required. Send {"confirmation": "DELETE_ALL_COMICS"} to confirm deletion.'
            }), 400

        # Block if any items are still listed on external platforms.
        all_comics = comic_service.get_comics_paginated(per_page=10000).get('comics', [])
        listed_platforms: set[str] = set()
        listed_count = 0
        for comic in all_comics:
            platforms = _get_active_platforms(comic)
            if platforms:
                listed_count += 1
                listed_platforms.update(platforms)

        if listed_count:
            platform_str = ' and '.join(sorted(listed_platforms))
            return jsonify({
                'success': False,
                'error': (
                    f'{listed_count} item(s) are still listed on {platform_str}. '
                    f'Please remove all items from {platform_str} before using Delete All.'
                ),
                'listed_count': listed_count,
            }), 409

        result = comic_service.delete_all_comics()
        return jsonify({
            'success': True,
            'deleted_count': result['comics_deleted'],
            'images_deleted': result['images_deleted'],
            'message': result['message']
        })
    except Exception as e:
        current_app.logger.error(f"Error deleting all comics: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while deleting comics'}), 500


@api_bp.route('/comics/bulk-update', methods=['POST'])
@login_required
@csrf_required
def bulk_update_comics() -> Response:
    """Update multiple comics at once.

    Applies same field updates to multiple comics. Used for batch operations.

    Request Body (JSON):
        {
            "skus": [str],           # List of SKUs to update
            "updates": {dict}         # Fields to update
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether updates succeeded
            - message (str): Confirmation message
            - updated_count (int): Number of comics updated

    Status Codes:
        200: Updates completed
        400: Invalid request data
        500: Server error

    Example Request:
        {
            "skus": ["1025", "1026", "1027"],
            "updates": {
                "Listing Type": "For Sale eBay",
                "Condition": "NM"
            }
        }

    Note:
        - All specified SKUs must exist
        - Same updates applied to all
        - CSV backed up after updates
    """
    try:
        data = request.get_json()
        skus = data.get('skus', [])
        updates = data.get('updates', {})

        if not skus:
            return jsonify({'success': False, 'error': 'No SKUs provided'}), 400

        if not updates:
            return jsonify({'success': False, 'error': 'No updates provided'}), 400

        updated_count = comic_service.bulk_update_comics(skus, updates)
        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'message': f'Successfully updated {updated_count} item(s)'
        })
    except Exception as e:
        current_app.logger.error(f"Error bulk updating comics: {e}")
        return jsonify({'success': False, 'error': 'Failed to bulk update comics'}), 500


@api_bp.route('/comics/delete-selected', methods=['DELETE'])
@login_required
@csrf_required
def delete_selected_comics() -> Response:
    """Delete multiple selected comics.

    Bulk delete operation for selected comics from browse page.

    Request Body (JSON):
        {
            "skus": [str]  # List of SKUs to delete
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether deletion succeeded
            - message (str): Confirmation with count
            - deleted_count (int): Number deleted

    Status Codes:
        200: Comics deleted successfully
        400: Missing SKU list
        500: Server error

    Warning:
        - Permanently deletes selected comics
        - Images moved to trash
        - Cannot be undone
    """
    try:
        data = request.get_json()
        skus = data.get('skus', [])

        if not skus:
            return jsonify({'success': False, 'error': 'No SKUs provided'}), 400

        # Block deletion for any item still listed on an external platform.
        blocked: list[dict] = []
        for sku in skus:
            comic = comic_service.get_comic(sku)
            if comic is None:
                continue
            platforms = _get_active_platforms(comic)
            if platforms:
                blocked.append({'sku': sku, 'platforms': platforms})

        if blocked:
            items_str = ', '.join(
                f"SKU {b['sku']} ({' and '.join(b['platforms'])})" for b in blocked
            )
            return jsonify({
                'success': False,
                'error': (
                    f'The following items are still listed on external platforms and must be '
                    f'removed before deletion: {items_str}.'
                ),
                'blocked': blocked,
            }), 409

        deleted_count, message = comic_service.delete_selected_comics(skus)
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'message': message
        })
    except Exception as e:
        current_app.logger.error(f"Error deleting selected comics: {e}")
        return jsonify({'success': False, 'error': 'Failed to delete selected comics'}), 500


@api_bp.route('/export-selected', methods=['POST'])
@login_required
@csrf_required
def export_selected() -> tuple:
    """Export selected comics to CSV file.

    Generates downloadable CSV file with selected comics data.

    Request Body (JSON):
        {
            "skus": [str]  # List of SKUs to export
        }

    Returns:
        tuple: (csv_file, status_code, headers)
            - csv_file (BytesIO): CSV file in memory
            - status_code (int): HTTP 200
            - headers (dict): Content-Disposition header

    Status Codes:
        200: CSV generated successfully
        400: No SKUs provided
        500: Server error

    Response Headers:
        Content-Type: text/csv
        Content-Disposition: attachment; filename=comics_export_TIMESTAMP.csv

    Note:
        - Includes all comic fields
        - Filename includes timestamp
        - UTF-8 encoding
        - Compatible with Excel/Google Sheets
    """
    try:
        data = request.get_json()
        skus = data.get('skus', [])
        platform = data.get('platform', 'whatnot').lower()

        if not skus:
            return jsonify({'success': False, 'message': 'No items selected'}), 400

        if platform not in ['whatnot', 'ebay']:
            return jsonify({'success': False, 'message': 'Invalid platform'}), 400

        # Get selected comics from service
        selected_comics = comic_service.get_selected_comics(skus)

        if not selected_comics:
            return jsonify({'success': False, 'message': 'No comics found for selected SKUs'}), 404

        # Create CSV in memory
        output = StringIO()

        if platform == 'whatnot':
            # WhatNot export: only include comics tagged for WhatNot (WhatNot Item ID == 'TRUE')
            whatnot_tagged = [comic for comic in selected_comics if is_whatnot_listed(comic)]

            if not whatnot_tagged:
                return jsonify({'success': False, 'message': 'No selected comics are tagged for WhatNot listing (WhatNot Item ID must be TRUE)'}), 400

            # Use the full proper WhatNot CSV schema and defaulting rules.
            fieldnames = get_whatnot_export_fieldnames()

            writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()

            for comic in whatnot_tagged:
                writer.writerow(sanitize_row(build_whatnot_export_row(comic)))

        else:  # eBay export
            # eBay export fields - use constants
            fieldnames = [
                WHATNOT_FIELD_NAMES['SKU'],
                WHATNOT_FIELD_NAMES['TITLE'],
                METADATA_FIELD_NAMES['EBAY_ITEM_ID'],
                WHATNOT_FIELD_NAMES['PRICE'],
                WHATNOT_FIELD_NAMES['QUANTITY'],
                WHATNOT_FIELD_NAMES['CONDITION'],
                WHATNOT_FIELD_NAMES['DESCRIPTION'],
                WHATNOT_FIELD_NAMES['IMAGE_URL_1'],
            ]

            writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()

            for comic in selected_comics:
                comic_dict = comic.to_dict()

                # Build row with eBay fields - use constants
                row = {
                    WHATNOT_FIELD_NAMES['SKU']: comic_dict.get(WHATNOT_FIELD_NAMES['SKU'], ''),
                    WHATNOT_FIELD_NAMES['TITLE']: comic_dict.get(WHATNOT_FIELD_NAMES['TITLE'], ''),
                    METADATA_FIELD_NAMES['EBAY_ITEM_ID']: comic_dict.get(METADATA_FIELD_NAMES['EBAY_ITEM_ID'], ''),
                    WHATNOT_FIELD_NAMES['PRICE']: comic_dict.get(WHATNOT_FIELD_NAMES['PRICE'], ''),
                    WHATNOT_FIELD_NAMES['QUANTITY']: comic_dict.get(WHATNOT_FIELD_NAMES['QUANTITY'], '1'),
                    WHATNOT_FIELD_NAMES['CONDITION']: comic_dict.get(WHATNOT_FIELD_NAMES['CONDITION'], ''),
                    WHATNOT_FIELD_NAMES['DESCRIPTION']: comic_dict.get(WHATNOT_FIELD_NAMES['DESCRIPTION'], ''),
                    WHATNOT_FIELD_NAMES['IMAGE_URL_1']: comic_dict.get(WHATNOT_FIELD_NAMES['IMAGE_URL_1'], ''),
                }

                writer.writerow(sanitize_row(row))

        # Convert StringIO to bytes and send as download
        csv_data = output.getvalue()
        output.close()

        bytes_output = BytesIO(csv_data.encode('utf-8'))
        bytes_output.seek(0)

        export_count = len(whatnot_tagged) if platform == 'whatnot' else len(selected_comics)
        filename = f"{platform}_export_{export_count}_items_{time.strftime('%Y-%m-%d')}.csv"

        return send_file(
            bytes_output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        current_app.logger.error(f"Error exporting selected comics: {e}")
        return jsonify({'success': False, 'message': safe_error_message(e)}), 500


@api_bp.route('/comics/for-linking', methods=['GET'])
@login_required
def get_comics_for_linking() -> Response:
    """Get comics available for eBay linking.

    Returns comics marked as "For Sale eBay" that don't have eBay Item IDs.
    Used in eBay linking interface.

    Query Parameters:
        page (int, optional): Page number (default: 1)
        per_page (int, optional): Items per page (default: 50)
        search (str, optional): Search term

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Always true
            - comics (list): Comics available for linking with SKU, Title, image
            - pagination (dict): Pagination info

    Status Codes:
        200: Comics retrieved
        500: Server error

    Example Response:
        {
            "success": true,
            "comics": [
                {
                    "SKU": "1025",
                    "Title": "Amazing Spider-Man #300",
                    "Price": "45.99",
                    "first_image": "https://..."
                }
            ],
            "pagination": {...}
        }

    Note:
        - Only returns "For Sale eBay" comics
        - Excludes comics already linked to eBay
        - Used for manual eBay linking modal
        - Returns only essential fields for performance
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '', type=str).strip()

        # Enforce pagination limits
        max_per_page = current_app.config.get('MAX_PER_PAGE', 100)
        if per_page > max_per_page:
            per_page = max_per_page
        if per_page < 1:
            per_page = 50
        if page < 1:
            page = 1

        # Get filtered comics using the service
        result = comic_service.get_comics_paginated(
            page=page,
            per_page=per_page,
            search_term=search,
            listing_type='',
            sort_by='sku_asc'
        )

        # Filter out comics that already have eBay IDs or are giveaways, and minimize data
        linkable_comics = []
        for comic in result['comics']:
            comic_dict = comic.to_dict()

            # Skip if has eBay ID or is giveaway
            ebay_item_id = comic_dict.get('eBay Item ID', '').strip()
            if ebay_item_id:
                continue

            # Skip if is a Giveaway item (check both Listing Type field and title prefix for backward compatibility)
            listing_type = comic_dict.get('Listing Type', '').strip()
            is_giveaway_item = (listing_type == 'Giveaway') or is_giveaway(comic_dict.get('Title', ''))

            if is_giveaway_item:
                continue

            # Return only essential data for linking
            linkable_comics.append({
                'SKU': comic_dict.get('SKU', ''),
                'Title': comic_dict.get('Title', ''),
                'Image URL 1': comic_dict.get('Image URL 1', '')  # Only first image
            })

        # Recalculate pagination based on filtered results
        total_linkable = len(linkable_comics)
        start = (page - 1) * per_page
        end = start + per_page
        page_comics = linkable_comics[start:end]

        pagination = {
            'page': page,
            'per_page': per_page,
            'total': total_linkable,
            'total_pages': (total_linkable + per_page - 1) // per_page,
            'has_next': end < total_linkable,
            'has_prev': page > 1
        }

        return jsonify({
            'success': True,
            'comics': page_comics,
            'pagination': pagination
        })

    except Exception as e:
        current_app.logger.error(f"Error getting comics for linking: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while retrieving linkable comics'}), 500
