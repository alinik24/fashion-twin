"""Vestiaire Collective collector using Playwright headless browser.

Vestiaire doesn't expose a public API, so we scrape via the rendered DOM.
The scraper extracts items from the search results grid.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from playwright.async_api import async_playwright, Page

from storage import ItemRecord

from .base import BaseCollector, CollectResult

logger = logging.getLogger(__name__)

VESTIAIRE_SEARCH_URL = "https://www.vestiairecollective.com/search/?q={query}&order=desc"


class VestiaireCollector(BaseCollector):
    source = "vestiaire"

    async def collect(
        self,
        query: str,
        pages: int = 3,
        **kwargs,
    ) -> CollectResult:
        items: list[ItemRecord] = []
        errors: list[str] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            url = VESTIAIRE_SEARCH_URL.format(query=query.replace(" ", "+"))
            try:
                for page_num in range(1, pages + 1):
                    page_url = url if page_num == 1 else f"{url}&page={page_num}"
                    await page.goto(page_url, wait_until="networkidle", timeout=30_000)
                    await page.wait_for_timeout(2000)

                    page_items = await self._extract_items(page)
                    items.extend(page_items)
                    logger.info(
                        "Vestiaire page %d/%d: %d items (query=%r)",
                        page_num,
                        pages,
                        len(page_items),
                        query,
                    )

                    if not page_items:
                        break
                    await self._delay()

            except Exception as exc:
                msg = f"Vestiaire scrape error: {exc}"
                logger.error(msg)
                errors.append(msg)
            finally:
                await browser.close()

        return CollectResult(
            items=items,
            source=self.source,
            query=query,
            pages_scraped=pages,
            errors=errors,
        )

    # ── DOM extraction ────────────────────────────────────────────────────────

    async def _extract_items(self, page: Page) -> list[ItemRecord]:
        """Extract item cards from the current Vestiaire search results page."""
        records: list[ItemRecord] = []

        # Vestiaire renders product cards with data attributes or JSON-LD
        # Try JSON-LD first (most reliable)
        ld_items = await self._extract_json_ld(page)
        if ld_items:
            return ld_items

        # Fallback: DOM scraping
        cards = await page.query_selector_all("[data-testid='product-card'], .product-card, article.product")
        for card in cards:
            try:
                rec = await self._parse_card(card)
                if rec:
                    records.append(rec)
            except Exception as exc:
                logger.debug("Card parse error: %s", exc)

        return records

    async def _extract_json_ld(self, page: Page) -> list[ItemRecord]:
        """Extract structured product data from JSON-LD script tags."""
        scripts = await page.query_selector_all('script[type="application/ld+json"]')
        records: list[ItemRecord] = []
        for script in scripts:
            try:
                content = await script.inner_text()
                data = json.loads(content)
                if isinstance(data, list):
                    items = data
                elif data.get("@type") == "ItemList":
                    items = data.get("itemListElement", [])
                else:
                    items = [data]

                for item in items:
                    if item.get("@type") not in ("Product", "Offer"):
                        item = item.get("item", item)
                    rec = self._ld_to_record(item)
                    if rec:
                        records.append(rec)
            except Exception:
                continue
        return records

    def _ld_to_record(self, ld: dict) -> Optional[ItemRecord]:
        name = ld.get("name")
        if not name:
            return None
        url = ld.get("url", "")
        ext_id = self._extract_id_from_url(url) or url[-20:]
        image = ld.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        offer = ld.get("offers", {})
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        price = self._safe_float(offer.get("price"))
        currency = offer.get("priceCurrency", "EUR")

        return ItemRecord(
            external_id=ext_id,
            source=self.source,
            title=name,
            brand=ld.get("brand", {}).get("name") if isinstance(ld.get("brand"), dict) else ld.get("brand"),
            price=price,
            currency=currency,
            image_url=str(image) if image else None,
            listing_url=url,
            raw_data=ld,
        )

    async def _parse_card(self, card: Any) -> Optional[ItemRecord]:
        """DOM fallback parser for a single product card element."""
        url_el = await card.query_selector("a[href]")
        url = await url_el.get_attribute("href") if url_el else ""
        if url and not url.startswith("http"):
            url = "https://www.vestiairecollective.com" + url

        title_el = await card.query_selector("[data-testid='product-title'], .product-title, h2, h3")
        title = await title_el.inner_text() if title_el else None

        price_el = await card.query_selector("[data-testid='product-price'], .price")
        price_text = await price_el.inner_text() if price_el else ""
        price = self._safe_float(re.sub(r"[^\d.]", "", price_text))

        image_el = await card.query_selector("img")
        image_url = await image_el.get_attribute("src") if image_el else None

        ext_id = self._extract_id_from_url(url) or url[-20:]

        if not title or not url:
            return None

        return ItemRecord(
            external_id=ext_id,
            source=self.source,
            title=title.strip(),
            price=price,
            currency="EUR",
            image_url=image_url,
            listing_url=url,
        )

    @staticmethod
    def _extract_id_from_url(url: str) -> Optional[str]:
        m = re.search(r"-(\d+)\.shtml", url) or re.search(r"/(\d+)$", url)
        return m.group(1) if m else None
