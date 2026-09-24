"""Tests for services.rag deep module package and legacy shims."""

from __future__ import annotations

from pathlib import Path
import pytest

import services.rag as rag
import services.rag_builder as rag_builder
import services.rag_search as rag_search
from core.config import cfg


def test_rag_package_exports():
    """Package services.rag must export full public interface."""
    expected_exports = {
        "build_rag_context",
        "resolve_explicit_references",
        "search",
        "SearchResult",
        "IndexCache",
        "EMBEDDING_INDEX_PATH",
        "EMBEDDING_DIM",
    }
    assert set(rag.__all__) == expected_exports
    for name in expected_exports:
        assert hasattr(rag, name)


def test_rag_shims_identity():
    """Legacy shims must re-export identical objects as services.rag."""
    assert rag_builder.build_rag_context is rag.build_rag_context
    assert rag_builder.resolve_explicit_references is rag.resolve_explicit_references
    assert rag_search.search is rag.search
    assert rag_search.SearchResult is rag.SearchResult
    assert rag_search.IndexCache is rag.IndexCache
    assert rag_search.EMBEDDING_INDEX_PATH is rag.EMBEDDING_INDEX_PATH
    assert rag_search.EMBEDDING_DIM is rag.EMBEDDING_DIM


def test_rag_resolve_explicit_and_context_build(tmp_path: Path):
    """build_rag_context and resolve_explicit_references function properly with isolated vault."""
    topics_dir = cfg.vault_root / "04 - Permanent" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    
    test_file = topics_dir / "kien_truc_rag.md"
    test_file.write_text(
        "---\ntitle: \"Kiến Trúc RAG\"\nsummary: \"Tóm tắt RAG\"\ntags:\n  - rag\n---\n\nNội dung chi tiết kiến trúc RAG.",
        encoding="utf-8",
    )

    docs = rag.resolve_explicit_references("[[kien_truc_rag]]")
    assert len(docs) == 1
    assert docs[0]["source_file"] == "kien_truc_rag.md"
    assert docs[0]["title"] == "Kiến Trúc RAG"
    assert "Nội dung chi tiết kiến trúc RAG." in docs[0]["body"]

    context, refs = rag.build_rag_context("Phân tích [[kien_truc_rag]]")
    assert '<document id="1" file="kien_truc_rag.md" title="Kiến Trúc RAG"' in context
    assert "TÓM TẮT: Tóm tắt RAG" in context
    assert 1 in refs
    assert refs[1] == ("kien_truc_rag.md", "Kiến Trúc RAG")


def test_rag_search_bm25_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """search falls back to BM25 correctly when no vector index exists."""
    # Force _load_embedding_index to return None
    monkeypatch.setattr("services.rag.hybrid_search._load_embedding_index", lambda: None)
    
    # Mock scan_all_concepts with enough documents for positive BM25 IDF
    concept_file1 = tmp_path / "concept_neural.md"
    concept_file1.write_text(
        "---\ntitle: Neural Networks\n---\nDeep learning and neural networks are powerful architectures.",
        encoding="utf-8",
    )
    concept_file2 = tmp_path / "concept_finance.md"
    concept_file2.write_text(
        "---\ntitle: Personal Finance\n---\nBudgeting and investing principles.",
        encoding="utf-8",
    )
    concept_file3 = tmp_path / "concept_cooking.md"
    concept_file3.write_text(
        "---\ntitle: Cooking Recipes\n---\nBaking sourdough bread and pasta.",
        encoding="utf-8",
    )

    mock_concepts = [
        {"_stem": "concept_neural", "_path": concept_file1},
        {"_stem": "concept_finance", "_path": concept_file2},
        {"_stem": "concept_cooking", "_path": concept_file3},
    ]
    monkeypatch.setattr("services.rag.hybrid_search.scan_all_concepts", lambda: mock_concepts)
    # Reset internal caches
    monkeypatch.setattr("services.rag.hybrid_search._bm25_corpus_cache", None)
    monkeypatch.setattr("services.rag.hybrid_search._bm25_model_cache", None)

    results = rag.search("neural networks", top_k=2)
    assert len(results) >= 1
    assert results[0].source_file == "concept_neural"
    assert results[0].method == "bm25"
