"""VvC Second Brain — Main Daemon (v7.5 Batching + Stability Guard).

Watchdog-based daemon that monitors 05-Fleeting/ for new images
and processes them through the 5-stage pipeline:
  OCR → Ground Truth → Synthesize → Self-Correct → Post-Process

New in v7.5:
  - Fix #2: Deterministic File Stability Guard — replaces naive time.sleep(1)
    with _is_file_stable() size-check to prevent processing partially-synced files.
  - Fix #3: Temporal Batching Engine — images dropped within 10s in the same
    workspace are grouped into a single batch task → one Concept Note per concept.

Also monitors Command.md and Brain_Dump.md for interactive queries.

Usage:
    pythonw.exe daemon.py      # Headless (production)
    python daemon.py           # Interactive (debug)
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# --- Headless stdio hardening (pythonw.exe & hidden python.exe compatibility) ---
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name)
    _is_valid = False
    if _stream is not None and hasattr(_stream, "write"):
        try:
            _stream.write("")
            _stream.flush()
            _is_valid = True
        except Exception:
            pass
    if not _is_valid:
        try:
            setattr(sys, _stream_name, open(os.devnull, "w", encoding="utf-8"))
        except Exception:
            setattr(sys, _stream_name, None)

# Set console streams to UTF-8 to prevent cp1252/UnicodeEncodeError on Windows if they are valid
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- Setup Python path ---
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg
from core.log import log

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(_SCRIPT_DIR / "daemon.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout) if (sys.stdout and hasattr(sys.stdout, "write")) else logging.NullHandler(),
    ],
)
_logger = logging.getLogger("vvc.daemon")

# --- Constants ---
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COMMAND_POLL_INTERVAL = 15  # seconds
BRAINDUMP_POLL_INTERVAL = 30
FLEETING_POLL_INTERVAL = 30  # seconds
_FILE_STABLE_WAIT = 1.5      # seconds between file size checks
_BATCH_COOLDOWN = 30.0       # seconds of inactivity before flushing a batch

# --- Work Queue ---
_work_queue: queue.Queue = queue.Queue()  # items: Path | list[Path]
_shutdown = threading.Event()

# --- Batching State ---
# Maps workspace dir (str) → list of (Path, arrival_time)
_pending_batches: dict[str, list[tuple[Path, float]]] = {}
# Tracks all files currently in-flight (staged, in queue, or processing)
_in_flight_paths: set[Path] = set()
_pending_lock = threading.Lock()


# ============================================================
# Image Processing Pipeline
# ============================================================

def process_image(image_path: Path) -> bool:
    """Run the full 5-stage pipeline on a single image.

    Returns True if a concept note was successfully created.
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
    source_ref = _find_source_ref(book_name)

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
        _trigger_moc_rebuild()
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


def _find_source_ref(book_name: str) -> str:
    """Find the source note reference for a book."""
    for f in cfg.sources_dir.iterdir():
        if f.suffix == ".md" and book_name.lower().replace("_", " ") in f.stem.lower().replace("_", " "):
            return f.stem
    return book_name


def _trigger_moc_rebuild() -> None:
    """Trigger MOC + Index rebuild after concept creation."""
    try:
        from wiki_maintain import rebuild_all
        rebuild_all()
    except Exception as e:
        _logger.warning(f"MOC rebuild failed: {e}")


# ============================================================
# File Stability Guard
# ============================================================

def _is_file_stable(path: Path, wait_s: float = _FILE_STABLE_WAIT) -> bool:
    """Check if a file has finished being written by comparing size twice.

    Prevents processing images still syncing from cloud/junction by retrying
    up to 5 times if the size is changing or zero.

    Args:
        path: File to check.
        wait_s: Seconds to wait between size checks.

    Returns:
        True if file size is stable and non-zero (write complete).
    """
    retries = 5
    for i in range(retries):
        try:
            if not path.exists():
                return False
            size1 = path.stat().st_size
            time.sleep(wait_s)
            size2 = path.stat().st_size
            if size1 == size2 and size1 > 0:
                return True
            _logger.info(f"File {path.name} is still writing/syncing (size: {size1} -> {size2}), retrying check ({i+1}/{retries})...")
        except OSError:
            time.sleep(wait_s)
    return False



