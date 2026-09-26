"""VvC Second Brain — Fleeting Ingestion Queue & Batch Engine.

Coordinates image batch debouncing, file stability checks, and background
pipeline worker execution for newly arrived Fleeting notes and book images.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from core.config import cfg
from core.daemon_utils import is_file_stable
from core.log import log
from pipeline.image_processor import process_image, process_image_batch

_logger = logging.getLogger("vvc.daemon.queue")

IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
FILE_STABLE_WAIT: float = 1.5
BATCH_COOLDOWN: float = 10.0

work_queue: queue.Queue = queue.Queue()  # items: Path | list[Path]
pending_batches: dict[str, list[tuple[Path, float]]] = {}
in_flight_paths: set[Path] = set()
pending_lock = threading.Lock()


def is_fleeting_candidate(path: Path) -> bool:
    """Determine if a file is an ingestion candidate in Fleeting workspace."""
    ext = path.suffix.lower()
    if ext not in IMAGE_EXTENSIONS and ext != ".md":
        return False
    if ext == ".md" and path.name in ("Command.md", "Brain_Dump.md"):
        return False
    # Skip internal files with leading underscore unless they are TOC or cover images
    if path.name.startswith("_") and not (
        path.name.lower().startswith("_toc") or path.name.lower().startswith("_cover")
    ):
        return False
    return True


def on_file_created(event_path: str) -> None:
    """Handle new file creation in Fleeting workspace.

    Applies two guards before enqueuing:
    1. File Stability Guard: waits until file size is stable (no partial syncs).
    2. Temporal Batch Debounce: groups images dropped within BATCH_COOLDOWN seconds
       in the same workspace into a single batch task.
    """
    path = Path(event_path)
    if not is_fleeting_candidate(path):
        return

    with pending_lock:
        if path in in_flight_paths:
            return
        in_flight_paths.add(path)

    if not is_file_stable(path, wait_s=FILE_STABLE_WAIT):
        _logger.warning(f"Skipping {path.name} — file not stable yet (still syncing?)")
        with pending_lock:
            in_flight_paths.discard(path)
        return

    if not path.exists():
        with pending_lock:
            in_flight_paths.discard(path)
        return

    workspace_key = str(path.parent)
    with pending_lock:
        if workspace_key not in pending_batches:
            pending_batches[workspace_key] = []
        if any(p == path for p, _ in pending_batches[workspace_key]):
            _logger.debug(f"Already staged for batching: {path.name}")
            return
        pending_batches[workspace_key].append((path, time.monotonic()))
    _logger.info(f"Staged for batching: {path.name} (workspace: {path.parent.name})")


def flush_batches(shutdown_event: threading.Event) -> None:
    """Background loop: flush pending image batches after cooldown."""
    _logger.info("Batch flusher started")
    while not shutdown_event.is_set():
        time.sleep(1)
        now = time.monotonic()
        to_flush: list[tuple[str, list[Path]]] = []

        with pending_lock:
            for ws_key, entries in list(pending_batches.items()):
                latest_arrival = max(t for _, t in entries)
                if now - latest_arrival >= BATCH_COOLDOWN:
                    paths = [p for p, _ in entries]
                    to_flush.append((ws_key, paths))
                    del pending_batches[ws_key]

        for ws_key, paths in to_flush:
            if len(paths) == 1:
                work_queue.put(paths[0])
                _logger.info(f"Enqueued (single): {paths[0].name}")
            else:
                work_queue.put(paths)
                names = ", ".join(p.name for p in paths)
                _logger.info(f"Enqueued (batch {len(paths)}): {names}")
                log("ingest", f"Batch of {len(paths)} images queued", source=Path(ws_key).name)


def _process_queue_item(item: Path | list[Path]) -> None:
    """Execute pipeline processing on a dequeued item."""
    try:
        if isinstance(item, list):
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


def worker_loop(shutdown_event: threading.Event) -> None:
    """Single-threaded worker processing images and markdown files from work_queue."""
    _logger.info("Worker loop started")
    while not shutdown_event.is_set():
        try:
            item = work_queue.get(timeout=5)
        except queue.Empty:
            continue

        try:
            _process_queue_item(item)
        finally:
            with pending_lock:
                if isinstance(item, list):
                    for p in item:
                        in_flight_paths.discard(p)
                else:
                    in_flight_paths.discard(item)
            work_queue.task_done()


def scan_existing_files(shutdown_event: threading.Event | None = None) -> None:
    """Scan fleeting directory on startup for any existing unprocessed files."""
    _logger.info("Scanning for pre-existing unprocessed files in 05-Fleeting...")
    try:
        fleeting_dir = cfg.fleeting_dir
        if not fleeting_dir.exists():
            return

        found_any = False
        for path in fleeting_dir.rglob("*"):
            if shutdown_event and shutdown_event.is_set():
                break
            if not path.is_file() or not is_fleeting_candidate(path):
                continue

            _logger.info(f"Found pre-existing file: {path.relative_to(fleeting_dir)}")
            found_any = True
            on_file_created(str(path))

        if found_any:
            _logger.info("Startup scan complete. Pre-existing files queued for batching.")
        else:
            _logger.info("Startup scan complete. No pre-existing files found.")
    except Exception as e:
        _logger.error(f"Error during startup scan: {e}", exc_info=True)
