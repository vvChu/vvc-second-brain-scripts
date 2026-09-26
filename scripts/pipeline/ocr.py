"""VvC Second Brain — OCR Extraction Stage (v7.0).

Vision API: auto-orient → OCR → page detection → highlight parsing.
Also handles TOC image extraction.

Usage:
    from pipeline.ocr import extract_ocr
    result = extract_ocr(image_path, book_name="The_Thinking_Machine")
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import NamedTuple

from core.config import cfg
from core.llm import call_vision
from core.prompts.pipeline import (
    OCR_EXTRACT as _OCR_PROMPT,
    TOC_EXTRACT as _TOC_PROMPT,
    TOC_ALIGNMENT as _TOC_ALIGNMENT_PROMPT,
)

_logger = logging.getLogger("vvc.ocr")

# --- OCR Result ---


class OcrResult(NamedTuple):
    """Result from OCR extraction."""
    raw_text: str           # Full OCR text (highlighted + context)
    highlighted: str        # Highlighted/underlined content only
    context: str            # Surrounding context text
    page_number: int | None # Detected page number, or None
    is_toc: bool            # Whether this is a TOC image


# --- Page Detection ---

_PAGE_PATTERN = re.compile(r"PAGE:\s*(\d+)", re.IGNORECASE)
_PAGE_NONE = re.compile(r"PAGE:\s*NONE", re.IGNORECASE)


def _parse_page(text: str) -> int | None:
    """Extract page number from OCR output."""
    match = _PAGE_PATTERN.search(text)
    if match:
        return int(match.group(1))
    first_line = text.strip().split("\n")[0].strip()
    if first_line.isdigit() and 1 <= int(first_line) <= 999:
        return int(first_line)
    return None


# --- Highlight Parsing ---


def _parse_highlights(text: str) -> tuple[str, str]:
    """Split OCR text into highlighted and context portions.

    Returns:
        Tuple of (highlighted, context).
    """
    text = _PAGE_PATTERN.sub("", text)
    text = _PAGE_NONE.sub("", text)

    highlighted = ""
    context = ""

    h_match = re.search(r"\[HIGHLIGHTED\]\s*\n(.*?)(?:\[CONTEXT\]|\Z)", text, re.DOTALL | re.IGNORECASE)
    c_match = re.search(r"\[CONTEXT\]\s*\n(.*?)$", text, re.DOTALL | re.IGNORECASE)

    if h_match:
        highlighted = h_match.group(1).strip()
    if c_match:
        context = c_match.group(1).strip()

    if not highlighted and not context:
        highlighted = text.strip()

    return highlighted, context


# --- OCR Noise Cleanup ---


def _clean_ocr_noise(text: str) -> str:
    """Remove common OCR artifacts."""
    text = re.sub(r"[A-ZÀ-Ỹ][A-ZÀ-Ỹ\s_]{14,}\.?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d{1,3}\s*\n", "", text)
    text = re.sub(r"xml version=['\"].*?['\"]", "", text)
    return text.strip()


def _auto_rotate_physical_image(image_path: Path) -> None:
    """Rotate physical image file on disk based on EXIF Orientation."""
    try:
        from PIL import Image, ImageOps

        img = Image.open(image_path)
        exif = img.getexif()
        if exif and exif.get(274, 1) > 1:
            _logger.info(f"EXIF Orientation={exif[274]} on {image_path.name}. Rotating...")
            rotated = ImageOps.exif_transpose(img)
            rotated.save(image_path, format=img.format, quality=95)
            _logger.info(f"Physical auto-rotation successful for {image_path.name}")
    except Exception as e:
        _logger.warning(f"Physical auto-rotation failed for {image_path.name}: {e}")


# --- Public API ---


def extract_ocr(image_path: Path, *, book_name: str = "") -> OcrResult:
    """Run Vision OCR on an image and parse the result.

    Args:
        image_path: Path to the image file.
        book_name: Book name for logging context.

    Returns:
        OcrResult with parsed OCR data.
    """
    _auto_rotate_physical_image(image_path)
    filename = image_path.name.lower()

    if filename.startswith("_toc") or filename.startswith("_cover"):
        return _extract_toc(image_path)

    _logger.info(f"OCR: {image_path.name}")
    raw = call_vision(image_path, _OCR_PROMPT, max_pixels=1536)

    if not raw or len(raw.strip()) < 30:
        _logger.warning(f"OCR returned too little text ({len(raw)} chars)")
        return OcrResult(raw_text=raw, highlighted="", context="", page_number=None, is_toc=False)

    page = _parse_page(raw)
    highlighted, context = _parse_highlights(raw)
    highlighted = _clean_ocr_noise(highlighted)
    context = _clean_ocr_noise(context)

    _logger.info(f"OCR OK: page={page}, highlighted={len(highlighted)} chars, context={len(context)} chars")

    return OcrResult(
        raw_text=raw,
        highlighted=highlighted,
        context=context,
        page_number=page,
        is_toc=False,
    )


# --- Source Note Sync & Helpers ---


def _find_source_note(book_name: str) -> Path | None:
    """Find matching Source Note by substring or token-based fuzzy matching."""
    book_clean = book_name.lower().replace("_", " ")
    for f in cfg.sources_dir.iterdir():
        if f.suffix == ".md" and book_clean in f.stem.lower().replace("_", " "):
            return f

    book_tokens = [t for t in book_name.lower().split("_") if len(t) > 2 and t not in ("the", "and", "for", "with", "from", "pdf", "epub")]
    if not book_tokens:
        return None

    best_match, max_matches = None, 0
    for f in cfg.sources_dir.iterdir():
        if f.suffix == ".md":
            stem_clean = f.stem.lower().replace("_", " ")
            matches = sum(1 for t in book_tokens if t in stem_clean or t[:-1] in stem_clean)
            if matches > max_matches and matches >= len(book_tokens) * 0.6:
                max_matches, best_match = matches, f
    if best_match:
        _logger.info(f"_sync_source_note: Fuzzy matched '{book_name}' to '{best_match.name}' ({max_matches}/{len(book_tokens)})")
    return best_match


def _update_source_frontmatter(content: str, book_title_vi: str, language: str | None) -> str:
    """Update title, aliases, date_modified, and language in frontmatter."""
    updated = content
    if book_title_vi:
        today = date.today().isoformat()
        updated = re.sub(r'^(title:\s*).*$', f'title: "{book_title_vi}"', updated, count=1, flags=re.MULTILINE)
        updated = re.sub(r'^(aliases:\s*\n\s*-\s*).*$', f'\\g<1>"{book_title_vi}"', updated, count=1, flags=re.MULTILINE)
        updated = re.sub(r'^(date_modified:\s*).*$', f'\\g<1>{today}', updated, count=1, flags=re.MULTILINE)

    if language:
        if re.search(r'^language:\s*.*$', updated, flags=re.MULTILINE):
            updated = re.sub(r'^(language:\s*).*$', f'language: "{language}"', updated, count=1, flags=re.MULTILINE)
        else:
            updated = re.sub(r'^(title:\s*.*)$', f'\\1\nlanguage: "{language}"', updated, count=1, flags=re.MULTILINE)
    return updated


def _inject_source_toc(content: str, chapters: list[dict]) -> str:
    """Inject or replace Table of Contents section in source note body."""
    if not chapters:
        return content
    lines = ["## 📚 Mục lục", "", "| Chương | Tiêu đề | Trang |", "|:---:|:---|:---:|"]
    for ch in chapters:
        num = ch.get("chapter_num", "?")
        title_vi = ch.get("title_vi", "")
        p_start, p_end = ch.get("page_start", ""), ch.get("page_end", "")
        page_range = f"{p_start}–{p_end}" if p_end else str(p_start)
        lines.append(f"| {num} | {title_vi} | {page_range} |")
    toc_block = "\n".join(lines)

    if "## 📚 Mục lục" in content:
        return re.sub(r'## 📚 Mục lục\n.*?(?=\n## |\Z)', toc_block + "\n", content, flags=re.DOTALL)
    return re.sub(r'(# .+\n)', f'\\g<1>\n{toc_block}\n\n', content, count=1)


def _sync_source_note(book_name: str, toc_data: dict) -> None:
    """Sync _toc.json data back into the Source Note (Fix #1: Reverse Metadata Sync).

    When a TOC image is processed and _toc.json is created, this hook:
    1. Finds the Source Note in 04-Permanent/sources/ for this book.
    2. Updates the YAML 'title' and 'aliases' with the Vietnamese book title.
    3. Injects a formatted Table of Contents table into the note body.
    """
    book_title_vi = toc_data.get("book_title_vi", "").strip()
    chapters = toc_data.get("chapters", [])
    if not book_title_vi and not chapters:
        _logger.debug("_sync_source_note: no useful data in toc_data, skipping")
        return

    source_note = _find_source_note(book_name)
    if source_note is None:
        _logger.warning(f"_sync_source_note: no Source Note found for '{book_name}'")
        return

    try:
        content = source_note.read_text(encoding="utf-8")
    except OSError as e:
        _logger.error(f"_sync_source_note: cannot read {source_note}: {e}")
        return

    updated = _update_source_frontmatter(content, book_title_vi, toc_data.get("language"))
    updated = _inject_source_toc(updated, chapters)

    if updated != content:
        try:
            source_note.write_text(updated, encoding="utf-8")
            _logger.info(
                f"Source Note synced: {source_note.name}"
                + (f" (title: {book_title_vi})" if book_title_vi else "")
                + (f" ({len(chapters)} chapters)" if chapters else "")
            )
        except OSError as e:
            _logger.error(f"_sync_source_note: failed to write {source_note}: {e}")
    else:
        _logger.debug(f"_sync_source_note: no changes needed for {source_note.name}")


# --- TOC Extraction & Alignment Helpers ---


def _resolve_toc_prompt(workspace_toc_path: Path) -> str:
    """Resolve TOC extraction prompt, using alignment prompt if template exists."""
    if workspace_toc_path.exists():
        try:
            template = workspace_toc_path.read_text(encoding="utf-8")
            if template.strip() and template.strip() != "{}":
                _logger.info("Loaded original TOC template for cross-lingual alignment")
                return _TOC_ALIGNMENT_PROMPT.format(original_toc=template)
        except OSError as e:
            _logger.warning(f"Failed to read existing _toc.json template: {e}")
    return _TOC_PROMPT


def _align_chapter_pages(chapters: list[dict]) -> list[dict]:
    """Sort chapters and calculate missing page_end."""
    def _start_val(x: dict) -> int:
        try:
            return int(x.get("page_start") or 0)
        except (ValueError, TypeError):
            return 0

    sorted_chapters = sorted(chapters, key=_start_val)
    for i, ch in enumerate(sorted_chapters):
        if "page_start" in ch and ch["page_start"] is not None:
            try:
                ch["page_start"] = int(ch["page_start"])
            except ValueError:
                pass
        if not ch.get("page_end"):
            if i < len(sorted_chapters) - 1:
                next_start = _start_val(sorted_chapters[i + 1])
                ch["page_end"] = next_start - 1 if next_start > 0 else None
            else:
                ch["page_end"] = None
    return sorted_chapters


def _trigger_toc_post_actions(book_dir: Path, toc_data: dict) -> None:
    """Run post-TOC hooks: source note sync and macro context enrichment."""
    try:
        _sync_source_note(book_dir.name, toc_data)
    except Exception as sync_err:
        _logger.warning(f"Source Note sync failed (non-critical): {sync_err}")

    try:
        from pipeline.map_reduce import enrich_book_context
        enrich_book_context(book_dir)
    except Exception as enrich_err:
        _logger.warning(f"Failed to auto-enrich _context.txt (non-critical): {enrich_err}")


def _extract_toc(image_path: Path) -> OcrResult:
    """Extract Table of Contents from a TOC image using Cross-lingual Alignment.

    Saves result as _toc.json in the same directory.
    Also triggers Reverse Metadata Sync to update the Source Note (Fix #1).
    """
    _logger.info(f"TOC extraction with alignment check: {image_path.name}")
    workspace_toc_path = image_path.parent / "_toc.json"
    prompt = _resolve_toc_prompt(workspace_toc_path)

    raw = call_vision(image_path, prompt, max_pixels=2048)
    if raw:
        try:
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                toc_data = json.loads(json_match.group())
                toc_data["chapters"] = _align_chapter_pages(toc_data.get("chapters", []))
                with open(workspace_toc_path, "w", encoding="utf-8") as f:
                    json.dump(toc_data, f, ensure_ascii=False, indent=2)
                _logger.info(f"TOC aligned and saved: {workspace_toc_path}")
                _trigger_toc_post_actions(image_path.parent, toc_data)
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning(f"TOC alignment parse/save failed: {e}")

    return OcrResult(raw_text=raw, highlighted="", context="", page_number=None, is_toc=True)
