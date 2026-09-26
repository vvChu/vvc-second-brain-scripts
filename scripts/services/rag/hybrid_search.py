"""VvC Second Brain — Hybrid RAG Search Engine (v8.15.13).

2-Stage search: BM25 keyword matching + Gemini Embedding similarity + RRF fusion.
Falls back gracefully to BM25-only if embedding index unavailable.

Usage:
    from services.rag import search
    results = search("transformer architecture", book_name="The_Thinking_Machine", top_k=5)
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple, TypedDict

import numpy as np

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

from core.config import cfg
from core.llm.embedding_client import get_embedding
from core.vault import scan_all_concepts
from core.vector_store import VectorStore

_logger = logging.getLogger("vvc.rag.hybrid_search")

EMBEDDING_INDEX_PATH = cfg.state_dir / "_embedding_index.npz"
EMBEDDING_DIM = 3072  # Gemini embedding-001

class IndexCache(TypedDict):
    embeddings: np.ndarray
    texts: list[str]
    sources: list[str]


class SearchResult(NamedTuple):
    """A single search result."""
    text: str
    source_file: str
    score: float
    method: str  # "hybrid" | "bm25" | "embedding"


# --- Embedding Index ---


def _load_embedding_index() -> IndexCache | None:
    """Load the pre-built embedding index from VectorStore."""
    store = VectorStore.get_instance()
    if len(store) == 0:
        _logger.info("No embedding index found, will use BM25 only")
        return None

    return {
        "embeddings": store.embeddings,
        "texts": store.texts,
        "sources": store.sources,
    }


def _get_query_embedding(query: str) -> np.ndarray | None:
    """Get embedding for a query string via AI Gateway."""
    return get_embedding(query)


# --- BM25 Search ---

_bm25_corpus_cache: list[tuple[str, str]] | None = None
_bm25_model_cache: Any = None

def _bm25_search(
    query: str,
    corpus: list[tuple[str, str]],
    top_k: int = 10,
    bm25_model: Any = None,
) -> list[tuple[int, float]]:
    """BM25 keyword search. Returns (index, score) pairs."""
    if BM25Okapi is None or not corpus:
        return []

    if bm25_model is None:
        tokenized = [text.lower().split() for _, text in corpus]
        bm25_model = BM25Okapi(tokenized)

    scores = bm25_model.get_scores(query.lower().split())

    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [(i, float(s)) for i, s in indexed[:top_k] if s > 0]


# --- Embedding Search ---

def _embedding_search(
    query_emb: np.ndarray | None,
    embeddings: np.ndarray | None = None,
    top_k: int = 10,
    threshold: float = 0.3,
) -> list[tuple[int, float]]:
    """Embedding cosine similarity search."""
    if query_emb is None:
        return []

    store = VectorStore.get_instance()
    return store.search_indices(query_emb, top_k=top_k, threshold=threshold)


# --- Reciprocal Rank Fusion ---

def _rrf_fuse(
    bm25_results: list[tuple[int, float]],
    emb_results: list[tuple[int, float]],
    k: int = 60,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion to combine BM25 and embedding results."""
    scores: dict[int, float] = {}

    for rank, (idx, _) in enumerate(bm25_results):
        scores[idx] = scores.get(idx, 0) + 1.0 / (k + rank + 1)

    for rank, (idx, _) in enumerate(emb_results):
        scores[idx] = scores.get(idx, 0) + 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# --- Public API ---

def _run_hybrid_bm25(
    query: str, sources: list[str], texts: list[str], valid_indices: set[int] | None, top_k: int
) -> list[tuple[int, float]]:
    """Execute BM25 search over unified or book-filtered corpus."""
    if valid_indices:
        filtered_corpus = [(sources[i], texts[i]) for i in range(len(sources)) if i in valid_indices]
        bm25_res = _bm25_search(query, filtered_corpus, top_k=top_k * 2)
        filtered_to_orig = [i for i in range(len(sources)) if i in valid_indices]
        return [(filtered_to_orig[i], s) for i, s in bm25_res]
    corpus = list(zip(sources, texts))
    return _bm25_search(query, corpus, top_k=top_k * 2)


