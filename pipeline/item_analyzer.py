"""
Comprehensive Item Analyzer

Deep-dive analysis of individual items including:
- Image condition assessment
- Google Lens / visual search
- Seller profile analysis
- Shipping cost calculation
- Comprehensive ranking
- Negotiation suggestions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path
import json

from llm.client import get_fast_llm, get_reasoning_llm
from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SellerProfile:
    """Seller information and trustworthiness."""
    user_id: str
    username: str
    rating: float  # 0-5 stars
    total_reviews: int
    positive_reviews: int
    negative_reviews: int
    items_sold: int
    response_time: Optional[str]
    verified: bool
    trust_score: float  # 0-100 calculated score


@dataclass
class ShippingInfo:
    """Shipping and delivery information."""
    cost: float
    currency: str
    method: str
    estimated_days: Optional[int]
    free_shipping: bool
    international: bool
    total_cost: float  # item price + shipping


@dataclass
class ConditionAssessment:
    """Image-based condition assessment."""
    stated_condition: str  # What seller says
    ai_assessed_condition: str  # What AI sees
    confidence: float  # 0-1
    visible_defects: List[str]
    wear_indicators: List[str]
    authenticity_score: float  # 0-100
    comparison_to_new: str  # "95% like new", "70% worn", etc.
    assessment_notes: str


@dataclass
class MarketAnalysis:
    """Market comparison and pricing analysis."""
    current_price: float
    market_average: float
    lowest_price: float
    highest_price: float
    price_percentile: float  # 0-100, lower = better deal
    similar_items_count: int
    price_trend: str  # "increasing", "stable", "decreasing"


@dataclass
class ComprehensiveScore:
    """Complete scoring breakdown."""
    total_score: float  # 0-100

    # Individual components
    price_score: float  # 0-100
    condition_score: float  # 0-100
    seller_score: float  # 0-100
    shipping_score: float  # 0-100
    authenticity_score: float  # 0-100
    match_score: float  # 0-100 (user preferences)

    # Quality rating
    quality: str  # "excellent", "good", "fair", "poor"

    # Recommendation
    recommendation: str  # "buy_now", "negotiate", "watch", "skip"
    confidence: float  # 0-1


@dataclass
class NegotiationSuggestion:
    """Negotiation strategy and talking points."""
    suggested_offer: float
    min_acceptable: float
    max_acceptable: float

    reasoning: str
    talking_points: List[str]
    seller_likely_to_accept: float  # 0-1 probability

    negotiation_strategy: str


@dataclass
class ItemAnalysis:
    """Complete analysis result for an item."""
    item_id: str
    url: str
    title: str

    # Core data
    price: float
    currency: str
    size: str
    brand: str

    # Detailed assessments
    condition: ConditionAssessment
    seller: SellerProfile
    shipping: ShippingInfo
    market: MarketAnalysis

    # Scoring
    score: ComprehensiveScore

    # Actions
    negotiation: NegotiationSuggestion

    # Raw data
    images: List[str]
    lens_results: Optional[Dict]
    raw_data: Dict

    analyzed_at: datetime


class ItemAnalyzer:
    """Comprehensive item analysis engine."""

    def __init__(self):
        self.cfg = get_settings()
        self.fast_llm = get_fast_llm()
        self.reasoning_llm = get_reasoning_llm()

    async def analyze_item(
        self,
        item_url: str,
        user_preferences: Dict,
        fetch_images: bool = True
    ) -> ItemAnalysis:
        """
        Perform complete deep-dive analysis of an item.

        Args:
            item_url: Vinted item URL or ID
            user_preferences: User preference profile
            fetch_images: Whether to download and analyze images

        Returns:
            Complete ItemAnalysis with all data and recommendations
        """
        logger.info(f"Starting comprehensive analysis for: {item_url}")

        # 1. Fetch item data from Vinted
        item_data = await self._fetch_item_data(item_url)

        # 2. Analyze seller profile
        seller = await self._analyze_seller(item_data)

        # 3. Calculate shipping
        shipping = await self._calculate_shipping(item_data)

        # 4. Assess condition from images
        condition = await self._assess_condition(item_data, fetch_images)

        # 5. Market analysis
        market = await self._analyze_market(item_data)

        # 6. Google Lens / visual search
        lens_results = await self._visual_search(item_data) if fetch_images else None

        # 7. Calculate comprehensive score
        score = await self._calculate_score(
            item_data, condition, seller, shipping, market, user_preferences
        )

        # 8. Generate negotiation strategy
        negotiation = await self._generate_negotiation(
            item_data, condition, seller, market, score
        )

        return ItemAnalysis(
            item_id=item_data['id'],
            url=item_url,
            title=item_data['title'],
            price=item_data['price'],
            currency=item_data.get('currency', 'EUR'),
            size=item_data.get('size', ''),
            brand=item_data.get('brand', ''),
            condition=condition,
            seller=seller,
            shipping=shipping,
            market=market,
            score=score,
            negotiation=negotiation,
            images=item_data.get('photos', []),
            lens_results=lens_results,
            raw_data=item_data,
            analyzed_at=datetime.now()
        )

    async def _fetch_item_data(self, item_url: str) -> Dict:
        """Fetch complete item data from Vinted."""
        # Extract item ID from URL
        item_id = item_url.split('/')[-1].split('-')[0]

        # Use VintedCollector to fetch detailed data
        from collector import VintedCollector
        collector = VintedCollector()

        item = await collector.fetch_item_detail(item_id)
        if not item:
            raise ValueError(f"Could not fetch item {item_id}")

        return item.raw_data

    async def _analyze_seller(self, item_data: Dict) -> SellerProfile:
        """Analyze seller profile and calculate trust score."""
        user_data = item_data.get('user', {})

        # Extract seller info
        user_id = str(user_data.get('id', ''))
        username = user_data.get('login', 'Unknown')

        # Feedback/ratings
        feedback = user_data.get('feedback_reputation', {})
        positive = feedback.get('positive', 0)
        neutral = feedback.get('neutral', 0)
        negative = feedback.get('negative', 0)
        total_reviews = positive + neutral + negative

        # Calculate rating (0-5 stars)
        if total_reviews > 0:
            rating = (positive * 5 + neutral * 3) / total_reviews
        else:
            rating = 0.0

        # Items sold
        items_sold = user_data.get('items_sold_count', 0)

        # Verification
        verified = user_data.get('verified', False)

        # Trust score (0-100)
        trust_score = self._calculate_trust_score(
            rating, total_reviews, positive, negative, items_sold, verified
        )

        return SellerProfile(
            user_id=user_id,
            username=username,
            rating=rating,
            total_reviews=total_reviews,
            positive_reviews=positive,
            negative_reviews=negative,
            items_sold=items_sold,
            response_time=user_data.get('avg_response_time'),
            verified=verified,
            trust_score=trust_score
        )

    def _calculate_trust_score(
        self,
        rating: float,
        total_reviews: int,
        positive: int,
        negative: int,
        items_sold: int,
        verified: bool
    ) -> float:
        """Calculate seller trust score (0-100)."""
        score = 0.0

        # Rating component (40 points)
        score += (rating / 5.0) * 40

        # Review volume (20 points)
        if total_reviews >= 100:
            score += 20
        elif total_reviews >= 50:
            score += 15
        elif total_reviews >= 20:
            score += 10
        elif total_reviews >= 5:
            score += 5

        # Positive ratio (20 points)
        if total_reviews > 0:
            positive_ratio = positive / total_reviews
            score += positive_ratio * 20

        # Sales history (10 points)
        if items_sold >= 100:
            score += 10
        elif items_sold >= 50:
            score += 7
        elif items_sold >= 20:
            score += 5
        elif items_sold >= 5:
            score += 3

        # Verification (10 points)
        if verified:
            score += 10

        return min(100, score)

    async def _calculate_shipping(self, item_data: Dict) -> ShippingInfo:
        """Extract and calculate shipping costs."""
        # Vinted shipping info
        price_data = item_data.get('price_numeric', item_data.get('price', 0))
        item_price = float(price_data) if price_data else 0.0

        # Shipping cost - check if included
        shipping_cost = 0.0
        free_shipping = False

        # Try to extract from package_size or shipping options
        shipping_data = item_data.get('shipping', {})
        if shipping_data:
            shipping_cost = float(shipping_data.get('cost', 0))
            free_shipping = shipping_data.get('free', False)

        # Vinted standard shipping (Germany)
        # Small: 3.95 EUR, Medium: 4.95 EUR, Large: 5.95 EUR
        if shipping_cost == 0 and not free_shipping:
            package_size = item_data.get('package_size_id', 2)
            shipping_cost = {1: 3.95, 2: 4.95, 3: 5.95, 4: 6.95}.get(package_size, 4.95)

        total_cost = item_price + shipping_cost

        return ShippingInfo(
            cost=shipping_cost,
            currency='EUR',
            method='Standard',
            estimated_days=3,
            free_shipping=free_shipping,
            international=False,
            total_cost=total_cost
        )

    async def _assess_condition(
        self,
        item_data: Dict,
        fetch_images: bool
    ) -> ConditionAssessment:
        """Assess item condition using AI vision and stated condition."""
        stated_condition = item_data.get('status', 'unknown')

        if not fetch_images:
            # Basic assessment without images
            return ConditionAssessment(
                stated_condition=stated_condition,
                ai_assessed_condition=stated_condition,
                confidence=0.5,
                visible_defects=[],
                wear_indicators=[],
                authenticity_score=70.0,
                comparison_to_new="Cannot assess without images",
                assessment_notes="No image analysis performed"
            )

        # Get images
        photos = item_data.get('photos', [])
        if not photos:
            return self._fallback_condition_assessment(stated_condition)

        # Use LLM for image analysis
        image_urls = []
        for photo in photos[:3]:  # Analyze first 3 images
            if isinstance(photo, dict):
                img_url = photo.get('full_size_url') or photo.get('url')
                if img_url:
                    image_urls.append(img_url)

        if not image_urls:
            return self._fallback_condition_assessment(stated_condition)

        # AI assessment via LLM vision
        assessment = await self._llm_assess_condition(
            image_urls,
            item_data.get('title', ''),
            item_data.get('description', ''),
            stated_condition
        )

        return assessment

    async def _llm_assess_condition(
        self,
        image_urls: List[str],
        title: str,
        description: str,
        stated_condition: str
    ) -> ConditionAssessment:
        """Use LLM to assess condition from images."""
        prompt = f"""Analyze these product images and assess the actual condition.

