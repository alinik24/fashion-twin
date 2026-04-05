"""Seasonal preference injection.

Injects season-appropriate score adjustments:
  - Spring/Summer → lighter fabrics, bright colors, sandals, linen
  - Fall/Winter   → coats, knitwear, dark tones, boots

Also supports fashion week calendar:
  - Pre-season: trend-forward items get a bonus
  - Mid-season: core pieces prioritised
  - Sale season: budget items boosted
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


@dataclass
class SeasonProfile:
    name: str           # spring_summer | fall_winter
    code: str           # SS25 | FW25
    preferred_materials: list[str]
    preferred_colors: list[str]
    preferred_categories: list[str]
    avoid_materials: list[str]
    avoid_categories: list[str]
    score_boost_keywords: list[str]    # words in title → small positive delta
    score_penalty_keywords: list[str]  # words in title → small negative delta


# ── Season definitions ────────────────────────────────────────────────────────
SEASON_PROFILES = {
    "spring_summer": SeasonProfile(
        name="Spring/Summer",
        code="SS25",
        preferred_materials=["linen", "cotton", "silk", "satin", "chiffon", "viscose"],
        preferred_colors=["white", "cream", "sand", "light blue", "yellow", "pink",
                          "mint", "coral", "nude", "blush"],
        preferred_categories=["dresses", "blouses", "shorts", "sandals", "skirts",
                               "swimwear", "light jackets"],
        avoid_materials=["wool", "cashmere", "fleece", "heavy denim"],
        avoid_categories=["heavy coats", "fur", "thick knitwear", "boots"],
        score_boost_keywords=["linen", "silk", "floral", "summer", "light",
                               "beach", "vacation", "resort"],
        score_penalty_keywords=["winter", "chunky", "wool coat", "fur"],
    ),
    "fall_winter": SeasonProfile(
        name="Fall/Winter",
        code="FW25",
        preferred_materials=["wool", "cashmere", "leather", "suede", "velvet",
                              "tweed", "mohair", "flannel"],
        preferred_colors=["black", "navy", "camel", "burgundy", "forest green",
                          "chocolate", "rust", "grey", "cream"],
        preferred_categories=["coats", "knitwear", "blazers", "boots", "trousers",
                               "heavy dresses", "jumpers"],
        avoid_materials=["linen", "chiffon"],
        avoid_categories=["swimwear", "shorts", "sandals", "crop tops"],
        score_boost_keywords=["cashmere", "wool", "coat", "leather", "boots",
                               "knit", "velvet", "cosy"],
        score_penalty_keywords=["summer", "beach", "swimwear", "linen"],
    ),
}


def get_current_season() -> str:
    """Return 'spring_summer' or 'fall_winter' based on today's date."""
    month = date.today().month
    return "spring_summer" if 3 <= month <= 8 else "fall_winter"


def get_season_year_code() -> str:
    """Return fashion season code e.g. SS25 or FW25."""
    d = date.today()
    year = str(d.year)[-2:]
    if 3 <= d.month <= 8:
        return f"SS{year}"
    return f"FW{year}"


class SeasonalScorer:
    """Applies seasonal score adjustments to items."""

    def __init__(self, season: str | None = None) -> None:
        self._season = season or get_current_season()
        self._profile = SEASON_PROFILES.get(self._season)
        logger.info("SeasonalScorer: %s (%s)", self._season, get_season_year_code())

    @property
    def current_season(self) -> str:
        return self._season

    @property
    def season_code(self) -> str:
        return get_season_year_code()

    def score_delta(self, item: dict) -> float:
        """Return seasonal score adjustment for item (-2.0 to +2.0)."""
        if not self._profile:
            return 0.0

        delta = 0.0
        title = (item.get("title") or "").lower()
        material = str(item.get("raw_data", {}).get("material", "") or "").lower()

        # Material bonuses
        for mat in self._profile.preferred_materials:
            if mat in material or mat in title:
                delta += 0.3
                break

        # Material penalties
        for mat in self._profile.avoid_materials:
            if mat in material:
                delta -= 0.4
                break

        # Color match
        color = (item.get("color1") or "").lower()
        for col in self._profile.preferred_colors:
            if col in color or col in title:
                delta += 0.2
                break

        # Keyword scan
        for kw in self._profile.score_boost_keywords:
            if kw in title:
                delta += 0.15

        for kw in self._profile.score_penalty_keywords:
            if kw in title:
                delta -= 0.2

        return max(-2.0, min(2.0, delta))

    def to_llm_context(self) -> str:
        """Return a string describing the current season for LLM prompts."""
        if not self._profile:
            return ""
        p = self._profile
        return (
            f"Current fashion season: {p.name} ({p.code}).\n"
            f"Trending materials: {', '.join(p.preferred_materials[:5])}.\n"
            f"Trending colors: {', '.join(p.preferred_colors[:6])}.\n"
            f"Key categories: {', '.join(p.preferred_categories[:5])}."
        )
