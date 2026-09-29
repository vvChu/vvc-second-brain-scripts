"""VvC Second Brain — Test Remediation for v8.15.14.

Verifies:
1. CircuitBreaker immediate tripping on fatal errors (401/403/404)
2. Hard abort lock in vector sync preventing index overwrite
3. Dimension guard preventing index corruption on mismatched vector size
4. Table escaped pipe and anchor support in title standardizer batch link update
5. Stale stubs rendering with date_created and linked_from keys
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from core.config import cfg
from core.llm.embedding_client import EmbeddingFatalError
from core.vector_sync import CircuitBreaker, SyncContext, _commit_sync_results, sync_vector_index
from services.weekly_synthesis import generate_weekly_synthesis
from services.wiki_health.title_standardizer import _update_all_links_vault_wide_batch


def test_circuit_breaker_fatal_error_immediate_trip():
    """Verify trip_immediately sets tripped=True instantly."""
    cb = CircuitBreaker()
    assert not cb.tripped
    cb.trip_immediately("HTTP 403 Forbidden")
    assert cb.tripped
    assert cb.consecutive_errors == 0


def test_vector_sync_aborts_on_circuit_breaker_tripped(tmp_path: Path):
    """Verify sync_vector_index does not overwrite index when circuit breaker trips."""
    mock_store = MagicMock()
    mock_store.lock_path = tmp_path / "sync.lock"
    mock_store.sources = ["existing_concept"]
    mock_store.texts = ["hash:123"]
    mock_store.embeddings = [np.ones(1024, dtype=np.float32)]

    concepts = [
        {"_path": tmp_path / "new_concept.md", "_stem": "new_concept", "path": str(tmp_path / "new_concept.md")}
    ]
    (tmp_path / "new_concept.md").write_text("# New Concept\nContent here.", encoding="utf-8")

    orig_url = cfg.gateway_url
    orig_key = cfg.gateway_api_key
    object.__setattr__(cfg, "gateway_url", "http://test:8090/v1")
    object.__setattr__(cfg, "gateway_api_key", "test-key")

    try:
        with patch("core.vector_sync.get_embedding", side_effect=EmbeddingFatalError(403, "Leaked API Key")):
            stats = sync_vector_index(mock_store, concepts=concepts)
    finally:
        object.__setattr__(cfg, "gateway_url", orig_url)
        object.__setattr__(cfg, "gateway_api_key", orig_key)

    assert stats.get("aborted") is True
    assert stats["total"] == 1
    mock_store._atomic_save.assert_not_called()


def test_dimension_guard_prevents_corrupted_commit(tmp_path: Path):
    """Verify _commit_sync_results aborts if vector dimension mismatches existing index."""
    mock_store = MagicMock()
    ctx = SyncContext(
        existing_sources=["concept_a"],
        existing_texts=["hash:a"],
        existing_embeddings=[np.ones(1024, dtype=np.float32)],
        index_map={"concept_a": 0},
        new_sources=["concept_a"],
        new_texts=["hash:a"],
        new_embeddings=[np.ones(512, dtype=np.float32)],  # Mismatched 512 vs 1024!
    )

    stats = _commit_sync_results(mock_store, ctx, deleted_count=0)
    assert stats.get("aborted") is True
    mock_store._atomic_save.assert_not_called()



def test_update_all_links_table_pipe_escaping(tmp_path: Path):
    r"""Verify _update_all_links_vault_wide_batch handles [[old\|alias]] and anchors."""
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir(parents=True)
    test_note = concepts_dir / "test_note.md"
    test_note.write_text(
        "| **[[old_slug\\|Old Alias]]** | Link: [[old_slug#heading\\|Heading Alias]] | Bare: [[old_slug]] |\n",
        encoding="utf-8",
    )

    orig_concepts = cfg.concepts_dir
    orig_sources = cfg.sources_dir
    orig_dump = cfg.dump_file

    object.__setattr__(cfg, "concepts_dir", concepts_dir)
    object.__setattr__(cfg, "sources_dir", tmp_path / "sources")
    object.__setattr__(cfg, "dump_file", tmp_path / "dump.md")

    try:
        renames = {"old_slug": "new_canonical_slug"}
        _update_all_links_vault_wide_batch(renames)

        updated_text = test_note.read_text(encoding="utf-8")
        assert "[[new_canonical_slug\\|Old Alias]]" in updated_text
        assert "[[new_canonical_slug#heading\\|Heading Alias]]" in updated_text
        assert "[[new_canonical_slug]]" in updated_text
    finally:
        object.__setattr__(cfg, "concepts_dir", orig_concepts)
        object.__setattr__(cfg, "sources_dir", orig_sources)
        object.__setattr__(cfg, "dump_file", orig_dump)


def test_weekly_synthesis_renders_stale_stubs_properly(tmp_path: Path):
    """Verify stale stubs section correctly renders date_created and linked_from."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    stale_file = state_dir / ".stale_stubs.json"
    stale_file.write_text(
        json.dumps([
            {
                "stem": "stale_concept",
                "title": "Stale Concept",
                "age_days": 45,
                "date_created": "2026-05-15",
                "linked_from": ["source_doc_a", "source_doc_b"],
            }
        ]),
        encoding="utf-8",
    )

    orig_state = cfg.state_dir
    orig_moc = cfg.moc_dir
    object.__setattr__(cfg, "state_dir", state_dir)
    object.__setattr__(cfg, "moc_dir", tmp_path)

    try:
        report_path = generate_weekly_synthesis(
            report={"orphans": [], "broken_links": [], "bridge_candidates": []},
            concepts=[],
            sources=[],
            healed_links=7,
            healed_typos=12,
        )
        content = report_path.read_text(encoding="utf-8")
        assert "2026-05-15" in content
        assert "[[source_doc_a]]" in content
        assert "`stale_concept` | 2026-05-15 | 45 |" in content
        assert "Đã tự động tạo thành công **7** ghi chú stub" in content
    finally:
        object.__setattr__(cfg, "state_dir", orig_state)
        object.__setattr__(cfg, "moc_dir", orig_moc)


