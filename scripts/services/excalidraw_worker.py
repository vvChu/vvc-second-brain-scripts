"""VvC Second Brain — Excalidraw Worker (v8.0 — Template-Enhanced).

Generates Excalidraw JSON diagrams via Copilot CLI (claude-sonnet for spatial reasoning).
Saves as .excalidraw.md files compatible with Obsidian Excalidraw plugin.

Usage:
    from services.excalidraw_worker import trigger_excalidraw_generation
    trigger_excalidraw_generation("kien_truc.excalidraw.md", context_text)
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from core.config import cfg
from core.log import log
from core.llm import call_llm
from services.diagram_base import find_diagram_context, spawn_worker, save_diagram_file, select_template

_logger = logging.getLogger("vvc.excalidraw")

from core.prompts.services import EXCALIDRAW_GENERATE as _EXCALIDRAW_PROMPT  # noqa: E402

# Excalidraw MD wrapper template
_MD_TEMPLATE = """---
excalidraw-plugin: parsed
tags: [excalidraw]
---
==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==

# Excalidraw Data

## Text Elements
{text_content}

%%
## Drawing
```json
{json_content}
```
%%
"""


def trigger_excalidraw_generation(diagram_name: str, source_text: str) -> None:
    """Trigger background Excalidraw diagram generation.

    Args:
        diagram_name: Filename (e.g. "kien_truc.excalidraw.md").
        source_text: Full response text for context extraction.
    """
    spawn_worker(
        target=_generate_excalidraw,
        args=(diagram_name, source_text),
        name=f"excalidraw-{diagram_name}",
    )


def _generate_excalidraw(diagram_name: str, source_text: str) -> None:
    """Worker function: generate Excalidraw diagram with template-enhanced prompting."""
    context = find_diagram_context(diagram_name, source_text)

    _logger.info(f"Generating Excalidraw: {diagram_name}")
    log("diagram", f"Excalidraw generation started: {diagram_name}")

    # Dynamic template injection via embedding similarity
    prompt = _EXCALIDRAW_PROMPT.format(context=context)
    template = select_template(context, diagram_type="excalidraw")
    if template:
        layout_tag = template.get("layout_tag", "")
        desc = template.get("description", "")
        structure = template.get("example_structure", "")
        prompt += (
            f"\n\nRECOMMENDED LAYOUT based on context analysis:\n"
            f"Diagram type: {desc}\n"
            f"Suggested layout tag: {layout_tag}\n"
            f"Structure guide:\n{structure.strip()}\n"
            f"Follow this structure but ADAPT content to the actual context."
        )
        _logger.info(f"Injected Excalidraw template: {desc[:50]}")

    # Use generic call_llm with task="reasoning"
    # This automatically routes to Tier 1 (Gateway Opus-Thinking) -> Tier 2 (Copilot Sonnet)
    # and enforces the safe 600s reasoning_timeout.
    json_content = call_llm(
        prompt,
        task="reasoning",
    )

    if not json_content:
        log("error", f"Excalidraw generation failed: {diagram_name}")
        return

    # Validate and fix JSON + Extract text
    result = _validate_excalidraw_json(json_content)
    if not result:
        log("error", f"Excalidraw JSON validation failed: {diagram_name}")
        return
        
    json_content, text_elements = result

    # Save as .excalidraw.md
    md_content = _MD_TEMPLATE.format(json_content=json_content, text_content=text_elements)
    save_diagram_file(diagram_name, md_content, "excalidraw")





def _validate_excalidraw_json(raw: str) -> tuple[str, str] | None:
    """Validate and clean Excalidraw JSON output, and extract text elements."""
    # Extract JSON block using regex to ignore any conversational text
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1)
    else:
        # Fallback if no markdown fences: find outermost { }
        start_idx = raw.find('{')
        end_idx = raw.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            raw = raw[start_idx:end_idx+1]

    try:
        data = json.loads(raw)

        # Ensure required fields
        if "type" not in data:
            data["type"] = "excalidraw"
        if "version" not in data:
            data["version"] = 2
        
        elements = data.get("elements", [])
        new_elements = []
        containers = {el["id"]: el for el in elements if "id" in el}

        for elem in elements:
            # 1. Heal: Extract "text" property from shapes into a separate text element
            if elem.get("type") in ("rectangle", "ellipse", "diamond") and "text" in elem:
                text_val = elem.pop("text")
                text_id = elem["id"] + "_text"
                
                text_elem = {
                    "type": "text",
                    "id": text_id,
                    "x": elem.get("x", 0) + 10,
                    "y": elem.get("y", 0) + 10,
                    "width": elem.get("width", 100) - 20,
                    "height": 20,
                    "text": text_val,
                    "fontSize": 16,
                    "fontFamily": 3,
                    "textAlign": "center",
                    "verticalAlign": "middle",
                    "containerId": elem["id"]
                }
                new_elements.append(text_elem)
                
                if "boundElements" not in elem or not elem["boundElements"]:
                    elem["boundElements"] = []
                elem["boundElements"].append({"id": text_id, "type": "text"})
            
            # 2. Heal: Ensure all text elements have required properties
            if elem.get("type") == "text":
                if "fontSize" not in elem: elem["fontSize"] = 16
                if "fontFamily" not in elem: elem["fontFamily"] = 3
                if "textAlign" not in elem: elem["textAlign"] = "center"
                if "verticalAlign" not in elem: elem["verticalAlign"] = "middle"
                if "width" not in elem: elem["width"] = 100
                if "height" not in elem: elem["height"] = 20
                if "x" not in elem: elem["x"] = 0
                if "y" not in elem: elem["y"] = 0

                # Auto-bind if not bound properly
                c_id = elem.get("containerId")
                if c_id and c_id in containers:
                    c = containers[c_id]
                    if "boundElements" not in c or not c["boundElements"]:
                        c["boundElements"] = []
                    
                    # Fix: Handle cases where boundElements contains None or strings instead of dicts
                    cleaned_bounds = []
                    for b in c["boundElements"]:
                        if isinstance(b, dict):
                            cleaned_bounds.append(b)
                        elif isinstance(b, str):
                            cleaned_bounds.append({"id": b, "type": "text"})
                    c["boundElements"] = cleaned_bounds
                    
                    if not any(b.get("id") == elem["id"] for b in c["boundElements"]):
                        c["boundElements"].append({"id": elem["id"], "type": "text"})

            new_elements.append(elem)
            
        import textwrap
        # Apply automatic text wrapping for text nodes
        for elem in new_elements:
            if elem.get("type") == "text" and "text" in elem:
                text = elem["text"]
                # Approximate container width based on element width or default 150
                w = float(elem.get("width", 150))
                # Approx 8 pixels per character for fontSize 16
                max_chars = max(10, int(w / 8))
                
                # Split by existing newlines to respect manual breaks
                lines = text.split("\n")
                wrapped_lines = []
                for line in lines:
                    if len(line) > max_chars:
                        wrapped_lines.extend(textwrap.wrap(line, width=max_chars))
                    else:
                        wrapped_lines.append(line)
                elem["text"] = "\n".join(wrapped_lines)

                # Recalculate height based on actual line count after wrapping
                num_lines = len(wrapped_lines)
                font_size = elem.get("fontSize", 16)
                line_height = font_size * 1.25  # Excalidraw default line spacing
                elem["height"] = num_lines * line_height
            
        # Apply deterministic layout engine via Central Router
        from core.layout_router import apply_smart_layout
        apply_smart_layout(new_elements)
            
        data["elements"] = new_elements

        # Extract text elements for Obsidian markdown compatibility
        text_blocks = []
        for elem in new_elements:
            if elem.get("type") == "text" and "text" in elem and "id" in elem:
                text_blocks.append(f"{elem['text']}\n^{elem['id']}")
        text_content = "\n\n".join(text_blocks)

        return json.dumps(data, ensure_ascii=False, indent=2), text_content
    except (json.JSONDecodeError, TypeError) as e:
        _logger.warning(f"Excalidraw JSON invalid: {e}")
        return None
