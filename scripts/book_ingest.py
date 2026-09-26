"""VvC Second Brain — Book Ingestion Daemon (v8.15.13).

Watches 03-Resources/books/ for new EPUB/PDF files.
Converts to chunked markdown corpus for BM25 matching.
Creates source notes and book workspaces in 05-Fleeting/.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.daemon_utils import harden_headless_stdio, is_file_stable
harden_headless_stdio()

from core.__version__ import __version__
from core.config import cfg
from core.log import log
from pipeline.book_staging import (
    _convert_book_corpus,
    _convert_epub,
    _create_source_note,
    _create_workspace,
    _normalize_book_name,
    _sync_toc_and_macro_context,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [book] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(cfg.log_dir / "book_ingestion.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout) if sys.stdout and sys.stdout.writable() else logging.NullHandler(),
    ],
)
_logger = logging.getLogger("vvc.book")
BOOK_EXTENSIONS = {".epub", ".pdf"}
_PID_FILE = _SCRIPT_DIR / ".book_ingest.pid"
_work_queue: queue.Queue[Path] = queue.Queue()
_processed_books: set[str] = set()
_shutdown = threading.Event()

__all__ = [
    "BOOK_EXTENSIONS",
    "_convert_book_corpus",
    "_convert_epub",
    "_create_source_note",
    "_create_workspace",
    "_normalize_book_name",
    "_sync_toc_and_macro_context",
    "main",
]


def _manage_pid(action: str) -> bool:
    """Manage PID file operations (write, cleanup, check)."""
    if action == "write":
        _PID_FILE.write_text(str(os.getpid()))
        return True
    if action == "cleanup":
        try:
            _PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return True
    if action == "check":
        if not _PID_FILE.exists():
            return False
        try:
            pid = int(_PID_FILE.read_text().strip())
            if sys.platform == "win32":
                import ctypes
                k32 = ctypes.windll.kernel32
                h = k32.OpenProcess(0x1000, False, pid)
                if h:
                    k32.CloseHandle(h)
                    return True
            else:
                os.kill(pid, 0)
                return True
        except (ValueError, OSError, AttributeError):
            pass
        return False
    return False


def _scan_existing() -> None:
    """Mark already-processed books to avoid re-processing."""
    for item in cfg.resources_books_dir.iterdir():
        if item.is_dir() and item.name.endswith("_MD"):
            _processed_books.add(item.name[:-3])


def _process_book(book_path: Path) -> None:
    """Process a new book: workspace + source note + corpus extraction."""
    book_name = _normalize_book_name(book_path.name)
    if book_name in _processed_books:
        return
    if not is_file_stable(book_path, wait_s=1.5, max_retries=1):
        _logger.warning(f"Skipping {book_path.name} — file not stable yet (still copying?)")
        return

    _logger.info(f"New book detected: {book_path.name}")
    log("book", f"Book detected: {book_path.name}")
    workspace = _create_workspace(book_name, book_path)
    _create_source_note(book_name, book_path)

    if _convert_book_corpus(book_path, book_name, workspace):
        _sync_toc_and_macro_context(book_name, workspace)

    _processed_books.add(book_name)
    log("book", f"Book processed: {book_name}")


def _worker_loop() -> None:
    """Sequential worker for book processing."""
    _logger.info("Book worker thread started")
    while not _shutdown.is_set():
        try:
            item = _work_queue.get(timeout=3)
        except queue.Empty:
            continue
        try:
            _process_book(item)
        except Exception as e:
            _logger.error(f"Book processing error for {item.name}: {e}", exc_info=True)
        finally:
            _work_queue.task_done()
    _logger.info("Book worker thread stopped")


def _on_file_created(event_path: str) -> None:
    """Queue new book for processing."""
    path = Path(event_path)
    if path.suffix.lower() in BOOK_EXTENSIONS and _normalize_book_name(path.name) not in _processed_books:
        _logger.info(f"New book detected and queued: {path.name}")
        _work_queue.put(path)


def _start_watchdog_with_retry(path: Path, handler, max_retries: int = 6):
    """Start Watchdog Observer with exponential backoff retry."""
    from watchdog.observers import Observer

    for attempt in range(max_retries):
        try:
            if not path.exists():
                raise OSError(f"Watch path not found: {path}")
            obs = Observer()
            obs.schedule(handler, str(path), recursive=False)
            obs.start()
            _logger.info(f"Book watchdog started: {path}")
            return obs
        except Exception as e:
            wait = 2 ** attempt
            _logger.warning(f"Watchdog start failed ({attempt + 1}/{max_retries}): {e}. Retry in {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
    _logger.error("Book watchdog failed to start after all retries.")
    return None


def _scan_unprocessed() -> None:
    """Scan books directory for any pre-existing books that haven't been processed yet."""
    _logger.info("Scanning for pre-existing unprocessed books...")
    try:
        for item in cfg.resources_books_dir.iterdir():
            if item.is_file() and item.suffix.lower() in BOOK_EXTENSIONS and _normalize_book_name(item.name) not in _processed_books:
                _logger.info(f"Found unprocessed book on startup: {item.name}")
                _work_queue.put(item)
    except Exception as e:
        _logger.error(f"Error during startup book scan: {e}")


