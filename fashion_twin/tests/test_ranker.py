"""Unit tests for the LightFM ranker and bandit (no DB required)."""

import numpy as np
import pytest


class TestFashionRanker:
    def _make_interactions(self):
        return [
            {"item_id": 1, "interaction_type": "like", "total_strength": 3.0},
            {"item_id": 2, "interaction_type": "dislike", "total_strength": 1.0},
            {"item_id": 3, "interaction_type": "view", "total_strength": 1.0},
            {"item_id": 4, "interaction_type": "like", "total_strength": 3.0},
            {"item_id": 5, "interaction_type": "skip", "total_strength": 0.5},
        ]

    def test_build_dataset(self):
        from ranker.lightfm_model import FashionRanker

        ranker = FashionRanker()
        interactions = self._make_interactions()
        ranker.build_dataset(interactions)
        assert ranker._dataset is not None
        assert 1 in ranker._item_id_map

    def test_train_and_score(self):
        from ranker.lightfm_model import FashionRanker

        ranker = FashionRanker()
        interactions = self._make_interactions()
        ranker.build_dataset(interactions)
        int_mat, weight_mat = ranker.build_interactions_matrix(interactions)
        ranker.train(int_mat, weight_mat, epochs=5)

        results = ranker.score_items([1, 2, 3, 4, 5])
        assert len(results) == 5
        item_ids = [r[0] for r in results]
        assert set(item_ids) == {1, 2, 3, 4, 5}
        # Results should be sorted descending
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_item_to_tags(self):
        from ranker.lightfm_model import FashionRanker

        tags = FashionRanker.item_to_tags({
            "brand": "Zara",
            "source": "vinted",
            "condition": "very good",
            "size": "M",
        })
        assert "brand:zara" in tags
        assert "source:vinted" in tags
        assert "condition:very_good" in tags
        assert "size:m" in tags


class TestFashionBandit:
    def test_update_and_score(self):
        from ranker.bandit import FashionBandit

        bandit = FashionBandit()
        dim = 16

        # Feed 15 updates to trigger fit
        for i in range(15):
            vec = np.random.randn(dim).astype(np.float32)
            bandit.update(item_id=i, reward=float(i % 2), context_vector=vec)

        context_vecs = np.random.randn(3, dim).astype(np.float32)
        results = bandit.score([1, 2, 3], context_vecs)
        # After fit, should return something (model may still return zeros if nchoices mismatch)
        assert len(results) == 3

    def test_reward_map_coverage(self):
        from ranker.bandit import FashionBandit

        for itype in ["like", "dislike", "view", "skip", "purchase"]:
            assert itype in FashionBandit.REWARD_MAP
