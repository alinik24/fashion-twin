"""Unit tests for the collector layer (no network calls)."""

import pytest
from collector.vinted import VintedCollector
from storage import ItemRecord


class TestVintedCollector:
    def setup_method(self):
        self.collector = VintedCollector()

    def test_to_record_dict(self):
        raw = {
            "id": 12345,
            "title": "Silk blouse",
            "brand_title": "Zara",
            "size_title": "M",
            "status": "good",
            "price": {"amount": 15.0, "currency_code": "GBP"},
            "currency": "GBP",
            "url": "https://www.vinted.co.uk/items/12345",
            "photos": [{"full_size_url": "https://img.vinted.com/photo.jpg"}],
            "catalog_id": 4,
            "color1": "white",
        }
        rec = self.collector._to_record(raw)
        assert isinstance(rec, ItemRecord)
        assert rec.external_id == "12345"
        assert rec.source == "vinted"
        assert rec.brand == "Zara"
        assert rec.size == "M"
        assert rec.condition == "good"
        assert rec.image_url == "https://img.vinted.com/photo.jpg"
        assert rec.listing_url == "https://www.vinted.co.uk/items/12345"

    def test_safe_float_dict(self):
        assert VintedCollector._safe_float({"amount": 12.5}) == 12.5

    def test_safe_float_str(self):
        assert VintedCollector._safe_float("£15.00") == 15.0

    def test_safe_float_none(self):
        assert VintedCollector._safe_float(None) is None

    def test_to_record_missing_fields(self):
        """Should not raise even with minimal data."""
        raw = {"id": 1, "url": "https://vinted.co.uk/items/1"}
        rec = self.collector._to_record(raw)
        assert rec.external_id == "1"
        assert rec.title is None
        assert rec.price is None
