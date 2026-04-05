"""
Photo Quality Scorer

Compares product photos against reference (new) images and assigns condition score.

Supports multiple backends:
1. CLIP-based similarity (open-source, local)
2. Custom CNN model (trainable)
3. VLM APIs (GPT-4V, Claude Vision, LLaVA)
4. Placeholder for future models

Configuration via .env:
    PHOTO_SCORER_BACKEND=clip|cnn|vlm|placeholder
    VLM_ENDPOINT=<url>
    VLM_API_KEY=<key>
"""

from __future__ import annotations

import logging
from typing import List, Optional, Dict
from pathlib import Path
from dataclasses import dataclass
import requests
from PIL import Image
import io

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PhotoScore:
    """Photo condition score result."""
    score: float  # 0-100 (100 = like new, 0 = very worn)
    confidence: float  # 0-1
    backend: str  # Which model was used
    details: Optional[Dict] = None  # Additional details


class PhotoScorer:
    """
    Score product photos against reference images.

    Returns condition score (0-100) based on visual similarity to new item.
    """

    def __init__(self):
        self.cfg = get_settings()
        self.backend = getattr(self.cfg, 'photo_scorer_backend', 'placeholder')

        # Initialize based on backend
        if self.backend == 'clip':
            self._init_clip()
        elif self.backend == 'cnn':
            self._init_cnn()
        elif self.backend == 'vlm':
            self._init_vlm()
        else:
            logger.info("Using placeholder photo scorer")

    def score_photos(
        self,
        product_images: List[str],
        reference_images: Optional[List[str]] = None
    ) -> PhotoScore:
        """
        Score product photos.

        Args:
            product_images: URLs of product photos to score
            reference_images: URLs of reference (new) product photos from Lens

        Returns:
            PhotoScore with 0-100 score (100 = like new)
        """
        if self.backend == 'clip':
            return self._score_with_clip(product_images, reference_images)
        elif self.backend == 'cnn':
            return self._score_with_cnn(product_images, reference_images)
        elif self.backend == 'vlm':
            return self._score_with_vlm(product_images, reference_images)
        else:
            return self._score_placeholder(product_images, reference_images)

    # ==================== CLIP Backend (Open Source, Local) ====================

    def _init_clip(self):
        """Initialize CLIP model for similarity scoring."""
        try:
            import torch
            from transformers import CLIPProcessor, CLIPModel

            self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
            self.clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.clip_model.to(self.device)
            logger.info(f"CLIP model loaded on {self.device}")
        except Exception as e:
            logger.error(f"Failed to load CLIP: {e}")
            self.backend = 'placeholder'

    def _score_with_clip(
        self,
        product_images: List[str],
        reference_images: Optional[List[str]]
    ) -> PhotoScore:
        """Score using CLIP similarity."""
        try:
            import torch

            # Download images
            product_imgs = [self._download_image(url) for url in product_images[:3]]
            product_imgs = [img for img in product_imgs if img is not None]

            if not product_imgs:
                return PhotoScore(score=50.0, confidence=0.0, backend='clip')

            if reference_images:
                ref_imgs = [self._download_image(url) for url in reference_images[:3]]
                ref_imgs = [img for img in ref_imgs if img is not None]

                if ref_imgs:
                    # Compare product vs reference
                    scores = []
                    for prod_img in product_imgs:
                        for ref_img in ref_imgs:
                            inputs = self.clip_processor(
                                images=[prod_img, ref_img],
                                return_tensors="pt"
                            ).to(self.device)

                            with torch.no_grad():
                                image_features = self.clip_model.get_image_features(**inputs)
                                # Cosine similarity
                                similarity = torch.nn.functional.cosine_similarity(
                                    image_features[0:1],
                                    image_features[1:2]
                                ).item()
                                scores.append(similarity)

                    # Convert similarity to condition score
                    # similarity 0.8-1.0 = like new (score 80-100)
                    # similarity 0.6-0.8 = good (score 60-80)
                    # similarity <0.6 = worn (score <60)
                    avg_similarity = sum(scores) / len(scores)
                    score = max(0, min(100, avg_similarity * 100))
                    confidence = 0.8

                    return PhotoScore(
                        score=score,
                        confidence=confidence,
                        backend='clip',
                        details={'similarity': avg_similarity}
                    )

            # No reference images - assess based on quality heuristics
            # Use CLIP to detect wear indicators
            wear_prompts = [
                "heavily worn item",
                "damaged product",
                "stained fabric",
                "pristine new item",
                "like new condition"
            ]

            inputs = self.clip_processor(
                text=wear_prompts,
                images=product_imgs,
                return_tensors="pt",
                padding=True
            ).to(self.device)

            with torch.no_grad():
                outputs = self.clip_model(**inputs)
                logits_per_image = outputs.logits_per_image
                probs = logits_per_image.softmax(dim=1)

            # Higher prob for "pristine" and "like new" = higher score
            avg_probs = probs.mean(dim=0).cpu().numpy()
            wear_score = avg_probs[0] * 20 + avg_probs[1] * 30 + avg_probs[2] * 40  # worn indicators
            new_score = avg_probs[3] * 50 + avg_probs[4] * 50  # new indicators

            score = new_score / (new_score + wear_score) * 100

            return PhotoScore(
                score=score,
                confidence=0.6,
                backend='clip',
                details={'wear_score': wear_score, 'new_score': new_score}
            )

        except Exception as e:
            logger.error(f"CLIP scoring failed: {e}")
            return PhotoScore(score=50.0, confidence=0.0, backend='clip_failed')

    # ==================== CNN Backend (Custom Trainable Model) ====================

    def _init_cnn(self):
        """Initialize custom CNN model."""
        # Placeholder for custom CNN
        # Will load trained model from artefacts/photo_scorer/
        logger.info("CNN backend not yet implemented")
        self.backend = 'placeholder'

    def _score_with_cnn(
        self,
        product_images: List[str],
        reference_images: Optional[List[str]]
    ) -> PhotoScore:
        """Score using custom CNN."""
        # TODO: Implement custom CNN
        # Model architecture:
        # - Input: Product image + Reference image
        # - Output: Condition score (0-100)
        # - Training data: Vinted items with known conditions
        return PhotoScore(score=50.0, confidence=0.0, backend='cnn_not_implemented')

    # ==================== VLM Backend (API-based Vision Models) ====================

    def _init_vlm(self):
        """Initialize VLM API."""
        self.vlm_endpoint = getattr(self.cfg, 'vlm_endpoint', '')
        self.vlm_api_key = getattr(self.cfg, 'vlm_api_key', '')

        if not self.vlm_endpoint:
            logger.warning("VLM endpoint not configured")
            self.backend = 'placeholder'

    def _score_with_vlm(
        self,
        product_images: List[str],
        reference_images: Optional[List[str]]
    ) -> PhotoScore:
        """Score using VLM API (GPT-4V, Claude, LLaVA)."""
        try:
            # Prepare prompt
            if reference_images:
                prompt = f"""Compare these product photos to the reference (new) product images.

Product images: {', '.join(product_images[:3])}
Reference (new): {', '.join(reference_images[:3])}

Score the product condition on a scale of 0-100:
- 100 = Like new, identical to reference
- 80-99 = Very good, minimal wear
- 60-79 = Good, some visible wear
- 40-59 = Satisfactory, noticeable wear
- 20-39 = Poor, significant damage
- 0-19 = Very poor, heavily worn

Return only a JSON object:
{{
    "score": 85,
    "confidence": 0.9,
    "reasoning": "brief explanation"
}}"""
            else:
                prompt = f"""Assess the condition of this product based on the photos.

Images: {', '.join(product_images[:3])}

Score on 0-100 scale (100 = like new, 0 = very worn).

Return JSON:
{{
    "score": 75,
    "confidence": 0.8,
    "reasoning": "brief explanation"
}}"""

            # Call VLM API
            response = requests.post(
                self.vlm_endpoint,
                headers={'Authorization': f'Bearer {self.vlm_api_key}'},
                json={'prompt': prompt},
                timeout=30
            )

            if response.ok:
                data = response.json()
                return PhotoScore(
                    score=data.get('score', 50.0),
                    confidence=data.get('confidence', 0.5),
                    backend='vlm',
                    details={'reasoning': data.get('reasoning')}
                )

        except Exception as e:
            logger.error(f"VLM scoring failed: {e}")

        return PhotoScore(score=50.0, confidence=0.0, backend='vlm_failed')

    # ==================== Placeholder Backend ====================

    def _score_placeholder(
        self,
        product_images: List[str],
        reference_images: Optional[List[str]]
    ) -> PhotoScore:
        """
        Placeholder scoring based on simple heuristics.

        To be replaced with actual model.
        """
        # Simple heuristic: assume average condition
        score = 70.0  # Default to "good" condition

        # If we have reference images, assume product is 80-90% as good
        if reference_images:
            score = 85.0

        return PhotoScore(
            score=score,
            confidence=0.3,
            backend='placeholder',
            details={'note': 'Using placeholder scorer - configure real model'}
        )

    # ==================== Helper Methods ====================

    def _download_image(self, url: str) -> Optional[Image.Image]:
        """Download image from URL."""
        try:
            response = requests.get(url, timeout=10)
            if response.ok:
                return Image.open(io.BytesIO(response.content)).convert('RGB')
        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
        return None


# ==================== Training Data Generator ====================

class PhotoScorerTrainer:
    """
    Generate training data for custom photo scorer model.

    Collects Vinted items with known conditions to train CNN.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def collect_training_data(self, num_items: int = 1000):
        """
        Collect training data from Vinted.

        For each item:
        - Download product photos
        - Record stated condition
        - Find reference (new) product via Lens
        - Label: (product_photo, reference_photo, condition_score)
        """
        # TODO: Implement
        # 1. Query database for items with conditions
        # 2. Download their photos
        # 3. Use Lens to find new product
        # 4. Save as training dataset
        pass

    def prepare_dataset(self):
        """
        Prepare dataset for training.

        Format:
        - train/new_with_tags/*.jpg (score 95-100)
        - train/new_without_tags/*.jpg (score 90-95)
        - train/very_good/*.jpg (score 80-90)
        - train/good/*.jpg (score 65-80)
        - train/satisfactory/*.jpg (score 50-65)
        - train/poor/*.jpg (score 0-50)
        """
        pass


# ==================== Model Configuration ====================

def get_photo_scorer() -> PhotoScorer:
    """Get configured photo scorer instance."""
    return PhotoScorer()
