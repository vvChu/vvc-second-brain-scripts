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

_logger = logging.getLogger("vvc.ocr")

# --- OCR Result ---

class OcrResult(NamedTuple):
    """Result from OCR extraction."""
    raw_text: str           # Full OCR text (highlighted + context)
    highlighted: str        # Highlighted/underlined content only
    context: str            # Surrounding context text
    page_number: int | None # Detected page number, or None
    is_toc: bool            # Whether this is a TOC image


# --- Prompts ---

_OCR_PROMPT = """BƯỚC 1: Tìm số trang trong ảnh. Trả lời: PAGE: [số] hoặc PAGE: NONE

BƯỚC 2: Đọc toàn bộ văn bản trong ảnh. Phân loại thành 2 phần:

[HIGHLIGHTED]
Phần text được highlight/gạch chân/đánh dấu bằng bút. Đây là nội dung quan trọng nhất.

[CONTEXT]
Phần text không được đánh dấu nhưng nằm trên cùng trang. Đây là ngữ cảnh bổ sung.

QUY TẮC QUAN TRỌNG:
- Đọc chính xác từng chữ, KHÔNG dịch, KHÔNG tóm tắt
- Nối các dòng bị đứt gãy thành đoạn văn mạch lạc
- Nếu không có highlight, đặt toàn bộ text vào [HIGHLIGHTED]
- Bỏ qua header/footer trang (số trang, tên chương in hoa)
"""

_TOC_PROMPT = """Đây là ảnh chụp Mục lục (Table of Contents) của sách.
Hãy trích xuất thông tin dưới dạng JSON theo đúng cấu trúc sau:
{
  "book_title_vi": "Tên sách tiếng Việt",
  "book_title_original": "Tên sách gốc (nếu nhìn thấy, không thì copy title_vi)",
  "chapters": [
    {
      "chapter_num": 1,
      "title_vi": "Tên chương tiếng Việt",
      "title_original": "Tên chương gốc (nếu có, không thì copy title_vi)",
      "description_vi": null,
      "epub_file": null,
      "page_start": 15
    }
  ]
}
Chỉ trả về JSON, không giải thích.
"""

_TOC_ALIGNMENT_PROMPT = """Đây là ảnh chụp Mục lục (Table of Contents) bằng tiếng Việt của một cuốn sách.
Dưới đây là cấu trúc chương sách gốc (tiếng Anh/tiếng bản ngữ) đã được hệ thống trích xuất từ trước:
---
{original_toc}
---

NHIỆM VỤ CỦA BẠN:
1. Đọc kỹ mục lục tiếng Việt trong ảnh chụp.
2. Dịch/So khớp từng chương từ ảnh chụp tiếng Việt với danh sách chương gốc tương ứng.
3. Bổ sung các trường sau vào từng chương trong JSON có sẵn:
   - "title_vi": "Tiêu đề tiếng Việt từ ảnh chụp"
   - "page_start": Số trang bắt đầu của chương này trên sách tiếng Việt ảnh chụp (kiểu integer).
   - "description_vi": "Mô tả ngắn tiếng Việt (nếu có)"
4. Tuyệt đối GIỮ NGUYÊN các trường "epub_file" và "title_original" của cấu trúc ban đầu để không làm mất liên kết tệp.
5. Cập nhật thêm "book_title_vi" ở gốc của JSON.
6. Nếu có chương mới trên mục lục tiếng Việt không khớp với chương nào trong template, hãy thêm mới chương đó với "epub_file": null.

Chỉ trả về JSON hoàn chỉnh sau khi cập nhật, không giải thích.
"""


# --- Page Detection ---

_PAGE_PATTERN = re.compile(r"PAGE:\s*(\d+)", re.IGNORECASE)
_PAGE_NONE = re.compile(r"PAGE:\s*NONE", re.IGNORECASE)


def _parse_page(text: str) -> int | None:
    """Extract page number from OCR output."""
    match = _PAGE_PATTERN.search(text)
    if match:
        return int(match.group(1))
    # Fallback: standalone number at start of text
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
    # Remove PAGE line
    text = _PAGE_PATTERN.sub("", text)
    text = _PAGE_NONE.sub("", text)

    highlighted = ""
    context = ""

    # Try to find [HIGHLIGHTED] and [CONTEXT] markers
    h_match = re.search(
        r"\[HIGHLIGHTED\]\s*\n(.*?)(?:\[CONTEXT\]|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    c_match = re.search(
        r"\[CONTEXT\]\s*\n(.*?)$",
        text, re.DOTALL | re.IGNORECASE,
    )

    if h_match:
        highlighted = h_match.group(1).strip()
    if c_match:
        context = c_match.group(1).strip()

    # Fallback: if no markers found, treat entire text as highlighted
    if not highlighted and not context:
        highlighted = text.strip()

    return highlighted, context


# --- OCR Noise Cleanup ---

