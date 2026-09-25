"""VvC Second Brain — Image Processing Pipeline (v8.7).

Extracted from daemon.py to enforce Single Responsibility Principle.
Contains the 5-stage pipeline orchestration for single images and
the Map-Reduce batch processor for multi-page photo bursts.

Functions:
    process_image: Full 5-stage pipeline for a single image.
    process_image_batch: Map-Reduce batch pipeline for multiple images.
    find_source_ref: Resolve book name to source note filename.
    trigger_moc_rebuild: Trigger MOC + Index rebuild after concept creation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.config import cfg
from core.llm.gateway_client import call_gateway_vision  # noqa: F401
from core.log import log
from core.types import PageData
from core.vector_store import VectorStore
from pipeline.book_assets import (
    find_book_md_dir,
    is_decorative_image,
    build_chapter_diagrams_catalog,
)

# Backward-compatible aliases for internal callers & tests
_find_md_dir = find_book_md_dir
_is_decorative_image = is_decorative_image
_get_chapter_diagrams = build_chapter_diagrams_catalog

from core.prompts.pipeline import FIGURE_ENRICH

_logger = logging.getLogger("vvc.imgproc")

FIGURE_ENRICH_PROMPT = FIGURE_ENRICH


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


def process_image(image_path: Path) -> bool:
    """Run the full 5-stage pipeline on a single image.

    Stages: OCR → Ground Truth → Synthesize → Self-Correct → Post-Process.

    Args:
        image_path: Path to the source image in a Fleeting workspace.

    Returns:
        True if a concept note was successfully created.
    """
    from pipeline.ocr import extract_ocr
    from pipeline.ground_truth import find_ground_truth, correct_ocr, _is_vietnamese
    from pipeline.synthesize import synthesize_concept
    from pipeline.self_correct import verify_and_correct
    from pipeline.post_process import save_concept
    book_name = image_path.parent.name
    _logger.info(f"Processing: {image_path.name} (book: {book_name})")
    log("ingest", f"Processing started: {image_path.name}", source=book_name)

    # Stage 1: OCR
    ocr = extract_ocr(image_path, book_name=book_name)
    if ocr.is_toc:
        log("ingest", f"TOC extracted: {image_path.name}")
        try:
            from pipeline.post_process import archive_image
            archive_image(image_path, book_name=book_name)
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted single TOC image: {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to clean up single TOC image {image_path.name}: {e}")
        return True  # TOC processing is done in extract_ocr

    if not ocr.highlighted or len(ocr.highlighted) < 50:
        log("skip", f"OCR text too short ({len(ocr.highlighted)} chars)", source=image_path.name)
        _logger.warning(f"Skip: OCR too short ({len(ocr.highlighted)} chars)")
        try:
            from pipeline.post_process import archive_image
            archive_image(image_path, book_name=book_name)
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted skipped single image (archived as raw): {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to clean up skipped single image {image_path.name}: {e}")
        return False

    # Stage 2: Ground Truth
    ground_truth = find_ground_truth(ocr.highlighted, book_name, page=ocr.page_number)
    highlighted = ocr.highlighted
    if ground_truth.paragraph:
        highlighted = correct_ocr(ocr.highlighted, ground_truth.paragraph)
        log("gt", f"BM25 matched: score={ground_truth.score:.1f}, chapter={ground_truth.chapter}", source=image_path.name)
    else:
        log("gt", f"No GT match (score={ground_truth.score:.1f})", source=image_path.name)

    # Resolve source reference
    source_ref = find_source_ref(book_name)

    # Get book macro context using workspace path
    book_macro_context = ""
    try:
        from pipeline.map_reduce import get_or_create_book_context
        book_macro_context = get_or_create_book_context(image_path.parent)
    except Exception as e:
        _logger.warning(f"Failed to get book macro context in process_image: {e}")

    # Stage 3: Synthesize
    gt_for_synthesis = "" if _is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph
    
    # Get JIT chapter diagrams XML catalog
    chapter_diagrams = ""
    if ground_truth.paragraph and ground_truth.chapter:
        chapter_diagrams = _get_chapter_diagrams(
            book_name=book_name,
            chapter_stem=ground_truth.chapter,
            ground_truth_text=ground_truth.paragraph,
            page=str(ocr.page_number or ""),
        )

    content = synthesize_concept(
        highlighted=highlighted,
        context=ocr.context,
        ground_truth=gt_for_synthesis,
        source_name=book_name,
        source_ref=source_ref,
        chapter="",  # Sách chụp tiếng Việt (để trống hoặc tự động trích xuất chương sau này)
        page=str(ocr.page_number or ""),
        gt_page=str(ground_truth.page or "") if ground_truth.page else "",
        gt_chapter=ground_truth.chapter,  # Bản gốc tiếng Anh
        book_macro_context=book_macro_context,
        chapter_diagrams=chapter_diagrams,
    )
    if not content:
        log("error", "Synthesis failed", source=image_path.name)
        return False
    log("synth", f"OK ({len(content)} chars)", source=image_path.name)

    # Stage 4: Self-Correction (independent verification)
    if ground_truth.paragraph:
        content = verify_and_correct(content, ground_truth.paragraph)

    # Stage 5: Post-Process (save + archive)
    saved = save_concept(content, image_path=image_path, book_name=book_name)
    if saved:
        try:
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted successfully processed single image: {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to delete processed single image {image_path.name}: {e}")
        trigger_moc_rebuild(saved)
        return True

    try:
        from pipeline.post_process import archive_image
        archive_image(image_path, book_name=book_name)
        if image_path.exists():
            image_path.unlink()
            _logger.info(f"Deleted failed single image (archived as raw): {image_path.name}")
    except Exception as e:
        _logger.warning(f"Failed to clean up failed single image {image_path.name}: {e}")
    return False


def _clean_blockquote_quote(bq: str) -> str:
    """Extract only the raw text of the main quote from a blockquote block,
    removing markdown syntax, citations, and outer quotes.
    """
    if not bq:
        return ""
    lines = bq.split("\n")
    quote_lines = []
    for line in lines:
        line_strip = line.strip()
        # Skip empty lines and citation lines starting with dash
        if not line_strip or any(line_strip.startswith(prefix) for prefix in ["> —", "> -", ">—", ">-"]):
            continue
        if line_strip.startswith(">"):
            content = line_strip[1:].strip()
            # Strip outer double quotes if present
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1].strip()
            elif content.startswith('“') and content.endswith('”'):
                content = content[1:-1].strip()
            if content:
                quote_lines.append(content)
    return " ".join(quote_lines).strip()


def process_image_batch(image_paths: list[Path]) -> bool:
    """Process multiple images from the same workspace using a Map-Reduce architecture.

    Stage 1: Runs OCR on each image.
    Map Step: Semantic Topic Segmenter detects atomic concepts and page boundaries.
    Reduce Step: Runs BM25 Ground Truth alignment, Synthesizes and Self-Corrects each concept note.
    Post-Process: Saves concept notes, archives images under Concept-Centric Naming v2.0, triggers MOC.

    Args:
        image_paths: Ordered list of images (same workspace/book).

    Returns:
        True if at least one concept note was successfully created (or classic fallback succeeded).
    """
    from pipeline.ocr import extract_ocr
    from pipeline.ground_truth import find_ground_truth, correct_ocr, _is_vietnamese
    from pipeline.synthesize import synthesize_concept
    from pipeline.self_correct import verify_and_correct
    from pipeline.post_process import save_concept, archive_image
    from pipeline.map_reduce import segment_concepts

    book_name = image_paths[0].parent.name
    workspace_dir = image_paths[0].parent
    # Get book macro context using workspace path
    book_macro_context = ""
    try:
        from pipeline.map_reduce import get_or_create_book_context
        book_macro_context = get_or_create_book_context(workspace_dir)
    except Exception as e:
        _logger.warning(f"Failed to get book macro context in process_batch: {e}")

    # Sort image_paths alphabetically to guarantee logical reading order (camera timestamp/seq)
    image_paths = sorted(image_paths, key=lambda p: p.name.lower())
    _logger.info(f"Batch processing {len(image_paths)} sorted images (book: {book_name})")
    log("ingest", f"Batch processing started: {len(image_paths)} images (sorted)", source=book_name)

    pages_data: list[PageData] = []
    toc_images: list[Path] = []

    # Stage 1: OCR each image
    for img in image_paths:
        ocr = extract_ocr(img, book_name=book_name)
        if ocr.is_toc:
            toc_images.append(img)
            continue
        if ocr.highlighted and len(ocr.highlighted) >= 30:
            pages_data.append(PageData.from_ocr(img, ocr))

    # Archive TOC images early to clear workspace
    for toc_img in toc_images:
        try:
            archive_image(toc_img, book_name=book_name)
        except Exception as e:
            _logger.warning(f"Failed to archive TOC image {toc_img.name}: {e}")

    if not pages_data:
        log("skip", "Batch: no usable highlighted text found", source=book_name)
        # Archive all images in the batch to prevent losing them and prevent infinite loop, then delete from fleeting
        for img_path in image_paths:
            try:
                if img_path not in toc_images:
                    archive_image(img_path, book_name=book_name)
                if img_path.exists():
                    img_path.unlink()
                    _logger.info(f"Cleaned up skipped batch image: {img_path.name}")
            except Exception as e:
                _logger.warning(f"Failed to clean up skipped batch image {img_path.name}: {e}")
        return False

    # Page Number Interpolation (Smart Page Resolving for Map Step)
    _interpolate_page_numbers(pages_data)

    created_count = 0
    saved_concepts: list[Path] = []
    segmented = None
    processed_images: set[Path] = set()
    exclude_hooks: list[str] = []
    # Trigger Map-Reduce if we have 1 or more usable pages
    if len(pages_data) >= 1:
        _logger.info(f"Triggering Map-Reduce for {len(pages_data)} pages")
        segmented = segment_concepts([p.to_dict() for p in pages_data], book_name)
        if segmented is not None:
            if not segmented:
                _logger.info("Map-Reduce actively decided 0 concepts from the input. Skipping concept creation.")
                processed_images.update(p.image_path for p in pages_data)
                created_count = -1
            else:
                with VectorStore.get_instance().batch():
                    for idx, concept in enumerate(segmented):
                        title = concept["title"]
                        page_start = concept["page_start"]
                        page_end = concept["page_end"]
                        
                        # Filter pages belonging to this concept
                        concept_pages = [
                            p for p in pages_data
                            if p.page_number is not None and page_start <= p.page_number <= page_end
                        ]
                        
                        if not concept_pages:
                            _logger.warning(f"Map-Reduce Mismatch: No pages found for concept '{title}' within [{page_start}, {page_end}]. Fallback to index-based.")
                            # Safe fallback: assign pages based on proportional division of index
                            chunk_size = max(1, len(pages_data) // len(segmented))
                            start_idx = idx * chunk_size
                            end_idx = min(len(pages_data), (idx + 1) * chunk_size)
                            concept_pages = pages_data[start_idx:end_idx]
                        
                        if not concept_pages:
                            continue
                        combined_h = "\n\n".join(p.highlighted for p in concept_pages)
                        combined_c = "\n\n".join(p.context for p in concept_pages)
                        first_p = str(concept_pages[0].page_number or 0)
                        primary_img = concept_pages[0].image_path

                        # Reduce Step: BM25 Ground Truth Correction
                        ground_truth = find_ground_truth(combined_h, book_name, page=int(first_p) if first_p and first_p != "0" else None)
                        if ground_truth.paragraph:
                            combined_h = correct_ocr(combined_h, ground_truth.paragraph)
                            _logger.info(f"BM25 matched for concept '{title}': score={ground_truth.score:.1f}")

                        # Reduce Step: Synthesis with structural title guideline
                        source_ref = find_source_ref(book_name)
                        guideline = f"\n\n[GUIDELINE: Bạn BẮT BUỘC phải tạo concept note cho khái niệm mang tên chính xác là '{title}']"
                        
                        # Add Hook Overlap Prevention Directive and Hybrid XML Marking
                        exclude_directive = ""
                        if exclude_hooks:
                            exclude_directive = (
                                "\n\n[CRITICAL DIRECTIVE: Để tránh trùng lặp trích dẫn giữa các ghi chú trong cùng một cụm trang (Hook Overlap), bạn TUYỆT ĐỐI KHÔNG ĐƯỢC phép chọn hoặc sử dụng các đoạn trích dẫn sau đây làm Evidence Hook (blockquote đầu ghi chú):\n"
                            )
                            for h in exclude_hooks:
                                exclude_directive += f'- "{h}"\n'
                                # Hybrid XML Marking: wrap matches in highlighted text
                                if len(h) > 10:
                                    try:
                                        escaped_h = re.escape(h)
                                        pattern = re.compile(escaped_h, re.IGNORECASE)
                                        combined_h = pattern.sub(lambda m: f"<USED_HOOK>{m.group(0)}</USED_HOOK>", combined_h)
                                    except Exception:
                                        pass
                            exclude_directive += "Hãy chọn một câu trích dẫn/highlight khác trong văn bản nguồn để làm Evidence Hook. Các đoạn trích dẫn đã bị hệ thống trước đó dùng làm Hook đã được bọc trong thẻ <USED_HOOK>...</USED_HOOK> ngay trong văn bản nguồn phía trên để bạn dễ nhận biết và tránh xa.]"

                        gt_for_synthesis = "" if _is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph
                        
                        # Get JIT chapter diagrams XML catalog for batch
                        chapter_diagrams = ""
                        if ground_truth.paragraph and ground_truth.chapter:
                            chapter_diagrams = _get_chapter_diagrams(
                                book_name=book_name,
                                chapter_stem=ground_truth.chapter,
                                ground_truth_text=ground_truth.paragraph,
                                page=first_p if first_p != "0" else "",
                            )

                        content = synthesize_concept(
                            highlighted=combined_h + guideline + exclude_directive,
                            context=combined_c,
                            ground_truth=gt_for_synthesis,
                            source_name=book_name,
                            source_ref=source_ref,
                            chapter="",
                            page=first_p if first_p != "0" else "",
                            gt_page=str(ground_truth.page or "") if ground_truth.page else "",
                            gt_chapter=ground_truth.chapter,
                            book_macro_context=book_macro_context,
                            chapter_diagrams=chapter_diagrams,
                        )

                        if content:
                            # Reduce Step: Self-Correction
                            if ground_truth.paragraph:
                                content = verify_and_correct(content, ground_truth.paragraph)
                            
                            # Track hook for subsequent synthesis calls in the same batch
                            from pipeline.self_correct import _extract_core_idea_blockquote
                            bq = _extract_core_idea_blockquote(content)
                            if bq:
                                clean_bq = _clean_blockquote_quote(bq)
                                if clean_bq:
                                    exclude_hooks.append(clean_bq)
                                    _logger.info(f"Registered processed hook to exclusion list: '{clean_bq[:40]}...'")

                            # Reduce Step: Save Note & Concept-Centric Image Renaming
                            saved = save_concept(content, image_path=primary_img, book_name=book_name)
                            if saved:
                                created_count += 1
                                saved_concepts.append(saved)
                                processed_images.add(primary_img)

    # Fallback to Classic Flow (Gộp thành 1 note) if Map-Reduce is bypassed or yielded zero notes
    if created_count == 0 and segmented is None:
        _logger.info("Map-Reduce bypassed or yielded zero notes. Falling back to Classic Single-Concept Flow.")
        combined_highlighted = "\n\n".join(p.highlighted for p in pages_data)
        combined_context = "\n\n".join(p.context for p in pages_data)
        first_page = str(pages_data[0].page_number) if pages_data[0].page_number else None

        ground_truth = find_ground_truth(combined_highlighted, book_name, page=int(first_page) if first_page else None)
        if ground_truth.paragraph:
            combined_highlighted = correct_ocr(combined_highlighted, ground_truth.paragraph)
            log("gt", f"BM25 matched (classic fallback): score={ground_truth.score:.1f}", source=book_name)

        source_ref = find_source_ref(book_name)
        gt_for_synthesis = "" if _is_vietnamese(ground_truth.paragraph) else ground_truth.paragraph
        
        # Get JIT chapter diagrams XML catalog for classic fallback
        chapter_diagrams = ""
        if ground_truth.paragraph and ground_truth.chapter:
            chapter_diagrams = _get_chapter_diagrams(
                book_name=book_name,
                chapter_stem=ground_truth.chapter,
                ground_truth_text=ground_truth.paragraph,
                page=first_page or "",
            )

        content = synthesize_concept(
            highlighted=combined_highlighted,
            context=combined_context,
            ground_truth=gt_for_synthesis,
            source_name=book_name,
            source_ref=source_ref,
            chapter="",
            page=first_page or "",
            gt_page=str(ground_truth.page or "") if ground_truth.page else "",
            gt_chapter=ground_truth.chapter,
            book_macro_context=book_macro_context,
            chapter_diagrams=chapter_diagrams,
        )

        if content:
            if ground_truth.paragraph:
                content = verify_and_correct(content, ground_truth.paragraph)
            
            saved = save_concept(content, image_path=pages_data[0].image_path, book_name=book_name)
            if saved:
                created_count += 1
                saved_concepts.append(saved)
                processed_images.add(pages_data[0].image_path)

    # Clean up and Archive all extra images in the batch, then delete originals
    # Archive remaining images that were not successfully saved as part of a concept note
    for img_path in image_paths:
        try:
            if img_path not in processed_images and img_path not in toc_images:
                archive_image(img_path, book_name=book_name)
        except Exception as ae:
            _logger.warning(f"Failed to archive image {img_path.name} on cleanup: {ae}")

    # Delete all original fleeting source images to clear fleeting workspace and prevent infinite loops
    for img_path in image_paths:
        try:
            if img_path.exists():
                img_path.unlink()
                _logger.debug(f"Deleted fleeting source image: {img_path.name}")
        except Exception as de:
            _logger.warning(f"Failed to delete fleeting source image {img_path.name}: {de}")
        
    if created_count > 0:
        for c_path in saved_concepts:
            trigger_moc_rebuild(c_path)
        _logger.info(f"Batch processing completed successfully. Synthesized {created_count} concepts.")
        return True

    return False


def _interpolate_page_numbers(pages_data: list[PageData]) -> None:
    """Interpolate missing page numbers using forward-fill then backward-fill.

    Modifies pages_data in-place.

    Args:
        pages_data: List of PageData with page_number (may be None).
    """
    # Forward fill
    last_known: int | None = None
    for p in pages_data:
        if p.page_number is not None:
            last_known = p.page_number
        elif last_known is not None:
            last_known += 1
            p.page_number = last_known

    # Backward fill for leading None values
    first_known_idx = -1
    for idx, p in enumerate(pages_data):
        if p.page_number is not None:
            first_known_idx = idx
            break
    if first_known_idx > 0:
        val = pages_data[first_known_idx].page_number
        for idx in range(first_known_idx - 1, -1, -1):
            val = max(1, val - 1)
            pages_data[idx].page_number = val

    # Enforce default 0 if all pages failed OCR detection
    for p in pages_data:
        if p.page_number is None:
            p.page_number = 0
