"""LightFM hybrid collaborative filter.

Uses WARP loss (good for implicit feedback) with item features derived from
Qdrant embeddings and item metadata (brand, source, condition).

Reference: Kula, M. (2015) "Metadata embeddings for user and item cold-start
           recommendations", CBRecSys@RecSys 2015.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.sparse as sp
from lightfm import LightFM
from lightfm.data import Dataset

from config import get_settings

logger = logging.getLogger(__name__)

# Map interaction types to implicit feedback weights
INTERACTION_WEIGHTS = {
    "purchase": 5.0,
    "like": 3.0,
    "view": 1.0,
    "skip": 0.2,
    "dislike": -1.0,   # treat as negative by zeroing out
}


class FashionRanker:
    """LightFM-based ranker that scores items for a single user (you)."""

    def __init__(self) -> None:
        self._cfg = get_settings()
        self._dataset: Optional[Dataset] = None
        self._model: Optional[LightFM] = None
        self._item_id_map: dict[int, int] = {}   # db_item_id → lightfm_item_idx
        self._item_idx_map: dict[int, int] = {}  # lightfm_item_idx → db_item_id
        self._user_id = 0                         # always user 0 internally

    # ── Build / train ─────────────────────────────────────────────────────────

    def build_dataset(
        self,
        interactions: list[dict],
        item_features: Optional[list[dict]] = None,
    ) -> None:
        """
        Fit the Dataset on known items and interactions.

        Args:
            interactions: list of dicts with keys item_id, interaction_type, total_strength
            item_features: optional list of dicts with item_id + feature tags
        """
        self._dataset = Dataset()

        db_item_ids = list({r["item_id"] for r in interactions})
        self._item_id_map = {db_id: idx for idx, db_id in enumerate(db_item_ids)}
        self._item_idx_map = {idx: db_id for db_id, idx in self._item_id_map.items()}

        feature_tags: list[str] = []
        if item_features:
            for feat in item_features:
                feature_tags.extend(feat.get("tags", []))
            feature_tags = list(set(feature_tags))

        self._dataset.fit(
            users=[0],  # single user
            items=db_item_ids,
            item_features=feature_tags or None,
        )
        logger.info(
            "Dataset built: %d items, %d feature tags",
            len(db_item_ids),
            len(feature_tags),
        )

    def build_interactions_matrix(
        self, interactions: list[dict]
    ) -> tuple[sp.coo_matrix, sp.coo_matrix]:
        """Build LightFM interaction + weight matrices from interaction records."""
        assert self._dataset is not None, "Call build_dataset first"

        rows: list[tuple[int, int, float]] = []
        for rec in interactions:
            itype = rec["interaction_type"]
            weight = INTERACTION_WEIGHTS.get(itype, 1.0)
            if weight <= 0:
                continue   # skip negatives — LightFM WARP doesn't use explicit negatives
            strength = float(rec.get("total_strength", 1.0)) * weight
            rows.append((0, rec["item_id"], strength))

        if not rows:
            raise ValueError("No positive interactions found for training")

        interactions_mat, weights_mat = self._dataset.build_interactions(
            [(u, i, w) for u, i, w in rows]
        )
        logger.info("Interaction matrix: %s", interactions_mat.shape)
        return interactions_mat, weights_mat

    def build_item_features(self, item_features: list[dict]) -> sp.csr_matrix:
        """
        Build item feature matrix.

        Each dict: {"item_id": int, "tags": ["brand:zara", "condition:new", ...]}
        """
        assert self._dataset is not None
        return self._dataset.build_item_features(
            [(feat["item_id"], feat["tags"]) for feat in item_features]
        )

    def train(
        self,
        interactions_mat: sp.coo_matrix,
        weights_mat: sp.coo_matrix,
        item_features: Optional[sp.csr_matrix] = None,
        epochs: Optional[int] = None,
        num_threads: Optional[int] = None,
    ) -> None:
        """Fit the LightFM model."""
        cfg = self._cfg
        self._model = LightFM(loss="warp", no_components=128, learning_rate=0.05)
        self._model.fit(
            interactions=interactions_mat,
            sample_weight=weights_mat,
            item_features=item_features,
            epochs=epochs or cfg.lightfm_epochs,
            num_threads=num_threads or cfg.lightfm_num_threads,
            verbose=True,
        )
        logger.info("LightFM training complete")

    # ── Scoring ───────────────────────────────────────────────────────────────

    def score_items(
        self,
        candidate_db_ids: list[int],
        item_features: Optional[sp.csr_matrix] = None,
    ) -> list[tuple[int, float]]:
        """
        Score a list of item DB IDs for user 0.

        Returns list of (db_item_id, score) sorted descending.
        """
        assert self._model is not None, "Model not trained yet"
        assert self._dataset is not None

        # Map to LightFM indices; items not seen during training get score 0
        known = [(db_id, self._item_id_map[db_id]) for db_id in candidate_db_ids
                 if db_id in self._item_id_map]
        unknown = [(db_id, None) for db_id in candidate_db_ids
                   if db_id not in self._item_id_map]

        if not known:
            return [(db_id, 0.0) for db_id in candidate_db_ids]

        item_indices = np.array([idx for _, idx in known])
        scores = self._model.predict(
            user_ids=0,
            item_ids=item_indices,
            item_features=item_features,
            num_threads=self._cfg.lightfm_num_threads,
        )

        results: list[tuple[int, float]] = []
        for (db_id, _), score in zip(known, scores):
            results.append((db_id, float(score)))
        for db_id, _ in unknown:
            results.append((db_id, 0.0))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: Optional[Path] = None) -> Path:
        cfg = get_settings()
        cfg.ensure_dirs()
        save_path = path or (cfg.model_save_dir / "lightfm_model.pkl")
        with open(save_path, "wb") as f:
            pickle.dump(
                {
                    "model": self._model,
                    "dataset": self._dataset,
                    "item_id_map": self._item_id_map,
                    "item_idx_map": self._item_idx_map,
                },
                f,
            )
        logger.info("Saved LightFM model to %s", save_path)
        return save_path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "FashionRanker":
        cfg = get_settings()
        load_path = path or (cfg.model_save_dir / "lightfm_model.pkl")
        if not load_path.exists():
            raise FileNotFoundError(f"No model at {load_path}")
        with open(load_path, "rb") as f:
            state = pickle.load(f)
        ranker = cls()
        ranker._model = state["model"]
        ranker._dataset = state["dataset"]
        ranker._item_id_map = state["item_id_map"]
        ranker._item_idx_map = state["item_idx_map"]
        logger.info("Loaded LightFM model from %s", load_path)
        return ranker

    # ── Item feature helpers ──────────────────────────────────────────────────

    @staticmethod
    def item_to_tags(item: dict) -> list[str]:
        """Convert an item dict to LightFM feature tags."""
        tags = []
        if item.get("brand"):
            tags.append(f"brand:{item['brand'].lower().replace(' ', '_')}")
        if item.get("source"):
            tags.append(f"source:{item['source']}")
        if item.get("condition"):
            tags.append(f"condition:{item['condition'].lower().replace(' ', '_')}")
        if item.get("size"):
            tags.append(f"size:{item['size'].lower()}")
        if item.get("catalog_id"):
            tags.append(f"catalog:{item['catalog_id']}")
        return tags
