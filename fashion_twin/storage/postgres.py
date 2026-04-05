"""PostgreSQL persistence layer — items, interactions, model snapshots."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PGConnection

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ItemRecord:
    external_id: str
    source: str
    listing_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    size: Optional[str] = None
    condition: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    image_url: Optional[str] = None
    catalog_id: Optional[int] = None
    color1: Optional[str] = None
    raw_data: dict = field(default_factory=dict)
    # set after insert
    id: Optional[int] = None


@dataclass
class InteractionRecord:
    item_id: int
    interaction_type: str          # like | dislike | view | skip | purchase
    user_id: int = 1
    strength: float = 1.0
    context: dict = field(default_factory=dict)


class PostgresStore:
    """Thin wrapper around psycopg2 for all Fashion Twin DB operations."""

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or get_settings().postgres_dsn
        self._conn: Optional[PGConnection] = None

    # ── Connection management ─────────────────────────────────────────────────

    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
            self._conn.autocommit = False
            logger.info("Connected to PostgreSQL")

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("PostgreSQL connection closed")

    def __enter__(self) -> "PostgresStore":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextmanager
    def _cursor(self) -> Generator[psycopg2.extras.DictCursor, None, None]:
        self.connect()
        assert self._conn is not None
        with self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ── Schema ────────────────────────────────────────────────────────────────

    def init_schema(self, schema_path: Optional[Path] = None) -> None:
        """Create tables from schema.sql (idempotent — uses IF NOT EXISTS)."""
        if schema_path is None:
            schema_path = Path(__file__).parent / "schema.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self._cursor() as cur:
            cur.execute(sql)
        logger.info("Schema initialised")

    # ── Items ─────────────────────────────────────────────────────────────────

    def upsert_item(self, item: ItemRecord) -> int:
        """Insert or update an item. Returns the DB id."""
        sql = """
            INSERT INTO items
                (external_id, source, title, description, brand, size, condition,
                 price, currency, image_url, listing_url, catalog_id, color1, raw_data)
            VALUES
                (%(external_id)s, %(source)s, %(title)s, %(description)s, %(brand)s,
                 %(size)s, %(condition)s, %(price)s, %(currency)s, %(image_url)s,
                 %(listing_url)s, %(catalog_id)s, %(color1)s, %(raw_data)s)
            ON CONFLICT (source, external_id) DO UPDATE SET
                title        = EXCLUDED.title,
                price        = EXCLUDED.price,
                image_url    = EXCLUDED.image_url,
                raw_data     = EXCLUDED.raw_data,
                scraped_at   = NOW()
            RETURNING id
        """
        params = {
            **item.__dict__,
            "raw_data": json.dumps(item.raw_data),
        }
        params.pop("id", None)
        with self._cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            item_id = row["id"]
        item.id = item_id
        return item_id

    def upsert_items(self, items: list[ItemRecord]) -> list[int]:
        """Batch upsert. Returns list of DB ids in same order."""
        return [self.upsert_item(it) for it in items]

    def get_item(self, item_id: int) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def get_items_without_embeddings(self, limit: int = 500) -> list[dict]:
        """Return items that have not been embedded yet."""
        sql = """
            SELECT i.* FROM items i
            LEFT JOIN item_embeddings e ON e.item_id = i.id
            WHERE e.item_id IS NULL
            ORDER BY i.scraped_at DESC
            LIMIT %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def mark_embedded(self, item_id: int, qdrant_id: str, model_version: str) -> None:
        sql = """
            INSERT INTO item_embeddings (item_id, model_version, qdrant_id)
            VALUES (%s, %s, %s::uuid)
            ON CONFLICT (item_id, model_version) DO UPDATE SET
                qdrant_id  = EXCLUDED.qdrant_id,
                created_at = NOW()
        """
        with self._cursor() as cur:
            cur.execute(sql, (item_id, model_version, qdrant_id))
        with self._cursor() as cur:
            cur.execute(
                "UPDATE items SET embedded_at = NOW() WHERE id = %s", (item_id,)
            )

    # ── Interactions ─────────────────────────────────────────────────────────

    def log_interaction(self, rec: InteractionRecord) -> int:
        sql = """
            INSERT INTO interactions (user_id, item_id, interaction_type, strength, context)
            VALUES (%(user_id)s, %(item_id)s, %(interaction_type)s, %(strength)s, %(context)s)
            RETURNING id
        """
        params = {**rec.__dict__, "context": json.dumps(rec.context)}
        with self._cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return row["id"]

    def get_interactions(
        self,
        user_id: int = 1,
        interaction_types: Optional[list[str]] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM interactions WHERE user_id = %s"
        args: list[Any] = [user_id]
        if interaction_types:
            sql += " AND interaction_type = ANY(%s)"
            args.append(interaction_types)
        sql += " ORDER BY created_at DESC"
        with self._cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_interaction_matrix(self, user_id: int = 1) -> list[dict]:
        """Return (item_id, interaction_type, strength) for LightFM training."""
        sql = """
            SELECT item_id,
                   interaction_type,
                   SUM(strength) AS total_strength
            FROM interactions
            WHERE user_id = %s
            GROUP BY item_id, interaction_type
            ORDER BY item_id
        """
        with self._cursor() as cur:
            cur.execute(sql, (user_id,))
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ── Model snapshots ───────────────────────────────────────────────────────

    def save_model_snapshot(
        self,
        model_type: str,
        model_path: str,
        metrics: Optional[dict] = None,
        model_version: Optional[str] = None,
    ) -> int:
        sql = """
            INSERT INTO model_snapshots (model_type, model_version, model_path, metrics)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """
        with self._cursor() as cur:
            cur.execute(
                sql,
                (model_type, model_version, model_path, json.dumps(metrics or {})),
            )
            row = cur.fetchone()
        return row["id"]

    def get_latest_snapshot(self, model_type: str) -> Optional[dict]:
        sql = """
            SELECT * FROM model_snapshots
            WHERE model_type = %s
            ORDER BY trained_at DESC
            LIMIT 1
        """
        with self._cursor() as cur:
            cur.execute(sql, (model_type,))
            row = cur.fetchone()
        return dict(row) if row else None

    # ── Scrape jobs ───────────────────────────────────────────────────────────

    def start_scrape_job(self, source: str, query: str, pages: int) -> int:
        sql = """
            INSERT INTO scrape_jobs (source, query, pages_requested)
            VALUES (%s, %s, %s)
            RETURNING id
        """
        with self._cursor() as cur:
            cur.execute(sql, (source, query, pages))
            row = cur.fetchone()
        return row["id"]

    def finish_scrape_job(
        self,
        job_id: int,
        items_found: int,
        items_new: int,
        error: Optional[str] = None,
    ) -> None:
        sql = """
            UPDATE scrape_jobs
            SET items_found = %s,
                items_new   = %s,
                finished_at = NOW(),
                error       = %s
            WHERE id = %s
        """
        with self._cursor() as cur:
            cur.execute(sql, (items_found, items_new, error, job_id))

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        queries = {
            "total_items": "SELECT COUNT(*) FROM items",
            "embedded_items": "SELECT COUNT(*) FROM items WHERE embedded_at IS NOT NULL",
            "total_interactions": "SELECT COUNT(*) FROM interactions",
            "likes": "SELECT COUNT(*) FROM interactions WHERE interaction_type = 'like'",
            "dislikes": "SELECT COUNT(*) FROM interactions WHERE interaction_type = 'dislike'",
        }
        result = {}
        with self._cursor() as cur:
            for key, sql in queries.items():
                cur.execute(sql)
                result[key] = cur.fetchone()[0]
        return result
