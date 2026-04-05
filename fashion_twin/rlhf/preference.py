"""Preference pair collection and storage.

Preference pairs are the core data structure for RLHF.
Each pair (item_A, item_B, preferred) trains the ranker to
score preferred items higher than rejected ones.

Collection methods:
  1. Explicit   — CLI comparison interface: "which do you prefer?"
  2. Implicit   — derive from signals: (liked item, disliked item) → A>B
  3. LLM judge  — GPT-5.1 auto-labels pairs given the style profile
  4. Cross-session — compare newly seen items against historical liked items

Reference:
  Christiano et al. (2017) "Deep RL from Human Preferences" — synthetic pairs
  Bradley-Terry model — probabilistic preference model underlying RLHF
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PreferencePair:
    item_a_id: int
    item_b_id: int
    preferred: str          # 'a' | 'b' | 'equal' | 'skip'
    reward_a: float = 0.0
    reward_b: float = 0.0
    llm_reasoning: str = ""
    source: str = "explicit"
    context_query: str = ""
    user_id: int = 1


class PreferenceCollector:
    """Builds and stores preference pairs from multiple sources."""

    def __init__(self, user_id: int = 1) -> None:
        self._user_id = user_id
        self._cfg = get_settings()

    # ── Explicit collection (CLI) ─────────────────────────────────────────────

    def collect_explicit_interactive(
        self,
        items: list[dict],
        n_pairs: int = 20,
        context_query: str = "",
    ) -> list[PreferencePair]:
        """
        Show item pairs in CLI; user picks preferred.
        Returns collected pairs (only those not skipped).
        """
        if len(items) < 2:
            print("Need at least 2 items for pairwise comparison.")
            return []

        pairs = self._sample_pairs(items, n_pairs)
        collected: list[PreferencePair] = []

        print(f"\nPairwise preference comparison ({len(pairs)} pairs)")
        print("Commands: [a] prefer A | [b] prefer B | [=] equal | [s] skip | [q] quit\n")

        for i, (item_a, item_b) in enumerate(pairs, 1):
            self._print_pair(i, len(pairs), item_a, item_b)
            choice = self._prompt_choice()
            if choice == "q":
                break
            if choice == "s":
                continue
            pair = PreferencePair(
                item_a_id=item_a["id"],
                item_b_id=item_b["id"],
                preferred=choice,
                source="explicit",
                context_query=context_query,
                user_id=self._user_id,
            )
            self._save_pair(pair)
            collected.append(pair)

        print(f"\nCollected {len(collected)} preference pairs.")
        return collected

    # ── Implicit derivation ───────────────────────────────────────────────────

    def derive_from_interactions(
        self,
        interactions: Optional[list[dict]] = None,
    ) -> list[PreferencePair]:
        """
        Auto-generate pairs from existing interaction history:
          liked items > disliked items (cross-product, sampled)
          purchased items > skipped items
        """
        if interactions is None:
            interactions = self._load_interactions()

        liked = [r["item_id"] for r in interactions
                 if r["interaction_type"] in ("like", "purchase", "favorite")]
        disliked = [r["item_id"] for r in interactions
                    if r["interaction_type"] in ("dislike",)]
        skipped = [r["item_id"] for r in interactions
                   if r["interaction_type"] == "skip"]

        pairs: list[PreferencePair] = []

        # liked > disliked
        for lid in liked:
            sample_neg = random.sample(disliked, min(3, len(disliked)))
            for did in sample_neg:
                pairs.append(PreferencePair(
                    item_a_id=lid,
                    item_b_id=did,
                    preferred="a",
                    reward_a=3.0,
                    reward_b=-3.0,
                    source="implicit",
                    user_id=self._user_id,
                ))

        # liked > skipped (weaker signal)
        for lid in liked[:10]:  # limit
            sample_skip = random.sample(skipped, min(2, len(skipped)))
            for sid in sample_skip:
                pairs.append(PreferencePair(
                    item_a_id=lid,
                    item_b_id=sid,
                    preferred="a",
                    reward_a=3.0,
                    reward_b=0.0,
                    source="implicit",
                    user_id=self._user_id,
                ))

        # Batch save
        for pair in pairs:
            self._save_pair(pair)

        logger.info("Derived %d implicit preference pairs", len(pairs))
        return pairs

    # ── LLM-judge derivation ──────────────────────────────────────────────────

    def derive_from_llm_judge(
        self,
        items: list[dict],
        style_profile: dict,
        trends_summary: str = "",
        n_pairs: int = 30,
    ) -> list[PreferencePair]:
        """
        Use GPT-5.1 to auto-label preference pairs.
        Effective for cold-start and augmenting sparse human feedback.

        Reference: Lee et al. (2023) "RLAIF: Scaling Reinforcement Learning from
        Human Feedback with AI Feedback"
        """
        from rlhf.reward_model import RewardModel
        rm = RewardModel()

        if not self._cfg.rlhf_llm_judge_enabled:
            logger.info("LLM judge disabled — skipping")
            return []

        scores = rm.score_batch(items, style_profile, trends_summary)
        score_map = {s.item_id: s for s in scores}

        pairs_input = self._sample_pairs(items, n_pairs)
        collected: list[PreferencePair] = []

        for item_a, item_b in pairs_input:
            sa = score_map.get(item_a["id"])
            sb = score_map.get(item_b["id"])
            if not sa or not sb:
                continue

            if abs(sa.score - sb.score) < 1.0:
                preferred = "equal"
            elif sa.score > sb.score:
                preferred = "a"
            else:
                preferred = "b"

            pair = PreferencePair(
                item_a_id=item_a["id"],
                item_b_id=item_b["id"],
                preferred=preferred,
                reward_a=sa.score,
                reward_b=sb.score,
                llm_reasoning=sa.reasoning,
                source="llm_judge",
                user_id=self._user_id,
            )
            self._save_pair(pair)
            collected.append(pair)

        logger.info("LLM judge generated %d preference pairs", len(collected))
        return collected

    # ── Load from DB ──────────────────────────────────────────────────────────

    def load_pairs(
        self,
        source: Optional[str] = None,
        min_pairs: Optional[int] = None,
    ) -> list[PreferencePair]:
        """Load stored preference pairs for training."""
        from storage import PostgresStore
        sql = "SELECT * FROM preference_comparisons WHERE user_id=%s AND preferred != 'skip'"
        args: list = [self._user_id]
        if source:
            sql += " AND source=%s"
            args.append(source)
        sql += " ORDER BY created_at DESC"

        with PostgresStore() as db:
            db.connect()
            with db._cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()

        pairs = [
            PreferencePair(
                item_a_id=r["item_a_id"],
                item_b_id=r["item_b_id"],
                preferred=r["preferred"],
                reward_a=float(r["reward_a"] or 0),
                reward_b=float(r["reward_b"] or 0),
                llm_reasoning=r["llm_reasoning"] or "",
                source=r["source"] or "explicit",
                user_id=self._user_id,
            )
            for r in rows
        ]
        if min_pairs and len(pairs) < min_pairs:
            logger.warning(
                "Only %d preference pairs — need %d for reliable DPO. "
                "Run seed_preferences.py or run_rlhf.py --collect",
                len(pairs), min_pairs,
            )
        return pairs

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sample_pairs(items: list[dict], n: int) -> list[tuple[dict, dict]]:
        pairs = []
        idx = list(range(len(items)))
        for _ in range(n * 3):   # oversample, deduplicate
            if len(idx) < 2:
                break
            a, b = random.sample(idx, 2)
            pairs.append((items[a], items[b]))
        # Deduplicate
        seen: set[tuple] = set()
        result = []
        for a, b in pairs:
            key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
            if key not in seen:
                seen.add(key)
                result.append((a, b))
            if len(result) >= n:
                break
        return result

    def _load_interactions(self) -> list[dict]:
        from storage import PostgresStore
        with PostgresStore() as db:
            return db.get_interaction_matrix(user_id=self._user_id)

    def _save_pair(self, pair: PreferencePair) -> None:
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO preference_comparisons
                               (user_id, item_a_id, item_b_id, preferred,
                                reward_a, reward_b, llm_reasoning, source, context_query)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            pair.user_id,
                            pair.item_a_id,
                            pair.item_b_id,
                            pair.preferred,
                            pair.reward_a,
                            pair.reward_b,
                            pair.llm_reasoning,
                            pair.source,
                            pair.context_query,
                        ),
                    )
        except Exception as exc:
            logger.debug("Pair save failed: %s", exc)

    @staticmethod
    def _print_pair(idx: int, total: int, item_a: dict, item_b: dict) -> None:
        def fmt(item: dict, label: str) -> str:
            return (
                f"  [{label}] {item.get('brand','—'):15s} "
                f"{(item.get('title') or '')[:45]:45s} "
                f"{item.get('condition','—'):12s} "
                f"{item.get('price') or '—'} {item.get('currency','')}"
            )
        print(f"\n── Pair {idx}/{total} ─────────────────────────────────────────")
        print(fmt(item_a, "A"))
        print(fmt(item_b, "B"))

    @staticmethod
    def _prompt_choice() -> str:
        while True:
            raw = input("  [a/b/=/s/q] > ").strip().lower()
            if raw in ("a", "b", "=", "s", "q"):
                return "equal" if raw == "=" else raw
            print("  Use a/b/=/s/q")
