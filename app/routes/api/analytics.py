"""Analytics routes - Event tracking and analytics management.

This module handles:
- Tracking user events (clicks, page views, etc.)
- Batch event processing
- Analytics data storage

All functions include type hints and comprehensive docstrings for better IDE support.
"""
import traceback
import json

from flask import request, jsonify, current_app, Response

from app.routes.api import api_bp
from app.models.analytics import AnalyticsStore, AnalyticsEvent
from app.security import rate_limiter, get_real_ip
from app.utils.user_context import get_user_analytics_dir, get_current_username


# Anonymous-tracking hardening limits (H3): defence against log/disk spam and
# oversized payloads pushed from untrusted origins to this un-authed endpoint.
_MAX_TRACK_PAYLOAD_BYTES = 16 * 1024   # 16 KB total
_MAX_TRACK_BATCH_EVENTS = 20           # events per request
_MAX_TRACK_REQS_PER_MIN = 60           # per IP


@api_bp.route('/analytics/track', methods=['POST'])
def track_analytics_event() -> Response:
    """Receive and store analytics events from frontend.

    Tracks user interactions including page views, button clicks, and other events.
    Supports both single events and batch processing for efficiency.

    Public (un-authed) endpoint — hardened with payload size caps, a 20-event
    batch ceiling, and a 60 req/min per-IP rate limit to protect against
    disk-exhaustion and log-flood abuse. Events from sessions without a
    logged-in user are still accepted (they are filed under 'default').
    """
    try:
        # Per-IP throttle: 60 requests/min
        client_ip = get_real_ip(request)
        track_key = f"analytics_track_{client_ip}"
        if rate_limiter:
            rate_limiter.record_request(track_key)
            if rate_limiter.is_rate_limited(track_key, max_requests=_MAX_TRACK_REQS_PER_MIN, window_seconds=60):
                return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429

        # Bound total payload size so a bad actor can't push multi-MB bodies
        content_length = request.content_length or 0
        if content_length > _MAX_TRACK_PAYLOAD_BYTES:
            return jsonify({'success': False, 'error': 'Payload too large'}), 413

        # Try to get JSON data, force=True allows parsing even without proper Content-Type
        data = request.get_json(force=True, silent=True)

        if not data:
            # Fallback: try to parse request.data as JSON (bounded by Flask MAX_CONTENT_LENGTH)
            try:
                raw = request.data[:_MAX_TRACK_PAYLOAD_BYTES].decode('utf-8', errors='replace')
                data = json.loads(raw)
            except Exception:
                return jsonify({'success': False, 'error': 'No valid JSON data provided'}), 400

        # Support batch events
        events_data = data.get('events', [])
        if not events_data and data.get('event_type'):
            # Single event format
            events_data = [data]

        if not events_data:
            return jsonify({'success': False, 'error': 'No events provided'}), 400

        # Cap the batch so one request can't file hundreds of events
        if len(events_data) > _MAX_TRACK_BATCH_EVENTS:
            events_data = events_data[:_MAX_TRACK_BATCH_EVENTS]

        # Initialize analytics store with user-specific directory
        username = get_current_username()
        analytics_dir = str(get_user_analytics_dir())
        store = AnalyticsStore(analytics_dir)

        # Convert to AnalyticsEvent objects
        events = []
        for event_data in events_data:
            if not isinstance(event_data, dict):
                continue
            event = AnalyticsEvent(
                event_type=event_data.get('event_type'),
                page=event_data.get('page'),
                element_id=event_data.get('element_id'),
                x=event_data.get('x'),
                y=event_data.get('y'),
                viewport_width=event_data.get('viewport_width'),
                viewport_height=event_data.get('viewport_height'),
                timestamp=event_data.get('timestamp')
            )
            events.append(event)

        # Save events
        store.save_events_batch(events)
        current_app.logger.debug(f"[User: {username}] Saved {len(events)} analytics events")

        return jsonify({'success': True, 'count': len(events)})

    except Exception as e:
        current_app.logger.error(f"Error tracking analytics: {e}")
        current_app.logger.error(traceback.format_exc())
        # Do NOT leak exception text to anonymous callers
        return jsonify({'success': False, 'error': 'Tracking error'}), 500
