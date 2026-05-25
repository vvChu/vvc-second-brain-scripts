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
