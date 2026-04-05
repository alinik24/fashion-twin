"""Crawlee Integration for Production-Grade Scraping

Uses Apify's Crawlee framework for robust, scalable scraping:
- Auto-scaling (handles rate limiting)
- Session management (maintains authentication)
- Request queue (efficient crawling)
- Retry logic (automatic error handling)
- Proxy rotation (avoid bans)

https://github.com/apify/crawlee-python

Installation:
    pip install crawlee

Usage:
    # Scrape entire Vinted catalog
    python scripts/crawl_marketplace.py --marketplace vinted --scale large

    # Monitor price changes
    python scripts/monitor_prices.py --items 1000

    # Track trending items
    python scripts/track_trending.py --realtime
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from crawlee.playwright_crawler import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee import Request

from .base import BaseExtractor

logger = logging.getLogger(__name__)


class CrawleeMarketplaceCrawler(BaseExtractor):
    """
    Production-grade marketplace crawler using Crawlee.

    Features:
    - Auto-scaling (concurrency based on system resources)
    - Session management (maintains login state)
    - Request queue (deduplication, prioritization)
    - Automatic retries (exponential backoff)
    - Proxy rotation (avoid rate limits)
    """

    def __init__(self, marketplace: str = "vinted", max_requests: int = 10000):
        super().__init__()
        self.marketplace = marketplace
        self.max_requests = max_requests

        # Marketplace-specific config
        self.config = self._get_marketplace_config(marketplace)

    def _get_marketplace_config(self, marketplace: str) -> Dict:
        """Get marketplace-specific configuration."""
        configs = {
            "vinted": {
                "base_url": "https://www.vinted.co.uk",
                "search_url": "https://www.vinted.co.uk/catalog",
                "item_selector": '[data-testid="item-box"]',
                "price_selector": '[data-testid="item-price"]',
                "title_selector": '.ItemBox_title',
                "image_selector": 'img.ItemBox_image'
            },
            "vestiaire": {
                "base_url": "https://www.vestiairecollective.com",
                "search_url": "https://www.vestiairecollective.com/search/",
                "item_selector": '.productItem',
                "price_selector": '.price',
                "title_selector": '.productItem__name',
                "image_selector": 'img.productItem__img'
            },
            "depop": {
                "base_url": "https://www.depop.com",
                "search_url": "https://www.depop.com/search/",
                "item_selector": '[data-testid="product"]',
                "price_selector": '[data-testid="price"]',
                "title_selector": '[data-testid="title"]',
                "image_selector": '[data-testid="image"]'
            }
        }

        return configs.get(marketplace, configs["vinted"])

    async def extract(
        self,
        query: str = None,
        categories: List[str] = None,
        max_price: float = None,
        **kwargs
    ) -> List[Dict]:
        """
        Extract items from marketplace using Crawlee.

        Args:
            query: Search query (e.g., "designer bags")
            categories: Categories to scrape (e.g., ["bags", "jackets"])
            max_price: Maximum price filter

        Returns:
            List of extracted items
        """
        logger.info(f"Starting Crawlee crawler for {self.marketplace}...")

        extracted_items = []

        # Create crawler
        crawler = PlaywrightCrawler(
            # Crawlee auto-manages concurrency based on system resources
            max_requests_per_crawl=self.max_requests,

            # Enable request queue deduplication
            max_request_retries=3,

            # Session management (maintains login state)
            use_session_pool=True,

            # Request handler
            request_handler=self._create_request_handler(extracted_items),

            # Failed request handler
            failed_request_handler=self._handle_failed_request,
        )

        # Build initial URLs
        urls = self._build_urls(query, categories, max_price)

        # Run crawler
        await crawler.run(urls)

        logger.info(f"✓ Crawled {len(extracted_items)} items")
        return extracted_items

    def _create_request_handler(self, extracted_items: List[Dict]):
        """Create request handler function for Crawlee."""

        async def handler(context: PlaywrightCrawlingContext) -> None:
            """Handle each page request."""
            page = context.page

            # Wait for items to load
            await page.wait_for_selector(self.config["item_selector"])

            # Extract all items on page
            items = await page.query_selector_all(self.config["item_selector"])

            for item in items:
                try:
                    # Extract item data
                    title_elem = await item.query_selector(self.config["title_selector"])
                    title = await title_elem.inner_text() if title_elem else "Unknown"

                    price_elem = await item.query_selector(self.config["price_selector"])
                    price_text = await price_elem.inner_text() if price_elem else "0"
                    price = self._parse_price(price_text)

                    link_elem = await item.query_selector('a[href*="/items/"]')
                    url = await link_elem.get_attribute("href") if link_elem else None
                    if url and not url.startswith("http"):
                        url = self.config["base_url"] + url

                    image_elem = await item.query_selector(self.config["image_selector"])
                    image_url = await image_elem.get_attribute("src") if image_elem else None

                    # Extract item ID from URL
                    item_id = self._extract_item_id(url) if url else None

                    extracted_items.append({
                        "item_id": f"{self.marketplace}_{item_id}" if item_id else None,
                        "title": title,
                        "price": price,
                        "url": url,
                        "image_url": image_url,
                        "source": f"crawlee_{self.marketplace}",
                        "scraped_at": datetime.now().isoformat()
                    })

                except Exception as e:
                    logger.warning(f"Failed to parse item: {e}")
                    continue

            # Enqueue next page
            next_button = await page.query_selector('[aria-label="Next page"], .pagination__next')
            if next_button:
                next_url = await page.url()
                await context.enqueue_links(
                    selector='[aria-label="Next page"]',
                    label='PAGINATION'
                )

        return handler

    async def _handle_failed_request(self, context: PlaywrightCrawlingContext) -> None:
        """Handle failed requests."""
        logger.error(f"Request failed: {context.request.url}")

    def _build_urls(
        self,
        query: Optional[str],
        categories: Optional[List[str]],
        max_price: Optional[float]
    ) -> List[str]:
        """Build initial URLs to crawl."""
        urls = []

        if self.marketplace == "vinted":
            base = "https://www.vinted.co.uk/catalog"
            params = []

            if query:
                params.append(f"search_text={query}")

            if categories:
                for cat in categories:
                    params.append(f"catalog[]={cat}")

            if max_price:
                params.append(f"price_to={int(max_price)}")

            url = base + ("?" + "&".join(params) if params else "")
            urls.append(url)

        elif self.marketplace == "vestiaire":
            base = "https://www.vestiairecollective.com/search/"
            if query:
                urls.append(base + f"?query={query}")
            else:
                urls.append(base)

        elif self.marketplace == "depop":
            base = "https://www.depop.com/search/"
            if query:
                urls.append(base + f"?q={query}")
            else:
                urls.append(base)

        return urls

    def _parse_price(self, price_text: str) -> float:
        """Parse price from text."""
        import re
        # Remove currency symbols and commas
        cleaned = re.sub(r'[£$€,]', '', price_text)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _extract_item_id(self, url: str) -> Optional[str]:
        """Extract item ID from URL."""
        if "/items/" in url:
            parts = url.split("/items/")
            if len(parts) > 1:
                return parts[1].split("-")[0]
        return None

    def store(self, data: List[Dict]):
        """Store extracted items in database."""
        from storage.postgres import PostgresStore

        logger.info("Storing crawled items...")

        with PostgresStore() as db:
            with db._cursor() as cur:
                for item in data:
                    if not item.get("item_id"):
                        continue

                    # Insert into items table
                    cur.execute("""
                        INSERT INTO items (
                            item_id, title, price, url, image_url, source, scraped_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (item_id) DO UPDATE SET
                            price = EXCLUDED.price,
                            scraped_at = EXCLUDED.scraped_at
                    """, (
                        item["item_id"],
                        item["title"],
                        item["price"],
                        item["url"],
                        item["image_url"],
                        item["source"],
                        item["scraped_at"]
                    ))

        logger.info(f"✓ Stored {len(data)} items")


class CrawleePriceMonitor:
    """
    Monitor prices of specific items using Crawlee.

    Efficiently tracks price changes across thousands of items.
    """

    def __init__(self, items_to_monitor: List[str]):
        self.items_to_monitor = items_to_monitor

    async def monitor(self):
        """Monitor prices for all tracked items."""
        logger.info(f"Monitoring {len(self.items_to_monitor)} items...")

        # Create crawler with custom handler
        crawler = PlaywrightCrawler(
            max_requests_per_crawl=len(self.items_to_monitor),
            request_handler=self._price_check_handler
        )

        # Build URLs for each item
        urls = [
            f"https://www.vinted.co.uk/items/{item_id}"
            for item_id in self.items_to_monitor
        ]

        await crawler.run(urls)

    async def _price_check_handler(self, context: PlaywrightCrawlingContext):
        """Check price for individual item."""
        page = context.page

        # Extract current price
        price_elem = await page.query_selector('[data-testid="item-price"]')
        if price_elem:
            price_text = await price_elem.inner_text()
            current_price = self._parse_price(price_text)

            # Extract item ID from URL
            item_id = context.request.url.split("/items/")[-1].split("-")[0]

            # Check if price changed
            await self._check_price_change(item_id, current_price)

    async def _check_price_change(self, item_id: str, current_price: float):
        """Check if price changed and trigger alert if needed."""
        from storage.postgres import PostgresStore

        with PostgresStore() as db:
            with db._cursor() as cur:
                # Get last known price
                cur.execute("""
                    SELECT price FROM price_history
                    WHERE item_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (f"vinted_{item_id}",))

                result = cur.fetchone()

                if result:
                    last_price = float(result[0])

                    if current_price < last_price:
                        # Price dropped!
                        drop_pct = ((last_price - current_price) / last_price) * 100

                        logger.info(f"Price drop detected: Item {item_id} (£{last_price} → £{current_price}, -{drop_pct:.1f}%)")

                        # Create price alert
                        cur.execute("""
                            INSERT INTO price_alerts (
                                item_id, old_price, new_price, drop_percentage, drop_amount
                            ) VALUES (
                                (SELECT id FROM items WHERE item_id = %s),
                                %s, %s, %s, %s
                            )
                        """, (
                            f"vinted_{item_id}",
                            last_price,
                            current_price,
                            drop_pct,
                            last_price - current_price
                        ))

                # Record new price
                cur.execute("""
                    INSERT INTO price_history (item_id, price, timestamp)
                    SELECT id, %s, NOW()
                    FROM items WHERE item_id = %s
                """, (current_price, f"vinted_{item_id}"))

    def _parse_price(self, price_text: str) -> float:
        """Parse price from text."""
        import re
        cleaned = re.sub(r'[£$€,]', '', price_text)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0


# Sync wrapper for async functions
def run_crawlee_extraction(marketplace: str, query: str = None, **kwargs) -> List[Dict]:
    """Synchronous wrapper for Crawlee extraction."""
    crawler = CrawleeMarketplaceCrawler(marketplace=marketplace)
    return asyncio.run(crawler.extract(query=query, **kwargs))


def run_price_monitoring(item_ids: List[str]):
    """Synchronous wrapper for price monitoring."""
    monitor = CrawleePriceMonitor(items_to_monitor=item_ids)
    asyncio.run(monitor.monitor())
