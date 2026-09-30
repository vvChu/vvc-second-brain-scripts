"""VvC Second Brain — Migration: Backfill origin tag in Permanent Notes.

Inspects YAML frontmatter of all notes in 04 - Permanent/concepts and
04 - Permanent/topics, determines knowledge provenance (book | ocr | web | command)
via deterministic heuristic, and inserts origin field idempotently.

Usage:
    python scripts/migrations/migrate_origin_tag.py [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

# Add scripts directory to sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from core.config import cfg
from core.frontmatter import parse_frontmatter

_FM_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)


def determine_origin(fm: dict[str, Any], path: Path) -> str:
    """Infer origin category from existing frontmatter metadata and location."""
    source_type = str(fm.get("source_type", "")).lower()
    source_str = str(fm.get("source", "")).lower()
    doc_type = str(fm.get("type", "")).lower()

    if path.parent.name == "topics" or doc_type == "topic" or source_str.startswith("command_"):
        return "command"
    if source_type in ("pdf", "epub"):
        return "book"
    if source_type == "image":
        return "ocr"
    if source_type == "web" or "youtube" in source_str or "transcript" in source_str:
        return "web"
    return "book"


def insert_origin_tag(content: str, origin: str, force: bool = False) -> tuple[str, bool]:
    """Idempotently insert origin field into YAML frontmatter string."""
    match = _FM_PATTERN.match(content)
    if not match:
        return content, False

    fm_text = match.group(0)
    if "origin:" in fm_text and not force:
        return content, False

    if "origin:" in fm_text and force:
        new_fm_text = re.sub(r"\norigin:\s*[^\n]+", f"\norigin: {origin}", fm_text)
    elif re.search(r"\ntype:\s*[^\n]+", fm_text):
        new_fm_text = re.sub(r"(\ntype:\s*[^\n]+)", rf"\1\norigin: {origin}", fm_text, count=1)
    else:
        new_fm_text = re.sub(r"^---\s*\r?\n", f"---\norigin: {origin}\n", fm_text, count=1)

    new_content = new_fm_text + content[match.end():]
    return new_content, True


def collect_target_files() -> list[Path]:
    """Collect all concept and topic markdown files in deterministic order."""
    targets: list[Path] = []
    if cfg.concepts_dir.exists():
        targets.extend(sorted(cfg.concepts_dir.glob("*.md"), key=lambda p: p.name))
    topics_dir = cfg.vault_root / "04 - Permanent" / "topics"
    if topics_dir.exists():
        targets.extend(sorted(topics_dir.glob("*.md"), key=lambda p: p.name))
    return targets


def run_migration(dry_run: bool = False, force: bool = False) -> None:
    """Execute origin tag backfill migration across the permanent knowledge base."""
    files = collect_target_files()
    stats: dict[str, int] = {"total": len(files), "updated": 0, "skipped": 0}
    origin_counts: dict[str, int] = {"book": 0, "ocr": 0, "web": 0, "command": 0}

    print(f"[*] Found {len(files)} notes to inspect (dry_run={dry_run}, force={force})...", flush=True)
    for i, path in enumerate(files):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[-] Failed to read {path.name}: {e}", file=sys.stderr, flush=True)
            continue

        fm = parse_frontmatter(content)
        origin = determine_origin(fm, path)
        new_content, modified = insert_origin_tag(content, origin, force=force)

        if modified:
            stats["updated"] += 1
            origin_counts[origin] = origin_counts.get(origin, 0) + 1
            if not dry_run:
                try:
                    path.write_text(new_content, encoding="utf-8")
                except OSError as e:
                    print(f"[-] Failed to write {path.name}: {e}", file=sys.stderr, flush=True)
        else:
            stats["skipped"] += 1

        if (i + 1) % 500 == 0:
            print(f"    ... inspected {i + 1}/{len(files)} notes", flush=True)

    print("\n[+] Migration Summary:", flush=True)
    print(f"    - Total inspected: {stats['total']}", flush=True)
    print(f"    - Modified:        {stats['updated']}", flush=True)
    print(f"    - Skipped:         {stats['skipped']}", flush=True)
    print("    - Breakdown by origin:", flush=True)
    for k, v in sorted(origin_counts.items()):
        print(f"        * {k:7s}: {v}", flush=True)


def main() -> None:
    """Entry point for migration CLI."""
    parser = argparse.ArgumentParser(description="Backfill origin tag in Permanent Notes")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without modifying files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing origin values")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
