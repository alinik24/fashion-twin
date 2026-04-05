#!/usr/bin/env python
"""Interactive preference seeder — show items and record like/dislike/skip.

This is how you teach the system your taste. Run after initial ingest.

Usage:
    python scripts/seed_preferences.py
    python scripts/seed_preferences.py --limit 50 --source vinted
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage import PostgresStore, InteractionRecord

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

COMMANDS = {
    "l": "like",
    "d": "dislike",
    "s": "skip",
    "v": "view",
    "q": "quit",
}

STRENGTH_MAP = {
    "like": 1.0,
    "dislike": 1.0,
    "skip": 0.5,
    "view": 0.3,
}


def show_item(item: dict, idx: int, total: int) -> None:
    print(f"\n{'─'*60}")
    print(f"[{idx}/{total}] #{item['id']}")
    print(f"  Title    : {item.get('title', 'N/A')}")
    print(f"  Brand    : {item.get('brand', '—')}")
    print(f"  Size     : {item.get('size', '—')}")
    print(f"  Condition: {item.get('condition', '—')}")
    price = item.get("price")
    currency = item.get("currency", "")
    print(f"  Price    : {f'{price:.2f} {currency}' if price else '—'}")
    print(f"  URL      : {item.get('listing_url', '—')}")
    print(f"  Image    : {item.get('image_url', '—')}")


def prompt_action() -> str:
    while True:
        raw = input("\n  [l]ike / [d]islike / [s]kip / [v]iew / [q]uit > ").strip().lower()
        if raw in COMMANDS:
            return COMMANDS[raw]
        print("  Unknown key. Use l/d/s/v/q")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed user preferences interactively")
    parser.add_argument("--limit", type=int, default=100, help="Max items to review")
    parser.add_argument("--source", default=None, help="Filter by source (vinted, vestiaire)")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    with PostgresStore() as db:
        # Fetch items that haven't been interacted with yet
        source_clause = f"AND source = '{args.source}'" if args.source else ""
        sql = f"""
            SELECT i.* FROM items i
            LEFT JOIN interactions inter
                ON inter.item_id = i.id AND inter.user_id = {args.user_id}
            WHERE inter.id IS NULL
            {source_clause}
            ORDER BY i.scraped_at DESC
            LIMIT {args.limit}
        """
        db.connect()
        with db._cursor() as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            print("No un-reviewed items found. Run ingest_items.py first.")
            return

        print(f"\nReviewing {len(rows)} items. Commands: [l]ike [d]islike [s]kip [v]iew [q]uit")

        liked = disliked = skipped = 0
        for idx, item in enumerate(rows, 1):
            show_item(item, idx, len(rows))
            action = prompt_action()

            if action == "quit":
                break

            rec = InteractionRecord(
                item_id=item["id"],
                interaction_type=action,
                user_id=args.user_id,
                strength=STRENGTH_MAP.get(action, 1.0),
            )
            db.log_interaction(rec)

            if action == "like":
                liked += 1
            elif action == "dislike":
                disliked += 1
            else:
                skipped += 1

        print(f"\nSession summary: liked={liked}, disliked={disliked}, skipped={skipped}")
        print("Run scripts/train_ranker.py to update your model.")


if __name__ == "__main__":
    main()
