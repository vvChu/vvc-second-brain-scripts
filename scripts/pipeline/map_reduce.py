"""VvC Second Brain — Map-Reduce Ingestion Module (v7.8).

Map Step: Semantic Topic Boundary Segmentation for multi-page image batches.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

from core.config import cfg
from core.llm import call_llm
from core.prompts.pipeline import (
    BOOK_CONTEXT_ENRICHMENT as _ENRICHMENT_PROMPT,
    TOPIC_SEGMENTATION as _SEGMENTATION_PROMPT,
)

_logger = logging.getLogger("vvc.map_reduce")


class SegmentedConcept(TypedDict):
    title: str
    page_start: int
    page_end: int
    rationale: str


_GENERIC_TITLE_PAT = re.compile(
    r"^(?:chapter|chương|part|phần|section|mục|preface|lời mở đầu|notes|ch|pt)\s*[ivxlc\d]*$",
    re.IGNORECASE,
)


def _is_generic_title(title: str) -> bool:
    """Check if chapter title is generic structural marker (e.g. Chapter 1, Part II)."""
    return bool(_GENERIC_TITLE_PAT.match(title.strip())) if title else True


def _clean_chapter_title_from_filename(epub_file: str) -> str:
    """Extract and clean a descriptive chapter title from an epub_file path/filename."""
    if not epub_file:
        return ""
    stem = Path(epub_file).stem
    cleaned = re.sub(r"^\d+_(?:[a-zA-Z0-9]+_)*(?:Part_[IVXLC\d]+_)?(?:Ch\d+_)??", "", stem, flags=re.IGNORECASE)
    return (cleaned if cleaned.strip() else stem).replace("_", " ").strip()


def _build_chapter_title(ch: dict[str, Any], ch_num: Any) -> str:
    """Build standardized bilingual or descriptive chapter title."""
    t_vi = ch.get("title_vi", "").strip() if isinstance(ch.get("title_vi"), str) else ""
    t_orig = ch.get("title_original", "").strip() if isinstance(ch.get("title_original"), str) else ""
    epub_file = ch.get("epub_file", "").strip() if isinstance(ch.get("epub_file"), str) else ""

    if epub_file:
        enriched = _clean_chapter_title_from_filename(epub_file)
        if enriched:
            if _is_generic_title(t_orig):
                t_orig = f"{t_orig or f'Chapter {ch_num}'}: {enriched}"
            if _is_generic_title(t_vi):
                prefix = t_vi or f"Chương {ch_num}"
                if enriched.lower() not in t_vi.lower():
                    t_vi = f"{prefix}: {enriched}"

    if t_vi and t_orig:
        t_vi_c, t_orig_c = t_vi.lower(), t_orig.lower()
        if t_vi_c == t_orig_c or t_orig_c in t_vi_c:
            return t_vi
        if t_vi_c in t_orig_c:
            return t_orig
        return f"{t_vi} ({t_orig})"
    return t_vi or t_orig or f"Chương {ch_num}"


def _calculate_page_end(ch: dict[str, Any], i: int, chapters: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Parse page_start and calculate page_end if missing."""
    p_start, p_end = ch.get("page_start"), ch.get("page_end")
    try: p_start = int(p_start) if p_start is not None else None
    except (ValueError, TypeError): p_start = None
    try: p_end = int(p_end) if p_end is not None else None
    except (ValueError, TypeError): p_end = None

    if p_start is not None and p_end is None:
        for next_ch in chapters[i + 1:]:
            n_start = next_ch.get("page_start")
            if n_start is not None:
                try:
                    p_end = int(n_start) - 1
                    break
                except (ValueError, TypeError): pass
    return p_start, p_end


def _format_toc_structure(toc_file: Path, fallback_title: str) -> tuple[str, str]:
    """Parse _toc.json and format book structure lines."""
    if not toc_file.exists():
        return fallback_title, "- (Chưa có thông tin cấu trúc chi tiết)"
    try:
        toc_data = json.loads(toc_file.read_text(encoding="utf-8"))
        book_title = toc_data.get("book_title_vi") or toc_data.get("book_title_original") or fallback_title
        chapters = toc_data.get("chapters", [])
        lines: list[str] = []
        for i, ch in enumerate(chapters):
            ch_num = ch.get("chapter_num")
            ch_title = _build_chapter_title(ch, ch_num)
            p_start, p_end = _calculate_page_end(ch, i, chapters)
            page_info = f" [Trang {p_start}-{p_end}]" if p_start is not None and p_end is not None else (f" [Trang {p_start}]" if p_start is not None else "")
            lines.append(f"- Mục {ch_num}: {ch_title}{page_info}")
            desc = ch.get("description_vi")
            summary_val = desc.strip() if isinstance(desc, str) and desc.strip() else "(Thêm tóm tắt chương tại đây để LLM nắm ngữ cảnh phân tích)"
            lines.append(f"      * Tóm tắt: {summary_val}")
        return book_title, "\n    ".join(lines) if lines else "- (Chưa có thông tin cấu trúc chi tiết)"
    except Exception as e:
        _logger.error(f"Failed to parse _toc.json in JIT context generation: {e}")
        return fallback_title, "- (Chưa có thông tin cấu trúc chi tiết)"