# ============================================================
# Watchdog Handler
# ============================================================

def _on_file_created(event_path: str) -> None:
    """Handle new file creation in Fleeting directory.

    Applies two guards before enqueuing:
    1. File Stability Guard: waits until file size is stable (no partial syncs).
    2. Temporal Batch Debounce: groups images dropped within BATCH_COOLDOWN seconds
       in the same workspace into a single batch task.
    """
    path = Path(event_path)
    ext = path.suffix.lower()

    if ext not in IMAGE_EXTENSIONS and ext != ".md":
        return

    if ext == ".md" and path.name in ("Command.md", "Brain_Dump.md"):
        return

    # Skip internal files starting with underscore (like _toc.json, _context.txt), but allow _toc and _cover images
    if path.name.startswith("_") and not (path.name.lower().startswith("_toc") or path.name.lower().startswith("_cover")):
        return

    # In-flight guard: check early before stability check
    with _pending_lock:
        if path in _in_flight_paths:
            return
        _in_flight_paths.add(path)

    # Fix #2: Deterministic stability guard (replaces naive time.sleep(1))
    if not _is_file_stable(path):
        _logger.warning(f"Skipping {path.name} — file not stable yet (still syncing?)")
        with _pending_lock:
            _in_flight_paths.discard(path)
        return

    if not path.exists():
        with _pending_lock:
            _in_flight_paths.discard(path)
        return

    # Fix #3: Temporal batch debounce — group images by workspace
    workspace_key = str(path.parent)
    with _pending_lock:
        if workspace_key not in _pending_batches:
            _pending_batches[workspace_key] = []
        # Guard against duplicate enqueuing
        if any(p == path for p, _ in _pending_batches[workspace_key]):
            _logger.debug(f"Already staged for batching: {path.name}")
            return
        _pending_batches[workspace_key].append((path, time.monotonic()))
    _logger.info(f"Staged for batching: {path.name} (workspace: {path.parent.name})")


def _flush_batches() -> None:
    """Background loop: flush pending image batches after cooldown.

    Runs every second. When a workspace has had no new images for
    BATCH_COOLDOWN seconds, enqueues all its staged images as a batch.
    Single-image batches are enqueued as plain Path (normal flow).
    Multi-image batches are enqueued as list[Path] (batch flow).
    """
    _logger.info("Batch flusher started")
    while not _shutdown.is_set():
        time.sleep(1)
        now = time.monotonic()
        to_flush: list[tuple[str, list[Path]]] = []

        with _pending_lock:
            for ws_key, entries in list(_pending_batches.items()):
                latest_arrival = max(t for _, t in entries)
                if now - latest_arrival >= _BATCH_COOLDOWN:
                    paths = [p for p, _ in entries]
                    to_flush.append((ws_key, paths))
                    del _pending_batches[ws_key]

        for ws_key, paths in to_flush:
            if len(paths) == 1:
                _work_queue.put(paths[0])
                _logger.info(f"Enqueued (single): {paths[0].name}")
            else:
                _work_queue.put(paths)  # batch
                names = ", ".join(p.name for p in paths)
                _logger.info(f"Enqueued (batch {len(paths)}): {names}")
                log("ingest", f"Batch of {len(paths)} images queued", source=Path(ws_key).name)


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
    last_known: int | None = None
    for p in pages_data:
        if p["page_number"] is not None:
            last_known = p["page_number"]
        elif last_known is not None:
            # Interpolate forwards
            last_known += 1
            p["page_number"] = last_known

    # Interpolate backwards for leading None values
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
                source_ref = _find_source_ref(book_name)
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

        source_ref = _find_source_ref(book_name)
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
        _trigger_moc_rebuild()
        _logger.info(f"Batch processing completed successfully. Synthesized {created_count} concepts.")
        return True

    return False


