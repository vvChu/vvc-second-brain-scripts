"""VvC Second Brain — Vault Sync Daemon (v7.0).

Bidirectional sync: D:\\VvC_Notes ↔ G:\\My Drive\\VvC_Vault.
- Photo Inbox: MOVES images from GDrive → Local (one-way)
- Priority files: syncs Command.md and Brain_Dump.md every 30s
- General sync: bidirectional every 60s

Usage:
    pythonw.exe vault_sync.py   # Headless (production)
    python vault_sync.py        # Debug
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import sys
import threading
import time
import concurrent.futures
from pathlib import Path

# Headless hardening
if sys.executable and "pythonw" in sys.executable.lower():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sync] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(_SCRIPT_DIR / "vault_sync.log", encoding="utf-8")],
)
_logger = logging.getLogger("vvc.sync")

# --- Configuration ---
GDRIVE_ROOT = Path(r"G:\My Drive\VvC_Vault")
LOCAL_ROOT = cfg.vault_root

POLL_INTERVAL = 30       # seconds between sync cycles
FULL_SYNC_INTERVAL = 60  # seconds between full bidirectional sync

SYNC_FOLDERS = [
    "00 - Maps of Content",
    "04 - Permanent",
    "99 - Archive",
    "templates",
]

PRIORITY_FILES = [
    "00 - Maps of Content/Command.md",
    "05 - Fleeting/Brain_Dump.md",
]

# Files/dirs to NEVER sync
EXCLUDE_PATTERNS = {".obsidian", "scripts", ".venv", "__pycache__", ".git", ".gemini"}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

MANIFEST_PATH = _SCRIPT_DIR / "_sync_manifest.json"

_shutdown = threading.Event()


# --- Manifest (state tracking for delete propagation) ---

def _load_manifest() -> dict:
    """Load sync manifest for tracking file states."""
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"files": {}, "dirs": []}


def _save_manifest(manifest: dict) -> None:
    """Save sync manifest."""
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except OSError as e:
        _logger.warning(f"Manifest save failed: {e}")

def _safe_file_op(operation: str, src: str, dst: str, timeout: float = 10.0) -> bool:
    """Run a file operation (copy2 or move) with a timeout to prevent hanging."""
    def _do_op():
        if operation == "copy":
            shutil.copy2(src, dst)
        elif operation == "move":
            shutil.move(src, dst)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_do_op)
        future.result(timeout=timeout)
        executor.shutdown(wait=False, cancel_futures=True)
        return True
    except concurrent.futures.TimeoutError:
        _logger.error(f"Timeout ({timeout}s) during {operation} from {src} to {dst}")
        executor.shutdown(wait=False, cancel_futures=True)
        return False
    except OSError:
        # Ignore normal IO errors, we just don't want it to hang
        executor.shutdown(wait=False, cancel_futures=True)
        return False
    except Exception as e:
        _logger.error(f"Error during {operation} from {src} to {dst}: {e}")
        executor.shutdown(wait=False, cancel_futures=True)
        return False


# --- Photo Inbox (one-way: GDrive → Local) ---

def _process_photo_inbox() -> None:
    """Move new photos from GDrive Fleeting to local Fleeting."""
    gdrive_fleeting = GDRIVE_ROOT / "05 - Fleeting"
    if not gdrive_fleeting.exists():
        return

    for book_dir in gdrive_fleeting.iterdir():
        if not book_dir.is_dir():
            continue

        local_book = cfg.fleeting_dir / book_dir.name
        local_book.mkdir(parents=True, exist_ok=True)

        for img in book_dir.iterdir():
            if img.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if img.name.startswith("_"):
                continue  # Skip _toc, _context

            dest = local_book / img.name
            if dest.exists():
                continue

            if _safe_file_op("move", str(img), str(dest)):
                _logger.info(f"Photo inbox: {img.name} → {dest.parent.name}/")
            else:
                _logger.warning(f"Photo move failed or timed out: {img.name}")


# --- Priority File Sync (fast, bidirectional) ---

def _sync_priority_files() -> None:
    """Quick sync for Command.md and Brain_Dump.md."""
    for rel_path in PRIORITY_FILES:
        local = LOCAL_ROOT / rel_path
        remote = GDRIVE_ROOT / rel_path

        if not local.exists() and not remote.exists():
            continue

        _sync_file(local, remote)


# --- General Sync (bidirectional) ---

def _full_sync() -> None:
    """Full bidirectional sync for configured folders."""
    manifest = _load_manifest()
    tracked_files = set(manifest.get("files", []))
    tracked_dirs  = set(manifest.get("dirs",  []))
    new_tracked_files: set = set()
    new_tracked_dirs:  set = set()

    for folder_name in SYNC_FOLDERS:
        local_dir  = LOCAL_ROOT  / folder_name
        remote_dir = GDRIVE_ROOT / folder_name

        if not local_dir.exists() and not remote_dir.exists():
            continue

        # --- Subdirectory-level delete propagation ---
        # Collect all immediate subdirs on both sides
        local_subdirs  = {d.name for d in local_dir.iterdir()  if d.is_dir()} if local_dir.exists()  else set()
        remote_subdirs = {d.name for d in remote_dir.iterdir() if d.is_dir()} if remote_dir.exists() else set()
        all_subdirs    = local_subdirs | remote_subdirs

        for sub in all_subdirs:
            sub_rel = f"{folder_name}/{sub}"
            sub_local  = local_dir  / sub
            sub_remote = remote_dir / sub

            if sub_rel in tracked_dirs:
                # Was tracked before — check for deletions
                if not sub_local.exists() and sub_remote.exists():
                    # Deleted locally → delete remote
                    try:
                        shutil.rmtree(sub_remote)
                        _logger.info(f"Dir delete propagated to remote: {sub_rel}")
                    except OSError as e:
                        _logger.warning(f"Failed to delete remote dir {sub_rel}: {e}")
                    continue
                elif not sub_remote.exists() and sub_local.exists():
                    # Deleted remotely → delete local
                    try:
                        shutil.rmtree(sub_local)
                        _logger.info(f"Dir delete propagated to local: {sub_rel}")
                    except OSError as e:
                        _logger.warning(f"Failed to delete local dir {sub_rel}: {e}")
                    continue

            # Not deleted — track it for next cycle
            if sub_local.exists() or sub_remote.exists():
                new_tracked_dirs.add(sub_rel)

        # --- File-level sync ---
        _sync_directory(local_dir, remote_dir, tracked_files, new_tracked_files)

    _save_manifest({"files": list(new_tracked_files), "dirs": list(new_tracked_dirs)})


def _sync_directory(local_dir: Path, remote_dir: Path, tracked_files: set, new_tracked_files: set) -> None:
    """Recursively sync two directories bidirectionally."""
    local_exists_dir  = local_dir.exists()
    remote_exists_dir = remote_dir.exists()

    if not local_exists_dir and not remote_exists_dir:
        return

    # Only create remote if local exists (not the other way round — prevents resurrection)
    if local_exists_dir:
        remote_dir.mkdir(parents=True, exist_ok=True)
    elif remote_exists_dir:
        # Remote exists but local doesn't — do NOT recreate local automatically.
        # The delete propagation in _full_sync already handles this case.
        return

    # Collect all files from both sides
    local_files = set()
    remote_files = set()

    for f in _walk_files(local_dir):
        local_files.add(f.relative_to(local_dir))

    for f in _walk_files(remote_dir):
        remote_files.add(f.relative_to(remote_dir))

    all_files = local_files | remote_files

    for rel in all_files:
        local = local_dir / rel
        remote = remote_dir / rel
        rel_str = str(local.relative_to(LOCAL_ROOT).as_posix())

        local_exists = rel in local_files
        remote_exists = rel in remote_files

        if rel_str in tracked_files:
            if not local_exists and not remote_exists:
                # Deleted from both? Do nothing
                continue
            elif not local_exists and remote_exists:
                # Deleted locally. Propagate delete to remote!
                try:
                    if remote.is_file():
                        remote.unlink()
                        _logger.info(f"Delete propagated to remote: {rel_str}")
                except OSError as e:
                    _logger.warning(f"Failed to delete remote {rel_str}: {e}")
                continue
            elif not remote_exists and local_exists:
                # Deleted remotely. Propagate delete to local!
                try:
                    if local.is_file():
                        local.unlink()
                        _logger.info(f"Delete propagated to local: {rel_str}")
                except OSError as e:
                    _logger.warning(f"Failed to delete local {rel_str}: {e}")
                continue

        # If it wasn't deleted (or we just didn't track it), sync it
        success = _sync_file(local, remote, local_exists, remote_exists)
        
        if success:
            new_tracked_files.add(rel_str)


def _sync_file(local: Path, remote: Path, local_exists: bool = None, remote_exists: bool = None) -> bool:
    """Sync a single file (newer wins). Returns True if the file successfully exists on both sides."""
    if local_exists is None:
        local_exists = local.exists()
    if remote_exists is None:
        remote_exists = remote.exists()

    if local_exists and not remote_exists:
        # Local → Remote
        remote.parent.mkdir(parents=True, exist_ok=True)
        return _safe_file_op("copy", str(local), str(remote))
    elif remote_exists and not local_exists:
        # Remote → Local
        local.parent.mkdir(parents=True, exist_ok=True)
        return _safe_file_op("copy", str(remote), str(local))
    elif local_exists and remote_exists:
        # Both exist: newer wins
        local_mtime = local.stat().st_mtime
        remote_mtime = remote.stat().st_mtime

        if local_mtime > remote_mtime + 2:
            _safe_file_op("copy", str(local), str(remote))
        elif remote_mtime > local_mtime + 2:
            _safe_file_op("copy", str(remote), str(local))
        return True
        
    return False


def _walk_files(directory: Path):
    """Walk directory, yielding files (excluding patterns)."""
    if not directory.exists():
        return
    for item in directory.rglob("*"):
        if item.is_file():
            # Check exclusions
            parts = item.relative_to(directory).parts
            if any(p in EXCLUDE_PATTERNS for p in parts):
                continue
            yield item


# --- Main Loop ---

def main() -> None:
    """Start the sync daemon."""
    def _signal_handler(sig, frame):
        _shutdown.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    _logger.info("=" * 40)
    _logger.info("Vault Sync Daemon v7.0 started")
    _logger.info(f"Local: {LOCAL_ROOT}")
    _logger.info(f"GDrive: {GDRIVE_ROOT}")

    if not GDRIVE_ROOT.exists():
        _logger.warning(f"GDrive path not found: {GDRIVE_ROOT}")
        _logger.info("Waiting for GDrive connection...")

    last_full_sync = 0.0
    gdrive_was_offline = not GDRIVE_ROOT.exists()

    while not _shutdown.is_set():
        now = time.time()

        if GDRIVE_ROOT.exists():
            if gdrive_was_offline:
                _logger.info("GDrive connection recovered!")
                gdrive_was_offline = False

            # Priority files (every cycle)
            try:
                _sync_priority_files()
            except Exception as e:
                _logger.error(f"Priority sync error: {e}")

            # Photo inbox (every cycle)
            try:
                _process_photo_inbox()
            except Exception as e:
                _logger.error(f"Photo inbox error: {e}")

            # Full sync (periodic)
            if now - last_full_sync >= FULL_SYNC_INTERVAL:
                try:
                    _full_sync()
                    last_full_sync = now
                except Exception as e:
                    _logger.error(f"Full sync error: {e}")
        else:
            if not gdrive_was_offline:
                _logger.warning("GDrive went offline")
                gdrive_was_offline = True

        time.sleep(POLL_INTERVAL)

    _logger.info("Vault Sync stopped")


if __name__ == "__main__":
    main()
