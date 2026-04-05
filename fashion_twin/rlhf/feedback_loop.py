"""RLHF feedback loop orchestrator.

Full RLHF pipeline for fashion recommendations:

  Phase 1 — Signal aggregation:
    Reads behavior_signals + interactions → unified reward signals

  Phase 2 — Preference collection:
    Derives implicit pairs + optionally runs LLM judge or interactive CLI

  Phase 3 — DPO update:
    Applies DPO-adapted preference optimization to LightFM ranker

  Phase 4 — Bandit update:
    Updates LinUCB with new reward observations

  Phase 5 — Profile update:
    Infers new style profile attributes from recent preferences (GPT-5.1)

Scheduling:
    Run daily or after N new signals accumulate.
    Can be triggered manually: python scripts/run_rlhf.py

Scientific basis:
  Full pipeline mirrors InstructGPT (Ouyang et al. 2022):
    SFT → Reward Model → PPO
  Adapted to recommendation:
    Base ranker → LLM reward model → DPO update
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import get_settings
from storage import PostgresStore, QdrantStore
from ranker import FashionRanker, FashionBandit

from .reward_model import RewardModel
from .preference import PreferenceCollector
from .dpo import DPOAdapter, DPOStats

logger = logging.getLogger(__name__)


@dataclass
class FeedbackLoopResult:
    signals_processed: int
    pairs_collected: int
    dpo_stats: Optional[DPOStats]
    bandit_updates: int
    profile_attributes_added: int
    errors: list[str]


class RLHFFeedbackLoop:
    """
    Orchestrates the complete RLHF loop for a single user.

    Usage:
        loop = RLHFFeedbackLoop()
        result = loop.run(collect_pairs=True, interactive=False)
    """

    def __init__(self, user_id: int = 1) -> None:
        self._user_id = user_id
        self._cfg = get_settings()
        self._db = PostgresStore()
        self._rm = RewardModel()
        self._collector = PreferenceCollector(user_id=user_id)
        self._dpo = DPOAdapter()

    def run(
        self,
        collect_pairs: bool = True,
        interactive: bool = False,
        use_llm_judge: bool = True,
        skip_dpo: bool = False,
        update_profile: bool = True,
        n_items_to_score: int = 100,
    ) -> FeedbackLoopResult:
        """
        Run one complete RLHF cycle.

        Args:
            collect_pairs:  whether to collect new preference pairs
            interactive:    if True, show CLI comparison interface
            use_llm_judge:  auto-label pairs via GPT-5.1
            skip_dpo:       skip DPO update (just collect data)
            update_profile: update style profile from preferences
            n_items_to_score: how many items to pass through reward model

        Returns:
            FeedbackLoopResult with summary statistics
        """
        errors: list[str] = []
        signals_processed = 0
        pairs_collected = 0
        dpo_stats = None
        bandit_updates = 0
        profile_attrs = 0

        self._db.connect()

        try:
            # ── Phase 1: Aggregate behavioral signals → interactions ──────────
            signals_processed = self._aggregate_signals()

            # ── Phase 2: Load items + style profile ───────────────────────────
            items = self._get_recent_items(limit=n_items_to_score)
            profile = self._load_style_profile()
            trends = self._get_trends_summary()

            if not items:
                logger.warning("No items found — run ingest_items.py first")
                return FeedbackLoopResult(0, 0, None, 0, 0, ["No items in DB"])

            # ── Phase 3: Preference collection ────────────────────────────────
            if collect_pairs:
                # 3a. Implicit pairs from interaction history
                interactions = self._db.get_interaction_matrix(self._user_id)
                implicit_pairs = self._collector.derive_from_interactions(interactions)
                pairs_collected += len(implicit_pairs)

                # 3b. LLM judge auto-labeling
                if use_llm_judge and self._cfg.rlhf_llm_judge_enabled:
                    try:
                        llm_pairs = self._collector.derive_from_llm_judge(
                            items, profile, trends,
                            n_pairs=min(50, len(items) * 2),
                        )
                        pairs_collected += len(llm_pairs)
                    except Exception as exc:
                        logger.warning("LLM judge failed: %s", exc)
                        errors.append(f"LLM judge: {exc}")

                # 3c. Interactive CLI comparison
                if interactive:
                    explicit_pairs = self._collector.collect_explicit_interactive(
                        items, n_pairs=20
                    )
                    pairs_collected += len(explicit_pairs)

            # ── Phase 4: DPO update ───────────────────────────────────────────
            if not skip_dpo:
                all_pairs = self._collector.load_pairs(
                    min_pairs=self._cfg.rlhf_min_pairs
                )
                if len(all_pairs) >= self._cfg.rlhf_min_pairs:
                    try:
                        interactions = self._db.get_interaction_matrix(self._user_id)
                        item_features = self._build_item_features(
                            list({p.item_a_id for p in all_pairs} |
                                 {p.item_b_id for p in all_pairs})
                        )
                        ranker, dpo_stats = self._dpo.update(
                            all_pairs, interactions, item_features=item_features
                        )
                        self._dpo.save_checkpoint(dpo_stats)
                        logger.info("DPO update complete: %s", dpo_stats)
                    except Exception as exc:
                        logger.error("DPO update failed: %s", exc)
                        errors.append(f"DPO: {exc}")
                else:
                    logger.info(
                        "Not enough pairs (%d < %d) — skipping DPO",
                        len(all_pairs), self._cfg.rlhf_min_pairs,
                    )

            # ── Phase 5: Update bandit with new reward signals ─────────────────
            bandit_updates = self._update_bandit(items, profile, trends)

            # ── Phase 6: Update style profile from preferences ────────────────
            if update_profile and pairs_collected > 0:
                try:
                    profile_attrs = self._infer_profile_updates(items, profile, trends)
                except Exception as exc:
                    logger.warning("Profile update failed: %s", exc)
                    errors.append(f"Profile: {exc}")

        finally:
            self._db.close()

        return FeedbackLoopResult(
            signals_processed=signals_processed,
            pairs_collected=pairs_collected,
            dpo_stats=dpo_stats,
            bandit_updates=bandit_updates,
            profile_attributes_added=profile_attrs,
            errors=errors,
        )

    # ── Phase helpers ─────────────────────────────────────────────────────────

    def _aggregate_signals(self) -> int:
        """Convert raw behavior_signals into weighted interactions."""
        try:
            with self._db._cursor() as cur:
                cur.execute(
                    """INSERT INTO interactions
                           (user_id, item_id, interaction_type, strength, context)
                       SELECT
                           user_id,
                           item_id,
                           CASE
                               WHEN signal_type IN ('offer','purchase','buy')        THEN 'purchase'
                               WHEN signal_type IN ('contact','favorite','like')     THEN 'like'
                               WHEN signal_type IN ('click','zoom','compare')        THEN 'view'
                               WHEN signal_type IN ('dislike')                       THEN 'dislike'
                               WHEN signal_type IN ('scroll_past','skip')            THEN 'skip'
                               ELSE 'view'
                           END,
                           SUM(
                               CASE
                                   WHEN signal_type = 'offer'       THEN 8.0
                                   WHEN signal_type = 'purchase'    THEN 10.0
                                   WHEN signal_type = 'contact'     THEN 6.0
                                   WHEN signal_type = 'favorite'    THEN 4.0
                                   WHEN signal_type = 'like'        THEN 3.0
                                   WHEN signal_type = 'click'       THEN 2.0
                                   WHEN signal_type = 'dwell'       THEN LEAST(2.0, LN(1 + COALESCE(value,0)/3))
                                   WHEN signal_type = 'dislike'     THEN 3.0
                                   WHEN signal_type = 'scroll_past' THEN 0.3
                                   WHEN signal_type = 'skip'        THEN 0.5
                                   ELSE 0.5
                               END
                           ),
                           '{"source": "behavior_signal"}'::jsonb
                       FROM behavior_signals
                       WHERE user_id = %s
                         AND item_id IS NOT NULL
                         AND created_at > COALESCE(
                             (SELECT MAX(created_at) FROM interactions WHERE user_id=%s
                              AND context->>'source'='behavior_signal'),
                             '1970-01-01'::timestamptz
                         )
                       GROUP BY user_id, item_id, signal_type
                       ON CONFLICT DO NOTHING""",
                    (self._user_id, self._user_id),
                )
                count = cur.rowcount
            logger.info("Aggregated %d new signal interactions", count)
            return count
        except Exception as exc:
            logger.warning("Signal aggregation failed: %s", exc)
            return 0

    def _get_recent_items(self, limit: int = 100) -> list[dict]:
        with self._db._cursor() as cur:
            cur.execute(
                "SELECT * FROM items ORDER BY scraped_at DESC LIMIT %s", (limit,)
            )
            return [dict(r) for r in cur.fetchall()]

    def _load_style_profile(self) -> dict:
        from prelearning.profile import StyleProfileManager
        return StyleProfileManager().to_llm_dict()

    def _get_trends_summary(self) -> str:
        from prelearning.trends import TrendManager
        return TrendManager().get_summary()

    def _build_item_features(self, item_ids: list[int]) -> list[dict]:
        features = []
        for iid in item_ids:
            item = self._db.get_item(iid)
            if item:
                tags = FashionRanker.item_to_tags(item)
                if tags:
                    features.append({"item_id": iid, "tags": tags})
        return features

    def _update_bandit(
        self, items: list[dict], profile: dict, trends: str
    ) -> int:
        """Update LinUCB bandit with reward model scores as context."""
        try:
            import numpy as np
            from ranker import FashionBandit
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            from storage import QdrantStore

            bandit = FashionBandit.load()
            qdrant = QdrantStore()
            count = 0

            # Score items with reward model
            scores = self._rm.score_batch(items[:30], profile, trends)
            for rs in scores:
                # Fetch vector from Qdrant for context
                hits = qdrant.client.scroll(
                    collection_name=qdrant.collection,
                    scroll_filter=Filter(
                        must=[FieldCondition(key="item_id",
                                             match=MatchValue(value=rs.item_id))]
                    ),
                    limit=1,
                    with_vectors=True,
                )
                points, _ = hits
                if not points:
                    continue
                vec = np.array(points[0].vector, dtype=np.float32)
                reward = rs.score / self._cfg.rlhf_reward_scale  # normalise to 0-1
                bandit.update(item_id=rs.item_id, reward=reward, context_vector=vec)
                count += 1

            bandit.save()
            return count
        except Exception as exc:
            logger.debug("Bandit update failed: %s", exc)
            return 0

    def _infer_profile_updates(
        self, items: list[dict], profile: dict, trends: str
    ) -> int:
        """Ask GPT-5.1 to infer new style profile attributes from recent preferences."""
        from llm import get_reward_llm
        from prelearning.profile import StyleProfileManager

        interactions = self._db.get_interaction_matrix(self._user_id)
        liked_ids = {r["item_id"] for r in interactions
                     if r["interaction_type"] in ("like", "purchase")}
        liked_items = [i for i in items if i.get("id") in liked_ids][:20]

        if not liked_items:
            return 0

        llm = get_reward_llm()
        prompt = f"""Based on these items the user has liked recently, infer 3-5 new style
profile attributes to add. Be specific and actionable.

Liked items:
{[{k: v for k, v in item.items() if k in ('title','brand','color1','condition','size')}
  for item in liked_items]}

Current profile:
{profile}

Return JSON array of new attributes:
[{{"attribute": "preferred_color", "value": "navy", "strength": 0.8, "source": "rlhf"}}, ...]
Only return NEW attributes not already in the profile."""

        try:
            resp = llm.chat_json([
                {"role": "system", "content": "You are a fashion preference analyst."},
                {"role": "user", "content": prompt},
            ])
            attrs = resp if isinstance(resp, list) else resp.get("attributes", [])
            pm = StyleProfileManager()
            for attr in attrs[:5]:
                pm.set(
                    attribute=attr["attribute"],
                    value=attr["value"],
                    strength=float(attr.get("strength", 0.7)),
                    source=attr.get("source", "rlhf"),
                )
            logger.info("Inferred %d new profile attributes", len(attrs))
            return len(attrs)
        except Exception as exc:
            logger.warning("Profile inference failed: %s", exc)
            return 0
