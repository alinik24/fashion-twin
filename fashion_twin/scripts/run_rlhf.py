#!/usr/bin/env python
"""Run the RLHF feedback loop.

Phases:
  1. Aggregate behavioral signals → interactions
  2. Collect preference pairs (implicit + LLM judge + optional interactive)
  3. DPO update of LightFM ranker
  4. Update LinUCB bandit with reward scores
  5. Infer new style profile attributes

Usage:
    python scripts/run_rlhf.py
    python scripts/run_rlhf.py --interactive        # CLI comparison pairs
    python scripts/run_rlhf.py --no-llm             # skip LLM judge
    python scripts/run_rlhf.py --collect-only       # collect data, no training
    python scripts/run_rlhf.py --n-items 200        # score more items
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rlhf import RLHFFeedbackLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RLHF feedback loop")
    parser.add_argument("--interactive", action="store_true",
                        help="Show CLI pairwise comparison interface")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM judge auto-labeling")
    parser.add_argument("--collect-only", action="store_true",
                        help="Collect preference pairs but skip DPO update")
    parser.add_argument("--no-profile-update", action="store_true")
    parser.add_argument("--n-items", type=int, default=100,
                        help="Number of items to pass through reward model")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Fashion Twin — RLHF Feedback Loop          ║")
    print("╚══════════════════════════════════════════════╝\n")

    loop = RLHFFeedbackLoop(user_id=args.user_id)
    result = loop.run(
        collect_pairs=True,
        interactive=args.interactive,
        use_llm_judge=not args.no_llm,
        skip_dpo=args.collect_only,
        update_profile=not args.no_profile_update,
        n_items_to_score=args.n_items,
    )

    print("\n── Results ─────────────────────────────────────")
    print(f"  Signals aggregated    : {result.signals_processed}")
    print(f"  Preference pairs      : {result.pairs_collected}")
    if result.dpo_stats:
        d = result.dpo_stats
        print(f"  DPO pairs used        : {d.n_pairs}")
        print(f"  DPO violations        : {d.n_violated}")
        print(f"  Mean margin δ         : {d.mean_margin_before:.3f} → {d.mean_margin_after:.3f}")
    else:
        print(f"  DPO                   : skipped (not enough pairs or --collect-only)")
    print(f"  Bandit updates        : {result.bandit_updates}")
    print(f"  New profile attrs     : {result.profile_attributes_added}")
    if result.errors:
        print(f"\n  Warnings:")
        for e in result.errors:
            print(f"    ⚠ {e}")
    print()


if __name__ == "__main__":
    main()
