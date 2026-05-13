"""eBay Finding API and Browse API service for price lookups."""
import os
import json
import re
import time
import base64
import hashlib
import threading
import traceback
import urllib.parse
import requests
from datetime import datetime
from difflib import SequenceMatcher
from flask import current_app
from app.utils.ebay_validators import build_trading_item
from app.utils.logging_utils import safe_error_message
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError as TradingError


class EbayDuplicateListingError(Exception):
    """
    Exception raised when eBay detects a duplicate listing.

    Attributes:
        message: Error message from eBay
        existing_item_id: eBay item ID of the existing duplicate listing
        existing_title: Title of the existing listing (if available)
    """
    def __init__(self, message, existing_item_id=None, existing_title=None):
        self.message = message
        self.existing_item_id = existing_item_id
        self.existing_title = existing_title
        super().__init__(self.message)

    def __str__(self):
        if self.existing_item_id and self.existing_title:
            return (f"This item appears to be a duplicate of an existing eBay listing.\n"
                   f"Existing listing: {self.existing_title} (Item ID: {self.existing_item_id})\n"
                   f"Please check your eBay listings or increase the quantity of the existing item.")
        elif self.existing_item_id:
            return (f"This item appears to be a duplicate of an existing eBay listing (Item ID: {self.existing_item_id}).\n"
                   f"Please check your eBay listings or increase the quantity of the existing item.")
        else:
            return f"Duplicate listing detected: {self.message}"


