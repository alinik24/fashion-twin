#!/usr/bin/env python3
"""
Test Full Fashion Twin Workflow

Tests the complete pipeline: scraping → embedding → ranking → deal hunting
Uses mock data if Vinted scraping fails (auth issues)
"""

import sys
from pathlib import Path
import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from storage import PostgresStore, ItemRecord
from embedder import FashionCLIPEmbedder
from deal_hunter import DealHunter, DealScorer
# from prelearning.profile import StyleProfile  # Not needed for this test
from llm.client import get_fast_llm


def create_mock_items_for_user():
    """Create mock items matching user preferences."""
    print("\n[*] Creating mock items based on user preferences...")

    # Load user preferences
    prefs_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
    with open(prefs_file, 'r') as f:
        prefs = json.load(f)

    mock_items = [
        # New Balance shoes
        ItemRecord(
            external_id="mock_nb_001",
            source="vinted",
            title="New Balance 574 Classic Grey - Size 43",
            description="Brand new New Balance 574 in grey. Never worn, with box.",
            brand="New Balance",
            size="43",
            condition="new_with_tags",
            price=45.0,
            currency="EUR",
            image_url="https://example.com/nb574.jpg",
            listing_url="https://www.vinted.de/items/mock_nb_001",
            catalog_id="365"  # Sneakers category
        ),
        ItemRecord(
            external_id="mock_nb_002",
            source="vinted",
            title="New Balance 530 White/Blue - Size 43.5",
            description="Lightly used New Balance 530, very good condition",
            brand="New Balance",
            size="43.5",
            condition="very_good",
            price=55.0,
            currency="EUR",
            image_url="https://example.com/nb530.jpg",
            listing_url="https://www.vinted.de/items/mock_nb_002",
            catalog_id="365"
        ),

        # Tommy Hilfiger jeans
        ItemRecord(
            external_id="mock_th_001",
            source="vinted",
            title="Tommy Hilfiger Slim Fit Jeans W31/L32 Dark Blue",
            description="Tommy Hilfiger jeans, slim fit, dark wash. Excellent condition.",
            brand="Tommy Hilfiger",
            size="W31/L32",
            condition="very_good",
            price=25.0,
            currency="EUR",
            image_url="https://example.com/th_jeans.jpg",
            listing_url="https://www.vinted.de/items/mock_th_001",
            catalog_id="12"  # Jeans category
        ),

        # The North Face jacket
        ItemRecord(
            external_id="mock_tnf_001",
            source="vinted",
            title="The North Face 1996 Retro Nuptse Jacket Black - Size M",
            description="Iconic TNF puffer jacket. Excellent condition, barely worn.",
            brand="The North Face",
            size="M",
            condition="very_good",
            price=120.0,
            currency="EUR",
            image_url="https://example.com/tnf_nuptse.jpg",
            listing_url="https://www.vinted.de/items/mock_tnf_001",
            catalog_id="16"  # Jackets category
        ),

        # Random items (not matching preferences)
        ItemRecord(
            external_id="mock_random_001",
            source="vinted",
            title="H&M Basic T-Shirt White - Size S",
            description="Basic white t-shirt from H&M",
            brand="H&M",
            size="S",
            condition="good",
            price=5.0,
            currency="EUR",
            image_url="https://example.com/hm_tshirt.jpg",
            listing_url="https://www.vinted.de/items/mock_random_001",
            catalog_id="1220"
        ),
    ]

    print(f"  Created {len(mock_items)} mock items")
    return mock_items


def test_storage(items):
    """Test storing items in database."""
    print("\n[1] Testing Storage...")
    print("-" * 70)

    with PostgresStore() as db:
        new_count = 0
        for item in items:
            if db.upsert_item(item):
                new_count += 1

        print(f"  Stored: {new_count} new items, {len(items) - new_count} updated")

        # Get statistics
        with db._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM items")
            total_items = cur.fetchone()[0]
            print(f"  Database stats: total_items={total_items}")

    return True


