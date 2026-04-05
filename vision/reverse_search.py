"""
Reverse Image Search

User uploads photo → Find product on Vinted

Methods:
1. Google Lens API (best results)
2. Vinted's own image search
3. CLIP-based similarity search in our database
"""

from __future__ import annotations

import logging
from typing import List, Optional, Dict
from pathlib import Path
import base64
import requests

from config import get_settings

logger = logging.getLogger(__name__)


class ReverseImageSearch:
    """Search for products by uploading an image."""

    def __init__(self):
        self.cfg = get_settings()

    async def search_by_image(
        self,
        image_path: str,
        source: str = "auto"
    ) -> List[Dict]:
        """
        Search for products using an image.

        Args:
            image_path: Path to image file or URL
            source: 'auto', 'google_lens', 'vinted', 'clip_db'

        Returns:
            List of matching products with scores
        """
        if source == "auto":
            # Try methods in order of effectiveness
            results = await self._search_google_lens(image_path)
            if not results:
                results = await self._search_vinted_image(image_path)
            if not results:
                results = await self._search_clip_database(image_path)
            return results

        elif source == "google_lens":
            return await self._search_google_lens(image_path)
        elif source == "vinted":
            return await self._search_vinted_image(image_path)
        elif source == "clip_db":
            return await self._search_clip_database(image_path)
        else:
            raise ValueError(f"Unknown source: {source}")

    async def _search_google_lens(self, image_path: str) -> List[Dict]:
        """
        Search using Google Lens API.

        Best for finding exact products and similar items.
        """
        try:
            # Read image
            if image_path.startswith('http'):
                response = requests.get(image_path)
                image_data = response.content
            else:
                with open(image_path, 'rb') as f:
                    image_data = f.read()

            # Encode as base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')

            # Google Lens API call (unofficial - requires SerpAPI or similar)
            # For production, use official Google Vision API
            google_lens_endpoint = getattr(
                self.cfg,
                'google_lens_api',
                'https://serpapi.com/search'
            )
            api_key = getattr(self.cfg, 'serpapi_key', '')

            if not api_key:
                logger.warning("Google Lens API key not configured")
                return []

            params = {
                'engine': 'google_lens',
                'image': image_b64,
                'api_key': api_key
            }

            response = requests.get(google_lens_endpoint, params=params, timeout=30)

            if response.ok:
                data = response.json()
                results = []

                # Extract visual matches
                visual_matches = data.get('visual_matches', [])
                for match in visual_matches[:10]:
                    results.append({
                        'title': match.get('title'),
                        'link': match.get('link'),
                        'source_name': match.get('source'),
                        'thumbnail': match.get('thumbnail'),
                        'price': self._extract_price(match),
                        'similarity': 0.9,  # High confidence from Lens
                        'method': 'google_lens'
                    })

                return results

        except Exception as e:
            logger.error(f"Google Lens search failed: {e}")

        return []

    async def _search_vinted_image(self, image_path: str) -> List[Dict]:
        """
        Search using Vinted's built-in image search.

        Vinted has /catalog/image_search endpoint.
        """
        try:
            # Upload image to Vinted
            if image_path.startswith('http'):
                image_url = image_path
            else:
                # Would need to upload to temporary hosting
                # For now, skip this method if local file
                logger.warning("Vinted image search requires uploaded image URL")
                return []

            # Vinted image search endpoint
            vinted_endpoint = f"{self.cfg.vinted_base_url}/api/v2/catalog/image_search"

            headers = {}
            if self.cfg.vinted_session_cookie:
                headers['Authorization'] = f'Bearer {self.cfg.vinted_session_cookie}'

            data = {
                'image_url': image_url,
                'per_page': 20
            }

            response = requests.post(
                vinted_endpoint,
                json=data,
                headers=headers,
                timeout=30
            )

            if response.ok:
                result_data = response.json()
                items = result_data.get('items', [])

                results = []
                for item in items:
                    results.append({
                        'title': item.get('title'),
                        'link': f"{self.cfg.vinted_base_url}/items/{item['id']}",
                        'price': item.get('price'),
                        'currency': item.get('currency', 'EUR'),
                        'brand': item.get('brand', {}).get('title'),
                        'image': item.get('photos', [{}])[0].get('url'),
                        'similarity': item.get('score', 0.7),
                        'method': 'vinted_search'
                    })

                return results

        except Exception as e:
            logger.error(f"Vinted image search failed: {e}")

        return []

    async def _search_clip_database(self, image_path: str) -> List[Dict]:
        """
        Search our local database using CLIP embeddings.

        Uses FashionCLIP to find visually similar items.
        """
        try:
            from embedder import FashionCLIPEmbedder
            from storage import QdrantStore
            from PIL import Image
            import requests
            import io

            # Load image
            if image_path.startswith('http'):
                response = requests.get(image_path)
                img = Image.open(io.BytesIO(response.content))
            else:
                img = Image.open(image_path)

            # Generate embedding
            embedder = FashionCLIPEmbedder()
            embedding = embedder.encode_image(img)

            # Search Qdrant
            qdrant = QdrantStore()
            similar_items = qdrant.search_similar(
                query_vector=embedding.tolist(),
                limit=20
            )

            # Convert to results format
            results = []
            for item, score in similar_items:
                results.append({
                    'title': item.get('title'),
                    'link': item.get('listing_url'),
                    'price': item.get('price'),
                    'currency': item.get('currency', 'EUR'),
                    'brand': item.get('brand'),
                    'image': item.get('image_url'),
                    'similarity': score,
                    'method': 'clip_database'
                })

            return results

        except Exception as e:
            logger.error(f"CLIP database search failed: {e}")

        return []

    def _extract_price(self, match: Dict) -> Optional[float]:
        """Extract price from Google Lens match."""
        # Try to find price in title or snippet
        text = f"{match.get('title', '')} {match.get('snippet', '')}"

        import re
        # Match prices like €50, $50.99, 50€, etc.
        price_patterns = [
            r'€\s*(\d+(?:[.,]\d{2})?)',
            r'(\d+(?:[.,]\d{2})?)\s*€',
            r'\$\s*(\d+(?:[.,]\d{2})?)',
            r'(\d+(?:[.,]\d{2})?)\s*EUR',
        ]

        for pattern in price_patterns:
            match_obj = re.search(pattern, text)
            if match_obj:
                try:
                    return float(match_obj.group(1).replace(',', '.'))
                except:
                    pass

        return None


