"""Comic data model."""
from dataclasses import dataclass, field
from typing import List, Optional
from app.utils.whatnot_validators import WHATNOT_FIELD_NAMES, METADATA_FIELD_NAMES

# Shorthand reference to Whatnot field names for cleaner code
FN = WHATNOT_FIELD_NAMES


@dataclass
class Comic:
    """
    Data model representing a comic book listing item.

    This class encapsulates all data about a single comic book, including
    marketplace-specific fields for Whatnot and eBay. It provides methods
    to serialize/deserialize to CSV format and validate data integrity.

    The model maintains both required and optional fields, with special
    handling for image URLs (up to 8) and marketplace-specific extensions
    like eBay item IDs.
    """
    sku: str
    title: str
    description: str
    quantity: int
    price: float
    category: str
    sub_category: str
    shipping_profile: str
    offerable: str
    hazmat: str
    condition: str
    comic_type: str = 'Buy it Now'
    condition_details: str = ''
    photos_details: str = ''
    shipping_details: str = ''
    signoff: str = ''
    cost_per_item: float = 0.0
    listing_type: str = 'For Sale'  # 'For Sale' or 'Giveaway'
    image_urls: List[str] = field(default_factory=list)
    extra_fields: dict = field(default_factory=dict)  # Store additional CSV columns
    ebay_item_id: Optional[str] = ''
    whatnot_item_id: Optional[str] = ''
    ebay_allow_offers: str = 'TRUE'  # Default enabled
    ebay_offer_min: Optional[str] = ''  # Minimum offer price
    ebay_offer_max: Optional[str] = ''  # Auto-accept price

    def to_dict(self):
        """
        Convert the Comic instance to a dictionary suitable for CSV export.

        The returned dictionary uses Whatnot CSV column names as keys and includes
        all standard comic fields plus image URLs. Price and cost fields are rounded
        up to the nearest dollar as required by Whatnot. Extra fields from the
        original import are preserved and included in the output.

        Returns:
            dict: A dictionary mapping Whatnot CSV headers to comic field values.
        """
        # Round price and cost to nearest dollar (ceiling) for Whatnot export
        import math
        price_rounded = math.ceil(self.price)
        cost_rounded = math.ceil(self.cost_per_item)

        # Start with extra fields (metadata like added_by, date_added, etc.)
        # These take lower priority and will be overridden by standard fields
        data = dict(self.extra_fields)

        # Add all standard comic fields using Whatnot column names
        # These override any extra fields with the same names
        data.update({
            FN['SKU']: self.sku,
            FN['TITLE']: self.title,
            FN['DESCRIPTION']: self.description,
            FN['QUANTITY']: str(self.quantity),
            FN['PRICE']: str(price_rounded),  # Whole dollar only
            FN['COST_PER_ITEM']: str(cost_rounded),  # Whole dollar only
            FN['CATEGORY']: self.category,
            FN['SUB_CATEGORY']: self.sub_category,
            FN['SHIPPING_PROFILE']: self.shipping_profile,
            FN['OFFERABLE']: self.offerable,
            FN['HAZMAT']: self.hazmat,
            FN['CONDITION']: self.condition,
            FN['CONDITION_DETAILS']: self.condition_details,
            FN['PHOTOS_DETAILS']: self.photos_details,
            FN['SHIPPING_DETAILS']: self.shipping_details,
            FN['SIGNOFF']: self.signoff,
            FN['TYPE']: self.comic_type,
            FN['LISTING_TYPE']: self.listing_type,
        })

        # Populate up to 8 image URL fields
        for i in range(1, 9):
            field_key = f'IMAGE_URL_{i}'
            if i <= len(self.image_urls):
                data[FN[field_key]] = self.image_urls[i-1]
            else:
                data[FN[field_key]] = ''

        # Add eBay item ID if present
        data[METADATA_FIELD_NAMES['EBAY_ITEM_ID']] = self.ebay_item_id or ''

        # Add WhatNot item ID if present
        data[METADATA_FIELD_NAMES['WHATNOT_ITEM_ID']] = self.whatnot_item_id or ''

        # Add eBay offer settings
        data[METADATA_FIELD_NAMES['EBAY_ALLOW_OFFERS']] = self.ebay_allow_offers or 'TRUE'
        data[METADATA_FIELD_NAMES['EBAY_OFFER_MIN']] = self.ebay_offer_min or ''
        data[METADATA_FIELD_NAMES['EBAY_OFFER_MAX']] = self.ebay_offer_max or ''

        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Comic':
        """
        Create a Comic instance from a dictionary of data.

        Handles multiple input formats seamlessly:
        - CSV exports with Whatnot column names
        - Web form submissions with various field name casings
        - Legacy formats for backwards compatibility

        Unknown fields are preserved in the extra_fields dictionary, allowing
        the comic to round-trip through serialization without data loss. Price
        and cost values are normalized to whole numbers.

        Args:
            data (dict): Dictionary containing comic attributes in various formats.

        Returns:
            Comic: A new Comic instance with data extracted from the dictionary.
        """
        # Enumerate all known field names in various formats
        # Includes both CSV column names (uppercase) and form field variations
        known_fields = {
            # Standard Whatnot CSV column names (proper case)
            FN['SKU'], FN['TITLE'], FN['DESCRIPTION'], FN['QUANTITY'],
            FN['PRICE'], FN['COST_PER_ITEM'], FN['CATEGORY'], FN['SUB_CATEGORY'],
            FN['SHIPPING_PROFILE'], FN['OFFERABLE'], FN['HAZMAT'], FN['CONDITION'],
            FN['CONDITION_DETAILS'], FN['PHOTOS_DETAILS'], FN['SHIPPING_DETAILS'], FN['SIGNOFF'],
            FN['TYPE'], FN['LISTING_TYPE'],
            FN['IMAGE_URL_1'], FN['IMAGE_URL_2'], FN['IMAGE_URL_3'], FN['IMAGE_URL_4'],
            FN['IMAGE_URL_5'], FN['IMAGE_URL_6'], FN['IMAGE_URL_7'], FN['IMAGE_URL_8'],
            'image_urls', METADATA_FIELD_NAMES['EBAY_ITEM_ID'], METADATA_FIELD_NAMES['WHATNOT_ITEM_ID'],
            METADATA_FIELD_NAMES['EBAY_ALLOW_OFFERS'], METADATA_FIELD_NAMES['EBAY_OFFER_MIN'],
            METADATA_FIELD_NAMES['EBAY_OFFER_MAX'],
            # Form field names (lowercase/mixed case variations)
            'sku', 'title', 'description', 'quantity', 'price', 'cost_per_item',
            'category', 'subCategory', 'sub_category', 'shippingProfile', 'shipping_profile',
            'offerable', 'hazmat', 'condition', 'type', 'listingType', 'listing_type',
            'condition_details', 'conditionDetails', 'photos_details', 'photosDetails',
            'shipping_details', 'shippingDetails', 'signoff',
            'Type', 'Price', 'Title', 'Description', 'Quantity', 'Category', 'SubCategory',
            'ShippingProfile', 'Offerable', 'Hazmat', 'Condition', 'Cost Per Item',
            'Condition Details', 'Photos Details', 'Shipping Details', 'Signoff',
            'Listing Type', 'image_url_1', 'image_url_2', 'image_url_3', 'image_url_4',
            'image_url_5', 'image_url_6', 'image_url_7', 'image_url_8',
            'ebayAllowOffers', 'ebayOfferMin', 'ebayOfferMax'
        }

        # Extract fields that aren't recognized as standard comic fields
        # These are preserved for round-trip serialization
        # Filter out camelCase form fields and admin defaults that shouldn't go in CSV
        fields_to_filter = [
            # camelCase eBay form fields
            'ebayListingMode', 'ebayScheduleDate', 'ebayAction', 'ebayCondition',
            'ebayCategory', 'ebayShippingProfile', 'ebayBestOfferAutoAccept',
            'ebayMinBestOffer', 'ebayBestOfferEnabled', 'ebayAllowOffers',
            'ebayOfferMin', 'ebayOfferMax',
            # Admin default fields (configuration, not comic properties)
            'EbayLocation', 'EbayPostalCode', 'EbayCategoryName', 'EbayReturnsAccepted',
            'EbayReturnProfile', 'EbayPaymentProfile', 'EbayCategoryId', 'EbayDuration',
            'EbayFormat', 'Price_BuyItNow', 'EbayImmediatePay', 'Price_Auction',
            'EbayListingMode', 'EbayFutureDays', 'EbayWeightMajor', 'EbayWeightMinor',
            'EbayPackageDepth', 'EbayPackageLength', 'EbayPackageWidth',
            'EbayShippingProfile'
        ]
        extra_fields = {k: v for k, v in data.items()
                       if k not in known_fields and k not in fields_to_filter}


        # Extract image URLs - try multiple input formats
        # Use 'image_urls' key if explicitly provided (even if empty list)
        if 'image_urls' in data:
            image_urls = data.get('image_urls', [])
            # Ensure it's a list
            if not isinstance(image_urls, list):
                image_urls = []
        else:
            # Fallback: look for individual Image URL fields in the data
            image_urls = []
            for i in range(1, 9):
                url = data.get(FN[f'IMAGE_URL_{i}'], '')
                if url and isinstance(url, str):
                    url = url.strip()
                    if url:
                        image_urls.append(url)

        # Parse price: remove currency symbols, whitespace, and commas, then normalize
        import math
        price_str = data.get(FN['PRICE']) or data.get('price') or data.get('Price') or '0'
        if isinstance(price_str, str):
            price_str = price_str.replace('$', '').replace(',', '').strip()

        try:
            price_float = float(price_str) if price_str else 0.0
            # Round up to nearest dollar
            price = max(1, math.ceil(price_float))
        except (ValueError, TypeError):
            # If price can't be parsed, log a warning and default to 1
            import logging
            logger = logging.getLogger(__name__)
            sku_val = data.get(FN['SKU']) or data.get('sku') or 'unknown'
            logger.warning(f"Could not parse price '{price_str}' for SKU {sku_val}, defaulting to $1")
            price = 1

        # Parse cost per item
        cost_str = data.get(FN['COST_PER_ITEM']) or data.get('cost_per_item') or data.get('Cost Per Item') or '0'
        if isinstance(cost_str, str):
            cost_str = cost_str.replace('$', '').replace(',', '').strip()

        try:
            cost_float = float(cost_str) if cost_str else 0.0
            cost_per_item = math.ceil(cost_float)
        except (ValueError, TypeError):
            # If cost can't be parsed, default to 0
            cost_per_item = 0

        comic_type = data.get(FN['TYPE']) or data.get('type') or data.get('Type') or ''
        listing_type = data.get(FN['LISTING_TYPE']) or data.get('listing_type') or data.get('Listing Type') or 'For Sale'  # Default to 'For Sale' for existing comics

        raw_item_id = data.get(METADATA_FIELD_NAMES['EBAY_ITEM_ID'], '')
        ebay_item_id = raw_item_id.strip() if isinstance(raw_item_id, str) else ''

        raw_whatnot_id = data.get(METADATA_FIELD_NAMES['WHATNOT_ITEM_ID'], '')
        whatnot_item_id = raw_whatnot_id.strip() if isinstance(raw_whatnot_id, str) else ''

        # Extract eBay offer settings with defaults
        ebay_allow_offers = data.get(METADATA_FIELD_NAMES['EBAY_ALLOW_OFFERS']) or data.get('ebayAllowOffers') or 'TRUE'
        ebay_offer_min = data.get(METADATA_FIELD_NAMES['EBAY_OFFER_MIN']) or data.get('ebayOfferMin') or ''
        ebay_offer_max = data.get(METADATA_FIELD_NAMES['EBAY_OFFER_MAX']) or data.get('ebayOfferMax') or ''

        # Ensure string type for offer prices
        if ebay_offer_min and not isinstance(ebay_offer_min, str):
            ebay_offer_min = str(ebay_offer_min)
        if ebay_offer_max and not isinstance(ebay_offer_max, str):
            ebay_offer_max = str(ebay_offer_max)

        # Helper function to get field from either CSV format (uppercase) or form format (lowercase/mixed case)
        def get_field(field_name):
            """Try CSV column name first, then try lowercase, then title case variations."""
            value = data.get(FN[field_name])
            if value is not None and value != '':
                return value
            # Try lowercase version for form data
            lowercase_name = FN[field_name].lower()
            value = data.get(lowercase_name)
            if value is not None and value != '':
                return value
            # Try title case without spaces (e.g., 'SubCategory')
            no_space = FN[field_name].replace(' ', '')
            value = data.get(no_space)
            if value is not None and value != '':
                return value
            return ''

        # Parse quantity safely (CSV corruption can put non-numeric values here)
        try:
            quantity = int(get_field('QUANTITY') or data.get('quantity', 0))
        except (ValueError, TypeError):
            quantity = 0

        return cls(
            sku=get_field('SKU') or data.get('sku', ''),
            title=get_field('TITLE') or data.get('title', ''),
            description=get_field('DESCRIPTION') or data.get('description', ''),
            quantity=quantity,
            price=price,
            category=get_field('CATEGORY') or data.get('category', ''),
            sub_category=get_field('SUB_CATEGORY') or data.get('subCategory', '') or data.get('sub_category', ''),
            shipping_profile=get_field('SHIPPING_PROFILE') or data.get('shippingProfile', '') or data.get('shipping_profile', ''),
            offerable=get_field('OFFERABLE') or data.get('offerable', ''),
            hazmat=get_field('HAZMAT') or data.get('hazmat', ''),
            condition=get_field('CONDITION') or data.get('condition', ''),
            condition_details=get_field('CONDITION_DETAILS') or data.get('conditionDetails', '') or data.get('condition_details', ''),
            photos_details=get_field('PHOTOS_DETAILS') or data.get('photosDetails', '') or data.get('photos_details', ''),
            shipping_details=get_field('SHIPPING_DETAILS') or data.get('shippingDetails', '') or data.get('shipping_details', ''),
            signoff=get_field('SIGNOFF') or data.get('signoff', ''),
            comic_type=comic_type,
            cost_per_item=cost_per_item,
            listing_type=listing_type,
            image_urls=image_urls,
            extra_fields=extra_fields,
            ebay_item_id=ebay_item_id,
            whatnot_item_id=whatnot_item_id,
            ebay_allow_offers=ebay_allow_offers,
            ebay_offer_min=ebay_offer_min,
            ebay_offer_max=ebay_offer_max
        )
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """
        Validate the Comic data for required fields and logical constraints.

        Checks that all essential fields are present and contain valid values:
        - Title and description are not empty
        - Quantity is at least 1
        - Price is at least $1 and is a whole dollar amount

        Note: Category and Sub Category are no longer required as they are
        marketplace-specific fields that have defaults configured by the admin.

        Returns:
            tuple: (success_bool, error_message_or_none)
                   Returns (True, None) if valid, or (False, error_text) if invalid.
        """
        if not self.title:
            return False, "Title is required"
        if not self.description:
            return False, "Description is required"
        if self.quantity < 1:
            return False, "Quantity must be at least 1"
        if self.price < 1:
            return False, "Price must be at least $1"
        if self.price != int(self.price):
            return False, "Price must be a whole dollar amount (no cents)"
        # Note: category and sub_category are optional as they are marketplace-specific
        # and have default values configured in admin settings
        return True, None
