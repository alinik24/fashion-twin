"""Main deal hunting orchestrator.

Continuously scans marketplaces for deals, scores them, and sends alerts.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from config import get_settings
from .price_tracker import PriceTracker
from .deal_scorer import DealScorer
from .alert_system import AlertSystem

logger = logging.getLogger(__name__)


class DealHunter:
    """
    Automated deal hunting system.

    Scans marketplaces at regular intervals, tracks prices,
    scores deals, and sends alerts for good opportunities.

    Features:
    - Continuous scanning mode
    - Category and brand filtering
    - Price range filtering
    - Automatic notifications
    - Deal history tracking
    """

    def __init__(self):
        self.cfg = get_settings()
        self.price_tracker = PriceTracker()
        self.deal_scorer = DealScorer(price_tracker=self.price_tracker)
        self.alert_system = AlertSystem()

        self.is_running = False
        self.scan_count = 0
        self.deals_found = 0

    def start_hunting(
        self,
        categories: Optional[list[str]] = None,
        brands: Optional[list[str]] = None,
        max_price: Optional[float] = None,
        min_score: Optional[int] = None,
    ):
        """
        Start continuous deal hunting.

        Args:
            categories: Filter by categories (e.g., ['jackets', 'dresses'])
            brands: Filter by brands
            max_price: Maximum price to consider
            min_score: Minimum deal score to alert on
        """
        if not self.cfg.hunter_mode_enabled:
            logger.warning("Hunter mode is disabled in config. Enable HUNTER_MODE_ENABLED=true")
            return

        # Use config defaults if not specified
        categories = categories or self.cfg.hunter_categories_list
        brands = brands or self.cfg.hunter_priority_brands_list
        max_price = max_price or self.cfg.hunter_max_price
        min_score = min_score or self.cfg.hunter_min_deal_score

        self.is_running = True
        scan_interval = self.cfg.hunter_scan_interval_minutes * 60  # Convert to seconds

        logger.info(
            "🎯 Starting deal hunter: categories=%s brands=%s max_price=%.2f min_score=%d",
            categories,
            brands,
            max_price,
            min_score,
        )

        try:
            while self.is_running:
                self.scan_count += 1
                logger.info("Scan #%d starting...", self.scan_count)

                deals = self.scan_for_deals(
                    categories=categories,
                    brands=brands,
                    max_price=max_price,
                    min_score=min_score,
                )

                logger.info(
                    "Scan #%d complete. Found %d deals. Total deals: %d",
                    self.scan_count,
                    len(deals),
                    self.deals_found,
                )

                # Wait for next scan
                time.sleep(scan_interval)

        except KeyboardInterrupt:
            logger.info("Deal hunter stopped by user")
            self.stop_hunting()
        except Exception as e:
            logger.error("Deal hunter error: %s", e, exc_info=True)
            self.stop_hunting()

    def stop_hunting(self):
        """Stop the hunting loop."""
        self.is_running = False
        logger.info("Deal hunter stopped. Total scans: %d, Total deals: %d", self.scan_count, self.deals_found)

    def scan_for_deals(
        self,
        categories: Optional[list[str]] = None,
        brands: Optional[list[str]] = None,
        max_price: Optional[float] = None,
        min_score: Optional[int] = None,
    ) -> list[dict]:
        """
        Perform a single scan for deals.

        Returns:
            List of deal dicts that met the criteria
        """
        from storage.postgres import PostgresStore  # Avoid circular import
        from collector.vinted import VintedCollector

        deals = []
        db = PostgresStore()

        try:
            # Scan each category
            categories = categories or self.cfg.hunter_categories_list

            for category in categories:
                logger.info("Scanning category: %s", category)

                # Use Vinted collector to fetch items
                collector = VintedCollector()

                # Build search query
                search_params = {
                    "catalog": category,
                    "price_to": max_price or self.cfg.hunter_max_price,
                    "per_page": 50,
                }

                # Add brand filter if specified
                if brands:
                    search_params["brand_ids"] = brands

                try:
                    items = collector.search(**search_params)
                except Exception as e:
                    logger.error("Failed to search %s: %s", category, e)
                    continue

                # Score each item
                for item in items:
                    deal = self._evaluate_item(item, db, min_score)
                    if deal:
                        deals.append(deal)
                        self.deals_found += 1

                # Rate limiting
                time.sleep(2)

        finally:
            db.close()

        return deals

    def _evaluate_item(
        self, item: dict, db, min_score: Optional[int] = None
    ) -> Optional[dict]:
        """
        Evaluate a single item and send alert if it's a good deal.

        Returns:
            Deal dict if meets criteria, None otherwise
        """
        item_id = str(item.get("id"))
        price = float(item.get("price", 0))
        brand = item.get("brand", {}).get("title") if isinstance(item.get("brand"), dict) else item.get("brand")
        condition = item.get("status", "good")
        title = item.get("title", "")

        # Record price
        self.price_tracker.record_price(
            item_id=item_id,
            price=price,
            currency=item.get("currency", "EUR"),
            original_price=item.get("original_price"),
            source="vinted",
        )

        # Get market average for similar items
        # For now, use a simple heuristic: category average from DB
        market_avg = self._get_market_average(item, db)

        # Calculate deal score
        created_at = datetime.fromisoformat(item["created_at"]) if "created_at" in item else datetime.now()

        deal_score = self.deal_scorer.score_deal(
            item_id=item_id,
            current_price=price,
            market_avg=market_avg,
            condition=condition,
            created_at=created_at,
            brand=brand,
            original_price=item.get("original_price"),
        )

        # Check if meets minimum score
        min_threshold = min_score or self.cfg.hunter_min_deal_score
        if deal_score.total_score < min_threshold:
            return None

        # Prepare deal data
        deal_data = {
            "id": item_id,
            "title": title,
            "price": price,
            "currency": item.get("currency", "EUR"),
            "brand": brand,
            "condition": condition,
            "url": item.get("url", f"https://www.vinted.com/items/{item_id}"),
            "image_url": item.get("photo", {}).get("url", "") if item.get("photo") else "",
            "deal_score": deal_score.total_score,
            "deal_quality": deal_score.quality,
            "found_at": datetime.now().isoformat(),
        }

        # Send alert
        logger.info(
            "🔥 Deal found: %s (score: %.1f) - %s @ %.2f",
            title[:50],
            deal_score.total_score,
            brand or "Unknown",
            price,
        )

        try:
            self.alert_system.send_deal_alert(item_id, deal_score, deal_data)
        except Exception as e:
            logger.error("Failed to send alert: %s", e)

        # Save to database
        self._save_deal(deal_data, deal_score, db)

        return deal_data

    def _get_market_average(self, item: dict, db) -> float:
        """
        Estimate market average for similar items.

        Simplified version - in production, use ML similarity or category stats.
        """
        # Placeholder: use price as market avg + 30%
        # In real implementation, query DB for similar items
        base_price = float(item.get("price", 0))
        return base_price * 1.3

    def _save_deal(self, deal_data: dict, deal_score, db):
        """Save deal to database for history tracking."""
        try:
            with db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO deals_found (
                        item_id, title, price, currency, brand, condition,
                        url, image_url, deal_score, deal_quality, found_at, deal_breakdown
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (item_id) DO UPDATE
                    SET deal_score = EXCLUDED.deal_score,
                        found_at = EXCLUDED.found_at,
                        deal_breakdown = EXCLUDED.deal_breakdown
                    """,
                    (
                        deal_data["id"],
                        deal_data["title"],
                        deal_data["price"],
                        deal_data["currency"],
                        deal_data.get("brand"),
                        deal_data.get("condition"),
                        deal_data.get("url"),
                        deal_data.get("image_url"),
                        deal_score.total_score,
                        deal_score.quality,
                        deal_data["found_at"],
                        str(deal_score.to_dict()),
                    ),
                )
        except Exception as e:
            logger.error("Failed to save deal to DB: %s", e)

    def get_deal_stats(self) -> dict:
        """Get statistics about found deals."""
        return {
            "total_scans": self.scan_count,
            "total_deals": self.deals_found,
            "is_running": self.is_running,
            "avg_deals_per_scan": self.deals_found / max(self.scan_count, 1),
        }
