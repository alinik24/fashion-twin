"""Google Lens Product Enrichment

Uses Google Lens to enrich incomplete product data by:
1. Searching product images via Google Lens
2. Finding original manufacturer/retailer pages
3. Extracting detailed product information
4. Verifying authenticity
5. Getting original retail prices

This solves the problem of incomplete second-hand listings.

Uses: https://github.com/dimdenGD/chrome-lens-ocr

Installation:
    npm install -g chrome-lens-ocr
    # Or: pip install chrome-lens-ocr (Python wrapper)

Usage:
    from pipeline.enrichers import GoogleLensEnricher

    enricher = GoogleLensEnricher()
    enriched_data = enricher.enrich_item(item_id="vinted_123", image_url="...")
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class GoogleLensEnricher:
    """
    Enrich product data using Google Lens visual search.

    Pipeline:
    1. Take product image from listing
    2. Search via Google Lens
    3. Find original product pages (brand websites, retailers)
    4. Extract detailed information
    5. Store in product_metadata table
    """

    def __init__(self):
        self.chrome_lens_path = "chrome-lens-ocr"  # npm global install
        self.http_client = httpx.Client(timeout=30.0)

    def enrich_item(
        self,
        item_id: str,
        image_url: str,
        current_title: str = None,
        current_price: float = None
    ) -> Dict:
        """
        Enrich item with Google Lens search results.

        Args:
            item_id: Item identifier
            image_url: URL of product image
            current_title: Current listing title (for comparison)
            current_price: Current price (to calculate discount)

        Returns:
            Enriched product data dict
        """
        logger.info(f"Enriching item {item_id} with Google Lens...")

        # Step 1: Search via Google Lens
        lens_results = self._search_google_lens(image_url)

        if not lens_results:
            logger.warning(f"No Lens results for item {item_id}")
            return {}

        # Step 2: Extract product information from results
        enriched_data = self._extract_product_info(lens_results)

        # Step 3: Find original product pages
        original_pages = self._find_original_pages(lens_results)

        # Step 4: Scrape detailed information from manufacturer pages
        if original_pages:
            detailed_info = self._scrape_product_details(original_pages[0])
            enriched_data.update(detailed_info)

        # Step 5: Compare with current listing (detect issues)
        enriched_data["comparison"] = self._compare_with_listing(
            enriched_data,
            current_title,
            current_price
        )

        # Step 6: Authenticity check
        enriched_data["authenticity"] = self._check_authenticity(
            enriched_data,
            lens_results
        )

        logger.info(f"✓ Enriched item {item_id}")
        return enriched_data

    def _search_google_lens(self, image_url: str) -> Dict:
        """
        Search image via Google Lens using chrome-lens-ocr.

        Returns:
            Lens search results with visual matches, text, links
        """
        logger.info(f"Searching Google Lens for image: {image_url}")

        try:
            # Call chrome-lens-ocr CLI
            result = subprocess.run(
                [self.chrome_lens_path, image_url, "--json"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )

            lens_data = json.loads(result.stdout)

            logger.info(f"  Found {len(lens_data.get('visual_matches', []))} visual matches")
            logger.info(f"  Found {len(lens_data.get('text_results', []))} text results")

            return lens_data

        except subprocess.CalledProcessError as e:
            logger.error(f"chrome-lens-ocr failed: {e.stderr}")
            return {}

        except FileNotFoundError:
            logger.error(
                "chrome-lens-ocr not found. Install: npm install -g chrome-lens-ocr"
            )
            return {}

        except Exception as e:
            logger.error(f"Lens search failed: {e}")
            return {}

    def _extract_product_info(self, lens_results: Dict) -> Dict:
        """
        Extract product information from Lens results.

        Lens provides:
        - visual_matches: Similar products found
        - text_results: Text detected in image (brand, model, etc.)
        - pages_with_matching_images: Original product pages
        """
        info = {
            "lens_title": None,
            "lens_brand": None,
            "lens_model": None,
            "lens_category": None,
            "lens_original_price": None,
            "lens_currency": "GBP",
            "lens_material": None,
            "lens_colors": [],
            "lens_features": [],
        }

        # Extract from visual matches
        visual_matches = lens_results.get("visual_matches", [])
        if visual_matches:
            # First match is usually the most relevant
            best_match = visual_matches[0]

            info["lens_title"] = best_match.get("title")
            info["lens_source_url"] = best_match.get("link")

            # Extract brand from title
            info["lens_brand"] = self._extract_brand(best_match.get("title", ""))

            # Extract price if available
            price_text = best_match.get("price")
            if price_text:
                info["lens_original_price"] = self._parse_price(price_text)

        # Extract text from image (brand logos, tags, etc.)
        text_results = lens_results.get("text_results", [])
        if text_results:
            detected_text = " ".join([t.get("text", "") for t in text_results])

            # Try to find brand in detected text
            if not info["lens_brand"]:
                info["lens_brand"] = self._extract_brand(detected_text)

            # Try to find model number
            model_match = re.search(r'\b[A-Z0-9]{5,}\b', detected_text)
            if model_match:
                info["lens_model"] = model_match.group(0)

        # Extract from page matches
        pages = lens_results.get("pages_with_matching_images", [])
        if pages:
            # Look for official brand pages
            for page in pages:
                url = page.get("url", "").lower()

                # Check if it's an official brand page
                if info["lens_brand"] and info["lens_brand"].lower() in url:
                    info["official_page_url"] = page.get("url")
                    break

        return info

    def _find_original_pages(self, lens_results: Dict) -> List[str]:
        """
        Find original manufacturer/retailer pages from Lens results.

        Prioritizes:
        1. Brand official websites
        2. Major retailers (Selfridges, Harrods, Net-a-Porter, etc.)
        3. Luxury marketplaces (Farfetch, Matches, etc.)
        """
        pages = []

        # Get all pages with matching images
        all_pages = lens_results.get("pages_with_matching_images", [])

        # Priority domains
        priority_domains = [
            # Luxury retailers
            "selfridges.com",
            "harrods.com",
            "net-a-porter.com",
            "mrporter.com",
            "matchesfashion.com",
            "farfetch.com",
            "ssense.com",
            "brownsfashion.com",

            # Brand official sites
            "gucci.com",
            "prada.com",
            "chanel.com",
            "hermes.com",
            "louisvuitton.com",
            "dior.com",
            "celine.com",
            "balenciaga.com",

            # Other retailers
            "nordstrom.com",
            "bloomingdales.com",
            "saksfifthavenue.com"
        ]

        # Sort pages by priority
        priority_pages = []
        other_pages = []

        for page in all_pages:
            url = page.get("url", "").lower()

            if any(domain in url for domain in priority_domains):
                priority_pages.append(page.get("url"))
            else:
                other_pages.append(page.get("url"))

        pages = priority_pages + other_pages[:5]  # Top 5 other pages

        logger.info(f"  Found {len(pages)} original pages")
        return pages

    def _scrape_product_details(self, product_url: str) -> Dict:
        """
        Scrape detailed product information from manufacturer page.

        Extracts:
        - Official product name
        - Brand
        - Model/SKU
        - Original retail price
        - Materials
        - Colors
        - Features/description
        - Product specifications
        """
        logger.info(f"Scraping product details from {product_url}")

        details = {}

        try:
            response = self.http_client.get(product_url)
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract product name (multiple selectors for different sites)
            name_selectors = [
                'h1.product-title',
                'h1[itemprop="name"]',
                'h1.ProductMeta__Title',
                'h1.product-name',
                '.product-title h1',
                'h1'
            ]

            for selector in name_selectors:
                name_elem = soup.select_one(selector)
                if name_elem:
                    details["official_name"] = name_elem.get_text(strip=True)
                    break

            # Extract price
            price_selectors = [
                '[itemprop="price"]',
                '.price',
                '.product-price',
                '[data-testid="product-price"]'
            ]

            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    details["official_price"] = self._parse_price(price_text)
                    break

            # Extract description/materials
            desc_selectors = [
                '[itemprop="description"]',
                '.product-description',
                '.ProductMeta__Description'
            ]

            for selector in desc_selectors:
                desc_elem = soup.select_one(selector)
                if desc_elem:
                    description = desc_elem.get_text(strip=True)
                    details["description"] = description

                    # Extract materials from description
                    details["materials"] = self._extract_materials(description)
                    break

            # Extract specifications (materials, dimensions, etc.)
            specs = self._extract_specifications(soup)
            if specs:
                details["specifications"] = specs

            logger.info(f"  ✓ Scraped product details")

        except Exception as e:
            logger.warning(f"Failed to scrape {product_url}: {e}")

        return details

    def _extract_materials(self, text: str) -> List[str]:
        """Extract material information from text."""
        materials = []

        # Common materials
        material_keywords = [
            "leather", "calf leather", "calfskin", "suede",
            "canvas", "cotton", "linen", "silk", "wool",
            "cashmere", "nylon", "polyester", "denim",
            "patent leather", "crocodile", "python", "exotic leather"
        ]

        text_lower = text.lower()
        for material in material_keywords:
            if material in text_lower:
                materials.append(material.title())

        return list(set(materials))

    def _extract_specifications(self, soup: BeautifulSoup) -> Dict:
        """Extract product specifications from page."""
        specs = {}

        # Look for specification tables/lists
        spec_selectors = [
            '.product-specs',
            '.specifications',
            '[data-testid="specifications"]'
        ]

        for selector in spec_selectors:
            spec_container = soup.select_one(selector)
            if spec_container:
                # Extract key-value pairs
                items = spec_container.find_all(['li', 'tr', 'div'])
                for item in items:
                    text = item.get_text(strip=True)
                    if ":" in text:
                        key, value = text.split(":", 1)
                        specs[key.strip()] = value.strip()

        return specs

    def _extract_brand(self, text: str) -> Optional[str]:
        """Extract brand name from text."""
        # List of known luxury brands
        brands = [
            "Gucci", "Prada", "Chanel", "Hermès", "Hermes", "Louis Vuitton",
            "Dior", "Celine", "Balenciaga", "Bottega Veneta", "Fendi",
            "Givenchy", "Saint Laurent", "YSL", "Valentino", "Burberry",
            "Loewe", "Versace", "Dolce & Gabbana", "Dolce&Gabbana",
            "Tom Ford", "Alexander McQueen", "Stella McCartney"
        ]

        text_upper = text.upper()
        for brand in brands:
            if brand.upper() in text_upper:
                return brand

        return None

    def _parse_price(self, price_text: str) -> float:
        """Parse price from text."""
        # Remove currency symbols and commas
        cleaned = re.sub(r'[£$€,]', '', price_text)

        # Extract number
        match = re.search(r'(\d+(?:\.\d{2})?)', cleaned)
        if match:
            return float(match.group(1))

        return 0.0

    def _compare_with_listing(
        self,
        enriched_data: Dict,
        current_title: str,
        current_price: float
    ) -> Dict:
        """
        Compare enriched data with current listing.

        Detects:
        - Incorrect title (seller lying?)
        - Huge discount (possible fake?)
        - Missing information
        """
        comparison = {
            "title_match": False,
            "brand_match": False,
            "price_accuracy": None,
            "discount_percentage": None,
            "missing_fields": []
        }

        # Check title match
        if current_title and enriched_data.get("lens_title"):
            lens_title = enriched_data["lens_title"].lower()
            current_title_lower = current_title.lower()

            # Simple word overlap
            lens_words = set(lens_title.split())
            current_words = set(current_title_lower.split())

            overlap = len(lens_words & current_words) / len(lens_words) if lens_words else 0
            comparison["title_match"] = overlap > 0.5

        # Check brand match
        if current_title and enriched_data.get("lens_brand"):
            comparison["brand_match"] = enriched_data["lens_brand"].lower() in current_title.lower()

        # Check price accuracy (calculate discount)
        if current_price and enriched_data.get("lens_original_price"):
            original = enriched_data["lens_original_price"]
            discount_pct = ((original - current_price) / original) * 100

            comparison["discount_percentage"] = round(discount_pct, 1)

            # Flag suspiciously high discounts
            if discount_pct > 80:
                comparison["warning"] = "Very high discount - possible fake?"
            elif discount_pct > 60:
                comparison["quality"] = "excellent_deal"
            elif discount_pct > 40:
                comparison["quality"] = "good_deal"

        # Check for missing fields
        required_fields = ["lens_brand", "lens_title", "lens_original_price"]
        for field in required_fields:
            if not enriched_data.get(field):
                comparison["missing_fields"].append(field)

        return comparison

    def _check_authenticity(self, enriched_data: Dict, lens_results: Dict) -> Dict:
        """
        Check authenticity based on Lens results.

        Red flags:
        - No exact visual matches found
        - Price too low compared to retail
        - No official retailer pages found
        - Detected text doesn't match known brand fonts/logos
        """
        authenticity = {
            "score": 100,  # 0-100
            "confidence": "high",  # high, medium, low
            "red_flags": []
        }

        # Check if exact visual matches exist
        visual_matches = lens_results.get("visual_matches", [])
        if not visual_matches:
            authenticity["score"] -= 30
            authenticity["red_flags"].append("No visual matches found")

        # Check if official pages found
        pages = lens_results.get("pages_with_matching_images", [])
        has_official = any(
            enriched_data.get("lens_brand", "").lower() in page.get("url", "").lower()
            for page in pages
        )

        if not has_official:
            authenticity["score"] -= 20
            authenticity["red_flags"].append("No official brand pages found")

        # Check price discount
        comparison = enriched_data.get("comparison", {})
        discount = comparison.get("discount_percentage", 0)

        if discount > 80:
            authenticity["score"] -= 40
            authenticity["red_flags"].append(f"Suspiciously high discount ({discount}%)")

        # Determine confidence
        if authenticity["score"] >= 80:
            authenticity["confidence"] = "high"
        elif authenticity["score"] >= 60:
            authenticity["confidence"] = "medium"
        else:
            authenticity["confidence"] = "low"

        return authenticity

    def store(self, item_id: str, enriched_data: Dict):
        """
        Store enriched data in product_metadata table.

        Args:
            item_id: Item identifier
            enriched_data: Enriched product data
        """
        from storage.postgres import PostgresStore

        logger.info(f"Storing enriched data for item {item_id}")

        with PostgresStore() as db:
            with db._cursor() as cur:
                # Insert or update product_metadata
                cur.execute("""
                    INSERT INTO product_metadata (
                        item_id,
                        lens_title,
                        lens_brand,
                        lens_model,
                        lens_original_price,
                        lens_currency,
                        official_name,
                        official_price,
                        materials,
                        description,
                        specifications,
                        authenticity_score,
                        authenticity_confidence,
                        authenticity_red_flags,
                        discount_percentage,
                        source_urls,
                        enriched_at
                    ) VALUES (
                        (SELECT id FROM items WHERE item_id = %s),
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (item_id) DO UPDATE SET
                        lens_title = EXCLUDED.lens_title,
                        lens_brand = EXCLUDED.lens_brand,
                        lens_model = EXCLUDED.lens_model,
                        lens_original_price = EXCLUDED.lens_original_price,
                        official_name = EXCLUDED.official_name,
                        official_price = EXCLUDED.official_price,
                        materials = EXCLUDED.materials,
                        description = EXCLUDED.description,
                        specifications = EXCLUDED.specifications,
                        authenticity_score = EXCLUDED.authenticity_score,
                        authenticity_confidence = EXCLUDED.authenticity_confidence,
                        authenticity_red_flags = EXCLUDED.authenticity_red_flags,
                        discount_percentage = EXCLUDED.discount_percentage,
                        source_urls = EXCLUDED.source_urls,
                        enriched_at = EXCLUDED.enriched_at
                """, (
                    item_id,
                    enriched_data.get("lens_title"),
                    enriched_data.get("lens_brand"),
                    enriched_data.get("lens_model"),
                    enriched_data.get("lens_original_price"),
                    enriched_data.get("lens_currency", "GBP"),
                    enriched_data.get("official_name"),
                    enriched_data.get("official_price"),
                    json.dumps(enriched_data.get("materials", [])),
                    enriched_data.get("description"),
                    json.dumps(enriched_data.get("specifications", {})),
                    enriched_data.get("authenticity", {}).get("score"),
                    enriched_data.get("authenticity", {}).get("confidence"),
                    json.dumps(enriched_data.get("authenticity", {}).get("red_flags", [])),
                    enriched_data.get("comparison", {}).get("discount_percentage"),
                    json.dumps([enriched_data.get("lens_source_url"),
                               enriched_data.get("official_page_url")]),
                    datetime.now()
                ))

        logger.info("✓ Enriched data stored")


def batch_enrich_items(item_ids: List[str], max_workers: int = 5):
    """
    Enrich multiple items in parallel.

    Args:
        item_ids: List of item IDs to enrich
        max_workers: Number of parallel workers
    """
    import concurrent.futures
    from storage.postgres import PostgresStore

    enricher = GoogleLensEnricher()

    def enrich_one(item_id: str):
        """Enrich single item."""
        # Get item data
        with PostgresStore() as db:
            with db._cursor() as cur:
                cur.execute("""
                    SELECT image_url, title, price
                    FROM items
                    WHERE item_id = %s
                """, (item_id,))

                result = cur.fetchone()
                if not result:
                    return None

                image_url, title, price = result

        # Enrich
        enriched_data = enricher.enrich_item(
            item_id=item_id,
            image_url=image_url,
            current_title=title,
            current_price=float(price) if price else None
        )

        # Store
        if enriched_data:
            enricher.store(item_id, enriched_data)

        return enriched_data

    # Process in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(enrich_one, item_ids))

    return results
