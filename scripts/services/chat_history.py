"""VvC Second Brain — Chat History Manager.

Handles auto-archiving of Command.md when it gets too large.
"""

import logging
import re
from datetime import datetime

from core.config import cfg
from core.log import log

_logger = logging.getLogger("vvc.history")

MAX_COMMAND_LEN = 100_000
INPUT_MARKER = "## 📥 Input"
HISTORY_MARKER = "## 🕰️ Lịch sử tương tác"
QUERY_PATTERN = re.compile(
    r"@AI:\s*(.*?)\s*---",
    re.DOTALL | re.IGNORECASE,
)

def extract_sections(content: str) -> tuple[str, str, str]:
    """Extract before_inbox, inbox, after_inbox (history)."""
    match = re.search(fr"({INPUT_MARKER}\s*\n)(.*?)({HISTORY_MARKER}\s*\n)", content, re.DOTALL | re.IGNORECASE)
    if not match:
        return "", "", ""
    before = content[:match.start(1)]
    inbox = match.group(2).strip()
    after = content[match.end(3):]
    return before, inbox, after


def auto_archive_command(content: str) -> str:
    """Archive old command content from the bottom if file exceeds MAX_COMMAND_LEN.
    Keeps the top 5 newest interactions to preserve context.
    """
    if len(content) < MAX_COMMAND_LEN:
        return content
        
    before, inbox, after = extract_sections(content)
    if not after:
        return content
        
    matches = list(QUERY_PATTERN.finditer(after))
    if len(matches) <= 5:
        return content
        
    # Split at the 5th query from top (since newest is at top)
    split_match = matches[5]
    split_idx = split_match.start()
    
    keep_text = after[:split_idx].strip()
    archive_text = after[split_idx:].strip()
    
    if archive_text:
        log_dir = cfg.vault_root / "00 - Maps of Content" / "_command_archive"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_file = log_dir / f"Command_Archive_{timestamp}.md"
        
        try:
            archive_file.write_text(archive_text, encoding="utf-8")
            _logger.info(f"Archived {len(archive_text)} chars to {archive_file.name}")
            log("lifecycle", f"Auto-archived Command.md: {len(archive_text)} chars")
        except OSError as e:
            _logger.error(f"Failed to archive Command.md: {e}")
            return content  # Abort archiving if file save fails
            
    return before + INPUT_MARKER + "\n\n" + inbox + "\n\n" + HISTORY_MARKER + "\n\n" + keep_text + "\n"
