"""VvC Second Brain — Utility: Heal & Upgrade Existing TOCs to v7.9 Standard.

Scans all fleeting workspaces, loads existing _toc.json files, maps them to original MD book corpora,
injects `epub_file` and `title_original` (from H1), autocompletes `page_end`, and triggers Reverse Metadata Sync.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg
from pipeline.book_assets import find_book_md_dir as _find_md_dir
from pipeline.ground_truth import _match_chapter_file
from pipeline.ocr import _sync_source_note

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [heal-toc] %(levelname)s: %(message)s",
    stream=sys.stdout
)
_logger = logging.getLogger("vvc.heal_toc")


def _extract_h1(file_path: Path) -> str:
    """Extract first H1 heading from a markdown file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        # Match lines starting with '# '
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            # Clean up potential wiki links inside H1
            h1 = match.group(1).strip()
            h1 = re.sub(r'\[\[[^|\]]+\|([^\]]+)\]\]', r'\1', h1)
            h1 = re.sub(r'\[\[([^\]]+)\]\]', r'\1', h1)
            return h1
    except Exception:
        pass
    return ""


def heal_all_tocs() -> None:
    """Scan and upgrade all existing _toc.json files in fleeting workspaces."""
    _logger.info("Starting TOC healing utility...")
    
    fleeting_dir = cfg.fleeting_dir
    if not fleeting_dir.exists():
        _logger.error(f"Fleeting directory not found: {fleeting_dir}")
        return

    workspaces = [d for d in fleeting_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    _logger.info(f"Found {len(workspaces)} fleeting workspaces to scan.")

    healed_count = 0

    for ws in workspaces:
        toc_path = ws / "_toc.json"
        
        # 1. Find corresponding MD corpus directory
        md_dir = _find_md_dir(ws.name)
        if not md_dir:
            _logger.warning(f"No extracted MD corpus directory found in resources for book name: {ws.name}")
            continue

        # 2. If _toc.json does not exist, attempt to auto-generate it
        if not toc_path.exists():
            _logger.info(f"Workspace {ws.name} does not have _toc.json. Attempting to auto-generate...")
            
            toc_original_path = md_dir / "_toc_original.json"
            if toc_original_path.exists():
                try:
                    import shutil
                    shutil.copy(str(toc_original_path), str(toc_path))
                    _logger.info(f"Copied original TOC template to workspace: {ws.name}/_toc.json")
                except OSError as e:
                    _logger.error(f"Failed to copy original TOC template: {e}")
                    continue
            else:
                _logger.info(f"No _toc_original.json found. Building chapters list from MD corpus files in {md_dir.name}...")
                exclude_patterns = ["copyright", "cover", "contents", "nav", "title_page", "epigraph", "also_by", "about_the_author", "about_the_authors", "index"]
                md_files = sorted(list(md_dir.glob("*.md")))
                
                chapters = []
                ch_idx = 1
                for f in md_files:
                    name_lower = f.name.lower()
                    if any(pat in name_lower for pat in exclude_patterns):
                        continue
                    if not re.match(r"^\d+_", f.name):
                        continue
                        
                    h1_title = _extract_h1(f)
                    title = h1_title if h1_title else f.stem.split("_", 1)[-1].replace("_", " ")
                    
                    ch_data = {
                        "chapter_num": ch_idx,
                        "title_original": title,
                        "title_vi": title,
                        "description_vi": None,
                        "epub_file": f.name
                    }
                    
                    # Try to extract page ranges from PDF naming (e.g. "01_pages_1_15.md")
                    page_match = re.search(r"pages_(\d+)_(\d+)", f.name)
                    if page_match:
                        ch_data["page_start"] = int(page_match.group(1))
                        ch_data["page_end"] = int(page_match.group(2))
                    
                    chapters.append(ch_data)
                    ch_idx += 1
                
                if chapters:
                    clean_title = ws.name.replace("_", " ")
                    toc_data = {
                        "book_title_original": clean_title,
                        "book_title_vi": clean_title,
                        "chapters": chapters
                    }
                    try:
                        with open(toc_path, "w", encoding="utf-8") as f:
                            json.dump(toc_data, f, ensure_ascii=False, indent=2)
                        _logger.info(f"SUCCESS: Auto-generated new _toc.json for {ws.name}")
                    except OSError as e:
                        _logger.error(f"Failed to save auto-generated TOC to {toc_path.name}: {e}")
                        continue
                else:
                    _logger.warning(f"No valid markdown chapter files found in {md_dir.name} to generate TOC.")
                    continue

        _logger.info(f"--- Processing workspace: {ws.name} ---")
        
        # 3. Load existing TOC
        try:
            with open(toc_path, "r", encoding="utf-8") as f:
                toc_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            _logger.error(f"Failed to read {toc_path.name} in {ws.name}: {e}")
            continue

        chapters = toc_data.get("chapters", [])
        if not chapters:
            _logger.warning(f"No chapters found in {toc_path.name} for {ws.name}")
            continue

        _logger.info(f"Found matching MD corpus: {md_dir.name}")

        md_files = list(md_dir.glob("*.md"))
        
        # 3. Align each chapter and enrich fields
        sorted_chapters = sorted(chapters, key=lambda x: (x.get("chapter_num") if x.get("chapter_num") is not None else 0))

        for idx, ch in enumerate(sorted_chapters):
            chapter_num = ch.get("chapter_num")
            if chapter_num is None:
                continue

            # Check if epub_file is already set and correct, if not, resolve it
            current_epub_file = ch.get("epub_file")
            matched_file = None
            
            if current_epub_file:
                # Verify existing file exists
                test_path = md_dir / current_epub_file
                if test_path.exists():
                    matched_file = test_path
            
            if not matched_file:
                # Run v7.8/v7.9 fuzzy match logic
                matched_file = _match_chapter_file(chapter_num, md_files)
                
            if matched_file:
                # Update epub_file
                if ch.get("epub_file") != matched_file.name:
                    ch["epub_file"] = matched_file.name
                    _logger.info(f"  Mapped Chapter {chapter_num} -> {matched_file.name}")

                # Update title_original
                if not ch.get("title_original"):
                    h1_title = _extract_h1(matched_file)
                    if h1_title:
                        ch["title_original"] = h1_title
                        _logger.info(f"  Extracted original title for Ch {chapter_num}: '{h1_title}'")
            else:
                _logger.warning(f"  Could not map Chapter {chapter_num} to any file in {md_dir.name}")

            # 4. Clean up page_start type
            if "page_start" in ch and ch["page_start"] is not None:
                try:
                    ch_start = int(ch["page_start"])
                    if ch["page_start"] != ch_start:
                        ch["page_start"] = ch_start
                except (ValueError, TypeError):
                    pass

            # 5. Autocomplete page_end based on next chapter's page_start
            if "page_end" not in ch or ch["page_end"] is None or ch["page_end"] == "":
                if idx < len(sorted_chapters) - 1:
                    next_ch = sorted_chapters[idx + 1]
                    next_start = next_ch.get("page_start")
                    try:
                        next_start_int = int(next_start)
                        ch["page_end"] = next_start_int - 1 if next_start_int > 0 else None
                        _logger.info(f"  Auto-assigned Ch {chapter_num} page_end: {ch['page_end']}")
                    except (ValueError, TypeError):
                        pass

        # 6. Save back TOC if updated
        toc_data["chapters"] = sorted_chapters
        
        # Set book_title_vi if missing or generic
        if not toc_data.get("book_title_vi") or toc_data["book_title_vi"] == "Không xác định":
            # Generate a nice title from folder name
            clean_title = ws.name.replace("_", " ")
            # Try to keep original if it exists as title
            toc_data["book_title_vi"] = clean_title

        try:
            with open(toc_path, "w", encoding="utf-8") as f:
                json.dump(toc_data, f, ensure_ascii=False, indent=2)
            healed_count += 1
            _logger.info(f"SUCCESS: Upgraded and saved {toc_path.name} in {ws.name}")
            
            # 7a. Normalize to canonical schema v8.0
            try:
                from migrate_toc_schema import migrate_toc
                changed, changes = migrate_toc(toc_path)
                if changed:
                    _logger.info(f"  Schema normalized: {len(changes)} fixes applied")
                    # Reload normalized data for sync
                    with open(toc_path, "r", encoding="utf-8") as f:
                        toc_data = json.load(f)
            except ImportError:
                pass  # migrate_toc_schema not available — skip normalization

            # 7b. Reverse Sync back to Source Note
            try:
                _sync_source_note(ws.name, toc_data)
            except Exception as sync_err:
                _logger.warning(f"Source Note sync failed for {ws.name}: {sync_err}")
                
            # 7c. Auto-enrich Macro Context Block inside _context.txt
            try:
                from pipeline.map_reduce import enrich_book_context
                enrich_book_context(ws)
            except Exception as enrich_err:
                _logger.warning(f"Failed to auto-enrich _context.txt for {ws.name} (non-critical): {enrich_err}")
                
        except OSError as e:
            _logger.error(f"Failed to save updated TOC to {toc_path.name}: {e}")

    _logger.info(f"TOC Healing utility complete. Successfully upgraded {healed_count} workspaces.")


if __name__ == "__main__":
    heal_all_tocs()
