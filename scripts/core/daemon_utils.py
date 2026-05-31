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
