"""
User Behavior Tracker

Tracks user interactions to learn preferences:
- Scroll time on items
- Clicks and views
- Color/style preferences
- Purchase patterns
- Browser behavior

Learns from:
1. Time spent viewing items
2. Products clicked vs scrolled past
3. Repeated color/brand patterns
4. Similar items searched after viewing
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
import json

from storage import PostgresStore

logger = logging.getLogger(__name__)


@dataclass
class ViewEvent:
    """Single item view event."""
    item_id: str
    timestamp: datetime
    duration_seconds: float
    interaction_type: str  # 'scroll', 'click', 'favorite', 'purchase'
    scroll_depth: Optional[float] = None  # 0-1 (how much was scrolled)
    came_from: Optional[str] = None  # 'search', 'similar', 'recommendation'


@dataclass
class PreferenceSignal:
    """Detected preference signal."""
    attribute: str  # 'color', 'brand', 'style', 'price_range'
    value: str
    confidence: float  # 0-1
    evidence_count: int  # How many times observed
    last_seen: datetime


class BehaviorTracker:
    """
    Track and analyze user behavior to learn preferences.

    Integrates with browser extension / frontend to track:
    - Scroll events
    - Click events
    - Time on page
    - Favorites
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.db = PostgresStore()
        self.session_file = Path(f"data/behavior_{user_id}.json")

    def track_view(self, event: ViewEvent):
        """Record a view event."""
        # Store in database
        with self.db._cursor() as cur:
            cur.execute("""
                INSERT INTO user_interactions (
                    user_id, item_id, interaction_type,
                    duration_seconds, metadata, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                self.user_id,
                event.item_id,
                event.interaction_type,
                event.duration_seconds,
                json.dumps({
                    'scroll_depth': event.scroll_depth,
                    'came_from': event.came_from
                }),
                event.timestamp
            ))

        logger.info(f"Tracked {event.interaction_type} on {event.item_id} ({event.duration_seconds:.1f}s)")

    def track_scroll_time(
        self,
        item_id: str,
        duration_seconds: float,
        scroll_depth: float = 1.0
    ):
        """Track time spent scrolling past an item."""
        event = ViewEvent(
            item_id=item_id,
            timestamp=datetime.now(timezone.utc),
            duration_seconds=duration_seconds,
            interaction_type='scroll',
            scroll_depth=scroll_depth
        )
        self.track_view(event)

        # Analyze if this indicates interest
        if duration_seconds > 3.0:  # Spent significant time
            self._analyze_item_interest(item_id, duration_seconds)

    def track_click(self, item_id: str, came_from: str = 'search'):
        """Track item click (strong interest signal)."""
        event = ViewEvent(
            item_id=item_id,
            timestamp=datetime.now(timezone.utc),
            duration_seconds=0.0,  # Will be updated when they leave
            interaction_type='click',
            came_from=came_from
        )
        self.track_view(event)

        # Strong signal - analyze immediately
        self._analyze_item_interest(item_id, weight=2.0)

    def track_favorite(self, item_id: str):
        """Track adding to favorites (very strong signal)."""
        event = ViewEvent(
            item_id=item_id,
            timestamp=datetime.now(timezone.utc),
            duration_seconds=0.0,
            interaction_type='favorite'
        )
        self.track_view(event)

        # Very strong signal
        self._analyze_item_interest(item_id, weight=5.0)

    def _analyze_item_interest(self, item_id: str, weight: float = 1.0):
        """Analyze item attributes to detect preferences."""
        # Fetch item details
        with self.db._cursor() as cur:
            cur.execute("""
                SELECT brand, raw_data FROM items WHERE external_id = %s
            """, (item_id,))
            result = cur.fetchone()

        if not result:
            return

        brand, raw_data = result
        metadata = raw_data or {}

        # Extract signals
        signals = []

        # Brand preference
        if brand:
            signals.append(PreferenceSignal(
                attribute='brand',
                value=brand,
                confidence=0.7 * weight,
                evidence_count=1,
                last_seen=datetime.now(timezone.utc)
            ))

        # Color preference
        colors = metadata.get('colors', [])
        for color in colors:
            signals.append(PreferenceSignal(
                attribute='color',
                value=color,
                confidence=0.5 * weight,
                evidence_count=1,
                last_seen=datetime.now(timezone.utc)
            ))

        # Gender preference
        gender = metadata.get('gender')
        if gender:
            signals.append(PreferenceSignal(
                attribute='gender',
                value=gender,
                confidence=0.9 * weight,
                evidence_count=1,
                last_seen=datetime.now(timezone.utc)
            ))

        # Category preference
        category = metadata.get('category')
        if category:
            signals.append(PreferenceSignal(
                attribute='category',
                value=category,
                confidence=0.6 * weight,
                evidence_count=1,
                last_seen=datetime.now(timezone.utc)
            ))

        # Store signals
        self._update_preferences(signals)

    def _update_preferences(self, signals: List[PreferenceSignal]):
        """Update learned preferences with new signals."""
        # Load existing
        prefs = self.load_learned_preferences()

        for signal in signals:
            key = f"{signal.attribute}:{signal.value}"

            if key in prefs:
                # Update existing
                old = prefs[key]
                prefs[key] = PreferenceSignal(
                    attribute=signal.attribute,
                    value=signal.value,
                    confidence=min(1.0, old.confidence * 0.9 + signal.confidence * 0.1),
                    evidence_count=old.evidence_count + signal.evidence_count,
                    last_seen=signal.last_seen
                )
            else:
                # New preference
                prefs[key] = signal

        # Save
        self.save_learned_preferences(prefs)

    def load_learned_preferences(self) -> Dict[str, PreferenceSignal]:
        """Load learned preferences from file."""
        if not self.session_file.exists():
            return {}

        with open(self.session_file, 'r') as f:
            data = json.load(f)

        prefs = {}
        for key, val in data.items():
            prefs[key] = PreferenceSignal(
                attribute=val['attribute'],
                value=val['value'],
                confidence=val['confidence'],
                evidence_count=val['evidence_count'],
                last_seen=datetime.fromisoformat(val['last_seen'])
            )

        return prefs

    def save_learned_preferences(self, prefs: Dict[str, PreferenceSignal]):
        """Save learned preferences to file."""
        self.session_file.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        for key, pref in prefs.items():
            data[key] = {
                'attribute': pref.attribute,
                'value': pref.value,
                'confidence': pref.confidence,
                'evidence_count': pref.evidence_count,
                'last_seen': pref.last_seen.isoformat()
            }

        with open(self.session_file, 'w') as f:
            json.dump(data, f, indent=2)

    def get_top_preferences(self, attribute: Optional[str] = None, limit: int = 10) -> List[PreferenceSignal]:
        """Get top learned preferences."""
        prefs = self.load_learned_preferences()

        # Filter by attribute if specified
        if attribute:
            prefs = {k: v for k, v in prefs.items() if v.attribute == attribute}

        # Sort by confidence * evidence_count
        sorted_prefs = sorted(
            prefs.values(),
            key=lambda p: p.confidence * min(p.evidence_count, 10),  # Cap at 10 to avoid over-weighting
            reverse=True
        )

        return sorted_prefs[:limit]

    def get_personalized_filters(self) -> Dict:
        """Get filters based on learned preferences for deal finding."""
        top_brands = [p.value for p in self.get_top_preferences('brand', 5)]
        top_colors = [p.value for p in self.get_top_preferences('color', 5)]
        top_categories = [p.value for p in self.get_top_preferences('category', 3)]
        top_gender = [p.value for p in self.get_top_preferences('gender', 1)]

        return {
            'preferred_brands': top_brands,
            'preferred_colors': top_colors,
            'preferred_categories': top_categories,
            'preferred_gender': top_gender[0] if top_gender else None
        }

    def analyze_session(self, session_duration: int = 3600) -> Dict:
        """Analyze recent session behavior."""
        cutoff = datetime.now(timezone.utc).timestamp() - session_duration

        with self.db._cursor() as cur:
            # Get recent interactions
            cur.execute("""
                SELECT item_id, interaction_type, duration_seconds
                FROM user_interactions
                WHERE user_id = %s
                  AND EXTRACT(EPOCH FROM created_at) > %s
                ORDER BY created_at DESC
            """, (self.user_id, cutoff))

            interactions = cur.fetchall()

        stats = {
            'total_views': len(interactions),
            'clicks': sum(1 for _, itype, _ in interactions if itype == 'click'),
            'favorites': sum(1 for _, itype, _ in interactions if itype == 'favorite'),
            'avg_scroll_time': 0.0,
            'items_viewed': set()
        }

        scroll_times = [dur for _, itype, dur in interactions if itype == 'scroll']
        if scroll_times:
            stats['avg_scroll_time'] = sum(scroll_times) / len(scroll_times)

        stats['items_viewed'] = list(set(iid for iid, _, _ in interactions))

        return stats


# ==================== Browser Integration ====================

class BrowserBehaviorCapture:
    """
    Captures behavior from browser extension.

    Frontend sends events:
    - Scroll depth on each item
    - Click events
    - Time spent on product pages
    """

    def __init__(self, tracker: BehaviorTracker):
        self.tracker = tracker

    def handle_scroll_event(self, items_in_viewport: List[Dict]):
        """
        Handle scroll event from frontend.

        items_in_viewport: List of {item_id, time_visible_ms, scroll_depth}
        """
        for item_data in items_in_viewport:
            if item_data['time_visible_ms'] > 500:  # Visible for >500ms
                self.tracker.track_scroll_time(
                    item_id=item_data['item_id'],
                    duration_seconds=item_data['time_visible_ms'] / 1000,
                    scroll_depth=item_data.get('scroll_depth', 1.0)
                )

    def handle_click_event(self, item_id: str, came_from: str = 'search'):
        """Handle click event."""
        self.tracker.track_click(item_id, came_from)

    def handle_favorite_event(self, item_id: str):
        """Handle favorite event."""
        self.tracker.track_favorite(item_id)
