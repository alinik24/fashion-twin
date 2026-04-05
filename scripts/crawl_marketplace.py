#!/usr/bin/env python3
"""Production-grade marketplace crawler using Crawlee.

Crawlee provides:
- Auto-scaling (adjusts concurrency based on system)
- Session management (maintains authentication)
- Request queue (deduplication, prioritization)
- Automatic retries (exponential backoff)
- Proxy rotation (avoid bans)

Usage:
    # Crawl Vinted for designer bags
    python scripts/crawl_marketplace.py --marketplace vinted --query "designer bags" --pages 100

    # Crawl all marketplaces
    python scripts/crawl_marketplace.py --all --categories bags,jackets

    # Monitor prices for tracked items
    python scripts/crawl_marketplace.py --monitor-prices

Installation:
    pip install crawlee playwright
    playwright install chromium
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.extractors.crawlee_extractor import (
    CrawleeMarketplaceCrawler,
    CrawleePriceMonitor,
    run_crawlee_extraction,
    run_price_monitoring
)


def main():
    parser = argparse.ArgumentParser(description="Crawl marketplaces using Crawlee")

    parser.add_argument(
        "--marketplace",
        choices=["vinted", "vestiaire", "depop", "all"],
        help="Marketplace to crawl"
    )
    parser.add_argument(
        "--query",
        help="Search query (e.g., 'designer bags')"
    )
    parser.add_argument(
        "--categories",
        help="Categories to crawl (comma-separated)"
    )
    parser.add_argument(
        "--max-price",
        type=float,
        help="Maximum price filter"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=10,
        help="Number of pages to crawl (default: 10)"
    )
    parser.add_argument(
        "--monitor-prices",
        action="store_true",
        help="Monitor prices for tracked items"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Crawl all marketplaces"
    )

    args = parser.parse_args()

    if args.monitor_prices:
        # Price monitoring mode
        print("=" * 70)
        print("PRICE MONITORING (Crawlee)")
        print("=" * 70)

        # Get items to monitor from database
        from storage.postgres import PostgresStore

        with PostgresStore() as db:
            with db._cursor() as cur:
                cur.execute("""
                    SELECT item_id FROM items
                    WHERE item_id LIKE 'vinted_%'
                    ORDER BY scraped_at DESC
                    LIMIT 1000
                """)
                items = [row[0].replace("vinted_", "") for row in cur.fetchall()]

        print(f"Monitoring {len(items)} items...")

        # Run monitoring
        run_price_monitoring(items)

        print("\n✓ Price monitoring complete")
        print("  Check price_alerts table for detected drops")

    else:
        # Crawling mode
        marketplaces = []

        if args.all:
            marketplaces = ["vinted", "vestiaire", "depop"]
        elif args.marketplace == "all":
            marketplaces = ["vinted", "vestiaire", "depop"]
        elif args.marketplace:
            marketplaces = [args.marketplace]
        else:
            parser.print_help()
            print("\nError: Must specify --marketplace or --all")
            sys.exit(1)

        # Parse categories
        categories = args.categories.split(",") if args.categories else None

        # Crawl each marketplace
        all_items = []

        for marketplace in marketplaces:
            print("\n" + "=" * 70)
            print(f"CRAWLING {marketplace.upper()}")
            print("=" * 70)

            # Calculate max requests (approx pages * items per page)
            max_requests = args.pages * 50

            print(f"Query: {args.query or 'all items'}")
            print(f"Categories: {categories or 'all'}")
            print(f"Max price: £{args.max_price}" if args.max_price else "Max price: no limit")
            print(f"Max requests: {max_requests}")

            try:
                # Run crawler
                items = run_crawlee_extraction(
                    marketplace=marketplace,
                    query=args.query,
                    categories=categories,
                    max_price=args.max_price,
                    max_requests=max_requests
                )

                all_items.extend(items)

                print(f"\n✓ Crawled {len(items)} items from {marketplace}")

                # Store in database
                from pipeline.extractors.crawlee_extractor import CrawleeMarketplaceCrawler
                crawler = CrawleeMarketplaceCrawler(marketplace=marketplace)
                crawler.store(items)

                print("✓ Stored in database")

            except Exception as e:
                print(f"\n✗ Failed to crawl {marketplace}: {e}")
                continue

        # Summary
        print("\n" + "=" * 70)
        print("CRAWLING SUMMARY")
        print("=" * 70)

        print(f"\nMarketplaces crawled: {len(marketplaces)}")
        print(f"Total items extracted: {len(all_items)}")

        print("\nCrawlee Features Used:")
        print("  ✓ Auto-scaling (concurrency adjusted automatically)")
        print("  ✓ Session management (maintains auth state)")
        print("  ✓ Request deduplication (no duplicate requests)")
        print("  ✓ Automatic retries (3x retry on failure)")
        print("  ✓ Efficient queue management")

        print("\nNext steps:")
        print("  1. python scripts/train_ranker.py")
        print("  2. python scripts/hunt_deals.py --scan-once")


if __name__ == "__main__":
    main()
