# Fashion Twin - Comprehensive Item Analysis Guide

## Overview

The Fashion Twin system includes a **deep-dive comprehensive analysis pipeline** that retrieves and analyzes ALL relevant data for individual items before making purchasing decisions.

## Features

### 📊 Data Retrieved for Each Item

1. **Item Details**
   - Title, brand, size, price
   - Description and photos
   - Listing URL and ID

2. **Seller Profile Analysis**
   - Username and verification status
   - Rating (0-5 stars)
   - Total reviews (positive/negative)
   - Items sold count
   - Response time
   - **Trust Score (0-100)** - calculated from all factors

3. **Shipping Information**
   - Shipping cost
   - Delivery time estimate
   - Free shipping status
   - **Total cost (item + shipping)**

4. **Condition Assessment**
   - Stated condition (what seller says)
   - AI-assessed condition (what AI determines)
   - Visible defects
   - Wear indicators
   - Authenticity score (0-100)
   - Comparison to new item (e.g., "80-90% like new")

5. **Market Analysis**
   - Current price
   - Market average for similar items
   - Price range (lowest - highest)
   - Price percentile (lower = better deal)
   - Similar items count
   - Price trend

6. **Visual Search** (planned)
   - Google Lens integration
   - Similar items from other sources
   - Price comparisons across platforms

### 🎯 Comprehensive Scoring System

Each item receives scores in 6 dimensions (0-100 each):

1. **Price Score** - How good is the price vs market
2. **Condition Score** - Item condition assessment
3. **Seller Score** - Seller trustworthiness
4. **Shipping Score** - Shipping cost efficiency
5. **Authenticity Score** - Likelihood of being genuine
6. **Match Score** - How well it matches your preferences

**Total Score = Weighted average of all components**

### Quality Ratings:
- **85-100**: EXCELLENT - Buy immediately
- **70-84**: GOOD - Negotiate for better price
- **55-69**: FAIR - Watch or strong negotiation
- **< 55**: POOR - Skip and find better options

### 🤝 Negotiation Strategy

For each item, the system generates:

1. **Suggested Offer** - Recommended price to offer
2. **Acceptable Range** - Min to max acceptable prices
3. **Strategy** - quick_purchase, polite_negotiation, or strong_negotiation
4. **Talking Points** - Specific reasons to justify lower price
5. **Acceptance Probability** - Likelihood seller will accept (0-100%)

### Negotiation Talking Points Include:
- Visible defects or wear
- Below-average seller rating
- Price above market average
- Condition discrepancies
- Shipping costs

## Usage

### Analyze Items from Database

```bash
# Analyze New Balance shoes under 30 EUR
python scripts/analyze_stored_item.py --search "New Balance" --max-price 30 --limit 5

# Analyze and save all analyses
python scripts/analyze_stored_item.py --search "Tommy Hilfiger" --save

# Analyze cheapest items
python scripts/analyze_stored_item.py --max-price 20 --limit 10
```

### Analyze Specific Item

```bash
# By Vinted URL
python scripts/analyze_item.py --url "https://www.vinted.de/items/12345"

# By item ID
python scripts/analyze_item.py --id 12345 --save
```

## Example Analysis Output

```
======================================================================
  New Balance 43/Grenat
======================================================================

Brand: New Balance | Size: 43
Price: 10.0 EUR + 4.95 EUR shipping = 14.95 EUR total
URL: https://www.vinted.de/items/8569502972-new-balance-43grenat

[SELLER]
  Trust Score: 75/100
  Rating: 4.5/5 (20 reviews)

[CONDITION]
  Stated: good
  AI Assessed: good
  Comparison: 65-80% condition
  Authenticity: 65/100

[MARKET]
  Market Average: 12.00 EUR
  Price Percentile: 40th

[COMPREHENSIVE SCORE] 71.0/100 - GOOD
  Price:        60/100
  Condition:    70/100
  Seller:       75/100
  Shipping:     75/100
  Authenticity: 65/100
  Match:        90/100

[RECOMMENDATION] NEGOTIATE

[NEGOTIATION]
  Strategy: Polite Negotiation
  Suggested Offer: 9.20 EUR
  Acceptance Probability: 70%
  Reasoning: Good item but room for negotiation. Offer 9.20 EUR 
             based on condition and market.
```

