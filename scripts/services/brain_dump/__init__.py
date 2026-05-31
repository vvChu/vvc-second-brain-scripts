"""VvC Second Brain — Brain Dump Handler (v7.0).

Split into sub-modules for maintainability:
- orchestrator: Main entry point and flow control
- inbox_io: Brain_Dump.md file I/O operations
- url_registry: URL deduplication and fetching
- concept_synthesis: Map-Reduce concept extraction and saving
"""
from services.brain_dump.orchestrator import handle_brain_dump  # noqa: F401
from services.brain_dump.inbox_io import _find_pending_dump, _extract_inbox_sections  # noqa: F401
from services.brain_dump.url_registry import (
    _normalize_url, _check_override, _load_url_registry, _save_url_registry  # noqa: F401
)
