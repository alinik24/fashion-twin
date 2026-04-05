"""Deal scoring algorithm for fashion items.

Combines multiple signals to calculate how good a deal is:
- Price vs. market average
- Price history trend
- Item condition
- Time sensitivity (how long it's been listed)
- Brand value
- Rarity score
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from config import get_settings
from .price_tracker import PriceTracker, PriceStats

logger = logging.getLogger(__name__)


class DealScore:
    """Deal scoring result."""

    def __init__(
        self,
        item_id: str,
        total_score: float,
        price_score: float,
        history_score: float,
        condition_score: float,
        time_score: float,
        brand_bonus: float = 0.0,
        rarity_bonus: float = 0.0,
        breakdown: Optional[dict] = None,
    ):
        self.item_id = item_id
        self.total_score = min(100.0, total_score)  # Cap at 100
        self.price_score = price_score
        self.history_score = history_score
        self.condition_score = condition_score
        self.time_score = time_score
        self.brand_bonus = brand_bonus
        self.rarity_bonus = rarity_bonus
        self.breakdown = breakdown or {}

    @property
    def quality(self) -> str:
        """Deal quality label."""
        cfg = get_settings()
        if self.total_score >= cfg.deal_excellent_threshold:
            return "excellent"
        elif self.total_score >= cfg.deal_good_threshold:
            return "good"
        elif self.total_score >= cfg.deal_fair_threshold:
            return "fair"
        else:
            return "poor"

    @property
    def is_worth_buying(self) -> bool:
        """Quick check if deal is worth pursuing."""
        return self.total_score >= get_settings().deal_good_threshold

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "item_id": self.item_id,
            "total_score": round(self.total_score, 2),
            "quality": self.quality,
            "is_worth_buying": self.is_worth_buying,
            "components": {
                "price_score": round(self.price_score, 2),
                "history_score": round(self.history_score, 2),
                "condition_score": round(self.condition_score, 2),
                "time_score": round(self.time_score, 2),
                "brand_bonus": round(self.brand_bonus, 2),
                "rarity_bonus": round(self.rarity_bonus, 2),
            },
            "breakdown": self.breakdown,
        }


class DealScorer:
    """
    Calculate deal scores for fashion items.

    Uses a multi-factor scoring model:
    1. Price Score (40%): How far below market average
    2. History Score (30%): Price trend and discount depth
    3. Condition Score (20%): Item condition quality
    4. Time Score (10%): Urgency based on listing age

    Plus bonuses for:
    - Premium brands
    - Rare/limited items
    """

    # Condition quality multipliers
    CONDITION_MULTIPLIERS = {
        "new": 1.0,
        "new_with_tags": 1.0,
        "like_new": 0.95,
        "very_good": 0.90,
        "good": 0.85,
        "satisfactory": 0.75,
        "worn": 0.60,
    }

    # Premium brands that get bonus points
    PREMIUM_BRANDS = {
        "chanel": 10,
        "hermès": 10,
        "hermes": 10,
        "louis vuitton": 10,
        "gucci": 8,
        "prada": 8,
        "dior": 8,
        "celine": 8,
        "bottega veneta": 8,
        "balenciaga": 7,
        "saint laurent": 7,
        "ysl": 7,
        "valentino": 7,
        "burberry": 6,
        "fendi": 6,
        "givenchy": 6,
        "loewe": 6,
    }

    def __init__(self, price_tracker: Optional[PriceTracker] = None):
        self.cfg = get_settings()
        self.price_tracker = price_tracker or PriceTracker()

    def calculate_price_score(
        self, current_price: float, market_avg: float, original_price: Optional[float] = None
    ) -> tuple[float, dict]:
        """
        Calculate score based on price vs. market.

        Score is higher when price is below average.

        Returns:
            (score_0_100, breakdown_dict)
        """
        if market_avg == 0 or current_price == 0:
            return 0.0, {"reason": "invalid_price"}

        # Ratio of current price to market average
        price_ratio = current_price / market_avg

        # Score formula: exponential decay as ratio approaches 1
        # price_ratio = 0.5 → score = 100 (50% below market)
        # price_ratio = 0.85 → score = 60
        # price_ratio = 1.0 → score = 0 (at market price)
        # price_ratio > 1.0 → negative (penalize above-market)

        if price_ratio <= 0.5:
            score = 100.0
        elif price_ratio >= 1.0:
            score = max(0, -50 * (price_ratio - 1.0))  # Penalty for overpriced
        else:
            # Sigmoid-like curve
            score = 100 * (1 - price_ratio) ** 1.5

        # Bonus if there's an original price discount
        discount_bonus = 0.0
        if original_price and original_price > current_price:
            discount_pct = ((original_price - current_price) / original_price) * 100
            discount_bonus = min(20, discount_pct / 2)  # Up to +20 points

        final_score = min(100, score + discount_bonus)

        breakdown = {
            "price_ratio": round(price_ratio, 3),
            "base_score": round(score, 2),
            "discount_bonus": round(discount_bonus, 2),
            "final_score": round(final_score, 2),
        }

        return final_score, breakdown

    def calculate_history_score(self, price_stats: Optional[PriceStats]) -> tuple[float, dict]:
        """
        Calculate score based on price history trend.

        Higher score if:
        - Price is falling
        - Current price near historical minimum
        - Significant drop from recent peak

        Returns:
            (score_0_100, breakdown_dict)
        """
        if not price_stats:
            return 50.0, {"reason": "no_history"}  # Neutral score

        # Component 1: Current price vs. min/max range (50%)
        price_range = price_stats.max_price - price_stats.min_price
        if price_range > 0:
            position_in_range = (price_stats.current_price - price_stats.min_price) / price_range
            range_score = (1 - position_in_range) * 100  # Lower in range = higher score
        else:
            range_score = 50.0

        # Component 2: Trend bonus (30%)
        trend_score = 0.0
        if price_stats.price_trend == "falling":
            trend_score = 100.0
        elif price_stats.price_trend == "stable":
            trend_score = 50.0
        else:  # rising
            trend_score = 20.0

        # Component 3: Drop from average (20%)
        drop_from_avg = ((price_stats.avg_price - price_stats.current_price) / price_stats.avg_price) * 100
        drop_score = min(100, max(0, drop_from_avg * 5))  # 20% drop = 100 points

        # Weighted combination
        final_score = (range_score * 0.5) + (trend_score * 0.3) + (drop_score * 0.2)

        breakdown = {
            "range_score": round(range_score, 2),
            "trend_score": round(trend_score, 2),
            "trend": price_stats.price_trend,
            "drop_score": round(drop_score, 2),
            "drop_from_avg_pct": round(drop_from_avg, 2),
            "final_score": round(final_score, 2),
        }

        return final_score, breakdown

    def calculate_condition_score(self, condition: str) -> tuple[float, dict]:
        """
        Calculate score based on item condition.

        Returns:
            (score_0_100, breakdown_dict)
        """
        condition_lower = condition.lower().replace("-", "_").replace(" ", "_")
        multiplier = self.CONDITION_MULTIPLIERS.get(condition_lower, 0.70)  # Default to 0.70

        score = multiplier * 100

        breakdown = {
            "condition": condition,
            "multiplier": multiplier,
            "score": round(score, 2),
        }

        return score, breakdown

    def calculate_time_score(
        self, created_at: datetime, updated_at: Optional[datetime] = None
    ) -> tuple[float, dict]:
        """
        Calculate urgency score based on listing age.

        Newer listings get higher scores (more urgent to act).
        Items listed 7+ days ago get lower scores.

        Returns:
            (score_0_100, breakdown_dict)
        """
        now = datetime.now()
        age_hours = (now - created_at).total_seconds() / 3600

        # Exponential decay: fresh items score high
        # 0-6 hours: 100
        # 12 hours: 90
        # 24 hours: 75
        # 48 hours: 50
        # 7 days: 10

        if age_hours <= 6:
            score = 100.0
        elif age_hours >= 168:  # 7 days
            score = 10.0
        else:
            # Logarithmic decay
            score = 100 * math.exp(-age_hours / 48)

        # Bonus if recently updated (price drop?)
        update_bonus = 0.0
        if updated_at and (now - updated_at).total_seconds() < 3600:  # Updated in last hour
            update_bonus = 20.0

        final_score = min(100, score + update_bonus)

        breakdown = {
            "age_hours": round(age_hours, 2),
            "base_score": round(score, 2),
            "update_bonus": round(update_bonus, 2),
            "final_score": round(final_score, 2),
        }

        return final_score, breakdown

    def calculate_brand_bonus(self, brand: Optional[str]) -> tuple[float, dict]:
        """
        Calculate bonus points for premium brands.

        Returns:
            (bonus_points, breakdown_dict)
        """
        if not brand:
            return 0.0, {"reason": "no_brand"}

        brand_lower = brand.lower().strip()
        bonus = self.PREMIUM_BRANDS.get(brand_lower, 0.0)

        breakdown = {
            "brand": brand,
            "bonus": bonus,
            "is_premium": bonus > 0,
        }

        return bonus, breakdown

    def score_deal(
        self,
        item_id: str,
        current_price: float,
        market_avg: float,
        condition: str,
        created_at: datetime,
        brand: Optional[str] = None,
        original_price: Optional[float] = None,
        updated_at: Optional[datetime] = None,
        is_rare: bool = False,
    ) -> DealScore:
        """
        Calculate comprehensive deal score.

        Args:
            item_id: Unique item identifier
            current_price: Current listing price
            market_avg: Market average price for similar items
            condition: Item condition
            created_at: When item was first listed
            brand: Brand name (optional)
            original_price: Original retail price (optional)
            updated_at: Last update time (optional)
            is_rare: Whether item is rare/limited (optional)

        Returns:
            DealScore object with breakdown
        """
        cfg = self.cfg

        # Get price history stats
        price_stats = self.price_tracker.get_price_stats(item_id)

        # Calculate component scores
        price_score, price_breakdown = self.calculate_price_score(
            current_price, market_avg, original_price
        )
        history_score, history_breakdown = self.calculate_history_score(price_stats)
        condition_score, condition_breakdown = self.calculate_condition_score(condition)
        time_score, time_breakdown = self.calculate_time_score(created_at, updated_at)

        # Calculate bonuses
        brand_bonus, brand_breakdown = self.calculate_brand_bonus(brand)
        rarity_bonus = 15.0 if is_rare else 0.0

        # Weighted combination
        base_score = (
            price_score * cfg.deal_score_price_weight
            + history_score * cfg.deal_score_history_weight
            + condition_score * cfg.deal_score_condition_weight
            + time_score * cfg.deal_score_time_weight
        )

        total_score = base_score + brand_bonus + rarity_bonus

        # Full breakdown
        breakdown = {
            "price": price_breakdown,
            "history": history_breakdown,
            "condition": condition_breakdown,
            "time": time_breakdown,
            "brand": brand_breakdown,
            "rarity": {"is_rare": is_rare, "bonus": rarity_bonus},
            "weights": {
                "price": cfg.deal_score_price_weight,
                "history": cfg.deal_score_history_weight,
                "condition": cfg.deal_score_condition_weight,
                "time": cfg.deal_score_time_weight,
            },
        }

        return DealScore(
            item_id=item_id,
            total_score=total_score,
            price_score=price_score,
            history_score=history_score,
            condition_score=condition_score,
            time_score=time_score,
            brand_bonus=brand_bonus,
            rarity_bonus=rarity_bonus,
            breakdown=breakdown,
        )
