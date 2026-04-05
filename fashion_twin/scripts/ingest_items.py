#!/usr/bin/env python
"""Scrape items from a marketplace, embed them, and store everything.

Usage:
    python scripts/ingest_items.py --query "silk blouse" --source vinted --pages 5
    python scripts/ingest_items.py --query "leather jacket" --source vestiaire --pages 3
    python scripts/ingest_items.py --query "midi dress" --embed-only   # just embed pending
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collector import VintedCollector, VestiaireCollector
from embedder import EmbeddingPipeline
from storage import PostgresStore, QdrantStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

COLLECTORS = {
    "vinted": VintedCollector,
    "vestiaire": VestiaireCollector,
}


async def scrape_and_store(
    query: str,
    source: str,
    pages: int,
    db: PostgresStore,
) -> tuple[int, int]:
    """Returns (items_found, items_new)."""
    CollectorClass = COLLECTORS[source]
    collector = CollectorClass()

    job_id = db.start_scrape_job(source=source, query=query, pages=pages)
    items_found = 0
    items_new = 0
    error = None

    try:
        result = await collector.collect(query=query, pages=pages)
        items_found = result.count
        logger.info("Collected %d items from %s", items_found, source)

        for item in result.items:
            try:
                item_id = db.upsert_item(item)
                # upsert returns same id for existing; count new ones
                items_new += 1
            except Exception as exc:
                logger.warning("Failed to store item %s: %s", item.external_id, exc)

        if result.errors:
            error = "; ".join(result.errors)

    except Exception as exc:
        error = str(exc)
        logger.error("Scrape failed: %s", exc)

    db.finish_scrape_job(job_id, items_found, items_new, error)
    return items_found, items_new


def embed_pending(db: PostgresStore, batch_size: int = 64) -> None:
    qdrant = QdrantStore()
    qdrant.ensure_collection()
    pipeline = EmbeddingPipeline(db=db, vector_store=qdrant)
    stats = pipeline.run(batch_size=batch_size)
    logger.info(
        "Embedding done — processed=%d, failed=%d", stats.processed, stats.failed
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest fashion items")
    parser.add_argument("--query", "-q", default="")
    parser.add_argument("--source", "-s", choices=list(COLLECTORS), default="vinted")
    parser.add_argument("--pages", "-p", type=int, default=3)
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding step")
    parser.add_argument("--embed-only", action="store_true", help="Only embed pending items")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    with PostgresStore() as db:
        if not args.embed_only:
            if not args.query:
                parser.error("--query is required unless --embed-only")
            found, new = asyncio.run(
                scrape_and_store(args.query, args.source, args.pages, db)
            )
            logger.info("Scraped: found=%d, new=%d", found, new)

        if not args.no_embed:
            embed_pending(db, batch_size=args.batch_size)

    stats = PostgresStore().stats() if True else {}
    with PostgresStore() as db:
        logger.info("DB stats: %s", db.stats())


if __name__ == "__main__":
    main()
