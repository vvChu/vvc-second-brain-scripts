#!/usr/bin/env python3
"""Consolidate God Notes: Trim excessive Evidence Hooks in oversized concept notes.

For each concept note exceeding the Dynamic Size Limit (7.7KB) or having ≥5
Evidence Hooks, this script:
1. Identifies all Evidence Hook blockquotes (lines starting with `> "`)
2. Keeps the first 3 most representative hooks (preserving chronological order)
3. Moves surplus hooks into the Ground Truth section as additional reference quotes
4. Reports size reduction

Usage:
    python consolidate_god_notes.py [--dry-run]
"""

import sys
import re
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
sys.stdout.reconfigure(encoding="utf-8")
logger = logging.getLogger("consolidate")

# --- Config ---
VAULT_ROOT = Path(r"D:\VvC_Notes")
CONCEPTS_DIR = VAULT_ROOT / "04 - Permanent" / "concepts"
MAX_HOOKS = 3           # Keep at most 3 Evidence Hooks
SIZE_THRESHOLD = 7700   # P95 × 1.3 (~7.7KB)
HOOK_THRESHOLD = 5      # Process notes with ≥5 hooks


def _find_hook_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Find contiguous Evidence Hook blocks (blockquote + citation pairs).
    
    Returns list of (start_line_idx, end_line_idx) for each hook block.
    A hook block starts with `> "` and continues until a non-blockquote line.
    """
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('> "') or line.startswith('> \u201c'):
            start = i
            # Consume the entire blockquote block (including citation line)
            while i < len(lines) and (lines[i].strip().startswith(">") or lines[i].strip() == ""):
                if lines[i].strip() == "" and i + 1 < len(lines) and not lines[i + 1].strip().startswith(">"):
                    break
                i += 1
            blocks.append((start, i))
        else:
            i += 1
    return blocks


def _consolidate_note(file_path: Path, dry_run: bool = False) -> dict | None:
    """Process a single note: trim hooks, move surplus to Ground Truth.
    
    Returns stats dict or None if no changes needed.
    """
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    
    # Count Evidence Hooks
    hook_blocks = _find_hook_blocks([l.rstrip("\n\r") for l in lines])
    hook_count = len(hook_blocks)
    
    if hook_count <= MAX_HOOKS:
        return None  # No trimming needed
    
    # Split: keep first MAX_HOOKS, move rest to Ground Truth
    keep_blocks = hook_blocks[:MAX_HOOKS]
    surplus_blocks = hook_blocks[MAX_HOOKS:]
    
    # Extract surplus text
    surplus_lines: list[str] = []
    for start, end in surplus_blocks:
        surplus_lines.append("\n")
        for j in range(start, end):
            surplus_lines.append(lines[j])
    
    # Find Ground Truth section
    gt_insert_idx = None
    for i, line in enumerate(lines):
        if "## 📖 Bản gốc" in line or "Ground Truth" in line:
            gt_insert_idx = i + 1
            break
    
    # If no GT section, find the `---` separator before References
    if gt_insert_idx is None:
        for i, line in enumerate(lines):
            if line.strip() == "---" and i > 60:  # Skip YAML frontmatter separator
                gt_insert_idx = i
                break
    
    if gt_insert_idx is None:
        logger.warning(f"  Cannot find GT section in {file_path.name}, skipping")
        return None
    
    # Build new content: remove surplus blocks from original position
    # Work backwards to preserve indices
    new_lines = list(lines)
    for start, end in reversed(surplus_blocks):
        # Also remove any trailing blank line
        actual_end = end
        if actual_end < len(new_lines) and new_lines[actual_end].strip() == "":
            actual_end += 1
        del new_lines[start:actual_end]
    
    # Recalculate GT insert position after deletions
    gt_insert_idx_new = None
    for i, line in enumerate(new_lines):
        if "## 📖 Bản gốc" in line or "Ground Truth" in line:
            gt_insert_idx_new = i + 1
            break
    if gt_insert_idx_new is None:
        for i, line in enumerate(new_lines):
            if line.strip() == "---" and i > 60:
                gt_insert_idx_new = i
                break
    
    if gt_insert_idx_new is None:
        logger.warning(f"  Cannot find GT section after trim in {file_path.name}")
        return None
    
    # Insert surplus as additional GT quotes
    insert_header = [f"\n### Trích đoạn bổ sung (consolidated from {len(surplus_blocks)} merged hooks)\n"]
    for sl in surplus_lines:
        insert_header.append(sl)
    
    for j, line in enumerate(insert_header):
        new_lines.insert(gt_insert_idx_new + j, line)
    
    new_content = "".join(new_lines)
    
    old_size = len(content.encode("utf-8"))
    new_size = len(new_content.encode("utf-8"))
    
    stats = {
        "file": file_path.name,
        "old_hooks": hook_count,
        "new_hooks": MAX_HOOKS,
        "moved": hook_count - MAX_HOOKS,
        "old_size_kb": round(old_size / 1024, 1),
        "new_size_kb": round(new_size / 1024, 1),
        "delta_kb": round((old_size - new_size) / 1024, 1),
    }
    
    if not dry_run:
        file_path.write_text(new_content, encoding="utf-8")
        logger.info(f"  ✅ Consolidated: {file_path.name}")
    else:
        logger.info(f"  [DRY-RUN] Would consolidate: {file_path.name}")
    
    return stats


def main() -> None:
    """Main entry point."""
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        logger.info("=== DRY RUN MODE (no files will be modified) ===")
    
    logger.info(f"Scanning {CONCEPTS_DIR} for God Notes...")
    
    candidates: list[Path] = []
    for f in sorted(CONCEPTS_DIR.glob("*.md")):
        if f.name.endswith(".excalidraw.md"):
            continue  # Skip Excalidraw files
        file_size = f.stat().st_size
        if file_size > SIZE_THRESHOLD:
            candidates.append(f)
    
    logger.info(f"Found {len(candidates)} notes exceeding {SIZE_THRESHOLD} bytes")
    
    results: list[dict] = []
    for f in candidates:
        logger.info(f"Processing: {f.name} ({round(f.stat().st_size/1024, 1)} KB)")
        stats = _consolidate_note(f, dry_run=dry_run)
        if stats:
            results.append(stats)
            logger.info(
                f"    Hooks: {stats['old_hooks']} → {stats['new_hooks']} "
                f"(moved {stats['moved']} to GT) | "
                f"Size: {stats['old_size_kb']}KB → {stats['new_size_kb']}KB "
                f"(Δ{stats['delta_kb']}KB)"
            )
        else:
            logger.info(f"    No consolidation needed (≤{MAX_HOOKS} hooks)")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY: {len(results)}/{len(candidates)} notes consolidated")
    if results:
        total_moved = sum(r["moved"] for r in results)
        total_delta = sum(r["delta_kb"] for r in results)
        logger.info(f"  Total hooks moved to GT: {total_moved}")
        logger.info(f"  Total size reduction: {total_delta} KB")


if __name__ == "__main__":
    main()
