"""Helper functions for eBay-specific operations."""
import re
from app.utils.ebay_validators import EBAY_FIELD_VALIDATION


def extract_all_sections_from_ebay_description(full_description):
    """
    Parse a structured eBay HTML description into individual sections.

    The app's listing template uses this structure:
        <strong>Label</strong>...<ul><li>bullet</li>...</ul>

    This function extracts each section's bullet text so it can be mapped
    back to form fields (Description, Condition Details, etc.).

    Args:
        full_description (str): Full HTML description from eBay

    Returns:
        dict: Mapping of section names to their content.
            Keys: 'description', 'condition', 'photos', 'shipping', 'signoff'
            Values: newline-joined plain-text strings (empty string if absent)
    """
    if not full_description:
        return {}

    sections = {}
    known_labels = ['Title', 'Description', 'Condition', 'Photos', 'Shipping']

    for label in known_labels:
        # Match: <strong>Label</strong> ... <ul> ... </ul>
        pattern = rf'<strong>\s*{label}\s*</strong>.*?<ul>(.*?)</ul>'
        match = re.search(pattern, full_description, re.DOTALL | re.IGNORECASE)
        if match:
            ul_content = match.group(1)
            # Extract text from each <li>
            items = re.findall(r'<li>(.*?)</li>', ul_content, re.DOTALL)
            items = [re.sub(r'<[^>]+>', '', item).strip() for item in items]
            items = [item for item in items if item]
            if items:
                sections[label.lower()] = '\n'.join(items)

    # Signoff: last <strong> whose text isn't a known label
    strong_matches = re.findall(r'<strong>(.*?)</strong>', full_description, re.DOTALL)
    for text in reversed(strong_matches):
        cleaned = re.sub(r'<[^>]+>', '', text).strip()
        if cleaned and cleaned not in known_labels:
            sections['signoff'] = cleaned
            break

    return sections


def extract_ebay_description_section(full_description):
    """
    Extract the user-editable description section from a full eBay item description.

    Tries structured template parsing first, then legacy comment markers,
    then falls back to returning the full description.

    Args:
        full_description (str): Full HTML description from eBay

    Returns:
        str: Extracted description text (plain text, newline-separated bullets)
    """
    if not full_description:
        return ''

    # 1. Try structured template parsing (our listing template format)
    sections = extract_all_sections_from_ebay_description(full_description)
    if 'description' in sections:
        return sections['description']

    # 2. Try legacy comment markers
    pattern = r'<!--DESCRIPTION_START-->(.*?)<!--DESCRIPTION_END-->'
    match = re.search(pattern, full_description, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. Fallback: strip all HTML tags and return plain text
    plain = re.sub(r'<[^>]+>', ' ', full_description)
    plain = re.sub(r'\s+', ' ', plain).strip()
    return plain[:500] if plain else ''


def extract_ebay_condition_section(full_description):
    """
    Extract the condition description section from a full eBay item description.

    Args:
        full_description (str): Full HTML description from eBay

    Returns:
        str: Extracted condition text (plain text, newline-separated bullets)
    """
    if not full_description:
        return ''

    # 1. Try structured template parsing
    sections = extract_all_sections_from_ebay_description(full_description)
    if 'condition' in sections:
        return sections['condition']

    # 2. Try legacy comment markers
    pattern = r'<!--CONDITION_START-->(.*?)<!--CONDITION_END-->'
    match = re.search(pattern, full_description, re.DOTALL)

    if match:
        return match.group(1).strip()

    return ''


def resolve_ebay_context(payload):
    """
    Extract eBay listing parameters from an API request payload.

    Parses environment, listing mode, field overrides, and schedule time
    from the JSON body sent by the frontend.

    Args:
        payload (dict): JSON body from the API request. Expected keys:
            - environment (str): 'production' or 'sandbox' (default: 'production')
            - mode (str): Listing mode — 'list', 'update', 'schedule', etc. (default: 'list')
            - overrides (dict): Optional field overrides for the Trading API item
            - schedule_time (str): Optional ISO-8601 datetime for scheduled listings

    Returns:
        tuple: (environment, listing_mode, overrides, schedule_time)
    """
    if not payload:
        payload = {}

    environment = payload.get('environment', 'production')
    listing_mode = payload.get('mode', 'list')
    overrides = payload.get('overrides') or {}
    schedule_time = payload.get('schedule_time') or None

    return environment, listing_mode, overrides, schedule_time


def validate_ebay_item_id(item_id):
    """
    Validate an eBay item ID format.

    eBay item IDs are typically numeric strings of 12-14 digits.

    Args:
        item_id (str): Item ID to validate

    Returns:
        tuple: (bool, str) - (is_valid, error_message)
            - is_valid: True if valid, False otherwise
            - error_message: Detailed error message if invalid, empty string if valid
    """
    if not item_id:
        return False, "eBay Item ID is required"

    # Remove any whitespace
    item_id = str(item_id).strip()

    # Check if it's numeric and reasonable length
    if not item_id.isdigit():
        return False, "eBay Item ID must be numeric"

    # eBay item IDs are typically 12-14 digits
    if len(item_id) < 10 or len(item_id) > 15:
        return False, f"eBay Item ID must be 10-15 digits (got {len(item_id)})"

    return True, ""



def get_ebay_validation_data():
    """
    Get eBay field validation data for frontend.

    This provides the frontend with information about:
    - Required fields
    - Field types
    - Allowed values
    - Validation rules

    Returns:
        dict: eBay validation configuration
    """
    return EBAY_FIELD_VALIDATION
