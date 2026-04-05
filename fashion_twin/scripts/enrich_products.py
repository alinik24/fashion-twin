#!/usr/bin/env python3
"""Enrich product data using Google Lens.

Uses Google Lens visual search to:
1. Find original product pages
2. Extract detailed information (brand, model, materials, price)
3. Verify authenticity
4. Calculate accurate discounts
5. Detect potential fakes

Installation:
    # Install chrome-lens-ocr
    npm install -g chrome-lens-ocr

    # Or Python wrapper
    pip install chrome-lens-ocr

Usage:
    # Enrich specific item
    python scripts/enrich_products.py --item vinted_123

    # Enrich all unenriched items
    python scripts/enrich_products.py --all

    # Enrich items needing authenticity check
    python scripts/enrich_products.py --check-authenticity

    # Batch enrich (fast)
    python scripts/enrich_products.py --batch 100 --workers 10
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.enrichers.google_lens_enricher import GoogleLensEnricher, batch_enrich_items
from storage.postgres import PostgresStore


def enrich_single_item(item_id: str):
    """Enrich a single item."""
    print(f"\n{'=' * 70}")
    print(f"ENRICHING ITEM: {item_id}")
    print("=" * 70)

    # Get item data
    with PostgresStore() as db:
        with db._cursor() as cur:
            cur.execute("""
                SELECT image_url, title, price, brand
                FROM items
                WHERE item_id = %s
            """, (item_id,))

            result = cur.fetchone()
            if not result:
                print(f"✗ Item not found: {item_id}")
                return

            image_url, title, price, brand = result

    print(f"\nCurrent listing:")
    print(f"  Title: {title}")
    print(f"  Brand: {brand or 'Unknown'}")
    print(f"  Price: £{price}")
    print(f"  Image: {image_url}")

    # Enrich
    enricher = GoogleLensEnricher()

    enriched_data = enricher.enrich_item(
        item_id=item_id,
        image_url=image_url,
        current_title=title,
        current_price=float(price) if price else None
    )

    if not enriched_data:
        print("\n✗ No enrichment data found")
        return

    # Display results
    print(f"\n{'=' * 70}")
    print("ENRICHMENT RESULTS")
    print("=" * 70)

    if enriched_data.get("lens_title"):
        print(f"\nGoogle Lens Match:")
        print(f"  Title: {enriched_data['lens_title']}")
        print(f"  Brand: {enriched_data.get('lens_brand', 'Unknown')}")
        print(f"  Model: {enriched_data.get('lens_model', 'N/A')}")

    if enriched_data.get("lens_original_price"):
        print(f"\nPricing:")
        print(f"  Original retail: £{enriched_data['lens_original_price']}")
        print(f"  Current price: £{price}")

        if enriched_data.get("comparison", {}).get("discount_percentage"):
            discount = enriched_data["comparison"]["discount_percentage"]
            print(f"  Discount: {discount}%")

    if enriched_data.get("official_name"):
        print(f"\nOfficial Product:")
        print(f"  Name: {enriched_data['official_name']}")
        if enriched_data.get("official_price"):
            print(f"  Official price: £{enriched_data['official_price']}")

    if enriched_data.get("materials"):
        print(f"\nMaterials: {', '.join(enriched_data['materials'])}")

    if enriched_data.get("authenticity"):
        auth = enriched_data["authenticity"]
        print(f"\nAuthenticity Check:")
        print(f"  Score: {auth['score']}/100 ({auth['confidence']} confidence)")

        if auth.get("red_flags"):
            print(f"  Red flags:")
            for flag in auth["red_flags"]:
                print(f"    ⚠ {flag}")

    # Store
    enricher.store(item_id, enriched_data)
    print("\n✓ Enrichment data stored")


def enrich_all_unenriched():
    """Enrich all items that don't have metadata yet."""
    print("=" * 70)
    print("ENRICHING ALL UNENRICHED ITEMS")
    print("=" * 70)

    # Get items needing enrichment
    with PostgresStore() as db:
        with db._cursor() as cur:
            cur.execute("""
                SELECT item_id FROM items_needing_enrichment
                WHERE enrichment_status = 'not_enriched'
                ORDER BY id DESC
                LIMIT 100
            """)

            item_ids = [row[0] for row in cur.fetchall()]

    if not item_ids:
        print("\n✓ All items already enriched!")
        return

    print(f"\nFound {len(item_ids)} items to enrich")
    print("Processing...")

    # Batch enrich
    batch_enrich_items(item_ids, max_workers=5)

    print(f"\n✓ Enriched {len(item_ids)} items")


