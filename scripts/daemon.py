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

# --- Setup Python path ---
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

# --- Headless stdio hardening (shared) ---
from core.daemon_utils import harden_headless_stdio, is_file_stable
harden_headless_stdio()

from core.config import cfg
from core.log import log

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(cfg.log_dir / "daemon.log", encoding="utf-8"),
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
# Image Processing Pipeline (extracted to pipeline/image_processor.py)
# ============================================================
from pipeline.image_processor import (
    process_image,
    process_image_batch,
    find_source_ref as _find_source_ref,
    trigger_moc_rebuild as _trigger_moc_rebuild,
)



# ============================================================
# File Stability Guard
# ============================================================

def _is_file_stable(path: Path, wait_s: float = _FILE_STABLE_WAIT) -> bool:
    """Delegate to shared daemon utility."""
    return is_file_stable(path, wait_s=wait_s, max_retries=5)



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


_dump_in_progress = False


def _poll_brain_dump() -> None:
    """Poll Brain_Dump.md for new content.

    Runs in a separate daemon thread to avoid blocking Command.md polling
    during long audio transcription or podcast runs.
    """
    global _dump_in_progress
    if _dump_in_progress:
        return
    if not cfg.dump_file.exists():
        return

    mtime = cfg.dump_file.stat().st_mtime
    if mtime <= _poller_state.dump_mtime:
        return
    _poller_state.dump_mtime = mtime

    _dump_in_progress = True

    def _run_dump() -> None:
        global _dump_in_progress
        try:
            from services.brain_dump import handle_brain_dump
            handle_brain_dump()
        except ImportError:
            pass
        except Exception as e:
            _logger.error(f"Brain dump handler error: {e}", exc_info=True)
        finally:
            _dump_in_progress = False

    threading.Thread(target=_run_dump, daemon=True, name="brain-dump-worker").start()


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
