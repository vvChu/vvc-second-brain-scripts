"""VvC Second Brain — Excalidraw Worker (v8.0 — Template-Enhanced).

Generates Excalidraw JSON diagrams via Copilot CLI (claude-sonnet for spatial reasoning).
Saves as .excalidraw.md files compatible with Obsidian Excalidraw plugin.

Usage:
    from services.excalidraw_worker import trigger_excalidraw_generation
    trigger_excalidraw_generation("kien_truc.excalidraw.md", context_text)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any

from core.config import cfg
from core.log import log
from core.llm import call_llm
from services.diagram_base import (
    find_diagram_context,
    spawn_worker,
    save_diagram_file,
    save_fallback_diagram,
    select_template,
)

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
        save_fallback_diagram(diagram_name, "Lỗi kết nối hoặc LLM không trả về phản hồi", "excalidraw")
        return

    # Validate and fix JSON + Extract text
    result = _validate_excalidraw_json(json_content)
    if not result:
        log("error", f"Excalidraw JSON validation failed: {diagram_name}")
        save_fallback_diagram(diagram_name, "Lỗi cú pháp JSON Excalidraw", "excalidraw")
        return
        
    json_content, text_elements = result

    # Save as .excalidraw.md
    md_content = _MD_TEMPLATE.format(json_content=json_content, text_content=text_elements)
    save_diagram_file(diagram_name, md_content, "excalidraw")





def _ensure_nanoid_8(raw_id: str, seen_ids: set[str] | None = None) -> str:
    """Ensure element ID is strictly 8 characters [a-zA-Z0-9_-] for Obsidian Excalidraw parser."""
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "", raw_id)
    if len(clean) == 8 and (seen_ids is None or clean not in seen_ids):
        if seen_ids is not None:
            seen_ids.add(clean)
        return clean

    base = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:8]
    candidate = base
    counter = 0
    if seen_ids is not None:
        while candidate in seen_ids:
            counter += 1
            candidate = hashlib.sha256(f"{raw_id}_{counter}".encode("utf-8")).hexdigest()[:8]
        seen_ids.add(candidate)
    return candidate


def _is_enclosing_container(shape: dict[str, Any], elements: list[dict[str, Any]]) -> bool:
    """Check if shape geometrically encloses another shape (subgraph container)."""
    if shape.get("type") not in ("rectangle", "ellipse", "diamond"):
        return False
    sx, sy = float(shape.get("x") or 0), float(shape.get("y") or 0)
    sw, sh = float(shape.get("width") or 100), float(shape.get("height") or 100)
    for o in elements:
        if o is not shape and o.get("type") in ("rectangle", "ellipse", "diamond"):
            ox, oy = float(o.get("x") or 0), float(o.get("y") or 0)
            ow, oh = float(o.get("width") or 50), float(o.get("height") or 50)
            if sx <= ox and sy <= oy and (sx + sw) >= (ox + ow) and (sy + sh) >= (oy + oh) and (sw * sh > ow * oh * 1.5):
                return True
    return False


def _create_shape_text_element(elem: dict[str, Any], is_enclosing: bool, text_val: str) -> dict[str, Any]:
    """Create a detached header or bound text element from shape text property."""
    text_id = _ensure_nanoid_8(f"t_{elem['id']}")
    if is_enclosing:
        return {
            "type": "text", "id": text_id, "x": elem.get("x", 0),
            "y": (elem.get("y") or 0) + 14, "width": elem.get("width", 100),
            "height": 36, "text": text_val, "fontSize": 13, "fontFamily": 3,
            "textAlign": "center", "verticalAlign": "top", "containerId": None,
            "containerHeaderOf": elem["id"],
        }
    elem.setdefault("boundElements", []).append({"id": text_id, "type": "text"})
    return {
        "type": "text", "id": text_id, "x": (elem.get("x") or 0) + 10,
        "y": (elem.get("y") or 0) + 10, "width": (elem.get("width") or 100) - 20,
        "height": 20, "text": text_val, "fontSize": 16, "fontFamily": 3,
        "textAlign": "center", "verticalAlign": "middle", "containerId": elem["id"],
    }


def _heal_text_element(elem: dict[str, Any], containers: dict[str, Any], elements: list[dict[str, Any]]) -> None:
    """Ensure text element has default properties and valid container binding."""
    for prop, default in [("fontSize", 16), ("fontFamily", 3), ("textAlign", "center"),
                          ("verticalAlign", "middle"), ("width", 100), ("height", 20), ("x", 0), ("y", 0)]:
        elem.setdefault(prop, default)

    c_id = elem.get("containerId")
    if not c_id:
        for cid, cand in containers.items():
            b_list = cand.get("boundElements") or []
            if any((b.get("id") if isinstance(b, dict) else b) == elem.get("id") for b in b_list):
                c_id = cid
                elem["containerId"] = cid
                break

    if c_id and c_id in containers:
        c = containers[c_id]
        if _is_enclosing_container(c, elements):
            elem["containerId"] = None
            elem["verticalAlign"] = "top"
            elem["y"] = (c.get("y") or 0) + 14
            elem["containerHeaderOf"] = c.get("id")
            if "boundElements" in c and isinstance(c["boundElements"], list):
                c["boundElements"] = [b for b in c["boundElements"] if (b.get("id") if isinstance(b, dict) else b) != elem["id"]]
        else:
            bounds = [{"id": b, "type": "text"} if isinstance(b, str) else b for b in c.get("boundElements") or []]
            c["boundElements"] = bounds
            if not any(b.get("id") == elem["id"] for b in bounds):
                bounds.append({"id": elem["id"], "type": "text"})


def _remap_element_ids(new_elements: list[dict[str, Any]]) -> None:
    """Normalize text IDs to strictly 8 chars and update referencing bindings."""
    seen_ids: set[str] = {el["id"] for el in new_elements if "id" in el and len(el["id"]) == 8 and re.match(r"^[a-zA-Z0-9_\-]+$", el["id"])}
    id_map: dict[str, str] = {}
    for el in new_elements:
        if el.get("type") == "text" and "id" in el:
            old_id = el["id"]
            if len(old_id) != 8 or not re.match(r"^[a-zA-Z0-9_\-]+$", old_id):
                new_id = _ensure_nanoid_8(old_id, seen_ids)
                id_map[old_id] = new_id
                el["id"] = new_id

    if not id_map:
        return
    for el in new_elements:
        if "boundElements" in el and isinstance(el["boundElements"], list):
            for b in el["boundElements"]:
                if isinstance(b, dict) and b.get("id") in id_map:
                    b["id"] = id_map[b["id"]]
        if el.get("type") == "arrow":
            for bind_key in ("startBinding", "endBinding"):
                b_val = el.get(bind_key)
                if isinstance(b_val, dict) and b_val.get("elementId") in id_map:
                    b_val["elementId"] = id_map[b_val["elementId"]]


def _wrap_and_fit_texts(new_elements: list[dict[str, Any]], containers: dict[str, Any]) -> None:
    """Wrap text strings and auto-expand container heights."""
    for elem in new_elements:
        if elem.get("type") == "text" and "text" in elem:
            w = float(elem.get("width") or 150)
            max_chars = max(10, int(w / 8))
            lines = [wrapped for line in elem["text"].split("\n") for wrapped in (textwrap.wrap(line, width=max_chars) or [""])]
            elem["text"] = "\n".join(lines)
            line_height = float(elem.get("fontSize") or 16) * 1.35
            elem["height"] = len(lines) * line_height

            c_id = elem.get("containerId")
            if c_id and c_id in containers:
                c = containers[c_id]
                min_h = elem["height"] + 30.0
                if float(c.get("height") or 0.0) < min_h:
                    c["height"] = min_h


def _validate_excalidraw_json(raw: str) -> tuple[str, str] | None:
    """Validate and clean Excalidraw JSON output, and extract text elements."""
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    raw_json = json_match.group(1) if json_match else raw
    if not json_match:
        s, e = raw_json.find('{'), raw_json.rfind('}')
        if s != -1 and e != -1 and e > s:
            raw_json = raw_json[s:e+1]

    try:
        data = json.loads(raw_json)
        data.setdefault("type", "excalidraw")
        data.setdefault("version", 2)

        elements = data.get("elements", [])
        containers = {el["id"]: el for el in elements if "id" in el}
        new_elements: list[dict[str, Any]] = []

        for elem in elements:
            if elem.get("type") in ("rectangle", "ellipse", "diamond") and "text" in elem:
                text_val = elem.pop("text")
                is_enclosing = _is_enclosing_container(elem, elements)
                new_elements.append(_create_shape_text_element(elem, is_enclosing, text_val))
            if elem.get("type") == "text":
                _heal_text_element(elem, containers, elements)
            new_elements.append(elem)

        _remap_element_ids(new_elements)
        _wrap_and_fit_texts(new_elements, containers)

        from core.layout_router import apply_smart_layout
        from services.diagram_base import normalize_canvas_bounding_box
        apply_smart_layout(new_elements)
        normalize_canvas_bounding_box(new_elements)

        data["elements"] = new_elements
        text_blocks = [f"{el['text']} ^{el['id']}" for el in new_elements if el.get("type") == "text" and "text" in el and "id" in el]
        return json.dumps(data, ensure_ascii=False, indent=2), "\n\n".join(text_blocks)
    except (json.JSONDecodeError, TypeError) as e:
        _logger.warning(f"Excalidraw JSON invalid: {e}")
        return None


# Canonical public alias for validating and repairing Excalidraw JSON
clean_and_repair_excalidraw_json = _validate_excalidraw_json
