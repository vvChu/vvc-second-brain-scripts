"""VvC Second Brain — Hybrid RAG Search (v7.0).

2-Stage search: BM25 keyword matching + Gemini Embedding similarity + RRF fusion.
Falls back gracefully to BM25-only if embedding index unavailable.

Usage:
    from services.rag_search import search
    results = search("transformer architecture", book_name="The_Thinking_Machine", top_k=5)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NamedTuple, TypedDict, List, Tuple

import numpy as np

try:
    import requests
except ImportError:
    requests = None

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

from core.config import cfg
from core.vault import scan_all_concepts

_logger = logging.getLogger("vvc.rag")

EMBEDDING_INDEX_PATH = Path(__file__).parent.parent / "_embedding_index.npz"
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

_index_cache: IndexCache | None = None


def _load_embedding_index() -> IndexCache | None:
    """Load the pre-built embedding index from disk."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    if not EMBEDDING_INDEX_PATH.exists():
        _logger.info("No embedding index found, will use BM25 only")
        return None

    try:
        data = np.load(EMBEDDING_INDEX_PATH, allow_pickle=True)
        
        if "embeddings" in data:
            embeddings = data["embeddings"]
            texts = data["texts"].tolist()
            sources = data["sources"].tolist()
        elif "vectors" in data and "stems" in data:
            embeddings = data["vectors"]
            sources = data["stems"].tolist()
            texts = []
            from core.config import cfg
            for stem in sources:
                fpath = cfg.concepts_dir / f"{stem}.md"
                if fpath.exists():
                    try:
                        texts.append(fpath.read_text(encoding="utf-8")[:2000])
                    except Exception:
                        texts.append("")
                else:
                    texts.append("")
        else:
            raise ValueError("Unknown embedding index format")

        # Pre-normalize for O(1) cosine similarity later
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalized_embeddings = embeddings / norms
        
        _index_cache = {
            "embeddings": normalized_embeddings,      # (N, 3072)
            "texts": texts,                           # list[str]
            "sources": sources,                       # list[str]
        }
        _logger.info(f"Embedding index loaded: {len(_index_cache['texts'])} entries")
        return _index_cache
    except Exception as e:
        _logger.warning(f"Failed to load embedding index: {e}")
        return None


def _get_query_embedding(query: str) -> np.ndarray | None:
    """Get embedding for a query string via AI Gateway (gemini-embed)."""
    if not cfg.gateway_url or not cfg.gateway_api_key or requests is None:
        return None

    try:
        url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gemini-embed",
            "input": [query],
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        values = resp.json()["data"][0]["embedding"]
        emb = np.array(values, dtype=np.float32)
        # Pre-normalize the query embedding
        norm = np.linalg.norm(emb)
        return emb / norm if norm > 0 else emb
    except Exception as e:
        _logger.warning(f"Embedding AI Gateway error: {e}")
        return None


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
    embeddings: np.ndarray,
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """Semantic embedding search on pre-normalized vectors. Returns (index, score) pairs."""
    if query_emb is None:
        return []

    # Fast dot product (equivalent to cosine similarity due to pre-normalization)
    similarities = np.dot(embeddings, query_emb)

    indexed = sorted(enumerate(similarities), key=lambda x: x[1], reverse=True)
    return [(i, float(s)) for i, s in indexed[:top_k] if s > 0.3]


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
        # Fallback: BM25 over vault concepts
        return _search_bm25_only(query, book_name=book_name, top_k=top_k)

    # Build unified corpus from index
    texts = index["texts"]
    sources = index["sources"]
    embeddings = index["embeddings"]
    corpus = list(zip(sources, texts))

    # Identify filtered indices if book_name is provided
    if book_name:
        book_lower = book_name.lower()
        valid_indices = {i for i, s in enumerate(sources) if book_lower in s.lower()}
        if not valid_indices:
            return []
    else:
        valid_indices = None

    # Stage 1: BM25
    if valid_indices:
        filtered_corpus = [(sources[i], texts[i]) for i in range(len(sources)) if i in valid_indices]
        bm25_res = _bm25_search(query, filtered_corpus, top_k=top_k * 2)
        # Remap indices back to original positions
        filtered_to_orig = [i for i in range(len(sources)) if i in valid_indices]
        bm25_results = [(filtered_to_orig[i], s) for i, s in bm25_res]
    else:
        bm25_results = _bm25_search(query, corpus, top_k=top_k * 2)

    # Stage 2: Embedding
    query_emb = _get_query_embedding(query)
    emb_results_raw = _embedding_search(query_emb, embeddings, top_k=top_k * 2 if not valid_indices else len(sources))
    
    # Filter embedding results if needed and re-sort
    if valid_indices:
        emb_results = []
        for i, s in emb_results_raw:
            if i in valid_indices:
                emb_results.append((i, s))
                if len(emb_results) >= top_k * 2:
                    break
    else:
        emb_results = emb_results_raw

    if emb_results:
        # Hybrid: RRF fusion
        fused = _rrf_fuse(bm25_results, emb_results)
        method = "hybrid"
    else:
        # Graceful degradation to BM25
        fused = [(i, s) for i, s in bm25_results]
        method = "bm25"

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
                
        results.append(SearchResult(
            text=full_text,
            source_file=stem,
            score=score,
            method=method,
        ))

    _logger.info(f"RAG search: {len(results)} results ({method}) for '{query[:50]}...'")
    return results


def _search_bm25_only(
    query: str,
    *,
    book_name: str = "",
    top_k: int = 5,
) -> list[SearchResult]:
    """BM25-only fallback searching concept notes directly."""
    global _bm25_corpus_cache, _bm25_model_cache
    
    if _bm25_corpus_cache is None:
        corpus: list[tuple[str, str]] = []
        concepts = scan_all_concepts()
        
        for fm in concepts:
            f = fm["_path"]
            try:
                text = f.read_text(encoding="utf-8")
                corpus.append((fm["_stem"], text))
            except OSError:
                continue
                
        _bm25_corpus_cache = corpus
        # Pre-build BM25 model for the entire corpus
        if BM25Okapi is not None and corpus:
            tokenized = [text.lower().split() for _, text in corpus]
            _bm25_model_cache = BM25Okapi(tokenized)

    corpus = _bm25_corpus_cache
    if not corpus:
        return []

    if book_name:
        book_lower = book_name.lower()
        valid_indices = {i for i, (s, _) in enumerate(corpus) if book_lower in s.lower()}
        filtered_corpus = [corpus[i] for i in range(len(corpus)) if i in valid_indices]
        bm25_res = _bm25_search(query, filtered_corpus, top_k=top_k)
        # Remap indices
        filtered_to_orig = [i for i in range(len(corpus)) if i in valid_indices]
        bm25_results = [(filtered_to_orig[i], s) for i, s in bm25_res]
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
