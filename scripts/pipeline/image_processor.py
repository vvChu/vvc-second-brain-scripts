"""VvC Second Brain — Image Processing Pipeline (v8.15.13).

Contains the 5-stage pipeline orchestration for single images:
Stages: OCR → Ground Truth → Synthesize → Self-Correct → Post-Process.
Re-exports batch processing via pipeline.batch_processor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm.gateway_client import call_gateway_vision  # noqa: F401
from core.log import log
from core.prompts.pipeline import FIGURE_ENRICH
from pipeline.book_assets import (
    find_book_md_dir,
    is_decorative_image,
    build_chapter_diagrams_catalog,
)
from pipeline.batch_processor import (
    process_image_batch,
    _clean_blockquote_quote,
    _interpolate_page_numbers,
)

# Backward-compatible aliases for internal callers & tests
_find_md_dir = find_book_md_dir
_is_decorative_image = is_decorative_image
_get_chapter_diagrams = build_chapter_diagrams_catalog
FIGURE_ENRICH_PROMPT = FIGURE_ENRICH

_logger = logging.getLogger("vvc.imgproc")

__all__ = [
    "process_image",
    "process_image_batch",
    "find_source_ref",
    "trigger_moc_rebuild",
    "_clean_blockquote_quote",
    "_interpolate_page_numbers",
]


def find_source_ref(book_name: str) -> str:
    """Find the source note reference for a book.

    Args:
        book_name: Name of the book workspace folder.

    Returns:
        Source note stem matching the book, or book_name as fallback.
    """
    for f in cfg.sources_dir.iterdir():
        if f.suffix == ".md" and book_name.lower().replace("_", " ") in f.stem.lower().replace("_", " "):
            return f.stem
    return book_name


def trigger_moc_rebuild(concept: dict | Path | None = None) -> None:
    """Trigger incremental or full MOC + Index rebuild after concept creation."""
    try:
        from wiki_maintain import rebuild_all, rebuild_incremental

        if concept:
            rebuild_incremental(concept)
        else:
            rebuild_all()
    except Exception as e:
        _logger.warning(f"MOC rebuild failed: {e}")


def _extract_and_validate_single_ocr(image_path: Path, book_name: str) -> tuple[Any | None, bool]:
    """Run OCR on single image and validate length and TOC status."""
    from pipeline.ocr import extract_ocr
    from pipeline.post_process import archive_image

    ocr = extract_ocr(image_path, book_name=book_name)
    if ocr.is_toc:
        log("ingest", f"TOC extracted: {image_path.name}")
        try:
            archive_image(image_path, book_name=book_name)
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted single TOC image: {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to clean up single TOC image {image_path.name}: {e}")
        return None, True

    if not ocr.highlighted or len(ocr.highlighted) < 50:
        log("skip", f"OCR text too short ({len(ocr.highlighted)} chars)", source=image_path.name)
        _logger.warning(f"Skip: OCR too short ({len(ocr.highlighted)} chars)")
        try:
            archive_image(image_path, book_name=book_name)
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted skipped single image (archived as raw): {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to clean up skipped single image {image_path.name}: {e}")
        return None, False

    return ocr, True


def _resolve_single_ground_truth(ocr: Any, book_name: str, image_path: Path) -> tuple[str, Any, str, str]:
    """Find Ground Truth BM25 match, macro context, and chapter diagrams."""
    from pipeline.ground_truth import find_ground_truth, correct_ocr

    ground_truth = find_ground_truth(ocr.highlighted, book_name, page=ocr.page_number)
    highlighted = ocr.highlighted
    if ground_truth.paragraph:
        highlighted = correct_ocr(ocr.highlighted, ground_truth.paragraph)
        log("gt", f"BM25 matched: score={ground_truth.score:.1f}, chapter={ground_truth.chapter}", source=image_path.name)
    else:
        log("gt", f"No GT match (score={ground_truth.score:.1f})", source=image_path.name)

    book_macro_context = ""
    try:
        from pipeline.map_reduce import get_or_create_book_context

        book_macro_context = get_or_create_book_context(image_path.parent)
    except Exception as e:
        _logger.warning(f"Failed to get book macro context in process_image: {e}")

    chapter_diagrams = ""
    if ground_truth.paragraph and ground_truth.chapter:
        chapter_diagrams = _get_chapter_diagrams(
            book_name=book_name,
            chapter_stem=ground_truth.chapter,
            ground_truth_text=ground_truth.paragraph,
            page=str(ocr.page_number or ""),
        )

    return highlighted, ground_truth, book_macro_context, chapter_diagrams


def _cleanup_single_image(image_path: Path, book_name: str, saved: Path | None) -> None:
    """Clean up fleeting source image and rebuild MOC after single processing."""
    from pipeline.post_process import archive_image

    if saved:
        try:
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted successfully processed single image: {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to delete processed single image {image_path.name}: {e}")
        trigger_moc_rebuild(saved)
    else:
        try:
            archive_image(image_path, book_name=book_name)
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted failed single image (archived as raw): {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to clean up failed single image {image_path.name}: {e}")


def _synthesize_and_save_single(
    image_path: Path,
    book_name: str,
    ocr: Any,
    highlighted: str,
    ground_truth: Any,
    book_macro_context: str,
    chapter_diagrams: str,
) -> bool:
    """Synthesize concept note, verify, save, and clean up source image."""
    from pipeline.synthesize import synthesize_concept
    from pipeline.self_correct import verify_and_correct
    from pipeline.post_process import save_concept
    from pipeline.ground_truth import _is_vietnamese

    gt_for_synth = "" if _is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph
    content = synthesize_concept(
        highlighted=highlighted,
        context=ocr.context,
        ground_truth=gt_for_synth,
        source_name=book_name,
        source_ref=find_source_ref(book_name),
        chapter="",
        page=str(ocr.page_number or ""),
        gt_page=str(ground_truth.page or "") if ground_truth.page else "",
        gt_chapter=ground_truth.chapter,
        book_macro_context=book_macro_context,
        chapter_diagrams=chapter_diagrams,
    )
    if not content:
        log("error", "Synthesis failed", source=image_path.name)
        return False
    log("synth", f"OK ({len(content)} chars)", source=image_path.name)

    if ground_truth.paragraph:
        content = verify_and_correct(content, ground_truth.paragraph)

    saved = save_concept(content, image_path=image_path, book_name=book_name)
    _cleanup_single_image(image_path, book_name, saved)
    return bool(saved)


def process_image(image_path: Path) -> bool:
    """Run the full 5-stage pipeline on a single image.

    Stages: OCR → Ground Truth → Synthesize → Self-Correct → Post-Process.

    Args:
        image_path: Path to the source image in a Fleeting workspace.

    Returns:
        True if a concept note was successfully created.
    """
    book_name = image_path.parent.name
    _logger.info(f"Processing: {image_path.name} (book: {book_name})")
    log("ingest", f"Processing started: {image_path.name}", source=book_name)

    ocr, valid = _extract_and_validate_single_ocr(image_path, book_name)
    if not valid:
        return False
    if ocr is None:
        return True

    highlighted, ground_truth, book_macro_context, chapter_diagrams = _resolve_single_ground_truth(
        ocr, book_name, image_path
    )

    return _synthesize_and_save_single(
        image_path=image_path,
        book_name=book_name,
        ocr=ocr,
        highlighted=highlighted,
        ground_truth=ground_truth,
        book_macro_context=book_macro_context,
        chapter_diagrams=chapter_diagrams,
    )
