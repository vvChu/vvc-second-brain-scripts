"""VvC Second Brain — Artifact Engine & Worker Dispatcher (v8.0).

Centralized Seam for scanning LLM responses, detecting embedded artifact placeholders
(Mermaid, Excalidraw, EA Scripts, DOCX, CSV/XLSX), and dispatching to background workers
via an extensible Strategy & Registry pattern.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

# Import individual workers with graceful fallback
try:
    from services.excalidraw_worker import trigger_excalidraw_generation
except ImportError:
    trigger_excalidraw_generation = None  # type: ignore[assignment]

try:
    from services.mermaid_worker import trigger_mermaid_generation
except ImportError:
    trigger_mermaid_generation = None  # type: ignore[assignment]

try:
    from services.ea_worker import trigger_ea_generation
except ImportError:
    trigger_ea_generation = None  # type: ignore[assignment]

try:
    from services.doc_worker import trigger_doc_generation
except ImportError:
    trigger_doc_generation = None  # type: ignore[assignment]

try:
    from services.vision_qc_worker import trigger_qc_generation
except ImportError:
    trigger_qc_generation = None  # type: ignore[assignment]

try:
    from services.d2_worker import trigger_d2_generation
except ImportError:
    trigger_d2_generation = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.dispatcher")

# Type alias for artifact handlers: (name: str, response: str, query: str) -> None
ArtifactHandler = Callable[[str, str, str], None]


class ArtifactEntry:
    """Descriptor for a registered artifact adapter."""

    def __init__(self, pattern: re.Pattern, handler: ArtifactHandler, name: str) -> None:
        """Initialize an artifact adapter entry.

        Args:
            pattern: Compiled regex pattern for matching placeholders.
            handler: Callable handler to invoke when placeholder is found.
            name: Human-readable name for telemetry and logging.
        """
        self.pattern = pattern
        self.handler = handler
        self.name = name


# Global registry of artifact adapters
_REGISTRY: list[ArtifactEntry] = []


def register_artifact_adapter(
    pattern: str | re.Pattern,
    handler: ArtifactHandler,
    name: str = "",
) -> None:
    """Register a new artifact handler with a regex pattern.

    Args:
        pattern: Regex string or compiled Pattern matching the wiki-link placeholder.
        handler: Callback function taking (name: str, response: str, query: str).
        name: Human-readable name for logging.
    """
    compiled_pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
    entry_name = name or getattr(handler, "__name__", "custom_adapter")
    _REGISTRY.append(ArtifactEntry(compiled_pattern, handler, entry_name))


# Built-in adapter bridges
def _excali_bridge(name: str, response: str, query: str) -> None:
    if trigger_excalidraw_generation is not None:
        trigger_excalidraw_generation(name, response)


def _mermaid_bridge(name: str, response: str, query: str) -> None:
    if trigger_mermaid_generation is not None:
        trigger_mermaid_generation(name, response)


def _ea_bridge(name: str, response: str, query: str) -> None:
    if trigger_ea_generation is not None:
        trigger_ea_generation(name, response)


def _doc_bridge(name: str, response: str, query: str) -> None:
    if trigger_doc_generation is not None:
        trigger_doc_generation(name, response)


def _qc_bridge(name: str, response: str, query: str) -> None:
    if trigger_qc_generation is not None:
        trigger_qc_generation(name, response, query)


def _d2_bridge(name: str, response: str, query: str) -> None:
    if trigger_d2_generation is not None:
        trigger_d2_generation(name, response)


def _init_default_registry() -> None:
    """Initialize built-in artifact adapters."""
    _REGISTRY.clear()
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.excalidraw\.md)(?:\|[^\]]*)?\]\]",
        _excali_bridge,
        name="excalidraw",
    )
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.mermaid\.md)(?:\|[^\]]*)?\]\]",
        _mermaid_bridge,
        name="mermaid",
    )
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.ea\.md)(?:\|[^\]]*)?\]\]",
        _ea_bridge,
        name="ea_script",
    )
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.docx)(?:\|[^\]]*)?\]\]",
        _doc_bridge,
        name="docx",
    )
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.(?:csv|xlsx))(?:\|[^\]]*)?\]\]",
        _qc_bridge,
        name="qc_matrix",
    )
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.d2\.svg)(?:\|[^\]]*)?\]\]",
        _d2_bridge,
        name="d2_diagram",
    )


# Pre-populate registry on module load
_init_default_registry()


def trigger_workers(response: str, query: str = "") -> list[str]:
    """Detect artifact placeholders in response and dispatch to registered workers.

    Args:
        response: Full LLM response markdown text containing placeholders.
        query: Optional user query (forwarded to specialized workers like QC).

    Returns:
        List of detected and triggered artifact filenames.
    """
    if not response:
        return []

    triggered: list[str] = []

    for entry in _REGISTRY:
        matches = entry.pattern.findall(response)
        for name in matches:
            try:
                entry.handler(name, response, query)
                triggered.append(name)
            except Exception as e:
                _logger.warning(f"Worker '{entry.name}' failed for artifact '{name}': {e}")

    return triggered
