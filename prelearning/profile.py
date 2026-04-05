"""Style profile manager — structured representation of user taste.

The style profile is the source of truth for:
  1. What the user explicitly told the system (rules, seeds)
  2. What the system inferred from interactions and RLHF
  3. Seasonal adjustments from season.py

Attributes use a namespaced key:
  preferred_color:white
  blocked_material:polyester
  liked_brand:Sandro
  preferred_size:M
  preferred_condition:new_with_tags,very_good
  price_ceiling:150
  preferred_aesthetic:quiet_luxury
  body_type:hourglass
  style_words:minimal,feminine,timeless

The profile is serialised to JSON for LLM prompts and stored in PostgreSQL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from config import get_settings

logger = logging.getLogger(__name__)

# Default profile template (populated during setup)
DEFAULT_PROFILE: dict[str, Any] = {
    "preferred_size": [],
    "preferred_condition": ["new_with_tags", "very_good", "good"],
    "price_ceiling": None,
    "preferred_colors": [],
    "blocked_materials": [],
    "liked_brands": [],
    "blocked_brands": [],
    "preferred_aesthetics": [],
    "style_words": [],
    "body_notes": "",
}


@dataclass
class ProfileAttribute:
    attribute: str
    value: str
    strength: float = 1.0   # 0–1 confidence
    source: str = "explicit"  # explicit | inferred | rlhf | rule


class StyleProfileManager:
    """Read/write the user's style profile from PostgreSQL + local JSON fallback."""

    def __init__(self, user_id: int = 1) -> None:
        self._user_id = user_id
        self._cfg = get_settings()
        self._cache: Optional[list[ProfileAttribute]] = None

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all(self, source: Optional[str] = None) -> list[ProfileAttribute]:
        """Load all active profile attributes."""
        if self._cache is not None:
            return self._cache
        try:
            from storage import PostgresStore
            sql = """SELECT attribute, value, strength, source
                     FROM style_profile
                     WHERE user_id = %s AND active = TRUE"""
            args: list = [self._user_id]
            if source:
                sql += " AND source = %s"
                args.append(source)
            sql += " ORDER BY strength DESC"
            with PostgresStore() as db:
                db.connect()
                with db._cursor() as cur:
                    cur.execute(sql, args)
                    rows = cur.fetchall()
            self._cache = [
                ProfileAttribute(
                    attribute=r["attribute"],
                    value=r["value"],
                    strength=float(r["strength"] or 1.0),
                    source=r["source"] or "explicit",
                )
                for r in rows
            ]
        except Exception as exc:
            logger.debug("Profile DB load failed: %s — using local file", exc)
            self._cache = self._load_from_file()
        return self._cache

    def to_dict(self) -> dict:
        """Return profile as grouped dict for programmatic use."""
        attrs = self.get_all()
        result: dict[str, Any] = {}
        for attr in attrs:
            key = attr.attribute
            if key not in result:
                result[key] = []
            result[key].append(attr.value)
        # Flatten single-value keys
        for key in list(result.keys()):
            if len(result[key]) == 1:
                result[key] = result[key][0]
        return result

    def to_llm_dict(self) -> dict:
        """
        Return profile as a clean dict suitable for LLM prompt injection.
        Includes season context.
        """
        from prelearning.season import SeasonalScorer
        d = self.to_dict()
        season = SeasonalScorer()
        d["current_season"] = season.season_code
        d["season_preferred_materials"] = season._profile.preferred_materials[:5] if season._profile else []
        d["season_preferred_colors"] = season._profile.preferred_colors[:5] if season._profile else []
        return d

    # ── Write ─────────────────────────────────────────────────────────────────

    def set(
        self,
        attribute: str,
        value: str,
        strength: float = 1.0,
        source: str = "explicit",
    ) -> None:
        """Upsert a profile attribute."""
        self._cache = None  # invalidate cache
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO style_profile
                               (user_id, attribute, value, strength, source, active)
                           VALUES (%s, %s, %s, %s, %s, TRUE)
                           ON CONFLICT DO NOTHING""",
                        (self._user_id, attribute, value, strength, source),
                    )
            self._save_to_file()
        except Exception as exc:
            logger.warning("Profile set failed: %s", exc)

    def set_many(self, attributes: list[ProfileAttribute]) -> None:
        for attr in attributes:
            self.set(attr.attribute, attr.value, attr.strength, attr.source)

    def deactivate(self, attribute: str, value: Optional[str] = None) -> None:
        """Remove/deactivate a profile attribute."""
        self._cache = None
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    if value:
                        cur.execute(
                            "UPDATE style_profile SET active=FALSE WHERE user_id=%s AND attribute=%s AND value=%s",
                            (self._user_id, attribute, value),
                        )
                    else:
                        cur.execute(
                            "UPDATE style_profile SET active=FALSE WHERE user_id=%s AND attribute=%s",
                            (self._user_id, attribute),
                        )
        except Exception as exc:
            logger.warning("Profile deactivate failed: %s", exc)

    # ── Interactive setup ─────────────────────────────────────────────────────

    def run_interactive_setup(self) -> None:
        """CLI wizard to seed the style profile from scratch."""
        print("\n╔══════════════════════════════════════════════╗")
        print("║   Fashion Twin — Style Profile Setup         ║")
        print("╚══════════════════════════════════════════════╝\n")
        print("Answer a few questions to pre-train your taste profile.")
        print("Press Enter to skip any question.\n")

        questions = [
            ("preferred_size",   "Your clothing size(s) (e.g. M, 38, S/M)"),
            ("price_ceiling",    "Maximum budget per item in GBP/EUR (e.g. 150)"),
            ("liked_brands",     "Favourite brands (comma-separated, e.g. Sandro, Toteme)"),
            ("blocked_brands",   "Brands to NEVER show (comma-separated)"),
            ("blocked_materials","Materials to avoid (e.g. polyester, acrylic, fur)"),
            ("preferred_colors", "Favourite colours (e.g. black, navy, camel)"),
            ("style_words",      "Words that describe your style (e.g. minimal, classic, feminine)"),
            ("preferred_aesthetics", "Aesthetic labels (e.g. quiet luxury, old money, coastal)"),
            ("body_notes",       "Anything about fit/body you want the system to know"),
        ]

        for attribute, question in questions:
            answer = input(f"  {question}: ").strip()
            if not answer:
                continue
            # Split comma-separated values
            for val in answer.split(","):
                val = val.strip()
                if val:
                    self.set(attribute, val, strength=1.0, source="explicit")

        print("\n✓ Profile saved. Run scripts/train_ranker.py to apply.")

    # ── LLM-powered profile summary ───────────────────────────────────────────

    def generate_summary(self) -> str:
        """Use GPT-5-mini to generate a natural-language summary of the profile."""
        from llm import get_fast_llm
        profile = self.to_dict()
        if not profile:
            return "No style profile set yet."
        llm = get_fast_llm()
        resp = llm.system_user(
            system="You are a personal stylist summarising a user's fashion preferences.",
            user=f"Summarise this style profile in 3 sentences:\n{json.dumps(profile, indent=2)}",
            max_tokens=200,
        )
        return resp

    # ── File fallback ─────────────────────────────────────────────────────────

    def _load_from_file(self) -> list[ProfileAttribute]:
        fp = self._cfg.style_profile_file
        if not fp.exists():
            return []
        try:
            data = json.loads(fp.read_text())
            return [
                ProfileAttribute(**item) for item in data
                if isinstance(item, dict)
            ]
        except Exception:
            return []

    def _save_to_file(self) -> None:
        try:
            attrs = self.get_all()
            fp = self._cfg.style_profile_file
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(
                json.dumps(
                    [{"attribute": a.attribute, "value": a.value,
                      "strength": a.strength, "source": a.source}
                     for a in attrs],
                    indent=2,
                )
            )
        except Exception as exc:
            logger.debug("Profile file save failed: %s", exc)
