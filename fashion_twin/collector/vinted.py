"""Vinted collector — wraps the vinted-scraper library.

Uses the typed AsyncVintedScraper for async search + optional item detail fetch.
Falls back to the synchronous VintedScraper if async context is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from vinted_scraper import AsyncVintedScraper

from config import get_settings
from storage import ItemRecord

from .base import BaseCollector, CollectResult

logger = logging.getLogger(__name__)

# Interaction-type weights used when converting a scraped listing to a view event
_CONDITION_MAP = {
    "new_with_tags": "new_with_tags",
    "new_without_tags": "new_without_tags",
    "very_good": "very_good",
    "good": "good",
    "satisfactory": "satisfactory",
}


class VintedCollector(BaseCollector):
    source = "vinted"

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__()
        self._base_url = base_url or self._cfg.vinted_base_url
        self._session_cookie: Optional[dict] = None
        if self._cfg.vinted_session_cookie:
            self._session_cookie = {
                "access_token_web": self._cfg.vinted_session_cookie
            }

    # ── Public API ────────────────────────────────────────────────────────────

    async def collect(
        self,
        query: str,
        pages: int = 3,
        per_page: int = 96,
        order: str = "newest_first",
        price_to: Optional[float] = None,
        catalog_ids: Optional[str] = None,
        brand_ids: Optional[str] = None,
        **kwargs,
    ) -> CollectResult:
        """Scrape Vinted search results for `query`."""
        items: list[ItemRecord] = []
        errors: list[str] = []

        scraper_kwargs: dict[str, Any] = {}
        if self._session_cookie:
            scraper_kwargs["session_cookie"] = self._session_cookie

        async with AsyncVintedScraper(self._base_url, **scraper_kwargs) as scraper:
            for page_num in range(1, pages + 1):
                try:
                    params: dict[str, Any] = {
                        "search_text": query,
                        "page": page_num,
                        "per_page": per_page,
                        "order": order,
                    }
                    if price_to:
                        params["price_to"] = price_to
                    if catalog_ids:
                        params["catalog_ids"] = catalog_ids
                    if brand_ids:
                        params["brand_ids"] = brand_ids

                    raw_items = await scraper.search(params)
                    page_records = [self._to_record(i) for i in raw_items]
                    items.extend(page_records)
                    logger.info(
                        "Vinted page %d/%d: fetched %d items (query=%r)",
                        page_num,
                        pages,
                        len(page_records),
                        query,
                    )

                    if len(raw_items) < per_page:
                        logger.debug("Reached last page at %d", page_num)
                        break

                    await self._delay()

                except Exception as exc:
                    msg = f"Error on page {page_num}: {exc}"
                    logger.warning(msg)
                    errors.append(msg)
                    break

        return CollectResult(
            items=items,
            source=self.source,
            query=query,
            pages_scraped=min(pages, len(items) // per_page + 1),
            errors=errors,
        )

    async def fetch_item_detail(self, item_id: str) -> Optional[ItemRecord]:
        """Fetch full item detail by Vinted item ID."""
        async with AsyncVintedScraper(self._base_url) as scraper:
            try:
                vitem = await scraper.item(item_id)
                return self._to_record(vitem)
            except Exception as exc:
                logger.warning("Failed to fetch item %s: %s", item_id, exc)
                return None

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _to_record(self, vitem: Any) -> ItemRecord:
        """Convert a VintedItem (or raw dict) to our ItemRecord."""
        if isinstance(vitem, dict):
            d = vitem
        else:
            # VintedItem dataclass — access attributes directly
            d = vitem.__dict__ if hasattr(vitem, "__dict__") else {}

        # Extract image URL
        image_url: Optional[str] = None
        photos = d.get("photos") or []
        if photos:
            first = photos[0]
            if isinstance(first, dict):
                image_url = first.get("full_size_url") or first.get("url")
            elif hasattr(first, "full_size_url"):
                image_url = first.full_size_url or getattr(first, "url", None)

        # Extract brand
        brand: Optional[str] = None
        raw_brand = d.get("brand") or d.get("brand_title")
        if isinstance(raw_brand, dict):
            brand = raw_brand.get("title")
        elif isinstance(raw_brand, str):
            brand = raw_brand
        elif hasattr(raw_brand, "title"):
            brand = raw_brand.title

        # Price
        price = self._safe_float(d.get("price") or d.get("total_item_price"))

        # Condition / status
        condition = d.get("status") or None

        return ItemRecord(
            external_id=str(d.get("id", "")),
            source=self.source,
            title=d.get("title"),
            description=d.get("description"),
            brand=brand,
            size=d.get("size_title"),
            condition=condition,
            price=price,
            currency=d.get("currency") or "GBP",
            image_url=image_url,
            listing_url=d.get("url") or d.get("listing_url") or "",
            catalog_id=d.get("catalog_id"),
            color1=d.get("color1"),
            raw_data=d if isinstance(d, dict) else {},
        )
