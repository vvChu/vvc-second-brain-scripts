"""Unit tests for Semantic Re-ranking in Ground Truth Matcher."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Test 1: _get_embeddings_batch returns L2-normalized vectors on success
# ---------------------------------------------------------------------------

class TestGetEmbeddingsBatch:
    """Tests for the _get_embeddings_batch helper function."""

    @patch("pipeline.ground_truth.cfg")
    @patch("requests.post")
    def test_success_returns_normalized_vectors(self, mock_post, mock_cfg):
        """API returns valid embeddings → function returns L2-normalized vectors."""
        mock_cfg.gateway_url = "http://fake-gateway:8090"
        mock_cfg.gateway_api_key = "test-key"

        # Create 2 fake 4-dim embedding vectors (not normalized)
        raw_vec_1 = [3.0, 0.0, 4.0, 0.0]  # norm = 5.0
        raw_vec_2 = [0.0, 1.0, 0.0, 0.0]  # norm = 1.0 (already normalized)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"embedding": raw_vec_1},
                {"embedding": raw_vec_2},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        from pipeline.ground_truth import _get_embeddings_batch

        result = _get_embeddings_batch(["query text", "candidate text"])

        assert result is not None
        assert len(result) == 2

        # Verify L2 normalization: each vector should have norm ≈ 1.0
        for vec in result:
            norm = float(np.linalg.norm(vec))
            assert abs(norm - 1.0) < 1e-5, f"Vector norm {norm} is not ~1.0"

        # Verify direction is preserved: vec1 should be [0.6, 0, 0.8, 0]
        assert abs(result[0][0] - 0.6) < 1e-5
        assert abs(result[0][2] - 0.8) < 1e-5

    @patch("pipeline.ground_truth.cfg")
    @patch("requests.post")
    def test_network_failure_returns_none(self, mock_post, mock_cfg):
        """Network timeout → function returns None (graceful fallback)."""
        mock_cfg.gateway_url = "http://fake-gateway:8090"
        mock_cfg.gateway_api_key = "test-key"

        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("VPN down")

        from pipeline.ground_truth import _get_embeddings_batch

        result = _get_embeddings_batch(["some text"])
        assert result is None

    @patch("pipeline.ground_truth.cfg")
    def test_no_gateway_config_returns_none(self, mock_cfg):
        """Missing gateway config → function returns None immediately."""
        mock_cfg.gateway_url = ""
        mock_cfg.gateway_api_key = ""

        from pipeline.ground_truth import _get_embeddings_batch

        result = _get_embeddings_batch(["some text"])
        assert result is None


# ---------------------------------------------------------------------------
# Test 2: Semantic re-ranking selects the semantically best candidate
# ---------------------------------------------------------------------------

class TestSemanticReranking:
    """Tests for semantic re-ranking integration in find_ground_truth."""

    @patch("pipeline.ground_truth._get_embeddings_batch")
    @patch("pipeline.ground_truth._bm25_search")
    @patch("pipeline.ground_truth._load_corpus")
    @patch("pipeline.ground_truth.resolve_chapter")
    @patch("pipeline.ground_truth._translate_query_to_english")
    @patch("pipeline.ground_truth._load_toc_data")
    def test_reranking_picks_semantically_best(
        self,
        mock_toc_data,
        mock_translate,
        mock_resolve,
        mock_corpus,
        mock_bm25,
        mock_embeddings,
    ):
        """BM25 top-1 is wrong but semantic re-ranking corrects to candidate #2."""
        mock_resolve.return_value = ["ch1.md"]
        mock_corpus.return_value = [("ch1", "para1"), ("ch1", "para2"), ("ch1", "para3")]
        mock_toc_data.return_value = {"language": "en"}
        mock_translate.return_value = "translated query"

        # BM25 returns 3 candidates, with candidate #0 having highest BM25 score
        mock_bm25.return_value = [
            ("ch1", "irrelevant paragraph with keywords", 45.0),
            ("ch1", "semantically correct paragraph about the topic", 38.0),
            ("ch1", "another irrelevant paragraph", 30.0),
        ]

        # Embeddings: query is most similar to candidate #1 (the semantically correct one)
        # query_emb direction: [1, 0, 0]
        query_emb = [1.0, 0.0, 0.0]
        # candidate #0: orthogonal → cosine = 0.0
        cand_0_emb = [0.0, 1.0, 0.0]
        # candidate #1: aligned → cosine = 1.0
        cand_1_emb = [1.0, 0.0, 0.0]
        # candidate #2: slightly aligned → cosine = 0.5
        cand_2_emb = [0.5, 0.866, 0.0]

        mock_embeddings.return_value = [query_emb, cand_0_emb, cand_1_emb, cand_2_emb]

        from pipeline.ground_truth import find_ground_truth

        result = find_ground_truth("query text", "TestBook", page=10)

        # Should pick candidate #1 (semantically best), not #0 (BM25 best)
        assert result.paragraph == "semantically correct paragraph about the topic"
        assert result.chapter == "ch1"
        assert result.score == 38.0  # BM25 score of the re-ranked winner

    @patch("pipeline.ground_truth._get_embeddings_batch")
    @patch("pipeline.ground_truth._bm25_search")
    @patch("pipeline.ground_truth._load_corpus")
    @patch("pipeline.ground_truth.resolve_chapter")
    @patch("pipeline.ground_truth._translate_query_to_english")
    @patch("pipeline.ground_truth._load_toc_data")
    def test_fallback_to_bm25_when_embeddings_fail(
        self,
        mock_toc_data,
        mock_translate,
        mock_resolve,
        mock_corpus,
        mock_bm25,
        mock_embeddings,
    ):
        """Gateway down → falls back gracefully to BM25 top-1."""
        mock_resolve.return_value = ["ch1.md"]
        mock_corpus.return_value = [("ch1", "para1"), ("ch1", "para2")]
        mock_toc_data.return_value = {"language": "en"}
        mock_translate.return_value = "translated query"

        mock_bm25.return_value = [
            ("ch1", "BM25 best paragraph", 50.0),
            ("ch1", "second best", 35.0),
        ]

        # Embeddings unavailable (Gateway down)
        mock_embeddings.return_value = None

        from pipeline.ground_truth import find_ground_truth

        result = find_ground_truth("query text", "TestBook", page=10)

        # Should fall back to BM25 top-1
        assert result.paragraph == "BM25 best paragraph"
        assert result.chapter == "ch1"
        assert result.score == 50.0
