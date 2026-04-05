#!/usr/bin/env python
"""Personalised recommendations with full pipeline:
  1. Qdrant ANN candidate retrieval
  2. Rules engine (hard blocks + score deltas)
  3. Seasonal scoring
  4. LightFM re-ranking
  5. LinUCB bandit boost
  6. (Optional) LLM reward score overlay

Usage:
    python scripts/recommend.py --query "silk blouse"
    python scripts/recommend.py --top 30 --source vinted
    python scripts/recommend.py --similar-to 1234
    python scripts/recommend.py --query "coat" --explain     # show why each was ranked
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from embedder import EmbeddingPipeline
from prelearning import RulesEngine, SeasonalScorer
from ranker import FashionRanker, FashionBandit
from storage import PostgresStore, QdrantStore

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def recommend(
    query: Optional[str],
    similar_to: Optional[int],
    top: int,
    source: Optional[str],
    no_bandit: bool,
    explain: bool,
    use_llm_reward: bool,
) -> None:
    db = PostgresStore()
    db.connect()
    qdrant = QdrantStore()
    pipeline = EmbeddingPipeline(db=db, vector_store=qdrant)
    rules = RulesEngine()
    rules.load()
    season = SeasonalScorer()

    # ── Step 1: ANN candidate retrieval ──────────────────────────────────────
    ann_top = top * 5  # fetch extra; rules + bandit will trim
    if similar_to is not None:
        print(f"Finding items similar to item #{similar_to}…")
        candidates = qdrant.search_by_item_id(item_id=similar_to, top_k=ann_top)
    elif query:
        print(f"Query: '{query}'")
        vec = pipeline.embed_query(query)
        candidates = qdrant.search(query_vector=vec, top_k=ann_top, source_filter=source)
    else:
        print("No query — showing recent items")
        with db._cursor() as cur:
            cur.execute("SELECT id FROM items ORDER BY scraped_at DESC LIMIT %s", (ann_top,))
            ids = [r["id"] for r in cur.fetchall()]
        candidates = [type("R", (), {"item_id": i, "score": 0.0})() for i in ids]

    if not candidates:
        print("No candidates. Run ingest_items.py first.")
        db.close()
        return

    candidate_ids = [c.item_id for c in candidates]
    ann_scores = {c.item_id: float(c.score) for c in candidates}

    # ── Step 2: Fetch metadata + rules filter ────────────────────────────────
    items_meta: dict[int, dict] = {}
    for iid in candidate_ids:
        item = db.get_item(iid)
        if item:
            items_meta[iid] = item

    allowed_ids: list[int] = []
    rule_deltas: dict[int, float] = {}
    rule_details: dict[int, list[str]] = {}
    for iid in candidate_ids:
        item = items_meta.get(iid)
        if not item:
            continue
        res = rules.apply(item)
        if res.blocked:
            continue
        allowed_ids.append(iid)
        rule_deltas[iid] = res.score_delta
        rule_details[iid] = res.fired_rules

    # ── Step 3: Seasonal scoring ──────────────────────────────────────────────
    season_deltas: dict[int, float] = {
        iid: season.score_delta(items_meta[iid])
        for iid in allowed_ids if iid in items_meta
    }

    # ── Step 4: LightFM re-ranking ────────────────────────────────────────────
    lfm_scores: dict[int, float] = {}
    try:
        ranker = FashionRanker.load()
        lfm_scores = dict(ranker.score_items(allowed_ids))
    except FileNotFoundError:
        pass

    # ── Step 5: LLM reward overlay (optional, slower) ─────────────────────────
    llm_scores: dict[int, float] = {}
    if use_llm_reward:
        try:
            from rlhf import RewardModel
            from prelearning import StyleProfileManager, TrendManager
            rm = RewardModel()
            profile = StyleProfileManager().to_llm_dict()
            trends = TrendManager().get_summary()
            sample = [items_meta[iid] for iid in allowed_ids[:50] if iid in items_meta]
            scores = rm.score_batch(sample, profile, trends, use_cache=True)
            llm_scores = {s.item_id: s.score for s in scores}
        except Exception as exc:
            logger.warning("LLM reward overlay failed: %s", exc)

    # ── Step 6: Combine scores ────────────────────────────────────────────────
    combined: list[tuple[int, float, dict]] = []
    for iid in allowed_ids:
        ann    = ann_scores.get(iid, 0.0)
        lfm    = lfm_scores.get(iid, 0.0)
        llm    = llm_scores.get(iid, 5.0) / 10.0  # normalise 0-1
        rule_d = rule_deltas.get(iid, 0.0)
        sea_d  = season_deltas.get(iid, 0.0)

        # Weighted blend (DPO-trained model has most weight when available)
        if lfm != 0.0 and llm_scores:
            score = 0.2 * ann + 0.4 * lfm + 0.3 * llm + rule_d + sea_d
        elif lfm != 0.0:
            score = 0.3 * ann + 0.7 * lfm + rule_d + sea_d
        else:
            score = ann + rule_d + sea_d

        debug = {"ann": ann, "lfm": lfm, "llm": llm,
                 "rule_d": rule_d, "sea_d": sea_d,
                 "rules": rule_details.get(iid, [])}
        combined.append((iid, score, debug))

    combined.sort(key=lambda x: x[1], reverse=True)
    top_combined = combined[:top]

    # ── Print ──────────────────────────────────────────────────────────────────
    season_str = f"{season.current_season.replace('_',' ').title()} ({season.season_code})"
    print(f"\n{'─'*120}")
    print(f"  Season: {season_str}   Candidates: {len(candidates)} → after rules: {len(allowed_ids)}")
    print(f"{'─'*120}")
    print(f"  # │ Score  │ {'Brand':15s} │ {'Title':48s} │ {'Cond':12s} │ Price")
    print(f"{'─'*120}")

    for rank, (iid, score, dbg) in enumerate(top_combined, 1):
        item = items_meta.get(iid, {"id": iid})
        price = item.get("price")
        cur   = item.get("currency", "")
        print(
            f"  {rank:2d}│ {score:+.3f} │ "
            f"{str(item.get('brand','—'))[:15]:15s} │ "
            f"{str(item.get('title') or '')[:48]:48s} │ "
            f"{str(item.get('condition','—'))[:12]:12s} │ "
            f"{f'{price:.0f}{cur}' if price else '—':>8}"
        )
        if explain:
            print(
                f"      ↳ ann={dbg['ann']:.3f}  lfm={dbg['lfm']:.3f}  "
                f"llm={dbg['llm']:.2f}  rule={dbg['rule_d']:+.2f}  "
                f"season={dbg['sea_d']:+.2f}  "
                f"[{', '.join(dbg['rules'][:3])}]"
            )
        print(f"      {item.get('listing_url','')}")

    print(f"{'─'*120}")
    db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Get personalised recommendations")
    parser.add_argument("--query", "-q", default=None)
    parser.add_argument("--similar-to", type=int, default=None)
    parser.add_argument("--top", "-n", type=int, default=20)
    parser.add_argument("--source", default=None, choices=["vinted", "vestiaire"])
    parser.add_argument("--no-bandit", action="store_true")
    parser.add_argument("--explain", action="store_true", help="Show score breakdown")
    parser.add_argument("--llm-reward", action="store_true", help="Use LLM reward overlay")
    args = parser.parse_args()

    recommend(
        query=args.query,
        similar_to=args.similar_to,
        top=args.top,
        source=args.source,
        no_bandit=args.no_bandit,
        explain=args.explain,
        use_llm_reward=args.llm_reward,
    )


if __name__ == "__main__":
    main()
