"""eBay data validation utilities."""
from datetime import datetime, timedelta, timezone
import os
import re

# ============================================================================
# EBAY FIELD NAMES - Change these to rename columns in CSV/exports
# ============================================================================
EBAY_FIELD_NAMES = {
    'ACTION': '*Action(SiteID=US|Country=US|Currency=USD|Version=1193)',
    'CUSTOM_LABEL_SKU': 'Custom Label (SKU)',
    'CATEGORY_ID': 'Category ID',
    'TRACKINGID': 'TrackingId (Do Not Change)',
    'CATEGORY_NAME': 'Category Name',
    'TITLE': 'Title',
    'ORIGINAL_ROW_NUMBER': 'Original Row Number',
    'SCHEDULE_TIME': 'Schedule Time',
    'P_EPID': 'P:EPID',
    'START_PRICE': 'Start price',
    'QUANTITY': 'Quantity',
    'ITEM_PHOTO_URL': 'Item photo URL',
    'VIDEOID': 'VideoID',
    'CONDITION_ID': 'Condition ID',
    'DESCRIPTION': 'Description',
    'FORMAT': 'Format',
    'DURATION': 'Duration',
    'BUY_IT_NOW_PRICE': 'Buy It Now price',
    'BEST_OFFER_ENABLED': 'Best Offer Enabled',
    'BEST_OFFER_AUTO_ACCEPT_PRICE': 'Best Offer Auto Accept Price',
    'MINIMUM_BEST_OFFER_PRICE': 'Minimum Best Offer Price',
    'IMMEDIATE_PAY_REQUIRED': 'Immediate pay required',
    'LOCATION': 'Location',
    'POSTALCODE': 'PostalCode',
    'WEIGHTMAJOR': 'WeightMajor',
    'WEIGHTMINOR': 'WeightMinor',
    'PACKAGELENGTH': 'PackageLength',
    'PACKAGEWIDTH': 'PackageWidth',
    'PACKAGEDEPTH': 'PackageDepth',
    'SHIPPING_SERVICE_1_OPTION': 'Shipping service 1 option',
    'SHIPPING_SERVICE_1_COST': 'Shipping service 1 cost',
    'SHIPPING_SERVICE_1_PRIORITY': 'Shipping service 1 priority',
    'SHIPPING_SERVICE_2_OPTION': 'Shipping service 2 option',
    'SHIPPING_SERVICE_2_COST': 'Shipping service 2 cost',
    'SHIPPING_SERVICE_2_PRIORITY': 'Shipping service 2 priority',
    'MAX_DISPATCH_TIME': 'Max dispatch time',
    'RETURNS_ACCEPTED_OPTION': 'Returns accepted option',
    'RETURNS_WITHIN_OPTION': 'Returns within option',
    'REFUND_OPTION': 'Refund option',
    'RETURN_SHIPPING_COST_PAID_BY': 'Return shipping cost paid by',
    'SHIPPING_PROFILE_NAME': 'Shipping profile name',
    'RETURN_PROFILE_NAME': 'Return profile name',
    'PAYMENT_PROFILE_NAME': 'Payment profile name',
    'C_SERIES_TITLE': 'C:Series Title',
    'C_CHARACTER': 'C:Character',
    'C_GENRE': 'C:Genre',
    'C_ARTIST_WRITER': 'C:Artist/Writer',
    'C_PUBLISHER': 'C:Publisher',
    'C_SUPERHERO_TEAM': 'C:Superhero Team',
    'C_PUBLICATION_YEAR': 'C:Publication Year',
    'C_FORMAT': 'C:Format',
    'C_ERA': 'C:Era',
    'C_TYPE': 'C:Type',
    'C_GRADE': 'C:Grade',
    'C_PROFESSIONAL_GRADER': 'C:Professional Grader',
    'C_TRADITION': 'C:Tradition',
    'C_CERTIFICATION_NUMBER': 'C:Certification Number',
    'C_UNIVERSE': 'C:Universe',
    'C_FEATURES': 'C:Features',
    'C_COVER_ARTIST': 'C:Cover Artist',
    'C_SIGNED_BY': 'C:Signed By',
    'C_UNIT_OF_SALE': 'C:Unit of Sale',
    'C_SIGNED': 'C:Signed',
    'C_INSCRIBED': 'C:Inscribed',
    'C_PERSONALIZED': 'C:Personalized',
    'C_VINTAGE': 'C:Vintage',
    'C_STORY_TITLE': 'C:Story Title',
    'C_STYLE': 'C:Style',
    'C_VARIANT_TYPE': 'C:Variant Type',
    'C_LANGUAGE': 'C:Language',
    'C_COUNTRY_OF_ORIGIN': 'C:Country of Origin',
    'C_CONVENTION_EVENT': 'C:Convention/Event',
    'C_AUTOGRAPH_AUTHENTICATION': 'C:Autograph Authentication',
    'C_INTENDED_AUDIENCE': 'C:Intended Audience',
    'C_AUTOGRAPH_AUTHENTICATION_NUMBER': 'C:Autograph Authentication Number',
    'C_CALIFORNIA_PROP_65_WARNING': 'C:California Prop 65 Warning',
    'C_ISSUE_NUMBER': 'C:Issue Number',
    'C_UPC': 'C:UPC',
    'C_UNIT_QUANTITY': 'C:Unit Quantity',
    'C_UNIT_TYPE': 'C:Unit Type',
}

# Field mapping from internal item data to eBay fields (uses EBAY_FIELD_NAMES)
EBAY_FIELD_MAPPING = {
    EBAY_FIELD_NAMES['CUSTOM_LABEL_SKU']: 'sku',
    EBAY_FIELD_NAMES['TITLE']: 'title',
    EBAY_FIELD_NAMES['START_PRICE']: 'price',
    EBAY_FIELD_NAMES['QUANTITY']: 'quantity',
    EBAY_FIELD_NAMES['ITEM_PHOTO_URL']: 'image_urls',
    EBAY_FIELD_NAMES['CONDITION_ID']: 'condition',
    EBAY_FIELD_NAMES['DESCRIPTION']: 'description'
}