def _worker_loop() -> None:
    """Single-threaded worker that processes images from the queue.

    Handles two item types from the queue:
    - Path: single image (normal flow via process_image)
    - list[Path]: multi-image batch (batch flow via process_image_batch)
    """
    _logger.info("Worker loop started")
    while not _shutdown.is_set():
        try:
            item = _work_queue.get(timeout=5)
        except queue.Empty:
            continue

        try:
            if isinstance(item, list):
                # Batch of images from same workspace
                process_image_batch(item)
            elif item.suffix.lower() == ".md":
                from pipeline.process_markdown import process_markdown_file
                process_markdown_file(item)
            else:
                process_image(item)
        except Exception as e:
            src = item[0].name if isinstance(item, list) else item.name
            _logger.error(f"Pipeline error: {e}", exc_info=True)
            log("error", f"Pipeline error: {e}", source=src)
        finally:
            with _pending_lock:
                if isinstance(item, list):
                    for p in item:
                        _in_flight_paths.discard(p)
                else:
                    _in_flight_paths.discard(item)
            _work_queue.task_done()


# ============================================================
# Command.md & Brain_Dump.md Polling
# ============================================================

@dataclass
class _PollerState:
    """Tracks last-seen mtimes for Command.md and Brain_Dump.md."""
    command_mtime: float = 0.0
    dump_mtime: float = 0.0

_poller_state = _PollerState()


def _poll_command() -> None:
    """Poll Command.md for new queries."""
    if not cfg.command_file.exists():
        return

    mtime = cfg.command_file.stat().st_mtime
    if mtime <= _poller_state.command_mtime:
        return
    _poller_state.command_mtime = mtime

    try:
        from services.command import handle_command
        handle_command()
    except ImportError:
        pass
    except Exception as e:
        _logger.error(f"Command handler error: {e}", exc_info=True)


def _poll_brain_dump() -> None:
    """Poll Brain_Dump.md for new content."""
    if not cfg.dump_file.exists():
        return

    mtime = cfg.dump_file.stat().st_mtime
    if mtime <= _poller_state.dump_mtime:
        return
    _poller_state.dump_mtime = mtime

    try:
        from services.brain_dump import handle_brain_dump
        handle_brain_dump()
    except ImportError:
        pass
    except Exception as e:
        _logger.error(f"Brain dump handler error: {e}", exc_info=True)


def _poll_fleeting_dir() -> None:
    """Poll fleeting directory recursively for unprocessed files.

    Used as a fallback for cloud sync mounts (like Google Drive)
    which may not fire filesystem change notifications on Windows.
    """
    try:
        fleeting_dir = cfg.fleeting_dir
        if not fleeting_dir.exists():
            return

        for path in fleeting_dir.rglob("*"):
            if _shutdown.is_set():
                break
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in IMAGE_EXTENSIONS and ext != ".md":
                continue
            if ext == ".md" and path.name in ("Command.md", "Brain_Dump.md"):
                continue
            # Skip internal files starting with underscore (like _toc.json, _context.txt), but allow _toc and _cover images
            if path.name.startswith("_") and not (path.name.lower().startswith("_toc") or path.name.lower().startswith("_cover")):
                continue

            with _pending_lock:
                if path in _in_flight_paths:
                    continue

            _logger.info(f"Poller found unprocessed file: {path.name}")
            _on_file_created(str(path))
    except Exception as e:
        _logger.error(f"Error during fleeting dir poll: {e}", exc_info=True)


