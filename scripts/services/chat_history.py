"""VvC Second Brain — Chat History Shim (v8.13.2).

Backward-compatibility shim. Re-exports all markers, section extractors,
and auto-archival logic from services.command.inbox.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "services.chat_history is deprecated and will be removed in v9.0. "
    "Please import directly from services.command.inbox instead.",
    DeprecationWarning,
    stacklevel=2,
)

from services.command.inbox import (
    MAX_COMMAND_LEN,
    INPUT_MARKER,
    HISTORY_MARKER,
    QUERY_PATTERN,
    extract_sections,
    auto_archive_command,
)

__all__ = [
    "MAX_COMMAND_LEN",
    "INPUT_MARKER",
    "HISTORY_MARKER",
    "QUERY_PATTERN",
    "extract_sections",
    "auto_archive_command",
]
