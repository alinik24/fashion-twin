"""Training orchestrator — pulls data from Postgres, trains LightFM, saves artefacts."""

from __future__ import annotations

import logging
from typing import Optional

from config import get_settings
from storage import PostgresStore

from .lightfm_model import FashionRanker

logger = logging.getLogger(__name__)


def train(
    user_id: int = 1,
    epochs: Optional[int] = None,
    db: Optional[PostgresStore] = None,
    verbose: bool = True,
) -> FashionRanker:
    """
    Full training run:
    1. Load interactions from Postgres
    2. Build item feature tags from metadata
    3. Fit LightFM
    4. Save artefact + Postgres snapshot
    5. Return trained ranker

    Args:
        user_id: whose interactions to train on (default 1 = you)
        epochs: override settings value
        db: existing DB connection (or creates one)
        verbose: print progress

    Returns:
        Trained FashionRanker instance
    """
    cfg = get_settings()
    _close_db = db is None
    if db is None:
        db = PostgresStore()
        db.connect()

    try:
        # 1. Interactions
        interactions = db.get_interaction_matrix(user_id=user_id)
        if not interactions:
            raise ValueError(
                "No interactions found. Run scripts/seed_preferences.py first."
            )
        if verbose:
            logger.info("Loaded %d interaction records", len(interactions))

        # 2. Item features from metadata
        all_item_ids = list({r["item_id"] for r in interactions})
        item_features: list[dict] = []
        for item_id in all_item_ids:
            item = db.get_item(item_id)
            if item:
                tags = FashionRanker.item_to_tags(item)
                if tags:
                    item_features.append({"item_id": item_id, "tags": tags})

        if verbose:
            logger.info("Built features for %d items", len(item_features))

        # 3. Build dataset + train
        ranker = FashionRanker()
        ranker.build_dataset(interactions, item_features=item_features)
        int_mat, weight_mat = ranker.build_interactions_matrix(interactions)

        feat_mat = None
        if item_features:
            try:
                feat_mat = ranker.build_item_features(item_features)
            except Exception as exc:
                logger.warning("Could not build item feature matrix: %s — skipping features", exc)

        ranker.train(
            interactions_mat=int_mat,
            weights_mat=weight_mat,
            item_features=feat_mat,
            epochs=epochs,
        )

        # 4. Save
        model_path = ranker.save()

        metrics = {
            "n_interactions": len(interactions),
            "n_items": len(all_item_ids),
            "n_features": len(item_features),
        }
        db.save_model_snapshot(
            model_type="lightfm",
            model_path=str(model_path),
            metrics=metrics,
        )

        if verbose:
            logger.info("Training complete. Model saved to %s", model_path)
            logger.info("Metrics: %s", metrics)

        return ranker

    finally:
        if _close_db:
            db.close()
