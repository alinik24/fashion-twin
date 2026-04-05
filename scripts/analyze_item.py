#!/usr/bin/env python3
"""
Comprehensive Item Analysis

Deep-dive analysis of a specific Vinted item with complete data retrieval,
condition assessment, seller analysis, and negotiation suggestions.

Usage:
    python scripts/analyze_item.py --url "https://www.vinted.de/items/8569502972"
    python scripts/analyze_item.py --id 8569502972
"""

import sys
import asyncio
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.item_analyzer import ItemAnalyzer
from config import get_settings


def print_section(title: str):
    """Print section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_analysis(analysis):
    """Print comprehensive analysis report."""
    print_section("ITEM DETAILS")
    print(f"Title: {analysis.title}")
    print(f"Brand: {analysis.brand}")
    print(f"Size: {analysis.size}")
    print(f"Price: {analysis.price} {analysis.currency}")
    print(f"URL: {analysis.url}")

    print_section("SELLER PROFILE")
    seller = analysis.seller
    print(f"Username: {seller.username}")
    print(f"Rating: {seller.rating:.1f}/5.0 stars ({seller.total_reviews} reviews)")
    print(f"  Positive: {seller.positive_reviews} | Negative: {seller.negative_reviews}")
    print(f"Items Sold: {seller.items_sold}")
    print(f"Verified: {'Yes' if seller.verified else 'No'}")
    print(f"TRUST SCORE: {seller.trust_score:.1f}/100")

    if seller.trust_score >= 80:
        print("  [EXCELLENT] Highly trustworthy seller")
    elif seller.trust_score >= 60:
        print("  [GOOD] Reliable seller")
    elif seller.trust_score >= 40:
        print("  [FAIR] Proceed with caution")
    else:
        print("  [POOR] High risk seller")

    print_section("SHIPPING INFORMATION")
    ship = analysis.shipping
    if ship.free_shipping:
        print("Shipping: FREE")
    else:
        print(f"Shipping Cost: {ship.cost} {ship.currency}")
    print(f"Total Cost: {ship.total_cost} {analysis.currency}")
    print(f"Estimated Delivery: {ship.estimated_days} days")

    print_section("CONDITION ASSESSMENT")
    cond = analysis.condition
    print(f"Stated Condition: {cond.stated_condition}")
    print(f"AI Assessed: {cond.ai_assessed_condition} (confidence: {cond.confidence:.0%})")
    print(f"Comparison to New: {cond.comparison_to_new}")
    print(f"Authenticity Score: {cond.authenticity_score:.1f}/100")

    if cond.visible_defects:
        print(f"\nVisible Defects:")
        for defect in cond.visible_defects:
            print(f"  - {defect}")

    if cond.wear_indicators:
        print(f"\nWear Indicators:")
        for wear in cond.wear_indicators:
            print(f"  - {wear}")

    if cond.assessment_notes:
        print(f"\nNotes: {cond.assessment_notes}")

    print_section("MARKET ANALYSIS")
    market = analysis.market
    print(f"Current Price: {market.current_price} EUR")
    print(f"Market Average: {market.market_average:.2f} EUR")
    print(f"Price Range: {market.lowest_price:.2f} - {market.highest_price:.2f} EUR")
    print(f"Price Percentile: {market.price_percentile:.0f}th percentile")

    if market.price_percentile <= 25:
        print("  [EXCELLENT] Great price - well below market")
    elif market.price_percentile <= 50:
        print("  [GOOD] Fair price - below average")
    elif market.price_percentile <= 75:
        print("  [FAIR] Average market price")
    else:
        print("  [POOR] Above market price")

    print_section("COMPREHENSIVE SCORING")
    score = analysis.score
    print(f"\nTOTAL SCORE: {score.total_score:.1f}/100 ({score.quality.upper()})")
    print(f"Confidence: {score.confidence:.0%}")
    print(f"\nBreakdown:")
    print(f"  Price Score:        {score.price_score:.1f}/100")
    print(f"  Condition Score:    {score.condition_score:.1f}/100")
    print(f"  Seller Score:       {score.seller_score:.1f}/100")
    print(f"  Shipping Score:     {score.shipping_score:.1f}/100")
    print(f"  Authenticity Score: {score.authenticity_score:.1f}/100")
    print(f"  Match Score:        {score.match_score:.1f}/100")

    print_section("RECOMMENDATION")
    if score.recommendation == "buy_now":
        print("[BUY NOW] Excellent deal - purchase immediately!")
    elif score.recommendation == "negotiate":
        print("[NEGOTIATE] Good item - try to negotiate a better price")
    elif score.recommendation == "watch":
        print("[WATCH] Fair item - monitor for price drop")
    else:
        print("[SKIP] Poor value - look for better options")

    print_section("NEGOTIATION STRATEGY")
    neg = analysis.negotiation
    print(f"Strategy: {neg.negotiation_strategy.replace('_', ' ').title()}")
    print(f"\nSuggested Offer: {neg.suggested_offer:.2f} {analysis.currency}")
    print(f"Acceptable Range: {neg.min_acceptable:.2f} - {neg.max_acceptable:.2f} EUR")
    print(f"Seller Acceptance Probability: {neg.seller_likely_to_accept:.0%}")

    print(f"\nReasoning:")
    print(f"  {neg.reasoning}")

    if neg.talking_points:
        print(f"\nNegotiation Talking Points:")
        for point in neg.talking_points:
            print(f"  - {point}")

    print_section("IMAGES")
    if analysis.images:
        print(f"Total Images: {len(analysis.images)}")
        for i, img_url in enumerate(analysis.images[:5], 1):
            print(f"  {i}. {img_url}")
    else:
        print("No images available")

    print("\n" + "=" * 70)
    print("FINAL RECOMMENDATION")
    print("=" * 70)

    if score.total_score >= 85:
        print("\n[EXCELLENT DEAL]")
        print(f"This is an outstanding deal! Item scores {score.total_score:.1f}/100")
        print(f"Recommended action: Purchase at {analysis.price} EUR immediately")
    elif score.total_score >= 70:
        print("\n[GOOD DEAL]")
        print(f"This is a solid purchase. Item scores {score.total_score:.1f}/100")
        print(f"Recommended action: Negotiate to {neg.suggested_offer:.2f} EUR")
    elif score.total_score >= 55:
        print("\n[FAIR DEAL]")
        print(f"This item is average. Score: {score.total_score:.1f}/100")
        print(f"Recommended action: Strong negotiation or wait for better options")
    else:
        print("\n[POOR DEAL]")
        print(f"This item has issues. Score: {score.total_score:.1f}/100")
        print(f"Recommended action: Skip and find better alternatives")

    print("\n" + "=" * 70)


async def main():
    parser = argparse.ArgumentParser(description="Comprehensive item analysis")
    parser.add_argument('--url', '-u', help="Vinted item URL")
    parser.add_argument('--id', '-i', help="Vinted item ID")
    parser.add_argument('--no-images', action='store_true', help="Skip image analysis")
    parser.add_argument('--save', '-s', action='store_true', help="Save analysis to JSON")
    args = parser.parse_args()

    if not args.url and not args.id:
        parser.error("Either --url or --id is required")

    # Construct URL if ID provided
    if args.id:
        item_url = f"https://www.vinted.de/items/{args.id}"
    else:
        item_url = args.url

    print("=" * 70)
    print("FASHION TWIN - COMPREHENSIVE ITEM ANALYSIS")
    print("=" * 70)
    print(f"\nAnalyzing: {item_url}")
    print("Please wait, fetching and analyzing data...")

    try:
        # Load user preferences
        prefs_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
        if prefs_file.exists():
            with open(prefs_file, 'r') as f:
                user_prefs = json.load(f)
        else:
            user_prefs = {}

        # Run analysis
        analyzer = ItemAnalyzer()
        analysis = await analyzer.analyze_item(
            item_url=item_url,
            user_preferences=user_prefs,
            fetch_images=not args.no_images
        )

        # Print results
        print_analysis(analysis)

        # Save if requested
        if args.save:
            output_dir = Path(__file__).parent.parent / "data" / "analyses"
            filepath = analyzer.save_analysis(analysis, output_dir)
            print(f"\n[SAVED] Analysis saved to: {filepath}")

        return 0

    except Exception as e:
        print(f"\n[ERROR] Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