# Condition mapping: Internal condition names -> eBay Condition IDs
CONDITION_MAPPING = {
    'Graded': '2750-Graded',
    'Gem Mint': '2750-Like New',
    'Mint': '2750-Like New',
    'Near Mint': '2750-Like New',
    'Very Fine': '2750-Like New',
    'Fine': '4000-Very Good',
    'Very Good': '4000-Very Good',
    'Good': '5000-Good',
    'Fair': '6000-Acceptable',
    'Poor': '6000-Acceptable'
}

# eBay field validation rules (generated from excel_fields_and_dropdowns.csv)
EBAY_FIELD_VALIDATION = {
    EBAY_FIELD_NAMES['ACTION']: {
        'required': True,
        'allowed_values': ['Add', 'Revise', 'Relist', 'End', 'Delete'],
        'default': 'Add'
    },

    EBAY_FIELD_NAMES['CUSTOM_LABEL_SKU']: {
        'required': False,
        'not_blank': False,
        'auto_populate': True,  # Auto-populate from item.sku
        'source_field': 'sku'
    },

    EBAY_FIELD_NAMES['CATEGORY_ID']: {
        'required': False,
        'type': 'integer',
        'default': '259104'
    },

    EBAY_FIELD_NAMES['TRACKINGID']: {
        'required': False
    },

    EBAY_FIELD_NAMES['CATEGORY_NAME']: {
        'required': True,
        'default': '/Collectibles/Comic Books & Memorabilia/Comics/Comics & Graphic Novels'
    },

    EBAY_FIELD_NAMES['TITLE']: {
        'required': True,  # May be required depending on action
        'not_blank': False,
        'max_length': 80,
        'auto_populate': True,  # Auto-populate from item.title
        'source_field': 'title'
    },

    EBAY_FIELD_NAMES['ORIGINAL_ROW_NUMBER']: {
        'required': False
    },

    EBAY_FIELD_NAMES['SCHEDULE_TIME']: {
        'required': False,
        'auto_populate': True,
        'source_field': '_schedule_time'  # Will be calculated as 2 weeks from now
    },

    EBAY_FIELD_NAMES['P_EPID']: {
        'required': False
    },

    EBAY_FIELD_NAMES['START_PRICE']: {
        'required': True,
        'type': 'currency',
        'auto_populate': True,  # Auto-populate from item.price
        'source_field': 'price'
    },

    EBAY_FIELD_NAMES['QUANTITY']: {
        'required': False,
        'type': 'integer',
        'default': '1',
        'auto_populate': True,  # Auto-populate from item.quantity
        'source_field': 'quantity'
    },

    EBAY_FIELD_NAMES['ITEM_PHOTO_URL']: {
        'required': False,
        'auto_populate': True,  # Auto-populate from item.image_urls (comma-separated list)
        'source_field': 'image_urls',
        'is_list': True  # Indicates this field accepts multiple URLs
    },

    EBAY_FIELD_NAMES['VIDEOID']: {
        'required': False
    },

    EBAY_FIELD_NAMES['CONDITION_ID']: {
        'required': True,
        'allowed_values': [
            '1000-Brand New',
            '1000-New',
            '2750-Graded',
            '2750-Like New',
            '3000-Used',
            '4000-Ungraded',
            '4000-Very Good',
            '5000-Good',
            '6000-Acceptable'
        ],
        'auto_populate': True,  # Auto-populate from item.condition (needs mapping)
        'source_field': 'condition',
        'requires_mapping': True  # Use CONDITION_MAPPING to convert
    },

    EBAY_FIELD_NAMES['DESCRIPTION']: {
        'required': True,
        'not_blank': False,
        'auto_populate': True,
        'source_field': '_description_html'  # Will be generated from title and description
    },
    EBAY_FIELD_NAMES['FORMAT']: {
        'required': True,
        'allowed_values': ['Auction', 'FixedPrice', 'StoresFixedPrice'],
        'default': 'FixedPrice',

    },
    EBAY_FIELD_NAMES['DURATION']: {
        'required': True,
        'allowed_values': ['Days_1', 'Days_3', 'Days_5', 'Days_7', 'Days_10', 'Days_30', 'GTC'],
        'default': 'GTC',
    },

    EBAY_FIELD_NAMES['BUY_IT_NOW_PRICE']: {
        'required': False,
        'type': 'currency',
        # 'auto_populate': True,  # Auto-populate from item.price
        # 'source_field': 'price'
    },

    EBAY_FIELD_NAMES['BEST_OFFER_ENABLED']: {
        'required': False,
        'allowed_values': ['TRUE', 'FALSE'],
        'default': 'TRUE',
    },

    EBAY_FIELD_NAMES['BEST_OFFER_AUTO_ACCEPT_PRICE']: {
        'required': False,
        'type': 'currency'
    },

    EBAY_FIELD_NAMES['MINIMUM_BEST_OFFER_PRICE']: {
        'required': False,
        'type': 'currency'
    },

    EBAY_FIELD_NAMES['IMMEDIATE_PAY_REQUIRED']: {
        'required': False,
        'allowed_values': ['TRUE', 'FALSE'],
        'default': 'TRUE'
    },

    EBAY_FIELD_NAMES['LOCATION']: {
        'required': True,
        'default': 'Highlands Ranch, CO'  # City, State format (NOT postal code)
    },

    EBAY_FIELD_NAMES['POSTALCODE']: {
        'required': False,
        'default': '80129'  # 5-digit postal code
    },

    EBAY_FIELD_NAMES['WEIGHTMAJOR']: {
        'required': False,
        'type': 'integer',
        'default': '1'  # Pounds (for English measurement system)
    },

    EBAY_FIELD_NAMES['WEIGHTMINOR']: {
        'required': False,
        'type': 'integer',
        'default': '0'  # Ounces (for English measurement system)
    },

    EBAY_FIELD_NAMES['PACKAGELENGTH']: {
        'required': False,
        'type': 'integer',
        'default': '13'  # Inches - typical comic book mailer length
    },

    EBAY_FIELD_NAMES['PACKAGEWIDTH']: {
        'required': False,
        'type': 'integer',
        'default': '9'  # Inches - typical comic book mailer width
    },

    EBAY_FIELD_NAMES['PACKAGEDEPTH']: {
        'required': False,
        'type': 'integer',
        'default': '2'  # Inches - typical comic book mailer depth
    },

    EBAY_FIELD_NAMES['SHIPPING_SERVICE_1_OPTION']: {
        'required': False
    },

    EBAY_FIELD_NAMES['SHIPPING_SERVICE_1_COST']: {
        'required': False,
        'type': 'currency'
    },

    EBAY_FIELD_NAMES['SHIPPING_SERVICE_1_PRIORITY']: {
        'required': False,
        'type': 'integer'
    },

    EBAY_FIELD_NAMES['SHIPPING_SERVICE_2_OPTION']: {
        'required': False
    },

    EBAY_FIELD_NAMES['SHIPPING_SERVICE_2_COST']: {
        'required': False,
        'type': 'currency'
    },

    EBAY_FIELD_NAMES['SHIPPING_SERVICE_2_PRIORITY']: {
        'required': False,
        'type': 'integer'
    },

    EBAY_FIELD_NAMES['MAX_DISPATCH_TIME']: {
        'required': False,
        'type': 'integer'
    },

    EBAY_FIELD_NAMES['RETURNS_ACCEPTED_OPTION']: {
        'required': True,
        'allowed_values': ['ReturnsAccepted', 'ReturnsNotAccepted'],
        'default': 'ReturnsNotAccepted'
    },

    EBAY_FIELD_NAMES['RETURNS_WITHIN_OPTION']: {
        'required': False,
        'allowed_values': ['Days_14', 'Days_30', 'Days_60']
    },

    EBAY_FIELD_NAMES['REFUND_OPTION']: {
        'required': False,
        'allowed_values': ['MoneyBack', 'MoneyBackOrReplacement']
    },

    EBAY_FIELD_NAMES['RETURN_SHIPPING_COST_PAID_BY']: {
        'required': False,
        'allowed_values': ['Buyer', 'Seller']
    },

    EBAY_FIELD_NAMES['SHIPPING_PROFILE_NAME']: {
        'required': True,
        'allowed_values': [
            'Calculated Shipping GA - (ID: 279875255015)',
            'Free Shipping - (ID: 279535304015)',
            'Calculated: USPSParcel , 2 business days (280768277015) - (ID: 280768277015)',
            'USPS Comic Fixed Price $5.99 - (ID: 261505401015)'
        ],
        'default': 'Calculated Shipping GA - (ID: 279875255015)'
    },

    EBAY_FIELD_NAMES['RETURN_PROFILE_NAME']: {
        'required': True,
        'allowed_values': [
            'No Return Accepted (261505402015) - (ID: 261505402015)'
        ],
        'default': 'No Return Accepted (261505402015) - (ID: 261505402015)'
    },

    EBAY_FIELD_NAMES['PAYMENT_PROFILE_NAME']: {
        'required': True,
        'allowed_values': [
            'eBay Managed Payments - (ID: 261505403015)'
        ],
        'default': 'eBay Managed Payments - (ID: 261505403015)'
    },

    # Category-Specific (C:) fields - optional, may be populated from eBay imports
    EBAY_FIELD_NAMES['C_SERIES_TITLE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_CHARACTER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_GENRE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_ARTIST_WRITER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_PUBLISHER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_SUPERHERO_TEAM']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_PUBLICATION_YEAR']: {
        'required': False,
        'type': 'integer'
    },
    EBAY_FIELD_NAMES['C_FORMAT']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_ERA']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_TYPE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_GRADE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_PROFESSIONAL_GRADER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_TRADITION']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_CERTIFICATION_NUMBER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_UNIVERSE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_FEATURES']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_COVER_ARTIST']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_SIGNED_BY']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_UNIT_OF_SALE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_SIGNED']: {
        'required': False,
        'allowed_values': ['Yes', 'No']
    },
    EBAY_FIELD_NAMES['C_INSCRIBED']: {
        'required': False,
        'allowed_values': ['Yes', 'No']
    },
    EBAY_FIELD_NAMES['C_PERSONALIZED']: {
        'required': False,
        'allowed_values': ['Yes', 'No']
    },
    EBAY_FIELD_NAMES['C_VINTAGE']: {
        'required': False,
        'allowed_values': ['Yes', 'No']
    },
    EBAY_FIELD_NAMES['C_STORY_TITLE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_STYLE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_VARIANT_TYPE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_LANGUAGE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_COUNTRY_OF_ORIGIN']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_CONVENTION_EVENT']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_AUTOGRAPH_AUTHENTICATION']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_INTENDED_AUDIENCE']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_AUTOGRAPH_AUTHENTICATION_NUMBER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_CALIFORNIA_PROP_65_WARNING']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_ISSUE_NUMBER']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_UPC']: {
        'required': False
    },
    EBAY_FIELD_NAMES['C_UNIT_QUANTITY']: {
        'required': False,
        'type': 'integer'
    },
    EBAY_FIELD_NAMES['C_UNIT_TYPE']: {
        'required': False
    },
    # Product Safety and Manufacturer fields (EU/UK compliance - may not be supported for US-only accounts)
    # Commented out to avoid schema errors - uncomment if your eBay account supports these fields
    # 'Product Safety Pictograms': {
    #     'required': False
    # },
    # 'Product Safety Statements': {
    #     'required': False
    # },
    # 'Product Safety Component': {
    #     'required': False
    # },
    # 'Regulatory Document Ids': {
    #     'required': False
    # },
    # 'Manufacturer Name': {
    #     'required': False
    # },
    # 'Manufacturer AddressLine1': {
    #     'required': False
    # },
    # 'Manufacturer AddressLine2': {
    #     'required': False
    # },
    # 'Manufacturer City': {
    #     'required': False
    # },
    # 'Manufacturer Country': {
    #     'required': False
    # },
    # 'Manufacturer PostalCode': {
    #     'required': False
    # },
    # 'Manufacturer StateOrProvince': {
    #     'required': False
    # },
    # 'Manufacturer Phone': {
    #     'required': False
    # },
    # 'Manufacturer Email': {
    #     'required': False
    # },
    # 'Manufacturer ContactURL': {
    #     'required': False
    # },
    # 'Responsible Person 1': {
    #     'required': False
    # },
    # 'Responsible Person 1 Type': {
    #     'required': False
    # },
    # 'Responsible Person 1 AddressLine1': {
    #     'required': False
    # },
    # 'Responsible Person 1 AddressLine2': {
    #     'required': False
    # },
    # 'Responsible Person 1 City': {
    #     'required': False
    # },
    # 'Responsible Person 1 Country': {
    #     'required': False
    # },
    # 'Responsible Person 1 PostalCode': {
    #     'required': False
    # },
    # 'Responsible Person 1 StateOrProvince': {
    #     'required': False
    # },
    # 'Responsible Person 1 Phone': {
    #     'required': False
    # },
    # 'Responsible Person 1 Email': {
    #     'required': False
    # },
    # 'Responsible Person 1 ContactURL': {
    #     'required': False
    # }
}


