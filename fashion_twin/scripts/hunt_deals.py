#!/usr/bin/env python3
"""
Deal Hunter CLI Script

Start automated deal hunting for fashion items.

Usage:
    python scripts/hunt_deals.py
    python scripts/hunt_deals.py --categories jackets,dresses --max-price 150
    python scripts/hunt_deals.py --brands chanel,gucci --min-score 80
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from deal_hunter import DealHunter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Fashion Twin Deal Hunter")
    parser.add_argument(
        "--categories",
        type=str,
        help="Comma-separated list of categories (e.g., jackets,dresses)",
    )
    parser.add_argument(
        "--brands",
        type=str,
        help="Comma-separated list of brands (e.g., chanel,gucci)",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        help="Maximum price to consider",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        help="Minimum deal score (0-100) to alert on",
    )
    parser.add_argument(
        "--scan-once",
        action="store_true",
        help="Run single scan instead of continuous mode",
    )

    args = parser.parse_args()

    cfg = get_settings()

    # Check if hunter mode is enabled
    if not cfg.hunter_mode_enabled:
        logger.error("Hunter mode is disabled. Set HUNTER_MODE_ENABLED=true in .env")
        return 1

    # Parse arguments
    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]

    brands = None
    if args.brands:
        brands = [b.strip().lower() for b in args.brands.split(",")]

    max_price = args.max_price
    min_score = args.min_score

    # Create hunter
    hunter = DealHunter()

    # Print configuration
    logger.info("=" * 60)
    logger.info("Fashion Twin Deal Hunter Starting")
    logger.info("=" * 60)
    logger.info("Categories: %s", categories or cfg.hunter_categories_list)
    logger.info("Brands: %s", brands or cfg.hunter_priority_brands_list)
    logger.info("Max Price: %.2f", max_price or cfg.hunter_max_price)
    logger.info("Min Score: %d", min_score or cfg.hunter_min_deal_score)
    if not args.scan_once:
        logger.info("Scan Interval: %d minutes", cfg.hunter_scan_interval_minutes)
    logger.info("=" * 60)

    # Check notification channels
    channels = []
    if cfg.deal_alert_discord_webhook:
        channels.append("Discord")
    if cfg.deal_alert_telegram_bot_token:
        channels.append("Telegram")

    if channels:
        logger.info("Notifications enabled: %s", ", ".join(channels))
    else:
        logger.warning("No notification channels configured! Set DEAL_ALERT_DISCORD_WEBHOOK or DEAL_ALERT_TELEGRAM_* in .env")

    logger.info("")

    try:
        if args.scan_once:
            # Single scan
            logger.info("Running single scan...")
            deals = hunter.scan_for_deals(
                categories=categories,
                brands=brands,
                max_price=max_price,
                min_score=min_score,
            )
            logger.info("Scan complete. Found %d deals.", len(deals))

            if deals:
                logger.info("\nTop deals found:")
                for i, deal in enumerate(deals[:5], 1):
                    logger.info(
                        "%d. %s - €%.2f (score: %.1f)",
                        i,
                        deal["title"][:50],
                        deal["price"],
                        deal["deal_score"],
                    )
        else:
            # Continuous mode
            logger.info("Starting continuous hunting... Press Ctrl+C to stop")
            hunter.start_hunting(
                categories=categories,
                brands=brands,
                max_price=max_price,
                min_score=min_score,
            )

    except KeyboardInterrupt:
        logger.info("\nStopping deal hunter...")
        hunter.stop_hunting()

        # Print stats
        stats = hunter.get_deal_stats()
        logger.info("\n" + "=" * 60)
        logger.info("Deal Hunter Statistics")
        logger.info("=" * 60)
        logger.info("Total Scans: %d", stats["total_scans"])
        logger.info("Total Deals Found: %d", stats["total_deals"])
        logger.info("Avg Deals Per Scan: %.2f", stats["avg_deals_per_scan"])
        logger.info("=" * 60)

    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
