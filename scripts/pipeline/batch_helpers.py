"""VvC Second Brain — Batch Image Processing Helpers.

Provides blockquote parsing, page number interpolation, diagram resolution,
hook exclusion directives, and batch image cleanup.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from core.types import PageData
import pipeline.post_process as pp

_logger = logging.getLogger("vvc.batch_proc.helpers")

__all__ = [
    "_clean_blockquote_quote",
    "_interpolate_page_numbers",
    "_get_diagrams_helper",
    "_interpolate_helper",
    "_trigger_moc_helper",
    "_build_hook_exclusion_directive",
    "_resolve_concept_pages",
    "_cleanup_batch_images",
]


def _clean_blockquote_quote(bq: str) -> str:
    """Extract raw quote text from a blockquote, removing markdown and citations."""
    if not bq:
        return ""
    quote_lines: list[str] = []
    for line in bq.splitlines():
        line_strip = line.strip()
        if not line_strip or any(line_strip.startswith(p) for p in ["> —", "> -", ">—", ">-"]):
            continue
        if line_strip.startswith(">"):
            c = line_strip[1:].strip()
            if (c.startswith('"') and c.endswith('"')) or (c.startswith("“") and c.endswith("”")):
                c = c[1:-1].strip()
            if c:
                quote_lines.append(c)
    return " ".join(quote_lines).strip()


def _interpolate_page_numbers(pages_data: list[PageData]) -> None:
    """Interpolate missing page numbers using forward-fill then backward-fill in-place."""
    last_known: int | None = None
    for p in pages_data:
        if p.page_number is not None:
            last_known = p.page_number
        elif last_known is not None:
            last_known += 1
            p.page_number = last_known

    first_known_idx = next((i for i, p in enumerate(pages_data) if p.page_number is not None), -1)
    if first_known_idx > 0:
        val = pages_data[first_known_idx].page_number or 1
        for idx in range(first_known_idx - 1, -1, -1):
            val = max(1, val - 1)
            pages_data[idx].page_number = val

    for p in pages_data:
        if p.page_number is None:
            p.page_number = 0


def _get_diagrams_helper(book_name: str, chapter_stem: str, ground_truth_text: str, page: str) -> str:
    """Resolve chapter diagrams through image_processor mock if available, else book_assets."""
    try:
        import pipeline.image_processor as ip

        fn = getattr(ip, "_get_chapter_diagrams", None)
        if fn is not None:
            return fn(book_name=book_name, chapter_stem=chapter_stem, ground_truth_text=ground_truth_text, page=page)
    except Exception:
        pass
    from pipeline.book_assets import build_chapter_diagrams_catalog

    return build_chapter_diagrams_catalog(
        book_name=book_name, chapter_stem=chapter_stem, ground_truth_text=ground_truth_text, page=page
    )


def _interpolate_helper(pages_data: list[PageData]) -> None:
    """Call page interpolation, delegating to image_processor mock if patched in tests."""
    try:
        import pipeline.image_processor as ip

        fn = getattr(ip, "_interpolate_page_numbers", None)
        if fn is not None and fn is not _interpolate_page_numbers:
            fn(pages_data)
            return
    except Exception:
        pass
    _interpolate_page_numbers(pages_data)


def _trigger_moc_helper(c_path: Path) -> None:
    """Trigger MOC rebuild, delegating to image_processor mock if patched in tests."""
    try:
        import pipeline.image_processor as ip

        fn = getattr(ip, "trigger_moc_rebuild", None)
        if fn is not None:
            fn(c_path)
    except Exception:
        pass


def _build_hook_exclusion_directive(exclude_hooks: list[str], combined_h: str) -> tuple[str, str]:
    """Build Hook Overlap Prevention Directive and apply Hybrid XML Marking."""
    if not exclude_hooks:
        return "", combined_h
    directive = (
        "\n\n[CRITICAL DIRECTIVE: Để tránh trùng lặp trích dẫn giữa các ghi chú trong cùng một cụm trang (Hook Overlap), "
        "bạn TUYỆT ĐỐI KHÔNG ĐƯỢC phép chọn hoặc sử dụng các đoạn trích dẫn sau đây làm Evidence Hook (blockquote đầu ghi chú):\n"
    )
    for h in exclude_hooks:
        directive += f'- "{h}"\n'
        if len(h) > 10:
            try:
                pattern = re.compile(re.escape(h), re.IGNORECASE)
                combined_h = pattern.sub(lambda m: f"<USED_HOOK>{m.group(0)}</USED_HOOK>", combined_h)
            except Exception:
                pass
    directive += (
        "Hãy chọn một câu trích dẫn/highlight khác trong văn bản nguồn để làm Evidence Hook. "
        "Các đoạn trích dẫn đã bị hệ thống trước đó dùng làm Hook đã được bọc trong thẻ <USED_HOOK>...</USED_HOOK> "
        "ngay trong văn bản nguồn phía trên để bạn dễ nhận biết và tránh xa.]"
    )
    return directive, combined_h


def _resolve_concept_pages(concept: dict[str, Any], idx: int, pages_data: list[PageData]) -> list[PageData]:
    """Filter pages belonging to concept boundary with fallback to proportional division."""
    p_start, p_end = concept["page_start"], concept["page_end"]
    c_pages = [p for p in pages_data if p.page_number is not None and p_start <= p.page_number <= p_end]
    if not c_pages:
        chunk_size = max(1, len(pages_data) // max(1, len(pages_data)))
        start_idx = idx * chunk_size
        c_pages = pages_data[start_idx : min(len(pages_data), (idx + 1) * chunk_size)]
    return c_pages


def _cleanup_batch_images(
    image_paths: list[Path], processed_images: set[Path], toc_images: list[Path], book_name: str
) -> None:
    """Archive unprocessed batch images and delete original fleeting images."""
    for img in image_paths:
        try:
            if img not in processed_images and img not in toc_images:
                pp.archive_image(img, book_name=book_name)
            if img.exists():
                img.unlink()
                _logger.debug(f"Deleted fleeting source image: {img.name}")
        except Exception as e:
            _logger.warning(f"Failed to cleanup batch image {img.name}: {e}")