def _find_source_summary(workspace_dir: Path) -> str:
    """Find matching Source Note and extract summary from frontmatter."""
    source_notes = list(cfg.sources_dir.glob(f"*_{workspace_dir.name.lower()}.md"))
    if source_notes:
        try:
            from core.frontmatter import parse_frontmatter
            fm = parse_frontmatter(source_notes[0].read_text(encoding="utf-8"))
            if fm and fm.get("summary"):
                return fm["summary"]
        except Exception as e:
            _logger.error(f"Failed to parse source note {source_notes[0]} frontmatter: {e}")
    return "Tóm tắt cốt lõi chưa được cập nhật."


def _build_book_context_xml(summary_str: str, structure_str: str) -> str:
    """Build XML representation for <BOOK_CONTEXT>."""
    return (
        f"<BOOK_CONTEXT>\n"
        f"  <SUMMARY>\n"
        f"    {summary_str}\n"
        f"  </SUMMARY>\n"
        f"  <STRUCTURE>\n"
        f"    {structure_str}\n"
        f"  </STRUCTURE>\n"
        f"  <GLOSSARY>\n"
        f"    - Thuật ngữ 1: Định nghĩa thuật ngữ 1 (Nhập thuật ngữ chuyên ngành của sách tại đây để LLM Segmenter & Synthesizer dịch nhất quán)\n"
        f"  </GLOSSARY>\n"
        f"  <COMPILATION_GUIDELINES>\n"
        f"    - Khẩu vị: Ưu tiên phân rã các concept ở mức nguyên tử tối đa (1 ý tưởng = 1 note).\n"
        f"    - Văn phong: Sử dụng văn phong học thuật, gãy gọn, không dùng từ ngữ sáo rỗng.\n"
        f"  </COMPILATION_GUIDELINES>\n"
        f"  <PEOPLE_AND_ORGANIZATIONS>\n"
        f"    - Nhân vật: (Các nhân vật nổi tiếng đề cập trong sách)\n"
        f"    - Tổ chức: (Các công ty/tổ chức nổi tiếng đề cập trong sách)\n"
        f"  </PEOPLE_AND_ORGANIZATIONS>\n"
        f"  <EXCLUDE_KEYWORDS>\n"
        f"    - Lời cảm ơn, Lời giới thiệu, Thông tin bản quyền, Lời tựa, Tác giả\n"
        f"  </EXCLUDE_KEYWORDS>\n"
        f"</BOOK_CONTEXT>"
    )


def get_or_create_book_context(workspace_dir: Path) -> str:
    """Get the book context from _context.txt, or create it if missing (Lazy-JIT Cache)."""
    context_file = workspace_dir / "_context.txt"
    if not context_file.exists():
        return ""
    try:
        content = context_file.read_text(encoding="utf-8")
    except Exception as e:
        _logger.error(f"Failed to read context file {context_file}: {e}")
        return ""

    if "<BOOK_CONTEXT>" in content and "</BOOK_CONTEXT>" in content:
        match = re.search(r"(<BOOK_CONTEXT>.*</BOOK_CONTEXT>)", content, re.DOTALL)
        if match:
            return match.group(1)

    _logger.info(f"Generating JIT <BOOK_CONTEXT> for workspace: {workspace_dir.name}")
    _, structure_str = _format_toc_structure(workspace_dir / "_toc.json", workspace_dir.name.replace("_", " "))
    summary_str = _find_source_summary(workspace_dir)
    xml_block = _build_book_context_xml(summary_str, structure_str)

    try:
        clean = content.rstrip()
        context_file.write_text(f"{clean}\n\n---\n{xml_block}\n", encoding="utf-8")
        _logger.info(f"Cached JIT <BOOK_CONTEXT> to {context_file.name}")
    except Exception as e:
        _logger.error(f"Failed to write JIT <BOOK_CONTEXT> cache to {context_file}: {e}")
    return xml_block


def _format_ocr_chunks(pages_data: list[dict[str, Any]]) -> str:
    """Sort pages and format concatenated OCR text with page breaks."""
    sorted_pages = sorted(
        pages_data,
        key=lambda x: x.get("page_number") if x.get("page_number") is not None else 9999,
    )
    chunks: list[str] = []
    for i, p in enumerate(sorted_pages):
        lbl = p.get("page_number")
        num = str(lbl) if lbl is not None else f"Không rõ (Ảnh {i+1})"
        chunk = (
            f"--- TRANG {num} ---\n"
            f"[HIGHLIGHTED]\n{p.get('highlighted', '').strip()}\n\n"
            f"[CONTEXT]\n{p.get('context', '').strip()}\n"
        )
        chunks.append(chunk)
    return "\n\n".join(chunks)


