#!/usr/bin/env python3
"""
Find Deals Matching User Preferences

Searches database for items matching user profile and finds best deals.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage import PostgresStore
from deal_hunter import DealScorer
from llm.client import get_fast_llm


def load_user_preferences():
    """Load user preferences from JSON file."""
    prefs_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
    with open(prefs_file, 'r') as f:
        return json.load(f)


def find_matching_items(db: PostgresStore, prefs: dict):
    """Find items matching user preferences."""
    print("\n[*] Searching for items matching your preferences...")
    print("-" * 70)

    all_matches = []

    # Search for preferred brands
    for category, brands in prefs['preferred_brands'].items():
        for brand in brands:
            with db._cursor() as cur:
                cur.execute("""
                    SELECT id, external_id, source, title, brand, size, condition,
                           price, currency, image_url, listing_url, scraped_at
                    FROM items
                    WHERE brand ILIKE %s
                    ORDER BY scraped_at DESC
                    LIMIT 50
                """, (f'%{brand}%',))

                results = cur.fetchall()
                for row in results:
                    item = {
                        'id': row[0],
                        'external_id': row[1],
                        'source': row[2],
                        'title': row[3],
                        'brand': row[4],
                        'size': row[5],
                        'condition': row[6],
                        'price': row[7],
                        'currency': row[8],
                        'image_url': row[9],
                        'listing_url': row[10],
                        'created_at': row[11],
                    }
                    all_matches.append(item)

    print(f"  Found {len(all_matches)} items from preferred brands")
    return all_matches


def score_items(items, prefs):
    """Score items based on user preferences."""
    print("\n[*] Scoring items based on your preferences...")
    print("-" * 70)

    scored = []

    for item in items:
        score = 0

        # Brand match
        for category, brands in prefs['preferred_brands'].items():
            if item['brand'] and any(brand.lower() in item['brand'].lower() for brand in brands):
                score += 30
                break

        # Size match
        if item['size']:
            all_sizes = []
            for size_cat, size_vals in prefs['sizes'].items():
                if isinstance(size_vals, list):
                    all_sizes.extend(str(s) for s in size_vals)
                elif isinstance(size_vals, dict):
                    all_sizes.extend(str(v) for v in size_vals.values())
                else:
                    all_sizes.append(str(size_vals))

            if any(s in str(item['size']) for s in all_sizes):
                score += 25

        # Condition match
        if item['condition']:
            cond_order = prefs['condition_preference']['priority_order']
            if item['condition'] in cond_order:
                idx = cond_order.index(item['condition'])
                score += 30 - (idx * 10)

        # Price bonus (cheaper is better)
        if item['price']:
            if item['price'] < 30:
                score += 10
            elif item['price'] < 50:
                score += 5

        scored.append((item, score))

    # Sort by score
    scored.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  Top 10 matches:")
    for i, (item, score) in enumerate(scored[:10], 1):
        print(f"  {i}. [{score}/95] {item['title'][:60]}")
        print(f"     {item['brand']} | {item['size']} | {item['condition']} | {item['price']} {item['currency']}")
        print(f"     {item['listing_url']}")

    return scored


def find_deals(scored_items):
    """Find price deals in scored items (simplified version)."""
    print("\n[*] Finding best value items...")
    print("-" * 70)

    # Simple deal finding: low price + good match + good condition
    deals = []

    for item, match_score in scored_items[:30]:
        # Simple deal score: low price + high match
        if item['price'] and item['price'] < 50 and match_score >= 65:
            price_score = max(0, 100 - item['price'] * 2)  # Lower price = higher score
            simple_deal_score = (price_score * 0.6) + (match_score * 0.4)

            if simple_deal_score >= 70:
                deals.append({
                    'item': item,
                    'match_score': match_score,
                    'price_score': price_score,
                    'total_score': simple_deal_score,
                })

    deals.sort(key=lambda x: x['total_score'], reverse=True)

    if deals:
        print(f"\n  Found {len(deals)} great deals!")
        for i, deal in enumerate(deals[:5], 1):
            item = deal['item']
            print(f"\n  {i}. [DEAL] {item['title'][:60]}")
            print(f"     Match: {deal['match_score']}/95 | Value Score: {deal['total_score']:.1f}/100")
            print(f"     {item['brand']} | {item['size']} | {item['condition']}")
            print(f"     Price: {item['price']} {item['currency']}")
            print(f"     {item['listing_url']}")
    else:
        print("  No exceptional deals found")

    return deals


def generate_recommendations(scored_items, deals, prefs):
    """Generate LLM recommendations."""
    print("\n[*] Generating AI recommendations...")
    print("-" * 70)

    top_items = [item for item, score in scored_items[:5]]

    items_text = "\n".join([
        f"- {item['title']} | {item['brand']} | {item['size']} | {item['condition']} | {item['price']} {item['currency']}\n  {item['listing_url']}"
        for item in top_items
    ])

    deals_text = ""
    if deals:
        deals_text = "\n\nBest Deals:\n" + "\n".join([
            f"- {deal['item']['title']} ({deal['total_score']:.0f}/100 value score, {deal['item']['price']} EUR)"
            for deal in deals[:3]
        ])

    llm = get_fast_llm()

    prompt = f"""You are a personal shopping assistant for a user in Germany who loves branded sportswear.

User Profile:
- Preferred brands: {prefs['preferred_brands']}
- Sizes: Shoes {prefs['sizes']['shoes']}, Jeans {prefs['sizes']['jeans']}
- Style: Prefers branded items in excellent condition (new with tags or very good)

Top matching items found:
{items_text}
{deals_text}

Task: Recommend which 2-3 items to buy and explain why they're great picks. Be enthusiastic but concise (max 150 words)."""

    response = llm.system_user(
        "You are an expert fashion shopping assistant specializing in sportswear and deals.",
        prompt
    )

    print(f"\n{response}")
    return response


def main():
    print("=" * 70)
    print("Fashion Twin - Personal Deal Finder")
    print("=" * 70)

    try:
        # Load preferences
        prefs = load_user_preferences()

        with PostgresStore() as db:
            # Find matching items
            items = find_matching_items(db, prefs)

            if not items:
                print("\n[!] No items found matching your preferences.")
                print("    Run: python scripts/ingest_items.py --query 'New Balance 43' --pages 2")
                return 1

            # Score items
            scored = score_items(items, prefs)

            # Find deals
            deals = find_deals(scored)

            # Generate recommendations
            recommendation = generate_recommendations(scored, deals, prefs)

        print("\n" + "=" * 70)
        print("[SUCCESS] Deal finding complete!")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
