"""VvC Second Brain — Cross-Machine Fencing Token Layer (v8.16.0).

Protects against Google Drive Split-Brain when runners on different hosts
(Linux Server Spark vs Windows Client) attempt to run simultaneously.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import sys
import time
from pathlib import Path
from typing import Any

from core.config import cfg

_logger = logging.getLogger("vvc.fencing")

_EPOCH_FILENAME = ".spark_heartbeat_epoch.json"


def get_epoch_path() -> Path:
    """Return path to shared epoch file on vault root (shared via Drive)."""
    return cfg.fleeting_dir.parent / _EPOCH_FILENAME


def get_current_host() -> str:
    """Return normalized current hostname."""
    return socket.gethostname().strip()


def record_active_epoch(role: str = "spark_daemon") -> bool:
    """Record heartbeat epoch timestamp to prevent Split-Brain."""
    epoch_file = get_epoch_path()
    now = time.time()
    data: dict[str, Any] = {
        "host": get_current_host(),
        "platform": sys.platform,
        "pid": os.getpid(),
        "role": role,
        "timestamp": now,
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "status": "active",
    }
    try:
        temp_file = epoch_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_file.replace(epoch_file)
        return True
    except Exception as e:
        _logger.warning(f"Failed to record epoch heartbeat to {epoch_file}: {e}")
        return False


def clear_active_epoch() -> bool:
    """Mark epoch as stopped on graceful daemon shutdown."""
    epoch_file = get_epoch_path()
    if not epoch_file.exists():
        return True
    now = time.time()
    data: dict[str, Any] = {
        "host": get_current_host(),
        "platform": sys.platform,
        "pid": os.getpid(),
        "timestamp": now,
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "status": "stopped",
    }
    try:
        epoch_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        _logger.warning(f"Failed to clear epoch at {epoch_file}: {e}")
        return False


def check_cross_machine_lease(
    max_stale_seconds: float = 120.0,
    force: bool = False,
) -> tuple[bool, str]:
    """Check if another remote host holds an active lease on the vault.

    Returns:
        (allowed, reason_message)
    """
    if force:
        return True, "Force flag specified — overriding any existing lease."

    epoch_file = get_epoch_path()
    if not epoch_file.exists():
        return True, "No existing lease found."

    try:
        content = json.loads(epoch_file.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning(f"Corrupt epoch file ignored: {e}")
        return True, "Epoch file could not be parsed."

    if content.get("status") != "active":
        return True, "Previous lease was cleanly released (stopped)."

    last_ts = float(content.get("timestamp", 0.0))
    age = time.time() - last_ts
    remote_host = content.get("host", "unknown")
    current_host = get_current_host()

    if remote_host == current_host:
        return True, f"Lease is held by this host ({current_host})."

    if age > max_stale_seconds:
        return True, f"Remote lease on {remote_host} expired ({age:.0f}s > {max_stale_seconds}s)."

    msg = (
        f"Active lease held by remote host '{remote_host}' "
        f"(active {age:.1f}s ago). Run cancelled to prevent Google Drive Split-Brain."
    )
    return False, msg


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VvC Cross-Machine Fencing Guard")
    parser.add_argument("--check", action="store_true", help="Check if runner can start safely")
    parser.add_argument("--record", action="store_true", help="Record active heartbeat epoch")
    parser.add_argument("--clear", action="store_true", help="Clear heartbeat epoch")
    parser.add_argument("--force", action="store_true", help="Force takeover lease")
    args = parser.parse_args()

    if args.record:
        success = record_active_epoch()
        sys.exit(0 if success else 1)
    elif args.clear:
        success = clear_active_epoch()
        sys.exit(0 if success else 1)
    else:
        allowed, reason = check_cross_machine_lease(force=args.force)
        print(f"[{'OK' if allowed else 'DENIED'}] {reason}")
        sys.exit(0 if allowed else 2)
