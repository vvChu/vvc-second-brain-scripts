"""VvC Second Brain — Book Ingestion Daemon (v7.0).

Watches 03-Resources/books/ for new EPUB/PDF files.
Converts to chunked markdown corpus for BM25 matching.
Creates source notes and book workspaces in 05-Fleeting/.

Usage:
    pythonw.exe book_ingest.py   # Headless
    python book_ingest.py        # Debug
"""

from __future__ import annotations

import logging
import os
import re
import signal
import sys
import threading
import time
from datetime import date
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

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg
from core.frontmatter import build_frontmatter
from core.llm import call_llm
from core.log import log

try:
    from epub_convert import convert_epub as _convert_epub_fn
except ImportError:
    _convert_epub_fn = None  # type: ignore[assignment]

try:
    from pdf_convert import convert_pdf as _convert_pdf_fn
except ImportError:
    _convert_pdf_fn = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [book] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(_SCRIPT_DIR / "book_ingestion.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout) if sys.stdout and sys.stdout.writable() else logging.NullHandler(),
    ],
)
_logger = logging.getLogger("vvc.book")

BOOK_EXTENSIONS = {".epub", ".pdf"}

import queue

_work_queue: queue.Queue[Path] = queue.Queue()
_processed_books: set[str] = set()
_shutdown = threading.Event()


def _scan_existing() -> None:
    """Mark already-processed books to avoid re-processing."""
    for item in cfg.resources_books_dir.iterdir():
        if item.is_dir() and item.name.endswith("_MD"):
            _processed_books.add(item.name.replace("_MD", ""))


def _normalize_book_name(filename: str) -> str:
    """Convert book filename to workspace name."""
    stem = Path(filename).stem
    # Replace spaces and special chars with underscores
    name = re.sub(r"[^a-zA-Z0-9À-ỹ]+", "_", stem)
    name = name.strip("_")
    return name


def _create_workspace(book_name: str, book_path: Path) -> Path:
    """Create a workspace folder in 05-Fleeting/ for photo drops."""
    workspace = cfg.fleeting_dir / book_name
    workspace.mkdir(parents=True, exist_ok=True)

    # Create _context.txt with book metadata
    context_file = workspace / "_context.txt"
    if not context_file.exists():
        corpus_rel = f"03 - Resources/books/{book_name}_MD"
        archive_rel = f"99 - Archive/{book_name}"
        context_file.write_text(
            f"book_title: {book_path.stem}\n"
            f"book_file: {book_path.name}\n"
            f"date_added: {date.today().isoformat()}\n"
            f"status: active\n"
            f"corpus_rel_path: {corpus_rel}\n"
            f"archive_rel_path: {archive_rel}\n",
            encoding="utf-8",
        )

    return workspace


def _create_source_note(book_name: str, book_path: Path) -> Path:
    """Create a source summary note in 04-Permanent/sources/."""
    today = date.today().isoformat()
    filename = f"{today}_{book_name.lower()}.md"
    source_path = cfg.sources_dir / filename

    if source_path.exists():
        return source_path

    # Generate metadata via LLM
    title = book_path.stem.replace("_", " ").replace("-", " ")

    fm = build_frontmatter({
        "title": title,
        "author": "",
        "aliases": [title],
        "tags": ["knowledge", "type/source"],
        "type": "source",
        "date_created": today,
        "date_modified": today,
        "source": book_path.name,
        "source_type": book_path.suffix.lstrip("."),
        "summary": f"Source note for: {title}",
        "related": [],
        "confidence": "high",
    })

    body = f"\n# {title}\n\n> Source summary pending ingestion.\n\n## Metadata\n\n- File: `{book_path.name}`\n- Format: {book_path.suffix.upper()}\n- Added: {today}\n"

    try:
        source_path.write_text(fm + body, encoding="utf-8")
        _logger.info(f"Source note created: {source_path.name}")
    except OSError as e:
        _logger.error(f"Failed to create source note: {e}")

    return source_path


