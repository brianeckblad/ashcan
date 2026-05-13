"""eBay Listings routes - Account listings management and viewing.

This module handles:
- Fetching seller's active eBay listings with caching
- Clearing listings cache for refresh
- Fetching individual item descriptions

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import request, jsonify, current_app, Response
from app.routes.api import api_bp
from app.routes.auth import login_required, csrf_required
from app.services.ebay_service import ebay_service
from app.services.comic_service import comic_service
from app.utils.defaults_helpers import get_user_preferences
from app.utils.logging_utils import safe_error_message
from app.utils.ebay_helpers import (
    extract_ebay_description_section,
    extract_ebay_condition_section,
    extract_all_sections_from_ebay_description,
)
from datetime import datetime


@api_bp.route('/ebay/listings', methods=['GET'])
@login_required
def get_ebay_listings() -> Response:
    """Fetch all active listings from seller's eBay account with pagination.

    Retrieves all active listings from the authenticated seller's eBay account.
    Uses in-memory caching (1 hour TTL) to avoid repeated API calls to eBay.
    Supports pagination for displaying listings in batches.

    Query Parameters:
        page (int, optional): Page number (default: 1)
        per_page (int, optional): Items per page (default: user preference or 24)

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether fetch succeeded
            - listings (list): List of eBay listing objects with:
                - itemId (str): eBay Item ID
                - title (str): Listing title
                - price (float): Current price
                - quantity (int): Available quantity
                - listingStatus (str): Active, Ended, etc.
                - viewItemURL (str): eBay listing URL
                - pictureURL (str): Main image URL
                - localSKU (str, optional): Linked local SKU if available
            - count (int): Number of listings on current page
            - total_count (int): Total listings available
            - has_more (bool): Whether more pages exist
            - page (int): Current page number
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved listings
        500: eBay API error or server error

    Example Request:
        GET /ebay/listings?page=1&per_page=24

    Example Response:
        {
            "success": true,
            "listings": [
                {
                    "itemId": "123456789012",
                    "title": "Amazing Spider-Man #300",
                    "price": 45.99,
                    "quantity": 1,
                    "listingStatus": "Active",
                    "viewItemURL": "https://ebay.com/itm/123456789012",
                    "pictureURL": "https://...",
                    "localSKU": "1025"
                }
            ],
            "count": 24,
            "total_count": 156,
            "has_more": true,
            "page": 1
        }

    Note:
        - Listings are cached for 1 hour to reduce API calls
        - Cache is environment-specific (production/sandbox)
        - Links to local inventory by matching eBay Item ID
        - Pagination happens client-side after fetching all listings
        - Use clear-cache endpoint to force refresh
    """
    try:
        prefs = get_user_preferences()
        environment = (prefs.get('ebay_environment') or 'production').lower()

        page_number = request.args.get('page', 1, type=int)
        items_per_page = int(prefs.get('desktop_per_page') or 24)

        if page_number < 1:
            page_number = 1

        # Use cache key based on environment to avoid cross-environment cache issues
        cache_key = f'ebay_listings_{environment}'

        # Check if we have cached listings
        if cache_key in current_app.ebay_cache:
            cached_data = current_app.ebay_cache[cache_key]
            all_listings = cached_data['listings']
            current_app.logger.info(f"Using cached eBay listings: {len(all_listings)} items (fetched {cached_data['fetched_at']})")
        else:
            # Fetch ALL listings once from eBay
            current_app.logger.info(f"Fetching ALL eBay listings from eBay API (not cached)")

            # Load all comics to check for linked eBay IDs
            ebay_id_to_sku = {}
            try:
                all_comics = comic_service.get_all_comics() or []
                current_app.logger.info(f"Retrieved {len(all_comics)} comics from service")
                # Handle both Comic objects and dictionaries
                for comic in all_comics:
                    if isinstance(comic, dict):
                        ebay_id = comic.get('eBay Item ID', '').strip()
                        if ebay_id:
                            ebay_id_to_sku[ebay_id] = comic.get('SKU', '')
                    else:
                        # Comic object
                        comic_dict = comic.to_dict() if hasattr(comic, 'to_dict') else comic.__dict__
                        ebay_id = comic_dict.get('eBay Item ID', '').strip()
                        if ebay_id:
                            sku = comic_dict.get('SKU', '')
                            ebay_id_to_sku[ebay_id] = sku
                current_app.logger.info(f"Loaded {len(ebay_id_to_sku)} linked eBay items")
            except Exception as e:
                current_app.logger.warning(f"Failed to load comics for link checking: {e}")
                ebay_id_to_sku = {}

            def _parse_item(item, status_label):
                """Parse an eBay item from API response into a listing dict."""
                try:
                    item_id = getattr(item, 'ItemID', '')
                    title = getattr(item, 'Title', 'Unknown Title')
                    quantity = int(getattr(item, 'Quantity', 1) or 1)
                    quantity_sold = int(getattr(item, 'QuantitySold', 0) or 0)

                    current_price = '0.00'
                    try:
                        selling_status = getattr(item, 'SellingStatus', None)
                        if selling_status:
                            price_obj = getattr(selling_status, 'CurrentPrice', None)
                            if price_obj:
                                if hasattr(price_obj, 'value'):
                                    current_price = str(price_obj.value)
                                else:
                                    current_price = str(price_obj)
                    except Exception as e:
                        current_app.logger.debug(f"Price error for {item_id}: {e}")

                    image_url = ''
                    try:
                        picture_details = getattr(item, 'PictureDetails', None)
                        if picture_details:
                            gallery_url = getattr(picture_details, 'GalleryURL', None)
                            if gallery_url:
                                image_url = gallery_url if isinstance(gallery_url, str) else str(gallery_url)
                    except Exception as e:
                        current_app.logger.debug(f"Image error for {item_id}: {e}")

                    listing_type = getattr(item, 'ListingType', 'FixedPriceItem')

                    # Extract statistics
                    watch_count = 0
                    try:
                        watch_count = int(getattr(item, 'WatchCount', 0) or 0)
                    except Exception as e:
                        current_app.logger.debug(f"Watch count error for {item_id}: {e}")

                    # Extract scheduled start time for pending listings
                    scheduled_start = ''
                    if status_label == 'Pending':
                        try:
                            listing_details = getattr(item, 'ListingDetails', None)
                            if listing_details:
                                start_time = getattr(listing_details, 'StartTime', None)
                                if start_time:
                                    scheduled_start = str(start_time)
                        except Exception:
                            pass

                    # Check if this eBay item is linked to any inventory item
                    linked_sku = ebay_id_to_sku.get(item_id, '')

                    # Extract end reason for unsold items (e.g. "NotAvailable" = seller ended)
                    end_reason = ''
                    if status_label == 'Unsold':
                        try:
                            selling_status = getattr(item, 'SellingStatus', None)
                            if selling_status:
                                listing_status = getattr(selling_status, 'ListingStatus', '')
                                end_reason = str(listing_status) if listing_status else ''
                            # Also try ListingDetails.EndingReason
                            listing_details = getattr(item, 'ListingDetails', None)
                            if listing_details:
                                ending_reason = getattr(listing_details, 'EndingReason', '')
                                if ending_reason:
                                    end_reason = str(ending_reason)
                        except Exception:
                            pass

                    return {
                        'Title': title,
                        'ItemID': item_id,
                        'CurrentPrice': current_price,
                        'Quantity': quantity,
                        'QuantitySold': quantity_sold,
                        'ListingStatus': status_label,
                        'ListingType': listing_type,
                        'image_url': image_url,
                        'linked_sku': linked_sku,
                        'Description': extract_ebay_description_section(''),
                        'WatchCount': watch_count,
                        'ScheduledStart': scheduled_start,
                        'EndReason': end_reason,
                    }
                except Exception as e:
                    current_app.logger.error(f"Item parse error: {e}")
                    return None

            # --- Fetch ACTIVE listings ---
            all_listings = []
            page_counter = 1
            total_fetched = 0

            while page_counter <= 50:
                try:
                    payload = {
                        'ActiveList': {
                            'Pagination': {
                                'EntriesPerPage': 100,
                                'PageNumber': page_counter
                            },
                            'Include': 'true'
                        },
                        'DetailLevel': 'ReturnAll',
                        'OutputSelector': [
                            'ItemID',
                            'Title',
                            'SellingStatus',
                            'PrimaryCategory',
                            'PictureDetails',
                            'ListingType',
                            'Quantity',
                            'QuantitySold',
                            'WatchCount'
                        ]
                    }

                    current_app.logger.info(f"eBay API call: GetMyeBaySelling ActiveList page {page_counter}")
                    response = ebay_service._execute_trading_call('GetMyeBaySelling', payload, environment=environment, mode='read')

                    if response and hasattr(response.reply, 'ActiveList'):
                        items = response.reply.ActiveList.ItemArray.Item if hasattr(response.reply.ActiveList, 'ItemArray') else []

                        if not isinstance(items, list):
                            items = [items] if items else []

                        current_app.logger.info(f"eBay API returned {len(items)} active items on page {page_counter}")

                        if not items:
                            break

                        for item in items:
                            parsed = _parse_item(item, 'Active')
                            if parsed:
                                all_listings.append(parsed)
                                total_fetched += 1

                        # Check if more pages
                        try:
                            pagination = getattr(response.reply.ActiveList, 'PaginationResult', None)
                            if pagination:
                                total_pages = int(getattr(pagination, 'TotalNumberOfPages', 1) or 1)
                                if page_counter >= total_pages:
                                    break
                        except Exception:
                            pass

                        page_counter += 1
                    else:
                        break

                except Exception as e:
                    current_app.logger.error(f"eBay fetch error ActiveList page {page_counter}: {e}")
                    break

            active_count = len(all_listings)

            # --- Fetch SCHEDULED (pending) listings ---
            page_counter = 1
            while page_counter <= 50:
                try:
                    payload = {
                        'ScheduledList': {
                            'Pagination': {
                                'EntriesPerPage': 100,
                                'PageNumber': page_counter
                            },
                            'Include': 'true'
                        },
                        'DetailLevel': 'ReturnAll',
                        'OutputSelector': [
                            'ItemID',
                            'Title',
                            'SellingStatus',
                            'PrimaryCategory',
                            'PictureDetails',
                            'ListingType',
                            'ListingDetails',
                            'Quantity',
                            'QuantitySold',
                            'WatchCount'
                        ]
                    }

                    current_app.logger.info(f"eBay API call: GetMyeBaySelling ScheduledList page {page_counter}")
                    response = ebay_service._execute_trading_call('GetMyeBaySelling', payload, environment=environment, mode='read')

                    if response and hasattr(response.reply, 'ScheduledList'):
                        sched_list = response.reply.ScheduledList
                        items = sched_list.ItemArray.Item if hasattr(sched_list, 'ItemArray') else []

                        if not isinstance(items, list):
                            items = [items] if items else []

                        current_app.logger.info(f"eBay API returned {len(items)} pending items on page {page_counter}")

                        if not items:
                            break

                        for item in items:
                            parsed = _parse_item(item, 'Pending')
                            if parsed:
                                all_listings.append(parsed)
                                total_fetched += 1

                        # Check if more pages
                        try:
                            pagination = getattr(sched_list, 'PaginationResult', None)
                            if pagination:
                                total_pages = int(getattr(pagination, 'TotalNumberOfPages', 1) or 1)
                                if page_counter >= total_pages:
                                    break
                        except Exception:
                            pass

                        page_counter += 1
                    else:
                        break

                except Exception as e:
                    current_app.logger.error(f"eBay fetch error ScheduledList page {page_counter}: {e}")
                    break

            pending_count = len(all_listings) - active_count

            # Sort: pending first, then active — alphabetically within each group
            status_order = {'Pending': 0, 'Active': 1}
            all_listings.sort(key=lambda x: (status_order.get(x['ListingStatus'], 3), x['Title'].lower()))

            # Cache the results for 1 hour
            current_app.logger.info(f"Caching {len(all_listings)} eBay listings ({active_count} active, {pending_count} scheduled)")
            current_app.ebay_cache[cache_key] = {
                'listings': all_listings,
                'fetched_at': datetime.now().isoformat(),
                'total_fetched': total_fetched,
                'active_count': active_count,
                'pending_count': pending_count,
            }

        # Now paginate from cached results
        total_count = len(all_listings)
        start_idx = (page_number - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_listings = all_listings[start_idx:end_idx]
        has_more = end_idx < total_count

        # Get counts from cache
        cached_data = current_app.ebay_cache.get(cache_key, {})
        active_count = cached_data.get('active_count', total_count)
        pending_count = cached_data.get('pending_count', 0)

        current_app.logger.info(f"Page {page_number}: {len(page_listings)} listings of {total_count} total ({active_count} active, {pending_count} scheduled)")

        return jsonify({
            'success': True,
            'listings': page_listings,
            'count': len(page_listings),
            'page': page_number,
            'per_page': items_per_page,
            'total_count': total_count,
            'active_count': active_count,
            'pending_count': pending_count,
            'has_more': has_more,
        })

    except Exception as e:
        current_app.logger.error(f"Error in get_ebay_listings: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': safe_error_message(e),
            'listings': []
        }), 500


@api_bp.route('/ebay/listings/clear-cache', methods=['POST'])
@login_required
@csrf_required
def clear_ebay_listings_cache() -> Response:
    """Force clear the eBay listings cache to fetch fresh data.

    Clears the in-memory cache of eBay listings, forcing the next request
    to fetch fresh data from eBay API. Useful when listings have been
    updated externally.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether cache was cleared
            - message (str): Confirmation message

    Status Codes:
        200: Cache cleared successfully (or was already empty)

    Example Response:
        {
            "success": true,
            "message": "Cache cleared successfully"
        }

    Note:
        - Cache is environment-specific (production/sandbox)
        - Next listings request will fetch from eBay API
        - Takes longer on next request but ensures fresh data
        - Use sparingly to avoid API rate limits
    """
    try:
        prefs = get_user_preferences()
        environment = (prefs.get('ebay_environment') or 'production').lower()
        cache_key = f'ebay_listings_{environment}'

        if cache_key in current_app.ebay_cache:
            del current_app.ebay_cache[cache_key]
            current_app.logger.info(f"Cleared eBay listings cache for {environment}")

        return jsonify({
            'success': True,
            'message': 'Cache cleared successfully'
        })
    except Exception as e:
        current_app.logger.error(f"Error clearing eBay cache: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e)
        }), 500


@api_bp.route('/ebay/item/<item_id>/description', methods=['GET'])
@login_required
def get_ebay_item_description(item_id: str) -> Response:
    """Fetch full description for a single eBay item on-demand.

    Retrieves complete item details from eBay including the full HTML description
    and condition details. Used when viewing an eBay listing to import its content
    into local inventory.

    Path Parameters:
        item_id (str): eBay Item ID (e.g., "123456789012")

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether fetch succeeded
            - itemId (str): eBay Item ID
            - title (str): Item title
            - description (str): Full HTML description
            - condition_details (str): Condition description text
            - price (float): Current price
            - quantity (int): Available quantity
            - error (str, optional): Error message if failed

    Status Codes:
        200: Successfully retrieved item
        404: Item not found on eBay
        500: eBay API error

    Example Request:
        GET /ebay/item/123456789012/description

    Example Response:
        {
            "success": true,
            "itemId": "123456789012",
            "title": "Amazing Spider-Man #300",
            "description": "Jim Mahfood variant cover...",
            "condition_details": "NM – Like New, raw copy...",
            "price": 45.99,
            "quantity": 1
        }

    Note:
        - Uses Trading API GetItem call
        - Extracts description from HTML CDATA section
        - Separates condition details from main description
        - Not cached (fetched on-demand)
        - Useful for creating local listings from eBay items
    """
    try:
        prefs = get_user_preferences()
        environment = (prefs.get('ebay_environment') or 'production').lower()

        current_app.logger.info(f"Fetching description for eBay item {item_id}")

        # Fetch item using GetItem API
        item_payload = {
            'ItemID': item_id,
            'DetailLevel': 'ReturnAll'
        }

        item_response = ebay_service._execute_trading_call('GetItem', item_payload, environment=environment, mode='read')

        if not item_response or not hasattr(item_response.reply, 'Item'):
            return jsonify({
                'success': False,
                'error': 'Could not fetch item from eBay',
                'description': ''
            }), 404

        item = item_response.reply.Item
        full_description = getattr(item, 'Description', '')

        # Parse the structured HTML template into individual sections
        sections = extract_all_sections_from_ebay_description(full_description)

        # Fall back to legacy extraction if structured parsing found nothing
        description = sections.get('description', '')
        condition_details = sections.get('condition', '')
        if not description and full_description:
            description = extract_ebay_description_section(full_description)
        if not condition_details and full_description:
            condition_details = extract_ebay_condition_section(full_description)

        return jsonify({
            'success': True,
            'description': description,
            'condition_details': condition_details,
            'photos_details': sections.get('photos', ''),
            'shipping_details': sections.get('shipping', ''),
            'signoff': sections.get('signoff', ''),
            'itemId': item_id
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching description for item {item_id}: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e),
            'description': ''
        }), 500
