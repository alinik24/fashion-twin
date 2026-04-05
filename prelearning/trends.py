"""Trend ingestion — scrape and store current fashion trends.

Sources:
  1. Vogue.co.uk / Vogue.com — editorial trend articles (RSS + DOM)
  2. Lyst Year in Fashion — structured trend data (public API)
  3. Pinterest Trends — RSS feed for fashion searches
  4. Vinted trending searches — internal API patterns

The scraped trends are stored in the `trends` table and summarised
by GPT-5.1 for injection into the reward model prompt.

Reference:
  Li et al. (2017) "NEMO: Next Career Move Prediction with Contextual Text"
  — cross-domain trend modelling from textual signals
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from config import get_settings
from .season import get_current_season, get_season_year_code

logger = logging.getLogger(__name__)

VOGUE_RSS = "https://www.vogue.co.uk/rss"
VOGUE_FASHION_RSS = "https://www.vogue.co.uk/fashion/rss"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


@dataclass
class TrendItem:
    source: str
    category: str
    trend_text: str
    keywords: list[str]
    season: str
    relevance_score: float = 1.0


class TrendScraper:
    """Scrapes trend data from multiple sources."""

    def __init__(self) -> None:
        self._season = get_season_year_code()

    def scrape_all(self) -> list[TrendItem]:
        trends: list[TrendItem] = []
        trends.extend(self._scrape_vogue())
        trends.extend(self._scrape_lyst())
        trends.extend(self._scrape_vinted_trending())
        return trends

    # ── Vogue RSS ─────────────────────────────────────────────────────────────

    def _scrape_vogue(self) -> list[TrendItem]:
        """Parse Vogue fashion RSS feed for trend keywords."""
        items: list[TrendItem] = []
        try:
            resp = httpx.get(VOGUE_FASHION_RSS, headers=HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            content = resp.text

            # Parse RSS titles and descriptions
            titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", content)
            if not titles:
                titles = re.findall(r"<title>(.*?)</title>", content)
            descriptions = re.findall(r"<description><!\[CDATA\[(.*?)\]\]></description>", content)

            fashion_keywords = self._extract_fashion_keywords(
                " ".join(titles[:20] + descriptions[:10])
            )

            for title in titles[:15]:
                keywords = self._extract_fashion_keywords(title)
                if keywords:
                    items.append(TrendItem(
                        source="vogue",
                        category="editorial",
                        trend_text=title.strip(),
                        keywords=keywords,
                        season=self._season,
                        relevance_score=0.9,
                    ))

        except Exception as exc:
            logger.debug("Vogue scrape failed: %s", exc)

        return items

    # ── Lyst Index ────────────────────────────────────────────────────────────

    def _scrape_lyst(self) -> list[TrendItem]:
        """
        Lyst publishes quarterly trend indexes.
        We scrape the public Lyst trending page for current hot items.
        """
        items: list[TrendItem] = []
        try:
            resp = httpx.get(
                "https://www.lyst.com/data/most-wanted/",
                headers={**HEADERS, "Accept": "application/json"},
                timeout=15,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    products = data.get("products", []) or data.get("data", [])
                    for p in products[:20]:
                        name = p.get("name", "") or p.get("product_name", "")
                        brand = p.get("brand", "") or p.get("designer", "")
                        if name:
                            items.append(TrendItem(
                                source="lyst",
                                category="most_wanted",
                                trend_text=f"{brand} {name}".strip(),
                                keywords=self._extract_fashion_keywords(f"{brand} {name}"),
                                season=self._season,
                                relevance_score=0.95,
                            ))
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Lyst scrape failed: %s", exc)

        return items

    # ── Vinted trending searches ──────────────────────────────────────────────

    def _scrape_vinted_trending(self) -> list[TrendItem]:
        """
        Vinted exposes suggested searches which reflect trending terms.
        """
        items: list[TrendItem] = []
        try:
            cfg = get_settings()
            resp = httpx.get(
                f"{cfg.vinted_base_url}/api/v2/catalog/search_suggestions",
                headers={**HEADERS, "Accept": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                suggestions = data.get("suggestions", []) or []
                for s in suggestions[:20]:
                    query = s.get("query", "") or s.get("text", "")
                    if query:
                        items.append(TrendItem(
                            source="vinted_trending",
                            category="search_trend",
                            trend_text=query,
                            keywords=query.lower().split(),
                            season=self._season,
                            relevance_score=0.85,
                        ))
        except Exception as exc:
            logger.debug("Vinted trending failed: %s", exc)

        return items

    # ── Helpers ───────────────────────────────────────────────────────────────

    FASHION_VOCAB = {
        "blazer", "coat", "jacket", "dress", "skirt", "blouse", "top",
        "trousers", "jeans", "shirt", "cardigan", "jumper", "knit", "sweater",
        "boots", "sandals", "heels", "sneakers", "bag", "handbag", "belt",
        "linen", "silk", "cashmere", "leather", "denim", "velvet", "satin",
        "vintage", "y2k", "minimalist", "quiet luxury", "coastal grandmother",
        "mob wife", "ballet core", "old money", "dopamine dressing",
        "zara", "sandro", "maje", "jacquemus", "toteme", "arket",
    }

    def _extract_fashion_keywords(self, text: str) -> list[str]:
        words = set(re.findall(r"\b\w+\b", text.lower()))
        return list(words & self.FASHION_VOCAB)


class TrendManager:
    """Stores and retrieves trends from PostgreSQL."""

    def __init__(self) -> None:
        self._cfg = get_settings()

    def refresh(self, force: bool = False) -> int:
        """Scrape fresh trends if stale. Returns number of new trends stored."""
        if not force:
            threshold = datetime.now(timezone.utc) - timedelta(
                hours=self._cfg.trend_refresh_hours
            )
            last = self._get_latest_scrape()
            if last and last > threshold:
                logger.debug("Trends fresh (last scraped %s)", last.isoformat())
                return 0

        scraper = TrendScraper()
        trends = scraper.scrape_all()
        count = self._store(trends)
        logger.info("Stored %d new trends", count)
        return count

    def get_summary(self, limit: int = 20) -> str:
        """Return a short trend summary string for LLM prompt injection."""
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                db.connect()
                with db._cursor() as cur:
                    cur.execute(
                        """SELECT trend_text, source, relevance_score
                           FROM trends
                           ORDER BY scraped_at DESC, relevance_score DESC
                           LIMIT %s""",
                        (limit,),
                    )
                    rows = cur.fetchall()
            if not rows:
                return f"No trend data available. Current season: {get_season_year_code()}"
            lines = [f"- {r['trend_text']} (source: {r['source']})" for r in rows]
            return f"Current fashion trends ({get_season_year_code()}):\n" + "\n".join(lines)
        except Exception as exc:
            logger.debug("Trend summary failed: %s", exc)
            return f"Trends unavailable. Season: {get_season_year_code()}"

    def get_keywords(self) -> list[str]:
        """Return flat list of all current trend keywords."""
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                db.connect()
                with db._cursor() as cur:
                    cur.execute(
                        "SELECT UNNEST(keywords) as kw FROM trends ORDER BY scraped_at DESC LIMIT 200"
                    )
                    return list({r["kw"] for r in cur.fetchall()})
        except Exception:
            return []

    def _store(self, trends: list[TrendItem]) -> int:
        try:
            from storage import PostgresStore
            from psycopg2.extras import execute_values
            with PostgresStore() as db:
                db.connect()
                rows = [
                    (
                        t.source, t.category, t.trend_text,
                        t.keywords, t.season, t.relevance_score,
                    )
                    for t in trends
                ]
                with db._cursor() as cur:
                    execute_values(
                        cur,
                        """INSERT INTO trends
                               (source, category, trend_text, keywords, season, relevance_score)
                           VALUES %s""",
                        rows,
                    )
            return len(trends)
        except Exception as exc:
            logger.warning("Trend store failed: %s", exc)
            return 0

    def _get_latest_scrape(self) -> Optional[datetime]:
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                db.connect()
                with db._cursor() as cur:
                    cur.execute("SELECT MAX(scraped_at) as ts FROM trends")
                    row = cur.fetchone()
                    return row["ts"] if row and row["ts"] else None
        except Exception:
            return None
