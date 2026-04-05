"""Abstract base collector + shared normalisation helpers."""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from config import get_settings
from storage import ItemRecord

logger = logging.getLogger(__name__)


@dataclass
class CollectResult:
    items: list[ItemRecord]
    source: str
    query: str
    pages_scraped: int
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)


class BaseCollector(ABC):
    source: str = "unknown"

    def __init__(self) -> None:
        self._cfg = get_settings()

    @abstractmethod
    async def collect(
        self,
        query: str,
        pages: int = 3,
        **kwargs,
    ) -> CollectResult:
        """Scrape `pages` pages for `query`. Returns CollectResult."""

    async def _delay(self) -> None:
        secs = random.uniform(self._cfg.scrape_delay_min, self._cfg.scrape_delay_max)
        await asyncio.sleep(secs)

    # ── Shared normalisation helpers ──────────────────────────────────────────

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            if isinstance(value, dict):
                return float(value.get("amount", 0))
            return float(str(value).replace(",", "").replace("£", "").strip())
        except (ValueError, TypeError):
            return None
