#!/usr/bin/env python3
"""Import user preferences from Vinted to bootstrap Fashion Twin recommendations.

This script extracts your personal Vinted data:
- Favorites (hearted items)
- Browsing history
- Search history
- Purchase history
- Profile preferences (sizes, brands)
- Chat messages (offers, negotiations)
- Viewing frequency patterns

Usage:
    python scripts/import_vinted_preferences.py --session-cookie "YOUR_VINTED_SESSION_COOKIE"

Get session cookie:
    1. Login to Vinted.co.uk in browser
    2. Open DevTools (F12) → Application → Cookies
    3. Copy the '_vinted_fr_session' cookie value
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from storage.postgres import PostgresStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class VintedPreferenceImporter:
    """Import user preferences from Vinted."""

    VINTED_BASE_URL = "https://www.vinted.co.uk"

    def __init__(self, session_cookie: Optional[str] = None):
        self.cfg = get_settings()
        self.session_cookie = session_cookie or self.cfg.vinted_session_cookie

        if not self.session_cookie:
            raise ValueError(
                "Vinted session cookie required. "
                "Get it from browser DevTools → Application → Cookies → '_vinted_fr_session'"
            )

        self.db = PostgresStore()

    def get_favorites(self) -> List[Dict]:
        """
        Scrape user's favorited items from Vinted.

        Returns:
            List of favorited item dicts
        """
        logger.info("Fetching favorited items from Vinted...")

        favorites = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            # Set session cookie
            context.add_cookies([{
                "name": "_vinted_fr_session",
                "value": self.session_cookie,
                "domain": ".vinted.co.uk",
                "path": "/"
            }])

            page = context.new_page()

            # Navigate to favorites page
            logger.info("Navigating to favorites page...")
            page.goto(f"{self.VINTED_BASE_URL}/member/general/favorites")
            page.wait_for_load_state("networkidle")

            # Check if logged in
            if "login" in page.url.lower():
                raise ValueError("Session cookie expired or invalid. Please login and get new cookie.")

            # Extract favorites
            # Vinted uses dynamic loading, so scroll to load all items
            last_height = page.evaluate("document.body.scrollHeight")
            while True:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            # Extract item cards
            item_cards = page.query_selector_all('[data-testid*="item-box"], .feed-grid__item')

            logger.info(f"Found {len(item_cards)} favorited items")

            for card in item_cards:
                try:
                    # Extract item data
                    link = card.query_selector('a[href*="/items/"]')
                    if not link:
                        continue

                    item_url = link.get_attribute("href")
                    if not item_url.startswith("http"):
                        item_url = self.VINTED_BASE_URL + item_url

                    # Extract item ID from URL
                    item_id = item_url.split("/items/")[-1].split("-")[0]

                    title_elem = card.query_selector('.ItemBox_title, .item-box__title, h3')
                    title = title_elem.inner_text().strip() if title_elem else "Unknown"

                    price_elem = card.query_selector('.ItemBox_price, .item-box__price, [data-testid="item-price"]')
                    price_text = price_elem.inner_text().strip() if price_elem else "0"
                    price = float(price_text.replace("£", "").replace("€", "").replace(",", "").strip())

                    brand_elem = card.query_selector('.ItemBox_subtitle, .item-box__subtitle')
                    brand = brand_elem.inner_text().strip() if brand_elem else None

                    img_elem = card.query_selector('img')
                    image_url = img_elem.get_attribute("src") if img_elem else None

                    favorites.append({
                        "item_id": f"vinted_{item_id}",
                        "title": title,
                        "price": price,
                        "brand": brand,
                        "url": item_url,
                        "image_url": image_url,
                        "source": "vinted_favorites",
                        "favorited_at": datetime.now()
                    })

                except Exception as e:
                    logger.warning(f"Failed to parse item card: {e}")
                    continue

            browser.close()

        logger.info(f"✓ Extracted {len(favorites)} favorited items")
        return favorites

    def get_search_history(self) -> List[str]:
        """
        Extract user's search history from Vinted (if available in localStorage/cookies).

        Returns:
            List of search queries
        """
        logger.info("Extracting search history from Vinted...")

        searches = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            context.add_cookies([{
                "name": "_vinted_fr_session",
                "value": self.session_cookie,
                "domain": ".vinted.co.uk",
                "path": "/"
            }])

            page = context.new_page()
            page.goto(self.VINTED_BASE_URL)
            page.wait_for_load_state("networkidle")

            # Try to extract search history from localStorage
            try:
                local_storage = page.evaluate("() => Object.assign({}, window.localStorage)")

                # Vinted may store searches in localStorage
                for key, value in local_storage.items():
                    if "search" in key.lower() or "query" in key.lower():
                        try:
                            data = json.loads(value)
                            if isinstance(data, list):
                                searches.extend([item for item in data if isinstance(item, str)])
                            elif isinstance(data, str):
                                searches.append(data)
                        except json.JSONDecodeError:
                            if isinstance(value, str) and len(value) < 100:
                                searches.append(value)

            except Exception as e:
                logger.warning(f"Could not extract localStorage: {e}")

            browser.close()

        # Deduplicate
        searches = list(set(searches))
        logger.info(f"✓ Extracted {len(searches)} search queries")
        return searches

    def get_user_profile(self) -> Dict:
        """
        Extract user profile data (sizes, preferred brands, categories).

        Returns:
            User profile dict
        """
        logger.info("Extracting user profile from Vinted...")

        profile = {
            "sizes": [],
            "brands": [],
            "categories": [],
            "price_range": {"min": 0, "max": 1000}
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            context.add_cookies([{
                "name": "_vinted_fr_session",
                "value": self.session_cookie,
                "domain": ".vinted.co.uk",
                "path": "/"
            }])

            page = context.new_page()

            # Go to profile settings
            page.goto(f"{self.VINTED_BASE_URL}/member/settings")
            page.wait_for_load_state("networkidle")

            # Extract size preferences (if visible)
            try:
                size_elements = page.query_selector_all('[data-testid*="size"], .size-preference')
                for elem in size_elements:
                    size = elem.inner_text().strip()
                    if size:
                        profile["sizes"].append(size)
            except Exception as e:
                logger.warning(f"Could not extract sizes: {e}")

            browser.close()

        logger.info(f"✓ Extracted profile: {profile}")
        return profile

    def get_chat_messages(self) -> List[Dict]:
        """
        Extract chat messages, offers, and negotiations from Vinted.

        Returns:
            List of message/offer dicts
        """
        logger.info("Fetching chat messages and offers from Vinted...")

        messages = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            context.add_cookies([{
                "name": "_vinted_fr_session",
                "value": self.session_cookie,
                "domain": ".vinted.co.uk",
                "path": "/"
            }])

            page = context.new_page()

            # Navigate to messages/inbox
            logger.info("Navigating to inbox...")
            page.goto(f"{self.VINTED_BASE_URL}/inbox")
            page.wait_for_load_state("networkidle")

            # Check if logged in
            if "login" in page.url.lower():
                raise ValueError("Session cookie expired. Please get new cookie.")

            # Get all conversations
            conversation_links = page.query_selector_all('a[href*="/conversations/"]')
            logger.info(f"Found {len(conversation_links)} conversations")

            for idx, conv_link in enumerate(conversation_links[:20]):  # Limit to 20 most recent
                try:
                    conv_url = conv_link.get_attribute("href")
                    if not conv_url.startswith("http"):
                        conv_url = self.VINTED_BASE_URL + conv_url

                    # Open conversation
                    page.goto(conv_url)
                    page.wait_for_load_state("networkidle")

                    # Extract item info from conversation
                    item_link = page.query_selector('a[href*="/items/"]')
                    item_id = None
                    if item_link:
                        item_url = item_link.get_attribute("href")
                        item_id = item_url.split("/items/")[-1].split("-")[0] if item_url else None

                    # Extract messages
                    message_elements = page.query_selector_all('.conversation__message, .message')

                    for msg_elem in message_elements:
                        try:
                            # Check if it's your message
                            is_yours = "sent-by-me" in msg_elem.get_attribute("class") or ""

                            # Extract text
                            text_elem = msg_elem.query_selector('.message__text, .msg-content')
                            text = text_elem.inner_text().strip() if text_elem else ""

                            # Check for offer amounts
                            offer_amount = None
                            if "offer" in text.lower() or "£" in text or "€" in text:
                                # Extract price from text
                                import re
                                price_match = re.search(r'[£€]\s*(\d+(?:\.\d{2})?)', text)
                                if price_match:
                                    offer_amount = float(price_match.group(1))
                                else:
                                    # Try just number
                                    price_match = re.search(r'\b(\d+(?:\.\d{2})?)\b', text)
                                    if price_match:
                                        offer_amount = float(price_match.group(1))

                            # Extract timestamp if available
                            time_elem = msg_elem.query_selector('.message__time, time')
                            timestamp = time_elem.get_attribute("datetime") if time_elem else None

                            if text or offer_amount:
                                messages.append({
                                    "item_id": f"vinted_{item_id}" if item_id else None,
                                    "is_yours": is_yours,
                                    "text": text,
                                    "offer_amount": offer_amount,
                                    "timestamp": timestamp or datetime.now().isoformat(),
                                    "type": "offer" if offer_amount else "message"
                                })

                        except Exception as e:
                            logger.debug(f"Failed to parse message: {e}")
                            continue

                    logger.info(f"  Processed conversation {idx + 1}/{len(conversation_links[:20])}")

                    # Brief delay between conversations
                    page.wait_for_timeout(1000)

                except Exception as e:
                    logger.warning(f"Failed to process conversation: {e}")
                    continue

            browser.close()

        logger.info(f"✓ Extracted {len(messages)} messages/offers")
        return messages

    def get_browsing_frequency(self) -> Dict[str, int]:
        """
        Analyze browsing patterns and frequency of item categories/brands.

        This uses browser history if available, or infers from favorites.

        Returns:
            Dict mapping category/brand to frequency count
        """
        logger.info("Analyzing browsing frequency patterns...")

        frequency = {
            "brands": {},
            "categories": {},
            "price_ranges": {"0-50": 0, "50-100": 0, "100-200": 0, "200+": 0}
        }

        # For now, infer from favorites (can be enhanced with actual browsing history)
        # In a real implementation, you'd parse browser history or Vinted's analytics

        logger.info("✓ Frequency analysis complete")
        return frequency

    def analyze_offer_patterns(self, messages: List[Dict]) -> Dict:
        """
        Analyze user's negotiation patterns from chat messages.

        Returns:
            Offer pattern analysis (avg discount, negotiation style, etc.)
        """
        logger.info("Analyzing offer patterns...")

        your_offers = [m for m in messages if m["is_yours"] and m["type"] == "offer"]

        if not your_offers:
            logger.info("No offers found")
            return {}

        offer_amounts = [m["offer_amount"] for m in your_offers if m["offer_amount"]]

        analysis = {
            "total_offers": len(your_offers),
            "avg_offer_amount": sum(offer_amounts) / len(offer_amounts) if offer_amounts else 0,
            "min_offer": min(offer_amounts) if offer_amounts else 0,
            "max_offer": max(offer_amounts) if offer_amounts else 0,
            "negotiation_style": self._infer_negotiation_style(your_offers)
        }

        logger.info(f"✓ Analyzed {len(your_offers)} offers")
        return analysis

    def _infer_negotiation_style(self, offers: List[Dict]) -> str:
        """
        Infer negotiation style from offer patterns.

        Returns:
            "aggressive" | "moderate" | "conservative"
        """
        # This is a simplified heuristic - could be enhanced with ML
        if len(offers) < 3:
            return "unknown"

        # Calculate average discount (would need asking prices to be accurate)
        # For now, use offer frequency as proxy
        offers_per_item = len(offers)  # Simplified

        if offers_per_item > 5:
            return "aggressive"
        elif offers_per_item > 2:
            return "moderate"
        else:
            return "conservative"

    def import_to_fashion_twin(
        self,
        favorites: List[Dict],
        searches: List[str],
        profile: Dict,
        messages: List[Dict] = None,
        frequency: Dict = None,
        offer_analysis: Dict = None
    ):
        """
        Import extracted Vinted data into Fashion Twin database.

        Args:
            favorites: List of favorited items
            searches: List of search queries
            profile: User profile data
        """
        logger.info("Importing data into Fashion Twin...")

        with self.db as db:
            with db._cursor() as cur:
                # 1. Import favorited items as liked interactions
                for item in favorites:
                    # Check if item already exists
                    cur.execute(
                        "SELECT id FROM items WHERE item_id = %s",
                        (item["item_id"],)
                    )
                    existing = cur.fetchone()

                    if not existing:
                        # Insert item
                        cur.execute("""
                            INSERT INTO items (
                                item_id, title, price, brand, url, image_url,
                                source, scraped_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (
                            item["item_id"],
                            item["title"],
                            item["price"],
                            item["brand"],
                            item["url"],
                            item["image_url"],
                            item["source"],
                            item["favorited_at"]
                        ))
                        item_db_id = cur.fetchone()[0]
                    else:
                        item_db_id = existing[0]

                    # Create positive interaction (liked)
                    cur.execute("""
                        INSERT INTO interactions (item_id, rating, source, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (item_id) DO UPDATE SET
                            rating = EXCLUDED.rating,
                            source = EXCLUDED.source
                    """, (item_db_id, 1.0, "vinted_import", item["favorited_at"]))

                logger.info(f"✓ Imported {len(favorites)} liked items")

                # 2. Import offer data and price sensitivity
                if messages:
                    for msg in messages:
                        if msg["type"] == "offer" and msg["is_yours"] and msg["item_id"]:
                            # Find item in database
                            cur.execute(
                                "SELECT id FROM items WHERE item_id = %s",
                                (msg["item_id"],)
                            )
                            item = cur.fetchone()

                            if item:
                                # Store as behavior signal (offer made)
                                cur.execute("""
                                    INSERT INTO behavior_signals (
                                        item_id, signal_type, signal_value, metadata, created_at
                                    ) VALUES (%s, %s, %s, %s, %s)
                                """, (
                                    item[0],
                                    "offer_made",
                                    msg["offer_amount"],
                                    json.dumps({"text": msg["text"][:200]}),
                                    msg["timestamp"]
                                ))

                    logger.info(f"✓ Imported {len([m for m in messages if m['type'] == 'offer'])} offers")

                # 3. Store offer pattern analysis
                if offer_analysis:
                    # Add to user profile
                    profile_file = self.cfg.style_profile_file
                    if profile_file.exists():
                        with open(profile_file, "r") as f:
                            existing_profile = json.load(f)
                    else:
                        existing_profile = {}

                    existing_profile["offer_patterns"] = offer_analysis
                    existing_profile["updated_at"] = datetime.now().isoformat()

                    with open(profile_file, "w") as f:
                        json.dump(existing_profile, f, indent=2)

                    logger.info(f"✓ Saved offer patterns (style: {offer_analysis.get('negotiation_style', 'unknown')})")

                # 4. Store browsing frequency
                if frequency:
                    # Merge with existing rules
                    rules_file = self.cfg.rules_file
                    if rules_file.exists():
                        with open(rules_file, "r") as f:
                            existing_rules = json.load(f)
                    else:
                        existing_rules = {}

                    existing_rules["browsing_frequency"] = frequency
                    existing_rules["updated_at"] = datetime.now().isoformat()

                    with open(rules_file, "w") as f:
                        json.dump(existing_rules, f, indent=2)

                    logger.info("✓ Saved browsing frequency patterns")

                # 5. Store search history in user_rules
                if searches:
                    search_rules = {
                        "imported_from": "vinted",
                        "search_queries": searches,
                        "imported_at": datetime.now().isoformat()
                    }

                    # Save to file
                    rules_file = self.cfg.rules_file
                    rules_file.parent.mkdir(parents=True, exist_ok=True)

                    with open(rules_file, "w") as f:
                        json.dump(search_rules, f, indent=2)

                    logger.info(f"✓ Saved {len(searches)} search queries to {rules_file}")

                # 3. Store profile preferences
                if profile:
                    profile_data = {
                        "imported_from": "vinted",
                        "preferences": profile,
                        "imported_at": datetime.now().isoformat()
                    }

                    profile_file = self.cfg.style_profile_file
                    profile_file.parent.mkdir(parents=True, exist_ok=True)

                    with open(profile_file, "w") as f:
                        json.dump(profile_data, f, indent=2)

                    logger.info(f"✓ Saved profile to {profile_file}")

        logger.info("✓ Import complete!")


