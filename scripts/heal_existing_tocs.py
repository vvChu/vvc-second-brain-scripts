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
from typing import Any

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


def _build_toc_from_md_files(ws: Path, md_dir: Path, toc_path: Path) -> bool:
    """Build chapters list from MD corpus files and save as new _toc.json."""
    _logger.info(f"No _toc_original.json found. Building chapters list from MD corpus files in {md_dir.name}...")
    exclude = {
        "copyright", "cover", "contents", "nav", "title_page",
        "epigraph", "also_by", "about_the_author", "about_the_authors", "index",
    }
    md_files = sorted(list(md_dir.glob("*.md")))
    chapters: list[dict[str, Any]] = []
    ch_idx = 1
    for f in md_files:
        name_lower = f.name.lower()
        if any(pat in name_lower for pat in exclude) or not re.match(r"^\d+_", f.name):
            continue
        h1_title = _extract_h1(f)
        title = h1_title if h1_title else f.stem.split("_", 1)[-1].replace("_", " ")
        ch_data: dict[str, Any] = {
            "chapter_num": ch_idx,
            "title_original": title,
            "title_vi": title,
            "description_vi": None,
            "epub_file": f.name,
        }
        page_match = re.search(r"pages_(\d+)_(\d+)", f.name)
        if page_match:
            ch_data["page_start"] = int(page_match.group(1))
            ch_data["page_end"] = int(page_match.group(2))
        chapters.append(ch_data)
        ch_idx += 1

    if not chapters:
        _logger.warning(f"No valid markdown chapter files found in {md_dir.name} to generate TOC.")
        return False
    clean_title = ws.name.replace("_", " ")
    toc_data = {"book_title_original": clean_title, "book_title_vi": clean_title, "chapters": chapters}
    try:
        toc_path.write_text(json.dumps(toc_data, ensure_ascii=False, indent=2), encoding="utf-8")
        _logger.info(f"SUCCESS: Auto-generated new _toc.json for {ws.name}")
        return True
    except OSError as e:
        _logger.error(f"Failed to save auto-generated TOC to {toc_path.name}: {e}")
        return False


def _ensure_toc_exists(ws: Path, md_dir: Path, toc_path: Path) -> bool:
    """Ensure _toc.json exists, copying from template or building from MD files."""
    if toc_path.exists():
        return True
    _logger.info(f"Workspace {ws.name} does not have _toc.json. Attempting to auto-generate...")
    toc_original_path = md_dir / "_toc_original.json"
    if toc_original_path.exists():
        try:
            import shutil
            shutil.copy(str(toc_original_path), str(toc_path))
            _logger.info(f"Copied original TOC template to workspace: {ws.name}/_toc.json")
            return True
        except OSError as e:
            _logger.error(f"Failed to copy original TOC template: {e}")
            return False
    return _build_toc_from_md_files(ws, md_dir, toc_path)


def _enrich_single_chapter(
    ch: dict[str, Any], idx: int, sorted_chapters: list[dict[str, Any]], md_dir: Path, md_files: list[Path]
) -> None:
    """Align single chapter with original MD file and autocomplete page ranges."""
    chapter_num = ch.get("chapter_num")
    if chapter_num is None:
        return
    current_epub = ch.get("epub_file")
    matched = (
        (md_dir / current_epub)
        if current_epub and (md_dir / current_epub).exists()
        else _match_chapter_file(chapter_num, md_files)
    )
    if matched:
        if ch.get("epub_file") != matched.name:
            ch["epub_file"] = matched.name
            _logger.info(f"  Mapped Chapter {chapter_num} -> {matched.name}")
        if not ch.get("title_original"):
            h1 = _extract_h1(matched)
            if h1:
                ch["title_original"] = h1
    if "page_start" in ch and ch["page_start"] is not None:
        try:
            ch["page_start"] = int(ch["page_start"])
        except (ValueError, TypeError):
            pass
    if ("page_end" not in ch or ch["page_end"] in (None, "")) and idx < len(sorted_chapters) - 1:
        next_start = sorted_chapters[idx + 1].get("page_start")
        try:
            next_val = int(next_start)
            ch["page_end"] = next_val - 1 if next_val > 0 else None
        except (ValueError, TypeError):
            pass


def _save_and_post_process_toc(ws: Path, toc_path: Path, toc_data: dict[str, Any]) -> bool:
    """Save enriched TOC and trigger schema migration, source sync, and context enrichment."""
    if not toc_data.get("book_title_vi") or toc_data["book_title_vi"] == "Không xác định":
        toc_data["book_title_vi"] = ws.name.replace("_", " ")
    try:
        toc_path.write_text(json.dumps(toc_data, ensure_ascii=False, indent=2), encoding="utf-8")
        _logger.info(f"SUCCESS: Upgraded and saved {toc_path.name} in {ws.name}")
    except OSError as e:
        _logger.error(f"Failed to save updated TOC to {toc_path.name}: {e}")
        return False

    try:
        from migrate_toc_schema import migrate_toc
        changed, _ = migrate_toc(toc_path)
        if changed:
            toc_data = json.loads(toc_path.read_text(encoding="utf-8"))
    except ImportError:
        pass

    try:
        _sync_source_note(ws.name, toc_data)
    except Exception as err:
        _logger.warning(f"Source Note sync failed for {ws.name}: {err}")

    try:
        from pipeline.map_reduce import enrich_book_context
        enrich_book_context(ws)
    except Exception as err:
        _logger.warning(f"Failed to auto-enrich _context.txt for {ws.name}: {err}")
    return True


def _process_single_workspace(ws: Path) -> bool:
    """Scan and upgrade a single fleeting workspace TOC."""
    toc_path = ws / "_toc.json"
    md_dir = _find_md_dir(ws.name)
    if not md_dir:
        _logger.warning(f"No extracted MD corpus directory found in resources for book name: {ws.name}")
        return False
    if not _ensure_toc_exists(ws, md_dir, toc_path):
        return False

    try:
        toc_data = json.loads(toc_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _logger.error(f"Failed to read {toc_path.name} in {ws.name}: {e}")
        return False

    chapters = toc_data.get("chapters", [])
    if not chapters:
        _logger.warning(f"No chapters found in {toc_path.name} for {ws.name}")
        return False

    md_files = list(md_dir.glob("*.md"))
    sorted_chapters = sorted(chapters, key=lambda x: (x.get("chapter_num") if x.get("chapter_num") is not None else 0))
    for idx, ch in enumerate(sorted_chapters):
        _enrich_single_chapter(ch, idx, sorted_chapters, md_dir, md_files)

    toc_data["chapters"] = sorted_chapters
    return _save_and_post_process_toc(ws, toc_path, toc_data)


def heal_all_tocs() -> None:
    """Scan and upgrade all existing _toc.json files in fleeting workspaces."""
    _logger.info("Starting TOC healing utility...")
    fleeting_dir = cfg.fleeting_dir
    if not fleeting_dir.exists():
        _logger.error(f"Fleeting directory not found: {fleeting_dir}")
        return

    workspaces = [d for d in fleeting_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    _logger.info(f"Found {len(workspaces)} fleeting workspaces to scan.")
    healed_count = sum(1 for ws in workspaces if _process_single_workspace(ws))
    _logger.info(f"TOC Healing utility complete. Successfully upgraded {healed_count} workspaces.")


if __name__ == "__main__":
    heal_all_tocs()