def _clean_ocr_noise(text: str) -> str:
    """Remove common OCR artifacts.

    - ALL-CAPS page headers/footers (>15 chars)
    - Standalone page numbers at start
    - XML/encoding artifacts
    """
    # Remove garbled ALL-CAPS lines (likely chapter headers from OCR)
    text = re.sub(r"[A-ZÀ-Ỹ][A-ZÀ-Ỹ\s_]{14,}\.?\s*$", "", text, flags=re.MULTILINE)
    # Remove standalone page numbers at start
    text = re.sub(r"^\s*\d{1,3}\s*\n", "", text)
    # Remove XML artifacts
    text = re.sub(r"xml version=['\"].*?['\"]", "", text)
    return text.strip()


def _auto_rotate_physical_image(image_path: Path) -> None:
    """Automatically rotate the physical image file on disk based on EXIF Orientation.

    This ensures that the image renders upright inside Obsidian and other markdown viewers.
    """
    try:
        from PIL import Image, ImageOps

        # Open image and read EXIF
        img = Image.open(image_path)
        exif = img.getexif()

        # Tag 274 corresponds to EXIF Orientation
        if exif and 274 in exif:
            orientation = exif[274]
            if orientation > 1:
                _logger.info(f"EXIF Orientation={orientation} detected on {image_path.name}. Performing physical auto-rotation...")

                # Rotate image based on EXIF metadata
                rotated_img = ImageOps.exif_transpose(img)

                # Save the rotated image back, overwriting the original file
                # Pillow will automatically clear or update the EXIF orientation to 1
                rotated_img.save(image_path, format=img.format, quality=95)
                _logger.info(f"Physical auto-rotation successful for {image_path.name} (EXIF reset to 1)")
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
    # 0. Automatically rotate physical image based on EXIF Orientation before any processing
    _auto_rotate_physical_image(image_path)

    filename = image_path.name.lower()

    # Check if this is a TOC image
    if filename.startswith("_toc") or filename.startswith("_cover"):
        return _extract_toc(image_path)

    # Regular OCR
    _logger.info(f"OCR: {image_path.name}")
    raw = call_vision(image_path, _OCR_PROMPT, max_pixels=1536)

    if not raw or len(raw.strip()) < 30:
        _logger.warning(f"OCR returned too little text ({len(raw)} chars)")
        return OcrResult(raw_text=raw, highlighted="", context="", page_number=None, is_toc=False)

    # Parse page number
    page = _parse_page(raw)

    # Parse highlights
    highlighted, context = _parse_highlights(raw)

    # Clean noise
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