def _run_hybrid_embedding(
    query: str, embeddings: np.ndarray, sources: list[str], valid_indices: set[int] | None, top_k: int
) -> list[tuple[int, float]]:
    """Execute embedding search with optional book-level filtering."""
    query_emb = _get_query_embedding(query)
    emb_results_raw = _embedding_search(
        query_emb, embeddings, top_k=top_k * 2 if not valid_indices else len(sources)
    )
    if not valid_indices:
        return emb_results_raw
    filtered: list[tuple[int, float]] = []
    for i, s in emb_results_raw:
        if i in valid_indices:
            filtered.append((i, s))
            if len(filtered) >= top_k * 2:
                break
    return filtered


def _assemble_search_results(
    fused: list[tuple[int, float]], sources: list[str], texts: list[str], method: str, top_k: int
) -> list[SearchResult]:
    """Hydrate search results with disk concept content if available."""
    results = []
    for idx, score in fused[:top_k]:
        stem = sources[idx]
        file_path = cfg.concepts_dir / f"{stem}.md"
        full_text = texts[idx]
        if file_path.exists():
            try:
                full_text = file_path.read_text(encoding="utf-8")
            except OSError:
                pass
        results.append(SearchResult(text=full_text, source_file=stem, score=score, method=method))
    return results


def search(
    query: str,
    *,
    book_name: str = "",
    top_k: int = 5,
) -> list[SearchResult]:
    """Hybrid search across the knowledge base.

    Args:
        query: Search query string.
        book_name: Optional filter to a specific book corpus.
        top_k: Number of results to return.

    Returns:
        List of SearchResult ordered by relevance.
    """
    index = _load_embedding_index()
    if index is None:
        return _search_bm25_only(query, book_name=book_name, top_k=top_k)

    texts, sources, embeddings = index["texts"], index["sources"], index["embeddings"]
    valid_indices = None
    if book_name:
        book_lower = book_name.lower()
        valid_indices = {i for i, s in enumerate(sources) if book_lower in s.lower()}
        if not valid_indices:
            return []

    bm25_results = _run_hybrid_bm25(query, sources, texts, valid_indices, top_k)
    emb_results = _run_hybrid_embedding(query, embeddings, sources, valid_indices, top_k)

    if emb_results:
        fused = _rrf_fuse(bm25_results, emb_results)
        method = "hybrid"
    else:
        fused = [(i, s) for i, s in bm25_results]
        method = "bm25"

    results = _assemble_search_results(fused, sources, texts, method, top_k)
    _logger.info(f"RAG search: {len(results)} results ({method}) for '{query[:50]}...'")
    return results


def _ensure_bm25_corpus_cache() -> list[tuple[str, str]]:
    """Initialize BM25 corpus and pre-built model cache from vault concept notes."""
    global _bm25_corpus_cache, _bm25_model_cache
    if _bm25_corpus_cache is None:
        corpus: list[tuple[str, str]] = []
        for fm in scan_all_concepts():
            try:
                corpus.append((fm["_stem"], fm["_path"].read_text(encoding="utf-8")))
            except OSError:
                continue
        _bm25_corpus_cache = corpus
        if BM25Okapi is not None and corpus:
            tokenized = [text.lower().split() for _, text in corpus]
            _bm25_model_cache = BM25Okapi(tokenized)
    return _bm25_corpus_cache


def _search_bm25_only(
    query: str,
    *,
    book_name: str = "",
    top_k: int = 5,
) -> list[SearchResult]:
    """BM25-only fallback searching concept notes directly."""
    corpus = _ensure_bm25_corpus_cache()
    if not corpus:
        return []

    if book_name:
        book_lower = book_name.lower()
        valid = [i for i, (s, _) in enumerate(corpus) if book_lower in s.lower()]
        filtered = [corpus[i] for i in valid]
        res = _bm25_search(query, filtered, top_k=top_k)
        bm25_results = [(valid[i], s) for i, s in res]
    else:
        bm25_results = _bm25_search(query, corpus, top_k=top_k, bm25_model=_bm25_model_cache)

    return [
        SearchResult(
            text=corpus[i][1],
            source_file=corpus[i][0],
            score=s,
            method="bm25",
        )
        for i, s in bm25_results
    ]


__all__ = [
    "search",
    "SearchResult",
    "IndexCache",
    "EMBEDDING_INDEX_PATH",
    "EMBEDDING_DIM",
]
