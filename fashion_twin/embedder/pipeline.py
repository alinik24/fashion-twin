"""Embedding pipeline — fetch un-embedded items from Postgres, encode, write to Qdrant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import get_settings
from storage import PostgresStore, QdrantStore

from .fashion_clip import FashionCLIPEmbedder, get_embedder

logger = logging.getLogger(__name__)

MODEL_VERSION = "fashion-clip-v1"


@dataclass
class PipelineStats:
    processed: int = 0
    skipped: int = 0
    failed: int = 0


def build_payload(item: dict) -> dict:
    """Extract lightweight Qdrant payload from a full Postgres item row."""
    return {
        "item_id": item["id"],
        "source": item.get("source", ""),
        "title": (item.get("title") or "")[:200],
        "brand": item.get("brand") or "",
        "price": item.get("price"),
        "currency": item.get("currency") or "",
        "size": item.get("size") or "",
        "condition": item.get("condition") or "",
        "listing_url": item.get("listing_url") or "",
        "image_url": item.get("image_url") or "",
    }


class EmbeddingPipeline:
    """Batch-embed unprocessed items and store vectors in Qdrant."""

    def __init__(
        self,
        db: Optional[PostgresStore] = None,
        vector_store: Optional[QdrantStore] = None,
        embedder: Optional[FashionCLIPEmbedder] = None,
    ) -> None:
        self._db = db
        self._vector_store = vector_store
        self._embedder = embedder or get_embedder()

    def _get_db(self) -> PostgresStore:
        if self._db:
            return self._db
        store = PostgresStore()
        store.connect()
        return store

    def _get_qdrant(self) -> QdrantStore:
        if self._vector_store:
            return self._vector_store
        store = QdrantStore()
        store.ensure_collection()
        return store

    def run(self, batch_size: int = 64, dry_run: bool = False) -> PipelineStats:
        """
        Fetch un-embedded items, encode them, write to Qdrant, mark in Postgres.

        Args:
            batch_size: how many items to embed per round
            dry_run: if True, encode but don't write to DB/Qdrant
        """
        db = self._get_db()
        qdrant = self._get_qdrant()
        stats = PipelineStats()

        items = db.get_items_without_embeddings(limit=batch_size)
        if not items:
            logger.info("No items to embed")
            return stats

        logger.info("Embedding %d items (model=%s)", len(items), MODEL_VERSION)

        # Prepare inputs
        titles = [item.get("title") or "" for item in items]
        image_urls = [item.get("image_url") for item in items]

        # Encode in batch
        try:
            text_vecs = self._embedder.encode_texts(titles)
        except Exception as exc:
            logger.error("Text encoding failed: %s", exc)
            text_vecs = None

        qdrant_records = []
        for i, item in enumerate(items):
            try:
                # Fuse image + text
                vec = self._embedder.encode_item(
                    title=item.get("title"),
                    image=image_urls[i],
                )
                payload = build_payload(item)
                qdrant_records.append({
                    "item_id": item["id"],
                    "vector": vec.tolist(),
                    "payload": payload,
                })
                stats.processed += 1
            except Exception as exc:
                logger.warning("Failed to embed item %s: %s", item.get("id"), exc)
                stats.failed += 1

        if dry_run:
            logger.info("[dry_run] Would upsert %d vectors", len(qdrant_records))
            return stats

        if qdrant_records:
            qdrant_ids = qdrant.upsert_batch(qdrant_records)
            for rec, qid in zip(qdrant_records, qdrant_ids):
                db.mark_embedded(rec["item_id"], qid, MODEL_VERSION)

        logger.info(
            "Embedding pipeline done — processed=%d, failed=%d",
            stats.processed,
            stats.failed,
        )
        return stats

    def embed_query(self, text: str) -> list[float]:
        """Encode a free-text query for use in ANN search."""
        vec = self._embedder.encode_text(text)
        return vec.tolist()

    def embed_image_url(self, image_url: str) -> list[float]:
        """Encode an image URL for visual similarity search."""
        vec = self._embedder.encode_image(image_url)
        return vec.tolist()
