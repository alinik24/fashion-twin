#!/usr/bin/env python
"""Initialize PostgreSQL schema and Qdrant collection.

Run once before any other scripts:
    python scripts/init_db.py
"""

import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from storage import PostgresStore, QdrantStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).parent.parent / "storage" / "schema.sql"


def create_database_if_not_exists(dsn: str) -> None:
    """Create database if it doesn't exist."""
    parsed = urlparse(dsn)
    db_name = parsed.path.lstrip('/')

    # Connect to default postgres database to create our database
    default_dsn = dsn.replace(f'/{db_name}', '/postgres')

    try:
        conn = psycopg2.connect(default_dsn)
        conn.autocommit = True

        with conn.cursor() as cur:
            # Check if database exists
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,)
            )
            exists = cur.fetchone()

            if not exists:
                logger.info(f"Creating database '{db_name}'...")
                cur.execute(f'CREATE DATABASE "{db_name}"')
                logger.info(f"✓ Database '{db_name}' created")
            else:
                logger.info(f"Database '{db_name}' already exists")

        conn.close()
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        raise


def main() -> None:
    cfg = get_settings()
    cfg.ensure_dirs()

    # Create database if it doesn't exist
    create_database_if_not_exists(cfg.postgres_dsn)

    logger.info("Initializing PostgreSQL schema...")
    with PostgresStore(cfg.postgres_dsn) as db:
        if SCHEMA_FILE.exists():
            logger.info("  Running unified schema.sql")
            db.init_schema(SCHEMA_FILE)
        else:
            logger.error("  Schema file not found: %s", SCHEMA_FILE)
            raise FileNotFoundError(f"Schema file missing: {SCHEMA_FILE}")
        stats = db.stats()
        logger.info("DB stats: %s", stats)

    logger.info("Initialising Qdrant collection '%s'…", cfg.qdrant_collection)
    qdrant = QdrantStore()
    qdrant.ensure_collection()
    logger.info("Qdrant: %s", qdrant.collection_info())

    # Initialise data directories
    for d in [
        cfg.rules_file.parent,
        cfg.style_profile_file.parent,
        cfg.tracker_session_file.parent,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    logger.info("Initialisation complete - ready to run!")
    print("\nNext steps:")
    print("  1. python scripts/manage_profile.py setup      # set your style profile")
    print("  2. python scripts/manage_profile.py rules preset sustainable")
    print("  3. python scripts/track_session.py consent enable fashion")
    print("  4. python scripts/ingest_items.py --query 'silk blouse' --pages 5")
    print("  5. python scripts/ingest_trends.py")
    print("  6. python scripts/seed_preferences.py          # label liked/disliked items")
    print("  7. python scripts/run_rlhf.py                  # full RLHF loop")
    print("  8. python scripts/recommend.py --query 'silk blouse' --explain")


if __name__ == "__main__":
    main()
