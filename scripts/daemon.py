"""VvC Second Brain — Main Daemon (v8.15.13).

Watchdog-based daemon that monitors 05-Fleeting/ for new images
and processes them through the 5-stage pipeline:
  OCR → Ground Truth → Synthesize → Self-Correct → Post-Process

Also monitors Command.md and Brain_Dump.md for interactive queries.

Usage:
    pythonw.exe daemon.py      # Headless (production)
    python daemon.py           # Interactive (debug)
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- Setup Python path ---
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.__version__ import __version__
from core.config import cfg
from core.daemon_utils import (
    create_file_watchdog,
    harden_headless_stdio,
    is_file_stable,
    restart_existing_daemons,
    setup_daemon_logging,
    start_watchdog_with_retry,
)
harden_headless_stdio()

from core.file_lock import CrossProcessFileLock
from core.log import log
from services.daemon_queue import (
    BATCH_COOLDOWN,
    FILE_STABLE_WAIT,
    IMAGE_EXTENSIONS,
    flush_batches,
    in_flight_paths,
    on_file_created,
    pending_batches,
    pending_lock,
    scan_existing_files,
    work_queue,
    worker_loop,
)

_logger = setup_daemon_logging("daemon.log", "vvc.daemon")

# Constants
COMMAND_POLL_INTERVAL = 15
BRAINDUMP_POLL_INTERVAL = 30
FLEETING_POLL_INTERVAL = 30
_FILE_STABLE_WAIT = FILE_STABLE_WAIT
_BATCH_COOLDOWN = BATCH_COOLDOWN

# Re-exported queue state for backward compatibility
_work_queue = work_queue
_pending_batches = pending_batches
_in_flight_paths = in_flight_paths
_pending_lock = pending_lock
_shutdown = threading.Event()

# Re-exported queue functions
_on_file_created = on_file_created
_scan_existing_files = scan_existing_files
_is_file_stable = is_file_stable
_flush_batches = lambda: flush_batches(_shutdown)
_worker_loop = lambda: worker_loop(_shutdown)


# ============================================================
# Command.md & Brain_Dump.md Polling
# ============================================================

@dataclass
class _PollerState:
    """Tracks last-seen mtimes for Command.md and Brain_Dump.md."""
    command_mtime: float = 0.0
    dump_mtime: float = 0.0

_poller_state = _PollerState()
_command_lock = threading.Lock()
_command_in_progress = False
_dump_in_progress = False


def _poll_command() -> None:
    """Poll Command.md for new queries in a non-blocking thread."""
    global _command_in_progress
    with _command_lock:
        if _command_in_progress or not cfg.command_file.exists():
            return
        mtime = cfg.command_file.stat().st_mtime
        if mtime <= _poller_state.command_mtime:
            return
        _poller_state.command_mtime = mtime
        _command_in_progress = True

    def _run_command() -> None:
        global _command_in_progress
        try:
            from services.command import handle_command
            handle_command()
        except ImportError:
            pass
        except Exception as e:
            _logger.error(f"Command handler error: {e}", exc_info=True)
        finally:
            with _command_lock:
                _command_in_progress = False
            try:
                if cfg.command_file.exists():
                    _poller_state.command_mtime = cfg.command_file.stat().st_mtime
            except OSError:
                pass

    try:
        threading.Thread(target=_run_command, daemon=True, name="command-worker").start()
    except Exception:
        with _command_lock:
            _command_in_progress = False
        raise


def _poll_brain_dump() -> None:
    """Poll Brain_Dump.md for new content in a non-blocking thread."""
    global _dump_in_progress
    if _dump_in_progress or not cfg.dump_file.exists():
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
    """Poll fleeting directory recursively for unprocessed files."""
    try:
        if not cfg.fleeting_dir.exists():
            return
        for path in cfg.fleeting_dir.rglob("*"):
            if _shutdown.is_set():
                break
            if not path.is_file():
                continue
            with _pending_lock:
                if path in _in_flight_paths:
                    continue
            _on_file_created(str(path))
    except Exception as e:
        _logger.error(f"Error during fleeting dir poll: {e}", exc_info=True)


def _poll_loop() -> None:
    """Background polling for Command.md, Brain_Dump.md, and Fleeting folder."""
    last_cmd, last_dump, last_fleeting, last_hb = 0.0, 0.0, 0.0, 0.0
    while not _shutdown.is_set():
        now = time.time()
        if now - last_hb >= 60.0:
            from core.log import update_heartbeat
            update_heartbeat("Online", detail="Polling loop healthy")
            last_hb = now
        if now - last_cmd >= COMMAND_POLL_INTERVAL:
            _poll_command()
            last_cmd = now
        if now - last_dump >= BRAINDUMP_POLL_INTERVAL:
            _poll_brain_dump()
            last_dump = now
        if now - last_fleeting >= FLEETING_POLL_INTERVAL:
            _poll_fleeting_dir()
            last_fleeting = now
        time.sleep(3)


# ============================================================
# Single-Instance Lock & Lifecycle
# ============================================================

_daemon_lock: CrossProcessFileLock | None = None


def _acquire_daemon_lock() -> bool:
    """Acquire kernel-level single-instance lock to prevent duplicate daemons."""
    global _daemon_lock
    lock_file = cfg.state_dir / ".daemon.lock"
    _daemon_lock = CrossProcessFileLock(lock_file, timeout=0.2)
    if not _daemon_lock.acquire():
        _daemon_lock = None
        return False
    return True


def _release_daemon_lock() -> None:
    """Release kernel-level single-instance lock on shutdown."""
    global _daemon_lock
    if _daemon_lock is not None:
        try:
            _daemon_lock.release()
        except Exception:
            pass
        _daemon_lock = None


def _start_watchdog_with_retry(path: Path, handler: Any, max_retries: int = 6) -> Any:
    """Delegate to shared daemon utility."""
    return start_watchdog_with_retry(path, handler, max_retries=max_retries)


def _start_daemon_threads() -> tuple[threading.Thread, threading.Thread, threading.Thread, threading.Thread]:
    """Start worker, flusher, poller, and startup-scanner threads."""
    worker = threading.Thread(target=lambda: worker_loop(_shutdown), daemon=False, name="worker")
    worker.start()
    flusher = threading.Thread(target=lambda: flush_batches(_shutdown), daemon=True, name="flusher")
    flusher.start()
    poller = threading.Thread(target=_poll_loop, daemon=False, name="poller")
    poller.start()
    scanner = threading.Thread(target=lambda: _scan_existing_files(_shutdown), daemon=True, name="startup-scanner")
    scanner.start()
    return worker, flusher, poller, scanner


def _revive_watchdog_if_dead(observer: Any, last_check: float) -> tuple[Any, float]:
    """Revive Watchdog Observer if it disconnected mid-session."""
    now = time.time()
    if observer is not None and observer.is_alive():
        return observer, last_check
    if now - last_check < 60:
        return observer, last_check

    _logger.warning("Watchdog Observer not active — attempting restart...")
    new_obs = create_file_watchdog(cfg.fleeting_dir, _on_file_created)
    if new_obs:
        log("lifecycle", "Watchdog auto-restarted after disconnect")
        return new_obs, now
    return observer, now


def _register_signal_handlers(observer: Any) -> None:
    """Register SIGINT and SIGTERM handlers."""
    def _signal_handler(sig, frame):
        _logger.info("Shutdown signal received")
        _shutdown.set()
        if observer:
            observer.stop()

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception as sig_err:
        _logger.warning(f"Failed to register signal handlers (normal in headless mode): {sig_err}")


def _graceful_shutdown(observer: Any, worker: threading.Thread, poller: threading.Thread) -> None:
    """Wait for worker and poller threads to exit gracefully."""
    if observer:
        observer.stop()
        observer.join(timeout=5)
    _logger.info("Waiting for worker thread to finish current task...")
    worker.join(timeout=30)
    poller.join(timeout=5)
    if worker.is_alive():
        _logger.warning("Worker thread did not finish in time — forcing exit")
    _release_daemon_lock()
    log("lifecycle", f"Daemon v{__version__} stopped")
    _logger.info("Daemon stopped")


def main(argv: list[str] | None = None) -> None:
    """Start the daemon."""
    import argparse
    parser = argparse.ArgumentParser(description="VvC Second Brain Daemon")
    parser.add_argument("--restart", action="store_true", help="Restart existing daemons before running")
    args = parser.parse_args(argv)

    if args.restart:
        restart_existing_daemons()

    if not _acquire_daemon_lock():
        _logger.warning("Another daemon instance is already running")
        return

    log("lifecycle", f"Daemon v{__version__} started")
    _logger.info("=" * 50)
    _logger.info(f"VvC Second Brain — Daemon v{__version__} (Batching + Stability Guard)")
    _logger.info(f"Vault: {cfg.vault_root} | Backend: {cfg.backend} | Fallback: {cfg.fallback}")
    _logger.info("=" * 50)

    global _poller_state
    _poller_state = _PollerState()

    worker, flusher, poller, scanner = _start_daemon_threads()
    observer = create_file_watchdog(cfg.fleeting_dir, _on_file_created)
    _register_signal_handlers(observer)

    try:
        last_observer_check = time.time()
        while not _shutdown.is_set():
            time.sleep(1)
            observer, last_observer_check = _revive_watchdog_if_dead(observer, last_observer_check)
    except KeyboardInterrupt:
        _shutdown.set()
    finally:
        _graceful_shutdown(observer, worker, poller)


if __name__ == "__main__":
    main()
