"""VvC Second Brain — Excalidraw Automate Worker (v7.0).

Generates Excalidraw Automate Javascript macros via LLM. 
Saves as .ea.md files so users can execute them in Obsidian.

Usage:
    from services.ea_worker import trigger_ea_generation
    trigger_ea_generation("kien_truc.ea.md", context_text)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from services.diagram_base import find_diagram_context, spawn_worker, save_diagram_file

_logger = logging.getLogger("vvc.ea")

_EA_PROMPT = """Write an Excalidraw Automate (Javascript) script for the following concept:

CONTEXT:
{context}

CRITICAL RULES:
1. Output ONLY valid Javascript code. Do not use markdown fences like ```javascript.
2. Assume `ea` is already initialized. Start by configuring defaults if needed.
3. Use the basic Excalidraw Automate API:
   - `let id = ea.addText(x, y, "text");`
   - `let id = ea.addRect(x, y, width, height);`
   - `let id = ea.addEllipse(x, y, width, height);`
   - `let id = ea.addDiamond(x, y, width, height);`
   - `ea.connectObjects(id1, "top", id2, "bottom", {{...options}});`
4. Space out the x and y coordinates logically.
5. Generate a script that builds a clear and structured diagram representing the concepts.
"""

# Wrapper template using Templater syntax
_MD_TEMPLATE = """---
tags: [ea-script]
---
<%*
const ea = ExcalidrawAutomate;
ea.reset();
{js_content}
await ea.addElementsToView();
%>
"""


def trigger_ea_generation(diagram_name: str, source_text: str) -> None:
    """Trigger background Excalidraw Automate macro generation."""
    spawn_worker(
        target=_generate_ea,
        args=(diagram_name, source_text),
        name=f"ea-{diagram_name}",
    )


def _generate_ea(diagram_name: str, source_text: str) -> None:
    """Worker function: generate Excalidraw Automate JS."""
    context = find_diagram_context(diagram_name, source_text)

    _logger.info(f"Generating Excalidraw Automate: {diagram_name}")
    log("diagram", f"EA Macro generation started: {diagram_name}")

    js_code = call_llm(
        _EA_PROMPT.format(context=context),
        task="reasoning",
    )

    if not js_code:
        log("error", f"EA Macro generation failed: {diagram_name}")
        return

    # Clean up output
    js_code = _clean_ea(js_code)

    if not js_code:
        log("error", f"EA Macro validation failed: {diagram_name}")
        return

    # Save as .ea.md
    md_content = _MD_TEMPLATE.format(js_content=js_code)
    save_diagram_file(diagram_name, md_content, "ea")


def _clean_ea(raw: str) -> str:
    """Clean and extract Javascript code."""
    raw = raw.strip()

    # Extract JS block using regex to ignore any conversational text
    js_match = re.search(r"```(?:javascript|js)?\s*(.*?)\s*```", raw, re.DOTALL)
    if js_match:
        raw = js_match.group(1).strip()
    else:
        # Fallback if no markdown fences
        raw = re.sub(r"^```(?:javascript|js)?\s*\n", "", raw.strip())
        raw = re.sub(r"\n```\s*$", "", raw)
        raw = raw.strip()

    return raw.strip()
