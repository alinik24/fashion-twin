"""General-purpose activity logger — domain-agnostic, consent-gated.

Beyond fashion, the system can learn from any daily activity:
  - Reading habits (articles, books)
  - Food choices (restaurant visits, recipe searches)
  - Travel searches
  - Tech/product browsing
  - Fitness tracking

When the user enables a domain, all signals are captured and can later
be used to build a general preference model or cross-domain recommendations.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from config import get_settings
from .consent import ConsentManager

logger = logging.getLogger(__name__)


KNOWN_DOMAINS = {
    "fashion":  "Clothing, shoes, accessories on second-hand markets",
    "food":     "Restaurants, recipes, grocery choices",
    "travel":   "Flights, hotels, destinations",
    "tech":     "Gadgets, apps, software",
    "fitness":  "Workouts, sports equipment, health",
    "reading":  "Articles, books, newsletters",
    "shopping": "General product purchases",
    "home":     "Furniture, décor, homeware",
    "beauty":   "Skincare, makeup, fragrances",
}


@dataclass
class ActivityEvent:
    domain: str
    activity_type: str
    payload: dict = field(default_factory=dict)
    source_url: Optional[str] = None
    session_id: Optional[str] = None
    user_id: int = 1
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ActivityLogger:
    """
    Log any real-world activity across any domain.
    Usage:
        logger = ActivityLogger()
        logger.log("food", "view", {"restaurant": "Ottolenghi", "cuisine": "Israeli"})
        logger.log("travel", "search", {"destination": "Tokyo", "dates": "May 2025"})
    """

    def __init__(self, consent: Optional[ConsentManager] = None) -> None:
        self._consent = consent or ConsentManager()

    def log(
        self,
        domain: str,
        activity_type: str,
        payload: Optional[dict] = None,
        source_url: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: int = 1,
    ) -> Optional[ActivityEvent]:
        """
        Log an activity. Returns None if consent not granted for domain.

        Args:
            domain:         one of KNOWN_DOMAINS or a custom string
            activity_type:  browse|search|view|purchase|read|favorite|…
            payload:        arbitrary metadata about the activity
            source_url:     origin URL if applicable
        """
        if not self._consent.is_allowed(domain):
            logger.debug("Activity ignored — no consent for domain '%s'", domain)
            return None

        event = ActivityEvent(
            domain=domain,
            activity_type=activity_type,
            payload=payload or {},
            source_url=source_url,
            session_id=session_id,
            user_id=user_id,
        )
        self._persist(event)
        return event

    def _persist(self, event: ActivityEvent) -> None:
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO activity_log
                               (user_id, session_id, domain, activity_type,
                                payload, source_url, consent_granted)
                           VALUES (%s, %s, %s, %s, %s, %s, TRUE)""",
                        (
                            event.user_id,
                            event.session_id,
                            event.domain,
                            event.activity_type,
                            json.dumps(event.payload),
                            event.source_url,
                        ),
                    )
        except Exception as exc:
            logger.debug("Activity persist failed: %s", exc)

    # ── Query helpers ─────────────────────────────────────────────────────────

    def get_recent(
        self,
        domain: Optional[str] = None,
        limit: int = 100,
        user_id: int = 1,
    ) -> list[dict]:
        from storage import PostgresStore
        sql = "SELECT * FROM activity_log WHERE user_id = %s"
        args: list[Any] = [user_id]
        if domain:
            sql += " AND domain = %s"
            args.append(domain)
        sql += " ORDER BY created_at DESC LIMIT %s"
        args.append(limit)
        with PostgresStore() as db:
            db.connect()
            with db._cursor() as cur:
                cur.execute(sql, args)
                return [dict(r) for r in cur.fetchall()]

    def domain_summary(self, user_id: int = 1) -> dict[str, int]:
        """Return activity count per domain."""
        from storage import PostgresStore
        sql = """SELECT domain, COUNT(*) as cnt
                 FROM activity_log
                 WHERE user_id = %s
                 GROUP BY domain
                 ORDER BY cnt DESC"""
        with PostgresStore() as db:
            db.connect()
            with db._cursor() as cur:
                cur.execute(sql, (user_id,))
                return {r["domain"]: r["cnt"] for r in cur.fetchall()}