def validate_ebay_data(data):
    """
    Validate data against eBay field rules.

    Args:
        data: Dictionary containing data with field names as keys

    Returns:
        tuple: (is_valid, list of error messages)
    """
    errors = []

    for field_name, rules in EBAY_FIELD_VALIDATION.items():
        value = data.get(field_name, '').strip() if isinstance(data.get(field_name), str) else str(data.get(field_name, ''))

        # Check if required and no value and no default
        if rules.get('required') and not value:
            if 'default' not in rules:
                errors.append(f"{field_name} is required")
                continue

        # Check if not blank
        if rules.get('not_blank') and not value:
            if 'default' not in rules:
                errors.append(f"{field_name} cannot be blank")
                continue

        # Check allowed values (only if value is not empty)
        if 'allowed_values' in rules and value:
            if value not in rules['allowed_values']:
                errors.append(f"{field_name} must be one of: {', '.join(rules['allowed_values'][:5])}{'...' if len(rules['allowed_values']) > 5 else ''}")

        # Check type validations (only if value is not empty)
        if 'type' in rules and value:
            if rules['type'] == 'integer':
                try:
                    int(value)
                except ValueError:
                    errors.append(f"{field_name} must be an integer")
            elif rules['type'] == 'currency':
                try:
                    # Remove currency symbols and validate
                    float(value.replace('$', '').replace(',', ''))
                except ValueError:
                    errors.append(f"{field_name} must be a valid dollar amount")

        # Check max length (only if value is not empty)
        if 'max_length' in rules and value:
            if len(value) > rules['max_length']:
                errors.append(f"{field_name} exceeds maximum length of {rules['max_length']} characters")

    return len(errors) == 0, errors


