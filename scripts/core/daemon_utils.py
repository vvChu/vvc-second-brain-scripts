"""VvC Second Brain — Shared Daemon Utilities.

Shared infrastructure for daemon processes (daemon.py, book_ingest.py).
Eliminates code duplication for headless stdio hardening and file stability checks.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

_logger = logging.getLogger("vvc.daemon_utils")


def harden_headless_stdio() -> None:
    """Redirect broken stdout/stderr to devnull for pythonw.exe compatibility.

    Must be called at module-level BEFORE any logging setup or print() calls.
    Also reconfigures valid streams to UTF-8 encoding on Windows.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        is_valid = False
        if stream is not None and hasattr(stream, "write"):
            try:
                stream.write("")
                stream.flush()
                is_valid = True
            except Exception:
                pass
        if not is_valid:
            try:
                setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                setattr(sys, stream_name, None)

    # Set console streams to UTF-8 to prevent cp1252/UnicodeEncodeError on Windows
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def is_file_stable(path: Path, wait_s: float = 1.5, max_retries: int = 5) -> bool:
    """Check if a file has finished being written by comparing size over time.

    Prevents processing images/books still syncing from cloud/junction by
    retrying up to `max_retries` times if the size is changing or zero.

    Args:
        path: File to check.
        wait_s: Seconds to wait between size checks.
        max_retries: Maximum number of retry attempts.

    Returns:
        True if file size is stable and non-zero (write complete).
    """
    for i in range(max_retries):
        try:
            if not path.exists():
                return False
            size1 = path.stat().st_size
            time.sleep(wait_s)
            size2 = path.stat().st_size
            if size1 == size2 and size1 > 0:
                return True
            _logger.info(
                f"File {path.name} is still writing/syncing "
                f"(size: {size1} -> {size2}), retrying check ({i+1}/{max_retries})..."
            )
        except OSError:
            time.sleep(wait_s)
    return False


def restart_existing_daemons() -> None:
    """Terminate existing daemon and book_ingest processes before starting."""
    import subprocess
    my_pid = os.getpid()
    if sys.platform == "win32":
        cmd = (
            f"Get-CimInstance Win32_Process -Filter 'Name like \"%python%\"' | "
            f"Where-Object {{ ($_.CommandLine -like '*daemon.py*' -or $_.CommandLine -like '*book_ingest.py*') -and $_.ProcessId -ne {my_pid} }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        )
        try:
            subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", cmd], capture_output=True, timeout=10)
            time.sleep(1.5)
            _logger.info("Terminated existing daemon processes via --restart")
        except Exception as e:
            _logger.warning(f"Failed to restart existing daemons: {e}")
    else:
        try:
            cmd = f"pgrep -f '(daemon\\.py|book_ingest\\.py)' | grep -v '^{my_pid}$' | xargs -r kill -15 2>/dev/null || true"
            subprocess.run(cmd, shell=True, capture_output=True)
            time.sleep(1.5)
            _logger.info("Terminated existing daemon processes via pgrep/kill")
        except Exception as e:
            _logger.warning(f"Failed to restart existing daemons: {e}")


def start_watchdog_with_retry(path: Path, handler: Any, max_retries: int = 6) -> Any:
    """Start Watchdog Observer with exponential backoff retry.

    Handles the race condition where GDrive Desktop junction is not yet
    mounted when the daemon starts at boot.

    Args:
        path: Directory to watch.
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

    _logger.error("Watchdog failed to start after all retries. Ingestion disabled.")
    return None


def setup_daemon_logging(log_filename: str = "daemon.log", logger_name: str = "vvc.daemon") -> logging.Logger:
    """Configure standard logging handlers for daemon processes."""
    from core.config import cfg
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(cfg.log_dir / log_filename, encoding="utf-8"),
            logging.StreamHandler(sys.stdout) if (sys.stdout and hasattr(sys.stdout, "write")) else logging.NullHandler(),
        ],
    )
    return logging.getLogger(logger_name)


def create_file_watchdog(path: Path, callback: Any, max_retries: int = 6) -> Any:
    """Create and start a Watchdog Observer invoking callback on non-directory file events."""
    try:
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    callback(event.src_path)
            def on_moved(self, event):
                if not event.is_directory:
                    callback(event.dest_path)

        return start_watchdog_with_retry(path, _Handler(), max_retries=max_retries)
    except ImportError:
        _logger.error("watchdog not installed!")
        return None


