"""Page rendering routes for the web application."""
from flask import Blueprint, render_template, send_file, current_app, jsonify, request, session
from app.routes.auth import login_required, csrf_required
from app.services.comic_service import comic_service
from app.services.s3_service import s3_service
from app.services.csv_service import CSVService
from app.services.analytics_service import HeatmapAnalyzer
from app.models.analytics import AnalyticsStore
from app.models.user import UserManager
from app.utils.logging_utils import safe_error_message
from app.utils.user_context import get_current_username, get_user_csv_file, get_user_analytics_dir
from app.utils.whatnot_validators import (
    WHATNOT_FIELD_VALIDATION,
    build_whatnot_export_row,
    get_whatnot_export_fieldnames,
    is_whatnot_listed,
)
from app.utils.ebay_validators import EBAY_FIELD_VALIDATION, populate_ebay_fields_from_item
from app.utils.csv_sanitizer import sanitize_row
from datetime import datetime
import os
import csv
import io
import traceback

main_bp = Blueprint('main', __name__)
user_manager = UserManager()


def _get_default_view() -> str:
    """Return the current user's default view preference ('grid' or 'list')."""
    username = session.get('username')
    if username:
        prefs = user_manager.get_preferences(username) or {}
        view = prefs.get('default_view', 'grid')
        if view in ('grid', 'list'):
            return view
    return 'grid'


@main_bp.route('/')
@login_required
def landing():
    """
    Display the application landing page.

    Shows an overview of the application with system statistics and
    quick access links to core features.
    """
    # Get the polling interval for system statistics updates (in milliseconds)
    stats_interval = current_app.config.get('SYSTEM_STATS_INTERVAL', 60000)
    return render_template('landing.html', active_page='home', stats_interval=stats_interval)


@main_bp.route('/add')
@login_required
def add_comic():
    """
    Display the comic form for adding or editing an item.

    Pre-populates the next available SKU and validation rules for
    client-side validation in the web form.
    """

    # Get the next available SKU to suggest to the user
    next_sku = comic_service.get_current_sku()
    return render_template('index.html',
                         next_sku=next_sku,
                         validation_data=WHATNOT_FIELD_VALIDATION,
                         active_page='add')


@main_bp.route('/add-from-image')
@login_required
def add_from_image():
    """Display the streamlined "Add Comic From Image" intake page.

    The user uploads or photographs a single cover image. The page searches
    eBay for visually similar comics, lets the user pick the closest match,
    then hands off to the standard ``/add`` form with the user's photo and
    the matched listing's metadata pre-filled.
    """
    return render_template('add_from_image.html', active_page='add')


@main_bp.route('/browse')
@login_required
def browse_comics():
    """Display the comic inventory browsing page."""
    return render_template('comics_list.html', active_page='browse', default_view=_get_default_view())


@main_bp.route('/trash')
@login_required
def trash():
    """Display the trash/deleted items management page."""
    return render_template('trash.html', active_page='trash')