def get_ebay_field_info(field_name):
    """
    Get validation info for a specific eBay field.

    Args:
        field_name: Name of the field

    Returns:
        dict: Validation rules for the field, or None if not found
    """
    return EBAY_FIELD_VALIDATION.get(field_name)


def get_ebay_dropdown_options(field_name):
    """
    Get dropdown options for a specific eBay field.

    Args:
        field_name: Name of the field

    Returns:
        list: List of allowed values, or None if field has no dropdown
    """
    field_info = get_ebay_field_info(field_name)
    if field_info and 'allowed_values' in field_info:
        return field_info['allowed_values']
    return None


def populate_ebay_fields_from_item(item):
    """
    Auto-populate eBay fields from item data.

    Args:
        item: Item object or dictionary with item data

    Returns:
        dict: Dictionary with eBay field names as keys and populated values
    """
    ebay_data = {}

    for ebay_field, rules in EBAY_FIELD_VALIDATION.items():
        if rules.get('auto_populate') and rules.get('source_field'):
            source_field = rules['source_field']

            # Handle special calculated fields
            if source_field == '_schedule_time':
                # Calculate 2 weeks from now in eBay's required format: YYYY-MM-DD HH:MM:SS
                schedule_time = datetime.now() + timedelta(weeks=2)
                ebay_data[ebay_field] = schedule_time.strftime('%Y-%m-%d %H:%M:%S')
                continue

            if source_field == '_description_html':
                # Generate HTML description from title and description
                if isinstance(item, dict):
                    title = item.get('title', '')
                    description = item.get('description', '')
                    condition_details = item.get('condition_details', '') or item.get('Condition Details', '')
                    photos_details = item.get('photos_details', '') or item.get('Photos Details', '')
                    shipping_details = item.get('shipping_details', '') or item.get('Shipping Details', '')
                    signoff = item.get('signoff', '') or item.get('Signoff', '')
                else:
                    title = getattr(item, 'title', '')
                    description = getattr(item, 'description', '')
                    condition_details = getattr(item, 'condition_details', '')
                    photos_details = getattr(item, 'photos_details', '')
                    shipping_details = getattr(item, 'shipping_details', '')
                    signoff = getattr(item, 'signoff', '')

                # Safety: strip HTML tags from description if old generated HTML
                # leaked into the CSV field (prevents double-nesting the template)
                if description and ('<div>' in description or '<li>' in description
                                    or '<strong>' in description or '<br' in description
                                    or '<p>' in description):
                    import re as _re
                    # Convert block-level and break tags to newlines BEFORE stripping
                    description = _re.sub(r'</?(div|p|br|li|ul|ol)[^>]*/?>', '\n', description, flags=_re.IGNORECASE)
                    # Strip remaining HTML tags
                    description = _re.sub(r'<[^>]+>', '', description)
                    # Collapse multiple blank lines but keep single newlines
                    description = _re.sub(r'\n{3,}', '\n\n', description)
                    description = '\n'.join(line.strip() for line in description.split('\n'))
                    description = description.strip()

                # Parse description into bullet points (split by newlines or periods)
                desc_bullets = []
                if description:
                    # Split by newlines first, then by periods if no newlines
                    lines = description.strip().split('\n')
                    if len(lines) == 1:
                        # Try splitting by periods
                        lines = [s.strip() for s in description.split('.') if s.strip()]
                    desc_bullets = [line.strip() for line in lines if line.strip()]

                # Build description bullet points HTML
                desc_bullets_html = ''.join([f'<li>{bullet}</li>' for bullet in desc_bullets]) if desc_bullets else ''

                # Build condition section HTML - use Condition Details field if available, otherwise use default boilerplate
                if condition_details and condition_details.strip():
                    condition_lines = condition_details.strip().split('\n')
                    condition_bullets = [line.strip() for line in condition_lines if line.strip()]
                    condition_html = ''.join([f'<li>{bullet}</li>' for bullet in condition_bullets])
                else:
                    # Default boilerplate
                    condition_html = '<li>NM – Like New, raw copy, Never Read, Stored Carefully</li><li>Please use the photos to judge condition</li>'

                # Build photos section HTML - use Photos Details field if available, otherwise use default boilerplate
                if photos_details and photos_details.strip():
                    photos_lines = photos_details.strip().split('\n')
                    photos_bullets = [line.strip() for line in photos_lines if line.strip()]
                    photos_html = ''.join([f'<li>{bullet}</li>' for bullet in photos_bullets])
                else:
                    # Default boilerplate
                    photos_html = '<li>Exact book you will recieve is pictured</li>'

                # Build shipping section HTML - use Shipping Details field if available, otherwise use default boilerplate
                if shipping_details and shipping_details.strip():
                    shipping_lines = shipping_details.strip().split('\n')
                    shipping_bullets = [line.strip() for line in shipping_lines if line.strip()]
                    shipping_html = ''.join([f'<li>{bullet}</li>' for bullet in shipping_bullets])
                else:
                    # Default boilerplate
                    shipping_html = '<li>All comics are bagged and boarded</li><li>Securely ships in Gemini Mailer within two business days</li>'

                # Build signoff text - use Signoff field if available, otherwise use default
                if not signoff or not signoff.strip():
                    signoff = 'Thanks for looking, Message with any questions'

                # Load description template from external file (customizable without editing Python)
                # File: app/templates/ebay_description_template.html
                template_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'ebay_description_template.html')
                try:
                    with open(template_path, 'r') as f:
                        html_template = f.read()
                    # Strip HTML comments (<!-- ... -->) so they don't appear in the eBay listing
                    html_template = re.sub(r'<!--.*?-->', '', html_template, flags=re.DOTALL).strip()
                except FileNotFoundError:
                    # Fallback: inline template if file is missing
                    html_template = '<div><div><div><strong>Title</strong></div><div><ul><li>{{title}}</li></ul></div><div><strong>Description</strong></div><div><ul>{{description}}</ul></div><div><strong>Condition</strong></div><div><ul>{{condition}}</ul></div><div><strong>Photos</strong></div><div><ul>{{photos}}</ul></div><div><strong>Shipping</strong></div><div><ul>{{shipping}}</ul></div><div><strong>{{signoff}}</strong></div></div></div>'

                # Replace placeholders with dynamic content
                html_template = html_template.replace('{{title}}', title)
                html_template = html_template.replace('{{description}}', desc_bullets_html)
                html_template = html_template.replace('{{condition}}', condition_html)
                html_template = html_template.replace('{{photos}}', photos_html)
                html_template = html_template.replace('{{shipping}}', shipping_html)
                html_template = html_template.replace('{{signoff}}', signoff)

                ebay_data[ebay_field] = html_template
                continue

            # Get value from item (works for both dict and object)
            if isinstance(item, dict):
                value = item.get(source_field)
            else:
                value = getattr(item, source_field, None)

            if value is not None:
                # Handle special field types
                if rules.get('is_list'):
                    # For image URLs - convert list to pipe-separated string (eBay requirement)
                    if isinstance(value, list):
                        ebay_data[ebay_field] = '|'.join(str(v) for v in value if v)
                    else:
                        ebay_data[ebay_field] = str(value)

                elif rules.get('requires_mapping'):
                    # For condition - map internal condition to eBay condition ID
                    if ebay_field == 'Condition ID' and value in CONDITION_MAPPING:
                        ebay_data[ebay_field] = CONDITION_MAPPING[value]
                    else:
                        ebay_data[ebay_field] = str(value)

                else:
                    # Standard field - just convert to string
                    ebay_data[ebay_field] = str(value)

            elif 'default' in rules:
                # Use default if no value provided
                ebay_data[ebay_field] = rules['default']

    # Add defaults for fields not auto-populated
    for ebay_field, rules in EBAY_FIELD_VALIDATION.items():
        if ebay_field not in ebay_data and 'default' in rules:
            ebay_data[ebay_field] = rules['default']

    # Populate eBay Best Offer settings from item
    # These are stored as metadata fields in the comic
    if isinstance(item, dict):
        allow_offers = item.get('ebay_allow_offers') or item.get('eBay Allow Offers', 'TRUE')
        offer_min = item.get('ebay_offer_min') or item.get('eBay Offer Min', '')
        offer_max = item.get('ebay_offer_max') or item.get('eBay Offer Max', '')
    else:
        allow_offers = getattr(item, 'ebay_allow_offers', 'TRUE')
        offer_min = getattr(item, 'ebay_offer_min', '')
        offer_max = getattr(item, 'ebay_offer_max', '')

    # Set the offer fields
    ebay_data[EBAY_FIELD_NAMES['BEST_OFFER_ENABLED']] = allow_offers
    if offer_min:
        ebay_data[EBAY_FIELD_NAMES['MINIMUM_BEST_OFFER_PRICE']] = str(offer_min)
    if offer_max:
        ebay_data[EBAY_FIELD_NAMES['BEST_OFFER_AUTO_ACCEPT_PRICE']] = str(offer_max)

    return ebay_data