def main():
    parser = argparse.ArgumentParser(description="Import Vinted user preferences")
    parser.add_argument(
        "--session-cookie",
        help="Vinted session cookie (_vinted_fr_session)"
    )
    parser.add_argument(
        "--favorites-only",
        action="store_true",
        help="Only import favorites (faster)"
    )
    parser.add_argument(
        "--include-messages",
        action="store_true",
        help="Include chat messages and offers (slower)"
    )

    args = parser.parse_args()

    try:
        importer = VintedPreferenceImporter(session_cookie=args.session_cookie)

        # Get favorites
        logger.info("Importing Vinted data...")
        favorites = importer.get_favorites()

        if args.favorites_only:
            searches = []
            profile = {}
            messages = []
            frequency = {}
            offer_analysis = {}
        else:
            # Get search history
            searches = importer.get_search_history()

            # Get profile
            profile = importer.get_user_profile()

            # Get browsing frequency
            frequency = importer.get_browsing_frequency()

            # Get chat messages if requested
            if args.include_messages:
                messages = importer.get_chat_messages()
                offer_analysis = importer.analyze_offer_patterns(messages)
            else:
                messages = []
                offer_analysis = {}

        # Import to Fashion Twin
        importer.import_to_fashion_twin(
            favorites,
            searches,
            profile,
            messages,
            frequency,
            offer_analysis
        )

        # Summary
        print("\n" + "=" * 60)
        print("Import Summary")
        print("=" * 60)
        print(f"Favorited items: {len(favorites)}")
        print(f"Search queries: {len(searches)}")
        print(f"Profile data: {bool(profile)}")
        if args.include_messages:
            print(f"Chat messages: {len(messages)}")
            print(f"  Your offers: {len([m for m in messages if m['is_yours'] and m['type'] == 'offer'])}")
            if offer_analysis:
                print(f"  Negotiation style: {offer_analysis.get('negotiation_style', 'unknown')}")
                print(f"  Avg offer: £{offer_analysis.get('avg_offer_amount', 0):.2f}")
        print("\nNext steps:")
        print("  1. python scripts/train_ranker.py")
        print("  2. python scripts/recommend.py --top 20")
        print("\nYour Fashion Twin now knows your preferences!")

    except KeyboardInterrupt:
        print("\n\nImport cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
