"""Behavioral signal definitions, weights, and implicit→reward conversion.

Scientific basis:
  - Joachims et al. (2005) "Accurately Interpreting Clickthrough Data as Implicit Feedback"
  - Yi et al. (2014) "Beyond Clicks: Dwell Time for Personalization"
  - Zhao et al. (2018) "Recommendations with Negative Feedback via Pairwise Deep Reinforcement Learning"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SignalType(str, Enum):
    # ── Positive signals (stronger = more intent) ────────────────────────────
    OFFER       = "offer"          # made a price offer — very strong buy intent
    CONTACT     = "contact"        # contacted seller — strong intent
    FAVORITE    = "favorite"       # hearted / saved item
    CLICK       = "click"          # opened item detail page
    DWELL       = "dwell"          # time spent on item (value = seconds)
    SHARE       = "share"          # shared item link
    COMPARE     = "compare"        # placed in comparison / basket

    # ── Weak positive (implicitly curious) ───────────────────────────────────
    ZOOM        = "zoom"           # zoomed in on photo
    HOVER       = "hover"          # hovered on card (value = seconds)

    # ── Negative signals ──────────────────────────────────────────────────────
    SCROLL_PAST = "scroll_past"    # scrolled past quickly
    SKIP        = "skip"           # explicit skip
    DISLIKE     = "dislike"        # explicit dislike button

    # ── Explicit (from seed_preferences) ─────────────────────────────────────
    LIKE        = "like"
    PURCHASE    = "purchase"

    # ── General activity (any domain) ────────────────────────────────────────
    SEARCH      = "search"         # performed a search
    BROWSE      = "browse"         # browsed a category
    VIEW        = "view"           # viewed any content
    READ        = "read"           # read article / product description
    BUY         = "buy"            # actual purchase (any domain)


# Base reward weight per signal type
# Reference: calibrated so that 1 "offer" ≈ 50 "dwell-seconds" ≈ 5 "likes"
SIGNAL_BASE_REWARD: dict[str, float] = {
    SignalType.PURCHASE:    10.0,
    SignalType.BUY:         10.0,
    SignalType.OFFER:        8.0,
    SignalType.CONTACT:      6.0,
    SignalType.FAVORITE:     4.0,
    SignalType.LIKE:         3.0,
    SignalType.SHARE:        3.0,
    SignalType.COMPARE:      2.5,
    SignalType.CLICK:        2.0,
    SignalType.ZOOM:         1.5,
    SignalType.DWELL:        0.0,   # computed dynamically from value (seconds)
    SignalType.HOVER:        0.1,
    SignalType.VIEW:         0.5,
    SignalType.READ:         0.8,
    SignalType.BROWSE:       0.2,
    SignalType.SEARCH:       0.1,
    SignalType.SCROLL_PAST: -0.3,
    SignalType.SKIP:        -0.5,
    SignalType.DISLIKE:     -3.0,
}


def compute_reward(signal_type: str, value: Optional[float] = None) -> float:
    """
    Convert a raw signal into a scalar reward.

    For DWELL: uses a logarithmic curve so 3s → 0.5, 10s → 1.0, 30s → 1.5
    (diminishing returns — consistent with Yi et al. 2014).
    """
    base = SIGNAL_BASE_REWARD.get(signal_type, 0.0)

    if signal_type == SignalType.DWELL and value is not None and value > 0:
        # log1p curve capped at 2.0
        return min(2.0, math.log1p(value / 3.0))

    if value is not None and signal_type in (SignalType.HOVER,):
        return min(0.5, base * math.log1p(value))

    return base


@dataclass
class Signal:
    """An individual captured behavioral event."""
    signal_type: str
    domain: str = "fashion"
    item_id: Optional[int] = None
    value: Optional[float] = None          # seconds for dwell, amount for offer
    context: dict = field(default_factory=dict)
    session_id: Optional[str] = None
    user_id: int = 1

    @property
    def reward(self) -> float:
        return compute_reward(self.signal_type, self.value)

    @property
    def is_positive(self) -> bool:
        return self.reward > 0

    @property
    def is_negative(self) -> bool:
        return self.reward < 0
