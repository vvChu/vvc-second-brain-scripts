"""VvC Second Brain — Shared Diagram Generation Infrastructure (v7.0).

Common utilities for Excalidraw and Mermaid diagram workers.
Handles placeholder scanning, vision image retrieval, and threaded spawning.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from core.config import cfg

_logger = logging.getLogger("vvc.diagram")


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


def find_diagram_context(diagram_name: str, source_text: str) -> str:
    """Extract context around a diagram placeholder from the source text.

    Args:
        diagram_name: e.g. "kien_truc.excalidraw.md"
        source_text: Full response text containing the placeholder.

    Returns:
        Surrounding context (±500 chars around the placeholder).
    """
    placeholder = f"![[{diagram_name}]]"
    idx = source_text.find(placeholder)
    if idx < 0:
        return source_text[:1000]

    start = max(0, idx - 500)
    end = min(len(source_text), idx + len(placeholder) + 500)
    return source_text[start:end]


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
    output_path = cfg.attachments_dir / diagram_name
    try:
        output_path.write_text(md_content, encoding="utf-8")
        _logger.info(f"{diagram_type.capitalize()} saved: {output_path.name}")
        from core.log import log
        log("diagram", f"{diagram_type.capitalize()} created: {diagram_name}")
    except OSError as e:
        _logger.error(f"Failed to save {diagram_type}: {e}")


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

