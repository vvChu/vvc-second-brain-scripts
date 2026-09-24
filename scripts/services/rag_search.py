"""VvC Second Brain — RAG Search Shim (v8.15.13).

DEPRECATED: Prefer importing from `services.rag` or `services.rag.search`.
Maintained for 100% backward compatibility.
"""

from __future__ import annotations

from services.rag.hybrid_search import (
    search,
    SearchResult,
    IndexCache,
    EMBEDDING_INDEX_PATH,
    EMBEDDING_DIM,
    _load_embedding_index,
    _get_query_embedding,
    _bm25_search,
    _embedding_search,
    _rrf_fuse,
    _search_bm25_only,
)

__all__ = [
    "search",
    "SearchResult",
    "IndexCache",
    "EMBEDDING_INDEX_PATH",
    "EMBEDDING_DIM",
]