@main_bp.route('/download')
@login_required
def download_csv():
    """
    Download the inventory CSV file, optionally filtered by listing type.

    Supports downloading the complete inventory or a filtered subset
    containing only items of a specific type (For Sale or Giveaway).
    Creates a backup copy in S3 before sending the file.

    Query Parameters:
        listing_type (str, optional): Filter by listing type
                                      ('For Sale' or 'Giveaway').
        platform (str, optional): When ``whatnot``, export in full WhatNot CSV
                                  format and only include items tagged as listed
                                  on WhatNot.
    """
    try:

        # Get filter parameter from query string
        listing_type = request.args.get('listing_type', '', type=str).strip()
        platform = request.args.get('platform', '', type=str).strip().lower()

        # Use user-specific CSV file
        username = get_current_username()
        csv_path = get_user_csv_file()

        if not os.path.exists(csv_path):
            return jsonify({'success': False, 'message': 'No inventory file found'}), 404

        # Generic full inventory export (used outside the WhatNot management UI).
        # Keep this behavior only when no WhatNot-specific export context was requested.
        if not listing_type and platform != 'whatnot':

            # Create a backup copy in S3 with timestamp for historical tracking
            s3_service.backup_csv_to_s3(str(csv_path))
            current_app.logger.info(f"[User: {username}] Downloaded CSV export")

            service = CSVService(str(csv_path))
            fieldnames = service._get_all_fieldnames()
            comics = service.read_all()

            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction='ignore', quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for comic in comics:
                writer.writerow(sanitize_row(comic.to_dict()))
            buf.seek(0)
            return send_file(
                io.BytesIO(buf.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name='comics_export.csv'
            )

        if listing_type:
            result = comic_service.get_comics_paginated(
                page=1,
                per_page=1000000,
                listing_type=listing_type,
            )
            candidate_comics = result['comics']
        else:
            candidate_comics = comic_service.get_all_comics()

        # WhatNot exports should only include items explicitly tagged as listed.
        whatnot_tagged = [comic for comic in candidate_comics if is_whatnot_listed(comic)]

        # Build CSV in memory with filtered comics
        output = io.StringIO()
        fieldnames = get_whatnot_export_fieldnames()

        writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        if whatnot_tagged:
            # Write each WhatNot-tagged comic in the full validator-defined WhatNot format
            for comic in whatnot_tagged:
                writer.writerow(sanitize_row(build_whatnot_export_row(comic)))

        # Convert to bytes and send as download
        output.seek(0)
        if listing_type:
            filename = f'whatnot_export_{listing_type.lower().replace(" ", "_")}.csv'
        else:
            filename = 'whatnot_export_all_listed.csv'

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        current_app.logger.error(f"[User: {get_current_username()}] Error downloading CSV: {e}")
        return jsonify({'success': False, 'message': 'An error occurred during download'}), 500


@main_bp.route('/download/ebay')
@login_required
def download_ebay_csv():
    """
    Download inventory as eBay File Exchange format CSV.

    Generates a CSV formatted for bulk import into eBay's selling tools.
    Only includes items marked as 'For Sale' (excludes Giveaways).
    """
    try:
        # Retrieve all comics from inventory
        all_comics = comic_service.get_all_comics()

        # Filter out giveaways — eBay listings are only for items for sale
        comics = [comic for comic in all_comics if comic.listing_type != 'Giveaway']

        if not comics:
            return jsonify({'success': False, 'message': 'No items for sale found in inventory'}), 404

        # Build CSV in memory
        output = io.StringIO()

        # Get column order and definitions from eBay validator
        fieldnames = list(EBAY_FIELD_VALIDATION.keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)

        # Write header row
        writer.writeheader()

        # Write each item as a row using eBay field mapping
        for comic in comics:
            # Auto-populate eBay-specific fields from item data
            ebay_data = populate_ebay_fields_from_item(comic)

            # Add any missing default values
            for field, rules in EBAY_FIELD_VALIDATION.items():
                if field not in ebay_data and 'default' in rules:
                    ebay_data[field] = rules['default']

            # Fill in any remaining empty fields
            for field in fieldnames:
                if field not in ebay_data:
                    ebay_data[field] = ''

            # Sanitize cells against spreadsheet formula injection
            writer.writerow(sanitize_row(ebay_data))

        # Prepare file for download
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),  # Add BOM for Excel compatibility
            mimetype='text/csv',
            as_attachment=True,
            download_name='ebay_file_exchange.csv'
        )

    except Exception as e:
        current_app.logger.error(f"[User: {get_current_username()}] Error generating eBay CSV: {e}")
        return jsonify({'success': False, 'message': 'An error occurred generating eBay CSV'}), 500


@main_bp.route('/price-lookup')
@login_required
def price_lookup():
    """eBay price lookup page."""
    return render_template('price_lookup.html', active_page='prices', default_view=_get_default_view())


