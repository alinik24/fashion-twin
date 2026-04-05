#!/usr/bin/env python
"""Train the LightFM ranker on your stored interactions.

Usage:
    python scripts/train_ranker.py
    python scripts/train_ranker.py --epochs 50
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ranker import train

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the fashion ranker")
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    try:
        ranker = train(user_id=args.user_id, epochs=args.epochs, verbose=True)
        print(f"\n✓ Model trained and saved.")
    except ValueError as exc:
        print(f"\n✗ {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
