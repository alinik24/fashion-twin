"""Tracking session manager — captures behavioral signals during an active session.

A session is a user-gated window where all interactions are recorded.
The user starts a session (`tracker start`), browses, and stops it.
Signals can arrive via:
  1. Direct Python API (this module)
  2. HTTP API endpoint (api/tracker_api.py) — for browser extension / mobile
  3. Manual CLI logging (scripts/track_session.py)

All signals are stored in behavior_signals + influence the bandit and RLHF loop.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_settings
from .consent import ConsentManager
from .signals import Signal, compute_reward

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    session_id: str
    domain: str
    started_at: str
    user_id: int = 1
    signal_count: int = 0
    active: bool = True
    metadata: dict = field(default_factory=dict)


class TrackingSession:
    """
    Manages one tracking session lifecycle: start → log signals → stop.

    Session state is written to a local JSON file so it survives process restarts.
    Signals are flushed to PostgreSQL in batches or on stop.
    """

    def __init__(
        self,
        session_file: Optional[Path] = None,
        consent: Optional[ConsentManager] = None,
    ) -> None:
        cfg = get_settings()
        self._file = session_file or cfg.tracker_session_file
        self._consent = consent or ConsentManager()
        self._state: Optional[SessionState] = None
        self._buffer: list[Signal] = []
        self._flush_every: int = 20   # flush to DB every N signals
        self._load()

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def start(self, domain: str = "fashion", metadata: Optional[dict] = None) -> str:
        """Start a new tracking session. Returns session_id."""
        if not self._consent.is_allowed(domain):
            raise PermissionError(
                f"Tracking not consented for domain '{domain}'. "
                f"Run: python scripts/track_session.py consent enable {domain}"
            )

        sid = str(uuid.uuid4())
        self._state = SessionState(
            session_id=sid,
            domain=domain,
            started_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        self._save()
        self._persist_session_start()
        logger.info("Tracking session started: %s (domain=%s)", sid[:8], domain)
        return sid

    def stop(self) -> Optional[str]:
        """Stop the active session, flush remaining signals."""
        if not self._state or not self._state.active:
            return None
        self.flush()
        sid = self._state.session_id
        self._state.active = False
        self._save()
        self._persist_session_end()
        logger.info(
            "Tracking session stopped: %s (%d signals)",
            sid[:8],
            self._state.signal_count,
        )
        return sid

    @property
    def active(self) -> bool:
        return self._state is not None and self._state.active

    @property
    def session_id(self) -> Optional[str]:
        return self._state.session_id if self._state else None

    @property
    def domain(self) -> str:
        return self._state.domain if self._state else "fashion"

    # ── Signal recording ──────────────────────────────────────────────────────

    def log(
        self,
        signal_type: str,
        item_id: Optional[int] = None,
        value: Optional[float] = None,
        context: Optional[dict] = None,
        domain: Optional[str] = None,
    ) -> Signal:
        """
        Record a behavioral signal.

        Args:
            signal_type: one of SignalType values
            item_id:     DB item id (None for general activity)
            value:       numeric payload (dwell seconds, offer amount, …)
            context:     arbitrary dict (query, rank, source_url, …)
            domain:      override session domain for this signal
        """
        sig_domain = domain or self.domain
        if not self._consent.is_allowed(sig_domain):
            logger.debug("Signal ignored (no consent for %s)", sig_domain)
            return Signal(signal_type=signal_type, domain=sig_domain)  # no-op

        sig = Signal(
            signal_type=signal_type,
            domain=sig_domain,
            item_id=item_id,
            value=value,
            context=context or {},
            session_id=self.session_id,
            user_id=self._state.user_id if self._state else 1,
        )

        self._buffer.append(sig)
        if self._state:
            self._state.signal_count += 1
            self._save()

        if len(self._buffer) >= self._flush_every:
            self.flush()

        return sig

    def dwell(self, item_id: int, seconds: float, context: Optional[dict] = None) -> Signal:
        return self.log("dwell", item_id=item_id, value=seconds, context=context)

    def click(self, item_id: int, context: Optional[dict] = None) -> Signal:
        return self.log("click", item_id=item_id, context=context)

    def offer(self, item_id: int, amount: float, context: Optional[dict] = None) -> Signal:
        return self.log("offer", item_id=item_id, value=amount, context=context)

    def contact(self, item_id: int, context: Optional[dict] = None) -> Signal:
        return self.log("contact", item_id=item_id, context=context)

    def favorite(self, item_id: int, context: Optional[dict] = None) -> Signal:
        return self.log("favorite", item_id=item_id, context=context)

    def scroll_past(self, item_id: int, context: Optional[dict] = None) -> Signal:
        return self.log("scroll_past", item_id=item_id, context=context)

    # ── General activity (any domain) ─────────────────────────────────────────

    def log_activity(
        self,
        activity_type: str,
        domain: str,
        payload: Optional[dict] = None,
        source_url: Optional[str] = None,
    ) -> None:
        """Log a general (non-item) activity for any domain."""
        if not self._consent.is_allowed(domain):
            return
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    import json as _json
                    cur.execute(
                        """INSERT INTO activity_log
                               (session_id, domain, activity_type, payload, source_url, consent_granted)
                           VALUES (%s, %s, %s, %s, %s, TRUE)""",
                        (
                            self.session_id,
                            domain,
                            activity_type,
                            _json.dumps(payload or {}),
                            source_url,
                        ),
                    )
        except Exception as exc:
            logger.debug("Activity log DB write failed: %s", exc)

    # ── Flush ─────────────────────────────────────────────────────────────────

    def flush(self) -> int:
        """Write buffered signals to PostgreSQL. Returns count written."""
        if not self._buffer:
            return 0
        batch = list(self._buffer)
        self._buffer.clear()
        self._write_signals(batch)
        return len(batch)

    def _write_signals(self, signals: list[Signal]) -> None:
        try:
            from storage import PostgresStore
            import json as _json
            with PostgresStore() as db:
                with db._cursor() as cur:
                    for sig in signals:
                        cur.execute(
                            """INSERT INTO behavior_signals
                                   (session_id, user_id, item_id, signal_type, value,
                                    domain, context, consent_granted)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)""",
                            (
                                sig.session_id,
                                sig.user_id,
                                sig.item_id,
                                sig.signal_type,
                                sig.value,
                                sig.domain,
                                _json.dumps(sig.context),
                            ),
                        )
            logger.debug("Flushed %d signals to DB", len(signals))
        except Exception as exc:
            logger.warning("Signal flush failed: %s — signals buffered in memory", exc)
            self._buffer.extend(signals)   # re-buffer on failure

    # ── Persistence (session state file) ──────────────────────────────────────

    def _save(self) -> None:
        if not self._state:
            return
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(asdict(self._state), indent=2))

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                self._state = SessionState(**data)
            except Exception:
                self._state = None

    def _persist_session_start(self) -> None:
        if not self._state:
            return
        try:
            from storage import PostgresStore
            import json as _json
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO tracker_sessions (id, user_id, domain, metadata)
                           VALUES (%s::uuid, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (
                            self._state.session_id,
                            self._state.user_id,
                            self._state.domain,
                            _json.dumps(self._state.metadata),
                        ),
                    )
        except Exception as exc:
            logger.debug("Session persist start failed: %s", exc)

    def _persist_session_end(self) -> None:
        if not self._state:
            return
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """UPDATE tracker_sessions
                           SET ended_at = NOW(), signal_count = %s
                           WHERE id = %s::uuid""",
                        (self._state.signal_count, self._state.session_id),
                    )
        except Exception as exc:
            logger.debug("Session persist end failed: %s", exc)
