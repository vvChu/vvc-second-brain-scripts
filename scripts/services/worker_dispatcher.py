"""VvC Second Brain — Worker Dispatcher.

Triggers background workers based on LLM response.
"""

import logging
import re

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

_logger = logging.getLogger("vvc.dispatcher")

def trigger_workers(response: str, query: str) -> None:
    """Detect placeholders and trigger background workers."""
    excali = re.findall(r"!\[\[([^\]|]+\.excalidraw\.md)(?:\|[^\]]*)?\]\]", response)
    mermaid = re.findall(r"!\[\[([^\]|]+\.mermaid\.md)(?:\|[^\]]*)?\]\]", response)
    ea = re.findall(r"!\[\[([^\]|]+\.ea\.md)(?:\|[^\]]*)?\]\]", response)
    docx = re.findall(r"!\[\[([^\]|]+\.docx)(?:\|[^\]]*)?\]\]", response)
    qc = re.findall(r"!\[\[([^\]|]+\.(?:csv|xlsx))(?:\|[^\]]*)?\]\]", response)

    if trigger_excalidraw_generation:
        for name in excali:
            try:
                trigger_excalidraw_generation(name, response)
            except Exception:
                _logger.debug(f"Excalidraw generation failed for: {name}")

    if trigger_mermaid_generation:
        for name in mermaid:
            try:
                trigger_mermaid_generation(name, response)
            except Exception:
                _logger.debug(f"Mermaid generation failed for: {name}")

    if trigger_ea_generation:
        for name in ea:
            try:
                trigger_ea_generation(name, response)
            except Exception:
                _logger.debug(f"EA Macro generation failed for: {name}")

    if trigger_doc_generation:
        for name in docx:
            try:
                trigger_doc_generation(name, response)
            except Exception:
                _logger.debug(f"Doc generation failed for: {name}")

    if trigger_qc_generation:
        for name in qc:
            try:
                trigger_qc_generation(name, response, query)
            except Exception:
                _logger.debug(f"QC generation failed for: {name}")