def get_auto_populate_fields():
    """
    Get list of eBay fields that can be auto-populated from item data.

    Returns:
        list: List of tuples (ebay_field_name, source_field_name, requires_mapping)
    """
    auto_fields = []
    for ebay_field, rules in EBAY_FIELD_VALIDATION.items():
        if rules.get('auto_populate'):
            source_field = rules.get('source_field', '')
            requires_mapping = rules.get('requires_mapping', False)
            is_list = rules.get('is_list', False)
            auto_fields.append((ebay_field, source_field, requires_mapping, is_list))
    return auto_fields


def _coerce_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _coerce_price(value, default=0):
    try:
        cleaned = str(value).replace('$', '').replace(',', '').strip()
        return str(round(float(cleaned), 2))
    except Exception:
        return str(round(float(default), 2))


def _extract_policy_info(value):
    if not value:
        return None, None
    match = re.search(r"\(ID:\s*(\d+)\)", value)
    policy_id = match.group(1) if match else None
    policy_name = value.split('(')[0].strip()
    return policy_id, policy_name or None


def _build_item_specifics(ebay_fields):
    """
    Build ItemSpecifics for eBay Trading API.

    The Trading API expects NameValueList entries with:
    - Name: the specific name (e.g., 'Publisher', 'Grade')
    - Value: a single string value, max 65 characters per eBay rules

    Args:
        ebay_fields: Dictionary of eBay fields including C: prefixed specifics

    Returns:
        List of NameValueList dicts or None if no specifics
    """
    MAX_VALUE_LEN = 65  # eBay item specifics value limit

    specifics = []
    for key, value in ebay_fields.items():
        if not value or not isinstance(key, str) or not key.startswith('C:'):
            continue
        name = key.split(':', 1)[1].strip()
        if not name:
            continue

        # Handle list/tuple values
        if isinstance(value, (list, tuple)):
            # For multiple values, create separate entries for each
            for v in value:
                v_str = str(v).strip()[:MAX_VALUE_LEN]
                if v_str:
                    specifics.append({'Name': name, 'Value': v_str})
        else:
            # Single value
            v_str = str(value).strip()[:MAX_VALUE_LEN]
            if v_str:
                specifics.append({'Name': name, 'Value': v_str})

    return specifics or None


