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
from pathlib import Path

from core.config import cfg
from core.log import log

_logger = logging.getLogger("vvc.imgproc")


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


def trigger_moc_rebuild() -> None:
    """Trigger MOC + Index rebuild after concept creation."""
    try:
        from wiki_maintain import rebuild_all
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
    gt = find_ground_truth(ocr.highlighted, book_name, page=ocr.page_number)
    highlighted = ocr.highlighted
    if gt.paragraph:
        highlighted = correct_ocr(ocr.highlighted, gt.paragraph)
        log("gt", f"BM25 matched: score={gt.score:.1f}, chapter={gt.chapter}", source=image_path.name)
    else:
        log("gt", f"No GT match (score={gt.score:.1f})", source=image_path.name)

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
    gt_for_synthesis = "" if _is_vietnamese(gt.paragraph) else gt.paragraph
    content = synthesize_concept(
        highlighted=highlighted,
        context=ocr.context,
        ground_truth=gt_for_synthesis,
        source_name=book_name,
        source_ref=source_ref,
        chapter="",  # Sách chụp tiếng Việt (để trống hoặc tự động trích xuất chương sau này)
        page=str(ocr.page_number or ""),
        gt_page=str(gt.page or "") if gt.page else "",
        gt_chapter=gt.chapter,  # Bản gốc tiếng Anh
        book_macro_context=book_macro_context,
    )
    if not content:
        log("error", "Synthesis failed", source=image_path.name)
        return False
    log("synth", f"OK ({len(content)} chars)", source=image_path.name)

    # Stage 4: Self-Correction (independent verification)
    if gt.paragraph:
        content = verify_and_correct(content, gt.paragraph)

    # Stage 5: Post-Process (save + archive)
    saved = save_concept(content, image_path=image_path, book_name=book_name)
    if saved:
        try:
            if image_path.exists():
                image_path.unlink()
                _logger.info(f"Deleted successfully processed single image: {image_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to delete processed single image {image_path.name}: {e}")
        trigger_moc_rebuild()
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
    workspace_path = image_paths[0].parent
    # Get book macro context using workspace path
    book_macro_context = ""
    try:
        from pipeline.map_reduce import get_or_create_book_context
        book_macro_context = get_or_create_book_context(workspace_path)
    except Exception as e:
        _logger.warning(f"Failed to get book macro context in process_batch: {e}")

    # Sort image_paths alphabetically to guarantee logical reading order (camera timestamp/seq)
    image_paths = sorted(image_paths, key=lambda p: p.name.lower())
    _logger.info(f"Batch processing {len(image_paths)} sorted images (book: {book_name})")
    log("ingest", f"Batch processing started: {len(image_paths)} images (sorted)", source=book_name)

    pages_data: list[dict] = []
    toc_images: list[Path] = []

    # Stage 1: OCR each image
    for img in image_paths:
        ocr = extract_ocr(img, book_name=book_name)
        if ocr.is_toc:
            toc_images.append(img)
            continue
        if ocr.highlighted and len(ocr.highlighted) >= 30:
            pages_data.append({
                "image_path": img,
                "highlighted": ocr.highlighted,
                "context": ocr.context,
                "page_number": ocr.page_number,
            })

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
    processed_images: set[Path] = set()

    # Trigger Map-Reduce if we have 3 or more usable pages
    if len(pages_data) >= 3:
        _logger.info(f"Triggering Map-Reduce for {len(pages_data)} pages")
        segmented = segment_concepts(pages_data, book_name)
        
        if segmented:
            for idx, concept in enumerate(segmented):
                title = concept["title"]
                page_start = concept["page_start"]
                page_end = concept["page_end"]
                
                # Filter pages belonging to this concept
                concept_pages = [
                    p for p in pages_data
                    if page_start <= p["page_number"] <= page_end
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

                combined_h = "\n\n".join(p["highlighted"] for p in concept_pages)
                combined_c = "\n\n".join(p["context"] for p in concept_pages)
                first_p = str(concept_pages[0]["page_number"])
                primary_img = concept_pages[0]["image_path"]

                # Reduce Step: BM25 Ground Truth Correction
                gt = find_ground_truth(combined_h, book_name, page=int(first_p) if first_p and first_p != "0" else None)
                if gt.paragraph:
                    combined_h = correct_ocr(combined_h, gt.paragraph)
                    _logger.info(f"BM25 matched for concept '{title}': score={gt.score:.1f}")

                # Reduce Step: Synthesis with structural title guideline
                source_ref = find_source_ref(book_name)
                guideline = f"\n\n[GUIDELINE: Bạn BẮT BUỘC phải tạo concept note cho khái niệm mang tên chính xác là '{title}']"
                
                gt_for_synthesis = "" if _is_vietnamese(gt.paragraph) else gt.paragraph
                content = synthesize_concept(
                    highlighted=combined_h + guideline,
                    context=combined_c,
                    ground_truth=gt_for_synthesis,
                    source_name=book_name,
                    source_ref=source_ref,
                    chapter="",
                    page=first_p if first_p != "0" else "",
                    gt_page=str(gt.page or "") if gt.page else "",
                    gt_chapter=gt.chapter,
                    book_macro_context=book_macro_context,
                )

                if content:
                    # Reduce Step: Self-Correction
                    if gt.paragraph:
                        content = verify_and_correct(content, gt.paragraph)
                    
                    # Reduce Step: Save Note & Concept-Centric Image Renaming
                    saved = save_concept(content, image_path=primary_img, book_name=book_name)
                    if saved:
                        created_count += 1
                        processed_images.add(primary_img)

    # Fallback to Classic Flow (Gộp thành 1 note) if Map-Reduce is bypassed or yielded zero notes
    if created_count == 0:
        _logger.info("Map-Reduce bypassed or yielded zero notes. Falling back to Classic Single-Concept Flow.")
        combined_highlighted = "\n\n".join(p["highlighted"] for p in pages_data)
        combined_context = "\n\n".join(p["context"] for p in pages_data)
        first_page = str(pages_data[0]["page_number"]) if pages_data[0]["page_number"] != 0 else None

        gt = find_ground_truth(combined_highlighted, book_name, page=int(first_page) if first_page else None)
        if gt.paragraph:
            combined_highlighted = correct_ocr(combined_highlighted, gt.paragraph)
            log("gt", f"BM25 matched (classic fallback): score={gt.score:.1f}", source=book_name)

        source_ref = find_source_ref(book_name)
        gt_for_synthesis = "" if _is_vietnamese(gt.paragraph) else gt.paragraph
        content = synthesize_concept(
            highlighted=combined_highlighted,
            context=combined_context,
            ground_truth=gt_for_synthesis,
            source_name=book_name,
            source_ref=source_ref,
            chapter="",
            page=first_page or "",
            gt_page=str(gt.page or "") if gt.page else "",
            gt_chapter=gt.chapter,
            book_macro_context=book_macro_context,
        )

        if content:
            if gt.paragraph:
                content = verify_and_correct(content, gt.paragraph)
            
            saved = save_concept(content, image_path=pages_data[0]["image_path"], book_name=book_name)
            if saved:
                created_count += 1
                processed_images.add(pages_data[0]["image_path"])

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
        trigger_moc_rebuild()
        _logger.info(f"Batch processing completed successfully. Synthesized {created_count} concepts.")
        return True

    return False


def _interpolate_page_numbers(pages_data: list[dict]) -> None:
    """Interpolate missing page numbers using forward-fill then backward-fill.

    Modifies pages_data in-place.

    Args:
        pages_data: List of page dicts with 'page_number' key (may be None).
    """
    # Forward fill
    last_known: int | None = None
    for p in pages_data:
        if p["page_number"] is not None:
            last_known = p["page_number"]
        elif last_known is not None:
            last_known += 1
            p["page_number"] = last_known

    # Backward fill for leading None values
    first_known_idx = -1
    for idx, p in enumerate(pages_data):
        if p["page_number"] is not None:
            first_known_idx = idx
            break
    if first_known_idx > 0:
        val = pages_data[first_known_idx]["page_number"]
        for idx in range(first_known_idx - 1, -1, -1):
            val = max(1, val - 1)
            pages_data[idx]["page_number"] = val

    # Enforce default 0 if all pages failed OCR detection
    for p in pages_data:
        if p["page_number"] is None:
            p["page_number"] = 0
