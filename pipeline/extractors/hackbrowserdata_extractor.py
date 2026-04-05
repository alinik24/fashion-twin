"""HackBrowserData Integration

Automatically extracts ALL browser data related to Vinted:
- Session cookies (no manual copy needed!)
- Complete browsing history with timestamps
- LocalStorage data (cached preferences)
- Downloads (saved images)

Uses: https://github.com/moonD4rk/HackBrowserData

Installation:
    # Windows
    go install github.com/moonD4rk/HackBrowserData@latest

    # Or download binary from releases
    https://github.com/moonD4rk/HackBrowserData/releases

Usage:
    python scripts/import_browser_data.py --browser chrome
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

from .base import BaseExtractor

logger = logging.getLogger(__name__)


class HackBrowserDataExtractor(BaseExtractor):
    """Extract browser data using HackBrowserData tool."""

    # Marketplaces to filter for
    MARKETPLACE_DOMAINS = [
        "vinted.co.uk",
        "vinted.fr",
        "vinted.de",
        "vestiairecollective.com",
        "depop.com",
        "ebay.com",
        "grailed.com",
        "poshmark.com"
    ]

    def __init__(self, hackbrowserdata_path: str = "hack-browser-data"):
        super().__init__()
        self.tool_path = hackbrowserdata_path

    def extract(self, browser: str = "chrome", **kwargs) -> Dict[str, List[Dict]]:
        """
        Extract all browser data for marketplace sites.

        Args:
            browser: Browser to extract from (chrome, firefox, edge, etc.)

        Returns:
            Dict containing:
                - history: Browsing history
                - cookies: Session cookies
                - downloads: Downloaded files
                - localstorage: Cached data
        """
        logger.info(f"Extracting data from {browser}...")

        # Run HackBrowserData
        output_dir = Path("./data/browser_export")
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Execute HackBrowserData
            cmd = [
                self.tool_path,
                "-b", browser,
                "-output", str(output_dir),
                "-format", "json"
            ]

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            logger.info("✓ Browser data extracted")

        except subprocess.CalledProcessError as e:
            logger.error(f"HackBrowserData failed: {e.stderr}")
            raise
        except FileNotFoundError:
            logger.error(
                "HackBrowserData not found. Install from: "
                "https://github.com/moonD4rk/HackBrowserData/releases"
            )
            raise

        # Load extracted data
        extracted_data = {
            "history": self._load_history(output_dir / f"{browser}_history.json"),
            "cookies": self._load_cookies(output_dir / f"{browser}_cookies.json"),
            "downloads": self._load_downloads(output_dir / f"{browser}_downloads.json"),
            "localstorage": self._load_localstorage(output_dir / f"{browser}_localstorage.json")
        }

        # Filter to only marketplace domains
        extracted_data = self._filter_marketplace_data(extracted_data)

        logger.info(f"✓ Extracted {sum(len(v) for v in extracted_data.values())} total items")
        return extracted_data

    def _load_history(self, path: Path) -> List[Dict]:
        """Load and parse browsing history."""
        if not path.exists():
            logger.warning(f"History file not found: {path}")
            return []

        with open(path) as f:
            history = json.load(f)

        parsed = []
        for entry in history:
            parsed.append({
                "url": entry.get("url"),
                "title": entry.get("title"),
                "visit_count": entry.get("visit_count", 1),
                "last_visit_time": entry.get("last_visit_time"),
                "typed_count": entry.get("typed_count", 0)  # User typed URL vs clicked
            })

        return parsed

    def _load_cookies(self, path: Path) -> List[Dict]:
        """Load and parse cookies (including session cookies!)."""
        if not path.exists():
            logger.warning(f"Cookies file not found: {path}")
            return []

        with open(path) as f:
            cookies = json.load(f)

        parsed = []
        for cookie in cookies:
            parsed.append({
                "name": cookie.get("name"),
                "value": cookie.get("value"),  # DECRYPTED!
                "domain": cookie.get("domain"),
                "path": cookie.get("path"),
                "expires": cookie.get("expires"),
                "secure": cookie.get("secure", False),
                "httponly": cookie.get("httponly", False)
            })

        return parsed

    def _load_downloads(self, path: Path) -> List[Dict]:
        """Load download history."""
        if not path.exists():
            logger.warning(f"Downloads file not found: {path}")
            return []

        with open(path) as f:
            downloads = json.load(f)

        parsed = []
        for dl in downloads:
            parsed.append({
                "url": dl.get("url"),
                "target_path": dl.get("target_path"),
                "start_time": dl.get("start_time"),
                "end_time": dl.get("end_time"),
                "total_bytes": dl.get("total_bytes", 0)
            })

        return parsed

    def _load_localstorage(self, path: Path) -> List[Dict]:
        """Load LocalStorage data."""
        if not path.exists():
            logger.warning(f"LocalStorage file not found: {path}")
            return []

        with open(path) as f:
            storage = json.load(f)

        # LocalStorage is key-value pairs per domain
        parsed = []
        for item in storage:
            parsed.append({
                "origin": item.get("origin"),
                "key": item.get("key"),
                "value": item.get("value")
            })

        return parsed

    def _filter_marketplace_data(self, data: Dict) -> Dict:
        """Filter data to only marketplace domains."""
        filtered = {}

        # Filter history
        filtered["history"] = [
            item for item in data["history"]
            if any(domain in item["url"] for domain in self.MARKETPLACE_DOMAINS)
        ]

        # Filter cookies
        filtered["cookies"] = [
            item for item in data["cookies"]
            if any(domain in item["domain"] for domain in self.MARKETPLACE_DOMAINS)
        ]

        # Filter downloads
        filtered["downloads"] = [
            item for item in data["downloads"]
            if any(domain in item["url"] for domain in self.MARKETPLACE_DOMAINS)
        ]

        # Filter localStorage
        filtered["localstorage"] = [
            item for item in data["localstorage"]
            if any(domain in item["origin"] for domain in self.MARKETPLACE_DOMAINS)
        ]

        logger.info(f"Filtered to marketplace data:")
        logger.info(f"  History: {len(filtered['history'])} items")
        logger.info(f"  Cookies: {len(filtered['cookies'])} items")
        logger.info(f"  Downloads: {len(filtered['downloads'])} items")
        logger.info(f"  LocalStorage: {len(filtered['localstorage'])} items")

        return filtered

    def store(self, data: Dict):
        """Store extracted browser data in database."""
        from storage.postgres import PostgresStore
        from config import get_settings

        logger.info("Storing browser data...")
        cfg = get_settings()

        with PostgresStore() as db:
            with db._cursor() as cur:
                # 1. Store browsing history
                self._store_history(cur, data["history"])

                # 2. Extract and save session cookies
                self._save_session_cookies(data["cookies"], cfg)

                # 3. Store downloaded items (likely favorited)
                self._store_downloads(cur, data["downloads"])

                # 4. Parse and store LocalStorage preferences
                self._store_preferences(cur, data["localstorage"], cfg)

        logger.info("✓ Browser data stored")

    def _store_history(self, cur, history: List[Dict]):
        """Store browsing history as behavior signals."""
        for entry in history:
            # Extract item ID from URL if it's an item page
            item_id = self._extract_item_id_from_url(entry["url"])

            if item_id:
                # Store as "item_viewed" signal
                cur.execute("""
                    INSERT INTO behavior_signals (item_id, signal_type, signal_value, metadata, created_at)
                    SELECT id, 'item_viewed', %s, %s, %s
                    FROM items WHERE item_id = %s
                    ON CONFLICT DO NOTHING
                """, (
                    entry["visit_count"],
                    json.dumps({
                        "title": entry["title"],
                        "typed": entry["typed_count"] > 0  # Direct navigation = higher intent
                    }),
                    entry["last_visit_time"],
                    f"vinted_{item_id}"
                ))

        logger.info(f"  Stored {len(history)} history entries")

    def _save_session_cookies(self, cookies: List[Dict], cfg):
        """
        Save Vinted session cookie to .env file.

        This eliminates the need for manual cookie copying!
        """
        vinted_session_cookie = None

        for cookie in cookies:
            if cookie["name"] == "_vinted_fr_session" and "vinted" in cookie["domain"]:
                vinted_session_cookie = cookie["value"]
                break

        if vinted_session_cookie:
            # Update .env file
            env_file = Path(".env")

            if env_file.exists():
                with open(env_file, "r") as f:
                    lines = f.readlines()

                # Update or add cookie
                updated = False
                for i, line in enumerate(lines):
                    if line.startswith("VINTED_SESSION_COOKIE="):
                        lines[i] = f"VINTED_SESSION_COOKIE={vinted_session_cookie}\n"
                        updated = True
                        break

                if not updated:
                    lines.append(f"\nVINTED_SESSION_COOKIE={vinted_session_cookie}\n")

                with open(env_file, "w") as f:
                    f.writelines(lines)

                logger.info("  ✓ Vinted session cookie saved to .env")
            else:
                logger.warning("  .env file not found, cannot save cookie")

    def _store_downloads(self, cur, downloads: List[Dict]):
        """Store downloaded images (likely favorited items)."""
        for dl in downloads:
            # If user downloaded an item image, they're probably interested
            if any(ext in dl["target_path"].lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                item_id = self._extract_item_id_from_url(dl["url"])

                if item_id:
                    cur.execute("""
                        INSERT INTO behavior_signals (item_id, signal_type, signal_value, metadata, created_at)
                        SELECT id, 'image_saved', 1.0, %s, %s
                        FROM items WHERE item_id = %s
                        ON CONFLICT DO NOTHING
                    """, (
                        json.dumps({"path": dl["target_path"]}),
                        dl["end_time"],
                        f"vinted_{item_id}"
                    ))

        logger.info(f"  Stored {len(downloads)} download entries")

    def _store_preferences(self, cur, localstorage: List[Dict], cfg):
        """Parse and store preferences from LocalStorage."""
        preferences = {}

        for item in localstorage:
            key = item["key"]
            value = item["value"]

            # Extract useful preference data
            if "filter" in key.lower():
                preferences["filters"] = json.loads(value) if value else {}
            elif "search" in key.lower():
                preferences["searches"] = json.loads(value) if value else {}
            elif "favorite" in key.lower() or "wishlist" in key.lower():
                preferences["favorites"] = json.loads(value) if value else {}

        # Save to user profile file
        if preferences:
            profile_file = cfg.style_profile_file
            profile_file.parent.mkdir(parents=True, exist_ok=True)

            if profile_file.exists():
                with open(profile_file, "r") as f:
                    existing = json.load(f)
            else:
                existing = {}

            existing["browser_preferences"] = preferences
            existing["updated_at"] = datetime.now().isoformat()

            with open(profile_file, "w") as f:
                json.dump(existing, f, indent=2)

            logger.info("  ✓ Preferences saved to profile")

    def _extract_item_id_from_url(self, url: str) -> str:
        """Extract Vinted item ID from URL."""
        # Vinted URLs: https://www.vinted.co.uk/items/12345-item-title
        if "/items/" in url:
            parts = url.split("/items/")
            if len(parts) > 1:
                item_id = parts[1].split("-")[0]
                return item_id

        return None
