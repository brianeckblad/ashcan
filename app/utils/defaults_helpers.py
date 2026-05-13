"""Helper functions for API routes - user preferences and defaults."""
from flask import session, current_app
from pathlib import Path
import json
from app.models.user import user_manager


def get_user_preferences():
    """
    Get preferences for the currently logged-in user.

    Returns:
        dict: User preferences or empty dict if no user logged in
    """
    username = session.get('username')
    if not username:
        return {}
    return user_manager.get_preferences(username) or {}


def get_app_defaults():
    """
    Load app defaults from file or return built-in defaults.

    Returns:
        dict: Application default values for comic fields
    """
    try:
        defaults_file = Path(current_app.instance_path) / 'app_defaults.json'
        if defaults_file.exists():
            with open(defaults_file, 'r') as f:
                loaded_defaults = json.load(f)
                # Normalize field names for backwards compatibility
                normalized = {}
                field_mappings = {
                    'SubCategory': 'Sub Category',
                    'ShippingProfile': 'Shipping Profile',
                    'PriceBuyItNow': 'Price_BuyItNow',
                    'PriceAuction': 'Price_Auction',
                }
                for key, value in loaded_defaults.items():
                    # Map old names to new names
                    normalized_key = field_mappings.get(key, key)
                    normalized[normalized_key] = value
                return normalized
    except Exception as e:
        current_app.logger.warning(f"Error loading app defaults: {e}")

    # Built-in defaults
    return {
        # WhatNot defaults
        'Type': 'Buy it Now',
        'Price_BuyItNow': '',
        'Price_Auction': '',
        'Category': 'Comics & Manga',
        'Sub Category': 'Modern Comics',
        'Shipping Profile': 'Dynamic (Gemeni Mailer)',
        'Offerable': 'TRUE',
        'Hazmat': 'Not Hazmat',
        'Condition': 'Near Mint',
        'AuctionStartingPrice': '',
        # eBay listing defaults
        'EbayListingMode': 'future',  # Default to 'List in 18 days'
        'EbayFutureDays': '18',
        # eBay item-specific defaults
        'EbayCategoryId': '259104',
        'EbayCategoryName': '',
        'EbayFormat': 'FixedPrice',
        'EbayDuration': 'GTC',
        'EbayWeightMajor': '1',
        'EbayWeightMinor': '0',
        'EbayImmediatePay': 'FALSE',
        # eBay package/location defaults
        'EbayPackageDepth': '2',
        'EbayPackageLength': '13',
        'EbayPackageWidth': '9',
        'EbayLocation': 'Highlands Ranch, CO',
        'EbayPostalCode': '80129',
        # eBay profile defaults
        'EbayPaymentProfile': '261505403015',
        'EbayReturnProfile': '261505402015',
        'EbayShippingProfile': '279875255015',
    }


def apply_defaults_to_comic_data(data, is_new_comic=True):
    """
    Apply admin defaults to comic data for any missing required fields.

    This ensures all marketplace-required fields have values even if the
    frontend doesn't send them (e.g., when they're in collapsed settings tabs).

    IMPORTANT: Only applies defaults for NEW comics. When editing existing comics,
    we preserve whatever values are already in the CSV - we don't overwrite with
    defaults unless the field is completely missing from the submission.

    Args:
        data (dict): Comic data from request
        is_new_comic (bool): True if this is a new comic being added

    Returns:
        dict: Comic data with defaults applied for missing fields
    """
    defaults = get_app_defaults()

    if is_new_comic:
        # For new comics: Apply defaults for any missing field
        for field, default_value in defaults.items():
            if field not in data or data[field] in ('', None):
                data[field] = default_value
    else:
        # For existing comics: Only fill in fields that are truly missing
        # (not sent by frontend at all). This preserves existing values.
        # The frontend sends all fields it knows about, even if empty.
        # So if a field is missing from `data`, it means the frontend
        # doesn't know about it (new field added to defaults).
        for field, default_value in defaults.items():
            if field not in data:
                data[field] = default_value

    return data