def _poll_loop() -> None:
    """Background polling for Command.md, Brain_Dump.md, and Fleeting folder."""
    last_cmd_poll = 0.0
    last_dump_poll = 0.0
    last_fleeting_poll = 0.0

    while not _shutdown.is_set():
        now = time.time()

        if now - last_cmd_poll >= COMMAND_POLL_INTERVAL:
            _poll_command()
            last_cmd_poll = now

        if now - last_dump_poll >= BRAINDUMP_POLL_INTERVAL:
            _poll_brain_dump()
            last_dump_poll = now

        if now - last_fleeting_poll >= FLEETING_POLL_INTERVAL:
            _poll_fleeting_dir()
            last_fleeting_poll = now

        time.sleep(3)


# ============================================================
# PID Guard & Watchdog Helpers
# ============================================================

_PID_FILE = _SCRIPT_DIR / ".daemon.pid"


def _write_pid() -> None:
    """Write PID file to prevent duplicate instances."""
    _PID_FILE.write_text(str(os.getpid()))


def _cleanup_pid() -> None:
    """Remove PID file on shutdown."""
    try:
        _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _check_pid() -> bool:
    """Check if another daemon instance is running."""
    if not _PID_FILE.exists():
        return False
    try:
        pid = int(_PID_FILE.read_text().strip())
        # Check if process exists (Windows)
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except (ValueError, OSError, AttributeError):
        pass
    return False


def _start_watchdog_with_retry(path: Path, handler, max_retries: int = 6):
    """Start Watchdog Observer with exponential backoff retry.

    Handles the race condition where GDrive Desktop junction is not yet
    mounted when the daemon starts at boot (before GDrive connects).

    Args:
        path: Directory to watch (may be a Windows junction to GDrive).
        handler: FileSystemEventHandler instance.
        max_retries: Number of retry attempts (default 6 = up to ~63s total).

    Returns:
        Running Observer, or None if all retries exhausted.
    """
    from watchdog.observers import Observer

    for attempt in range(max_retries):
        try:
            if not path.exists():
                raise OSError(f"Watch path not found: {path}")
            obs = Observer()
            obs.schedule(handler, str(path), recursive=True)
            obs.start()
            _logger.info(f"Watchdog started: {path}")
            return obs
        except Exception as e:
            wait = 2 ** attempt  # 1, 2, 4, 8, 16, 32 seconds
            _logger.warning(
                f"Watchdog start failed (attempt {attempt + 1}/{max_retries}): {e}. "
                f"Retry in {wait}s (GDrive may not be mounted yet)..."
            )
            if attempt < max_retries - 1:
                time.sleep(wait)

    _logger.error("Watchdog failed to start after all retries. Image ingestion disabled.")
    return None


def _scan_existing_files() -> None:
    """Scan fleeting directory on startup for any existing unprocessed files.

    Feeds them to _on_file_created to utilize the stability guard and batch debouncer.
    """
    _logger.info("Scanning for pre-existing unprocessed files in 05-Fleeting...")
    try:
        fleeting_dir = cfg.fleeting_dir
        if not fleeting_dir.exists():
            return

        found_any = False
        # Recursive scan of the fleeting directory
        for path in fleeting_dir.rglob("*"):
            if _shutdown.is_set():
                break
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in IMAGE_EXTENSIONS and ext != ".md":
                continue
            if ext == ".md" and path.name in ("Command.md", "Brain_Dump.md"):
                continue
            # Skip internal files starting with underscore (like _toc.json, _context.txt), but allow _toc and _cover images
            if path.name.startswith("_") and not (path.name.lower().startswith("_toc") or path.name.lower().startswith("_cover")):
                continue

            _logger.info(f"Found pre-existing file: {path.relative_to(fleeting_dir)}")
            found_any = True
            # Process via the normal creation handler to utilize batching and stability checks
            _on_file_created(str(path))

        if found_any:
            _logger.info("Startup scan complete. Pre-existing files queued for batching.")
        else:
            _logger.info("Startup scan complete. No pre-existing files found.")
    except Exception as e:
        _logger.error(f"Error during startup scan: {e}", exc_info=True)