def _apply_mode_overrides(item, mode='list', schedule_time_override=None):
    """
    Apply mode-specific overrides to the item payload.

    Args:
        item (dict): The item payload to modify
        mode (str): The listing mode - 'list' or 'future'
            - 'list': Go live immediately (no ScheduleTime)
            - 'future': Schedule for 18 days in the future
        schedule_time_override (datetime or str, optional): Custom schedule time for 'future' mode
            Can be a datetime object or ISO format string

    Returns:
        dict: Modified item payload

    NOTE: Auction vs Fixed-Price is controlled by the Format field in the item data,
    NOT by the mode parameter. Set Format='Auction' for auction listings.

    eBay Scheduled Listing Requirements (per Trading API docs):
    - Scheduled listings: ScheduleTime must be 1 minute to 21 DAYS in the future
    - When ScheduleTime is set, listing status becomes 'Scheduled'
    - At ScheduleTime, listing automatically becomes 'Active'
    - WITHOUT ScheduleTime, listing goes 'Active' immediately
    """
    # Helper to parse schedule_time_override if it's a string
    def parse_schedule_time(schedule_time):
        if isinstance(schedule_time, str):
            try:
                # Try parsing ISO format: YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS
                parsed = datetime.fromisoformat(schedule_time.replace('Z', '+00:00'))
                # Ensure timezone-aware (assume UTC if naive)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except (ValueError, AttributeError):
                return None
        # If it's already a datetime, ensure it's timezone-aware
        if isinstance(schedule_time, datetime) and schedule_time.tzinfo is None:
            return schedule_time.replace(tzinfo=timezone.utc)
        return schedule_time


    if mode == 'future':
        # For future listing mode, use provided schedule_time or default to 18 days from now
        # This creates a SCHEDULED listing (not active immediately)
        # eBay allows MAXIMUM 21 days in the future
        schedule_time = parse_schedule_time(schedule_time_override) if schedule_time_override else None

        if not schedule_time:
            # Default to 18 days from now (conservative, within eBay's 21-day maximum)
            # Use UTC time since eBay API expects UTC
            schedule_time = datetime.now(timezone.utc) + timedelta(days=18)

        # Ensure schedule time is within eBay's allowed range
        now = datetime.now(timezone.utc)  # Use UTC for consistency
        min_time = now + timedelta(minutes=5)  # eBay minimum: a few minutes (give buffer)
        max_time = now + timedelta(days=21)    # eBay maximum: 21 days

        if schedule_time < min_time:
            schedule_time = min_time
        elif schedule_time > max_time:
            try:
                from flask import current_app
                current_app.logger.warning(
                    f"Requested schedule time exceeds eBay's 21-day limit. Capping at 21 days from now."
                )
            except (RuntimeError, AttributeError, ImportError):
                # No Flask app context (e.g., running in validation script)
                pass
            schedule_time = max_time

        # Format as ISO 8601 with UTC timezone (Z suffix)
        item['ScheduleTime'] = schedule_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')

    elif mode == 'schedule':
        # Custom schedule time provided by user
        schedule_time = parse_schedule_time(schedule_time_override) if schedule_time_override else None

        if schedule_time:
            # Ensure schedule time is in valid range (max 21 days per eBay API limits)
            now = datetime.now(timezone.utc)  # Use UTC for consistency with eBay API
            min_time = now + timedelta(minutes=5)  # eBay minimum with buffer
            max_time = now + timedelta(days=21)    # eBay maximum: 21 days

            if schedule_time < min_time:
                schedule_time = min_time
            elif schedule_time > max_time:
                try:
                    from flask import current_app
                    current_app.logger.warning(
                        f"Requested schedule time {schedule_time} exceeds eBay's 21-day limit. Capping at 21 days."
                    )
                except (RuntimeError, AttributeError, ImportError):
                    # No Flask app context
                    pass
                schedule_time = max_time

            item['ScheduleTime'] = schedule_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        else:
            # Default to 18 days if no schedule time provided
            schedule_time = datetime.now(timezone.utc) + timedelta(days=18)
            item['ScheduleTime'] = schedule_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')

    # NOTE: For mode='list', we do NOT set ScheduleTime - listing goes ACTIVE immediately
    # The mode parameter only controls WHEN the listing goes live ('list' = now, 'future' = scheduled)
    # Auction vs Fixed-Price is controlled by the 'Format' field in admin defaults.

    return item


