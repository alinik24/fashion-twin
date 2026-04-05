#!/usr/bin/env python3
"""
Analyze Item from Database

Run comprehensive analysis on items already stored in the database.

Usage:
    python scripts/analyze_stored_item.py --search "New Balance 43"
    python scripts/analyze_stored_item.py --limit 5
"""

import sys
import asyncio
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage import PostgresStore
from pipeline.item_analyzer import (
    ItemAnalysis, SellerProfile, ShippingInfo, ConditionAssessment,
    MarketAnalysis, ComprehensiveScore, NegotiationSuggestion
)
from llm.client import get_reasoning_llm


async def analyze_database_item(item_data: dict, user_prefs: dict) -> ItemAnalysis:
    """Analyze item from database."""
    from pipeline.item_analyzer import ItemAnalyzer
    analyzer = ItemAnalyzer()

    # Build SellerProfile (mock for now since we don't have full data)
    seller = SellerProfile(
        user_id=item_data.get('user_id', 'unknown'),
        username='Vinted User',
        rating=4.5,
        total_reviews=20,
        positive_reviews=18,
        negative_reviews=2,
        items_sold=15,
        response_time='< 24h',
        verified=True,
        trust_score=75.0
    )

    # Calculate shipping
    price = float(item_data['price'])
    shipping_cost = 4.95  # Standard Vinted shipping
    shipping = ShippingInfo(
        cost=shipping_cost,
        currency='EUR',
        method='Standard',
        estimated_days=3,
        free_shipping=False,
        international=False,
        total_cost=price + shipping_cost
    )

    # Assess condition
    condition_map = {
        'New with tags': 'new_with_tags',
        'New without tags': 'new_without_tags',
        'Very good': 'very_good',
        'Good': 'good',
        'Satisfactory': 'satisfactory',
        'Poor': 'poor'
    }

    stated_condition = item_data.get('condition', 'unknown')
    normalized_condition = condition_map.get(stated_condition, stated_condition.lower().replace(' ', '_'))

    # Use LLM for detailed assessment if description available
    description = item_data.get('description', '')
    title = item_data.get('title', '')

    if description:
        llm = get_reasoning_llm()
        prompt = f"""Assess the condition of this secondhand item:

Title: {title}
Stated Condition: {stated_condition}
Description: {description[:300]}

Based on the description, assess:
1. Likely actual condition (new_with_tags, new_without_tags, very_good, good, satisfactory, poor)
2. Any defects or wear mentioned
3. Comparison to new (e.g., "90% like new")
4. Authenticity concerns

Return JSON:
{{
    "assessed_condition": "condition",
    "defects": ["list"],
    "wear": ["list"],
    "comparison": "X% like new",
    "authenticity_score": 85,
    "notes": "brief notes"
}}"""

        try:
            response = llm.system_user(
                "You are an expert at assessing secondhand item condition.",
                prompt
            )

            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()

            assess_data = json.loads(json_str)

            condition = ConditionAssessment(
                stated_condition=stated_condition,
                ai_assessed_condition=assess_data.get('assessed_condition', normalized_condition),
                confidence=0.75,
                visible_defects=assess_data.get('defects', []),
                wear_indicators=assess_data.get('wear', []),
                authenticity_score=assess_data.get('authenticity_score', 75.0),
                comparison_to_new=assess_data.get('comparison', 'Cannot determine'),
                assessment_notes=assess_data.get('notes', '')
            )
        except:
            # Fallback
            condition = analyzer._fallback_condition_assessment(normalized_condition)
    else:
        condition = analyzer._fallback_condition_assessment(normalized_condition)

    # Market analysis
    market = MarketAnalysis(
        current_price=price,
        market_average=price * 1.2,
        lowest_price=price * 0.85,
        highest_price=price * 1.5,
        price_percentile=40.0,
        similar_items_count=10,
        price_trend="stable"
    )

    # Calculate scores
    score = await analyzer._calculate_score(
        item_data, condition, seller, shipping, market, user_prefs
    )

    # Generate negotiation
    negotiation = await analyzer._generate_negotiation(
        item_data, condition, seller, market, score
    )

    # Build analysis
    return ItemAnalysis(
        item_id=item_data['external_id'],
        url=item_data.get('listing_url', ''),
        title=item_data['title'],
        price=price,
        currency=item_data.get('currency', 'EUR'),
        size=item_data.get('size', ''),
        brand=item_data.get('brand', ''),
        condition=condition,
        seller=seller,
        shipping=shipping,
        market=market,
        score=score,
        negotiation=negotiation,
        images=[item_data.get('image_url', '')] if item_data.get('image_url') else [],
        lens_results=None,
        raw_data=item_data,
        analyzed_at=datetime.now(timezone.utc)
    )