def _parse_segmented_concepts(raw_response: str) -> list[SegmentedConcept] | None:
    """Parse JSON array from LLM response into validated SegmentedConcept list."""
    match = re.search(r"\[\s*\{.*\}\s*\]", raw_response, re.DOTALL) or re.search(r"\[.*\]", raw_response, re.DOTALL)
    if not match:
        _logger.error("Segment concepts: could not find JSON array block in LLM response")
        return None
    try:
        parsed = json.loads(match.group())
        valid: list[SegmentedConcept] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "").strip()
            if not title:
                continue
            try:
                p_start = int(item.get("page_start")) if item.get("page_start") is not None else 0
                p_end = int(item.get("page_end")) if item.get("page_end") is not None else p_start
            except (ValueError, TypeError):
                p_start, p_end = 0, 0
            valid.append({"title": title, "page_start": p_start, "page_end": p_end, "rationale": item.get("rationale", "").strip()})
        _logger.info(f"Segment concepts: successfully segmented {len(valid)} concepts")
        return valid
    except Exception as e:
        _logger.error(f"Segment concepts: failed to parse JSON array: {e}")
        return None


def segment_concepts(pages_data: list[dict[str, Any]], book_name: str) -> list[SegmentedConcept] | None:
    """Analyze OCR texts of a large image batch and segment it into atomic concepts."""
    if not pages_data:
        _logger.warning("segment_concepts: empty pages_data list")
        return []

    book_macro_context = ""
    if pages_data and "image_path" in pages_data[0]:
        img_path = pages_data[0]["image_path"]
        if isinstance(img_path, (str, Path)):
            try:
                book_macro_context = get_or_create_book_context(Path(img_path).parent)
            except Exception as e:
                _logger.error(f"Failed to obtain book macro context: {e}")

    formatted_ocr = _format_ocr_chunks(pages_data)
    prompt = _SEGMENTATION_PROMPT.format(
        book_name=book_name,
        book_macro_context=book_macro_context or "Không có thông tin nền vĩ mô.",
        formatted_ocr=formatted_ocr,
    )
    _logger.info(f"Segmenting concepts (Map Step) for book: {book_name} over {len(pages_data)} pages")
    raw_response = call_llm(prompt, task="reasoning")
    if not raw_response:
        _logger.error("Segment concepts: empty response from LLM")
        return None

    from core.llm.utils import strip_think_tags
    return _parse_segmented_concepts(strip_think_tags(raw_response))


def _extract_context_body(enriched_content: str) -> str | None:
    """Extract and validate <BOOK_CONTEXT> body from LLM output."""
    if "<BOOK_CONTEXT>" not in enriched_content or "</BOOK_CONTEXT>" not in enriched_content:
        _logger.error("enrich_book_context: LLM output did not contain valid <BOOK_CONTEXT> tags")
        return None
    if "---" in enriched_content:
        return enriched_content.split("---", 1)[1].strip()
    match = re.search(r"(<BOOK_CONTEXT>.*</BOOK_CONTEXT>)", enriched_content, re.DOTALL)
    return match.group(1).strip() if match else None


def enrich_book_context(workspace_dir: Path) -> bool:
    """Auto-enrich placeholders inside _context.txt based on complete _toc.json (JIT Context Enrichment)."""
    context_file = workspace_dir / "_context.txt"
    toc_file = workspace_dir / "_toc.json"
    if not context_file.exists() or not toc_file.exists():
        _logger.warning(f"enrich_book_context: missing _context.txt or _toc.json in {workspace_dir.name}")
        return False
    try:
        current_context = context_file.read_text(encoding="utf-8")
        toc_json = toc_file.read_text(encoding="utf-8")
    except Exception as e:
        _logger.error(f"enrich_book_context: failed to read files in {workspace_dir.name}: {e}")
        return False

    placeholders = [
        "(Thêm tóm tắt chương tại đây để LLM nắm ngữ cảnh phân tích)",
        "Định nghĩa thuật ngữ 1 (Nhập thuật ngữ chuyên ngành",
        "(Các nhân vật nổi tiếng đề cập trong sách)",
        "(Các công ty/tổ chức nổi tiếng đề cập trong sách)",
    ]
    if not any(p in current_context for p in placeholders):
        _logger.info(f"enrich_book_context: _context.txt in {workspace_dir.name} is already enriched, skipping")
        return True

    _logger.info(f"enrich_book_context: Starting JIT Enrichment for {workspace_dir.name}...")
    prompt = _ENRICHMENT_PROMPT.format(
        book_name=workspace_dir.name.replace("_", " "),
        current_context=current_context,
        toc_json=toc_json,
    )
    try:
        raw = call_llm(prompt, task="synthesis")
        if not raw:
            _logger.error("enrich_book_context: Empty response from LLM")
            return False
        from core.llm.utils import strip_think_tags
        body = _extract_context_body(strip_think_tags(raw).strip())
        if not body:
            return False
        header = current_context.split("---", 1)[0].strip() if "---" in current_context else ""
        final_content = f"{header}\n\n---\n{body}\n" if header else f"{body}\n"
        context_file.write_text(final_content, encoding="utf-8")
        _logger.info(f"enrich_book_context: Successfully enriched _context.txt for {workspace_dir.name}!")
        return True
    except Exception as e:
        _logger.error(f"enrich_book_context: failed during JIT enrichment process: {e}")
        return False