def _sync_source_note(book_name: str, toc_data: dict) -> None:
    """Sync _toc.json data back into the Source Note (Fix #1: Reverse Metadata Sync).

    When a TOC image is processed and _toc.json is created, this hook:
    1. Finds the Source Note in 04-Permanent/sources/ for this book.
    2. Updates the YAML 'title' and 'aliases' with the Vietnamese book title.
    3. Injects a formatted Table of Contents table into the note body.

    Args:
        book_name: Normalized book identifier (snake_case).
        toc_data: Parsed _toc.json content.
    """
    book_title_vi = toc_data.get("book_title_vi", "").strip()
    chapters = toc_data.get("chapters", [])

    if not book_title_vi and not chapters:
        _logger.debug("_sync_source_note: no useful data in toc_data, skipping")
        return

    # Find matching source note
    source_note: Path | None = None
    book_key = book_name.lower().replace("_", " ")
    for f in cfg.sources_dir.iterdir():
        if f.suffix == ".md" and book_key in f.stem.lower().replace("_", " "):
            source_note = f
            break

    if source_note is None:
        _logger.warning(f"_sync_source_note: no Source Note found for '{book_name}'")
        return

    try:
        content = source_note.read_text(encoding="utf-8")
    except OSError as e:
        _logger.error(f"_sync_source_note: cannot read {source_note}: {e}")
        return

    updated = content
    today = date.today().isoformat()

    # --- Update YAML title if we have Vietnamese title ---
    if book_title_vi:
        # Update title: field
        updated = re.sub(
            r'^(title:\s*).*$',
            f'title: "{book_title_vi}"',
            updated,
            count=1,
            flags=re.MULTILINE,
        )
        # Update aliases: field (replace first alias)
        updated = re.sub(
            r'^(aliases:\s*\n\s*-\s*).*$',
            f'\\g<1>"{book_title_vi}"',
            updated,
            count=1,
            flags=re.MULTILINE,
        )
        # Update date_modified
        updated = re.sub(
            r'^(date_modified:\s*).*$',
            f'\\g<1>{today}',
            updated,
            count=1,
            flags=re.MULTILINE,
        )

    # --- Update YAML language if present ---
    language = toc_data.get("language")
    if language:
        if re.search(r'^language:\s*.*$', updated, flags=re.MULTILINE):
            updated = re.sub(
                r'^(language:\s*).*$',
                f'language: "{language}"',
                updated,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # Insert language right under the title: field in frontmatter
            updated = re.sub(
                r'^(title:\s*.*)$',
                f'\\1\nlanguage: "{language}"',
                updated,
                count=1,
                flags=re.MULTILINE,
            )

    # --- Inject/replace Table of Contents section ---
    if chapters:
        toc_lines = [
            "## 📚 Mục lục",
            "",
            "| Chương | Tiêu đề | Trang |",
            "|:---:|:---|:---:|",
        ]
        for ch in chapters:
            num = ch.get("chapter_num", "?")
            title_vi = ch.get("title_vi", "")
            page_start = ch.get("page_start", "")
            page_end = ch.get("page_end", "")
            page_range = f"{page_start}–{page_end}" if page_end else str(page_start)
            toc_lines.append(f"| {num} | {title_vi} | {page_range} |")

        toc_block = "\n".join(toc_lines)

        # Replace existing TOC section if present, else inject before ## Metadata
        if "## 📚 Mục lục" in updated:
            updated = re.sub(
                r'## 📚 Mục lục\n.*?(?=\n## |\Z)',
                toc_block + "\n",
                updated,
                flags=re.DOTALL,
            )
        else:
            # Inject after the H1 title line
            updated = re.sub(
                r'(# .+\n)',
                f'\\g<1>\n{toc_block}\n\n',
                updated,
                count=1,
            )

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


def _extract_toc(image_path: Path) -> OcrResult:
    """Extract Table of Contents from a TOC image using Cross-lingual Alignment.

    Saves result as _toc.json in the same directory.
    Also triggers Reverse Metadata Sync to update the Source Note (Fix #1).
    """
    _logger.info(f"TOC extraction with alignment check: {image_path.name}")
    
    workspace_toc_path = image_path.parent / "_toc.json"
    original_toc_str = "{}"
    
    # Try to load existing original TOC template if present
    if workspace_toc_path.exists():
        try:
            original_toc_str = workspace_toc_path.read_text(encoding="utf-8")
            _logger.info("Loaded original TOC template for cross-lingual alignment")
        except OSError as e:
            _logger.warning(f"Failed to read existing _toc.json template: {e}")
            
    # Resolve prompt
    if original_toc_str != "{}":
        prompt = _TOC_ALIGNMENT_PROMPT.format(original_toc=original_toc_str)
    else:
        prompt = _TOC_PROMPT

    raw = call_vision(image_path, prompt, max_pixels=2048)

    if raw:
        # Try to parse and save JSON
        try:
            # Extract JSON from response (may have markdown fences)
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                toc_data = json.loads(json_match.group())
                
                # Autocomplete and align page_end based on page_start of next chapter
                chapters = toc_data.get("chapters", [])
                def _get_page_start_val(x):
                    val = x.get("page_start")
                    if val is None:
                        return 0
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        return 0
                sorted_chapters = sorted(chapters, key=_get_page_start_val)
                for i in range(len(sorted_chapters)):
                    ch = sorted_chapters[i]
                    # Ensure page_start is integer
                    if "page_start" in ch and ch["page_start"] is not None:
                        try:
                            ch["page_start"] = int(ch["page_start"])
                        except ValueError:
                            pass
                            
                    # Calculate page_end if missing
                    if "page_end" not in ch or ch["page_end"] is None or ch["page_end"] == "":
                        if i < len(sorted_chapters) - 1:
                            next_start = sorted_chapters[i + 1].get("page_start", 0)
                            try:
                                next_start = int(next_start)
                                ch["page_end"] = next_start - 1 if next_start > 0 else None
                            except (ValueError, TypeError):
                                ch["page_end"] = None
                        else:
                            ch["page_end"] = None
                            
                toc_data["chapters"] = sorted_chapters
                
                with open(workspace_toc_path, "w", encoding="utf-8") as f:
                    json.dump(toc_data, f, ensure_ascii=False, indent=2)
                _logger.info(f"TOC aligned and saved: {workspace_toc_path}")

                # Fix #1: Reverse Metadata Sync — push toc data to Source Note
                book_name = image_path.parent.name
                try:
                    _sync_source_note(book_name, toc_data)
                except Exception as sync_err:
                    _logger.warning(f"Source Note sync failed (non-critical): {sync_err}")

                # Auto-enrich Macro Context Block inside _context.txt
                try:
                    from pipeline.map_reduce import enrich_book_context
                    enrich_book_context(image_path.parent)
                except Exception as enrich_err:
                    _logger.warning(f"Failed to auto-enrich _context.txt (non-critical): {enrich_err}")

        except (json.JSONDecodeError, OSError) as e:
            _logger.warning(f"TOC alignment parse/save failed: {e}")

    return OcrResult(raw_text=raw, highlighted="", context="", page_number=None, is_toc=True)
