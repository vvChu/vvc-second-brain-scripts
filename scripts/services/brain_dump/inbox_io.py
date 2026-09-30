"""VvC Second Brain — Brain Dump: Inbox I/O operations.

Handles reading and writing to the Brain_Dump.md file and inbox queue:
- _find_pending_dump: Find unprocessed brain dump content
- _extract_inbox_sections: Parse ## Inbox sections
- _commit_inbox_changes: Single-write commit of all changes
- _clear_inbox_only: Clear processed text without generating concepts
- harvest_inbox_and_conflicts: Harvest timestamped inbox & conflict dump files
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from core.config import cfg

try:
    from wiki_maintain import rebuild_all as _rebuild_all
except ImportError:
    _rebuild_all = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.dump")

# --- Brain Dump Detection ---

_DUMP_MARKER = "---"
_PROCESSED_MARKER = "<!-- processed -->"


def _extract_inbox_sections(content: str) -> tuple[str, str, str]:
    """Extracts inbox content and splits the file.
    Returns (before_inbox, inbox_content, after_inbox)
    """
    match = re.search(r"(##\s*Inbox[ \t]*\n)(.*?)(?=\n##\s*|\Z)", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return "", "", ""
    
    before = content[:match.start(2)]
    inbox = match.group(2).strip()
    after = content[match.end(2):]
    return before, inbox, after


def _find_pending_dump(content: str) -> str | None:
    """Find unprocessed brain dump content from ## Inbox."""
    _, inbox, _ = _extract_inbox_sections(content)
    if inbox and len(inbox) >= 10:
        return inbox

    # Fallback to legacy marker if ## Inbox is not found
    if _PROCESSED_MARKER in content:
        parts = content.rsplit(_PROCESSED_MARKER, 1)
        remaining = parts[1].strip() if len(parts) > 1 else ""
        if len(remaining) >= 20:
            return remaining

    return None


def _update_inbox_text(inbox: str, dump_text_to_replace: str, new_inbox_content: str) -> str:
    """Filter out replaced lines and append new content to inbox section."""
    replace_lines = {line.strip() for line in dump_text_to_replace.splitlines() if line.strip()}
    remaining_lines = [line for line in inbox.splitlines() if line.strip() not in replace_lines]
    if new_inbox_content.strip():
        remaining_lines.append(new_inbox_content.strip())
    new_inbox = "\n".join(remaining_lines).strip()
    return f"\n{new_inbox}\n" if new_inbox else "\n\n"


def _append_processed_links(after: str, links_to_append: list[str]) -> str:
    """Append generated concept links under ## Processed heading."""
    links_str = "\n".join(links_to_append)
    if not after.startswith("\n"):
        after = "\n" + after
    if "## Processed" in after:
        if not after.endswith("\n"):
            after += "\n"
        return re.sub(r"(##\s*Processed\s*\n)", f"\\1{links_str}\n", after, count=1, flags=re.IGNORECASE)
    return f"{after}\n## Processed\n{links_str}\n"


