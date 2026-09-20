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

    # Out-of-band Telegram alert on error if configured
    if level.lower() == "error":
        send_telegram_alert(f"**[{category}]** {message}{src_tag}", level="ERROR")


def send_telegram_alert(message: str, level: str = "ERROR") -> bool:
    """Send an alert message to Telegram if credentials are configured.

    Reads ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID from environment.
    Uses only standard library urllib.request (zero dependencies).
    """
    import json
    import os
    import urllib.request

    bot_token = os.environ.get("ALERT_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("ALERT_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return False

    prefix = "🚨 [Spark 24/7 Alert]" if level.upper() == "ERROR" else "ℹ️ [Spark 24/7 Info]"
    payload = {
        "chat_id": chat_id,
        "text": f"{prefix}\n{message}",
        "parse_mode": "Markdown",
    }
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status == 200
    except Exception as e:
        _logger.warning(f"Failed to send Telegram alert: {e}")
        return False


def update_heartbeat(status: str = "Online", detail: str = "") -> None:
    """Record daemon heartbeat timestamp and state in state_dir."""
    import json
    state_file = cfg.state_dir / "daemon_heartbeat.json"
    data = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "detail": detail,
    }
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


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
