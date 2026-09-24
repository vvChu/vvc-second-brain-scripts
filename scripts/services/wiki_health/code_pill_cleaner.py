"""VvC Second Brain — Wiki Health: Code-Pill Wikilink Cleaner.

Scans and cleans markdown files containing backticks wrapped around wikilinks
or embedded wikilinks (e.g. `[[concept]]` or `![[attachment]]`).
Part of Deep Module package services.wiki_health.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from core.config import cfg

_logger = logging.getLogger("vvc.health.code_pill")

_CODE_PILL_LINK_PATTERN = re.compile(r"`(!?\[\[[^`\n]+?\]\])`")


def scan_wikilink_code_pills(fix: bool = False, target_dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    """Scan vault files for code-pill wikilinks (`[[...]]` or `![[...]]`).

    If fix=True, removes backticks around wikilinks in-place.
    Returns a list of findings with file path, count, and matched strings.
    """
    findings = []
    pattern = _CODE_PILL_LINK_PATTERN
    if target_dirs is None:
        target_dirs = [
            cfg.concepts_dir,
            cfg.vault_root / "04 - Permanent" / "topics",
            cfg.sources_dir,
        ]
    for d in target_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            try:
                content = p.read_text(encoding="utf-8")
                matches = pattern.findall(content)
                if matches:
                    findings.append({
                        "file": str(p),
                        "count": len(matches),
                        "matches": matches,
                    })
                    if fix:
                        cleaned = pattern.sub(r"\1", content)
                        p.write_text(cleaned, encoding="utf-8")
                        _logger.info(f"Cleaned {len(matches)} code-pill wikilinks in {p.name}")
            except Exception as e:
                _logger.warning(f"Error scanning code-pills in {p.name}: {e}")
    return findings


__all__ = [
    "_CODE_PILL_LINK_PATTERN",
    "scan_wikilink_code_pills",
]
