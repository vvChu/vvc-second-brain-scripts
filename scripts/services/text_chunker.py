"""VvC Second Brain — Text Chunker Shim (Backward Compatibility).

Delegates to services.orthography to eliminate symbol collision with core.text_chunker.
"""

from __future__ import annotations

from services.orthography import (
    call_llm,
    is_structured_article,
    orthographic_preprocess,
)

__all__ = [
    "is_structured_article",
    "orthographic_preprocess",
]
