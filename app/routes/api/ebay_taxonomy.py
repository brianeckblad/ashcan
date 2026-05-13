"""eBay Taxonomy routes - Category search and browsing.

This module handles:
- Searching eBay categories by name
- Getting root categories
- Getting category children (subcategories)
- Getting full category tree

All functions include type hints and comprehensive docstrings for better IDE support.
"""
from flask import request, jsonify, current_app, Response
from app.routes.api import api_bp
from app.routes.auth import login_required
from app.services.ebay_service import ebay_service
from app.utils.logging_utils import safe_error_message


@api_bp.route('/ebay/taxonomy/search', methods=['GET'])
@login_required
def ebay_taxonomy_search() -> Response:
    """Search eBay categories by name using the Taxonomy API.

    Searches for categories matching the query string. Useful for finding
    the correct category ID when creating eBay listings.

    Query Parameters:
        q (str): Search query (minimum 2 characters)
        marketplace_id (str, optional): eBay marketplace (default: "EBAY_US")
            Options: EBAY_US, EBAY_UK, EBAY_DE, etc.

    Returns:
        Response: Flask JSON response containing:
            - success (bool): Whether search succeeded
            - data (dict): Search results with matching categories
            - error (str, optional): Error message if failed

    Status Codes:
        200: Search completed successfully
        400: Invalid query (too short or empty)
        500: eBay API error or server error

    Example Request:
        GET /ebay/taxonomy/search?q=comic&marketplace_id=EBAY_US

    Example Response:
        {
            "success": true,
            "data": {
                "categoryTreeId": "0",
                "categorySuggestions": [
                    {
                        "categoryId": "63",
                        "categoryName": "Comic Books",
                        "categoryTreeNodeLevel": 2
                    }
                ]
            }
        }

    Note:
        - Requires valid eBay OAuth token
        - Query must be at least 2 characters
        - Results include category hierarchy information
    """
    try:
        query = request.args.get('q', '').strip()
        marketplace_id = request.args.get('marketplace_id', 'EBAY_US')

        if not query or len(query) < 2:
            return jsonify({
                'success': False,
                'error': 'Search query must be at least 2 characters'
            }), 400

        result = ebay_service.search_categories(query, marketplace_id)

        if 'error' in result:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 500

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        current_app.logger.error(f"Error searching eBay categories: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e)
        }), 500


@api_bp.route('/ebay/taxonomy/root', methods=['GET'])
@login_required
def ebay_taxonomy_root() -> Response:
    """Get root (top-level) eBay categories.

    Retrieves the highest-level categories in the eBay category hierarchy.
    These are the main category groups like "Collectibles", "Electronics", etc.

    Query Parameters:
        marketplace_id (str, optional): eBay marketplace (default: "EBAY_US")

    Returns:
        Response: Flask JSON response with root categories

    Status Codes:
        200: Successfully retrieved categories
        500: eBay API error

    Example Response:
        {
            "success": true,
            "data": {
                "rootCategoryNode": [
                    {"categoryId": "20081", "categoryName": "Antiques"},
                    {"categoryId": "550", "categoryName": "Art"}
                ]
            }
        }
    """
    try:
        marketplace_id = request.args.get('marketplace_id', 'EBAY_US')

        result = ebay_service.get_root_categories(marketplace_id)

        if 'error' in result:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 500

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching eBay root categories: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e)
        }), 500


@api_bp.route('/ebay/taxonomy/children/<category_id>', methods=['GET'])
@login_required
def ebay_taxonomy_children(category_id: str) -> Response:
    """Get child categories (subcategories) of a specific category.

    Retrieves all subcategories under a given parent category. Used to build
    hierarchical category navigation.

    Path Parameters:
        category_id (str): Parent category ID

    Query Parameters:
        marketplace_id (str, optional): eBay marketplace (default: "EBAY_US")

    Returns:
        Response: Flask JSON response with child categories

    Status Codes:
        200: Successfully retrieved subcategories
        500: eBay API error or category not found

    Example Request:
        GET /ebay/taxonomy/children/63?marketplace_id=EBAY_US

    Example Response:
        {
            "success": true,
            "childCategoryTreeNodes": [
                {"categoryId": "259", "categoryName": "Golden Age"},
                {"categoryId": "260", "categoryName": "Silver Age"}
            ]
        }
    """
    try:
        marketplace_id = request.args.get('marketplace_id', 'EBAY_US')

        result = ebay_service.get_category_children(category_id, marketplace_id)

        if 'error' in result:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 500

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error fetching category children: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e)
        }), 500


@api_bp.route('/ebay/taxonomy/tree', methods=['GET'])
@login_required
def ebay_taxonomy_tree() -> Response:
    """Get complete eBay category tree hierarchy.

    Retrieves the entire category tree for a marketplace. Warning: This can be
    a large response (several MB) as it includes all categories and subcategories.

    Query Parameters:
        marketplace_id (str, optional): eBay marketplace (default: "EBAY_US")

    Returns:
        Response: Flask JSON response with full category tree

    Status Codes:
        200: Successfully retrieved tree
        500: eBay API error

    Example Response:
        {
            "success": true,
            "data": {
                "categoryTreeId": "0",
                "categoryTreeVersion": "119",
                "rootCategoryNode": {
                    "childCategoryTreeNodes": [...]
                }
            }
        }

    Note:
        - Response can be very large (>5MB)
        - Consider caching for performance
        - Use children endpoint for partial tree navigation
    """
    try:
        marketplace_id = request.args.get('marketplace_id', 'EBAY_US')

        result = ebay_service.get_category_tree(marketplace_id)

        if 'error' in result:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 500

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching eBay category tree: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e)
        }), 500
