"""Qdrant vector store — upsert embeddings, ANN search, filter by payload."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import get_settings

logger = logging.getLogger(__name__)

VECTOR_NAME = "fashion_clip"


@dataclass
class SearchResult:
    qdrant_id: str
    item_id: int
    score: float
    payload: dict


class QdrantStore:
    """Manages the Qdrant collection for fashion item vectors."""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection: Optional[str] = None,
        dim: Optional[int] = None,
    ) -> None:
        cfg = get_settings()
        self._url = url or cfg.qdrant_url
        self._api_key = api_key or cfg.qdrant_api_key or None
        self.collection = collection or cfg.qdrant_collection
        self._dim = dim or cfg.embedding_dim
        self._client: Optional[QdrantClient] = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        kwargs: dict[str, Any] = {"url": self._url}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        self._client = QdrantClient(**kwargs)
        logger.info("Connected to Qdrant at %s", self._url)

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    # ── Collection lifecycle ──────────────────────────────────────────────────

    def ensure_collection(self) -> None:
        """Create collection if it does not exist."""
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection '%s' dim=%d", self.collection, self._dim)
        else:
            logger.debug("Collection '%s' already exists", self.collection)

    def drop_collection(self) -> None:
        self.client.delete_collection(self.collection)
        logger.warning("Dropped collection '%s'", self.collection)

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert(
        self,
        item_id: int,
        vector: list[float],
        payload: Optional[dict] = None,
        qdrant_id: Optional[str] = None,
    ) -> str:
        """Upsert a single vector. Returns the qdrant_id used."""
        qid = qdrant_id or str(uuid.uuid4())
        point = PointStruct(
            id=qid,
            vector=vector,
            payload={"item_id": item_id, **(payload or {})},
        )
        self.client.upsert(collection_name=self.collection, points=[point])
        return qid

    def upsert_batch(
        self,
        records: list[dict],
    ) -> list[str]:
        """
        Batch upsert. Each dict must have:
          - item_id: int
          - vector: list[float]
          - payload: dict (optional)
          - qdrant_id: str (optional)
        Returns list of qdrant_ids.
        """
        points = []
        ids = []
        for rec in records:
            qid = rec.get("qdrant_id") or str(uuid.uuid4())
            ids.append(qid)
            points.append(
                PointStruct(
                    id=qid,
                    vector=rec["vector"],
                    payload={"item_id": rec["item_id"], **rec.get("payload", {})},
                )
            )
        self.client.upsert(collection_name=self.collection, points=points)
        logger.debug("Upserted %d vectors", len(points))
        return ids

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        top_k: int = 50,
        source_filter: Optional[str] = None,
        exclude_item_ids: Optional[list[int]] = None,
    ) -> list[SearchResult]:
        """ANN search with optional source and exclusion filters."""
        must_conditions = []

        if source_filter:
            must_conditions.append(
                FieldCondition(key="source", match=MatchValue(value=source_filter))
            )

        if exclude_item_ids:
            # Qdrant doesn't have a NOT IN natively, so we fetch more and filter
            top_k_fetch = top_k + len(exclude_item_ids)
        else:
            top_k_fetch = top_k

        flt = Filter(must=must_conditions) if must_conditions else None

        hits = self.client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            limit=top_k_fetch,
            query_filter=flt,
            with_payload=True,
        )

        results = []
        for hit in hits:
            payload = hit.payload or {}
            iid = payload.get("item_id", -1)
            if exclude_item_ids and iid in exclude_item_ids:
                continue
            results.append(
                SearchResult(
                    qdrant_id=str(hit.id),
                    item_id=iid,
                    score=hit.score,
                    payload=payload,
                )
            )
            if len(results) >= top_k:
                break

        return results

    def search_by_item_id(self, item_id: int, top_k: int = 20) -> list[SearchResult]:
        """Find items similar to a given item_id (look up its vector first)."""
        hits = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="item_id", match=MatchValue(value=item_id))]
            ),
            limit=1,
            with_vectors=True,
        )
        points, _ = hits
        if not points:
            return []
        vec = points[0].vector
        return self.search(query_vector=vec, top_k=top_k + 1, exclude_item_ids=[item_id])

    # ── Stats ─────────────────────────────────────────────────────────────────

    def count(self) -> int:
        info = self.client.get_collection(self.collection)
        return info.points_count or 0

    def collection_info(self) -> dict:
        info = self.client.get_collection(self.collection)
        return {
            "name": self.collection,
            "points": info.points_count,
            "status": str(info.status),
        }