def _sanitize_html_for_ebay(html_content):
    """
    Sanitize HTML content for eBay's XML parser.

    eBay's Trading API requires HTML to be wrapped in CDATA tags to prevent
    XML parsing errors. The HTML inside CDATA is treated as plain text.

    Args:
        html_content (str): The HTML content to sanitize

    Returns:
        str: HTML wrapped in CDATA tags for eBay XML
    """
    if not html_content:
        return html_content

    # Remove any existing CDATA tags to avoid double-wrapping
    html_content = html_content.replace('<![CDATA[', '').replace(']]>', '')

    # Wrap the HTML in CDATA tags
    # This tells eBay's XML parser to treat the HTML as plain text content
    return f'<![CDATA[{html_content}]]>'



def build_trading_item(comic, overrides=None, mode='list', include_item_id=False, schedule_time=None):
    """Build an eBay Trading API Item payload from a Comic instance.

    Args:
        comic: The Comic model instance
        overrides: dict of field overrides
        mode: 'list' (immediate) or 'future' (scheduled 18 days)
        include_item_id: bool, include ItemID for updates
        schedule_time: datetime, custom schedule time for 'future' mode
    """
    from flask import current_app

    ebay_fields = populate_ebay_fields_from_item(comic)

    # Merge C: prefixed item specifics from comic's extra_fields
    # These are stored in the CSV as extra columns (e.g. C:Publisher, C:Era)
    if hasattr(comic, 'extra_fields') and comic.extra_fields:
        for key, value in comic.extra_fields.items():
            if key.startswith('C:') and value:
                ebay_fields[key] = value

    pictures = [url for url in getattr(comic, 'image_urls', []) if url]

    current_app.logger.debug(f"[build_trading_item] SKU {comic.sku}: comic.image_urls = {getattr(comic, 'image_urls', [])}")
    current_app.logger.debug(f"[build_trading_item] SKU {comic.sku}: Filtered pictures list = {pictures}")

    # NOTE: Images are uploaded to eBay via UploadSiteHostedPictures in
    # ebay_service.list_comic / update_listing BEFORE this function is called.
    # The caller passes eBay-hosted URLs through the overrides dict under
    # the key '_ebay_picture_urls'.  If present, those short eBay-hosted URLs
    # replace the raw S3 URLs.

    if overrides:
        # Extract eBay-hosted picture URLs before general override processing
        ebay_picture_urls = overrides.pop('_ebay_picture_urls', None)
        if ebay_picture_urls:
            pictures = ebay_picture_urls
            current_app.logger.debug(f"[build_trading_item] SKU {comic.sku}: Using {len(pictures)} eBay-hosted picture URLs")

        for key, value in overrides.items():
            if value not in (None, '', []):
                ebay_fields[key] = value

    start_price = _coerce_price(ebay_fields.get('Start price', comic.price), comic.price)
    quantity = _coerce_int(ebay_fields.get('Quantity', comic.quantity), comic.quantity)

    # ============================================================================
    # AUCTION VS FIXED-PRICE LISTINGS
    # ============================================================================
    # The listing type (Auction vs Fixed-Price) is controlled by ADMIN DEFAULTS:
    #
    # Format field:
    #   - 'FixedPrice' = Fixed-price listing (Buy It Now)
    #   - 'Auction' = Auction listing (bidding)
    #   - 'StoresFixedPrice' = eBay Store fixed-price listing
    #
    # Duration field:
    #   - 'GTC' = Good 'Til Cancelled (only valid for Fixed-Price)
    #   - 'Days_1', 'Days_3', 'Days_5', 'Days_7', 'Days_10' = Auction durations
    #
    # The mode parameter ('list' or 'future') only controls WHEN the listing
    # goes live, not WHETHER it's an auction or fixed-price.
    #
    # To create an auction listing:
    # 1. Set Format='Auction' in admin defaults
    # 2. Set Duration='Days_7' (or other Days_* option) in admin defaults
    # 3. Use mode='list' to go live immediately, or 'future' to schedule
    # ============================================================================

    # ============================================================================
    # Business Policies (SellerProfiles) - CURRENTLY DISABLED
    # ============================================================================
    # The payment/return/shipping profile settings from admin defaults are NOT
    # being used because eBay's Business Policies (SellerProfiles) caused schema
    # errors (Code: 20170 - unexpected child element).
    #
    # The working sample JSON provided uses MANUAL shipping/return policies, not
    # Business Policies. To match that working structure, we're using manual
    # policies below (ShippingDetails, ReturnPolicy, etc.)
    #
    # To re-enable Business Policies in the future:
    # 1. Uncomment the lines below to extract profile IDs
    # 2. Set using_profiles = True (or based on profile detection)
    # 3. Remove the manual shipping/return/payment sections in the else block
    # 4. Test thoroughly with eBay's Trading API
    # ============================================================================
    # payment_profile_id, _ = _extract_policy_info(ebay_fields.get('Payment profile name'))
    # return_profile_id, _ = _extract_policy_info(ebay_fields.get('Return profile name'))
    # shipping_profile_id, _ = _extract_policy_info(ebay_fields.get('Shipping profile name'))
    # using_profiles = bool(shipping_profile_id or return_profile_id or payment_profile_id)
    using_profiles = False  # Force manual policies to match working sample

    # Build the basic item structure - For AddFixedPriceItem API
    # ListingType is REQUIRED for scheduled/auction listings per eBay docs
    # - 'FixedPriceItem' = Fixed price (Buy It Now)
    # - 'Chinese' = Auction listing

    # Get the format from admin defaults to determine ListingType
    ebay_format = ebay_fields.get('Format', 'FixedPrice')

    # Map format to ListingType
    if ebay_format == 'Auction':
        listing_type = 'Chinese'  # eBay's code for auction listings
    else:
        listing_type = 'FixedPriceItem'  # eBay's code for fixed-price listings

    item = {
        'Title': ebay_fields.get('Title', comic.title)[:80],
        'Description': _sanitize_html_for_ebay(ebay_fields.get('Description', comic.description)),
        'PrimaryCategory': {'CategoryID': str(ebay_fields.get('Category ID', '259104'))},
        'StartPrice': start_price,
        'ListingType': listing_type,  # REQUIRED for scheduled listings
        'ListingDuration': ebay_fields.get('Duration', 'GTC'),
        'Quantity': _coerce_int(getattr(comic, 'quantity', 1), 1),  # Required field
        # ConditionID — eBay requires a numeric condition code. Comics almost never
        # ship as "Brand New" (1000), so we default to Like New (2750) and let the
        # user override per-comic via the "eBay Condition ID" field on the comic's
        # eBay Settings tab. Valid comic-category values: 2750, 3000, 4000, 5000, 6000.
        'ConditionID': _coerce_int(
            (getattr(comic, 'extra_fields', None) or {}).get('eBay Condition ID')
            or ebay_fields.get('eBay Condition ID')
            or 2750,
            2750
        ),
        'Country': 'US',
        'Currency': 'USD',
        'DispatchTimeMax': _coerce_int(ebay_fields.get('Max dispatch time', 3), 3),
        'PostalCode': ebay_fields.get('PostalCode', '80129'),
        'SKU': str(getattr(comic, 'sku', ''))  # Custom SKU for inventory tracking
    }


    # Handle Item ID for updates
    if include_item_id and getattr(comic, 'ebay_item_id', None):
        item['ItemID'] = str(comic.ebay_item_id)

    # Handle Pictures - Always include if available
    if pictures:
        item['PictureDetails'] = {'PictureURL': pictures[:12]}
        current_app.logger.debug(f"[build_trading_item] SKU {comic.sku}: ✅ Added PictureDetails with {len(pictures[:12])} images")
    else:
        current_app.logger.warning(f"[build_trading_item] SKU {comic.sku}: ⚠️ NO pictures to add - pictures list is empty!")

    # Best Offer Settings
    # Configure Best Offer (Make Offer) feature for the listing
    best_offer_enabled = ebay_fields.get(EBAY_FIELD_NAMES['BEST_OFFER_ENABLED'], 'TRUE')
    if best_offer_enabled == 'TRUE' or best_offer_enabled is True:
        best_offer_details = {'BestOfferEnabled': True}

        # Add minimum offer price if specified
        min_offer = ebay_fields.get(EBAY_FIELD_NAMES['MINIMUM_BEST_OFFER_PRICE'])
        if min_offer:
            try:
                min_price = _coerce_price(min_offer, 0)
                if float(min_price) > 0:
                    best_offer_details['MinimumBestOfferPrice'] = min_price
            except Exception:
                pass

        # Add auto-accept price if specified
        auto_accept = ebay_fields.get(EBAY_FIELD_NAMES['BEST_OFFER_AUTO_ACCEPT_PRICE'])
        if auto_accept:
            try:
                accept_price = _coerce_price(auto_accept, 0)
                if float(accept_price) > 0:
                    best_offer_details['BestOfferAutoAcceptPrice'] = accept_price
            except Exception:
                pass

        item['BestOfferDetails'] = best_offer_details
    else:
        # Explicitly disable Best Offer
        item['BestOfferDetails'] = {'BestOfferEnabled': False}

    # Since using_profiles = False, we always use manual shipping/return details
    # NOT using Business Policies - include manual shipping/return details

    item['ShippingDetails'] = {
        'ShippingType': 'Flat',
        'ShippingServiceOptions': [{
            'ShippingService': ebay_fields.get('Shipping service 1 option', 'USPSPriorityFlatRateEnvelope'),
            'ShippingServiceCost': str(_coerce_price(ebay_fields.get('Shipping service 1 cost', 6), 6)),
            'ShippingServicePriority': 1
        }]
    }

    # Return Policy
    returns_accepted = ebay_fields.get('Returns accepted option', 'ReturnsNotAccepted')
    if returns_accepted == 'ReturnsAccepted':
        item['ReturnPolicy'] = {
            'ReturnsAcceptedOption': returns_accepted,
            'ReturnsWithinOption': ebay_fields.get('Returns within option', 'Days_30'),
            'RefundOption': ebay_fields.get('Refund option', 'MoneyBack'),
            'ShippingCostPaidByOption': ebay_fields.get('Return shipping cost paid by', 'Buyer')
        }
    else:
        item['ReturnPolicy'] = {
            'ReturnsAcceptedOption': 'ReturnsNotAccepted'
        }

    # Site and AutoPay - add AFTER ReturnPolicy to match sample order
    item['Site'] = 'US'
    item['AutoPay'] = False

    # ItemSpecifics — send C: prefixed fields from the comic's extra_fields
    specifics = _build_item_specifics(ebay_fields)
    if specifics:
        item['ItemSpecifics'] = {'NameValueList': specifics}

    # Apply mode-specific overrides (draft, future listing, etc.)
    item = _apply_mode_overrides(item, mode=mode, schedule_time_override=schedule_time)


    return item