def check_authenticity():
    """Check authenticity for all items with metadata but no authenticity score."""
    print("=" * 70)
    print("CHECKING AUTHENTICITY")
    print("=" * 70)

    with PostgresStore() as db:
        with db._cursor() as cur:
            cur.execute("""
                SELECT item_id FROM items_needing_enrichment
                WHERE enrichment_status = 'authenticity_not_checked'
                LIMIT 50
            """)

            item_ids = [row[0] for row in cur.fetchall()]

    if not item_ids:
        print("\n✓ All items have authenticity scores!")
        return

    print(f"\nFound {len(item_ids)} items to check")

    # Re-enrich to add authenticity
    batch_enrich_items(item_ids, max_workers=5)

    print(f"\n✓ Checked {len(item_ids)} items")


def batch_enrich_command(batch_size: int, workers: int):
    """Enrich items in batches."""
    print("=" * 70)
    print(f"BATCH ENRICHMENT ({batch_size} items, {workers} workers)")
    print("=" * 70)

    with PostgresStore() as db:
        with db._cursor() as cur:
            cur.execute("""
                SELECT item_id FROM items_needing_enrichment
                WHERE enrichment_status = 'not_enriched'
                ORDER BY id DESC
                LIMIT %s
            """, (batch_size,))

            item_ids = [row[0] for row in cur.fetchall()]

    if not item_ids:
        print("\n✓ No items to enrich!")
        return

    print(f"\nEnriching {len(item_ids)} items with {workers} parallel workers...")

    batch_enrich_items(item_ids, max_workers=workers)

    print(f"\n✓ Batch enrichment complete")


def show_stats():
    """Show enrichment statistics."""
    print("=" * 70)
    print("ENRICHMENT STATISTICS")
    print("=" * 70)

    with PostgresStore() as db:
        with db._cursor() as cur:
            # Total items
            cur.execute("SELECT COUNT(*) FROM items WHERE image_url IS NOT NULL")
            total_items = cur.fetchone()[0]

            # Enriched items
            cur.execute("SELECT COUNT(*) FROM product_metadata")
            enriched_items = cur.fetchone()[0]

            # Items with brand
            cur.execute("SELECT COUNT(*) FROM product_metadata WHERE lens_brand IS NOT NULL")
            with_brand = cur.fetchone()[0]

            # Items with original price
            cur.execute("SELECT COUNT(*) FROM product_metadata WHERE lens_original_price IS NOT NULL")
            with_price = cur.fetchone()[0]

            # Items with authenticity check
            cur.execute("SELECT COUNT(*) FROM product_metadata WHERE authenticity_score IS NOT NULL")
            with_auth = cur.fetchone()[0]

            # Potential fakes
            cur.execute("SELECT COUNT(*) FROM potential_fakes")
            fakes = cur.fetchone()[0]

            # Verified deals
            cur.execute("SELECT COUNT(*) FROM verified_deals")
            deals = cur.fetchone()[0]

    print(f"\nTotal items (with images): {total_items}")
    print(f"Enriched items: {enriched_items} ({enriched_items/total_items*100:.1f}%)")
    print(f"  With brand: {with_brand}")
    print(f"  With original price: {with_price}")
    print(f"  With authenticity check: {with_auth}")
    print(f"\nPotential fakes detected: {fakes}")
    print(f"Verified deals found: {deals}")


def list_potential_fakes():
    """List items flagged as potential fakes."""
    print("=" * 70)
    print("POTENTIAL FAKES")
    print("=" * 70)

    with PostgresStore() as db:
        with db._cursor() as cur:
            cur.execute("""
                SELECT
                    item_id,
                    title,
                    price,
                    lens_brand,
                    discount_percentage,
                    authenticity_score,
                    authenticity_red_flags
                FROM potential_fakes
                LIMIT 20
            """)

            results = cur.fetchall()

    if not results:
        print("\n✓ No potential fakes found!")
        return

    for item_id, title, price, brand, discount, score, flags in results:
        print(f"\n{item_id}: {title[:50]}")
        print(f"  Brand: {brand}")
        print(f"  Price: £{price} (discount: {discount}%)")
        print(f"  Authenticity: {score}/100")
        print(f"  Red flags: {flags}")


def main():
    parser = argparse.ArgumentParser(description="Enrich product data using Google Lens")

    parser.add_argument("--item", help="Enrich specific item by ID")
    parser.add_argument("--all", action="store_true", help="Enrich all unenriched items")
    parser.add_argument("--check-authenticity", action="store_true", help="Check authenticity for items")
    parser.add_argument("--batch", type=int, help="Batch enrich N items")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel workers (default: 5)")
    parser.add_argument("--stats", action="store_true", help="Show enrichment statistics")
    parser.add_argument("--list-fakes", action="store_true", help="List potential fakes")

    args = parser.parse_args()

    if args.item:
        enrich_single_item(args.item)

    elif args.all:
        enrich_all_unenriched()

    elif args.check_authenticity:
        check_authenticity()

    elif args.batch:
        batch_enrich_command(args.batch, args.workers)

    elif args.stats:
        show_stats()

    elif args.list_fakes:
        list_potential_fakes()

    else:
        parser.print_help()
        print("\nTip: Start with --stats to see what needs enrichment")


if __name__ == "__main__":
    main()
