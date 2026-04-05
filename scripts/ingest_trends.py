#!/usr/bin/env python
"""Scrape and store current fashion trends.

Usage:
    python scripts/ingest_trends.py
    python scripts/ingest_trends.py --force   # ignore cache, re-scrape
    python scripts/ingest_trends.py --show    # print current trends
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from prelearning import TrendManager
from prelearning.season import get_season_year_code

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest fashion trends")
    parser.add_argument("--force", action="store_true", help="Force re-scrape")
    parser.add_argument("--show", action="store_true", help="Print current trends")
    args = parser.parse_args()

    tm = TrendManager()

    if args.show:
        print(tm.get_summary(limit=30))
        kw = tm.get_keywords()
        print(f"\nTrend keywords ({len(kw)}): {', '.join(kw[:30])}")
        return

    print(f"Refreshing trends for {get_season_year_code()}…")
    count = tm.refresh(force=args.force)
    if count > 0:
        print(f"✓ Stored {count} new trends")
    else:
        print("✓ Trends already fresh (use --force to re-scrape)")
    print(tm.get_summary(limit=10))


if __name__ == "__main__":
    main()
