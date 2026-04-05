"""GDPR Export Extractor

Processes Vinted's official GDPR data export (most complete data source).

Vinted's GDPR export contains EVERYTHING they know about you:
- Full browsing history
- All searches
- All messages
- All offers
- All purchases
- All favorites
- Device info
- Session logs
- Analytics data
- Much more...

This is the GOLD STANDARD - contains all data that Vinted's algorithm uses.

How to get your GDPR export:
    1. Login to Vinted
    2. Settings → Privacy → Download My Data
    3. Wait 24-48 hours for email
    4. Download ZIP file
    5. Place in data/exports/vinted_gdpr_export.zip
"""

import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .base import BaseExtractor

logger = logging.getLogger(__name__)


class GDPRExportExtractor(BaseExtractor):
    """Extract and process Vinted GDPR export data."""

    def __init__(self, export_path: str = None):
        super().__init__()
        self.export_path = Path(export_path) if export_path else None

    def extract(self, export_path: str = None, **kwargs) -> Dict:
        """
        Extract all data from GDPR export ZIP file.

        Args:
            export_path: Path to GDPR export ZIP

        Returns:
            Dict containing all extracted data categories
        """
        if export_path:
            self.export_path = Path(export_path)

        if not self.export_path or not self.export_path.exists():
            raise FileNotFoundError(
                f"GDPR export not found at {self.export_path}\n"
                "Download your data: Vinted → Settings → Privacy → Download My Data"
            )

        logger.info(f"Extracting GDPR export from {self.export_path}")

        extracted_data = {}

        with zipfile.ZipFile(self.export_path) as zf:
            # Vinted GDPR export structure:
            # vinted_export/
            #   ├── profile.json
            #   ├── favorites.json
            #   ├── purchases.json
            #   ├── messages.json
            #   ├── searches.json
            #   ├── browsing_history.json
            #   ├── offers.json
            #   ├── listings.json (if you sell)
            #   ├── analytics.json
            #   └── sessions.json

            for filename in zf.namelist():
                if filename.endswith(".json"):
                    category = Path(filename).stem
                    logger.info(f"  Extracting {category}...")

                    with zf.open(filename) as f:
                        data = json.load(f)
                        extracted_data[category] = self._process_category(category, data)

        logger.info(f"✓ Extracted {len(extracted_data)} data categories")
        return extracted_data

    def _process_category(self, category: str, data: any) -> List[Dict]:
        """Process each category of GDPR data."""

        if category == "favorites":
            return self._process_favorites(data)

        elif category == "purchases":
            return self._process_purchases(data)

        elif category == "messages":
            return self._process_messages(data)

        elif category == "searches":
            return self._process_searches(data)

        elif category == "browsing_history":
            return self._process_browsing_history(data)

        elif category == "offers":
            return self._process_offers(data)

        elif category == "listings":
            return self._process_listings(data)

        elif category == "analytics":
            return self._process_analytics(data)

        elif category == "sessions":
            return self._process_sessions(data)

        else:
            # Unknown category - store as-is
            logger.warning(f"Unknown GDPR category: {category}")
            return data if isinstance(data, list) else [data]

    def _process_favorites(self, data: List[Dict]) -> List[Dict]:
        """Process favorites data."""
        favorites = []
        for item in data:
            favorites.append({
                "item_id": f"vinted_{item.get('item_id')}",
                "title": item.get("title"),
                "price": item.get("price"),
                "brand": item.get("brand"),
                "url": item.get("url"),
                "image_url": item.get("photo"),
                "favorited_at": item.get("created_at"),
                "source": "gdpr_export",
                "weight": 1.0  # Strong signal
            })
        return favorites

    def _process_purchases(self, data: List[Dict]) -> List[Dict]:
        """Process purchase history."""
        purchases = []
        for item in data:
            purchases.append({
                "item_id": f"vinted_{item.get('item_id')}",
                "title": item.get("title"),
                "price_paid": item.get("total_price"),
                "purchase_date": item.get("purchased_at"),
                "condition": item.get("condition"),
                "brand": item.get("brand"),
                "source": "gdpr_export",
                "weight": 1.5  # Strongest signal - actual purchase!
            })
        return purchases

    def _process_messages(self, data: List[Dict]) -> List[Dict]:
        """
        Process message history.

        CRITICAL: This contains your offer negotiations!
        """
        messages = []
        for msg in data:
            # Extract offer amount if present
            offer_amount = None
            text = msg.get("message", "")

            if "offer" in text.lower() or "£" in text or "€" in text:
                import re
                price_match = re.search(r'[£€]\s*(\d+(?:\.\d{2})?)', text)
                if price_match:
                    offer_amount = float(price_match.group(1))

            messages.append({
                "item_id": f"vinted_{msg.get('item_id')}" if msg.get("item_id") else None,
                "message_id": msg.get("id"),
                "text": text,
                "offer_amount": offer_amount,
                "is_yours": msg.get("sender_id") == msg.get("your_user_id"),
                "timestamp": msg.get("created_at"),
                "source": "gdpr_export",
                "weight": 1.2 if offer_amount else 0.8
            })
        return messages

    def _process_searches(self, data: List[Dict]) -> List[Dict]:
        """
        Process search history.

        This tells us exactly what you're looking for!
        """
        searches = []
        for search in data:
            searches.append({
                "query": search.get("query"),
                "filters": search.get("filters", {}),
                "timestamp": search.get("searched_at"),
                "results_count": search.get("results_count"),
                "source": "gdpr_export",
                "weight": 0.8
            })
        return searches

    def _process_browsing_history(self, data: List[Dict]) -> List[Dict]:
        """
        Process full browsing history.

        THIS IS GOLD! Shows every item you viewed, for how long, etc.
        This is what Vinted's algorithm uses to understand you.
        """
        history = []
        for view in data:
            history.append({
                "item_id": f"vinted_{view.get('item_id')}",
                "title": view.get("title"),
                "viewed_at": view.get("viewed_at"),
                "dwell_time_seconds": view.get("time_spent", 0),
                "scroll_depth_percent": view.get("scroll_depth", 0),
                "images_viewed": view.get("images_viewed", []),
                "source": "gdpr_export",
                "weight": 0.7
            })
        return history

    def _process_offers(self, data: List[Dict]) -> List[Dict]:
        """
        Process offer history.

        Shows your negotiation patterns and price sensitivity.
        """
        offers = []
        for offer in data:
            offers.append({
                "item_id": f"vinted_{offer.get('item_id')}",
                "offer_amount": offer.get("amount"),
                "asking_price": offer.get("asking_price"),
                "discount_pct": ((offer.get("asking_price", 0) - offer.get("amount", 0)) /
                                offer.get("asking_price", 1)) * 100 if offer.get("asking_price") else 0,
                "status": offer.get("status"),  # accepted, rejected, countered
                "created_at": offer.get("created_at"),
                "source": "gdpr_export",
                "weight": 1.3  # Very strong signal of interest
            })
        return offers

    def _process_listings(self, data: List[Dict]) -> List[Dict]:
        """
        Process your own listings (if you sell on Vinted).

        For RESELLERS: This is critical data!
        """
        listings = []
        for listing in data:
            listings.append({
                "item_id": f"vinted_sold_{listing.get('id')}",
                "title": listing.get("title"),
                "listed_price": listing.get("price"),
                "sold_price": listing.get("sold_price"),
                "profit_margin": ((listing.get("sold_price", 0) - listing.get("cost_basis", 0)) /
                                 listing.get("sold_price", 1)) * 100 if listing.get("sold_price") else 0,
                "cost_basis": listing.get("cost_basis"),  # What you paid
                "views": listing.get("views"),
                "favorites": listing.get("favorites"),
                "messages_received": listing.get("messages"),
                "days_to_sell": listing.get("days_to_sell"),
                "listed_at": listing.get("created_at"),
                "sold_at": listing.get("sold_at"),
                "source": "gdpr_export",
                "weight": 1.5  # Critical for reseller mode!
            })
        return listings

    def _process_analytics(self, data: Dict) -> List[Dict]:
        """
        Process Vinted's analytics data about you.

        This contains high-level patterns that Vinted has identified.
        """
        analytics = []

        # Extract key metrics
        if "user_segments" in data:
            for segment in data["user_segments"]:
                analytics.append({
                    "type": "user_segment",
                    "value": segment,
                    "source": "gdpr_export"
                })

        if "browsing_patterns" in data:
            analytics.append({
                "type": "browsing_pattern",
                "data": data["browsing_patterns"],
                "source": "gdpr_export"
            })

        if "price_sensitivity" in data:
            analytics.append({
                "type": "price_sensitivity",
                "score": data["price_sensitivity"],
                "source": "gdpr_export"
            })

        return analytics

    def _process_sessions(self, data: List[Dict]) -> List[Dict]:
        """
        Process session data.

        Shows when you browse, for how long, device type, etc.
        """
        sessions = []
        for session in data:
            sessions.append({
                "session_id": session.get("id"),
                "started_at": session.get("started_at"),
                "ended_at": session.get("ended_at"),
                "duration_seconds": session.get("duration"),
                "device_type": session.get("device_type"),
                "browser": session.get("browser"),
                "pages_viewed": session.get("pages_viewed"),
                "items_viewed": session.get("items_viewed", []),
                "source": "gdpr_export"
            })
        return sessions

    def store(self, data: Dict):
        """
        Store all GDPR export data in database.

        Args:
            data: Dict of all extracted categories
        """
        from storage.postgres import PostgresStore

        logger.info("Storing GDPR export data...")

        with PostgresStore() as db:
            with db._cursor() as cur:
                # Store each category
                for category, items in data.items():
                    logger.info(f"  Storing {len(items)} {category} items")

                    if category == "favorites":
                        self._store_favorites(cur, items)
                    elif category == "purchases":
                        self._store_purchases(cur, items)
                    elif category == "messages":
                        self._store_messages(cur, items)
                    elif category == "browsing_history":
                        self._store_browsing_history(cur, items)
                    elif category == "offers":
                        self._store_offers(cur, items)
                    elif category == "listings":
                        self._store_listings(cur, items)
                    # ... etc

        logger.info("✓ GDPR export data stored")

    def _store_favorites(self, cur, items):
        """Store favorites in database."""
        for item in items:
            # Insert into items table
            cur.execute("""
                INSERT INTO items (item_id, title, price, brand, url, image_url, source, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (item_id) DO NOTHING
                RETURNING id
            """, (
                item["item_id"], item["title"], item["price"], item["brand"],
                item["url"], item["image_url"], item["source"], item["favorited_at"]
            ))

            result = cur.fetchone()
            if result:
                item_db_id = result[0]

                # Create interaction
                cur.execute("""
                    INSERT INTO interactions (item_id, rating, source, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (item_id) DO UPDATE SET rating = EXCLUDED.rating
                """, (item_db_id, item["weight"], item["source"], item["favorited_at"]))

    def _store_purchases(self, cur, items):
        """Store purchase history."""
        for item in items:
            # Purchases are strongest signal
            cur.execute("""
                INSERT INTO interactions (item_id, rating, source, created_at)
                SELECT id, %s, %s, %s FROM items WHERE item_id = %s
                ON CONFLICT (item_id) DO UPDATE SET rating = EXCLUDED.rating
            """, (item["weight"], item["source"], item["purchase_date"], item["item_id"]))

    def _store_messages(self, cur, items):
        """Store message history."""
        for msg in items:
            if msg["offer_amount"]:
                # Store as behavior signal
                cur.execute("""
                    INSERT INTO behavior_signals (item_id, signal_type, signal_value, metadata, created_at)
                    SELECT id, 'offer_made', %s, %s, %s FROM items WHERE item_id = %s
                """, (
                    msg["offer_amount"],
                    json.dumps({"text": msg["text"][:200]}),
                    msg["timestamp"],
                    msg["item_id"]
                ))

    def _store_browsing_history(self, cur, items):
        """Store browsing history with dwell times."""
        for view in items:
            # Store as behavior signal
            cur.execute("""
                INSERT INTO behavior_signals (item_id, signal_type, signal_value, metadata, created_at)
                SELECT id, 'item_viewed', %s, %s, %s FROM items WHERE item_id = %s
            """, (
                view["dwell_time_seconds"],
                json.dumps({
                    "scroll_depth": view["scroll_depth_percent"],
                    "images_viewed": view["images_viewed"]
                }),
                view["viewed_at"],
                view["item_id"]
            ))

    def _store_offers(self, cur, items):
        """Store offer history."""
        for offer in items:
            cur.execute("""
                INSERT INTO behavior_signals (item_id, signal_type, signal_value, metadata, created_at)
                SELECT id, 'offer_made', %s, %s, %s FROM items WHERE item_id = %s
            """, (
                offer["offer_amount"],
                json.dumps({
                    "asking_price": offer["asking_price"],
                    "discount_pct": offer["discount_pct"],
                    "status": offer["status"]
                }),
                offer["created_at"],
                offer["item_id"]
            ))

    def _store_listings(self, cur, items):
        """Store your own listings (for resellers)."""
        # This would go in a separate reseller_inventory table
        pass


