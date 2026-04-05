#!/usr/bin/env python3
"""
System Test Script for Fashion Twin

Tests all major components to verify the system is working correctly.
"""

import sys
import subprocess
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def ensure_database_exists():
    """Ensure database exists before running tests."""
    print("\n[*] Checking database setup...")
    try:
        from config import get_settings
        import psycopg2

        cfg = get_settings()

        # Try to connect to the database
        try:
            conn = psycopg2.connect(cfg.postgres_dsn)
            conn.close()
            print(f"  [OK] Database exists and is accessible")
            return True
        except psycopg2.OperationalError as e:
            if "does not exist" in str(e):
                # Database doesn't exist, run init_db.py
                print(f"  Database not found. Running initialization...")
                result = subprocess.run(
                    [sys.executable, "scripts/init_db.py"],
                    cwd=Path(__file__).parent,
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    print(f"  [OK] Database initialized successfully")
                    return True
                else:
                    print(f"  [FAIL] Initialization failed:")
                    print(result.stderr)
                    return False
            else:
                raise

    except Exception as e:
        print(f"  [FAIL] Database setup check failed: {e}")
        return False


def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    try:
        from config import get_settings
        from llm.client import get_fast_llm, get_reward_llm
        from storage.postgres import PostgresStore
        from storage.qdrant_store import QdrantStore
        from deal_hunter import DealHunter, PriceTracker, DealScorer
        print("[PASS] All imports successful")
        return True
    except Exception as e:
        print(f"[FAIL] Import failed: {e}")
        return False


def test_config():
    """Test configuration loading."""
    print("\nTesting configuration...")
    try:
        from config import get_settings
        cfg = get_settings()
        cfg.ensure_dirs()

        print(f"  Database: {cfg.postgres_dsn[:50]}...")
        print(f"  Qdrant: {cfg.qdrant_url}")
        print(f"  Redis: {cfg.redis_url}")
        print(f"  LLM Provider: {cfg.llm_primary_provider}")
        print(f"  Hunter Enabled: {cfg.hunter_mode_enabled}")
        print("[PASS] Configuration loaded successfully")
        return True
    except Exception as e:
        print(f"[FAIL] Configuration failed: {e}")
        return False


def test_database():
    """Test database connection."""
    print("\nTesting database connection...")
    try:
        from storage.postgres import PostgresStore

        with PostgresStore() as db:
            with db._cursor() as cur:
                cur.execute("SELECT 1 as test")
                result = cur.fetchone()
                assert result[0] == 1

        print("[PASS] Database connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] Database connection failed: {e}")
        print("  Make sure database is created: docker exec -it postgres psql -U postgres -c 'CREATE DATABASE fashion_twin;'")
        return False


def test_qdrant():
    """Test Qdrant connection."""
    print("\nTesting Qdrant connection...")
    try:
        from storage.qdrant_store import QdrantStore
        qdrant = QdrantStore()

        # Test collection exists or can be created
        collections = qdrant.client.get_collections()
        print(f"  Collections: {[c.name for c in collections.collections]}")

        print("[PASS] Qdrant connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] Qdrant connection failed: {e}")
        print("  Make sure Qdrant is running: docker compose up -d qdrant")
        return False


def test_redis():
    """Test Redis connection."""
    print("\nTesting Redis connection...")
    try:
        import redis
        from config import get_settings

        cfg = get_settings()
        r = redis.from_url(cfg.redis_url)
        r.ping()

        print("[PASS] Redis connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] Redis connection failed: {e}")
        print("  Make sure Redis is running: docker compose up -d redis")
        return False


def test_llm():
    """Test LLM connection."""
    print("\nTesting LLM connection...")
    try:
        from llm.client import get_fast_llm

        llm = get_fast_llm()
        response = llm.system_user(
            "You are a helpful assistant.",
            "Say 'OK' in one word only."
        )

        print(f"  LLM Response: {response[:50]}")
        print("[PASS] LLM connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] LLM connection failed: {e}")
        print("  Check your API key in .env")
        return False


def test_deal_scorer():
    """Test deal scoring logic."""
    print("\nTesting deal scorer...")
    try:
        from deal_hunter import DealScorer
        from datetime import datetime

        scorer = DealScorer()

        # Test scoring
        score = scorer.score_deal(
            item_id="test_001",
            current_price=50.0,
            market_avg=100.0,
            condition="good",
            created_at=datetime.now(),
            brand="gucci",
        )

        print(f"  Test Score: {score.total_score:.1f}/100 ({score.quality})")
        print(f"    Price: {score.price_score:.1f}")
        print(f"    Condition: {score.condition_score:.1f}")
        print(f"    Brand Bonus: {score.brand_bonus:.1f}")

        assert score.total_score > 0
        print("[PASS] Deal scorer working")
        return True
    except Exception as e:
        print(f"[FAIL] Deal scorer failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Fashion Twin System Test")
    print("=" * 60)

    # Ensure database exists before testing
    if not ensure_database_exists():
        print("\n[FAIL] Database setup failed. Cannot continue.")
        return 1

    tests = [
        test_imports,
        test_config,
        test_database,
        test_qdrant,
        test_redis,
        test_llm,
        test_deal_scorer,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except KeyboardInterrupt:
            print("\n\nTest interrupted by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n[SUCCESS] All tests passed! System is ready.")
        print("\nNext steps:")
        print("  1. python scripts/ingest_items.py --query 'vintage jacket' --pages 2")
        print("  2. python scripts/hunt_deals.py --scan-once")
        return 0
    else:
        print("\n[FAIL] Some tests failed. Fix issues above before proceeding.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
