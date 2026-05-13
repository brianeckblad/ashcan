"""Service for processing and analyzing heatmap data."""
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import json


class HeatmapAnalyzer:
    """Analyzes user interaction data to generate insights."""

    def __init__(self, analytics_store):
        self.store = analytics_store

    def generate_click_heatmap(self, page=None, viewport_width=1920, viewport_height=1080):
        """
        Generate click heatmap data for visualization.
        Returns coordinates and intensity for heat overlay.
        """
        events = self.store.get_all_events()

        if page:
            events = [e for e in events if e['page'] == page]

        click_events = [e for e in events if e['event_type'] == 'click' and e.get('x') and e.get('y')]

        # Normalize coordinates to target viewport
        normalized_clicks = []
        for event in click_events:
            if event.get('viewport_width') and event.get('viewport_height'):
                # Convert to percentage then to target viewport
                x_pct = event['x'] / event['viewport_width']
                y_pct = event['y'] / event['viewport_height']

                normalized_x = int(x_pct * viewport_width)
                normalized_y = int(y_pct * viewport_height)

                normalized_clicks.append({
                    'x': normalized_x,
                    'y': normalized_y,
                    'element': event.get('element_id', 'unknown'),
                    'timestamp': event['timestamp']
                })

        return normalized_clicks

    def generate_scroll_heatmap(self, page=None):
        """Generate scroll depth heatmap."""
        events = self.store.get_all_events()

        if page:
            events = [e for e in events if e['page'] == page]

        scroll_events = [e for e in events if e['event_type'] == 'scroll' and e.get('y')]

        # Group by scroll depth buckets (every 100px)
        scroll_depths = defaultdict(int)
        for event in scroll_events:
            bucket = (event['y'] // 100) * 100
            scroll_depths[bucket] += 1

        return dict(scroll_depths)

    def analyze_user_flows(self, time_window_seconds=30):
        """
        Analyze common user journeys through the application.
        Returns sequences of pages visited.
        """
        events = self.store.get_all_events()
        pageviews = [e for e in events if e['event_type'] == 'pageview']

        # Sort by timestamp
        pageviews.sort(key=lambda x: x['timestamp'])

        # Group into sessions based on time window
        sessions = []
        current_session = []
        last_time = None

        for event in pageviews:
            # Handle JavaScript ISO format with 'Z' suffix
            timestamp = event['timestamp'].replace('Z', '+00:00') if 'Z' in event['timestamp'] else event['timestamp']
            event_time = datetime.fromisoformat(timestamp)

            if last_time is None or (event_time - last_time).total_seconds() <= time_window_seconds:
                current_session.append(event['page'])
            else:
                if current_session:
                    sessions.append(current_session)
                current_session = [event['page']]

            last_time = event_time

        if current_session:
            sessions.append(current_session)

        # Find common flows (sequences of 2-3 pages)
        flow_pairs = Counter()
        flow_triples = Counter()

        for session in sessions:
            # 2-page flows
            for i in range(len(session) - 1):
                flow_pairs[f"{session[i]} → {session[i+1]}"] += 1

            # 3-page flows
            for i in range(len(session) - 2):
                flow_triples[f"{session[i]} → {session[i+1]} → {session[i+2]}"] += 1

        return {
            'total_sessions': len(sessions),
            'top_2_step_flows': flow_pairs.most_common(10),
            'top_3_step_flows': flow_triples.most_common(10),
            'all_sessions': sessions
        }

    def analyze_element_engagement(self, page=None):
        """
        Analyze which elements get the most interaction.
        Includes clicks, hovers, and time spent.
        """
        events = self.store.get_all_events()

        if page:
            events = [e for e in events if e['page'] == page]

        element_data = defaultdict(lambda: {
            'clicks': 0,
            'hovers': 0,
            'first_seen': None,
            'last_seen': None
        })

        for event in events:
            element_id = event.get('element_id')
            if not element_id:
                continue

            timestamp = event['timestamp']

            if event['event_type'] == 'click':
                element_data[element_id]['clicks'] += 1
            elif event['event_type'] == 'hover':
                element_data[element_id]['hovers'] += 1

            # Track first and last interaction
            if element_data[element_id]['first_seen'] is None:
                element_data[element_id]['first_seen'] = timestamp
            element_data[element_id]['last_seen'] = timestamp

        # Calculate engagement score (weighted)
        engagement_scores = []
        for element_id, data in element_data.items():
            score = (data['clicks'] * 10) + (data['hovers'] * 1)
            engagement_scores.append({
                'element': element_id,
                'score': score,
                'clicks': data['clicks'],
                'hovers': data['hovers'],
                'hesitation_rate': data['hovers'] / max(data['clicks'], 1)  # High = users hesitate
            })

        # Sort by score
        engagement_scores.sort(key=lambda x: x['score'], reverse=True)

        return engagement_scores

    def analyze_page_performance(self):
        """Analyze which pages are most/least used."""
        events = self.store.get_all_events()
        pageviews = [e for e in events if e['event_type'] == 'pageview']

        page_stats = defaultdict(lambda: {
            'views': 0,
            'unique_days': set()
        })

        for event in pageviews:
            page = event['page']
            page_stats[page]['views'] += 1

            # Track unique days
            day = event['timestamp'].split('T')[0]
            page_stats[page]['unique_days'].add(day)

        # Convert to list
        result = []
        for page, stats in page_stats.items():
            result.append({
                'page': page,
                'total_views': stats['views'],
                'unique_days': len(stats['unique_days']),
                'avg_views_per_day': stats['views'] / max(len(stats['unique_days']), 1)
            })

        result.sort(key=lambda x: x['total_views'], reverse=True)
        return result

    def identify_drop_off_points(self):
        """Find where users leave the application or stop engaging."""
        flow_data = self.analyze_user_flows()
        sessions = flow_data['all_sessions']

        # Count where sessions end
        last_pages = Counter([session[-1] for session in sessions if session])

        # Count total visits to each page
        all_page_visits = Counter()
        for session in sessions:
            for page in session:
                all_page_visits[page] += 1

        # Calculate drop-off rate
        drop_off_rates = []
        for page in all_page_visits:
            total_visits = all_page_visits[page]
            exits = last_pages.get(page, 0)
            rate = (exits / total_visits) * 100 if total_visits > 0 else 0

            drop_off_rates.append({
                'page': page,
                'total_visits': total_visits,
                'exits': exits,
                'drop_off_rate': round(rate, 2)
            })

        drop_off_rates.sort(key=lambda x: x['drop_off_rate'], reverse=True)
        return drop_off_rates

    def generate_recommendations(self):
        """Generate UX recommendations based on analytics data."""
        recommendations = []

        # Analyze engagement
        engagement = self.analyze_element_engagement()

        # Find high-hesitation elements (lots of hovers, few clicks)
        high_hesitation = [e for e in engagement if e['hesitation_rate'] > 5 and e['clicks'] > 5]
        if high_hesitation:
            recommendations.append({
                'priority': 'high',
                'category': 'Usability',
                'issue': 'Users are hesitating on important elements',
                'elements': [e['element'] for e in high_hesitation[:5]],
                'suggestion': 'These elements receive many hovers but few clicks. Consider making them more prominent, adding tooltips, or clarifying their purpose.'
            })

        # Find rarely used features
        low_engagement = [e for e in engagement if e['score'] < 5 and e['clicks'] < 3]
        if len(low_engagement) > 3:
            recommendations.append({
                'priority': 'medium',
                'category': 'Feature Usage',
                'issue': f'{len(low_engagement)} elements have very low engagement',
                'elements': [e['element'] for e in low_engagement[:5]],
                'suggestion': 'Consider hiding these features in a menu, improving their visibility, or removing them if not essential.'
            })

        # Analyze page performance
        page_perf = self.analyze_page_performance()
        if len(page_perf) > 0:
            least_visited = [p for p in page_perf if p['total_views'] < 10]
            if least_visited:
                recommendations.append({
                    'priority': 'medium',
                    'category': 'Navigation',
                    'issue': 'Some pages are rarely visited',
                    'elements': [p['page'] for p in least_visited],
                    'suggestion': 'These pages have low traffic. Verify if they are needed, improve navigation to them, or consolidate with other pages.'
                })

        # Analyze drop-off points
        drop_offs = self.identify_drop_off_points()
        high_drop_offs = [d for d in drop_offs if d['drop_off_rate'] > 50 and d['total_visits'] > 10]
        if high_drop_offs:
            recommendations.append({
                'priority': 'high',
                'category': 'User Retention',
                'issue': 'High drop-off rates detected',
                'elements': [d['page'] for d in high_drop_offs[:3]],
                'suggestion': 'Users frequently leave from these pages. Review the content, add clear next steps, or reduce friction in the workflow.'
            })

        # Analyze user flows
        flows = self.analyze_user_flows()
        if flows['total_sessions'] > 20:
            recommendations.append({
                'priority': 'low',
                'category': 'User Journey',
                'issue': 'Common user paths identified',
                'elements': [f[0] for f in flows['top_2_step_flows'][:3]],
                'suggestion': 'Optimize these common workflows with shortcuts, quick actions, or streamlined forms.'
            })

        return recommendations
