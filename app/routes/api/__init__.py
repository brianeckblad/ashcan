"""API Routes Package - Modular API endpoints.

This package contains API routes split by domain/feature:

Modules:
- admin.py: Admin settings and security (8 routes)
- analytics.py: Analytics tracking (1 route)
- ebay_taxonomy.py: eBay category/taxonomy operations (4 routes)
- system.py: System stats and utilities (6 routes)
- trash.py: Trash management (3 routes)
- snapshots.py: Snapshot operations (4 routes)
- ebay_search.py: eBay price lookup and search (4 routes)
- ebay_listings.py: eBay account listings management (3 routes)
- account.py: User account management (13 routes)
- comics.py: Comic CRUD operations (11 routes)
- ebay.py: eBay listing operations (10 routes)

Total: 67 routes across 11 modules.
"""

from flask import Blueprint

# Main API blueprint - all sub-blueprints register here
api_bp = Blueprint('api', __name__)

# Import ALL route modules (they register their routes on api_bp)
from app.routes.api import (
    admin,
    analytics,
    ebay_taxonomy,
    system,
    trash,
    snapshots,
    ebay_search,
    ebay_listings,
    account,
    comics,
    ebay,
)

__all__ = ['api_bp']