def _convert_epub(book_path: Path, book_name: str) -> bool:
    """Convert EPUB to chunked markdown corpus."""
    output_dir = cfg.resources_books_dir / f"{book_name}_MD"
    if output_dir.exists() and any(output_dir.glob("*.md")):
        _logger.info(f"MD corpus already exists: {output_dir.name}")
        return True

    if _convert_epub_fn is not None:
        return _convert_epub_fn(book_path, output_dir)

    # Fallback: basic ebooklib extraction
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(book_path))
        output_dir.mkdir(parents=True, exist_ok=True)

        idx = 0
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if len(text) < 100:
                continue

            md_name = f"{idx:02d}_{item.get_name().replace('/', '_').replace('.xhtml', '')}.md"
            (output_dir / md_name).write_text(text, encoding="utf-8")
            idx += 1

        _logger.info(f"EPUB extracted: {idx} chapters -> {output_dir.name}")
        return idx > 0
    except Exception as e:
        _logger.error(f"EPUB conversion failed: {e}")
        return False


def _is_file_stable(path: Path, wait_s: float = 1.5) -> bool:
    """Check if a file has finished being written by comparing size twice.

    Prevents processing a PDF/EPUB that is still being copied into the folder.

    Args:
        path: File to check.
        wait_s: Seconds to wait between size checks.

    Returns:
        True if file size is stable (copy complete).
    """
    try:
        size1 = path.stat().st_size
        time.sleep(wait_s)
        size2 = path.stat().st_size
        return size1 == size2 and size1 > 0
    except OSError:
        return False


def _process_book(book_path: Path) -> None:
    """Process a new book: workspace + source note + corpus extraction."""
    book_name = _normalize_book_name(book_path.name)

    if book_name in _processed_books:
        return

    # Guard against partially-written files (still being copied)
    if not _is_file_stable(book_path):
        _logger.warning(f"Skipping {book_path.name} — file not stable yet (still copying?)")
        return

    _logger.info(f"New book detected: {book_path.name}")
    log("book", f"Book detected: {book_path.name}")

    # 1. Create workspace
    workspace = _create_workspace(book_name, book_path)

    # 2. Create source note
    _create_source_note(book_name, book_path)

    # 3. Convert to markdown corpus
    converted = False
    if book_path.suffix.lower() == ".epub":
        converted = _convert_epub(book_path, book_name)
    elif book_path.suffix.lower() == ".pdf":
        if _convert_pdf_fn is not None:
            try:
                converted = _convert_pdf_fn(book_path, workspace_dir=workspace)
            except Exception as e:
                _logger.error(f"Failed to run convert_pdf: {e}")
        else:
            _logger.warning("pdf_convert module not available")

    # 4. Sync original TOC template to workspace
    if converted:
        md_dir = cfg.resources_books_dir / f"{book_name}_MD"
        toc_original = md_dir / "_toc_original.json"
        workspace_toc = workspace / "_toc.json"
        
        if toc_original.exists() and not workspace_toc.exists():
            try:
                import shutil
                shutil.copy(str(toc_original), str(workspace_toc))
                _logger.info(f"Copied original TOC template to workspace: {workspace.name}/_toc.json")
            except OSError as e:
                _logger.error(f"Failed to copy original TOC template: {e}")

    # 5. Eagerly generate book macro context block inside _context.txt
    try:
        from pipeline.map_reduce import get_or_create_book_context
        get_or_create_book_context(workspace)
        _logger.info(f"Eagerly generated <BOOK_CONTEXT> for {book_name}")
    except Exception as e:
        _logger.warning(f"Failed to eagerly generate <BOOK_CONTEXT> for {book_name}: {e}")

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
    if path.suffix.lower() in BOOK_EXTENSIONS:
        book_name = _normalize_book_name(path.name)
        if book_name not in _processed_books:
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
            wait = 2 ** attempt  # 1, 2, 4, 8, 16, 32 seconds
            _logger.warning(
                f"Book watchdog start failed (attempt {attempt + 1}/{max_retries}): {e}. "
                f"Retry in {wait}s (GDrive may not be mounted yet)..."
            )
            if attempt < max_retries - 1:
                time.sleep(wait)

    _logger.error("Book watchdog failed to start after all retries. Image ingestion disabled.")
    return None


