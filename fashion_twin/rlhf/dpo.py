"""Direct Preference Optimization (DPO) adapter for LightFM ranker.

Adapts DPO (Rafailov et al. 2023) to a recommendation ranking context.

Original DPO loss (for LLMs):
  L_DPO = -E[log σ(β·(log π(y_w|x) - log π_ref(y_w|x))
                   - β·(log π(y_l|x) - log π_ref(y_l|x)))]

Adaptation for ranking:
  - π(y|x)      = softmax(score(item)) from current LightFM model
  - π_ref(y|x)  = softmax(score(item)) from ANN similarity (reference policy)
  - y_w         = preferred item (winner)
  - y_l         = rejected item (loser)
  - β           = temperature controlling deviation from reference

The DPO update is implemented as:
  1. For each preference pair (winner, loser):
     - Compute margin = score(winner) - score(loser)
     - If margin < threshold → create synthetic positive interaction for winner
       and negative weight for loser
  2. Retrain LightFM with preference-augmented interaction matrix

Reference:
  Rafailov et al. (2023) "Direct Preference Optimization: Your Language Model
  is Secretly a Reward Model." NeurIPS 2023.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.sparse as sp

from config import get_settings
from ranker.lightfm_model import FashionRanker
from .preference import PreferencePair

logger = logging.getLogger(__name__)


@dataclass
class DPOStats:
    n_pairs: int
    n_violated: int           # pairs where winner scored <= loser
    mean_margin_before: float
    mean_margin_after: float
    beta: float


class DPOAdapter:
    """
    Applies DPO-style preference optimization to a LightFM ranker.

    The key insight: instead of gradient-based policy optimization (which
    requires a differentiable model), we convert preference violations into
    interaction weight adjustments that re-train LightFM.
    """

    def __init__(
        self,
        ranker: Optional[FashionRanker] = None,
        beta: Optional[float] = None,
    ) -> None:
        cfg = get_settings()
        self._beta = beta or cfg.rlhf_beta
        self._ranker = ranker
        self._cfg = cfg

    def update(
        self,
        pairs: list[PreferencePair],
        existing_interactions: list[dict],
        item_features: Optional[list[dict]] = None,
    ) -> tuple[FashionRanker, DPOStats]:
        """
        Run one DPO update step.

        Args:
            pairs: preference pairs to learn from
            existing_interactions: base interaction history
            item_features: item metadata tags for content features

        Returns:
            (updated_ranker, stats)
        """
        if not pairs:
            raise ValueError("No preference pairs provided")

        filtered = [p for p in pairs if p.preferred in ("a", "b")]
        if not filtered:
            raise ValueError("No non-equal pairs to learn from")

        # Step 1: Compute current scores for all involved items
        all_item_ids = list({p.item_a_id for p in filtered} | {p.item_b_id for p in filtered})

        current_scores: dict[int, float] = {}
        if self._ranker:
            scored = self._ranker.score_items(all_item_ids)
            current_scores = dict(scored)
        else:
            # No model yet — use reward_a/reward_b from pairs as initial scores
            for p in filtered:
                current_scores[p.item_a_id] = p.reward_a
                current_scores[p.item_b_id] = p.reward_b

        # Step 2: Compute margins before update
        margins_before = self._compute_margins(filtered, current_scores)
        violated = sum(1 for m in margins_before if m <= 0)

        # Step 3: Build augmented interaction set
        augmented = list(existing_interactions)
        augmented.extend(
            self._pairs_to_interactions(filtered, current_scores)
        )

        # Step 4: Retrain LightFM with augmented interactions
        new_ranker = FashionRanker()
        new_ranker.build_dataset(augmented, item_features=item_features)
        int_mat, weight_mat = new_ranker.build_interactions_matrix(augmented)

        feat_mat = None
        if item_features:
            try:
                feat_mat = new_ranker.build_item_features(item_features)
            except Exception:
                pass

        new_ranker.train(int_mat, weight_mat, item_features=feat_mat)

        # Step 5: Compute margins after update
        post_scores = dict(new_ranker.score_items(all_item_ids))
        margins_after = self._compute_margins(filtered, post_scores)

        stats = DPOStats(
            n_pairs=len(filtered),
            n_violated=violated,
            mean_margin_before=float(np.mean(margins_before)) if margins_before else 0.0,
            mean_margin_after=float(np.mean(margins_after)) if margins_after else 0.0,
            beta=self._beta,
        )
        logger.info(
            "DPO update: pairs=%d violated=%d margin: %.3f → %.3f",
            stats.n_pairs,
            stats.n_violated,
            stats.mean_margin_before,
            stats.mean_margin_after,
        )

        self._ranker = new_ranker
        return new_ranker, stats

    # ── Core DPO-inspired conversion ──────────────────────────────────────────

    def _pairs_to_interactions(
        self,
        pairs: list[PreferencePair],
        current_scores: dict[int, float],
    ) -> list[dict]:
        """
        Convert preference pairs to synthetic interactions for LightFM.

        DPO logic adapted to interaction weights:
          - winner gets a positive interaction with weight proportional to
            how much we need to push it up (DPO "upweight")
          - loser gets a diminished weight
        """
        interactions: list[dict] = []

        for pair in pairs:
            winner_id = pair.item_a_id if pair.preferred == "a" else pair.item_b_id
            loser_id = pair.item_b_id if pair.preferred == "a" else pair.item_a_id

            s_w = current_scores.get(winner_id, 0.0)
            s_l = current_scores.get(loser_id, 0.0)

            # DPO-inspired weight: σ(β · (s_ref_w - s_ref_l)) where s_ref = reward scores
            r_w = pair.reward_a if pair.preferred == "a" else pair.reward_b
            r_l = pair.reward_b if pair.preferred == "a" else pair.reward_a

            # Preference weight = how strongly we should reinforce this pair
            # High r_w - r_l → clear preference → strong update
            pref_strength = self._dpo_weight(r_w, r_l)

            # Winner: positive interaction
            interactions.append({
                "item_id": winner_id,
                "interaction_type": "like",
                "total_strength": pref_strength,
            })

            # Loser: if it's currently scored too high, add a skip with negative weight
            # (LightFM WARP doesn't use negatives, so we just reduce loser's boost)
            margin = s_w - s_l
            if margin < 0:  # violation: loser scoring higher
                # Extra push for winner to overcome violation
                interactions.append({
                    "item_id": winner_id,
                    "interaction_type": "like",
                    "total_strength": pref_strength * abs(margin) * 2,
                })

        return interactions

    def _dpo_weight(self, reward_winner: float, reward_loser: float) -> float:
        """
        Compute DPO-style sample weight.
        σ(β · log(π_w/π_l)) ≈ σ(β · (r_w - r_l)) for our reward-parameterized policy.
        Clipped to [0.5, 5.0] to avoid extreme updates.
        """
        delta = reward_winner - reward_loser
        weight = 1.0 / (1.0 + math.exp(-self._beta * delta))  # sigmoid
        return max(0.5, min(5.0, weight * 5.0))  # scale to [0.5, 5.0]

    @staticmethod
    def _compute_margins(
        pairs: list[PreferencePair],
        scores: dict[int, float],
    ) -> list[float]:
        margins = []
        for p in pairs:
            if p.preferred == "equal":
                continue
            w_id = p.item_a_id if p.preferred == "a" else p.item_b_id
            l_id = p.item_b_id if p.preferred == "a" else p.item_a_id
            margins.append(scores.get(w_id, 0.0) - scores.get(l_id, 0.0))
        return margins

    def save_checkpoint(self, stats: DPOStats) -> None:
        """Persist the updated ranker and log DPO training metrics."""
        if not self._ranker:
            return
        cfg = self._cfg
        cfg.ensure_dirs()
        path = self._ranker.save(cfg.rlhf_checkpoint_dir / "lightfm_dpo.pkl")
        try:
            from storage import PostgresStore
            import json
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO dpo_training_log
                               (pairs_used, loss_before, loss_after, beta, model_path)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (
                            stats.n_pairs,
                            -stats.mean_margin_before,
                            -stats.mean_margin_after,
                            stats.beta,
                            str(path),
                        ),
                    )
        except Exception as exc:
            logger.debug("DPO log DB write failed: %s", exc)
