"""Analytics data models for tracking user interactions."""
from datetime import datetime, timedelta, timezone
import json
import os
# Deferred import: avoids initialization-order issues when this module is
# imported before the Flask app context is ready (e.g., at startup sync).
# Use get_user_analytics_dir() only inside methods, not at module-level code.
from app.utils.user_context import get_user_analytics_dir


class AnalyticsEvent:
    """Individual analytics event (click, pageview, etc)."""

    def __init__(self, event_type, page, element_id, x=None, y=None,
                 viewport_width=None, viewport_height=None, timestamp=None):
        self.event_type = event_type  # 'click', 'hover', 'pageview', 'scroll'
        self.page = page
        self.element_id = element_id
        self.x = x  # Mouse X position
        self.y = y  # Mouse Y position
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {
            'event_type': self.event_type,
            'page': self.page,
            'element_id': self.element_id,
            'x': self.x,
            'y': self.y,
            'viewport_width': self.viewport_width,
            'viewport_height': self.viewport_height,
            'timestamp': self.timestamp
        }


class AnalyticsStore:
    """Manages storage and retrieval of analytics data with user isolation."""

    def __init__(self, data_dir=None):
        if data_dir:
            self.data_dir = data_dir
        else:
            # Use user-specific analytics directory
            self.data_dir = str(get_user_analytics_dir())

        self.events_file = os.path.join(self.data_dir, 'analytics_events.jsonl')
        self.ensure_directory()

    def ensure_directory(self):
        """Create analytics directory if it doesn't exist."""
        os.makedirs(self.data_dir, exist_ok=True)

    def save_event(self, event):
        """Append event to JSONL file."""
        with open(self.events_file, 'a') as f:
            f.write(json.dumps(event.to_dict()) + '\n')

    def save_events_batch(self, events):
        """Save multiple events at once."""
        with open(self.events_file, 'a') as f:
            for event in events:
                f.write(json.dumps(event.to_dict()) + '\n')

    def get_all_events(self, limit=None):
        """Load all events from storage."""
        if not os.path.exists(self.events_file):
            return []

        events = []
        with open(self.events_file, 'r') as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

        if limit:
            return events[-limit:]
        return events

    def get_events_by_page(self, page):
        """Get all events for a specific page."""
        all_events = self.get_all_events()
        return [e for e in all_events if e['page'] == page]

    def get_events_by_type(self, event_type):
        """Get all events of a specific type."""
        all_events = self.get_all_events()
        return [e for e in all_events if e['event_type'] == event_type]

    def clear_old_events(self, days=30):
        """Remove events older than specified days."""
        if not os.path.exists(self.events_file):
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = self.get_all_events()

        # Filter events
        kept_events = [
            e for e in events
            if datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00') if 'Z' in e['timestamp'] else e['timestamp']) > cutoff
        ]

        # Rewrite file
        with open(self.events_file, 'w') as f:
            for event in kept_events:
                f.write(json.dumps(event) + '\n')

    def get_stats(self):
        """Get summary statistics."""
        events = self.get_all_events()

        if not events:
            return {
                'total_events': 0,
                'total_clicks': 0,
                'total_pageviews': 0,
                'total_hovers': 0,
                'total_scrolls': 0,
                'pages': {},
                'top_elements': []
            }

        stats = {
            'total_events': len(events),
            'total_clicks': 0,
            'total_pageviews': 0,
            'total_hovers': 0,
            'total_scrolls': 0,
            'pages': {},
            'element_clicks': {}
        }

        for event in events:
            event_type = event['event_type']
            page = event['page']
            element_id = event.get('element_id', 'unknown')

            # Count by type
            if event_type == 'click':
                stats['total_clicks'] += 1
                key = f"{page}::{element_id}"
                stats['element_clicks'][key] = stats['element_clicks'].get(key, 0) + 1
            elif event_type == 'pageview':
                stats['total_pageviews'] += 1
            elif event_type == 'hover':
                stats['total_hovers'] += 1
            elif event_type == 'scroll':
                stats['total_scrolls'] += 1

            # Count by page
            if page not in stats['pages']:
                stats['pages'][page] = 0
            stats['pages'][page] += 1

        # Get top elements
        stats['top_elements'] = sorted(
            stats['element_clicks'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:20]

        return stats