def main() -> None:
    """Start the daemon."""
    if _check_pid():
        _logger.warning("Another daemon instance is already running")
        return

    _write_pid()
    log("lifecycle", "Daemon v7.5 started")
    _logger.info("=" * 50)
    _logger.info("VvC Second Brain — Daemon v7.5 (Batching + Stability Guard)")
    _logger.info(f"Vault: {cfg.vault_root}")
    _logger.info(f"Backend: {cfg.backend} | Fallback: {cfg.fallback}")
    _logger.info("=" * 50)

    global _poller_state
    _poller_state = _PollerState()  # Reset state on (re)start

    # Start worker thread (non-daemon: allow graceful finish on shutdown)
    worker = threading.Thread(target=_worker_loop, daemon=False, name="worker")
    worker.start()

    # Start batch flusher thread (daemon: ok to terminate on exit)
    flusher = threading.Thread(target=_flush_batches, daemon=True, name="flusher")
    flusher.start()

    # Start polling thread (non-daemon: allow clean exit)
    poller = threading.Thread(target=_poll_loop, daemon=False, name="poller")
    poller.start()

    # Start startup scanner thread (daemon: ok to terminate on exit, runs once)
    scanner = threading.Thread(target=_scan_existing_files, daemon=True, name="startup-scanner")
    scanner.start()

    # Start Watchdog with retry (handles GDrive junction not yet mounted at boot)
    try:
        from watchdog.events import FileSystemEventHandler

        class ImageHandler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    _on_file_created(event.src_path)
            def on_moved(self, event):
                if not event.is_directory:
                    _on_file_created(event.dest_path)

        observer = _start_watchdog_with_retry(cfg.fleeting_dir, ImageHandler())
    except ImportError:
        _logger.error("watchdog not installed!")
        observer = None

    # Signal handling
    def _signal_handler(sig, frame):
        _logger.info("Shutdown signal received")
        _shutdown.set()
        if observer:
            observer.stop()

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception as sig_err:
        _logger.warning(f"Failed to register signal handlers (normal in headless/service mode): {sig_err}")

    # Main loop
    try:
        last_observer_check = time.time()
        while not _shutdown.is_set():
            time.sleep(1)

            # Watchdog health check: restart Observer if it died mid-session
            # (e.g. GDrive Desktop disconnected and reconnected, or failed to start initially)
            if observer is None or not observer.is_alive():
                now = time.time()
                if now - last_observer_check >= 60:
                    last_observer_check = now
                    _logger.warning("Watchdog Observer not active — attempting restart...")
                    try:
                        from watchdog.events import FileSystemEventHandler

                        class _RevivedImageHandler(FileSystemEventHandler):
                            def on_created(self, event):
                                if not event.is_directory:
                                    _on_file_created(event.src_path)
                            def on_moved(self, event):
                                if not event.is_directory:
                                    _on_file_created(event.dest_path)

                        observer = _start_watchdog_with_retry(cfg.fleeting_dir, _RevivedImageHandler())
                        if observer:
                            log("lifecycle", "Watchdog auto-restarted after disconnect")
                    except Exception as revive_err:
                        _logger.error(f"Watchdog revival failed: {revive_err}")
    except KeyboardInterrupt:
        _shutdown.set()
    finally:
        if observer:
            observer.stop()
            observer.join(timeout=5)
        # Graceful shutdown: wait for worker to finish current task (max 30s)
        _logger.info("Waiting for worker thread to finish current task...")
        worker.join(timeout=30)
        poller.join(timeout=5)
        if worker.is_alive():
            _logger.warning("Worker thread did not finish in time — forcing exit")
        _cleanup_pid()
        log("lifecycle", "Daemon v7.5 stopped")
        _logger.info("Daemon stopped")


if __name__ == "__main__":
    main()
