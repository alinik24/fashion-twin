"""Unit tests for the embedder — mocks FashionCLIP to avoid loading model."""

from unittest.mock import MagicMock, patch
import numpy as np
import pytest


class TestFashionCLIPEmbedder:
    def test_encode_item_text_only(self):
        from embedder.fashion_clip import FashionCLIPEmbedder

        embedder = FashionCLIPEmbedder()
        mock_model = MagicMock()
        mock_model.encode_text.return_value = np.random.randn(1, 512).astype(np.float32)
        embedder._model = mock_model

        vec = embedder.encode_item(title="silk blouse", image=None)
        assert vec.shape == (512,)
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5, "Vector should be L2-normalised"

    def test_encode_item_no_inputs(self):
        from embedder.fashion_clip import FashionCLIPEmbedder

        embedder = FashionCLIPEmbedder()
        embedder._model = MagicMock()

        vec = embedder.encode_item(title=None, image=None)
        assert vec.shape == (512,)
        assert np.all(vec == 0.0)

    def test_load_image_invalid_url(self):
        from embedder.fashion_clip import FashionCLIPEmbedder

        result = FashionCLIPEmbedder._load_image("https://not-a-real-url-12345.example.com/img.jpg")
        assert result is None

    def test_encode_texts_delegates_to_model(self):
        from embedder.fashion_clip import FashionCLIPEmbedder

        embedder = FashionCLIPEmbedder()
        expected = np.random.randn(2, 512).astype(np.float32)
        mock_model = MagicMock()
        mock_model.encode_text.return_value = expected
        embedder._model = mock_model

        result = embedder.encode_texts(["blouse", "jacket"])
        assert result.shape == (2, 512)
        mock_model.encode_text.assert_called_once()