def _commit_inbox_changes(
    dump_text_to_replace: str,
    new_inbox_content: str,
    links_to_append: list[str],
    rebuild: bool = False,
) -> None:
    """Ghi tất cả thay đổi đối với Brain_Dump.md trong một giao dịch duy nhất (Single-Write Commit)."""
    try:
        current_content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return

    before, inbox, after = _extract_inbox_sections(current_content)
    if before and inbox:
        new_inbox = _update_inbox_text(inbox, dump_text_to_replace, new_inbox_content)
        new_after = _append_processed_links(after, links_to_append)
        new_content = before + new_inbox + new_after
        try:
            cfg.dump_file.write_text(new_content, encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Không thể ghi Brain_Dump.md: {e}")

    if rebuild and _rebuild_all is not None:
        try:
            _rebuild_all()
        except Exception:
            pass

def _clear_inbox_only(dump_text: str) -> None:
    """Clear the processed dump_text from Inbox without generating new concepts (Self-Healing mode)."""
    try:
        current_content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return
    before, inbox, after = _extract_inbox_sections(current_content)
    if before and inbox:
        new_inbox = inbox.replace(dump_text, "").strip()
        if new_inbox:
            new_inbox = "\n" + new_inbox + "\n"
        else:
            new_inbox = "\n\n"
            
        if not after.startswith("\n"):
            after = "\n" + after
        new_content = before + new_inbox + after
        try:
            cfg.dump_file.write_text(new_content, encoding="utf-8")
        except OSError:
            pass


def _archive_file(file_path: Path) -> None:
    """Safely archive a processed inbox or conflict file to 99 - Archive/inbox/."""
    archive_dir = cfg.archive_dir / "inbox"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / file_path.name
    if target.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = archive_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
    try:
        shutil.move(str(file_path), str(target))
        _logger.info(f"Archived {file_path.name} -> {target.relative_to(cfg.vault_root)}")
    except OSError as e:
        _logger.warning(f"Failed to archive {file_path.name}: {e}")


def _extract_inbox_payload(file_path: Path) -> str:
    """Extract pending payload text from an inbox or conflict file."""
    try:
        text = file_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not text:
        return ""
    _, inbox, _ = _extract_inbox_sections(text)
    return inbox if inbox else text


def _find_candidate_files() -> list[Path]:
    """Find all timestamped inbox files and conflict Brain_Dump files deterministically."""
    candidates: list[Path] = []
    inbox_dir = cfg.fleeting_dir / "inbox"
    if inbox_dir.exists():
        candidates.extend(sorted(inbox_dir.glob("*.md"), key=lambda p: p.name))
    if cfg.fleeting_dir.exists():
        for p in sorted(cfg.fleeting_dir.glob("*.md"), key=lambda p: p.name):
            name_lower = p.name.lower()
            if name_lower.startswith("brain_dump (") or "conflict" in name_lower:
                candidates.append(p)
    return candidates


def has_pending_inbox_or_conflicts() -> bool:
    """Quick check if there are pending inbox notes or conflict dump files."""
    return bool(_find_candidate_files())



def _append_harvested_text(harvested_texts: list[str]) -> bool:
    """Append harvested text chunks to Brain_Dump.md ## Inbox section."""
    if not harvested_texts or not cfg.dump_file.exists():
        return False
    try:
        content = cfg.dump_file.read_text(encoding="utf-8")
        before, inbox, after = _extract_inbox_sections(content)
        combined_payload = "\n".join(harvested_texts)
        if before and (inbox or after):
            new_inbox = f"\n{inbox}\n\n{combined_payload}\n" if inbox else f"\n{combined_payload}\n"
            cfg.dump_file.write_text(before + new_inbox + after, encoding="utf-8")
        else:
            cfg.dump_file.write_text(f"{content.rstrip()}\n\n## Inbox\n{combined_payload}\n", encoding="utf-8")
        return True
    except OSError as e:
        _logger.error(f"Failed to append harvested inbox text to Brain_Dump.md: {e}")
        return False


def harvest_inbox_and_conflicts() -> int:
    """Harvest pending text from 05 - Fleeting/inbox and conflict files into Brain_Dump.md."""
    from core.daemon_utils import is_file_stable

    candidates = _find_candidate_files()
    if not candidates:
        return 0

    harvested_texts: list[str] = []
    files_to_archive: list[Path] = []

    for path in candidates:
        if not is_file_stable(path, wait_s=1.0):
            continue
        payload = _extract_inbox_payload(path)
        if payload:
            harvested_texts.append(payload)
        files_to_archive.append(path)

    if not files_to_archive:
        return 0

    if harvested_texts:
        if not _append_harvested_text(harvested_texts):
            return 0

    for path in files_to_archive:
        _archive_file(path)

    _logger.info(f"Harvested {len(files_to_archive)} inbox/conflict files into Brain_Dump.md")
    return len(files_to_archive)