# ==================== Enhanced Vinted Search ====================

class VintedSearchEnhancer:
    """
    Enhance Vinted search results using image analysis.

    When user uploads image:
    1. Use Lens to identify brand/model
    2. Extract key attributes (color, style)
    3. Build optimized search query
    4. Search Vinted with specific terms
    """

    def __init__(self):
        self.reverse_search = ReverseImageSearch()

    async def search_from_image(self, image_path: str) -> Dict:
        """
        Complete workflow: Image → Product identification → Vinted search.

        Returns:
            {
                'identified_product': {...},
                'search_query': "Nike Air Max 90 white blue",
                'vinted_results': [...]
            }
        """
        # Step 1: Identify product via Lens
        lens_results = await self.reverse_search._search_google_lens(image_path)

        if not lens_results:
            return {'error': 'Could not identify product from image'}

        # Step 2: Extract attributes from top match
        top_match = lens_results[0]
        search_terms = self._extract_search_terms(top_match)

        # Step 3: Search Vinted
        from collector import VintedEnhancedCollector
        collector = VintedEnhancedCollector()

        search_query = ' '.join(search_terms)
        vinted_results = await collector.collect(query=search_query, pages=2)

        return {
            'identified_product': top_match,
            'search_query': search_query,
            'search_terms': search_terms,
            'vinted_results': vinted_results.items,
            'total_found': len(vinted_results.items)
        }

    def _extract_search_terms(self, product_info: Dict) -> List[str]:
        """Extract search terms from identified product."""
        title = product_info.get('title', '')

        # Common patterns to extract
        import re

        terms = []

        # Extract brand names (common fashion brands)
        brands = [
            'Nike', 'Adidas', 'Puma', 'New Balance', 'Vans',
            'Gucci', 'Prada', 'Louis Vuitton', 'Chanel',
            'Tommy Hilfiger', 'Calvin Klein', 'Ralph Lauren',
            'The North Face', 'Patagonia', 'Columbia'
        ]

        for brand in brands:
            if brand.lower() in title.lower():
                terms.append(brand)
                break

        # Extract model/product name
        # Remove common words
        stop_words = ['the', 'and', 'or', 'for', 'with', 'in', 'on', 'at']
        words = title.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # Take first 4-5 meaningful words
        terms.extend(keywords[:5])

        return terms
