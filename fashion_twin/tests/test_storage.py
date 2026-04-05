"""Unit tests for storage helpers that don't need a live DB."""

import json
import pytest
from storage.postgres import ItemRecord, InteractionRecord


class TestItemRecord:
    def test_defaults(self):
        rec = ItemRecord(external_id="123", source="vinted", listing_url="https://x.com")
        assert rec.id is None
        assert rec.raw_data == {}
        assert rec.price is None

    def test_all_fields(self):
        rec = ItemRecord(
            external_id="abc",
            source="vestiaire",
            listing_url="https://v.com/abc",
            title="Silk top",
            brand="Chloé",
            price=120.0,
            currency="EUR",
        )
        assert rec.brand == "Chloé"
        assert rec.price == 120.0


class TestInteractionRecord:
    def test_defaults(self):
        rec = InteractionRecord(item_id=1, interaction_type="like")
        assert rec.user_id == 1
        assert rec.strength == 1.0
        assert rec.context == {}

    def test_custom(self):
        rec = InteractionRecord(
            item_id=5,
            interaction_type="dislike",
            strength=2.0,
            context={"query": "silk blouse"},
        )
        assert rec.context["query"] == "silk blouse"