class EbayService:
    """
    Service for interacting with eBay's Finding and Browse APIs.
    
    This service provides methods for searching completed listings (for pricing),
    active listings, and searching by image (visual search). It handles OAuth
    authentication, rate limit tracking, and caching of results.
    """

    # Production URLs
    FINDING_API_URL_PROD = "https://svcs.ebay.com/services/search/FindingService/v1"
    BROWSE_API_URL_PROD = "https://api.ebay.com/buy/browse/v1"
    OAUTH_URL_PROD = "https://api.ebay.com/identity/v1/oauth2/token"
    MARKETPLACE_INSIGHTS_URL_PROD = "https://api.ebay.com/buy/marketplace_insights/v1_beta"

    # Sandbox URLs
    FINDING_API_URL_SANDBOX = "https://svcs.sandbox.ebay.com/services/search/FindingService/v1"
    BROWSE_API_URL_SANDBOX = "https://api.sandbox.ebay.com/buy/browse/v1"
    OAUTH_URL_SANDBOX = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    MARKETPLACE_INSIGHTS_URL_SANDBOX = "https://api.sandbox.ebay.com/buy/marketplace_insights/v1_beta"

    # eBay condition name → condition ID mapping (used by search methods)
    _CONDITION_MAP: dict[str, str] = {
        'new': '1000',
        'like new': '1500',
        'very good': '2000',
        'good': '2500',
        'used': '3000',
        'acceptable': '4000',
    }

    def __init__(self):
        """Initialize the eBay service and determine the environment (production/sandbox)."""
        # User-specific state (cached per user to avoid repeated AWS calls).
        # Mutated from request handlers across threads; protect with a lock.
        self._user_credentials_cache = {}  # {username: {credentials}}
        self._user_tokens_cache = {}  # {username: {'token': ..., 'expires': ...}}
        self._cache_lock = threading.Lock()

        # Shared cache for search results (include username in cache keys)
        self.cache = {}  # Simple in-memory cache
        self.cache_ttl = 3600  # Default TTL
        self._logged_init = False  # Track if we've logged initialization

        # API call tracking for monitoring (shared across all users)
        self._call_counts = {}  # Track API calls by type

        # Category tree cache (shared across all users - categories are the same)
        instance_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'instance')
        os.makedirs(instance_dir, exist_ok=True)  # Ensure instance directory exists
        self.category_cache_file = os.path.join(instance_dir, 'ebay_category_cache.json')
        self.category_tree_cache = None  # Full category tree cache
        self.category_tree_version = None  # Track eBay's category tree version

        # Determine environment (default to production)
        self.environment = os.getenv('EBAY_ENVIRONMENT', 'production').lower()

        # Set API URLs based on environment
        if self.environment == 'sandbox':
            self.finding_api_url = self.FINDING_API_URL_SANDBOX
            self.browse_api_url = self.BROWSE_API_URL_SANDBOX
            self.oauth_url = self.OAUTH_URL_SANDBOX
            self.marketplace_insights_url = self.MARKETPLACE_INSIGHTS_URL_SANDBOX
        else:
            self.finding_api_url = self.FINDING_API_URL_PROD
            self.browse_api_url = self.BROWSE_API_URL_PROD
            self.oauth_url = self.OAUTH_URL_PROD
            self.marketplace_insights_url = self.MARKETPLACE_INSIGHTS_URL_PROD

    def _log_init(self):
        """
        Log initialization details. 
        
        Called lazily to ensure the Flask application context is available 
        for logging.
        """
        if not self._logged_init:
            try:
                # Update TTL from config if available
                self.cache_ttl = current_app.config.get('EBAY_CACHE_TTL', 3600)
                
                mode = "SANDBOX" if self.environment == 'sandbox' else "PRODUCTION"
                current_app.logger.info(f"eBay Service initialized in {mode} mode")
                self._logged_init = True
            except RuntimeError:
                # App context not available yet, skip logging
                pass

    def initialize_category_cache(self, marketplace_id='EBAY_US'):
        """
        Initialize category cache on app startup.

        This method:
        1. Ensures instance directory exists
        2. Loads existing cache if available
        3. If cache doesn't exist or is invalid, fetches from eBay
        4. Creates empty cache as fallback if eBay fetch fails

        Args:
            marketplace_id: The marketplace ID (e.g., 'EBAY_US')
        """
        try:
            # Ensure instance directory exists
            cache_dir = os.path.dirname(self.category_cache_file)
            os.makedirs(cache_dir, exist_ok=True)

            current_app.logger.info(f"Initializing category cache (file: {self.category_cache_file})")

            # Try to load existing cache
            if self._load_category_cache():
                file_size = os.path.getsize(self.category_cache_file)
                current_app.logger.info(f"✓ Category cache loaded from file ({file_size} bytes)")
                return True

            # No cache exists - try to fetch it
            current_app.logger.info("⚠ No category cache found - fetching from eBay (this will take 5-10 seconds)...")
            result = self._fetch_full_category_tree(marketplace_id)

            if 'error' not in result:
                # Verify file was actually created
                if os.path.exists(self.category_cache_file):
                    file_size = os.path.getsize(self.category_cache_file)
                    current_app.logger.info(f"✓ Category cache initialized successfully ({file_size} bytes saved)")
                    return True
                else:
                    current_app.logger.error(f"⚠ Cache was fetched but file was not created: {self.category_cache_file}")
            else:
                error_msg = result.get('error')
                current_app.logger.warning(f"Failed to fetch category cache from eBay: {error_msg}")

            # If we got here, either eBay fetch failed or file wasn't created
            current_app.logger.info("Creating empty cache file as fallback...")
            return self._create_empty_cache()

        except Exception as e:
            current_app.logger.error(f"Error initializing category cache: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            # Create empty cache as last resort
            try:
                return self._create_empty_cache()
            except Exception as e2:
                current_app.logger.error(f"Failed to create empty cache: {e2}")
                return False

    def _create_empty_cache(self):
        """Create an empty but valid cache file."""
        try:
            empty_cache = {
                'tree': {
                    'categoryTreeId': '0',
                    'categoryTreeVersion': 'empty',
                    'categoryTreeNode': {
                        'categoryId': '0',
                        'categoryName': 'All Categories',
                        'childCategoryTreeNodes': []
                    }
                },
                'version': 'empty',
                'cached_at': datetime.now().isoformat()
            }

            # Ensure directory exists
            cache_dir = os.path.dirname(self.category_cache_file)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)

            # Write empty cache
            with open(self.category_cache_file, 'w') as f:
                json.dump(empty_cache, f, indent=2)

            self.category_tree_cache = empty_cache['tree']
            self.category_tree_version = 'empty'
            current_app.logger.info(f"Created empty cache file: {self.category_cache_file}")
            return True
        except Exception as e:
            current_app.logger.error(f"Failed to create empty cache: {e}")
            return False


    def _get_app_id(self, username=None):
        """Get eBay App ID from config based on environment and current user."""
        # Deferred import: user_context requires Flask app context; ebay_service
        # is a module-level singleton instantiated before app context is ready.
        from app.utils.user_context import get_current_username, get_ebay_credentials

        if username is None:
            username = get_current_username()

        # Check if we have cached credentials for this user (under lock to
        # avoid two threads concurrently re-fetching for the same user).
        with self._cache_lock:
            creds = self._user_credentials_cache.get(username)
            if creds is None:
                creds = get_ebay_credentials(username)
                self._user_credentials_cache[username] = creds

        if self.environment == 'sandbox':
            return creds.get('EBAY_SANDBOX_APP_ID') or os.getenv('EBAY_SANDBOX_APP_ID') or current_app.config.get('EBAY_SANDBOX_APP_ID')
        else:
            return creds.get('EBAY_PRODUCTION_APP_ID') or os.getenv('EBAY_PRODUCTION_APP_ID') or current_app.config.get('EBAY_PRODUCTION_APP_ID')

    def _get_cert_id(self, username=None):
        """Get eBay Cert ID (Client Secret) from config based on environment and current user."""
        # Deferred import: see _get_app_id for rationale.
        from app.utils.user_context import get_current_username, get_ebay_credentials

        if username is None:
            username = get_current_username()

        with self._cache_lock:
            creds = self._user_credentials_cache.get(username)
            if creds is None:
                creds = get_ebay_credentials(username)
                self._user_credentials_cache[username] = creds

        if self.environment == 'sandbox':
            return creds.get('EBAY_SANDBOX_CERT_ID') or os.getenv('EBAY_SANDBOX_CERT_ID') or current_app.config.get('EBAY_SANDBOX_CERT_ID')
        else:
            return creds.get('EBAY_PRODUCTION_CERT_ID') or os.getenv('EBAY_PRODUCTION_CERT_ID') or current_app.config.get('EBAY_PRODUCTION_CERT_ID')

    def _get_oauth_token(self, username=None):
        """Get OAuth 2.0 access token for the current user, refreshing if needed."""
        # Deferred import: see _get_app_id for rationale.
        from app.utils.user_context import get_current_username

        if username is None:
            username = get_current_username()

        # Check if current token for this user is still valid (under lock)
        with self._cache_lock:
            token_data = self._user_tokens_cache.get(username)
            if token_data and token_data['token'] and time.time() < token_data['expires']:
                return token_data['token']

        app_id = self._get_app_id(username)
        cert_id = self._get_cert_id(username)

        if not app_id or not cert_id:
            # Provide detailed error message about which credentials are missing
            missing_creds = []
            if not app_id:
                if self.environment == 'sandbox':
                    missing_creds.append('EBAY_SANDBOX_APP_ID')
                else:
                    missing_creds.append('EBAY_PRODUCTION_APP_ID')
            if not cert_id:
                if self.environment == 'sandbox':
                    missing_creds.append('EBAY_SANDBOX_CERT_ID')
                else:
                    missing_creds.append('EBAY_PRODUCTION_CERT_ID')

            current_app.logger.error(f"[User: {username}] Missing eBay credentials for {self.environment}: {', '.join(missing_creds)}")
            return None

        current_app.logger.info(f"[User: {username}] Requesting OAuth token for {self.environment} environment")

        try:
            # Create Basic Auth credentials
            credentials = f"{app_id}:{cert_id}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            # Request OAuth token using Client Credentials grant
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Authorization': f'Basic {encoded_credentials}'
            }

            data = {
                'grant_type': 'client_credentials',
                'scope': 'https://api.ebay.com/oauth/api_scope'
            }

            response = requests.post(self.oauth_url, headers=headers, data=data, timeout=10)

            if response.status_code != 200:
                current_app.logger.error(f"[User: {username}] OAuth token request failed: {response.status_code} - {response.text}")
                return None

            token_data = response.json()
            oauth_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 7200)  # Default 2 hours
            token_expires = time.time() + expires_in - 60  # Refresh 1 min early

            # Cache token for this user (under lock — concurrent refreshes are
            # acceptable and the last writer wins.)
            with self._cache_lock:
                self._user_tokens_cache[username] = {
                    'token': oauth_token,
                    'expires': token_expires
                }

            current_app.logger.info(f"[User: {username}] Successfully obtained eBay OAuth token")
            return oauth_token

        except Exception as e:
            current_app.logger.error(f"[User: {username}] Error getting OAuth token: {e}")
            return None

    def _get_cache_key(self, title, condition, limit, username=None):
        """Generate cache key from search parameters, including username for multi-user isolation."""
        # Deferred import: see _get_app_id for rationale.
        from app.utils.user_context import get_current_username

        if username is None:
            username = get_current_username()

        key_str = f"{username}:{title}:{condition}:{limit}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _set_cache(self, cache_key, result):
        """Store result in cache."""
        self.cache[cache_key] = (result, time.time())
        
        # Also save to disk for sharing between workers
        try:
            cache_dir = os.path.join(current_app.instance_path, 'ebay_cache')
            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, f"{cache_key}.json")
            with open(cache_file, 'w') as f:
                json.dump({
                    'result': result,
                    'timestamp': time.time()
                }, f)
        except Exception as e:
            current_app.logger.warning(f"Error saving eBay cache to disk: {e}")

    def _get_cached_result(self, cache_key):
        """Get cached result if still valid."""
        # Try memory cache first
        if cache_key in self.cache:
            result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return result
            else:
                del self.cache[cache_key]

        # Try disk cache
        try:
            cache_file = os.path.join(current_app.instance_path, 'ebay_cache', f"{cache_key}.json")
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    result = data['result']
                    timestamp = data['timestamp']
                    if time.time() - timestamp < self.cache_ttl:
                        # Update memory cache
                        self.cache[cache_key] = (result, timestamp)
                        return result
                    else:
                        os.remove(cache_file)
        except Exception as e:
            current_app.logger.warning(f"Error reading eBay cache from disk: {e}")
            
        return None

    def search_completed_items(self, title, condition=None, limit=10):
        """
        Search for completed and sold listings on eBay to assist with pricing.
        
        This method uses the 'findItemsAdvanced' operation of the Finding API. 
        It filters for sold items only, restricted to the 'Comic Books' category.
        
        Args:
            title (str): The comic title to search for.
            condition (str, optional): The condition filter. Defaults to None.
            limit (int): Maximum number of results to return. Defaults to 10.
            
        Returns:
            dict: Parsed search results including item titles, prices, and URLs.
        """
        self._log_init()  # Log initialization on first use

        try:
            # Check cache first
            cache_key = self._get_cache_key(title, condition, limit)
            cached = self._get_cached_result(cache_key)
            if cached:
                cached['cached'] = True
                return cached

            app_id = self._get_app_id()
            if not app_id:
                return {'success': False, 'error': 'eBay App ID not configured'}

            # Build search keywords - add "comic" to improve relevance
            search_keywords = f"{title} comic"

            # Build request parameters
            # Note: Using findItemsAdvanced instead of findCompletedItems
            # findCompletedItems has very restrictive rate limits
            params = {
                'OPERATION-NAME': 'findItemsAdvanced',
                'SERVICE-VERSION': '1.0.0',
                'SECURITY-APPNAME': app_id,
                'RESPONSE-DATA-FORMAT': 'JSON',
                'keywords': search_keywords,
                'paginationInput.entriesPerPage': str(limit),  # Use configurable limit
                'categoryId': '63',  # Comic Books category
                'itemFilter(0).name': 'SoldItemsOnly',
                'itemFilter(0).value': 'true',
                'itemFilter(1).name': 'ListingType',
                'itemFilter(1).value': 'FixedPrice'  # Buy It Now only (no auctions)
            }

            # Add condition filter if specified, default to Used (3000) for comics if not specified
            ebay_condition = '3000'
            if condition:
                cond_lower = condition.lower()
                ebay_condition = self._CONDITION_MAP.get(cond_lower, condition if condition.isdigit() else '3000')
            
            params['itemFilter(2).name'] = 'Condition'
            params['itemFilter(2).value'] = ebay_condition

            # Make API request
            current_app.logger.info(f"eBay Finding API request ({self.environment}): {search_keywords}")
            response = requests.get(self.finding_api_url, params=params, timeout=10)


            # Log rate limit headers if available
            rl_limit = response.headers.get('X-EBAY-API-CALL-LIMIT')
            rl_remaining = response.headers.get('X-EBAY-API-CALL-LIMIT-REMAINING')
            if rl_limit or rl_remaining:
                current_app.logger.info(f"eBay Finding API Rate Limit: {rl_remaining}/{rl_limit}")

            # Check response status
            if response.status_code != 200:
                current_app.logger.error(f"eBay Finding API HTTP error: {response.status_code} - {response.text}")

                # Try to parse error details from response
                try:
                    error_data = response.json()
                    error_msg = error_data.get('errorMessage', [{}])[0]
                    error_detail = error_msg.get('error', [{}])[0]
                    error_id = error_detail.get('errorId', ['Unknown'])[0]
                    error_message = error_detail.get('message', ['Unknown error'])[0]

                    # Specific handling for rate limit errors
                    if error_id == '10001' or 'limit' in error_message.lower() or 'quota' in error_message.lower():
                        return {
                            'success': False,
                            'error': 'The eBay service for looking up sold prices is currently unavailable due to daily API limits. However, you can still use the image search results (which show current prices) as a guide.',
                            'rate_limit': True,
                            'api_type': 'FindingAPI'
                        }

                    return {'success': False, 'error': f'eBay API error {error_id}: {error_message}'}
                except Exception:
                    return {'success': False, 'error': f'eBay Finding API returned HTTP {response.status_code}'}

            data = response.json()

            # Parse response (using findItemsAdvanced response format)
            search_result = data.get('findItemsAdvancedResponse', [{}])[0]
            ack = search_result.get('ack', [None])[0]

            if ack != 'Success':
                error_msg = search_result.get('errorMessage', [{}])[0]
                error_detail = error_msg.get('error', [{}])[0]
                error_id = error_detail.get('errorId', ['Unknown'])[0]
                error_message = error_detail.get('message', ['Unknown error'])[0]

                current_app.logger.error(f"eBay API error {error_id}: {error_message}")

                # Specific handling for rate limit errors
                if error_id == '10001' or 'limit' in error_message.lower() or 'quota' in error_message.lower():
                    return {
                        'success': False,
                        'error': 'The eBay service for looking up sold prices is currently unavailable due to daily API limits. However, you can still use the image search results (which show current prices) as a guide.',
                        'rate_limit': True,
                        'api_type': 'FindingAPI'
                    }

                return {
                    'success': False,
                    'error': f'{error_message}',
                    'api_type': 'FindingAPI'
                }

            # Extract items
            search_items = search_result.get('searchResult', [{}])[0]
            items = search_items.get('item', [])

            # Specific handling for "Call Usage Limit Reached" error
            if ack == 'Failure' or ack == 'PartialFailure':
                error_msg = search_result.get('errorMessage', [{}])[0]
                error_detail = error_msg.get('error', [{}])[0]
                error_id = error_detail.get('errorId', ['Unknown'])[0]
                error_message = error_detail.get('message', ['Unknown error'])[0]
                
                if 'limit' in error_message.lower() or 'quota' in error_message.lower() or error_id == '10001':
                    return {
                        'success': False,
                        'error': 'The eBay service for looking up sold prices is currently unavailable due to daily API limits. However, you can still use the image search results (which show current prices) as a guide.',
                        'rate_limit': True,
                        'api_type': 'FindingAPI'
                    }

            # Also check if paginationOutput says 0
            pagination = search_result.get('paginationOutput', [{}])[0]
            total_entries = pagination.get('totalEntries', ['0'])[0]
            if int(total_entries) == 0 and not items:
                current_app.logger.info(f"eBay returned 0 results for: {search_keywords}")

            # Format results (use the requested limit)
            results = []
            for item in items[:limit]:  # Process up to the requested limit
                try:
                    sold_price = item.get('sellingStatus', [{}])[0].get('currentPrice', [{}])[0].get('__value__', '0')
                    condition_name = item.get('condition', [{}])[0].get('conditionDisplayName', ['Unknown'])[0]

                    results.append({
                        'title': item.get('title', ['No title'])[0],
                        'itemId': item.get('itemId', [''])[0],
                        'price': float(sold_price),
                        'condition': condition_name,
                        'listing_url': item.get('viewItemURL', [''])[0],
                        'image_url': item.get('galleryURL', [''])[0],
                        'end_time': item.get('listingInfo', [{}])[0].get('endTime', [''])[0]
                    })
                except (KeyError, IndexError, ValueError) as e:
                    current_app.logger.warning(f"Error parsing eBay item: {e}")
                    continue

            # Calculate price statistics from all results
            prices = [item['price'] for item in results if item['price'] > 0]
            price_stats = {}

            if prices:
                sorted_prices = sorted(prices)
                median = sorted_prices[len(sorted_prices) // 2] if len(sorted_prices) % 2 != 0 else (sorted_prices[len(sorted_prices) // 2 - 1] + sorted_prices[len(sorted_prices) // 2]) / 2

                price_stats = {
                    'average': round(sum(prices) / len(prices), 2),
                    'median': round(median, 2),
                    'min': round(min(prices), 2),
                    'max': round(max(prices), 2),
                    'total_items': len(prices)
                }

            result = {
                'success': True,
                'count': len(results),
                'items': results,
                'price_stats': price_stats,
                'cached': False
            }

            # Cache successful results
            self._set_cache(cache_key, result)

            return result

        except requests.RequestException as e:
            current_app.logger.error(f"eBay API request error: {e}")
            return {'success': False, 'error': f'API request failed: {safe_error_message(e)}'}
        except Exception as e:
            current_app.logger.error(f"eBay service error: {e}")
            return {'success': False, 'error': safe_error_message(e)}

    def search_sold_items(self, title, condition=None, limit=20, sort_by_title=None):
        """Return recently-sold listings for ``title``.

        Strategy:

        1. If ``EBAY_MARKETPLACE_INSIGHTS_ENABLED`` is truthy in the config /
           environment, try the Marketplace Insights API
           (``/buy/marketplace_insights/v1_beta/item_sales/search``). This is
           the official, supported, last-90-days sold-items endpoint. It is
           in Limited Release — eBay must approve the application.
        2. Otherwise (or on failure), fall back to the legacy Finding API
           path via :py:meth:`search_completed_items` (``findItemsAdvanced``
           with ``SoldItemsOnly=true``). The Finding API was deprecated in
           Feb 2025 — coverage is degraded but not yet zero.

        Both paths return the same normalized shape so the front-end can
        render either with the existing ``renderImageSearchResults`` JS:

        ``{success, count, items: [{title, itemId, price, condition,
            listing_url, image_url, end_time?, sold_date?}],
            data_source: 'marketplace_insights' | 'finding_api',
            market_label: 'SOLD (LAST 90D)',
            stats_label: 'Sold Price Statistics'}``

        Args:
            title: Search keywords (typically the comic's stored title).
            condition: Optional condition filter (e.g. ``'Near Mint'``).
                Only used by the Finding API fallback today.
            limit: Maximum results (1-50, default 20).
            sort_by_title: Optional title to re-rank results by similarity
                (mirrors :py:meth:`search_marketplace`).

        Returns:
            Normalized dict described above, or ``{'success': False, ...}``.
        """
        self._log_init()

        try:
            limit = max(1, min(50, int(limit)))
        except (ValueError, TypeError):
            limit = 20

        # UI-facing labels — both branches set these so the renderer doesn't
        # have to special-case the data source.
        labels = {
            'market_label': 'SOLD (LAST 90D)',
            'stats_label': 'Sold Price Statistics',
        }

        insights_enabled = self._marketplace_insights_enabled()
        if insights_enabled:
            insights_result = self._search_sold_via_marketplace_insights(
                title, limit=limit
            )
            if insights_result.get('success'):
                items = insights_result.get('items', [])
                if sort_by_title and items:
                    items = self._score_items_by_title_similarity(
                        items, sort_by_title
                    )
                return {
                    'success': True,
                    'count': len(items),
                    'items': items,
                    'data_source': 'marketplace_insights',
                    **labels,
                }
            current_app.logger.warning(
                "Marketplace Insights call failed, falling back to Finding API: "
                f"{insights_result.get('error')}"
            )

        # Finding API fallback (or primary, when Insights is not enabled).
        finding_result = self.search_completed_items(
            title, condition=condition, limit=limit
        )
        if not finding_result.get('success'):
            # Preserve rate_limit / fallback URL info for the route to surface.
            return {
                **finding_result,
                'data_source': 'finding_api',
                **labels,
            }

        items = finding_result.get('items', [])
        if sort_by_title and items:
            items = self._score_items_by_title_similarity(items, sort_by_title)

        return {
            'success': True,
            'count': len(items),
            'items': items,
            'data_source': 'finding_api',
            'cached': finding_result.get('cached', False),
            **labels,
        }

    def _marketplace_insights_enabled(self):
        """Return True if Marketplace Insights should be tried."""
        try:
            cfg_flag = current_app.config.get('EBAY_MARKETPLACE_INSIGHTS_ENABLED')
        except RuntimeError:
            cfg_flag = None
        env_flag = os.getenv('EBAY_MARKETPLACE_INSIGHTS_ENABLED')
        flag = cfg_flag if cfg_flag is not None else env_flag
        if flag is None:
            return False
        return str(flag).strip().lower() in ('1', 'true', 'yes', 'on')

    def _search_sold_via_marketplace_insights(self, query, limit=20):
        """Call eBay Marketplace Insights ``item_sales/search``.

        Returns the same normalized item shape as
        :py:meth:`search_completed_items`. This method is a no-op until the
        feature flag is on AND the OAuth client-credentials token has the
        ``buy.marketplace.insights`` scope (granted after eBay approves the
        Limited Release application).
        """
        token = self._get_oauth_token()
        if not token:
            return {
                'success': False,
                'error': 'Failed to obtain OAuth token for Marketplace Insights.',
            }

        url = f"{self.marketplace_insights_url}/item_sales/search"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US',
        }
        params = {
            'q': query,
            'category_ids': '63',  # Comic Books
            'limit': str(limit),
        }

        current_app.logger.info(
            f"Marketplace Insights item_sales/search: '{query}' (limit: {limit})"
        )
        response = requests.get(url, headers=headers, params=params, timeout=15)

        rl_remaining = response.headers.get('X-EBAY-C-CALL-LIMIT-REMAINING')
        if rl_remaining:
            current_app.logger.info(
                f"Marketplace Insights calls remaining: {rl_remaining}"
            )

        if response.status_code != 200:
            current_app.logger.error(
                f"Marketplace Insights HTTP {response.status_code}: {response.text[:500]}"
            )
            return {
                'success': False,
                'error': f'Marketplace Insights returned HTTP {response.status_code}',
            }

        data = response.json()
        sales = data.get('itemSales', [])
        items = []
        for sale in sales:
            try:
                price_info = sale.get('lastSoldPrice') or sale.get('price') or {}
                price_value = price_info.get('value', '0')
                image_obj = sale.get('image', {}) or {}
                browse_item_id = sale.get('itemId', '') or ''
                legacy_item_id = browse_item_id
                if '|' in browse_item_id:
                    parts = browse_item_id.split('|')
                    if len(parts) >= 2:
                        legacy_item_id = parts[1]

                items.append({
                    'title': sale.get('title', 'No title'),
                    'itemId': legacy_item_id,
                    'price': float(price_value),
                    'condition': sale.get('condition', 'Unknown'),
                    'listing_url': sale.get('itemWebUrl', ''),
                    'image_url': image_obj.get('imageUrl', ''),
                    'sold_date': sale.get('lastSoldDate', ''),
                })
            except (KeyError, ValueError) as e:
                current_app.logger.warning(
                    f"Error parsing Marketplace Insights sale: {e}"
                )
                continue

        return {'success': True, 'count': len(items), 'items': items}

    def get_sold_prices_url(self, title, condition=None):
        """
        Generate an eBay URL for viewing sold listings.
        This bypasses API limits by providing a direct link to eBay's sold listings page.

        Args:
            title (str): The comic title to search for.
            condition (str, optional): The condition filter.

        Returns:
            dict: Contains the URL and instructions for manual lookup.
        """

        # Build search URL with sold items filter
        base_url = "https://www.ebay.com/sch/i.html"
        search_query = f"{title} comic"

        params = {
            '_nkw': search_query,
            '_sacat': '63',  # Comic Books category
            'LH_Sold': '1',  # Sold listings
            'LH_Complete': '1',  # Completed listings
            'LH_BIN': '1',  # Buy It Now only
            '_sop': '13'  # Sort by recently sold
        }

        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        return {
            'success': True,
            'url': url,
            'message': 'eBay API limits reached. Use this URL to view sold prices manually.'
        }

    def search_active_items(self, title, condition=None, limit=20):
        """
        Search for active (current) listings on eBay.

        Args:
            title (str): The comic title to search for.
            condition (str, optional): The condition filter. Defaults to None.
            limit (int): Maximum number of results to return. Defaults to 20.

        Returns:
            dict: Parsed search results for active listings.
        """
        self._log_init()

        try:
            # Check cache first
            cache_key = self._get_cache_key(f"active_{title}", condition, limit)
            cached = self._get_cached_result(cache_key)
            if cached:
                cached['cached'] = True
                return cached

            app_id = self._get_app_id()
            if not app_id:
                return {'success': False, 'error': 'eBay App ID not configured'}

            # Build search keywords
            search_keywords = f"{title} comic"

            # Build request parameters for active listings
            params = {
                'OPERATION-NAME': 'findItemsAdvanced',
                'SERVICE-VERSION': '1.0.0',
                'SECURITY-APPNAME': app_id,
                'RESPONSE-DATA-FORMAT': 'JSON',
                'keywords': search_keywords,
                'paginationInput.entriesPerPage': str(limit),
                'categoryId': '63',  # Comic Books category
                'itemFilter(0).name': 'ListingType',
                'itemFilter(0).value': 'FixedPrice'  # Buy It Now only
            }

            # Add condition filter if specified
            if condition:
                cond_lower = condition.lower()
                ebay_condition = self._CONDITION_MAP.get(cond_lower, condition if condition.isdigit() else '3000')

                params['itemFilter(1).name'] = 'Condition'
                params['itemFilter(1).value'] = ebay_condition

            # Make API request
            current_app.logger.info(f"eBay Finding API request for active items ({self.environment}): {search_keywords}")
            response = requests.get(self.finding_api_url, params=params, timeout=10)


            if response.status_code != 200:
                current_app.logger.error(f"eBay Finding API HTTP error: {response.status_code}")
                current_app.logger.error(f"Response body: {response.text[:500]}")

                # Check if it's a rate limit error
                try:
                    error_data = response.json()
                    error_messages = error_data.get('errorMessage', [{}])
                    if error_messages:
                        error = error_messages[0].get('error', [{}])[0]
                        error_id = error.get('errorId', [''])[0]
                        error_msg = error.get('message', [''])[0]

                        if error_id == '10001' or 'rate' in error_msg.lower():
                            return {
                                'success': False,
                                'error': 'Daily API limit reached for Finding API. Please try the image search instead or wait until tomorrow.',
                                'rate_limit': True
                            }
                except Exception:
                    pass

                return {'success': False, 'error': f'eBay API returned HTTP {response.status_code}'}

            # Parse response
            data = response.json()
            search_response = data.get('findItemsAdvancedResponse', [{}])[0]
            ack = search_response.get('ack', [''])[0]

            if ack == 'Failure':
                error_msg = search_response.get('errorMessage', [{}])[0]
                return {'success': False, 'error': 'eBay API error', 'api_type': 'FindingAPI'}

            # Extract items
            search_result = search_response.get('searchResult', [{}])[0]
            items = search_result.get('item', [])

            # Format results
            results = []
            for item in items[:limit]:
                try:
                    current_price = item.get('sellingStatus', [{}])[0].get('currentPrice', [{}])[0].get('__value__', '0')
                    condition_name = item.get('condition', [{}])[0].get('conditionDisplayName', ['Unknown'])[0]

                    results.append({
                        'title': item.get('title', ['No title'])[0],
                        'itemId': item.get('itemId', [''])[0],
                        'price': float(current_price),
                        'condition': condition_name,
                        'listing_url': item.get('viewItemURL', [''])[0],
                        'image_url': item.get('galleryURL', [''])[0],
                        'listing_type': item.get('listingInfo', [{}])[0].get('listingType', [''])[0]
                    })
                except (KeyError, IndexError, ValueError) as e:
                    current_app.logger.warning(f"Error parsing eBay item: {e}")
                    continue

            # Calculate price statistics
            prices = [item['price'] for item in results if item['price'] > 0]
            price_stats = {}

            if prices:
                sorted_prices = sorted(prices)
                median = sorted_prices[len(sorted_prices) // 2] if len(sorted_prices) % 2 != 0 else (sorted_prices[len(sorted_prices) // 2 - 1] + sorted_prices[len(sorted_prices) // 2]) / 2

                price_stats = {
                    'average': round(sum(prices) / len(prices), 2),
                    'median': round(median, 2),
                    'min': round(min(prices), 2),
                    'max': round(max(prices), 2),
                    'total_items': len(prices)
                }

            result = {
                'success': True,
                'count': len(results),
                'items': results,
                'price_stats': price_stats,
                'cached': False
            }

            # Cache successful results
            self._set_cache(cache_key, result)

            current_app.logger.info(f"Found {len(results)} active items")
            return result

        except requests.RequestException as e:
            current_app.logger.error(f"eBay API request error: {e}")
            return {'success': False, 'error': f'API request failed: {safe_error_message(e)}'}
        except Exception as e:
            current_app.logger.error(f"eBay service error: {e}")
            return {'success': False, 'error': safe_error_message(e)}

    def search_by_image(self, image_data, limit=20, sort_by_title=None):
        """
        Perform a visual search on eBay using image data.
        
        This method uses eBay's 'search_by_image' Browse API endpoint. 
        It requires an OAuth user token and base64 encoded image data.
        
        Args:
            image_data (str): Base64 encoded image data.
            limit (int): Maximum number of results to return. Defaults to 20.
            sort_by_title (str, optional): Title to use for similarity sorting.
            
        Returns:
            dict: Parsed search results including matched items.
        """
        self._log_init()  # Log initialization on first use

        try:
            # Get OAuth token
            token = self._get_oauth_token()
            if not token:
                return {'success': False, 'error': 'Failed to obtain OAuth token. Check EBAY_APP_ID and EBAY_CERT_ID configuration.'}

            # Prepare request
            url = f"{self.browse_api_url}/item_summary/search_by_image"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'
            }

            payload = {
                'image': image_data,
                'limit': str(limit),
                'category_ids': '259104',  # Comic Books category (can be made configurable)
                'filter': 'buyingOptions:{FIXED_PRICE}'  # Only Buy It Now listings
            }

            current_app.logger.info(f"Searching eBay by image (limit: {limit})")
            response = requests.post(url, headers=headers, json=payload, timeout=15)


            # Log rate limit headers for Browse API
            rl_limit = response.headers.get('X-EBAY-C-CALL-LIMIT-REMAINING') # Browse API uses different headers
            if rl_limit:
                current_app.logger.info(f"eBay Browse API Remaining: {rl_limit}")

            if response.status_code != 200:
                error_detail = response.text
                current_app.logger.error(f"eBay image search HTTP error: {response.status_code} - {error_detail}")
                return {'success': False, 'error': f'eBay API returned HTTP {response.status_code}', 'detail': error_detail}

            data = response.json()

            # Parse response
            item_summaries = data.get('itemSummaries', [])

            if not item_summaries:
                return {
                    'success': True,
                    'count': 0,
                    'items': [],
                    'message': 'No similar items found'
                }

            # Format results
            items = []
            filtered_out_count = 0

            for item in item_summaries:
                try:
                    # Check if item is in Comics category (259104) or any of its sub-categories
                    # Comics category IDs: 259104 (main), 63 (older ID)
                    categories = item.get('categories', [])
                    category_ids = [cat.get('categoryId', '') for cat in categories]

                    # Filter: only include items from Comics categories
                    is_comic = False
                    for cat_id in category_ids:
                        # Check if it's the Comics category or starts with 259104 (sub-categories)
                        if cat_id == '259104' or cat_id == '63' or (cat_id and cat_id.startswith('259104')):
                            is_comic = True
                            break

                    if not is_comic:
                        filtered_out_count += 1
                        continue

                    # Get price info
                    price_info = item.get('price', {})
                    price_value = price_info.get('value', '0')

                    # Get image
                    image_obj = item.get('image', {})
                    image_url = image_obj.get('imageUrl', '')

                    # Browse API returns item IDs like "v1|123456789012|0"; extract
                    # the legacy Trading item ID so downstream GetItem calls succeed.
                    browse_item_id = item.get('itemId', '')
                    legacy_item_id = browse_item_id
                    if '|' in browse_item_id:
                        parts = browse_item_id.split('|')
                        if len(parts) >= 2:
                            legacy_item_id = parts[1]

                    item_data = {
                        'title': item.get('title', 'No title'),
                        'itemId': legacy_item_id,
                        'browse_item_id': browse_item_id,
                        'price': float(price_value),
                        'condition': item.get('condition', 'Unknown'),
                        'listing_url': item.get('itemWebUrl', ''),
                        'image_url': image_url,
                        'item_location': item.get('itemLocation', {}).get('country', 'US'),
                        'categories': category_ids
                    }

                    items.append(item_data)

                except (KeyError, ValueError) as e:
                    current_app.logger.warning(f"Error parsing eBay item: {e}")
                    continue

            if filtered_out_count > 0:
                current_app.logger.info(f"Filtered out {filtered_out_count} non-comic items from image search")

            result = {
                'success': True,
                'count': len(items),
                'items': items,
                'environment': self.environment
            }

            # Sort by title similarity if requested
            if sort_by_title and items:
                result['items'] = self._score_items_by_title_similarity(items, sort_by_title)
                result['count'] = len(result['items'])

            current_app.logger.info(f"Found {len(result['items'])} comic items via image search")
            return result

        except requests.RequestException as e:
            current_app.logger.error(f"eBay image search request error: {e}")
            return {'success': False, 'error': f'API request failed: {safe_error_message(e)}'}
        except Exception as e:
            current_app.logger.error(f"eBay image search error: {e}")
            return {'success': False, 'error': safe_error_message(e)}

    @staticmethod
    def _score_items_by_title_similarity(items, reference_title):
        """Sort a list of item dicts by title similarity to ``reference_title``.

        Args:
            items: List of dicts with a ``title`` key.
            reference_title: Title string to compare against.

        Returns:
            New list ordered from most-similar to least-similar.
        """
        reference = (reference_title or "").lower()
        if not reference or not items:
            return list(items)

        def score(item):
            return SequenceMatcher(
                None, (item.get("title") or "").lower(), reference
            ).ratio()

        return sorted(items, key=score, reverse=True)

    def search_marketplace(self, query, limit=12, sort_by_title=None):
        """
        Search all of eBay marketplace using the Browse API (text-based).

        Uses the Browse API /item_summary/search endpoint which has separate
        rate limits from the Finding API. Returns active listings from all sellers.

        Args:
            query (str): Search keywords.
            limit (int): Maximum number of results (1-50, default 12).
            sort_by_title (str, optional): If provided, results are re-sorted by
                title similarity to this string (highest similarity first). This
                mirrors the behavior of ``search_by_image``.

        Returns:
            dict: Search results with items list, or error info.
        """
        self._log_init()

        try:
            token = self._get_oauth_token()
            if not token:
                return {'success': False, 'error': 'Failed to obtain OAuth token. Check eBay credentials.'}

            url = f"{self.browse_api_url}/item_summary/search"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'
            }

            params = {
                'q': query,
                'category_ids': '63',  # Comics category
                'limit': str(min(50, max(1, limit))),
            }

            current_app.logger.info(f"Searching eBay marketplace via Browse API: '{query}' (limit: {limit})")
            response = requests.get(url, headers=headers, params=params, timeout=15)

            # Log rate limit headers
            rl_remaining = response.headers.get('X-EBAY-C-CALL-LIMIT-REMAINING')
            if rl_remaining:
                current_app.logger.info(f"eBay Browse API calls remaining: {rl_remaining}")

            if response.status_code != 200:
                error_detail = response.text
                current_app.logger.error(f"eBay Browse search HTTP error: {response.status_code} - {error_detail}")
                return {'success': False, 'error': f'eBay API returned HTTP {response.status_code}', 'detail': error_detail}

            data = response.json()
            item_summaries = data.get('itemSummaries', [])

            if not item_summaries:
                return {'success': True, 'count': 0, 'items': [], 'message': 'No items found'}

            items = []
            for item in item_summaries:
                try:
                    price_info = item.get('price', {})
                    price_value = price_info.get('value', '0')
                    image_obj = item.get('image', {})
                    image_url = image_obj.get('imageUrl', '')

                    # Extract the legacy item ID from the Browse API itemId
                    # Browse API returns itemId like "v1|123456789|0" — extract middle part
                    browse_item_id = item.get('itemId', '')
                    legacy_item_id = browse_item_id
                    if '|' in browse_item_id:
                        parts = browse_item_id.split('|')
                        if len(parts) >= 2:
                            legacy_item_id = parts[1]

                    items.append({
                        'title': item.get('title', 'No title'),
                        'itemId': legacy_item_id,
                        'price': float(price_value),
                        'condition': item.get('condition', 'Unknown'),
                        'listing_url': item.get('itemWebUrl', ''),
                        'image_url': image_url,
                        'seller': item.get('seller', {}).get('username', ''),
                    })
                except (KeyError, ValueError) as e:
                    current_app.logger.warning(f"Error parsing Browse API item: {e}")
                    continue

            current_app.logger.info(f"Browse API search found {len(items)} items for '{query}'")

            if sort_by_title:
                items = self._score_items_by_title_similarity(items, sort_by_title)

            return {'success': True, 'count': len(items), 'items': items}

        except requests.RequestException as e:
            current_app.logger.error(f"eBay Browse search request error: {e}")
            return {'success': False, 'error': f'API request failed: {safe_error_message(e)}'}
        except Exception as e:
            current_app.logger.error(f"eBay Browse search error: {e}")
            return {'success': False, 'error': safe_error_message(e)}

    def _get_trading_credentials(self, environment=None):
        env = (environment or self.environment or 'production').lower()
        cfg = current_app.config
        if env == 'sandbox':
            return {
                'app_id': cfg.get('EBAY_SANDBOX_APP_ID') or os.getenv('EBAY_SANDBOX_APP_ID'),
                'dev_id': cfg.get('EBAY_SANDBOX_DEV_ID') or os.getenv('EBAY_SANDBOX_DEV_ID'),
                'cert_id': cfg.get('EBAY_SANDBOX_CERT_ID') or os.getenv('EBAY_SANDBOX_CERT_ID'),
                'token': cfg.get('EBAY_SANDBOX_TOKEN') or os.getenv('EBAY_SANDBOX_TOKEN'),
                'domain': 'api.sandbox.ebay.com'
            }
        return {
            'app_id': cfg.get('EBAY_PRODUCTION_APP_ID') or os.getenv('EBAY_PRODUCTION_APP_ID'),
            'dev_id': cfg.get('EBAY_PRODUCTION_DEV_ID') or os.getenv('EBAY_PRODUCTION_DEV_ID'),
            'cert_id': cfg.get('EBAY_PRODUCTION_CERT_ID') or os.getenv('EBAY_PRODUCTION_CERT_ID'),
            'token': cfg.get('EBAY_PRODUCTION_TOKEN') or os.getenv('EBAY_PRODUCTION_TOKEN'),
            'domain': 'api.ebay.com'
        }

    def _get_trading_connection(self, environment=None):
        creds = self._get_trading_credentials(environment)
        missing = [k for k, v in creds.items() if k != 'domain' and not v]
        if missing:
            raise RuntimeError(f"Missing eBay credentials for {environment or self.environment}: {', '.join(missing)}")
        return Trading(
            config_file=None,
            domain=creds['domain'],
            appid=creds['app_id'],
            devid=creds['dev_id'],
            certid=creds['cert_id'],
            token=creds['token'],
            warnings=True,
            timeout=15,  # Fail fast before Gunicorn worker timeout fires; DNS/network errors raise cleanly
        )

    # ------------------------------------------------------------------
    # Error simplification helpers
    # ------------------------------------------------------------------

    # Map of eBay error codes to user-friendly messages.
    # Keys are string error codes, values are short descriptions.
    _EBAY_ERROR_MESSAGES = {
        '5': 'XML parsing error — please try again or contact support',
        '10': 'Internal eBay error — please try again later',
        '17': 'Invalid eBay category — check the category setting',
        '21916275': 'Listing upgrade not available for this category',
        '21916286': 'Invalid shipping service — check eBay shipping settings',
        '21916293': 'Return policy is required — check eBay return profile',
        '21916550': 'Title too long — eBay titles cannot exceed 80 characters',
        '21916578': 'Invalid item specifics — check required item details',
        '21916684': 'Not authorized for this action — check eBay account permissions',
        '21916750': 'Missing required field — check that all eBay fields are filled in',
        '21916799': 'Invalid condition for this category',
        '21917091': 'Listing cannot be revised — it may have bids or sales',
        '21919067': 'Duplicate listing — this item is already listed on eBay',
        '21919136': 'Image does not meet eBay requirements (min 500×500 pixels)',
        '21919188': 'Invalid return policy — check eBay return profile',
        '21919303': 'Invalid shipping policy — check eBay shipping profile',
        '21919474': 'Payment policy error — check eBay payment profile',
        '240': 'Selling limits reached — you have hit your eBay selling allowance',
        '488': 'Item cannot be listed or revised — it may be restricted',
        '21916547': 'Image URL not understood — image upload failed',
    }

    def _parse_trading_error(self, exc, conn, call_name):
        """Parse a TradingError and return a user-friendly exception.

        Tries to extract structured error data from the connection response.
        Falls back to regex parsing of the raw error string.

        Returns:
            EbayDuplicateListingError for duplicate listings, otherwise RuntimeError.
        """
        raw = str(exc)

        # Try structured parsing from the response object
        try:
            resp = getattr(conn, 'response', None)
            reply = getattr(resp, 'reply', None) if resp else None
            errors = getattr(reply, 'Errors', None) if reply else None

            if errors:
                for err in errors if isinstance(errors, list) else [errors]:
                    code = str(getattr(err, 'ErrorCode', ''))
                    msg = str(getattr(err, 'LongMessage', getattr(err, 'ShortMessage', '')))

                    # Duplicate listing detection
                    if code == '21919067' or 'duplicate listing' in msg.lower():
                        existing_title, existing_item_id = self._extract_duplicate_info(msg)
                        raise EbayDuplicateListingError(msg, existing_item_id, existing_title)

                    # Known error code → friendly message
                    if code in self._EBAY_ERROR_MESSAGES:
                        raise RuntimeError(self._EBAY_ERROR_MESSAGES[code])
        except (EbayDuplicateListingError, RuntimeError):
            raise  # Let our own exceptions propagate
        except Exception:
            pass  # Structured parsing failed, fall back to string parsing

        # Fall back to regex on the raw string
        return RuntimeError(self._simplify_ebay_error(raw))

    @staticmethod
    def _extract_duplicate_info(msg):
        """Extract title and item ID from a duplicate-listing error message."""
        match = re.search(
            r'(?:already have|already exists) on eBay:\s*(.+?)\s*\((\d+)\)',
            msg, re.IGNORECASE
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()
        # Fallback: just the item ID in parentheses
        match = re.search(r'\((\d{12,})\)', msg)
        if match:
            return None, match.group(1).strip()
        return None, None

    @classmethod
    def _simplify_ebay_error(cls, raw):
        """Convert a raw eBay error string to a short user-friendly message.

        Strips the verbose 'CallName: Class: …, Severity: …, Code: …,' prefix
        and maps known codes to plain-English text.
        """
        # Try to extract error code from the raw string
        code_match = re.search(r'Code:\s*(\d+)', raw)
        if code_match:
            code = code_match.group(1)
            if code in cls._EBAY_ERROR_MESSAGES:
                return cls._EBAY_ERROR_MESSAGES[code]

        # Duplicate listing check by content
        if 'duplicate listing' in raw.lower():
            return 'Duplicate listing — this item is already listed on eBay'

        # Strip the verbose prefix: "CallName: Class: RequestError, Severity: Error, Code: XXXX, "
        stripped = re.sub(
            r'^[A-Za-z]+:\s*Class:\s*\w+,\s*Severity:\s*\w+,\s*Code:\s*\d+,\s*',
            '', raw
        )
        if stripped and stripped != raw:
            # Truncate if still too long (keep first sentence)
            if len(stripped) > 150:
                first_period = stripped.find('.')
                if 0 < first_period < 150:
                    stripped = stripped[:first_period + 1]
                else:
                    stripped = stripped[:147] + '...'
            return stripped

        # Last resort: truncate the raw message
        if len(raw) > 150:
            return raw[:147] + '...'
        return raw or 'eBay request failed'

    @staticmethod
    def _escape_bare_ampersands(value):
        """Escape only raw ampersands that are not already valid XML entities."""
        if not isinstance(value, str) or '&' not in value:
            return value
        return re.sub(r'&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)', '&amp;', value)

    def _sanitize_trading_payload_strings(self, value, path=''):
        """Recursively sanitize payload string values and collect changed paths."""
        changed_paths = []

        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                sanitized_item, item_changes = self._sanitize_trading_payload_strings(item, child_path)
                sanitized[key] = sanitized_item
                changed_paths.extend(item_changes)
            return sanitized, changed_paths

        if isinstance(value, list):
            sanitized = []
            for idx, item in enumerate(value):
                child_path = f"{path}[{idx}]"
                sanitized_item, item_changes = self._sanitize_trading_payload_strings(item, child_path)
                sanitized.append(sanitized_item)
                changed_paths.extend(item_changes)
            return sanitized, changed_paths

        if isinstance(value, str):
            sanitized = self._escape_bare_ampersands(value)
            if sanitized != value:
                changed_paths.append(path or '<root>')
            return sanitized, changed_paths

        return value, changed_paths

    def _execute_trading_call(self, call_name, payload, environment=None, mode='list', files=None):
        """Execute an eBay Trading API call with error handling.

        Args:
            call_name (str): Trading API verb (e.g. 'AddFixedPriceItem').
            payload (dict): Request body as a dict.
            environment (str): 'production' or 'sandbox'.
            mode (str): 'list', 'upload', etc. (for logging).
            files (dict, optional): Multipart file data for binary uploads,
                e.g. ``{'file': ('name.jpg', bytes_data, 'image/jpeg')}``.
        """
        env = (environment or self.environment or 'production').lower()
        current_app.logger.debug(
            "eBay Trading call=%s env=%s mode=%s payload_keys=%s",
            call_name,
            env,
            mode,
            list(payload.keys())
        )

        payload_for_call = payload
        if call_name in {'AddFixedPriceItem', 'ReviseFixedPriceItem'}:
            payload_for_call, changed_paths = self._sanitize_trading_payload_strings(payload)
            if changed_paths:
                current_app.logger.warning(
                    "Sanitized XML-unsafe ampersands for %s fields: %s",
                    call_name,
                    ', '.join(changed_paths[:10]) + (' ...' if len(changed_paths) > 10 else '')
                )

        conn = self._get_trading_connection(env)
        try:
            response = conn.execute(call_name, payload_for_call, files=files)
        except TradingError as exc:
            # Log full details for debugging (XML request/response)
            xml_request = None
            if hasattr(conn, 'request_xml'):
                xml_request = conn.request_xml
            elif hasattr(conn, 'request') and hasattr(conn.request, 'body'):
                xml_request = conn.request.body

            current_app.logger.error("eBay XML Request: %s", xml_request or 'Unable to retrieve request XML')
            current_app.logger.error("eBay XML Response: %s", conn.response.content if hasattr(conn.response, 'content') else 'N/A')
            current_app.logger.error(
                "TradingError during %s (%s): %s", call_name, env, exc,
                exc_info=True
            )

            # Parse the error into a user-friendly message instead of exposing raw API output
            raise self._parse_trading_error(exc, conn, call_name) from exc
        except Exception as exc:
            current_app.logger.error(
                "Unexpected error during %s (%s): %s", call_name, env, exc,
                exc_info=True
            )
            raise RuntimeError(self._simplify_ebay_error(str(exc))) from exc

        ack = getattr(response.reply, 'Ack', None)
        warnings = getattr(response.reply, 'Errors', None) if ack == 'Warning' else None

        if warnings:
            warn_messages = []
            for warn in warnings if isinstance(warnings, list) else [warnings]:
                code = getattr(warn, 'ErrorCode', 'WARN')
                msg = getattr(warn, 'LongMessage', getattr(warn, 'ShortMessage', 'Unknown warning'))
                warn_messages.append(f"[{code}] {msg}")
            current_app.logger.warning(
                "eBay Trading %s returned warnings: %s",
                call_name,
                '; '.join(warn_messages)
            )

        item_id = getattr(response.reply, 'ItemID', None)
        current_app.logger.debug("eBay Trading %s succeeded env=%s item_id=%s", call_name, env, item_id)
        return response

    def list_comic(self, comic, environment=None, mode='list', overrides=None, schedule_time=None):
        """List a comic on eBay."""
        # Validate that comic has at least 1 image
        image_urls = getattr(comic, 'image_urls', [])

        valid_images = [url for url in image_urls if url and url.strip()]

        if not valid_images:
            current_app.logger.error(f"[list_comic] SKU {comic.sku}: No valid images found")
            raise ValueError('Cannot list item on eBay without at least 1 photo. Please add an image first.')

        current_app.logger.debug(f"[list_comic] SKU {comic.sku}: Found {len(valid_images)} valid images")

        # Upload images to eBay's servers first, getting back short hosted URLs
        ebay_picture_urls = self.upload_pictures(valid_images, environment=environment)
        if not ebay_picture_urls:
            raise RuntimeError('Failed to upload any images to eBay. Cannot create listing without pictures.')
        current_app.logger.info(f"[list_comic] SKU {comic.sku}: Uploaded {len(ebay_picture_urls)} images to eBay")

        # Pass eBay-hosted URLs into overrides so build_trading_item uses them
        overrides = overrides or {}
        overrides['_ebay_picture_urls'] = ebay_picture_urls

        payload = {'Item': build_trading_item(comic, overrides=overrides, mode=mode, schedule_time=schedule_time)}

        # Log if PictureDetails is in the payload
        if 'PictureDetails' in payload.get('Item', {}):
            pic_urls = payload['Item']['PictureDetails'].get('PictureURL', [])
            current_app.logger.debug(f"[list_comic] SKU {comic.sku}: Sending {len(pic_urls)} images to eBay in PictureDetails")
        else:
            current_app.logger.warning(f"[list_comic] SKU {comic.sku}: ⚠️ NO PictureDetails in payload!")

        response = self._execute_trading_call('AddFixedPriceItem', payload, environment=environment, mode=mode)
        return getattr(response.reply, 'ItemID', None)

    def update_listing(self, comic, environment=None, overrides=None, mode='list', schedule_time=None):
        if not comic.ebay_item_id:
            raise ValueError('Cannot update listing without ebay_item_id')

        # Upload images to eBay's servers
        image_urls = getattr(comic, 'image_urls', [])
        valid_images = [url for url in image_urls if url and url.strip()]
        current_app.logger.debug(f"[update_listing] SKU {comic.sku}: Found {len(valid_images)} valid images")

        if valid_images:
            ebay_picture_urls = self.upload_pictures(valid_images, environment=environment)
            if ebay_picture_urls:
                overrides = overrides or {}
                overrides['_ebay_picture_urls'] = ebay_picture_urls
                current_app.logger.info(f"[update_listing] SKU {comic.sku}: Uploaded {len(ebay_picture_urls)} images to eBay")

        payload = {'Item': build_trading_item(comic, overrides=overrides, mode=mode, include_item_id=True, schedule_time=schedule_time)}

        # Log if PictureDetails is in the payload
        if 'PictureDetails' in payload.get('Item', {}):
            pic_urls = payload['Item']['PictureDetails'].get('PictureURL', [])
            current_app.logger.debug(f"[update_listing] SKU {comic.sku}: Sending {len(pic_urls)} images to eBay")
        else:
            current_app.logger.warning(f"[update_listing] SKU {comic.sku}: ⚠️ NO PictureDetails in payload!")

        response = self._execute_trading_call('ReviseFixedPriceItem', payload, environment=environment, mode=mode)
        return getattr(response.reply, 'ItemID', comic.ebay_item_id)

    def update_price_only(self, item_id: str, new_price: float, environment: str | None = None) -> str:
        """Send a lightweight ReviseFixedPriceItem that changes only the StartPrice.

        Does not re-upload images or rebuild the full listing payload.  Use this
        for quick price edits where only the price field needs to change.

        Args:
            item_id: eBay item ID of the active listing.
            new_price: New price in USD (will be formatted to 2 decimal places).
            environment: 'production' or 'sandbox'. Defaults to service default.

        Returns:
            The eBay ItemID returned by the API (same as item_id on success).

        Raises:
            ValueError: If item_id is empty.
            TradingError: If the eBay API call fails.
        """
        if not item_id:
            raise ValueError("item_id is required for update_price_only")

        payload = {
            'Item': {
                'ItemID': str(item_id),
                'StartPrice': f"{float(new_price):.2f}",
            }
        }
        current_app.logger.info(
            "[update_price_only] ItemID=%s new_price=%.2f env=%s",
            item_id,
            new_price,
            environment or self.environment or 'production',
        )
        response = self._execute_trading_call(
            'ReviseFixedPriceItem', payload, environment=environment, mode='list'
        )
        return getattr(response.reply, 'ItemID', item_id)

    def upload_picture(self, image_url, environment=None):
        """Upload a single image to eBay via UploadSiteHostedPictures.

        Downloads the image from S3 using boto3 and uploads the raw bytes
        directly to eBay as a multipart binary upload.  This avoids all
        URL-related issues (presigned URL length, XML escaping of ``&``,
        private bucket access).

        Args:
            image_url (str): S3 URL of the image to upload.
            environment (str, optional): 'production' or 'sandbox'.

        Returns:
            str: eBay-hosted image URL, or None on failure.
        """
        from app.services.s3_service import s3_service  # Deferred: avoids circular import at module load

        try:
            # ── 1. Download image bytes from S3 ────────────────────────
            parsed = urllib.parse.urlparse(image_url)
            s3_key = urllib.parse.unquote(parsed.path.lstrip('/'))
            bucket = s3_service.bucket_name

            if not bucket:
                current_app.logger.error("[upload_picture] S3 bucket not configured")
                return None

            current_app.logger.debug(f"[upload_picture] Downloading s3://{bucket}/{s3_key}")
            s3_obj = s3_service.client().get_object(Bucket=bucket, Key=s3_key)
            image_bytes = s3_obj['Body'].read()
            content_type = s3_obj.get('ContentType', 'image/jpeg')

            if not image_bytes:
                current_app.logger.error(f"[upload_picture] Empty image data for {image_url}")
                return None

            # ── 2. Determine filename from the S3 key ──────────────────
            filename = s3_key.rsplit('/', 1)[-1] if '/' in s3_key else s3_key

            # ── 3. Upload binary to eBay ───────────────────────────────
            payload = {
                'PictureName': filename,
            }
            files = {
                'file': (filename, image_bytes, content_type),
            }

            response = self._execute_trading_call(
                'UploadSiteHostedPictures', payload,
                environment=environment, mode='upload',
                files=files,
            )

            site_hosted = getattr(response.reply, 'SiteHostedPictureDetails', None)
            if site_hosted:
                full_url = getattr(site_hosted, 'FullURL', None)
                if full_url:
                    current_app.logger.info(f"[upload_picture] Uploaded {filename} → {full_url}")
                    return str(full_url)

            current_app.logger.error(f"[upload_picture] No FullURL in response for {image_url}")
            return None

        except Exception as e:
            current_app.logger.error(f"[upload_picture] Failed to upload {image_url}: {e}")
            return None

    def upload_pictures(self, image_urls, environment=None):
        """Upload multiple images to eBay, returning eBay-hosted URLs.

        Args:
            image_urls (list): List of S3 image URLs.
            environment (str, optional): 'production' or 'sandbox'.

        Returns:
            list: eBay-hosted URLs (only successful uploads). Max 12 per eBay limits.
        """
        ebay_urls = []
        for url in image_urls[:12]:  # eBay max 12 pictures
            hosted_url = self.upload_picture(url, environment=environment)
            if hosted_url:
                ebay_urls.append(hosted_url)
        return ebay_urls

    def get_item(self, item_id, environment=None):
        """
        Get item details from eBay using GetItem Trading API call.

        Args:
            item_id (str): The eBay Item ID to retrieve
            environment (str, optional): 'production' or 'sandbox'

        Returns:
            dict: Item details if found, None if not found
        """
        if not item_id:
            return None

        try:
            payload = {
                'ItemID': item_id,
                'DetailLevel': 'ReturnAll'
            }
            response = self._execute_trading_call('GetItem', payload, environment=environment, mode='read')

            if response and hasattr(response.reply, 'Item'):
                item = response.reply.Item
                return {
                    'ItemID': getattr(item, 'ItemID', None),
                    'Title': getattr(item, 'Title', None),
                    'ListingStatus': getattr(item, 'SellingStatus', {}).get('ListingStatus') if hasattr(item, 'SellingStatus') else None,
                    'Quantity': getattr(item, 'Quantity', None),
                    'QuantitySold': getattr(item, 'SellingStatus', {}).get('QuantitySold') if hasattr(item, 'SellingStatus') else None,
                    'CurrentPrice': getattr(item, 'SellingStatus', {}).get('CurrentPrice') if hasattr(item, 'SellingStatus') else None,
                    'ListingType': getattr(item, 'ListingType', None),
                    'StartTime': getattr(item, 'ListingDetails', {}).get('StartTime') if hasattr(item, 'ListingDetails') else None,
                    'EndTime': getattr(item, 'ListingDetails', {}).get('EndTime') if hasattr(item, 'ListingDetails') else None,
                }
            return None

        except Exception as e:
            current_app.logger.warning(f"Failed to get eBay item {item_id}: {e}")
            # If item not found or error, return None (item doesn't exist)
            return None

    def end_listing(self, comic, reason='NotAvailable', environment=None):
        if not comic.ebay_item_id:
            raise ValueError('Cannot end listing without ebay_item_id')
        payload = {'EndingReason': reason, 'ItemID': comic.ebay_item_id}
        self._execute_trading_call('EndFixedPriceItem', payload, environment=environment, mode='end')

    def end_item_by_id(self, item_id, reason='NotAvailable', environment=None):
        """End an eBay listing by item ID (no Comic object needed).

        Useful for deleting drafts or ending listings that aren't linked
        to a local inventory item.

        Args:
            item_id (str): eBay Item ID to end.
            reason (str): End reason (NotAvailable, LostOrBroken, etc.).
            environment (str, optional): 'production' or 'sandbox'.
        """
        if not item_id:
            raise ValueError('Item ID is required')
        payload = {'EndingReason': reason, 'ItemID': str(item_id)}
        self._execute_trading_call('EndFixedPriceItem', payload, environment=environment, mode='end')
        current_app.logger.info(f"Ended eBay item {item_id} (reason={reason})")

    def get_item_details(self, item_id, environment=None):
        """Get full item details from eBay for cloning / import.

        Returns comprehensive metadata including description, item specifics,
        category, condition, and picture URLs — everything needed to replicate
        a listing locally.

        Args:
            item_id (str): The eBay Item ID to retrieve.
            environment (str, optional): 'production' or 'sandbox'.

        Returns:
            dict: Full item details, or None if not found.
        """
        if not item_id:
            return None

        try:
            payload = {
                'ItemID': item_id,
                'DetailLevel': 'ReturnAll',
                'IncludeItemSpecifics': True
            }
            response = self._execute_trading_call('GetItem', payload, environment=environment, mode='read')

            if not response or not hasattr(response.reply, 'Item'):
                return None

            item = response.reply.Item

            # --- Extract basic fields ---
            result = {
                'ItemID': getattr(item, 'ItemID', None),
                'Title': getattr(item, 'Title', None),
                'ListingStatus': None,
                'CurrentPrice': None,
                'Quantity': getattr(item, 'Quantity', None),
                'QuantitySold': None,
                'ListingType': getattr(item, 'ListingType', None),
                'ConditionID': getattr(item, 'ConditionID', None),
                'ConditionDisplayName': getattr(item, 'ConditionDisplayName', None),
                'Description': getattr(item, 'Description', ''),
                'SKU': getattr(item, 'SKU', ''),
                'PostalCode': getattr(item, 'PostalCode', ''),
            }

            # Selling status
            selling_status = getattr(item, 'SellingStatus', None)
            if selling_status:
                result['ListingStatus'] = getattr(selling_status, 'ListingStatus', None)
                result['QuantitySold'] = getattr(selling_status, 'QuantitySold', None)
                price_obj = getattr(selling_status, 'CurrentPrice', None)
                if price_obj:
                    result['CurrentPrice'] = str(price_obj.value) if hasattr(price_obj, 'value') else str(price_obj)

            # Category
            primary_cat = getattr(item, 'PrimaryCategory', None)
            if primary_cat:
                result['CategoryID'] = getattr(primary_cat, 'CategoryID', None)
                result['CategoryName'] = getattr(primary_cat, 'CategoryName', None)

            # Pictures
            pic_details = getattr(item, 'PictureDetails', None)
            if pic_details:
                gallery_url = getattr(pic_details, 'GalleryURL', '')
                result['GalleryURL'] = str(gallery_url) if gallery_url else ''
                pic_urls = getattr(pic_details, 'PictureURL', [])
                if pic_urls:
                    if isinstance(pic_urls, str):
                        result['PictureURLs'] = [pic_urls]
                    elif isinstance(pic_urls, list):
                        result['PictureURLs'] = [str(u) for u in pic_urls]
                    else:
                        result['PictureURLs'] = [str(pic_urls)]
                else:
                    result['PictureURLs'] = []

            # Item specifics
            item_specifics = getattr(item, 'ItemSpecifics', None)
            if item_specifics:
                nv_list = getattr(item_specifics, 'NameValueList', [])
                if nv_list:
                    if not isinstance(nv_list, list):
                        nv_list = [nv_list]
                    specifics = {}
                    for nv in nv_list:
                        name = getattr(nv, 'Name', '')
                        values = getattr(nv, 'Value', [])
                        if isinstance(values, list):
                            specifics[name] = values[0] if len(values) == 1 else values
                        else:
                            specifics[name] = str(values)
                    result['ItemSpecifics'] = specifics

            # Shipping details
            shipping_details = getattr(item, 'ShippingDetails', None)
            if shipping_details:
                services = getattr(shipping_details, 'ShippingServiceOptions', [])
                if services:
                    if not isinstance(services, list):
                        services = [services]
                    result['ShippingService'] = getattr(services[0], 'ShippingService', '')
                    cost_obj = getattr(services[0], 'ShippingServiceCost', None)
                    if cost_obj:
                        result['ShippingCost'] = str(cost_obj.value) if hasattr(cost_obj, 'value') else str(cost_obj)

            # Listing dates
            listing_details = getattr(item, 'ListingDetails', None)
            if listing_details:
                result['StartTime'] = getattr(listing_details, 'StartTime', None)
                result['EndTime'] = getattr(listing_details, 'EndTime', None)
                result['ViewItemURL'] = getattr(listing_details, 'ViewItemURL', None)

            current_app.logger.info(f"Retrieved full details for eBay item {item_id}")
            return result

        except Exception as e:
            current_app.logger.warning(f"Failed to get eBay item details for {item_id}: {e}")
            return None

    def relist_item(self, comic, environment=None, overrides=None, mode='list', schedule_time=None):
        """Relist an ended eBay item with the app's generated description.

        This ends any existing listing (if still active), then creates a
        brand-new listing using the comic's current data, which generates a
        fresh description from the template.

        Args:
            comic: Comic model instance (must have ebay_item_id set).
            environment (str, optional): 'production' or 'sandbox'.
            overrides (dict, optional): Field overrides for the new listing.
            mode (str): 'list' or 'future'.
            schedule_time: Optional schedule time for future listings.

        Returns:
            str: New eBay Item ID.
        """
        old_item_id = comic.ebay_item_id

        # Try to end the old listing (ignore errors if already ended)
        if old_item_id:
            try:
                self.end_item_by_id(old_item_id, reason='NotAvailable', environment=environment)
                current_app.logger.info(f"Ended old listing {old_item_id} before relist")
            except Exception as e:
                current_app.logger.warning(f"Could not end old listing {old_item_id}: {e}")

        # Clear the old item ID so list_comic creates a fresh listing
        comic.ebay_item_id = ''

        # Create a new listing with the app's generated description
        new_item_id = self.list_comic(
            comic,
            environment=environment,
            mode=mode,
            overrides=overrides,
            schedule_time=schedule_time
        )

        current_app.logger.info(f"Relisted SKU {comic.sku}: old={old_item_id} -> new={new_item_id}")
        return new_item_id

    def get_category_tree_id(self, marketplace_id='EBAY_US'):
        """Map marketplace ID to eBay category tree ID."""
        marketplace_to_tree_id = {
            'EBAY_US': '0',
            'EBAY_GB': '3',
            'EBAY_CA': '2',
            'EBAY_AU': '15',
            'EBAY_DE': '77',
            'EBAY_FR': '71',
            'EBAY_IT': '101',
            'EBAY_ES': '186',
            'EBAY_MOTORS_US': '100',
        }
        return marketplace_to_tree_id.get(marketplace_id, '0')

    def _load_category_cache(self):
        """Load the cached full category tree from disk."""
        try:
            if not os.path.exists(self.category_cache_file):
                return False

            with open(self.category_cache_file, 'r') as f:
                cache_data = json.load(f)

            self.category_tree_cache = cache_data.get('tree')
            self.category_tree_version = cache_data.get('version')
            return bool(self.category_tree_cache)
        except Exception as e:
            current_app.logger.error(f"Error loading category cache: {e}")
            return False

    def _save_category_cache(self, tree_data, version):
        """Persist the full category tree cache to disk."""
        try:
            cache_data = {
                'tree': tree_data,
                'version': version,
                'cached_at': datetime.now().isoformat(),
            }

            cache_dir = os.path.dirname(self.category_cache_file)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)

            temp_file = self.category_cache_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            os.replace(temp_file, self.category_cache_file)

            self.category_tree_cache = tree_data
            self.category_tree_version = version
            return True
        except Exception as e:
            current_app.logger.error(f"Error saving category cache: {e}")
            return False

    def _normalize_category_node(self, node):
        """Normalize eBay taxonomy node shape to a flat categoryId/categoryName schema."""
        if not node:
            return None

        category_obj = node.get('category', {}) if isinstance(node, dict) else {}
        category_id = (
            node.get('categoryId')
            or node.get('categoryTreeNodeId')
            or category_obj.get('categoryId')
        )
        category_name = (
            node.get('categoryName')
            or node.get('categoryTreeNodeName')
            or category_obj.get('categoryName')
            or 'Unknown'
        )

        children = node.get('childCategoryTreeNodes', []) if isinstance(node, dict) else []
        normalized_children = []
        for child in children:
            normalized_child = self._normalize_category_node(child)
            if normalized_child:
                normalized_children.append(normalized_child)

        return {
            'categoryId': str(category_id) if category_id is not None else '',
            'categoryName': str(category_name),
            'childCategoryTreeNodes': normalized_children,
        }

    def _count_categories(self, node):
        """Count categories in a normalized category tree node."""
        if not node:
            return 0
        count = 1
        for child in node.get('childCategoryTreeNodes', []):
            count += self._count_categories(child)
        return count

    def _fetch_full_category_tree(self, marketplace_id='EBAY_US', max_depth=2):
        """Fetch and normalize the full taxonomy tree from eBay and cache it."""
        _ = max_depth  # kept for API compatibility

        token = self._get_oauth_token()
        if not token:
            return {'error': 'Failed to obtain OAuth token'}

        try:
            category_tree_id = self.get_category_tree_id(marketplace_id)
            tree_url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{category_tree_id}"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }

            response = requests.get(tree_url, headers=headers, timeout=10)
            if response.status_code != 200:
                return {'error': f'Failed to get tree: {response.status_code}'}

            tree_data = response.json()
            version = tree_data.get('categoryTreeVersion')
            root_node = tree_data.get('rootCategoryNode', {})
            normalized_root = self._normalize_category_node(root_node)

            result = {
                'categoryTreeId': category_tree_id,
                'categoryTreeVersion': version,
                'categoryTreeNode': {
                    'categoryId': '0',
                    'categoryName': 'All Categories',
                    'childCategoryTreeNodes': normalized_root.get('childCategoryTreeNodes', []) if normalized_root else [],
                },
            }

            total = self._count_categories(result['categoryTreeNode'])
            current_app.logger.info(f"Fetched eBay category tree with {total} categories")

            self._save_category_cache(result, version)
            return result
        except Exception as e:
            current_app.logger.error(f"Error fetching full category tree: {e}")
            return {'error': safe_error_message(e)}

    def get_root_categories(self, marketplace_id='EBAY_US'):
        """Return full category tree used by the category explorer UI.

        The root endpoint historically returns the whole tree for client-side
        filtering/expansion, so keep that behavior for compatibility.
        """
        try:
            if self.category_tree_cache is not None:
                return self.category_tree_cache

            if self._load_category_cache() and self.category_tree_cache is not None:
                return self.category_tree_cache

            return self._fetch_full_category_tree(marketplace_id)
        except Exception as e:
            current_app.logger.error(f"Error in get_root_categories: {e}")
            return {'error': safe_error_message(e)}

    def get_category_tree(self, marketplace_id='EBAY_US'):
        """Return the complete eBay category tree for a marketplace."""
        return self.get_root_categories(marketplace_id)

    def get_category_children(self, category_id, marketplace_id='EBAY_US'):
        """Return childCategoryTreeNodes for a specific category ID."""
        try:
            tree = self.get_root_categories(marketplace_id)
            if 'error' in tree:
                return tree

            target_id = str(category_id)

            def _find_node(node):
                if not node:
                    return None
                if str(node.get('categoryId', '')) == target_id:
                    return node
                for child in node.get('childCategoryTreeNodes', []):
                    found = _find_node(child)
                    if found:
                        return found
                return None

            root = tree.get('categoryTreeNode')
            found_node = _find_node(root)
            if not found_node:
                return {'success': True, 'childCategoryTreeNodes': []}

            return {
                'success': True,
                'childCategoryTreeNodes': found_node.get('childCategoryTreeNodes', []),
            }
        except Exception as e:
            current_app.logger.error(f"Error fetching category children: {e}")
            return {'error': safe_error_message(e)}

    def search_categories(self, query, marketplace_id='EBAY_US'):
        """Search eBay taxonomy categories by query string."""
        token = self._get_oauth_token()
        if not token:
            return {'error': 'Failed to obtain OAuth token'}

        try:
            category_tree_id = self.get_category_tree_id(marketplace_id)
            url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_category_suggestions"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }
            params = {'q': query}

            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()

            current_app.logger.error(f"Category search failed: {response.status_code} - {response.text}")
            return {'error': f'Request failed with status {response.status_code}'}
        except Exception as e:
            current_app.logger.error(f"Error searching categories: {e}")
            return {'error': safe_error_message(e)}


# Singleton instance
ebay_service = EbayService()

