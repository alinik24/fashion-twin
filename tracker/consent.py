"""Consent management — user decides which domains/sessions are tracked.

Consent is stored in a local JSON file (fast, no DB needed for reads) and
also persisted to the consent_log table for audit trail.

Domains:  fashion | food | travel | tech | fitness | reading | shopping | all
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)

_ALL_DOMAINS = {"fashion", "food", "travel", "tech", "fitness", "reading", "shopping"}


class ConsentManager:
    """Read/write per-domain tracking consent."""

    def __init__(self, consent_file: Optional[Path] = None) -> None:
        cfg = get_settings()
        self._file = consent_file or cfg.tracker_consent_file
        self._state: dict[str, bool] = {}
        self._load()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._file.exists():
            try:
                self._state = json.loads(self._file.read_text())
            except Exception:
                self._state = {}
        else:
            # Seed from settings
            cfg = get_settings()
            for domain in cfg.enabled_domains_list:
                self._state[domain] = True

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._state, indent=2))

    # ── Public API ────────────────────────────────────────────────────────────

    def is_allowed(self, domain: str) -> bool:
        """Return True if tracking is enabled for this domain."""
        if self._state.get("all"):
            return True
        return self._state.get(domain, False)

    def enable(self, domain: str, reason: str = "") -> None:
        """Enable tracking for a domain."""
        self._state[domain] = True
        self._save()
        self._log_change(domain, True, reason)
        logger.info("Tracking ENABLED for domain: %s", domain)

    def disable(self, domain: str, reason: str = "") -> None:
        """Disable tracking for a domain."""
        self._state[domain] = False
        self._save()
        self._log_change(domain, False, reason)
        logger.info("Tracking DISABLED for domain: %s", domain)

    def enable_all(self) -> None:
        self._state = {"all": True}
        self._save()

    def disable_all(self) -> None:
        self._state = {}
        self._save()

    def status(self) -> dict[str, bool]:
        return dict(self._state)

    def _log_change(self, domain: str, enabled: bool, reason: str) -> None:
        """Persist consent change to DB (best-effort)."""
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO consent_log (domain, enabled, reason)
                           VALUES (%s, %s, %s)""",
                        (domain, enabled, reason),
                    )
        except Exception as exc:
            logger.debug("Consent DB log failed (non-fatal): %s", exc)
