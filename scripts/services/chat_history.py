"""VvC Second Brain — Chat History Shim (v8.13.2).

Backward-compatibility shim. Re-exports all markers, section extractors,
and auto-archival logic from services.command.inbox.
"""

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
