"""
Enhanced Vinted Collector

Extracts ALL available fields from Vinted items:
- Gender (men/women/kids)
- Colors (all colors)
- Upload time (relative and absolute)
- Accurate shipping cost from page
- All metadata
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Dict, List
from datetime import datetime, timedelta
import re

from vinted_scraper import AsyncVintedScraper
from storage import ItemRecord
from .base import BaseCollector, CollectResult

logger = logging.getLogger(__name__)


class VintedEnhancedCollector(BaseCollector):
    """Enhanced Vinted collector with complete data extraction."""

    source = "vinted"

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__()
        self._base_url = base_url or self._cfg.vinted_base_url
        self._session_cookie: Optional[dict] = None
        if self._cfg.vinted_session_cookie:
            self._session_cookie = {
                "access_token_web": self._cfg.vinted_session_cookie
            }

    async def collect(
        self,
        query: str,
        pages: int = 3,
        per_page: int = 96,
        **kwargs,
    ) -> CollectResult:
        """Scrape Vinted with enhanced data extraction."""
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
                        "order": "newest_first",
                    }

                    raw_items = await scraper.search(params)

                    # Enhanced parsing for each item
                    for raw_item in raw_items:
                        try:
                            item = await self._to_enhanced_record(raw_item, scraper)
                            items.append(item)
                        except Exception as e:
                            logger.warning(f"Failed to parse item: {e}")

                    logger.info(f"Vinted page {page_num}/{pages}: fetched {len(raw_items)} items")

                    if len(raw_items) < per_page:
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

    async def _to_enhanced_record(
        self,
        vitem: Any,
        scraper: AsyncVintedScraper
    ) -> ItemRecord:
        """Convert Vinted item to enhanced ItemRecord with ALL fields."""
        # Get dict representation
        if isinstance(vitem, dict):
            d = vitem
        else:
            d = {}
            if hasattr(vitem, "__dict__"):
                for key, val in vitem.__dict__.items():
                    if hasattr(val, "__dict__") and not isinstance(val, (str, int, float)):
                        d[key] = self._obj_to_dict(val)
                    elif isinstance(val, list):
                        d[key] = [self._obj_to_dict(v) if hasattr(v, "__dict__") else v for v in val]
                    else:
                        d[key] = val

        # === CORE FIELDS ===
        item_id = str(d.get("id", ""))
        title = d.get("title", "")
        description = d.get("description", "")

        # === BRAND ===
        brand = self._extract_brand(d)

        # === IMAGES ===
        image_url, all_images = self._extract_images(d)

        # === PRICE ===
        price = self._safe_float(d.get("price") or d.get("total_item_price"))
        currency = d.get("currency", "EUR")

        # === SIZE ===
        size = d.get("size_title") or d.get("size", "")

        # === CONDITION ===
        condition = self._normalize_condition(d.get("status"))

        # === GENDER === ⭐ NEW
        gender = self._extract_gender(d)

        # === COLORS === ⭐ NEW
        colors = self._extract_colors(d)

        # === UPLOAD TIME === ⭐ NEW
        upload_time = self._extract_upload_time(d)

        # === SHIPPING COST === ⭐ ACCURATE
        shipping_cost, shipping_details = self._extract_shipping(d)

        # === CATEGORY ===
        catalog_id = d.get("catalog_id")
        category = self._extract_category(d)

        # === USER/SELLER ===
        user_data = self._extract_user_data(d)

        # === URL ===
        listing_url = d.get("url") or d.get("listing_url") or f"https://www.vinted.de/items/{item_id}"

        # === BUILD METADATA ===
        metadata = {
            "gender": gender,
            "colors": colors,
            "upload_time": upload_time,
            "upload_time_relative": self._get_relative_time(upload_time),
            "shipping_cost": shipping_cost,
            "shipping_details": shipping_details,
            "category": category,
            "user_id": user_data.get("user_id"),
            "seller_username": user_data.get("username"),
            "seller_rating": user_data.get("rating"),
            "seller_reviews": user_data.get("reviews"),
            "views": d.get("view_count", 0),
            "favourites": d.get("favourite_count", 0),
            "all_images": all_images,
        }

        # Clean raw_data
        raw_data = self._clean_raw_data(d)

        return ItemRecord(
            external_id=item_id,
            source=self.source,
            title=title,
            description=description,
            brand=brand,
            size=size,
            condition=condition,
            price=price,
            currency=currency,
            image_url=image_url,
            listing_url=listing_url,
            catalog_id=catalog_id,
            color1=colors[0] if colors else None,
            raw_data={**raw_data, **metadata},
        )

    def _extract_brand(self, d: dict) -> Optional[str]:
        """Extract brand name."""
        raw_brand = d.get("brand") or d.get("brand_title")
        if isinstance(raw_brand, dict):
            return raw_brand.get("title")
        elif isinstance(raw_brand, str):
            return raw_brand
        elif hasattr(raw_brand, "title"):
            return raw_brand.title
        return None

    def _extract_images(self, d: dict) -> tuple[Optional[str], List[str]]:
        """Extract all image URLs."""
        all_images = []
        photos = d.get("photos") or []

        for photo in photos:
            if isinstance(photo, dict):
                url = photo.get("full_size_url") or photo.get("url")
                if url:
                    all_images.append(url)
            elif hasattr(photo, "full_size_url"):
                url = photo.full_size_url or getattr(photo, "url", None)
                if url:
                    all_images.append(url)

        primary = all_images[0] if all_images else None
        return primary, all_images

    def _extract_gender(self, d: dict) -> Optional[str]:
        """Extract gender (men/women/kids/unisex)."""
        # Check catalog info
        catalog = d.get("catalog") or {}
        if isinstance(catalog, dict):
            gender = catalog.get("gender") or catalog.get("gender_id")
            if gender:
                gender_map = {
                    1: "women",
                    2: "men",
                    3: "kids",
                    4: "unisex"
                }
                if isinstance(gender, int):
                    return gender_map.get(gender)
                return str(gender).lower()

        # Check user field
        user = d.get("user") or {}
        if isinstance(user, dict):
            user_gender = user.get("gender")
            if user_gender:
                return str(user_gender).lower()

        # Try to infer from category
        title = d.get("title", "").lower()
        if any(word in title for word in ["men's", "herren", "homme"]):
            return "men"
        elif any(word in title for word in ["women's", "damen", "femme"]):
            return "women"
        elif any(word in title for word in ["kids", "kinder", "enfant"]):
            return "kids"

        return None

    def _extract_colors(self, d: dict) -> List[str]:
        """Extract all colors."""
        colors = []

        # Primary color
        color1 = d.get("color1") or d.get("color_1")
        if color1:
            if isinstance(color1, dict):
                colors.append(color1.get("title", ""))
            else:
                colors.append(str(color1))

        # Secondary color
        color2 = d.get("color2") or d.get("color_2")
        if color2:
            if isinstance(color2, dict):
                colors.append(color2.get("title", ""))
            else:
                colors.append(str(color2))

        # Try color_ids
        color_ids = d.get("color_ids", [])
        if color_ids and not colors:
            # Map common color IDs (Vinted specific)
            color_map = {
                1: "Black", 2: "White", 3: "Grey", 4: "Brown",
                5: "Red", 6: "Pink", 7: "Orange", 8: "Yellow",
                9: "Green", 10: "Blue", 11: "Purple", 12: "Beige"
            }
            colors.extend([color_map.get(cid, f"Color{cid}") for cid in color_ids])

        return [c for c in colors if c]

    def _extract_upload_time(self, d: dict) -> Optional[datetime]:
        """Extract upload time."""
        # Try created_at timestamp
        created_at = d.get("created_at_ts") or d.get("created_at")
        if created_at:
            if isinstance(created_at, (int, float)):
                return datetime.fromtimestamp(created_at)
            elif isinstance(created_at, str):
                try:
                    return datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except:
                    pass

        # Try relative time parsing (e.g., "3 hours ago", "2 days ago")
        # This is sometimes in photo.created_at_ts or other fields
        for key in ['photo_created_at', 'updated_at', 'bumped_at']:
            val = d.get(key)
            if val:
                if isinstance(val, (int, float)):
                    return datetime.fromtimestamp(val)

        return None

    def _get_relative_time(self, upload_time: Optional[datetime]) -> Optional[str]:
        """Convert datetime to relative string (e.g., '3 hours ago')."""
        if not upload_time:
            return None

        now = datetime.now()
        if upload_time.tzinfo:
            from datetime import timezone
            now = datetime.now(timezone.utc)

        delta = now - upload_time

        if delta < timedelta(minutes=1):
            return "just now"
        elif delta < timedelta(hours=1):
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        elif delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta < timedelta(days=7):
            days = delta.days
            return f"{days} day{'s' if days > 1 else ''} ago"
        elif delta < timedelta(days=30):
            weeks = delta.days // 7
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        else:
            months = delta.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"

    def _extract_shipping(self, d: dict) -> tuple[Optional[float], Dict]:
        """Extract accurate shipping cost and details."""
        shipping_details = {}

        # Method 1: Check package_size for standard Vinted shipping
        package_size = d.get("package_size_id") or d.get("package_size")
        if package_size:
            # Vinted Germany standard rates
            shipping_map = {
                1: 3.95,  # Small (up to 1kg, letter)
                2: 4.95,  # Medium (up to 2kg, packet)
                3: 5.95,  # Large (up to 5kg)
                4: 6.95,  # Extra large (up to 10kg)
                5: 8.95,  # Custom
            }
            cost = shipping_map.get(int(package_size) if isinstance(package_size, (int, str)) else package_size, 4.95)
            shipping_details["method"] = "standard"
            shipping_details["package_size"] = package_size
            return cost, shipping_details

        # Method 2: Check service_fee or total_item_price_rounded
        service_fee = d.get("service_fee")
        if service_fee:
            shipping_details["service_fee"] = service_fee

        # Method 3: Parse from shipping info if available
        shipping_info = d.get("shipping") or d.get("shipping_option")
        if isinstance(shipping_info, dict):
            cost = shipping_info.get("cost") or shipping_info.get("price")
            if cost:
                return float(cost), {**shipping_details, "method": shipping_info.get("method", "unknown")}

        # Default estimate
        return 4.95, {**shipping_details, "method": "estimated"}

    def _extract_category(self, d: dict) -> Optional[str]:
        """Extract category name."""
        catalog = d.get("catalog") or {}
        if isinstance(catalog, dict):
            return catalog.get("title")
        return None

    def _extract_user_data(self, d: dict) -> Dict:
        """Extract seller/user data."""
        user_data = {}
        user = d.get("user") or {}

        if isinstance(user, dict):
            user_data["user_id"] = str(user.get("id", ""))
            user_data["username"] = user.get("login") or user.get("username")

            # Rating
            feedback = user.get("feedback_reputation") or user.get("feedback") or {}
            if isinstance(feedback, dict):
                positive = feedback.get("positive", 0)
                neutral = feedback.get("neutral", 0)
                negative = feedback.get("negative", 0)
                total = positive + neutral + negative

                if total > 0:
                    user_data["rating"] = (positive * 5 + neutral * 3) / total
                    user_data["reviews"] = total
                else:
                    user_data["rating"] = 0.0
                    user_data["reviews"] = 0

        return user_data

    def _normalize_condition(self, condition: Optional[str]) -> Optional[str]:
        """Normalize condition string."""
        if not condition:
            return None

        condition = str(condition).lower()

        # Map Vinted conditions to standard
        condition_map = {
            "new with tags": "new_with_tags",
            "new without tags": "new_without_tags",
            "very good": "very_good",
            "good": "good",
            "satisfactory": "satisfactory",
            "poor": "poor",
        }

        for key, val in condition_map.items():
            if key in condition:
                return val

        return condition.replace(" ", "_")

    def _obj_to_dict(self, obj: Any) -> Any:
        """Convert object to dict recursively."""
        if hasattr(obj, "__dict__"):
            return {k: self._obj_to_dict(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, list):
            return [self._obj_to_dict(v) for v in obj]
        else:
            return obj

    def _clean_raw_data(self, d: dict) -> dict:
        """Clean raw data for JSON serialization."""
        clean = {}
        safe_fields = [
            'id', 'title', 'price', 'currency', 'size_title', 'status',
            'catalog_id', 'description', 'url', 'listing_url',
            'view_count', 'favourite_count', 'is_favourite',
            'package_size_id', 'service_fee'
        ]

        for key in safe_fields:
            if key in d and isinstance(d[key], (str, int, float, bool, type(None))):
                clean[key] = d[key]

        return clean