Product: {title}
Stated Condition: {stated_condition}
Description: {description[:200]}

Image URLs: {', '.join(image_urls[:3])}

Assess:
1. Actual condition (new_with_tags, new_without_tags, very_good, good, satisfactory, poor)
2. Visible defects (list any wear, stains, damage you can see)
3. Wear indicators (areas showing use)
4. Comparison to new (e.g., "95% like new", "70% worn but functional")
5. Authenticity concerns (does it look genuine?)

Return JSON:
{{
    "assessed_condition": "condition_name",
    "confidence": 0.8,
    "defects": ["list", "of", "defects"],
    "wear": ["wear", "indicators"],
    "authenticity_score": 85,
    "comparison": "90% like new - minimal signs of wear",
    "notes": "Brief assessment"
}}"""

        response = self.reasoning_llm.system_user(
            "You are an expert at assessing secondhand item condition from images.",
            prompt
        )

        # Parse JSON response
        try:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)

            return ConditionAssessment(
                stated_condition=stated_condition,
                ai_assessed_condition=data.get('assessed_condition', stated_condition),
                confidence=data.get('confidence', 0.7),
                visible_defects=data.get('defects', []),
                wear_indicators=data.get('wear', []),
                authenticity_score=data.get('authenticity_score', 70.0),
                comparison_to_new=data.get('comparison', 'Cannot determine'),
                assessment_notes=data.get('notes', '')
            )
        except:
            return self._fallback_condition_assessment(stated_condition)

    def _fallback_condition_assessment(self, stated_condition: str) -> ConditionAssessment:
        """Fallback when image analysis not available."""
        # Map stated condition to scores
        condition_scores = {
            'new_with_tags': (95, "95-100% like new"),
            'new_without_tags': (90, "90-95% like new"),
            'very_good': (80, "80-90% condition"),
            'good': (65, "65-80% condition"),
            'satisfactory': (50, "50-65% condition - noticeable wear"),
            'poor': (30, "30-50% condition - significant wear")
        }

        score, comparison = condition_scores.get(
            stated_condition.lower(),
            (60, "Unknown condition")
        )

        return ConditionAssessment(
            stated_condition=stated_condition,
            ai_assessed_condition=stated_condition,
            confidence=0.6,
            visible_defects=[],
            wear_indicators=[],
            authenticity_score=score,
            comparison_to_new=comparison,
            assessment_notes="Based on seller statement only"
        )

    async def _analyze_market(self, item_data: Dict) -> MarketAnalysis:
        """Analyze market pricing for similar items."""
        # This would query database for similar items
        # For now, estimate based on typical markdowns
        current_price = float(item_data.get('price', 0))

        # Estimate market average (secondhand luxury typically 50-70% of retail)
        # For sportswear/casual, more like 30-50%
        brand = item_data.get('brand', '').lower()

        if any(luxury in brand for luxury in ['gucci', 'prada', 'chanel', 'hermes']):
            market_avg = current_price * 1.3
        elif any(premium in brand for premium in ['north face', 'patagonia', 'arc\'teryx']):
            market_avg = current_price * 1.2
        else:
            market_avg = current_price * 1.15

        lowest = current_price * 0.85
        highest = current_price * 1.5

        # Price percentile (lower = better deal)
        if current_price <= lowest:
            percentile = 10
        elif current_price <= market_avg:
            percentile = 40
        else:
            percentile = 70

        return MarketAnalysis(
            current_price=current_price,
            market_average=market_avg,
            lowest_price=lowest,
            highest_price=highest,
            price_percentile=percentile,
            similar_items_count=0,  # Would query DB
            price_trend="stable"
        )

    async def _visual_search(self, item_data: Dict) -> Optional[Dict]:
        """Perform Google Lens / visual search (placeholder)."""
        # This would integrate with Google Lens API or similar
        # For now, return placeholder
        return {
            "source": "google_lens",
            "similar_items": [],
            "price_range": "N/A",
            "notes": "Visual search not yet implemented"
        }

    async def _calculate_score(
        self,
        item_data: Dict,
        condition: ConditionAssessment,
        seller: SellerProfile,
        shipping: ShippingInfo,
        market: MarketAnalysis,
        user_prefs: Dict
    ) -> ComprehensiveScore:
        """Calculate comprehensive score from all factors."""
        # Price score (0-100, lower price = higher score)
        price_score = max(0, 100 - market.price_percentile)

        # Condition score
        condition_map = {
            'new_with_tags': 100,
            'new_without_tags': 95,
            'very_good': 85,
            'good': 70,
            'satisfactory': 50,
            'poor': 25
        }
        condition_score = condition_map.get(
            condition.ai_assessed_condition.lower(),
            60
        )

        # Adjust for stated vs assessed mismatch
        if condition.stated_condition != condition.ai_assessed_condition:
            condition_score *= 0.9  # 10% penalty for mismatch

        # Seller score
        seller_score = seller.trust_score

        # Shipping score (lower cost = higher score)
        if shipping.free_shipping:
            shipping_score = 100
        elif shipping.cost <= 3:
            shipping_score = 90
        elif shipping.cost <= 5:
            shipping_score = 75
        elif shipping.cost <= 7:
            shipping_score = 60
        else:
            shipping_score = 40

        # Authenticity score
        authenticity_score = condition.authenticity_score

        # Match score (user preferences)
        match_score = self._calculate_match_score(item_data, user_prefs)

        # Total score (weighted average)
        total_score = (
            price_score * 0.25 +
            condition_score * 0.20 +
            seller_score * 0.15 +
            shipping_score * 0.10 +
            authenticity_score * 0.15 +
            match_score * 0.15
        )

        # Quality rating
        if total_score >= 85:
            quality = "excellent"
            recommendation = "buy_now"
        elif total_score >= 70:
            quality = "good"
            recommendation = "negotiate"
        elif total_score >= 55:
            quality = "fair"
            recommendation = "watch"
        else:
            quality = "poor"
            recommendation = "skip"

        # Confidence
        confidence = condition.confidence * (seller.total_reviews / 100 if seller.total_reviews < 100 else 1.0)

        return ComprehensiveScore(
            total_score=total_score,
            price_score=price_score,
            condition_score=condition_score,
            seller_score=seller_score,
            shipping_score=shipping_score,
            authenticity_score=authenticity_score,
            match_score=match_score,
            quality=quality,
            recommendation=recommendation,
            confidence=min(1.0, confidence)
        )

    def _calculate_match_score(self, item_data: Dict, user_prefs: Dict) -> float:
        """Calculate how well item matches user preferences."""
        score = 50.0  # Base score

        # Brand match
        brand = item_data.get('brand', '').lower()
        for category, brands in user_prefs.get('preferred_brands', {}).items():
            if any(b.lower() in brand for b in brands):
                score += 25
                break

        # Size match
        size = str(item_data.get('size', '')).lower()
        for size_cat, size_vals in user_prefs.get('sizes', {}).items():
            if isinstance(size_vals, list):
                if any(str(s).lower() in size for s in size_vals):
                    score += 15
                    break

        # Condition preference
        condition = item_data.get('status', '').lower()
        preferred_conditions = user_prefs.get('condition_preference', {}).get('priority_order', [])
        if condition in [c.lower() for c in preferred_conditions]:
            score += 10

        return min(100, score)

    async def _generate_negotiation(
        self,
        item_data: Dict,
        condition: ConditionAssessment,
        seller: SellerProfile,
        market: MarketAnalysis,
        score: ComprehensiveScore
    ) -> NegotiationSuggestion:
        """Generate negotiation strategy and suggestions."""
        current_price = market.current_price

        # Calculate offer based on condition and market
        if score.total_score >= 85:
            # Excellent deal, offer asking price
            suggested_offer = current_price
            negotiation_range = 0.95
        elif score.total_score >= 70:
            # Good item, try 5-10% off
            suggested_offer = current_price * 0.92
            negotiation_range = 0.90
        else:
            # Fair/poor, try 15-20% off
            suggested_offer = current_price * 0.85
            negotiation_range = 0.80

        min_acceptable = current_price * negotiation_range
        max_acceptable = current_price

        # Generate talking points
        talking_points = []

        if condition.visible_defects:
            talking_points.append(f"Visible wear: {', '.join(condition.visible_defects[:2])}")

        if seller.rating < 4.5:
            talking_points.append(f"Seller has limited reviews ({seller.total_reviews})")

        if market.price_percentile > 60:
            talking_points.append(f"Price is above market average")

        # Seller likelihood to accept
        if seller.items_sold > 50 and seller.rating > 4.5:
            acceptance_prob = 0.6  # Established sellers less likely to discount
        elif seller.items_sold < 10:
            acceptance_prob = 0.8  # New sellers more likely to accept offers
        else:
            acceptance_prob = 0.7

        # Strategy
        if score.total_score >= 85:
            strategy = "quick_purchase"
            reasoning = "Excellent deal at current price. Purchase immediately before someone else does."
        elif score.total_score >= 70:
            strategy = "polite_negotiation"
            reasoning = f"Good item but room for negotiation. Offer {suggested_offer:.2f} EUR based on condition and market."
        else:
            strategy = "strong_negotiation"
            reasoning = f"Fair item with issues. Strong negotiation warranted. Start at {suggested_offer:.2f} EUR."

        return NegotiationSuggestion(
            suggested_offer=suggested_offer,
            min_acceptable=min_acceptable,
            max_acceptable=max_acceptable,
            reasoning=reasoning,
            talking_points=talking_points,
            seller_likely_to_accept=acceptance_prob,
            negotiation_strategy=strategy
        )

    def save_analysis(self, analysis: ItemAnalysis, output_dir: Path):
        """Save complete analysis to JSON file."""
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"item_analysis_{analysis.item_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = output_dir / filename

        # Convert to dict
        data = {
            'item_id': analysis.item_id,
            'url': analysis.url,
            'title': analysis.title,
            'price': analysis.price,
            'currency': analysis.currency,
            'size': analysis.size,
            'brand': analysis.brand,
            'condition': {
                'stated': analysis.condition.stated_condition,
                'ai_assessed': analysis.condition.ai_assessed_condition,
                'confidence': analysis.condition.confidence,
                'defects': analysis.condition.visible_defects,
                'wear': analysis.condition.wear_indicators,
                'authenticity_score': analysis.condition.authenticity_score,
                'comparison': analysis.condition.comparison_to_new,
                'notes': analysis.condition.assessment_notes
            },
            'seller': {
                'username': analysis.seller.username,
                'rating': analysis.seller.rating,
                'total_reviews': analysis.seller.total_reviews,
                'items_sold': analysis.seller.items_sold,
                'trust_score': analysis.seller.trust_score,
                'verified': analysis.seller.verified
            },
            'shipping': {
                'cost': analysis.shipping.cost,
                'total_cost': analysis.shipping.total_cost,
                'free_shipping': analysis.shipping.free_shipping
            },
            'market': {
                'current_price': analysis.market.current_price,
                'market_average': analysis.market.market_average,
                'price_percentile': analysis.market.price_percentile
            },
            'score': {
                'total': analysis.score.total_score,
                'price': analysis.score.price_score,
                'condition': analysis.score.condition_score,
                'seller': analysis.score.seller_score,
                'shipping': analysis.score.shipping_score,
                'authenticity': analysis.score.authenticity_score,
                'match': analysis.score.match_score,
                'quality': analysis.score.quality,
                'recommendation': analysis.score.recommendation,
                'confidence': analysis.score.confidence
            },
            'negotiation': {
                'suggested_offer': analysis.negotiation.suggested_offer,
                'min_acceptable': analysis.negotiation.min_acceptable,
                'max_acceptable': analysis.negotiation.max_acceptable,
                'reasoning': analysis.negotiation.reasoning,
                'talking_points': analysis.negotiation.talking_points,
                'acceptance_probability': analysis.negotiation.seller_likely_to_accept,
                'strategy': analysis.negotiation.negotiation_strategy
            },
            'images': analysis.images,
            'analyzed_at': analysis.analyzed_at.isoformat()
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Analysis saved to: {filepath}")
        return filepath