@main_bp.route('/account')
@login_required
def account():
    """Account settings page."""
    username = session.get('username', 'Unknown')
    return render_template('account.html', username=username, active_page='account')


@main_bp.route('/ebay-listings')
@login_required
def ebay_listings():
    """eBay listings summary page showing active and pending listings."""
    return render_template('ebay_listings.html', active_page='ebay-listings')


@main_bp.route('/admin/analytics')
@login_required
def analytics_dashboard():
    """Analytics and heatmap dashboard."""
    return render_template('analytics_dashboard.html', active_page='analytics')


@main_bp.route('/admin/analytics/data')
@login_required
def analytics_data():
    """Get analytics data as JSON."""

    data_type = 'summary'
    try:
        # Use user-specific analytics directory
        analytics_dir = str(get_user_analytics_dir())
        store = AnalyticsStore(analytics_dir)
        analyzer = HeatmapAnalyzer(store)

        # Get query parameters
        page_filter = request.args.get('page')
        data_type = request.args.get('type', 'summary')

        if data_type == 'summary':
            stats = store.get_stats()
            return jsonify(stats)

        elif data_type == 'clicks':
            viewport_width = request.args.get('width', 1920, type=int)
            viewport_height = request.args.get('height', 1080, type=int)
            clicks = analyzer.generate_click_heatmap(page_filter, viewport_width, viewport_height)
            return jsonify({'clicks': clicks})

        elif data_type == 'scrolls':
            scrolls = analyzer.generate_scroll_heatmap(page_filter)
            return jsonify({'scrolls': scrolls})

        elif data_type == 'flows':
            flows = analyzer.analyze_user_flows()
            return jsonify(flows)

        elif data_type == 'engagement':
            engagement = analyzer.analyze_element_engagement(page_filter)
            return jsonify({'engagement': engagement})

        elif data_type == 'pages':
            pages = analyzer.analyze_page_performance()
            return jsonify({'pages': pages})

        elif data_type == 'dropoffs':
            dropoffs = analyzer.identify_drop_off_points()
            return jsonify({'dropoffs': dropoffs})

        elif data_type == 'recommendations':
            recommendations = analyzer.generate_recommendations()
            return jsonify({'recommendations': recommendations})

        else:
            return jsonify({'error': 'Invalid data type'}), 400

    except Exception as e:
        username = get_current_username()
        current_app.logger.error(f"[User: {username}] Error in analytics_data for type={data_type}: {e}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'error': safe_error_message(e),
            'type': data_type,
            'message': f'Failed to load {data_type} data'
        }), 500


@main_bp.route('/admin/analytics/export')
@login_required
def analytics_export():
    """Export analytics data as CSV."""

    # Use user-specific analytics directory
    analytics_dir = str(get_user_analytics_dir())
    store = AnalyticsStore(analytics_dir)

    events = store.get_all_events()

    # Create CSV
    output = io.StringIO()
    if events:
        fieldnames = list(events[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for ev in events:
            writer.writerow(sanitize_row(ev))

    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'analytics_export_{timestamp}.csv'
    )


@main_bp.route('/admin/analytics/clear', methods=['POST'])
@login_required
@csrf_required
def analytics_clear():
    """Clear all analytics data."""

    try:
        # Use user-specific analytics directory
        username = get_current_username()
        analytics_dir = str(get_user_analytics_dir())
        store = AnalyticsStore(analytics_dir)

        # Get count before clearing
        events = store.get_all_events()
        event_count = len(events)

        # Clear the events file
        if os.path.exists(store.events_file):
            os.remove(store.events_file)
            current_app.logger.info(f"[User: {username}] Cleared {event_count} analytics events")

        return jsonify({
            'success': True,
            'message': f'Cleared {event_count} analytics events',
            'events_deleted': event_count
        })

    except Exception as e:
        current_app.logger.error(f"[User: {get_current_username()}] Error clearing analytics data: {e}")
        return jsonify({
            'success': False,
            'error': safe_error_message(e)
        }), 500
