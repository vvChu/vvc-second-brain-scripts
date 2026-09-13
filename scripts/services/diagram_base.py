"""VvC Second Brain — Shared Diagram Generation Infrastructure (v7.0).

Common utilities for Excalidraw and Mermaid diagram workers.
Handles placeholder scanning, vision image retrieval, and threaded spawning.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any

from core.config import cfg
from services.moc_mermaid import sanitize_mermaid, wrap_label

_logger = logging.getLogger("vvc.diagram")

__all__ = [
    "get_shape_boundary_point",
    "sync_bound_text_translation",
    "normalize_canvas_bounding_box",
    "compute_safe_arrow_endpoints",
    "find_diagram_context",
    "resolve_chapter_images",
    "spawn_worker",
    "save_diagram_file",
    "save_fallback_diagram",
    "load_templates",
    "select_template",
    "wrap_label",
    "sanitize_mermaid",
]


def get_shape_boundary_point(shape: dict, dx: float, dy: float) -> tuple[float, float]:
    """Compute the exact boundary point of a shape along direction (dx, dy) from center.

    Replaces the approximate ``min(w, h) / 2`` radius used for arrow trimming.
    Supports rectangle/diamond (axis-aligned box clipping) and ellipse (parametric).

    Args:
        shape: Excalidraw element dict with ``x``, ``y``, ``width``, ``height``, ``type``.
        dx: X component of direction vector (need not be normalised).
        dy: Y component of direction vector.

    Returns:
        ``(bx, by)`` — the point on the shape boundary in the given direction.
        The caller should add a small gap (e.g. +5px outward) before using as arrow origin.
    """
    import math

    cx = float(shape.get("x", 0)) + float(shape.get("width", 150)) / 2
    cy = float(shape.get("y", 0)) + float(shape.get("height", 100)) / 2
    hw = float(shape.get("width", 150)) / 2
    hh = float(shape.get("height", 100)) / 2

    dist = math.hypot(dx, dy)
    if dist == 0 or hw == 0 or hh == 0:
        return cx, cy

    ndx = dx / dist
    ndy = dy / dist

    if shape.get("type") == "ellipse":
        # Parametric ellipse: solve (ndx*t/hw)² + (ndy*t/hh)² = 1
        denom = math.sqrt((ndx / hw) ** 2 + (ndy / hh) ** 2)
        t = 1.0 / denom if denom > 0 else min(hw, hh)
    else:
        # Rectangle (and diamond treated as bounding-box rectangle)
        tx = hw / abs(ndx) if abs(ndx) > 1e-9 else float("inf")
        ty = hh / abs(ndy) if abs(ndy) > 1e-9 else float("inf")
        t = min(tx, ty)

    return cx + ndx * t, cy + ndy * t


def sync_bound_text_translation(
    shape: dict[str, Any],
    elements: list[dict[str, Any]],
    dx: float,
    dy: float,
) -> None:
    """Synchronously translate bound text elements for a shape.

    Checks both shape.get("boundElements", []) and any element with
    el.get("containerId") == shape["id"], translating text elements synchronously.

    Args:
        shape: Shape element dict being translated.
        elements: Full list of diagram elements.
        dx: Horizontal displacement.
        dy: Vertical displacement.
    """
    sid = shape.get("id")
    if not sid:
        return

    bound_text_ids = set()
    for bound in shape.get("boundElements", []):
        if isinstance(bound, dict) and bound.get("type") == "text" and bound.get("id"):
            bound_text_ids.add(bound["id"])

    for el in elements:
        if el.get("type") != "text":
            continue
        el_id = el.get("id")
        is_bound = (
            (el_id and el_id in bound_text_ids)
            or (el.get("containerId") == sid)
            or (el.get("containerHeaderOf") == sid)
        )
        if is_bound:
            el["x"] = float(el.get("x", 0.0) + dx)
            el["y"] = float(el.get("y", 0.0) + dy)
            if not el.get("strokeColor"):
                el["strokeColor"] = cfg.excalidraw_stroke_color
            if not el.get("fontFamily"):
                el["fontFamily"] = cfg.excalidraw_font_family


def normalize_canvas_bounding_box(
    elements: list[dict[str, Any]],
    min_padding_x: float = 80.0,
    min_padding_y: float = 60.0,
) -> None:
    """Shift all canvas elements to safe positive coordinates if clipping occurs.

    Accounts for shapes, text, and arrow bend points (points array).

    Args:
        elements: List of Excalidraw element dicts.
        min_padding_x: Minimum x coordinate (default 80.0).
        min_padding_y: Minimum y coordinate (default 60.0).
    """
    if not elements:
        return

    min_x = float("inf")
    min_y = float("inf")

    for el in elements:
        if "x" not in el or "y" not in el:
            continue
        el_x = float(el.get("x", 0.0))
        el_y = float(el.get("y", 0.0))

        if el.get("type") == "arrow" and "points" in el:
            pts = el["points"]
            if isinstance(pts, list) and pts:
                p_xs = [el_x + float(p[0]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                p_ys = [el_y + float(p[1]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                if p_xs:
                    min_x = min(min_x, min(p_xs))
                if p_ys:
                    min_y = min(min_y, min(p_ys))
        else:
            min_x = min(min_x, el_x)
            min_y = min(min_y, el_y)

    if min_x == float("inf") or min_y == float("inf"):
        return

    shift_x = 0.0
    shift_y = 0.0
    if min_x < min_padding_x:
        shift_x = min_padding_x - min_x
    if min_y < min_padding_y:
        shift_y = min_padding_y - min_y

    if shift_x > 0.0 or shift_y > 0.0:
        for el in elements:
            if "x" in el:
                el["x"] = float(el.get("x", 0.0) + shift_x)
            if "y" in el:
                el["y"] = float(el.get("y", 0.0) + shift_y)


def compute_safe_arrow_endpoints(
    s_shape: dict[str, Any],
    e_shape: dict[str, Any],
) -> tuple[float, float, float, float]:
    """Compute safe arrow start and end points between two shapes.

    Extracts boundaries via get_shape_boundary_point, enforces safety distance
    dot > 12.0 with adaptive padding min(5.0, (dot - 2.0) / 2.0) to prevent
    inverted arrows or crushed arrowhead blobs.

    Args:
        s_shape: Source shape dict.
        e_shape: Target shape dict.

    Returns:
        tuple (start_x, start_y, end_x, end_y) of safe endpoints.
    """
    import math

    sx = float(s_shape.get("x", 0.0)) + float(s_shape.get("width", 150.0)) / 2.0
    sy = float(s_shape.get("y", 0.0)) + float(s_shape.get("height", 100.0)) / 2.0
    ex = float(e_shape.get("x", 0.0)) + float(e_shape.get("width", 150.0)) / 2.0
    ey = float(e_shape.get("y", 0.0)) + float(e_shape.get("height", 100.0)) / 2.0

    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist > 0:
        bsx, bsy = get_shape_boundary_point(s_shape, dx, dy)
        bex, bey = get_shape_boundary_point(e_shape, -dx, -dy)
        dot = (bex - bsx) * (dx / dist) + (bey - bsy) * (dy / dist)
        if dot > 12.0:
            padding = min(5.0, (dot - 2.0) / 2.0)
            start_x = bsx + (dx / dist) * padding
            start_y = bsy + (dy / dist) * padding
            end_x = bex - (dx / dist) * padding
            end_y = bey - (dy / dist) * padding
        elif dot > 0:
            start_x, start_y = bsx, bsy
            end_x, end_y = bex, bey
        else:
            start_x, start_y, end_x, end_y = sx, sy, ex, ey
    else:
        start_x, start_y, end_x, end_y = sx, sy, ex, ey

    return float(start_x), float(start_y), float(end_x), float(end_y)


def find_diagram_context(diagram_name: str, source_text: str) -> str:
    """Extract context around a diagram placeholder from the source text.

    Implements Dual-Scope Context:
    - Locates the section containing the placeholder (tagged with === [TARGET SECTION (Trọng tâm sơ đồ)] ===)
    - Provides full response context up to 12,000 characters (tagged with === [FULL ARTICLE CONTEXT (Toàn bộ bài viết tham chiếu)] ===)
    If no headings are found in source_text, falls back to ±500 chars around the placeholder.
    If placeholder not found, falls back to searching for the nearest section heading matching diagram name keywords before defaulting to source_text[:1000].

    Args:
        diagram_name: e.g. "kien_truc.excalidraw.md"
        source_text: Full response text containing the placeholder.

    Returns:
        Dual-scope or surrounding context string.
    """
    target_name = Path(diagram_name).name
    escaped_targets = [re.escape(target_name)]
    if target_name.endswith(".excalidraw.md"):
        escaped_targets.append(re.escape(target_name[:-14] + "_excalidraw_md"))
        escaped_targets.append(re.escape(target_name[:-3]))  # .excalidraw
    elif target_name.endswith(".mermaid.md"):
        escaped_targets.append(re.escape(target_name[:-11] + "_mermaid_md"))
        escaped_targets.append(re.escape(target_name[:-3]))  # .mermaid
    elif target_name.endswith(".d2.svg"):
        escaped_targets.append(re.escape(target_name[:-7] + "_d2_svg"))
        escaped_targets.append(re.escape(target_name[:-4]))  # .d2
    elif target_name.endswith(".excalidraw"):
        escaped_targets.append(re.escape(target_name + ".md"))
        escaped_targets.append(re.escape(target_name + "_md"))
    elif target_name.endswith(".mermaid"):
        escaped_targets.append(re.escape(target_name + ".md"))
        escaped_targets.append(re.escape(target_name + "_md"))
    elif target_name.endswith(".d2"):
        escaped_targets.append(re.escape(target_name + ".svg"))
        escaped_targets.append(re.escape(target_name + "_svg"))

    target_pattern = "|".join(escaped_targets)
    pattern = re.compile(rf"!\[\[(?:{target_pattern})(?:\|[^\]]*)?\]\]")
    match = pattern.search(source_text)
    if match:
        headings = list(re.finditer(r"^(#{1,6}\s+.*?)$", source_text, flags=re.MULTILINE))
        if headings:
            prev_h = None
            next_h = None
            for h in headings:
                if h.start() <= match.start():
                    prev_h = h
                elif h.start() > match.start() and next_h is None:
                    next_h = h
                    break

            sec_start = prev_h.start() if prev_h is not None else 0
            sec_end = next_h.start() if next_h is not None else len(source_text)
            target_section = source_text[sec_start:sec_end].strip()
            full_context = source_text[:12000].strip()
            return (
                f"=== [TARGET SECTION (Trọng tâm sơ đồ)] ===\n"
                f"{target_section}\n\n"
                f"=== [FULL ARTICLE CONTEXT (Toàn bộ bài viết tham chiếu)] ===\n"
                f"{full_context}"
            )
        else:
            start = max(0, match.start() - 500)
            end = min(len(source_text), match.end() + 500)
            return source_text[start:end]

    # Fallback: search for the section heading matching the most diagram keywords
    stem = re.sub(
        r"\.(excalidraw\.md|mermaid\.md|d2\.svg|excalidraw|mermaid|d2|svg|md)$",
        "",
        target_name,
        flags=re.IGNORECASE,
    )
    keywords = [w.lower() for w in re.split(r"[_\-\s]+", stem) if len(w) >= 2]

    if keywords:
        headings = list(re.finditer(r"^(#{1,6}\s+.*?)$", source_text, flags=re.MULTILINE))
        best_heading = None
        best_score = 0
        for h in headings:
            h_text = h.group(1).lower()
            score = sum(1 for kw in keywords if kw in h_text)
            if score > best_score:
                best_score = score
                best_heading = h
        if best_heading is not None and best_score > 0:
            h_start = best_heading.start()
            return source_text[h_start : min(len(source_text), h_start + 1000)]

    return source_text[:1000]


def resolve_chapter_images(
    chapter: str,
    book_name: str,
    max_images: int = 3,
) -> list[Path]:
    """Find relevant source images for a chapter via TOC mapping.

    Args:
        chapter: Chapter file stem (e.g. "05_CHAPTER 1").
        book_name: Book workspace folder name.
        max_images: Max images to return.

    Returns:
        List of image paths from the archive.
    """
    archive_dir = cfg.archive_dir / book_name
    if not archive_dir.exists():
        return []

    # Find images with chapter prefix
    images = []
    ch_match = re.search(r"(\d+)", chapter)
    ch_num = ch_match.group(1) if ch_match else ""

    for img in archive_dir.iterdir():
        if img.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            if ch_num and f"ch{ch_num}" in img.name.lower():
                images.append(img)

    return sorted(images)[:max_images]


def spawn_worker(target: callable, args: tuple, name: str = "diagram") -> None:
    """Spawn a background thread for diagram generation.

    Args:
        target: Worker function.
        args: Arguments for the worker.
        name: Thread name for logging.
    """
    thread = threading.Thread(target=target, args=args, daemon=True, name=name)
    thread.start()
    _logger.info(f"Spawned {name} worker thread")

def save_diagram_file(diagram_name: str, md_content: str, diagram_type: str) -> None:
    """Save diagram markdown content to the attachments directory."""
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', diagram_name)
    output_path = cfg.attachments_dir / safe_name
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md_content, encoding="utf-8")
        _logger.info(f"{diagram_type.capitalize()} saved: {output_path.name}")
        from core.log import log
        log("diagram", f"{diagram_type.capitalize()} created: {safe_name}")
    except OSError as e:
        _logger.error(f"Failed to save {diagram_type}: {e}")


def save_fallback_diagram(diagram_name: str, error_reason: str, diagram_type: str) -> None:
    """Save a minimal, valid warning diagram file to prevent broken links in Obsidian.

    Creates an error/warning placeholder for Mermaid, Excalidraw, or D2 diagrams
    when generation or validation fails.

    Args:
        diagram_name: Filename of target diagram (e.g. "flow.mermaid.md", "arch.excalidraw.md", "sys.d2.svg").
        error_reason: Human-readable error reason for display.
        diagram_type: Diagram engine type ("mermaid", "excalidraw", or "d2").
    """
    clean_error = error_reason.replace('"', "'").strip()

    if diagram_type.lower() == "mermaid":
        clean_title = Path(diagram_name).name
        for ext in (".mermaid.md", ".mermaid", ".md"):
            if clean_title.endswith(ext):
                clean_title = clean_title[:-len(ext)]
                break
        clean_title = clean_title.replace("_", " ").title()

        safe_title = sanitize_mermaid(clean_title)
        safe_error = clean_error.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")

        mermaid_code = (
            "flowchart TD\n"
            f'    err["⚠️ Không thể khởi tạo sơ đồ: {safe_title}<br/><i>{safe_error}</i>"]\n'
            "    style err fill:#fee2e2,stroke:#ef4444,stroke-width:2px,color:#991b1b;\n"
        )
        md_content = f"```mermaid\n{mermaid_code}```\n"
        save_diagram_file(diagram_name, md_content, "mermaid")

    elif diagram_type.lower() == "excalidraw":
        clean_title = Path(diagram_name).name
        for ext in (".excalidraw.md", ".excalidraw", ".md"):
            if clean_title.endswith(ext):
                clean_title = clean_title[:-len(ext)]
                break
        clean_title = clean_title.replace("_", " ").title()

        card_id = "carderr1"
        text_id = "texterr1"
        text_label = f"⚠️ Sơ đồ: {clean_title}\n{clean_error}"

        elements = [
            {
                "id": card_id,
                "type": "rectangle",
                "x": 100,
                "y": 100,
                "width": 380,
                "height": 100,
                "angle": 0,
                "strokeColor": "#ef4444",
                "backgroundColor": "#fee2e2",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "dashed",
                "roughness": 1,
                "opacity": 100,
                "groupIds": [],
                "roundness": {"type": 3},
                "seed": 1000,
                "version": 1,
                "versionNonce": 1,
                "isDeleted": False,
                "boundElements": [{"id": text_id, "type": "text"}],
            },
            {
                "id": text_id,
                "type": "text",
                "x": 120,
                "y": 125,
                "width": 340,
                "height": 50,
                "angle": 0,
                "strokeColor": "#991b1b",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "roughness": 1,
                "opacity": 100,
                "groupIds": [],
                "roundness": None,
                "seed": 1001,
                "version": 1,
                "versionNonce": 1,
                "isDeleted": False,
                "boundElements": None,
                "text": text_label,
                "fontSize": 16,
                "fontFamily": 3,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": card_id,
                "originalText": text_label,
            },
        ]

        data = {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": elements,
            "appState": {"viewBackgroundColor": "#ffffff", "currentItemFontFamily": 3},
            "files": {},
        }

        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        text_content = f"{text_label} ^{text_id}"

        md_content = (
            "---\n"
            "excalidraw-plugin: parsed\n"
            "tags: [excalidraw]\n"
            "---\n"
            "==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==\n\n"
            "# Excalidraw Data\n\n"
            "## Text Elements\n"
            f"{text_content}\n\n"
            "%%\n"
            "## Drawing\n"
            "```json\n"
            f"{json_str}\n"
            "```\n"
            "%%\n"
        )
        save_diagram_file(diagram_name, md_content, "excalidraw")

    elif diagram_type.lower() == "d2":
        clean_title = Path(diagram_name).name
        for ext in (".d2.svg", ".svg", ".d2"):
            if clean_title.endswith(ext):
                clean_title = clean_title[:-len(ext)]
                break
        clean_title = clean_title.replace("_", " ").title()

        # Save raw .d2 error file alongside
        if diagram_name.endswith(".d2.svg"):
            d2_filename = diagram_name[:-4]
        elif diagram_name.endswith(".svg"):
            d2_filename = diagram_name[:-4] + ".d2"
        else:
            d2_filename = f"{diagram_name}.d2"

        safe_d2_title = clean_title.replace('"', "'")
        safe_d2_error = clean_error.replace('"', "'")
        d2_code = (
            f'error: "⚠️ Không thể khởi tạo sơ đồ: {safe_d2_title}\\n{safe_d2_error}" {{\n'
            '  style: {\n'
            '    fill: "#fee2e2"\n'
            '    stroke: "#ef4444"\n'
            '  }\n'
            '}\n'
        )
        safe_d2_filename = re.sub(r'[<>:"/\\|?*]', '_', d2_filename)
        try:
            d2_path = cfg.attachments_dir / safe_d2_filename
            d2_path.parent.mkdir(parents=True, exist_ok=True)
            d2_path.write_text(d2_code, encoding="utf-8")
        except OSError:
            pass

        # Generate minimal valid standalone SVG with XML entity escaping
        safe_svg_title = html.escape(clean_title, quote=True)
        safe_svg_error = html.escape(clean_error, quote=True)
        svg_content = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="450" height="120" viewBox="0 0 450 120">\n'
            '  <rect x="10" y="10" width="430" height="100" rx="8" fill="#fee2e2" stroke="#ef4444" stroke-width="2" stroke-dasharray="4 4"/>\n'
            f'  <text x="225" y="50" font-family="sans-serif" font-size="14" font-weight="bold" fill="#991b1b" text-anchor="middle">⚠️ Sơ đồ D2: {safe_svg_title}</text>\n'
            f'  <text x="225" y="75" font-family="sans-serif" font-size="12" fill="#7f1d1d" text-anchor="middle">{safe_svg_error}</text>\n'
            '</svg>\n'
        )
        save_diagram_file(diagram_name, svg_content, "d2")
    else:
        _logger.warning(f"Unknown diagram type for fallback: {diagram_type}")



# --- Template Library ---

_TEMPLATES_PATH = Path(__file__).parent.parent / "resources" / "diagram_templates.yaml"
_templates_cache: dict | None = None


def load_templates() -> dict:
    """Load diagram templates from YAML config (cached).

    Returns:
        Dict with 'mermaid' and 'excalidraw' template sections.
    """
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache

    if not _TEMPLATES_PATH.exists():
        _logger.warning(f"Template library not found: {_TEMPLATES_PATH}")
        _templates_cache = {}
        return _templates_cache

    try:
        import yaml
        with open(_TEMPLATES_PATH, encoding="utf-8") as f:
            _templates_cache = yaml.safe_load(f) or {}
        _logger.info(f"Loaded diagram templates: {list(_templates_cache.keys())}")
    except Exception as e:
        _logger.warning(f"Failed to load diagram templates: {e}")
        _templates_cache = {}

    return _templates_cache


def select_template(
    context: str,
    diagram_type: str = "mermaid",
) -> dict | None:
    """Select the best-matching template for the given context.

    Uses embedding similarity via AI Gateway when available,
    falls back to keyword frequency matching.

    Args:
        context: The diagram generation context text.
        diagram_type: 'mermaid' or 'excalidraw'.

    Returns:
        Template dict with 'description', 'example'/'example_structure',
        and 'source'/'layout_tag', or None if no match.
    """
    templates = load_templates()
    section = templates.get(diagram_type, {})
    if not section:
        return None

    # --- Strategy 1: Embedding similarity ---
    best = _select_by_embedding(context, section)
    if best:
        _logger.info(f"Template selected via embedding: {best[0]} (score={best[1]:.3f})")
        return section[best[0]]

    # --- Strategy 2: Keyword frequency fallback ---
    best_kw = _select_by_keywords(context, section)
    if best_kw:
        _logger.info(f"Template selected via keywords: {best_kw}")
        return section[best_kw]

    return None


def _select_by_embedding(
    context: str,
    section: dict,
) -> tuple[str, float] | None:
    """Select template using embedding cosine similarity.

    Args:
        context: Diagram context text.
        section: Template section dict (e.g., templates['mermaid']).

    Returns:
        Tuple of (template_name, similarity_score) or None.
    """
    try:
        import numpy as np
        import requests as req_lib
    except ImportError:
        return None

    if not cfg.gateway_url or not cfg.gateway_api_key:
        return None

    url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {cfg.gateway_api_key}",
        "Content-Type": "application/json",
    }

    # Build texts: context + all template descriptions
    texts_to_embed = [context[:500]]
    template_names = []
    for name, tmpl in section.items():
        desc = tmpl.get("description", "")
        keywords = " ".join(tmpl.get("keywords", []))
        texts_to_embed.append(f"{desc} {keywords}")
        template_names.append(name)

    if not template_names:
        return None

    try:
        payload = {"model": "gemini-embed", "input": texts_to_embed}
        resp = req_lib.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()

        embeddings = [
            np.array(d["embedding"], dtype=np.float32)
            for d in resp.json()["data"]
        ]

        # Normalize all vectors
        for i in range(len(embeddings)):
            norm = np.linalg.norm(embeddings[i])
            if norm > 0:
                embeddings[i] /= norm

        # Cosine similarity: context vs each template
        context_emb = embeddings[0]
        best_name = None
        best_score = 0.0

        for i, name in enumerate(template_names):
            score = float(np.dot(context_emb, embeddings[i + 1]))
            if score > best_score:
                best_score = score
                best_name = name

        # Minimum threshold to avoid random matches
        if best_score >= 0.35:
            return (best_name, best_score)

    except Exception as e:
        _logger.debug(f"Embedding template selection failed: {e}")

    return None


def _select_by_keywords(context: str, section: dict) -> str | None:
    """Fallback: select template by keyword frequency matching.

    Args:
        context: Diagram context text.
        section: Template section dict.

    Returns:
        Best matching template name or None.
    """
    context_lower = context.lower()
    best_name = None
    best_hits = 0

    for name, tmpl in section.items():
        keywords = tmpl.get("keywords", [])
        hits = sum(1 for kw in keywords if kw.lower() in context_lower)
        if hits > best_hits:
            best_hits = hits
            best_name = name

    return best_name if best_hits >= 2 else None

