"""Online contextual bandit for real-time preference adaptation.

Uses LinUCB (Linear Upper Confidence Bound) from contextualbandits.
The bandit receives the FashionCLIP embedding as context and learns which
items to promote based on like/skip/dislike signals.

Reference: Li et al. (2010) "A Contextual-Bandit Approach to Personalised
           News Article Recommendation", WWW 2010.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

from config import get_settings

logger = logging.getLogger(__name__)


class FashionBandit:
    """
    LinUCB bandit that re-ranks ANN candidates using real-time feedback.

    Usage:
        bandit = FashionBandit()
        # Recommend
        ranked = bandit.rank(candidates, context_vectors)
        # Update after user action
        bandit.update(item_id=42, reward=1.0, context_vector=vec)
    """

    def __init__(self, alpha: float = 0.5, nchoices: int = 1) -> None:
        self._alpha = alpha
        self._nchoices = nchoices
        self._model = None
        self._context_dim: Optional[int] = None
        # Buffer interactions before first fit
        self._buffer_X: list[np.ndarray] = []
        self._buffer_y: list[float] = []
        self._buffer_ids: list[int] = []

    # ── Internal model init ───────────────────────────────────────────────────

    def _init_model(self, dim: int) -> None:
        try:
            from contextualbandits.online import LinUCB
            self._model = LinUCB(nchoices=self._nchoices, alpha=self._alpha)
            self._context_dim = dim
            logger.info("LinUCB bandit initialised (dim=%d, alpha=%.2f)", dim, self._alpha)
        except ImportError as exc:
            raise RuntimeError(
                "contextualbandits not installed. Run: pip install contextualbandits"
            ) from exc

    # ── Scoring / ranking ─────────────────────────────────────────────────────

    def score(
        self,
        context_vectors: np.ndarray,
        item_ids: list[int],
    ) -> list[tuple[int, float]]:
        """
        Score candidates given their context vectors.

        Args:
            context_vectors: (N, dim) array of FashionCLIP embeddings
            item_ids: corresponding DB item IDs

        Returns:
            list of (item_id, score) sorted descending
        """
        if self._model is None or len(self._buffer_X) < 10:
            # Not enough data yet — return uniform scores (no bandit effect)
            return [(iid, 0.0) for iid in item_ids]

        scores_raw = self._predict_scores(context_vectors)
        results = list(zip(item_ids, scores_raw.tolist()))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _predict_scores(self, X: np.ndarray) -> np.ndarray:
        """Return raw LinUCB scores for rows of X."""
        assert self._model is not None
        # LinUCB.predict expects (n_samples, n_features)
        # We use the decision scores (exploit + explore bonus)
        try:
            # contextualbandits API: decision(X) returns chosen arm index
            # For scoring we use the internal scores if available
            if hasattr(self._model, "decision_function"):
                return self._model.decision_function(X)
            # Fallback: use predict and return 1 for predicted arm, 0 otherwise
            preds = self._model.predict(X)
            return preds.astype(float)
        except Exception as exc:
            logger.debug("Bandit score failed: %s", exc)
            return np.zeros(len(X))

    # ── Update (online learning) ──────────────────────────────────────────────

    def update(
        self,
        item_id: int,
        reward: float,
        context_vector: np.ndarray,
    ) -> None:
        """
        Update the bandit with observed reward for an item.

        reward conventions:
          +1.0 = like / purchase
           0.5 = view (neutral positive)
           0.0 = skip
          -0.5 = dislike
        """
        if self._model is None:
            self._init_model(len(context_vector))

        self._buffer_X.append(context_vector)
        self._buffer_y.append(max(0.0, reward))  # LinUCB expects non-negative
        self._buffer_ids.append(item_id)

        # Partial fit once we have enough data
        if len(self._buffer_X) >= 10:
            self._fit_buffer()

    def _fit_buffer(self) -> None:
        assert self._model is not None
        X = np.array(self._buffer_X)
        y = np.array(self._buffer_y)
        # LinUCB partial_fit: (X, actions, rewards)
        # With nchoices=1, action is always 0
        actions = np.zeros(len(y), dtype=int)
        try:
            self._model.partial_fit(X, actions, y)
            logger.debug("Bandit updated with %d samples", len(y))
        except Exception as exc:
            logger.warning("Bandit partial_fit failed: %s", exc)
        # Keep last 100 in buffer for continued learning
        self._buffer_X = self._buffer_X[-100:]
        self._buffer_y = self._buffer_y[-100:]
        self._buffer_ids = self._buffer_ids[-100:]

    # ── Convenience reward mapping ────────────────────────────────────────────

    REWARD_MAP = {
        "purchase": 1.0,
        "like": 1.0,
        "view": 0.5,
        "skip": 0.0,
        "dislike": -0.5,
    }

    def update_from_interaction(
        self,
        interaction_type: str,
        context_vector: np.ndarray,
        item_id: int,
    ) -> None:
        reward = self.REWARD_MAP.get(interaction_type, 0.0)
        self.update(item_id=item_id, reward=reward, context_vector=context_vector)

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: Optional[Path] = None) -> Path:
        cfg = get_settings()
        cfg.ensure_dirs()
        save_path = path or (cfg.model_save_dir / "bandit.pkl")
        with open(save_path, "wb") as f:
            pickle.dump(
                {
                    "model": self._model,
                    "alpha": self._alpha,
                    "context_dim": self._context_dim,
                    "buffer_X": self._buffer_X,
                    "buffer_y": self._buffer_y,
                    "buffer_ids": self._buffer_ids,
                },
                f,
            )
        logger.info("Saved bandit to %s", save_path)
        return save_path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "FashionBandit":
        cfg = get_settings()
        load_path = path or (cfg.model_save_dir / "bandit.pkl")
        if not load_path.exists():
            bandit = cls()
            logger.info("No saved bandit found — starting fresh")
            return bandit
        with open(load_path, "rb") as f:
            state = pickle.load(f)
        bandit = cls(alpha=state["alpha"])
        bandit._model = state["model"]
        bandit._context_dim = state["context_dim"]
        bandit._buffer_X = state["buffer_X"]
        bandit._buffer_y = state["buffer_y"]
        bandit._buffer_ids = state["buffer_ids"]
        logger.info("Loaded bandit from %s", load_path)
        return bandit
