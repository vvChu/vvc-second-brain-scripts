"""VvC Second Brain — Structured Event Logger (v7.0).

Append-only logger that writes structured events to log.md.
Thread-safe via Lock. Supports log rotation (30-day max).

Usage:
    from core.log import log
    log("ingest", "Created concept: foo.md", source="bar.jpg")
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from core.config import cfg

_lock = threading.Lock()
_logger = logging.getLogger("vvc")


def log(
    category: str,
    message: str,
    *,
    source: str = "",
    level: str = "info",
) -> None:
    """Append a structured event to log.md.

    Args:
        category: Event category (ingest, synth, gt, error, lifecycle, etc.)
        message: Human-readable event description.
        source: Optional source file/image name.
        level: Log level for Python logger (info, warning, error).
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    src_tag = f" | src: {source}" if source else ""
    entry = f"- [{now}] **{category}** | {message}{src_tag}\n"

    with _lock:
        try:
            with open(cfg.log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError as e:
            _logger.error(f"Failed to write log: {e}")

    # Also emit to Python logger
    getattr(_logger, level, _logger.info)(f"[{category}] {message}")


def rotate_log(max_age_days: int = 30) -> None:
    """Archive log entries older than max_age_days.

    Moves old entries to log_archive_YYYY-MM.md in vault root.
    """
    log_path = cfg.log_file
    if not log_path.exists():
        return

    cutoff = datetime.now() - timedelta(days=max_age_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    keep_lines: list[str] = []
    archive_lines: list[str] = []

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            # Parse date from "- [YYYY-MM-DD HH:MM]"
            if line.startswith("- [") and len(line) > 14:
                date_part = line[3:13]
                if date_part < cutoff_str:
                    archive_lines.append(line)
                    continue
            keep_lines.append(line)

    if not archive_lines:
        return

    # Write archive
    archive_name = f"log_archive_{cutoff.strftime('%Y-%m')}.md"
    archive_path = cfg.vault_root / archive_name
    with open(archive_path, "a", encoding="utf-8") as f:
        f.writelines(archive_lines)

    # Rewrite current log (only recent entries)
    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(keep_lines)

    log("lifecycle", f"Rotated {len(archive_lines)} old entries to {archive_name}")