def _scan_unprocessed() -> None:
    """Scan books directory for any pre-existing books that haven't been processed yet."""
    _logger.info("Scanning for pre-existing unprocessed books...")
    try:
        found_any = False
        for item in cfg.resources_books_dir.iterdir():
            if item.is_file() and item.suffix.lower() in BOOK_EXTENSIONS:
                book_name = _normalize_book_name(item.name)
                if book_name not in _processed_books:
                    _logger.info(f"Found unprocessed book on startup: {item.name}")
                    _work_queue.put(item)
                    found_any = True
        if not found_any:
            _logger.info("No unprocessed books found on startup.")
    except Exception as e:
        _logger.error(f"Error during startup book scan: {e}")


def main() -> None:
    """Start the book ingestion daemon with Watchdog Observer."""
    def _signal_handler(sig, frame):
        _logger.info("Shutdown signal received")
        _shutdown.set()

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception as sig_err:
        _logger.warning(f"Failed to register signal handlers (normal in headless/service mode): {sig_err}")

    _logger.info("Book Ingestion Daemon v8.0 (Watchdog-driven) started")

    # JIT Google Drive mount / junction directory readiness guard
    max_retries = 15
    for attempt in range(max_retries):
        if cfg.resources_books_dir.exists():
            break
        _logger.warning(f"Vault books directory not ready yet (attempt {attempt + 1}/{max_retries}). GDrive may not be mounted. Waiting 10s...")
        time.sleep(10)

    if not cfg.resources_books_dir.exists():
        _logger.error("Vault books directory not found after waiting 150s. Exiting to prevent crash.")
        return

    _scan_existing()
    _logger.info(f"Known books: {len(_processed_books)}")

    # Start sequential worker thread
    worker = threading.Thread(target=_worker_loop, daemon=False, name="book-worker")
    worker.start()

    # Start watchdog observer
    try:
        from watchdog.events import FileSystemEventHandler

        class BookHandler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    _on_file_created(event.src_path)
            def on_moved(self, event):
                if not event.is_directory:
                    _on_file_created(event.dest_path)

        observer = _start_watchdog_with_retry(cfg.resources_books_dir, BookHandler())
    except ImportError:
        _logger.error("watchdog not installed!")
        observer = None

    # Scan for pre-existing unprocessed books
    _scan_unprocessed()

    # Main loop health check for Watchdog Observer
    try:
        last_observer_check = time.time()
        while not _shutdown.is_set():
            time.sleep(1)

            # Auto-restart Observer if it died (e.g. GDrive disconnected)
            if observer is None or not observer.is_alive():
                now = time.time()
                if now - last_observer_check >= 60:
                    last_observer_check = now
                    _logger.warning("Book watchdog Observer not active — attempting restart...")
                    try:
                        from watchdog.events import FileSystemEventHandler

                        class _RevivedBookHandler(FileSystemEventHandler):
                            def on_created(self, event):
                                if not event.is_directory:
                                    _on_file_created(event.src_path)
                            def on_moved(self, event):
                                if not event.is_directory:
                                    _on_file_created(event.dest_path)

                        observer = _start_watchdog_with_retry(cfg.resources_books_dir, _RevivedBookHandler())
                        if observer:
                            log("book", "Book watchdog auto-restarted after disconnect")
                    except Exception as revive_err:
                        _logger.error(f"Book watchdog revival failed: {revive_err}")
    except KeyboardInterrupt:
        _shutdown.set()
    finally:
        if observer:
            observer.stop()
            observer.join(timeout=5)
        
        # Graceful shutdown: wait for book worker thread to finish
        _logger.info("Waiting for book worker thread to finish...")
        worker.join(timeout=30)
        _logger.info("Book Ingestion Daemon stopped")


if __name__ == "__main__":
    main()
