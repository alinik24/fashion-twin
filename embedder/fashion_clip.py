"""FashionCLIP wrapper — encode images and text to 512-d vectors.

Model: patrickjohncyh/fashion-clip (HuggingFace)
Paper: "Contrastive Language-Image Pre-training for Fashion"
Benchmarks: best zero-shot on FashionGen, DeepFashion-MultiModal
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Optional, Union
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from config import get_settings

logger = logging.getLogger(__name__)

ImageInput = Union[str, Path, bytes, Image.Image]


class FashionCLIPEmbedder:
    """Thin wrapper around the fashion-clip library."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._model_name = model_name or get_settings().embedding_model
        self._model = None
        self._dim = get_settings().embedding_dim

    # ── Lazy loading ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from fashion_clip.fashion_clip import FashionCLIP
            self._model = FashionCLIP(self._model_name)
            logger.info("Loaded FashionCLIP model: %s", self._model_name)
        except ImportError as exc:
            raise RuntimeError(
                "fashion-clip not installed. Run: pip install fashion-clip"
            ) from exc

    @property
    def model(self):
        self._load()
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    # ── Encoding ─────────────────────────────────────────────────────────────

    def encode_images(
        self,
        images: list[ImageInput],
        batch_size: Optional[int] = None,
    ) -> np.ndarray:
        """
        Encode a list of images to L2-normalised vectors (N x dim).

        Args:
            images: list of PIL Images, file paths, URLs (str), or raw bytes
            batch_size: processing batch size (defaults to settings value)

        Returns:
            np.ndarray of shape (N, 512)
        """
        batch_size = batch_size or get_settings().embedding_batch_size
        pil_images = [self._load_image(img) for img in images]
        # Filter out load failures (None entries)
        valid: list[tuple[int, Image.Image]] = [
            (i, img) for i, img in enumerate(pil_images) if img is not None
        ]
        if not valid:
            return np.zeros((len(images), self._dim), dtype=np.float32)

        idx, imgs = zip(*valid)
        embeddings_valid = self.model.encode_images(list(imgs), batch_size=batch_size)
        # Re-insert zeros for failed images
        out = np.zeros((len(images), self._dim), dtype=np.float32)
        for pos, row_idx in enumerate(idx):
            out[row_idx] = embeddings_valid[pos]
        return out

    def encode_texts(
        self,
        texts: list[str],
        batch_size: Optional[int] = None,
    ) -> np.ndarray:
        """
        Encode a list of text strings to L2-normalised vectors (N x dim).
        """
        batch_size = batch_size or get_settings().embedding_batch_size
        return self.model.encode_text(texts, batch_size=batch_size)

    def encode_image(self, image: ImageInput) -> np.ndarray:
        """Encode a single image. Returns 1-d array of shape (dim,)."""
        result = self.encode_images([image])
        return result[0]

    def encode_text(self, text: str) -> np.ndarray:
        """Encode a single text string. Returns 1-d array of shape (dim,)."""
        result = self.encode_texts([text])
        return result[0]

    def encode_item(self, title: Optional[str], image: Optional[ImageInput]) -> np.ndarray:
        """
        Fuse text + image embeddings for a fashion item.

        Strategy: average(image_vec, text_vec) then re-normalise.
        If only one modality is available, return that alone.
        """
        vecs = []

        if image is not None:
            try:
                vecs.append(self.encode_image(image))
            except Exception as exc:
                logger.debug("Image encode failed: %s", exc)

        if title:
            try:
                vecs.append(self.encode_text(title))
            except Exception as exc:
                logger.debug("Text encode failed: %s", exc)

        if not vecs:
            return np.zeros(self._dim, dtype=np.float32)

        fused = np.mean(vecs, axis=0)
        norm = np.linalg.norm(fused)
        if norm > 0:
            fused = fused / norm
        return fused.astype(np.float32)

    # ── Image loading ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_image(source: ImageInput) -> Optional[Image.Image]:
        try:
            if isinstance(source, Image.Image):
                return source.convert("RGB")
            if isinstance(source, bytes):
                return Image.open(io.BytesIO(source)).convert("RGB")
            if isinstance(source, Path):
                return Image.open(source).convert("RGB")
            if isinstance(source, str):
                if source.startswith("http://") or source.startswith("https://"):
                    resp = requests.get(source, timeout=10)
                    resp.raise_for_status()
                    return Image.open(io.BytesIO(resp.content)).convert("RGB")
                return Image.open(source).convert("RGB")
        except Exception as exc:
            logger.debug("Could not load image from %s: %s", type(source).__name__, exc)
        return None


@lru_cache(maxsize=1)
def get_embedder() -> FashionCLIPEmbedder:
    """Module-level singleton embedder."""
    return FashionCLIPEmbedder()