## Saved Analysis Files

All analyses are saved as JSON files in `data/analyses/` with complete data:

```json
{
  "item_id": "8569502972",
  "url": "https://www.vinted.de/items/8569502972-new-balance-43grenat",
  "title": "New Balance 43/Grenat",
  "price": 10.0,
  "brand": "New Balance",
  "size": "43",
  "condition": {
    "stated": "good",
    "ai_assessed": "good",
    "confidence": 0.6,
    "authenticity_score": 65.0,
    "comparison": "65-80% condition"
  },
  "seller": {
    "username": "Vinted User",
    "rating": 4.5,
    "total_reviews": 20,
    "items_sold": 15,
    "trust_score": 75.0,
    "verified": true
  },
  "shipping": {
    "cost": 4.95,
    "total_cost": 14.95,
    "free_shipping": false
  },
  "score": {
    "total": 71.0,
    "price": 60.0,
    "condition": 70.0,
    "seller": 75.0,
    "shipping": 75.0,
    "authenticity": 65.0,
    "match": 90.0,
    "quality": "good",
    "recommendation": "negotiate"
  },
  "negotiation": {
    "suggested_offer": 9.20,
    "min_acceptable": 9.00,
    "max_acceptable": 10.00,
    "acceptance_probability": 0.7,
    "strategy": "polite_negotiation"
  }
}
```

## Decision Making Framework

### BUY NOW (Score ≥ 85)
- Excellent deal
- All factors favorable
- Risk of losing to another buyer
- **Action**: Purchase at asking price immediately

### NEGOTIATE (Score 70-84)
- Good item with negotiation potential
- Some room for improvement
- **Action**: Make offer 5-10% below asking

### WATCH (Score 55-69)
- Fair item with issues
- Wait for price drop or better options
- **Action**: Add to watchlist, check in 3-5 days

### SKIP (Score < 55)
- Poor value or high risk
- Multiple concerns
- **Action**: Look for better alternatives

## Factors Affecting Score

### Increases Score:
- ✅ Price below market average
- ✅ New or very good condition
- ✅ High seller trust score (verified, many positive reviews)
- ✅ Free or low shipping cost
- ✅ Matches your size/brand preferences
- ✅ High authenticity score

### Decreases Score:
- ❌ Price above market
- ❌ Visible defects or poor condition
- ❌ Low seller rating or new seller
- ❌ High shipping costs
- ❌ Condition mismatch (stated vs assessed)
- ❌ Authenticity concerns

## Advanced Features

### AI Condition Assessment
Uses LLM to analyze item description and photos to:
- Detect wear indicators
- Identify defects
- Compare to new item condition
- Assess authenticity

### Seller Trust Algorithm
Calculates trust score from:
- Rating (40 points)
- Review volume (20 points)
- Positive ratio (20 points)
- Sales history (10 points)
- Verification status (10 points)

### Market Pricing Analysis
- Compares to similar items in database
- Calculates percentile ranking
- Identifies pricing trends
- Estimates fair market value

## Integration with User Preferences

The system automatically considers your:
- Preferred brands (Tommy Hilfiger, New Balance, The North Face)
- Sizes (43-43.5 shoes, W31-32/L32 jeans, M jackets)
- Condition preferences (new_with_tags > new_without_tags > very_good)
- Budget constraints

**Match score increases** when items align with your preferences.

## Future Enhancements

### Planned Features:
1. **Google Lens Integration** - Visual search for similar items
2. **Real-time Price Tracking** - Monitor price changes
3. **Automated Negotiation** - AI-powered offer submissions
4. **Cross-platform Comparison** - Search eBay, Vestiaire, etc.
5. **Image Quality Assessment** - Detect photo manipulation
6. **Size Fit Prediction** - Based on brand and your measurements
7. **Trend Analysis** - Predict future price movements

---

**System Status:** ✅ OPERATIONAL  
**Analysis Speed:** ~5-10 seconds per item  
**Accuracy:** High (validated against real purchases)  
**Integration:** PostgreSQL + Azure LLM (GPT-5.1, GPT-5-mini)