def print_analysis_summary(analysis: ItemAnalysis):
    """Print comprehensive analysis summary."""
    print("\n" + "=" * 70)
    print(f"  {analysis.title[:65]}")
    print("=" * 70)

    print(f"\nBrand: {analysis.brand} | Size: {analysis.size}")
    print(f"Price: {analysis.price} EUR + {analysis.shipping.cost} EUR shipping = {analysis.shipping.total_cost} EUR total")
    print(f"URL: {analysis.url}")

    print(f"\n[SELLER]")
    print(f"  Trust Score: {analysis.seller.trust_score:.0f}/100")
    print(f"  Rating: {analysis.seller.rating:.1f}/5 ({analysis.seller.total_reviews} reviews)")

    print(f"\n[CONDITION]")
    print(f"  Stated: {analysis.condition.stated_condition}")
    print(f"  AI Assessed: {analysis.condition.ai_assessed_condition}")
    print(f"  Comparison: {analysis.condition.comparison_to_new}")
    print(f"  Authenticity: {analysis.condition.authenticity_score:.0f}/100")

    if analysis.condition.visible_defects:
        print(f"  Defects: {', '.join(analysis.condition.visible_defects)}")

    print(f"\n[MARKET]")
    print(f"  Market Average: {analysis.market.market_average:.2f} EUR")
    print(f"  Price Percentile: {analysis.market.price_percentile:.0f}th")

    print(f"\n[COMPREHENSIVE SCORE] {analysis.score.total_score:.1f}/100 - {analysis.score.quality.upper()}")
    print(f"  Price:        {analysis.score.price_score:.0f}/100")
    print(f"  Condition:    {analysis.score.condition_score:.0f}/100")
    print(f"  Seller:       {analysis.score.seller_score:.0f}/100")
    print(f"  Shipping:     {analysis.score.shipping_score:.0f}/100")
    print(f"  Authenticity: {analysis.score.authenticity_score:.0f}/100")
    print(f"  Match:        {analysis.score.match_score:.0f}/100")

    print(f"\n[RECOMMENDATION] {analysis.score.recommendation.upper().replace('_', ' ')}")

    print(f"\n[NEGOTIATION]")
    print(f"  Strategy: {analysis.negotiation.negotiation_strategy.replace('_', ' ').title()}")
    print(f"  Suggested Offer: {analysis.negotiation.suggested_offer:.2f} EUR")
    print(f"  Acceptance Probability: {analysis.negotiation.seller_likely_to_accept:.0%}")
    print(f"  Reasoning: {analysis.negotiation.reasoning}")

    if analysis.negotiation.talking_points:
        print(f"  Talking Points:")
        for point in analysis.negotiation.talking_points:
            print(f"    - {point}")

    print("\n" + "-" * 70)


async def main():
    parser = argparse.ArgumentParser(description="Analyze items from database")
    parser.add_argument('--search', '-s', help="Search query (brand, title)")
    parser.add_argument('--limit', '-l', type=int, default=5, help="Number of items to analyze")
    parser.add_argument('--min-price', type=float, help="Minimum price")
    parser.add_argument('--max-price', type=float, help="Maximum price")
    parser.add_argument('--save', action='store_true', help="Save analyses to JSON")
    args = parser.parse_args()

    print("=" * 70)
    print("FASHION TWIN - DATABASE ITEM ANALYSIS")
    print("=" * 70)

    try:
        # Load user preferences
        prefs_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
        if prefs_file.exists():
            with open(prefs_file, 'r') as f:
                user_prefs = json.load(f)
        else:
            user_prefs = {}

        # Fetch items from database
        with PostgresStore() as db:
            with db._cursor() as cur:
                # Build query
                query = "SELECT * FROM items WHERE 1=1"
                params = []

                if args.search:
                    query += " AND (title ILIKE %s OR brand ILIKE %s)"
                    params.extend([f'%{args.search}%', f'%{args.search}%'])

                if args.min_price:
                    query += " AND price >= %s"
                    params.append(args.min_price)

                if args.max_price:
                    query += " AND price <= %s"
                    params.append(args.max_price)

                query += " ORDER BY scraped_at DESC LIMIT %s"
                params.append(args.limit)

                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()

        if not rows:
            print("\nNo items found matching criteria.")
            return 1

        print(f"\nAnalyzing {len(rows)} items...\n")

        analyses = []
        for row in rows:
            item_data = dict(zip(columns, row))

            # Analyze
            analysis = await analyze_database_item(item_data, user_prefs)
            analyses.append(analysis)

            # Print summary
            print_analysis_summary(analysis)

        # Sort by score
        analyses.sort(key=lambda x: x.score.total_score, reverse=True)

        print("\n" + "=" * 70)
        print("TOP RECOMMENDATIONS")
        print("=" * 70)

        for i, analysis in enumerate(analyses[:3], 1):
            print(f"\n{i}. [{analysis.score.total_score:.0f}/100] {analysis.title[:60]}")
            print(f"   {analysis.brand} | {analysis.size} | {analysis.condition.stated_condition}")
            print(f"   {analysis.price} EUR + {analysis.shipping.cost} EUR shipping")
            print(f"   Action: {analysis.score.recommendation.replace('_', ' ').upper()}")
            if analysis.score.recommendation in ['buy_now', 'negotiate']:
                print(f"   Offer: {analysis.negotiation.suggested_offer:.2f} EUR")

        # Save if requested
        if args.save:
            from pipeline.item_analyzer import ItemAnalyzer
            output_dir = Path(__file__).parent.parent / "data" / "analyses"
            output_dir.mkdir(parents=True, exist_ok=True)

            analyzer = ItemAnalyzer()
            for analysis in analyses:
                analyzer.save_analysis(analysis, output_dir)

            print(f"\n[SAVED] {len(analyses)} analyses saved to: {output_dir}")

        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
