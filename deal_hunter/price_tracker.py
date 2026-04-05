"""Price tracking system for marketplace items.

Tracks price history, detects price drops, and maintains price statistics.
Supports PostgreSQL for persistence and Redis for caching.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import redis

from config import get_settings

logger = logging.getLogger(__name__)


class PriceHistory:
    """Price point in history."""

    def __init__(
        self,
        item_id: str,
        price: float,
        currency: str,
        timestamp: datetime,
        original_price: Optional[float] = None,
    ):
        self.item_id = item_id
        self.price = price
        self.currency = currency
        self.timestamp = timestamp
        self.original_price = original_price

    @property
    def discount_percentage(self) -> float:
        """Calculate discount percentage if original price exists."""
        if self.original_price and self.original_price > 0:
            return ((self.original_price - self.price) / self.original_price) * 100
        return 0.0


class PriceStats:
    """Statistical summary of price history."""

    def __init__(
        self,
        item_id: str,
        current_price: float,
        avg_price: float,
        min_price: float,
        max_price: float,
        price_trend: str,  # 'rising', 'falling', 'stable'
        total_snapshots: int,
        first_seen: datetime,
        last_updated: datetime,
    ):
        self.item_id = item_id
        self.current_price = current_price
        self.avg_price = avg_price
        self.min_price = min_price
        self.max_price = max_price
        self.price_trend = price_trend
        self.total_snapshots = total_snapshots
        self.first_seen = first_seen
        self.last_updated = last_updated

    @property
    def price_vs_avg_ratio(self) -> float:
        """Current price as ratio of average (< 1.0 = below average)."""
        if self.avg_price == 0:
            return 1.0
        return self.current_price / self.avg_price

    @property
    def is_good_deal(self) -> bool:
        """Quick check if price is significantly below average."""
        return self.price_vs_avg_ratio < 0.85


class PriceTracker:
    """
    Track item prices over time and detect deals.

    Features:
    - Price history tracking in PostgreSQL
    - Price drop detection and alerts
    - Statistical analysis (avg, min, max, trend)
    - Redis caching for fast lookups
    """

    def __init__(self):
        cfg = get_settings()
        self.cfg = cfg

        # PostgreSQL connection
        self.conn = psycopg2.connect(cfg.postgres_dsn)
        self.conn.autocommit = True

        # Redis for caching
        try:
            self.redis = redis.from_url(cfg.redis_url, decode_responses=False)
            self.redis.ping()
            self.cache_enabled = True
        except Exception as e:
            logger.warning("Redis not available, caching disabled: %s", e)
            self.redis = None
            self.cache_enabled = False

        self._ensure_tables()

    def _ensure_tables(self):
        """Create price tracking tables if they don't exist."""
        with self.conn.cursor() as cur:
            # Price history table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id SERIAL PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    price NUMERIC(10, 2) NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'EUR',
                    original_price NUMERIC(10, 2),
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source TEXT  -- vinted, vestiaire, etc.
                )
            """)

            # Indexes for price_history
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_history_item_time
                ON price_history (item_id, timestamp DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_history_timestamp
                ON price_history (timestamp DESC)
            """)

            # Price alerts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id SERIAL PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    old_price NUMERIC(10, 2) NOT NULL,
                    new_price NUMERIC(10, 2) NOT NULL,
                    drop_percentage NUMERIC(5, 2) NOT NULL,
                    drop_amount NUMERIC(10, 2) NOT NULL,
                    alerted BOOLEAN DEFAULT FALSE,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Indexes for price_alerts
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_alerts_item
                ON price_alerts (item_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_alerts_not_alerted
                ON price_alerts (alerted, timestamp) WHERE NOT alerted
            """)

        logger.info("Price tracking tables ready")

    def record_price(
        self,
        item_id: str,
        price: float,
        currency: str = "EUR",
        original_price: Optional[float] = None,
        source: str = "vinted",
    ) -> Optional[dict]:
        """
        Record a new price observation.

        Args:
            item_id: Unique item identifier
            price: Current price
            currency: Currency code
            original_price: Original price before discount (if any)
            source: Marketplace source

        Returns:
            Alert info if price drop detected, None otherwise
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get last known price
            cur.execute(
                """
                SELECT price, timestamp
                FROM price_history
                WHERE item_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (item_id,),
            )
            last_record = cur.fetchone()

            # Insert new price record
            cur.execute(
                """
                INSERT INTO price_history (item_id, price, currency, original_price, source, timestamp)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (item_id, price, currency, original_price, source),
            )

            # Check for price drop
            alert = None
            if last_record:
                old_price = float(last_record["price"])
                drop_amount = old_price - price
                drop_percentage = (drop_amount / old_price) * 100

                # Trigger alert if significant drop
                if (
                    drop_percentage >= (self.cfg.price_drop_alert_threshold * 100)
                    and drop_amount >= self.cfg.price_drop_min_amount
                ):
                    # Record alert
                    cur.execute(
                        """
                        INSERT INTO price_alerts (item_id, old_price, new_price, drop_percentage, drop_amount)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (item_id, old_price, price, drop_percentage, drop_amount),
                    )

                    alert = {
                        "item_id": item_id,
                        "old_price": old_price,
                        "new_price": price,
                        "drop_percentage": drop_percentage,
                        "drop_amount": drop_amount,
                    }

                    logger.info(
                        "Price drop detected: %s from %.2f to %.2f (%.1f%%)",
                        item_id,
                        old_price,
                        price,
                        drop_percentage,
                    )

            # Invalidate cache
            if self.cache_enabled and self.redis:
                cache_key = f"price:stats:{item_id}"
                self.redis.delete(cache_key)

            return alert

    def get_price_stats(self, item_id: str, days: int = 30) -> Optional[PriceStats]:
        """
        Get price statistics for an item.

        Args:
            item_id: Item identifier
            days: Number of days to look back

        Returns:
            PriceStats object or None if no history
        """
        # Check cache
        if self.cache_enabled and self.redis:
            cache_key = f"price:stats:{item_id}"
            cached = self.redis.get(cache_key)
            if cached:
                import pickle
                return pickle.loads(cached)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            since = datetime.now() - timedelta(days=days)

            cur.execute(
                """
                SELECT
                    MIN(price) as min_price,
                    MAX(price) as max_price,
                    AVG(price) as avg_price,
                    COUNT(*) as total_snapshots,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_updated
                FROM price_history
                WHERE item_id = %s AND timestamp >= %s
                """,
                (item_id, since),
            )
            row = cur.fetchone()

            if not row or row["total_snapshots"] == 0:
                return None

            # Get current price
            cur.execute(
                """
                SELECT price
                FROM price_history
                WHERE item_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (item_id,),
            )
            current_row = cur.fetchone()
            current_price = float(current_row["price"]) if current_row else 0.0

            # Determine trend (simple: compare first half vs second half)
            cur.execute(
                """
                WITH split AS (
                    SELECT
                        price,
                        ROW_NUMBER() OVER (ORDER BY timestamp) as rn,
                        COUNT(*) OVER () as total
                    FROM price_history
                    WHERE item_id = %s AND timestamp >= %s
                )
                SELECT
                    AVG(CASE WHEN rn <= total / 2 THEN price END) as first_half_avg,
                    AVG(CASE WHEN rn > total / 2 THEN price END) as second_half_avg
                FROM split
                """,
                (item_id, since),
            )
            trend_row = cur.fetchone()

            price_trend = "stable"
            if trend_row and trend_row["first_half_avg"] and trend_row["second_half_avg"]:
                first_avg = float(trend_row["first_half_avg"])
                second_avg = float(trend_row["second_half_avg"])
                diff_pct = abs(second_avg - first_avg) / first_avg * 100

                if diff_pct > 5:
                    price_trend = "falling" if second_avg < first_avg else "rising"

            stats = PriceStats(
                item_id=item_id,
                current_price=current_price,
                avg_price=float(row["avg_price"]),
                min_price=float(row["min_price"]),
                max_price=float(row["max_price"]),
                price_trend=price_trend,
                total_snapshots=int(row["total_snapshots"]),
                first_seen=row["first_seen"],
                last_updated=row["last_updated"],
            )

            # Cache for 1 hour
            if self.cache_enabled and self.redis:
                import pickle
                self.redis.setex(cache_key, 3600, pickle.dumps(stats))

            return stats

    def get_pending_alerts(self, limit: int = 50) -> list[dict]:
        """Get price drop alerts that haven't been sent yet."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM price_alerts
                WHERE alerted = FALSE
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_alert_sent(self, alert_id: int):
        """Mark a price alert as sent."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE price_alerts SET alerted = TRUE WHERE id = %s",
                (alert_id,),
            )

    def get_price_history(
        self, item_id: str, days: int = 30, limit: int = 100
    ) -> list[PriceHistory]:
        """
        Get price history for an item.

        Args:
            item_id: Item identifier
            days: Number of days to look back
            limit: Maximum number of records

        Returns:
            List of PriceHistory objects
        """
        since = datetime.now() - timedelta(days=days)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM price_history
                WHERE item_id = %s AND timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (item_id, since, limit),
            )

            return [
                PriceHistory(
                    item_id=row["item_id"],
                    price=float(row["price"]),
                    currency=row["currency"],
                    timestamp=row["timestamp"],
                    original_price=float(row["original_price"]) if row["original_price"] else None,
                )
                for row in cur.fetchall()
            ]

    def cleanup_old_records(self, days: int = 90):
        """Delete price history older than specified days."""
        cutoff = datetime.now() - timedelta(days=days)

        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM price_history WHERE timestamp < %s",
                (cutoff,),
            )
            deleted = cur.rowcount

        logger.info("Cleaned up %d old price records (> %d days)", deleted, days)
        return deleted

    def close(self):
        """Close connections."""
        if self.conn:
            self.conn.close()
        if self.redis:
            self.redis.close()