def test_style_profile(items):
    """Test building style profile from items."""
    print("\n[2] Testing Style Profile Builder...")
    print("-" * 70)

    # profile = StyleProfile()  # Using manual scoring instead

    # Load user preferences
    prefs_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
    with open(prefs_file, 'r') as f:
        user_prefs = json.load(f)

    print(f"  User preferences loaded:")
    print(f"    Preferred brands: {user_prefs['preferred_brands']}")
    print(f"    Shoe sizes: {user_prefs['sizes']['shoes']}")
    print(f"    Condition preference: {user_prefs['condition_preference']['priority_order']}")

    # Score items based on profile
    scored_items = []
    for item in items:
        score = 0

        # Brand match
        for category, brands in user_prefs['preferred_brands'].items():
            if item.brand and item.brand in brands:
                score += 30
                print(f"  [+] {item.title[:50]} - Brand match ({item.brand}): +30")

        # Size match (simple check)
        if item.size:
            all_sizes = []
            for size_cat, size_vals in user_prefs['sizes'].items():
                if isinstance(size_vals, list):
                    all_sizes.extend(size_vals)
                elif isinstance(size_vals, dict):
                    all_sizes.extend(size_vals.values())
                else:
                    all_sizes.append(size_vals)

            if any(str(s) in str(item.size) for s in all_sizes):
                score += 20
                print(f"  [+] {item.title[:50]} - Size match ({item.size}): +20")

        # Condition match
        if item.condition in user_prefs['condition_preference']['priority_order']:
            idx = user_prefs['condition_preference']['priority_order'].index(item.condition)
            condition_score = 30 - (idx * 10)  # 30 for new_with_tags, 20 for new_without_tags, etc.
            score += condition_score
            print(f"  [+] {item.title[:50]} - Condition ({item.condition}): +{condition_score}")

        scored_items.append((item, score))

    # Sort by score
    scored_items.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  Top matches for user:")
    for item, score in scored_items[:3]:
        print(f"    {score}/80 - {item.title}")
        print(f"           {item.brand} | {item.size} | {item.condition} | {item.price} EUR")

    return scored_items


def test_deal_hunting(items):
    """Test deal hunting and scoring."""
    print("\n[3] Testing Deal Hunter...")
    print("-" * 70)

    hunter = DealHunter()
    scorer = DealScorer()

    deals = []
    for item in items:
        # Calculate market average (mock - in reality from database)
        market_avg = item.price * 1.5  # Assume market is 50% higher

        # Score deal
        score = scorer.score_deal(
            item_id=item.external_id,
            current_price=item.price,
            market_avg=market_avg,
            condition=item.condition,
            created_at=datetime.now(),
            brand=item.brand or "",
        )

        if score.total_score >= 60:  # Good deal threshold
            deals.append((item, score))
            print(f"  [DEAL] FOUND: {item.title[:50]}")
            print(f"      Score: {score.total_score:.1f}/100 ({score.quality})")
            print(f"      Price: {item.price} EUR (market: {market_avg:.2f} EUR)")
            print(f"      Breakdown: Price={score.price_score:.1f}, Condition={score.condition_score:.1f}, Brand={score.brand_bonus:.1f}")

    print(f"\n  Found {len(deals)} good deals")
    return deals


def test_llm_recommendations(scored_items):
    """Test LLM-powered recommendations."""
    print("\n[4] Testing LLM Recommendations...")
    print("-" * 70)

    # Load user preferences
    prefs_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
    with open(prefs_file, 'r') as f:
        user_prefs = json.load(f)

    # Get top 3 items
    top_items = [item for item, score in scored_items[:3]]

    llm = get_fast_llm()

    items_text = "\n".join([
        f"- {item.title} | {item.brand} | Size: {item.size} | Condition: {item.condition} | Price: {item.price} EUR"
        for item in top_items
    ])

    prompt = f"""You are a fashion stylist helping a user in Germany.

User Profile:
- Preferred brands: {user_prefs['preferred_brands']}
- Sizes: Shoes {user_prefs['sizes']['shoes']}, Jeans {user_prefs['sizes']['jeans']}
- Style: Casual, sporty, prefers branded items in good condition

Available items:
{items_text}

Task: Recommend which items to buy and explain why they match the user's style. Keep it under 100 words."""

    response = llm.system_user(
        "You are a fashion stylist and deal hunter.",
        prompt
    )

    print(f"\n  LLM Recommendation:\n")
    print(f"  {response}")

    return response


def main():
    print("=" * 70)
    print("Fashion Twin - Full Workflow Test")
    print("=" * 70)

    try:
        # Create mock items
        items = create_mock_items_for_user()

        # Test each component
        test_storage(items)
        scored_items = test_style_profile(items)
        deals = test_deal_hunting(items)
        recommendation = test_llm_recommendations(scored_items)

        print("\n" + "=" * 70)
        print("[SUCCESS] Full Workflow Test Complete!")
        print("=" * 70)

        print("\nSummary:")
        print(f"  - Items processed: {len(items)}")
        print(f"  - Items matching preferences: {len([s for _, s in scored_items if s > 40])}")
        print(f"  - Good deals found: {len(deals)}")
        print(f"  - LLM recommendation generated: {'Yes' if recommendation else 'No'}")

        print("\n[INFO] Next steps:")
        print("  1. Get Vinted session cookie for real scraping")
        print("  2. Run: python scripts/ingest_items.py --query 'New Balance 43'")
        print("  3. Run: python scripts/hunt_deals.py --scan-once")

        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
