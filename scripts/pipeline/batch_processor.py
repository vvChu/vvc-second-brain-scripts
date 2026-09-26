"""VvC Second Brain — Batch Image Processing Pipeline (v8.15.13).

Map-Reduce batch processor for multi-page photo bursts from book workspaces:
Runs OCR, segment concepts, Ground Truth alignment, synthesizes and archives.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
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

_logger = logging.getLogger("vvc.batch_proc")


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


def _prepare_synth_params(concept: dict[str, Any], ground_truth: Any, exclude_hooks: list[str], combined_h: str, book_name: str, first_p: str) -> tuple[str, str, str]:
    """Prepare enriched highlighted text, ground truth, and chapter diagrams for synthesis."""
    guideline = f"\n\n[GUIDELINE: Bạn BẮT BUỘC phải tạo concept note cho khái niệm mang tên chính xác là '{concept['title']}']"
    exclude_dir, h = _build_hook_exclusion_directive(exclude_hooks, combined_h)
    gt_synth = "" if gt._is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph
    diagrams = _get_diagrams_helper(book_name, ground_truth.chapter, ground_truth.paragraph, first_p) if ground_truth.paragraph and ground_truth.chapter else ""
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

    highlighted_arg, gt_for_synth, diagrams = _prepare_synth_params(concept, ground_truth, exclude_hooks, combined_h, book_name, first_p)
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
            saved, p_img, clean_bq = _synthesize_concept_item(concept, idx, pages_data, book_name, book_ctx, exclude_hooks)
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

    diagrams = _get_diagrams_helper(book_name, ground_truth.chapter, ground_truth.paragraph, first_p or "") if ground_truth.paragraph and ground_truth.chapter else ""
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
            created_count, saved_concepts, processed_images = _run_reduce_loop(segmented, pages_data, book_name, book_macro_context)

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
