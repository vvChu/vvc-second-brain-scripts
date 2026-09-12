"""VvC Second Brain — Command Interactive Deep Module (v8.13.0).

Monitors Command.md for @AI: queries, processes them with RAG + LLM,
writes responses back. Supports 10 writing styles via /prefix.

Sub-modules:
- coordinator: Stateful orchestration, LLM dispatch, resilient I/O
- inbox: Pure string transformations for inbox, queries, and patching
- styles: Pure taxonomy of 10 writing styles and prefix parser
- citations: Pure citation reindexing and wikilink quote sanitization
- topic_saver: Auto-save long responses as Topic notes
"""

from __future__ import annotations

from core.config import cfg
from core.llm import call_llm

from services.command.styles import WRITING_STYLES, parse_style
from services.command.citations import reindex_citations, clean_wikilink_quotes
from services.command.inbox import (
    ensure_format,
    find_pending_query,
    find_pending_query_span,
    format_response_callout,
    patch_inbox,
    apply_command_patch,
)
from services.command.topic_saver import (
    TOPIC_AUTO_SAVE_THRESHOLD,
    build_topic_content,
    save_topic_file,
    auto_save_topic,
)
from services.command.coordinator import (
    generate_response,
    check_file_back,
    write_response,
    handle_command,
)

# Public Seam
__all__ = [
    "handle_command",
    "WRITING_STYLES",
    "reindex_citations",
]

# Shims / Re-exports for backward compatibility & test monkeypatching
_parse_style = parse_style
_find_pending_query = find_pending_query
_find_pending_query_span = find_pending_query_span
_ensure_format = ensure_format
_generate_response = generate_response
_write_response = write_response
_check_file_back = check_file_back
_auto_save_topic = auto_save_topic
