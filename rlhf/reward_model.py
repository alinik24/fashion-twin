"""LLM-based reward model — scores items against the user's style profile.

Architecture:
  Uses configured LLM (via LLM_REWARD_PROVIDER/MODEL) as a "fashion judge":
  - Receives item metadata + user style profile + current trends
  - Returns a structured score (0–10) with breakdown
  - Scores are cached in reward_scores table

Scientific basis:
  - Ziegler et al. (2019) "Fine-Tuning Language Models from Human Feedback"
  - Ouyang et al. (2022) InstructGPT — reward model as preference approximation
  - Bai et al. (2022) "Training a Helpful and Harmless Assistant with RLHF"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from config import get_settings
from llm import get_reward_llm

logger = logging.getLogger(__name__)

REWARD_SYSTEM_PROMPT = """You are an expert personal fashion stylist and AI reward model.
Your task is to evaluate how well a second-hand fashion item matches a specific user's
style profile, preferences, rules, and the current fashion trends.

Be precise and analytical. Consider:
1. Style match — does the item fit the user's aesthetic?
2. Rule compliance — does it violate any hard rules (blocked materials, brands)?
3. Trend alignment — is it trending right now for the current season?
4. Practical fit — size, condition, price range
5. Historical patterns — what has the user liked/disliked before?

Return JSON with exactly these keys:
{
  "score": <float 0-10>,
  "style_match": <float 0-10>,
  "rule_score": <float 0-10>,
  "trend_score": <float 0-10>,
  "practical_score": <float 0-10>,
  "reasoning": "<one sentence explaining the score>",
  "red_flags": ["<flag1>", ...],
  "highlights": ["<plus1>", ...]
}"""


@dataclass
class RewardScore:
    item_id: int
    score: float                        # overall 0-10
    style_match: float = 0.0
    rule_score: float = 0.0
    trend_score: float = 0.0
    practical_score: float = 0.0
    reasoning: str = ""
    red_flags: list[str] = None
    highlights: list[str] = None

    def __post_init__(self):
        if self.red_flags is None:
            self.red_flags = []
        if self.highlights is None:
            self.highlights = []

    @property
    def breakdown(self) -> dict:
        return {
            "style_match": self.style_match,
            "rule_score": self.rule_score,
            "trend_score": self.trend_score,
            "practical_score": self.practical_score,
        }


class RewardModel:
    """
    Uses GPT-5.1 to score items against the user's style profile.
    Scores are cached to avoid repeated LLM calls for the same item.
    """

    MODEL_VERSION = "gpt5.1-reward-v1"

    def __init__(self) -> None:
        self._llm = get_reward_llm()
        self._cfg = get_settings()

    def score_item(
        self,
        item: dict,
        style_profile: dict,
        trends_summary: str = "",
        use_cache: bool = True,
    ) -> RewardScore:
        """Score a single item. Checks DB cache first."""
        if use_cache:
            cached = self._get_cached(item["id"])
            if cached:
                return cached

        score = self._call_llm(item, style_profile, trends_summary)
        self._cache_score(score)
        return score

    def score_batch(
        self,
        items: list[dict],
        style_profile: dict,
        trends_summary: str = "",
    ) -> list[RewardScore]:
        """Score multiple items, reusing cache where possible."""
        results = []
        for item in items:
            try:
                score = self.score_item(item, style_profile, trends_summary)
                results.append(score)
            except Exception as exc:
                logger.warning("Reward score failed for item %s: %s", item.get("id"), exc)
                results.append(RewardScore(item_id=item.get("id", -1), score=5.0))
        return results

    def compare(
        self,
        item_a: dict,
        item_b: dict,
        style_profile: dict,
        trends_summary: str = "",
    ) -> tuple[RewardScore, RewardScore, str]:
        """
        Pairwise comparison: which item better matches the profile?
        Returns (score_a, score_b, preferred='a'|'b'|'equal').
        """
        prompt = self._build_comparison_prompt(item_a, item_b, style_profile, trends_summary)
        try:
            resp = self._llm.chat_json([
                {"role": "system", "content": REWARD_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])
            score_a = self._parse_score(item_a["id"], resp.get("item_a", {}))
            score_b = self._parse_score(item_b["id"], resp.get("item_b", {}))
            preferred = resp.get("preferred", "equal")
        except Exception as exc:
            logger.warning("Comparison LLM call failed: %s", exc)
            score_a = RewardScore(item_id=item_a["id"], score=5.0)
            score_b = RewardScore(item_b["id"], score=5.0)
            preferred = "equal"

        return score_a, score_b, preferred

    # ── LLM calls ─────────────────────────────────────────────────────────────

    def _call_llm(
        self,
        item: dict,
        style_profile: dict,
        trends_summary: str,
    ) -> RewardScore:
        user_content = self._build_score_prompt(item, style_profile, trends_summary)
        try:
            resp = self._llm.chat_json([
                {"role": "system", "content": REWARD_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ])
            return self._parse_score(item["id"], resp)
        except Exception as exc:
            logger.warning("LLM reward call failed: %s", exc)
            return RewardScore(item_id=item["id"], score=5.0, reasoning="LLM unavailable")

    @staticmethod
    def _build_score_prompt(item: dict, profile: dict, trends: str) -> str:
        item_clean = {k: v for k, v in item.items()
                      if k in ("title", "brand", "size", "condition", "price",
                               "currency", "color1", "catalog_id", "source")}
        return f"""## User Style Profile
{json.dumps(profile, indent=2, ensure_ascii=False)}

