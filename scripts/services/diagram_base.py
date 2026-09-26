"""VvC Second Brain — Shared Diagram Generation Infrastructure (v8.15.14).

Common utilities for Excalidraw, Mermaid, and D2 diagram workers.
Handles placeholder scanning, vision image retrieval, and threaded spawning.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from core.config import cfg
from services.diagram_fallback import (
    save_fallback_diagram as _save_fallback_diagram_impl,
)
from services.diagram_geometry import (
    compute_safe_arrow_endpoints,
    get_shape_boundary_point,
    normalize_canvas_bounding_box,
    sync_bound_text_translation,
)
from services.diagram_templates import load_templates, select_template

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


def wrap_label(text: str, max_chars: int | None = None) -> str:
    """Wrap label text at word boundaries using <br> for neat layout in Mermaid nodes."""
    if max_chars is None:
        L = len(text)
        max_chars = 20 if L <= 20 else min(25, 20 + (L - 20) // 5)

    words = text.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0

    for word in words:
        added_len = len(word) + (1 if current_line else 0)
        if current_len + added_len > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
        else:
            current_line.append(word)
            current_len += added_len

    if current_line:
        lines.append(" ".join(current_line))

    return "<br>".join(lines)


def sanitize_mermaid(text: str) -> str:
    """Escape characters that break Mermaid syntax."""
    return (
        text.replace('"', "'")
        .replace("(", "❨")
        .replace(")", "❩")
        .replace("[", "❲")
        .replace("]", "❳")
        .replace("{", "❴")
        .replace("}", "❵")
        .replace("<", "‹")
        .replace(">", "›")
        .replace("&", "+")
        .replace("#", "Nr")
    )


def save_diagram_file(diagram_name: str, md_content: str, diagram_type: str) -> None:
    """Save diagram markdown content to the attachments directory."""
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", diagram_name)
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
    """Save a minimal, valid warning diagram file to prevent broken links in Obsidian."""
    _save_fallback_diagram_impl(
        diagram_name,
        error_reason,
        diagram_type,
        save_diagram_file,
        attachments_dir=cfg.attachments_dir,
    )


def _build_placeholder_pattern(diagram_name: str) -> re.Pattern:
    """Build regex pattern matching diagram embeds across extensions."""
    target_name = Path(diagram_name).name
    escaped_targets = [re.escape(target_name)]
    if target_name.endswith(".excalidraw.md"):
        escaped_targets.append(re.escape(target_name[:-14] + "_excalidraw_md"))
        escaped_targets.append(re.escape(target_name[:-3]))
    elif target_name.endswith(".mermaid.md"):
        escaped_targets.append(re.escape(target_name[:-11] + "_mermaid_md"))
        escaped_targets.append(re.escape(target_name[:-3]))
    elif target_name.endswith(".d2.svg"):
        escaped_targets.append(re.escape(target_name[:-7] + "_d2_svg"))
        escaped_targets.append(re.escape(target_name[:-4]))
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
    return re.compile(rf"!\[\[(?:{target_pattern})(?:\|[^\]]*)?\]\]")


def _extract_matched_section(match: re.Match, source_text: str) -> str:
    """Extract section containing diagram placeholder with Dual-Scope context."""
    headings = list(re.finditer(r"^(#{1,6}\s+.*?)$", source_text, flags=re.MULTILINE))
    if not headings:
        start = max(0, match.start() - 500)
        end = min(len(source_text), match.end() + 500)
        return source_text[start:end]

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


def _extract_keyword_heading(target_name: str, source_text: str) -> str:
    """Fallback: extract section matching most keywords in diagram filename stem."""
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


def find_diagram_context(diagram_name: str, source_text: str) -> str:
    """Extract context around a diagram placeholder from source text."""
    pattern = _build_placeholder_pattern(diagram_name)
    match = pattern.search(source_text)
    if match:
        return _extract_matched_section(match, source_text)
    return _extract_keyword_heading(Path(diagram_name).name, source_text)


def resolve_chapter_images(
    chapter: str,
    book_name: str,
    max_images: int = 3,
) -> list[Path]:
    """Find relevant source images for a chapter via TOC mapping."""
    archive_dir = cfg.archive_dir / book_name
    if not archive_dir.exists():
        return []

    images = []
    ch_match = re.search(r"(\d+)", chapter)
    ch_num = ch_match.group(1) if ch_match else ""

    for img in archive_dir.iterdir():
        if img.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            if ch_num and f"ch{ch_num}" in img.name.lower():
                images.append(img)

    return sorted(images)[:max_images]


def spawn_worker(target: Any, args: tuple, name: str = "diagram") -> None:
    """Spawn a background thread for diagram generation."""
    thread = threading.Thread(target=target, args=args, daemon=True, name=name)
    thread.start()
    _logger.info(f"Spawned {name} worker thread")