def _wait_for_books_dir(max_retries: int = 15) -> bool:
    """Wait for books directory to be accessible (GDrive mount guard)."""
    for attempt in range(max_retries):
        if cfg.resources_books_dir.exists():
            return True
        _logger.warning(f"Vault books dir not ready ({attempt + 1}/{max_retries}). Waiting 10s...")
        time.sleep(10)
    return False


def _create_book_observer():
    """Instantiate and start watchdog observer for books directory."""
    try:
        from watchdog.events import FileSystemEventHandler

        class BookHandler(FileSystemEventHandler):
            def on_created(self, e):
                if not e.is_directory:
                    _on_file_created(e.src_path)

            def on_moved(self, e):
                if not e.is_directory:
                    _on_file_created(e.dest_path)

        return _start_watchdog_with_retry(cfg.resources_books_dir, BookHandler())
    except ImportError:
        _logger.error("watchdog not installed!")
        return None


def _observer_supervision_loop(observer) -> None:
    """Monitor observer liveness and auto-restart if disconnected."""
    last_check = time.time()
    while not _shutdown.is_set():
        time.sleep(1)
        if (observer is None or not observer.is_alive()) and time.time() - last_check >= 60:
            last_check = time.time()
            _logger.warning("Book watchdog Observer not active — attempting restart...")
            observer = _create_book_observer()
            if observer:
                log("book", "Book watchdog auto-restarted after disconnect")
    if observer:
        observer.stop()
        observer.join(timeout=5)


def main() -> None:
    """Start the book ingestion daemon with Watchdog Observer."""
    def _sig_handler(sig, frame):
        _logger.info("Shutdown signal received")
        _shutdown.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _sig_handler)
        except Exception:
            pass

    _logger.info(f"Book Ingestion Daemon v{__version__} (Watchdog-driven) started")
    if _manage_pid("check"):
        _logger.warning("Another book ingestion daemon instance is already running. Exiting.")
        return
    _manage_pid("write")

    if not _wait_for_books_dir():
        _logger.error("Vault books directory not found after waiting 150s. Exiting.")
        _manage_pid("cleanup")
        return

    _scan_existing()
    _logger.info(f"Known books: {len(_processed_books)}")

    worker = threading.Thread(target=_worker_loop, daemon=False, name="book-worker")
    worker.start()
    observer = _create_book_observer()
    _scan_unprocessed()

    try:
        _observer_supervision_loop(observer)
    except KeyboardInterrupt:
        _shutdown.set()
    finally:
        _logger.info("Waiting for book worker thread to finish...")
        worker.join(timeout=30)
        _manage_pid("cleanup")
        _logger.info("Book Ingestion Daemon stopped")


if __name__ == "__main__":
    main()
