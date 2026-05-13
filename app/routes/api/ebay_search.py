"""eBay Search routes - Price lookup and visual search operations.

This module handles:
- eBay price lookup (completed items search)
- Active listings search
- Visual search by image
- Image proxy for CORS

All functions include type hints and comprehensive docstrings for better IDE support.
"""
import base64
import binascii
import io
import os
from urllib.parse import parse_qs, quote, unquote, urlparse

from flask import Response, current_app, jsonify, redirect, request
from flask.typing import ResponseReturnValue
from werkzeug.datastructures import FileStorage

from app.routes.api import api_bp
from app.routes.auth import csrf_required, login_required
from app.services.ebay_service import ebay_service
from app.services.s3_service import s3_service
from app.utils.upload_security import UploadValidationError, validate_uploaded_image


ALLOWED_IMAGE_MIME_TO_EXTENSIONS = {
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
}


def _encode_validated_uploaded_image(file_storage: FileStorage) -> str:
    """Validate an uploaded image file and return a base64 payload for eBay."""
    validate_uploaded_image(file_storage)
    image_bytes = file_storage.stream.read()
    file_storage.stream.seek(0)
    return base64.b64encode(image_bytes).decode('ascii')


def _encode_validated_base64_image(image_data: str) -> str:
    """Validate a base64 image payload and normalize it for eBay search."""
    if not isinstance(image_data, str) or not image_data.strip():
        raise UploadValidationError('Image data is required')

    normalized_data = image_data.strip()
    mime_type = ''

    if normalized_data.startswith('data:'):
        header, separator, payload = normalized_data.partition(',')
        if not separator or not payload:
            raise UploadValidationError('Invalid image payload')
        mime_type = header[5:].split(';', 1)[0].lower()
        normalized_data = payload

    if mime_type and mime_type not in ALLOWED_IMAGE_MIME_TO_EXTENSIONS:
        raise UploadValidationError(
            'Unsupported image type. Allowed: jpg, jpeg, png, gif, webp'
        )

    try:
        image_bytes = base64.b64decode(normalized_data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise UploadValidationError('Invalid image payload') from exc

    filename_extension = ALLOWED_IMAGE_MIME_TO_EXTENSIONS.get(mime_type, 'png')
    file_storage = FileStorage(
        stream=io.BytesIO(image_bytes),
        filename=f'image-search.{filename_extension}',
    )
    validate_uploaded_image(file_storage)
    return base64.b64encode(image_bytes).decode('ascii')


@api_bp.route('/ebay/lookup-price', methods=['POST'])
@login_required
@csrf_required
def lookup_ebay_price() -> ResponseReturnValue:
    """Search eBay completed items for price research.

    Searches recently sold items on eBay to help determine appropriate pricing.
    Uses eBay Finding API to search completed/sold listings.

    Request Body (JSON):
        {
            "title": str,               # Comic title to search
            "condition": Optional[str], # Condition filter (e.g., "Near Mint")
            "limit": Optional[int]      # Max results (5-100, default 20)
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether search succeeded
            - results (list): List of sold items with:
                - title (str): Item title
                - soldPrice (str): Final sale price
                - soldDate (str): Date sold
                - condition (str): Item condition
                - url (str): eBay item URL
            - count (int): Number of results returned
            - rate_limit (bool, optional): If API limit hit
            - fallback_url (str, optional): Manual search URL if rate limited
            - error (str, optional): Error message if failed

    Status Codes:
        200: Search completed successfully
        400: Title required or invalid request
        500: eBay API error or server error

    Example Request:
        {
            "title": "Amazing Spider-Man 300",
            "condition": "Near Mint",
            "limit": 20
        }

    Example Response:
        {
            "success": true,
            "results": [
                {
                    "title": "Amazing Spider-Man #300",
                    "soldPrice": "$45.99",
                    "soldDate": "2026-01-25",
                    "condition": "Near Mint",
                    "url": "https://ebay.com/itm/..."
                }
            ],
            "count": 15
        }

    Note:
        - Results limited to items sold in past 90 days
        - Prices show actual sale price, not asking price
        - Useful for competitive pricing research
        - Falls back to manual search URL if API rate limited
    """
    try:
        data = request.get_json()
        title = data.get('title')
        condition = data.get('condition')
        limit = data.get('limit', 20)

        if not title:
            return jsonify({'success': False, 'error': 'Comic title is required'}), 400

        # Validate limit
        try:
            limit = int(limit)
            if limit < 5 or limit > 100:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

        # Search eBay for completed items
        result = ebay_service.search_completed_items(title, condition=condition, limit=limit)

        # If API limit error, provide fallback URL
        if not result.get('success') and result.get('rate_limit'):
            fallback = ebay_service.get_sold_prices_url(title, condition)
            result['fallback_url'] = fallback['url']
            result['fallback_message'] = fallback['message']

        return jsonify(result)

    except Exception as e:
        current_app.logger.exception("Error looking up eBay price")
        return jsonify({'success': False, 'error': 'Failed to lookup eBay prices'}), 500


@api_bp.route('/ebay/search-active', methods=['POST'])
@login_required
@csrf_required
def search_active_items() -> ResponseReturnValue:
    """Search active (currently listed) items on eBay.

    Searches current eBay listings to see what's currently available and at what prices.
    Useful for competitive analysis and market research.

    Request Body (JSON):
        {
            "title": str,               # Comic title to search
            "condition": Optional[str], # Condition filter
            "limit": Optional[int]      # Max results (5-100, default 20)
        }

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether search succeeded
            - results (list): List of active listings
            - count (int): Number of results
            - error (str, optional): Error message if failed

    Status Codes:
        200: Search completed successfully
        400: Title required
        500: eBay API error

    Example Response:
        {
            "success": true,
            "results": [
                {
                    "title": "Amazing Spider-Man #300",
                    "currentPrice": "$49.99",
                    "condition": "Very Good",
                    "url": "https://ebay.com/itm/..."
                }
            ],
            "count": 12
        }

    Note:
        - Shows currently available items only
        - Prices are asking prices, not sold prices
        - Use for competitive pricing and availability research
    """
    try:
        data = request.get_json()
        title = data.get('title')
        condition = data.get('condition')
        limit = data.get('limit', 20)

        if not title:
            return jsonify({'success': False, 'error': 'Comic title is required'}), 400

        # Validate limit
        try:
            limit = int(limit)
            if limit < 5 or limit > 100:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

        # Search eBay for active listings
        result = ebay_service.search_active_items(title, condition=condition, limit=limit)

        return jsonify(result)

    except Exception as e:
        current_app.logger.exception("Error searching active eBay listings")
        return jsonify({'success': False, 'error': 'Failed to search active eBay listings'}), 500


@api_bp.route('/ebay/search-sold', methods=['POST'])
@login_required
@csrf_required
def search_sold() -> ResponseReturnValue:
    """Return recently-sold listings for a comic title.

    Tries the eBay Marketplace Insights API (last-90-days sold items, official
    supported endpoint) when the ``EBAY_MARKETPLACE_INSIGHTS_ENABLED`` feature
    flag is set, and falls back to the legacy Finding API
    (``findItemsAdvanced`` + ``SoldItemsOnly=true``) otherwise. Both branches
    return the same normalized JSON shape — the front-end uses one renderer.

    Request Body (JSON):
        {
            "title": str,                    # Comic title to search
            "condition": Optional[str],      # Condition filter
            "limit": Optional[int],          # Max results (1-50, default 20)
            "sort_by_title": Optional[str],  # If set, results re-ranked by
                                             # title similarity. Defaults to
                                             # ``title``.
        }

    Returns:
        Flask JSON response with ``success``, ``count``, ``items``,
        ``data_source`` (``"marketplace_insights"`` or ``"finding_api"``),
        ``market_label``, ``stats_label``, and a ``fallback_url`` for the
        manual eBay sold-listings page when the API hits a rate limit.
    """
    try:
        data = request.get_json() or {}
        title = data.get('title')
        condition = data.get('condition')
        limit = data.get('limit', 20)
        sort_by_title = data.get('sort_by_title', title)

        if not title:
            return jsonify({'success': False, 'error': 'Comic title is required'}), 400

        try:
            limit = max(1, min(50, int(limit)))
        except (ValueError, TypeError):
            limit = 20

        result = ebay_service.search_sold_items(
            title,
            condition=condition,
            limit=limit,
            sort_by_title=sort_by_title,
        )

        # Always include a manual eBay sold-listings URL the UI can show as a
        # secondary call-to-action — useful both on rate-limit and on success.
        fallback = ebay_service.get_sold_prices_url(title, condition)
        result['fallback_url'] = fallback.get('url')
        if not result.get('success') and result.get('rate_limit'):
            result['fallback_message'] = fallback.get('message')

        return jsonify(result)

    except Exception as e:
        current_app.logger.exception("Error searching sold eBay listings")
        return jsonify({'success': False, 'error': 'Failed to search sold listings'}), 500


@api_bp.route('/ebay/search-marketplace', methods=['POST'])
@login_required
@csrf_required
def search_marketplace() -> ResponseReturnValue:
    """Search all of eBay marketplace using the Browse API.

    Uses the Browse API text search which has separate rate limits
    from the Finding API. Returns active listings from any seller.

    Request Body (JSON):
        {
            "title": str,                    # Search keywords
            "limit": Optional[int],          # Max results (1-50, default 12)
            "sort_by_title": Optional[str],  # If set, results re-ranked by title
                                             # similarity to this string. Defaults
                                             # to ``title`` so the closest comic
                                             # listings surface first.
        }

    Returns:
        Response: Flask JSON response with search results.
    """
    try:
        data = request.get_json()
        title = data.get('title')
        limit = data.get('limit', 12)
        sort_by_title = data.get('sort_by_title', title)

        if not title:
            return jsonify({'success': False, 'error': 'Search query is required'}), 400

        try:
            limit = max(1, min(50, int(limit)))
        except (ValueError, TypeError):
            limit = 12

        result = ebay_service.search_marketplace(
            title, limit=limit, sort_by_title=sort_by_title
        )
        return jsonify(result)

    except Exception as e:
        current_app.logger.exception("Error searching eBay marketplace")
        return jsonify({'success': False, 'error': 'Failed to search eBay marketplace'}), 500


@api_bp.route('/ebay/search-by-image', methods=['POST'])
@login_required
@csrf_required
def search_by_image() -> ResponseReturnValue:
    """Search eBay using visual/image recognition to find similar items.

    Upload an image and find visually similar items on eBay. Uses eBay's
    Browse API for image-based search capabilities.

    Request Body:
        JSON:
            {
                "image": str,               # Base64 encoded image data / data URL
                "title": Optional[str],     # Optional title for filtering results
                "limit": Optional[int]      # Max results (5-100, default 20)
            }

        multipart/form-data:
            - image_file: uploaded image file
            - title: optional title hint
            - limit: optional max results

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether search succeeded
            - results (list): List of visually similar items
            - count (int): Number of results
            - error (str, optional): Error message if failed

    Status Codes:
        200: Search completed successfully
        400: Image data required
        500: eBay API error or upload failed

    Example Request:
        {
            "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
            "title": "Spider-Man",
            "limit": 20
        }

    Example Response:
        {
            "success": true,
            "results": [
                {
                    "title": "Amazing Spider-Man #300",
                    "price": "$45.99",
                    "imageUrl": "https://...",
                    "itemUrl": "https://ebay.com/itm/..."
                }
            ],
            "count": 18
        }

    Note:
        - Image is uploaded to eBay for comparison
        - Results ordered by visual similarity
        - Optional title filter helps narrow results
        - Supports JPEG, PNG, GIF formats
        - Maximum image size: 10MB
    """
    try:
        request_data = request.get_json(silent=True) or {}
        uploaded_image = request.files.get('image_file')
        image_payload = ''

        if uploaded_image:
            title = request.form.get('title', '')
            limit = request.form.get('limit', 20)
            image_payload = _encode_validated_uploaded_image(uploaded_image)
        else:
            title = request_data.get('title', '')
            limit = request_data.get('limit', 20)
            image_data = request_data.get('image')
            if not isinstance(image_data, str) or not image_data:
                return jsonify({'success': False, 'error': 'Image data is required'}), 400
            image_payload = _encode_validated_base64_image(image_data)

        # Validate limit
        try:
            limit = max(5, min(100, int(limit)))
        except (ValueError, TypeError):
            limit = 20

        # Search eBay by image with configurable limit and optional similarity sorting
        result = ebay_service.search_by_image(image_payload, limit=limit, sort_by_title=title)

        return jsonify(result)

    except UploadValidationError as exc:
        current_app.logger.warning("Rejected image search upload: %s", exc)
        message = exc.args[0] if exc.args else 'Invalid image upload'
        return jsonify({'success': False, 'error': message}), exc.status_code

    except Exception as e:
        current_app.logger.exception("Error searching eBay by image route")
        return jsonify({'success': False, 'error': 'Failed to search eBay by image'}), 500


@api_bp.route('/proxy-image', methods=['GET'])
@login_required
def proxy_image() -> ResponseReturnValue:
    """Proxy S3 images through the server using IAM credentials.

    The S3 bucket blocks all public access, so the browser cannot load images
    directly. This route fetches images via the boto3 S3 client (IAM-authenticated)
    and streams them to the authenticated user.

    Query Parameters:
        url (str): S3 image URL to proxy

    Returns:
        Tuple: (image_bytes, status_code, headers)
            - image_bytes: Raw image data
            - status_code: HTTP status (200 or error code)
            - headers: Content-Type and Cache-Control headers

    Status Codes:
        200: Image successfully proxied
        400: URL parameter missing
        403: URL not from allowed S3 bucket (security)
        404: Image not found in S3
        500: Failed to fetch image from S3

    Example Request:
        GET /api/proxy-image?url=https://bucket.s3.amazonaws.com/users/brian/images/1001_1.jpg

    Security:
        - Only allows S3 URLs from the app's configured bucket
        - Rejects external URLs to prevent abuse
        - Requires authentication (login_required)

    Note:
        - Uses boto3 S3 client with IAM credentials (bucket is private)
        - Browser caches images for 7 days (604800 seconds)
        - Content type inferred from S3 metadata or file extension
    """

    image_url = request.args.get('url')
    if not image_url:
        return jsonify({'error': 'URL parameter required'}), 400

    # Security: Only allow S3 URLs from our bucket
    s3_bucket = current_app.config.get('S3_BUCKET', os.environ.get('S3_BUCKET_NAME', ''))
    if not s3_bucket or 's3.amazonaws.com' not in image_url or s3_bucket not in image_url:
        return jsonify({'error': 'Invalid image URL'}), 403

    try:
        # Extract S3 key from the URL
        # URL format: https://{bucket}.s3.amazonaws.com/{key}
        parsed = urlparse(image_url)
        s3_key = unquote(parsed.path.lstrip('/'))

        # Fetch image from S3 using IAM-authenticated boto3 client
        response = s3_service.client().get_object(Bucket=s3_bucket, Key=s3_key)
        body = response['Body'].read()

        # Determine content type from S3 metadata or file extension
        content_type = response.get('ContentType', '')
        if not content_type or content_type == 'binary/octet-stream':
            if s3_key.endswith('.webp'):
                content_type = 'image/webp'
            elif s3_key.endswith('.png'):
                content_type = 'image/png'
            elif s3_key.endswith('.gif'):
                content_type = 'image/gif'
            else:
                content_type = 'image/jpeg'

        return body, 200, {
            'Content-Type': content_type,
            'Cache-Control': 'public, max-age=604800'
        }
    except Exception as e:
        error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
        if error_code in ('NoSuchKey', '404'):
            return jsonify({'error': 'Image not found'}), 404
        current_app.logger.exception("Error proxying image %s", image_url)
        return jsonify({'error': 'Failed to fetch image'}), 500


@api_bp.route('/google-lens', methods=['GET'])
@login_required
def google_lens_redirect() -> ResponseReturnValue:
    """Redirect to Google Lens using a Lens-compatible image URL.

    For private S3 objects, this route generates a short-lived presigned URL so
    Google can fetch the image. If no usable image URL is available, it falls
    back to Google Images search by title.
    """

    raw_image_url = (request.args.get('url') or '').strip()
    title = (request.args.get('title') or '').strip()
    image_url = raw_image_url

    def _is_public_host(hostname: str) -> bool:
        host = (hostname or '').lower()
        if not host or host in {'localhost', '127.0.0.1', '0.0.0.0'}:
            return False
        if host.endswith('.local'):
            return False
        if host.startswith('10.') or host.startswith('192.168.'):
            return False
        if host.startswith('172.'):
            parts = host.split('.')
            if len(parts) >= 2:
                try:
                    second_octet = int(parts[1])
                    if 16 <= second_octet <= 31:
                        return False
                except ValueError:
                    pass
        return True

    try:
        # Unwrap local proxy URLs: /api/proxy-image?url=<s3_url>
        if image_url:
            parsed_input = urlparse(image_url)
            if parsed_input.path.endswith('/api/proxy-image'):
                nested = parse_qs(parsed_input.query).get('url', [''])[0].strip()
                if nested:
                    image_url = nested

        # Generate a presigned URL when the source is in our private S3 bucket
        if image_url and 's3.amazonaws.com' in image_url:
            s3_bucket = current_app.config.get('S3_BUCKET', os.environ.get('S3_BUCKET_NAME', ''))
            if s3_bucket and s3_bucket in image_url:
                image_url = s3_service.generate_presigned_url(image_url, expires_in=900)

        if image_url:
            parsed = urlparse(image_url)
            if parsed.scheme in {'http', 'https'} and _is_public_host(parsed.hostname or ''):
                lens_url = f"https://lens.google.com/uploadbyurl?url={quote(image_url, safe='')}"
                return redirect(lens_url, code=302)

        if title:
            search_url = f"https://www.google.com/search?tbm=isch&q={quote(title, safe='')}"
            return redirect(search_url, code=302)

        return jsonify({'error': 'No valid image URL or title provided'}), 400
    except Exception:
        current_app.logger.exception("Failed to prepare Google Lens redirect")
        if title:
            search_url = f"https://www.google.com/search?tbm=isch&q={quote(title, safe='')}"
            return redirect(search_url, code=302)
        return jsonify({'error': 'Failed to prepare Google Lens link'}), 500