## Current Trends
{trends or "No trend data available."}

## Item to Evaluate
{json.dumps(item_clean, indent=2, ensure_ascii=False)}

Score this item for this user (0=terrible match, 10=perfect match)."""

    @staticmethod
    def _build_comparison_prompt(
        item_a: dict, item_b: dict, profile: dict, trends: str
    ) -> str:
        item_a_clean = {k: v for k, v in item_a.items()
                        if k in ("title", "brand", "size", "condition", "price")}
        item_b_clean = {k: v for k, v in item_b.items()
                        if k in ("title", "brand", "size", "condition", "price")}
        return f"""## User Style Profile
{json.dumps(profile, indent=2, ensure_ascii=False)}

## Trends
{trends or "N/A"}

## Item A
{json.dumps(item_a_clean, indent=2)}

## Item B
{json.dumps(item_b_clean, indent=2)}

Return JSON:
{{
  "item_a": {{same score keys as usual}},
  "item_b": {{same score keys as usual}},
  "preferred": "a"|"b"|"equal",
  "reasoning": "why one is better"
}}"""

    @staticmethod
    def _parse_score(item_id: int, resp: dict) -> RewardScore:
        return RewardScore(
            item_id=item_id,
            score=float(resp.get("score", 5.0)),
            style_match=float(resp.get("style_match", 5.0)),
            rule_score=float(resp.get("rule_score", 5.0)),
            trend_score=float(resp.get("trend_score", 5.0)),
            practical_score=float(resp.get("practical_score", 5.0)),
            reasoning=resp.get("reasoning", ""),
            red_flags=resp.get("red_flags", []),
            highlights=resp.get("highlights", []),
        )

    # ── DB cache ──────────────────────────────────────────────────────────────

    def _get_cached(self, item_id: int) -> Optional[RewardScore]:
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """SELECT score, score_breakdown FROM reward_scores
                           WHERE item_id=%s AND model_version=%s
                           ORDER BY scored_at DESC LIMIT 1""",
                        (item_id, self.MODEL_VERSION),
                    )
                    row = cur.fetchone()
            if row:
                bd = row["score_breakdown"] or {}
                return RewardScore(
                    item_id=item_id,
                    score=float(row["score"]),
                    style_match=bd.get("style_match", 0.0),
                    rule_score=bd.get("rule_score", 0.0),
                    trend_score=bd.get("trend_score", 0.0),
                    practical_score=bd.get("practical_score", 0.0),
                )
        except Exception:
            pass
        return None

    def _cache_score(self, score: RewardScore) -> None:
        try:
            from storage import PostgresStore
            with PostgresStore() as db:
                with db._cursor() as cur:
                    cur.execute(
                        """INSERT INTO reward_scores
                               (item_id, score, score_breakdown, model_version)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (item_id, user_id, model_version) DO UPDATE
                           SET score=EXCLUDED.score,
                               score_breakdown=EXCLUDED.score_breakdown,
                               scored_at=NOW()""",
                        (
                            score.item_id,
                            score.score,
                            json.dumps(score.breakdown),
                            self.MODEL_VERSION,
                        ),
                    )
        except Exception as exc:
            logger.debug("Reward cache write failed: %s", exc)
