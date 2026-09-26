"""VvC Second Brain — Batch Image Processing Pipeline (v8.15.13).

Map-Reduce batch processor for multi-page photo bursts from book workspaces:
Runs OCR, segment concepts, Ground Truth alignment, synthesizes and archives.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.log import log
from core.types import PageData
from core.vector_store import VectorStore

import pipeline.ocr as ocr_mod
import pipeline.ground_truth as gt
import pipeline.synthesize as syn
import pipeline.self_correct as sc
import pipeline.post_process as pp
import pipeline.map_reduce as mr
from pipeline.batch_helpers import (
    _build_hook_exclusion_directive,
    _clean_blockquote_quote,
    _cleanup_batch_images,
    _get_diagrams_helper,
    _interpolate_helper,
    _interpolate_page_numbers,
    _resolve_concept_pages,
    _trigger_moc_helper,
)

_logger = logging.getLogger("vvc.batch_proc")

__all__ = [
    "process_image_batch",
    "_clean_blockquote_quote",
    "_interpolate_page_numbers",
    "_get_diagrams_helper",
    "_interpolate_helper",
    "_trigger_moc_helper",
    "_build_hook_exclusion_directive",
    "_resolve_concept_pages",
    "_cleanup_batch_images",
]


def _collect_batch_pages(image_paths: list[Path], book_name: str) -> tuple[list[PageData], list[Path]]:
    """Run OCR across batch images and separate TOC images."""
    pages_data: list[PageData] = []
    toc_images: list[Path] = []
    for img in image_paths:
        ocr = ocr_mod.extract_ocr(img, book_name=book_name)
        if ocr.is_toc:
            toc_images.append(img)
        elif ocr.highlighted and len(ocr.highlighted) >= 30:
            pages_data.append(PageData.from_ocr(img, ocr))

    for toc_img in toc_images:
        try:
            pp.archive_image(toc_img, book_name=book_name)
        except Exception as e:
            _logger.warning(f"Failed to archive TOC image {toc_img.name}: {e}")
    return pages_data, toc_images


def _prepare_synth_params(
    concept: dict[str, Any], ground_truth: Any, exclude_hooks: list[str], combined_h: str, book_name: str, first_p: str
) -> tuple[str, str, str]:
    """Prepare enriched highlighted text, ground truth, and chapter diagrams for synthesis."""
    guideline = f"\n\n[GUIDELINE: Bạn BẮT BUỘC phải tạo concept note cho khái niệm mang tên chính xác là '{concept['title']}']"
    exclude_dir, h = _build_hook_exclusion_directive(exclude_hooks, combined_h)
    gt_synth = "" if gt._is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph
    diagrams = (
        _get_diagrams_helper(book_name, ground_truth.chapter, ground_truth.paragraph, first_p)
        if ground_truth.paragraph and ground_truth.chapter
        else ""
    )
    return h + guideline + exclude_dir, gt_synth, diagrams


def _synthesize_concept_item(
    concept: dict[str, Any],
    idx: int,
    pages_data: list[PageData],
    book_name: str,
    book_macro_context: str,
    exclude_hooks: list[str],
) -> tuple[Path | None, Path | None, str]:
    """Execute Reduce step: Ground truth matching, synthesis, self-correction and saving for one concept."""
    from pipeline.image_processor import find_source_ref

    c_pages = _resolve_concept_pages(concept, idx, pages_data)
    if not c_pages:
        return None, None, ""

    combined_h = "\n\n".join(p.highlighted for p in c_pages)
    combined_c = "\n\n".join(p.context for p in c_pages)
    first_p = str(c_pages[0].page_number or 0)
    primary_img = c_pages[0].image_path

    ground_truth = gt.find_ground_truth(combined_h, book_name, page=int(first_p) if first_p != "0" else None)
    if ground_truth.paragraph:
        combined_h = gt.correct_ocr(combined_h, ground_truth.paragraph)

    highlighted_arg, gt_for_synth, diagrams = _prepare_synth_params(
        concept, ground_truth, exclude_hooks, combined_h, book_name, first_p
    )
    content = syn.synthesize_concept(
        highlighted=highlighted_arg,
        context=combined_c,
        ground_truth=gt_for_synth,
        source_name=book_name,
        source_ref=find_source_ref(book_name),
        chapter="",
        page=first_p if first_p != "0" else "",
        gt_page=str(ground_truth.page or "") if ground_truth.page else "",
        gt_chapter=ground_truth.chapter,
        book_macro_context=book_macro_context,
        chapter_diagrams=diagrams,
    )
    if not content:
        return None, primary_img, ""

    if ground_truth.paragraph:
        content = sc.verify_and_correct(content, ground_truth.paragraph)

    bq = sc._extract_core_idea_blockquote(content)
    clean_bq = _clean_blockquote_quote(bq) if bq else ""
    saved = pp.save_concept(content, image_path=primary_img, book_name=book_name)
    return saved, primary_img, clean_bq


def _run_reduce_loop(
    segmented: list[dict[str, Any]], pages_data: list[PageData], book_name: str, book_ctx: str
) -> tuple[int, list[Path], set[Path]]:
    """Execute Reduce loop across segmented concepts with hook exclusion tracking."""
    created_count = 0
    saved_concepts: list[Path] = []
    processed_images: set[Path] = set()
    exclude_hooks: list[str] = []

    with VectorStore.get_instance().batch():
        for idx, concept in enumerate(segmented):
            saved, p_img, clean_bq = _synthesize_concept_item(
                concept, idx, pages_data, book_name, book_ctx, exclude_hooks
            )
            if clean_bq:
                exclude_hooks.append(clean_bq)
            if saved and p_img:
                created_count += 1
                saved_concepts.append(saved)
                processed_images.add(p_img)
    return created_count, saved_concepts, processed_images


def _run_classic_batch_fallback(
    pages_data: list[PageData], book_name: str, book_macro_context: str
) -> tuple[Path | None, Path]:
    """Execute classic single-concept fallback when Map-Reduce is bypassed or yields 0 notes."""
    from pipeline.image_processor import find_source_ref

    _logger.info("Map-Reduce bypassed or yielded zero notes. Falling back to Classic Single-Concept Flow.")
    combined_h = "\n\n".join(p.highlighted for p in pages_data)
    combined_c = "\n\n".join(p.context for p in pages_data)
    first_p = str(pages_data[0].page_number) if pages_data[0].page_number else None
    primary_img = pages_data[0].image_path

    ground_truth = gt.find_ground_truth(combined_h, book_name, page=int(first_p) if first_p else None)
    if ground_truth.paragraph:
        combined_h = gt.correct_ocr(combined_h, ground_truth.paragraph)

    diagrams = (
        _get_diagrams_helper(book_name, ground_truth.chapter, ground_truth.paragraph, first_p or "")
        if ground_truth.paragraph and ground_truth.chapter
        else ""
    )
    gt_for_synth = "" if gt._is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph

    content = syn.synthesize_concept(
        highlighted=combined_h,
        context=combined_c,
        ground_truth=gt_for_synth,
        source_name=book_name,
        source_ref=find_source_ref(book_name),
        chapter="",
        page=first_p or "",
        gt_page=str(ground_truth.page or "") if ground_truth.page else "",
        gt_chapter=ground_truth.chapter,
        book_macro_context=book_macro_context,
        chapter_diagrams=diagrams,
    )
    if not content:
        return None, primary_img

    if ground_truth.paragraph:
        content = sc.verify_and_correct(content, ground_truth.paragraph)

    saved = pp.save_concept(content, image_path=primary_img, book_name=book_name)
    return saved, primary_img


def process_image_batch(image_paths: list[Path]) -> bool:
    """Process multiple images from the same workspace using a Map-Reduce architecture."""
    book_name = image_paths[0].parent.name
    book_macro_context = ""
    try:
        book_macro_context = mr.get_or_create_book_context(image_paths[0].parent)
    except Exception as e:
        _logger.warning(f"Failed to get book macro context in process_batch: {e}")

    image_paths = sorted(image_paths, key=lambda p: p.name.lower())
    _logger.info(f"Batch processing {len(image_paths)} sorted images (book: {book_name})")
    log("ingest", f"Batch processing started: {len(image_paths)} images (sorted)", source=book_name)

    pages_data, toc_images = _collect_batch_pages(image_paths, book_name)
    if not pages_data:
        log("skip", "Batch: no usable highlighted text found", source=book_name)
        _cleanup_batch_images(image_paths, set(), toc_images, book_name)
        return False

    _interpolate_helper(pages_data)
    created_count, saved_concepts = 0, []
    processed_images: set[Path] = set()

    segmented = mr.segment_concepts([p.to_dict() for p in pages_data], book_name)
    if segmented is not None:
        if not segmented:
            processed_images.update(p.image_path for p in pages_data)
        else:
            created_count, saved_concepts, processed_images = _run_reduce_loop(
                segmented, pages_data, book_name, book_macro_context
            )

    if created_count == 0 and segmented is None:
        saved, p_img = _run_classic_batch_fallback(pages_data, book_name, book_macro_context)
        if saved:
            created_count += 1
            saved_concepts.append(saved)
            processed_images.add(p_img)

    _cleanup_batch_images(image_paths, processed_images, toc_images, book_name)
    if created_count > 0:
        for c_path in saved_concepts:
            _trigger_moc_helper(c_path)
        _logger.info(f"Batch processing completed successfully. Synthesized {created_count} concepts.")
        return True
    return False
