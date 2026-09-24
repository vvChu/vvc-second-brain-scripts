"""VvC Second Brain — RAG Builder Shim (v8.15.13).

DEPRECATED: Prefer importing from `services.rag` or `services.rag.context_builder`.
Maintained for 100% backward compatibility.
"""

from __future__ import annotations

from services.rag.context_builder import (
    build_rag_context,
    resolve_explicit_references,
    _rag_search,
)

__all__ = [
    "build_rag_context",
    "resolve_explicit_references",
]