def request_gdpr_export_instructions():
    """Print instructions for requesting GDPR export."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     HOW TO GET YOUR VINTED DATA EXPORT                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

This is the MOST COMPLETE data source - contains everything Vinted knows about you!

STEP 1: Request Your Data
    1. Login to Vinted (vinted.co.uk)
    2. Click your profile → Settings ⚙️
    3. Go to "Privacy & Data"
    4. Click "Download My Data"
    5. Confirm request

STEP 2: Wait
    - Vinted takes 24-48 hours to prepare your export
    - You'll receive an email when ready
    - Link expires after 7 days

STEP 3: Download
    - Click link in email
    - Download ZIP file (usually 10-50MB)
    - Save to: data/exports/vinted_gdpr_export.zip

STEP 4: Import
    python scripts/import_gdpr_export.py

WHAT YOU'LL GET:
    ✓ Complete browsing history (every item you viewed)
    ✓ All searches (exact queries + filters)
    ✓ All messages (including offers)
    ✓ All favorites
    ✓ All purchases
    ✓ All your listings (if you sell)
    ✓ Session logs (when you browse, for how long)
    ✓ Analytics (Vinted's insights about you)
    ✓ Device info (what you browse on)
    ✓ And much more...

This is literally the SAME data Vinted's algorithm uses to recommend items to you.
By importing this, Fashion Twin learns EXACTLY what Vinted knows about you.

═══════════════════════════════════════════════════════════════════════════════
Note: You can request this once every 30 days (GDPR limitation)
═══════════════════════════════════════════════════════════════════════════════
    """)