def test_get_embeddings_batch_and_model_resolution():
    """Verify get_embeddings_batch formats payload with configured model."""
    from core.llm.embedding_client import get_embeddings_batch, http_session

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {"embedding": [1.0] * 1024},
            {"embedding": [2.0] * 1024},
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    target = "core.llm.embedding_client.http_session.post" if http_session is not None else "core.llm.embedding_client.requests.post"
    with patch(target, return_value=mock_resp) as mock_post:
        results = get_embeddings_batch(["hello", "world"])
        assert len(results) == 2
        assert results[0].shape == (1024,)
        assert np.isclose(np.linalg.norm(results[0]), 1.0)
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["model"] == "bge-m3"
        assert len(call_kwargs["json"]["input"]) == 2


def test_dual_gate_isolated_pair_passes(tmp_path: Path):
    """Isolated duplicate pair (Top-1 >= 0.95 and Margin >= 0.03) passes gate."""
    from pipeline.semantic_fallback import evaluate_dual_gate

    valid_matches = [("target_concept", 0.9650), ("second_concept", 0.9100)]
    res = evaluate_dual_gate(valid_matches, "New Concept")
    assert res == ("target_concept", 0.9650)


def test_dual_gate_cluster_detected_and_queued(tmp_path: Path):
    """Dense cluster (Top-1 >= 0.95 but Margin < 0.03) queues for review without merging."""
    from pipeline.semantic_fallback import evaluate_dual_gate

    orig_state = cfg.state_dir
    object.__setattr__(cfg, "state_dir", tmp_path)
    try:
        valid_matches = [("target_concept", 0.9550), ("cluster_sibling", 0.9400)]
        res = evaluate_dual_gate(valid_matches, "New Cluster Note")
        assert res is None
        cand_file = tmp_path / ".merge_candidates.jsonl"
        assert cand_file.exists()
        entry = json.loads(cand_file.read_text(encoding="utf-8").strip())
        assert entry["category"] == "cluster"
        assert entry["matched_stem"] == "target_concept"
        assert entry["score"] == 0.955
    finally:
        object.__setattr__(cfg, "state_dir", orig_state)


def test_dual_gate_candidate_in_90_95_logged(tmp_path: Path):
    """Candidate in [0.90, 0.95) is audit-logged without online merge."""
    from pipeline.semantic_fallback import evaluate_dual_gate

    orig_state = cfg.state_dir
    object.__setattr__(cfg, "state_dir", tmp_path)
    try:
        valid_matches = [("near_concept", 0.9250), ("other_concept", 0.8600)]
        res = evaluate_dual_gate(valid_matches, "New Related Note")
        assert res is None
        cand_file = tmp_path / ".merge_candidates.jsonl"
        assert cand_file.exists()
        entry = json.loads(cand_file.read_text(encoding="utf-8").strip())
        assert entry["category"] == "candidate"
        assert entry["matched_stem"] == "near_concept"
        assert entry["score"] == 0.925
    finally:
        object.__setattr__(cfg, "state_dir", orig_state)


def test_ground_truth_rerank_respects_margin():
    """Ground truth reranking preserves BM25 rank 0 when embedding margin < 0.03."""
    from pipeline.ground_truth import _rerank_results

    results = [
        ("ch1", "BM25 rank 0 paragraph", 50.0),
        ("ch1", "candidate paragraph slightly higher cosine", 30.0),
    ]
    # Candidate 1 has cosine 0.41, Rank 0 has cosine 0.40 -> margin 0.01 < 0.03
    query_vec = [1.0, 0.0]
    cand0_vec = [0.40, 0.9165]
    cand1_vec = [0.41, 0.9121]

    with patch("pipeline.ground_truth._get_embeddings_batch", return_value=[query_vec, cand0_vec, cand1_vec]):
        ch, para, score = _rerank_results("query text", results)
        assert para == "BM25 rank 0 paragraph"
        assert score == 50.0



