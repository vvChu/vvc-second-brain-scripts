"""VvC Second Brain — RAG Package Deep Seam.

Exports core RAG functionality:
- build_rag_context: Format retrieved notes into XML context for LLMs.
- resolve_explicit_references: Extract and resolve [[stem]] references from queries.
- search: Hybrid BM25 + Embedding search.
- SearchResult: Search result data structure.
"""

from __future__ import annotations

from services.rag.context_builder import build_rag_context, resolve_explicit_references
from services.rag.hybrid_search import (
    search,
    SearchResult,
    IndexCache,
    EMBEDDING_INDEX_PATH,
    EMBEDDING_DIM,
)

__all__ = [
    "build_rag_context",
    "resolve_explicit_references",
    "search",
    "SearchResult",
    "IndexCache",
    "EMBEDDING_INDEX_PATH",
    "EMBEDDING_DIM",
]
