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





def _ensure_nanoid_8(raw_id: str) -> str:
    """Ensure element ID is strictly 8 alphanumeric characters for Obsidian Excalidraw parser."""
    import hashlib
    clean = re.sub(r"[^a-zA-Z0-9]", "", raw_id)
    if len(clean) == 8:
        return clean
    if len(clean) > 8:
        return clean[:8]
    h = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
    return (clean + h)[:8]


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

        def _is_enclosing_container(shape: dict) -> bool:
            if shape.get("type") not in ("rectangle", "ellipse", "diamond"):
                return False
            sx, sy = shape.get("x", 0), shape.get("y", 0)
            sw, sh = shape.get("width", 100), shape.get("height", 100)
            for o in elements:
                if o is not shape and o.get("type") in ("rectangle", "ellipse", "diamond"):
                    ox, oy = o.get("x", 0), o.get("y", 0)
                    ow, oh = o.get("width", 50), o.get("height", 50)
                    if sx <= ox and sy <= oy and (sx + sw) >= (ox + ow) and (sy + sh) >= (oy + oh) and (sw * sh > ow * oh * 1.5):
                        return True
            return False

        for elem in elements:
            # 1. Heal: Extract "text" property from shapes into a separate text element
            if elem.get("type") in ("rectangle", "ellipse", "diamond") and "text" in elem:
                text_val = elem.pop("text")
                text_id = _ensure_nanoid_8(f"t_{elem['id']}")
                is_enclosing = _is_enclosing_container(elem)
                
                if is_enclosing:
                    text_elem = {
                        "type": "text",
                        "id": text_id,
                        "x": elem.get("x", 0),
                        "y": elem.get("y", 0) + 14,
                        "width": elem.get("width", 100),
                        "height": 36,
                        "text": text_val,
                        "fontSize": 13,
                        "fontFamily": 3,
                        "textAlign": "center",
                        "verticalAlign": "top",
                        "containerId": None
                    }
                    new_elements.append(text_elem)
                else:
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
                    # If container is an enclosing subgraph frame, unbind to prevent middle centering
                    if _is_enclosing_container(c):
                        elem["containerId"] = None
                        elem["verticalAlign"] = "top"
                        elem["y"] = c.get("y", 0) + 14
                        if "boundElements" in c and isinstance(c["boundElements"], list):
                            c["boundElements"] = [b for b in c["boundElements"] if (b.get("id") if isinstance(b, dict) else b) != elem["id"]]
                    else:
                        if "boundElements" not in c or not c["boundElements"]:
                            c["boundElements"] = []
                        
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
            
        # Normalize all text element IDs strictly to 8 alphanumeric characters
        id_map = {}
        for elem in new_elements:
            if elem.get("type") == "text" and "id" in elem:
                old_id = elem["id"]
                if len(old_id) != 8:
                    new_id = _ensure_nanoid_8(old_id)
                    id_map[old_id] = new_id
                    elem["id"] = new_id

        if id_map:
            for elem in new_elements:
                if "boundElements" in elem and isinstance(elem["boundElements"], list):
                    for b in elem["boundElements"]:
                        if isinstance(b, dict) and b.get("id") in id_map:
                            b["id"] = id_map[b["id"]]

        import textwrap
        # Apply automatic text wrapping for text nodes
        for elem in new_elements:
            if elem.get("type") == "text" and "text" in elem:
                text = elem["text"]
                w = float(elem.get("width", 150))
                max_chars = max(10, int(w / 8))
                
                lines = text.split("\n")
                wrapped_lines = []
                for line in lines:
                    if len(line) > max_chars:
                        wrapped_lines.extend(textwrap.wrap(line, width=max_chars))
                    else:
                        wrapped_lines.append(line)
                elem["text"] = "\n".join(wrapped_lines)

                num_lines = len(wrapped_lines)
                font_size = elem.get("fontSize", 16)
                line_height = font_size * 1.25
                elem["height"] = num_lines * line_height
            
        # Apply deterministic layout engine via Central Router
        from core.layout_router import apply_smart_layout
        apply_smart_layout(new_elements)
            
        data["elements"] = new_elements

        # Extract text elements for Obsidian markdown compatibility
        text_blocks = []
        for elem in new_elements:
            if elem.get("type") == "text" and "text" in elem and "id" in elem:
                text_blocks.append(f"{elem['text']} ^{elem['id']}")
        text_content = "\n\n".join(text_blocks)

        return json.dumps(data, ensure_ascii=False, indent=2), text_content
    except (json.JSONDecodeError, TypeError) as e:
        _logger.warning(f"Excalidraw JSON invalid: {e}")
        return None
