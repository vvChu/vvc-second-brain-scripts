"""VvC Second Brain — Brain Dump: Inbox I/O operations.

Handles reading and writing to the Brain_Dump.md file:
- _find_pending_dump: Find unprocessed brain dump content
- _extract_inbox_sections: Parse ## Inbox sections
- _commit_inbox_changes: Single-write commit of all changes
- _clear_inbox_only: Clear processed text without generating concepts
"""

from __future__ import annotations

import logging
import re

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


def _commit_inbox_changes(dump_text_to_replace: str, new_inbox_content: str, links_to_append: list[str]) -> None:
    """Ghi tất cả thay đổi đối với Brain_Dump.md trong một giao dịch duy nhất (Single-Write Commit)."""
    try:
        current_content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return
        
    before, inbox, after = _extract_inbox_sections(current_content)
    if before and inbox:
        # Nâng cấp v8.9: So khớp line-by-line linh hoạt chống lệch khoảng trắng và CRLF (\r\n) trên Windows
        replace_lines = {line.strip() for line in dump_text_to_replace.splitlines() if line.strip()}
        inbox_lines = inbox.splitlines()
        
        remaining_lines = []
        for line in inbox_lines:
            if line.strip() in replace_lines:
                continue
            remaining_lines.append(line)
            
        if new_inbox_content.strip():
            remaining_lines.append(new_inbox_content.strip())
            
        new_inbox = "\n".join(remaining_lines).strip()
        if new_inbox:
            new_inbox = "\n" + new_inbox + "\n"
        else:
            new_inbox = "\n\n"
            
        links_str = "\n".join(links_to_append)
        if not after.startswith("\n"):
            after = "\n" + after
        if "## Processed" in after:
            if not after.endswith("\n"):
                after += "\n"
            after = re.sub(r"(##\s*Processed\s*\n)", f"\\1{links_str}\n", after, count=1, flags=re.IGNORECASE)
        else:
            after += f"\n## Processed\n{links_str}\n"
            
        new_content = before + new_inbox + after
        try:
            cfg.dump_file.write_text(new_content, encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Không thể ghi Brain_Dump.md: {e}")
            
    if _rebuild_all is not None:
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
