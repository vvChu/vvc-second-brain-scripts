"""VvC Second Brain — Map-Reduce Ingestion Module (v7.8).

Map Step: Semantic Topic Boundary Segmentation for multi-page image batches.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TypedDict

from core.llm import call_llm
from core.config import cfg
from core.prompts.pipeline import (
    TOPIC_SEGMENTATION as _SEGMENTATION_PROMPT,
    BOOK_CONTEXT_ENRICHMENT as _ENRICHMENT_PROMPT,
)

_logger = logging.getLogger("vvc.map_reduce")


class SegmentedConcept(TypedDict):
    title: str
    page_start: int
    page_end: int
    rationale: str




_GENERIC_TITLE_PAT = re.compile(r"^(?:chapter|chương|part|phần|section|mục|preface|lời mở đầu|notes|ch|pt)\s*[ivxlc\d]*$", re.IGNORECASE)

def _is_generic_title(title: str) -> bool:
    """Check if the chapter title is a generic structural marker (e.g. Chapter 1, Part II)."""
    if not title:
        return True
    return bool(_GENERIC_TITLE_PAT.match(title.strip()))


def _clean_chapter_title_from_filename(epub_file: str) -> str:
    """Extract and clean a descriptive chapter title from an epub_file path/filename.
    
    Example: 
        "05_1_A_New_Organization_How_Can.md" -> "A New Organization How Can"
        "09_Part_II_The_New_Organizational_Form.md" -> "The New Organizational Form"
    """
    if not epub_file:
        return ""
    stem = Path(epub_file).stem
    
    # Remove leading sequence digits and structural prefixes (e.g., "05_1_", "09_Part_II_")
    cleaned = re.sub(r"^\d+_(?:[a-zA-Z0-9]+_)*(?:Part_[IVXLC\d]+_)?(?:Ch\d+_)??", "", stem, flags=re.IGNORECASE)
    
    if not cleaned.strip():
        cleaned = stem
        
    # Replace underscores with spaces
    return cleaned.replace("_", " ").strip()


def get_or_create_book_context(workspace_dir: Path) -> str:
    """Get the book context from _context.txt, or create it if missing (Lazy-JIT Cache).

    Args:
        workspace_dir: Path to the fleeting workspace.

    Returns:
        The XML string representation of the book context.
    """
    context_file = workspace_dir / "_context.txt"
    if not context_file.exists():
        return ""

    try:
        content = context_file.read_text(encoding="utf-8")
    except Exception as e:
        _logger.error(f"Failed to read context file {context_file}: {e}")
        return ""

    # Check if <BOOK_CONTEXT> block already exists
    if "<BOOK_CONTEXT>" in content and "</BOOK_CONTEXT>" in content:
        match = re.search(r"(<BOOK_CONTEXT>.*</BOOK_CONTEXT>)", content, re.DOTALL)
        if match:
            return match.group(1)

    # Generate it JIT
    _logger.info(f"Generating JIT <BOOK_CONTEXT> for workspace: {workspace_dir.name}")
    
    # 1. Parse _toc.json to get book title and structure
    toc_file = workspace_dir / "_toc.json"
    book_title = workspace_dir.name.replace("_", " ")
    structure_lines: list[str] = []
    
    if toc_file.exists():
        try:
            toc_data = json.loads(toc_file.read_text(encoding="utf-8"))
            book_title = toc_data.get("book_title_vi") or toc_data.get("book_title_original") or book_title
            
            chapters = toc_data.get("chapters", [])
            for i, ch in enumerate(chapters):
                ch_num = ch.get("chapter_num")
                
                title_vi_raw = ch.get("title_vi")
                title_vi = title_vi_raw.strip() if isinstance(title_vi_raw, str) else ""
                
                title_orig_raw = ch.get("title_original")
                title_orig = title_orig_raw.strip() if isinstance(title_orig_raw, str) else ""
                
                epub_file_raw = ch.get("epub_file")
                epub_file = epub_file_raw.strip() if isinstance(epub_file_raw, str) else ""
                
                page_start = ch.get("page_start")
                page_end = ch.get("page_end")
                
                description_vi_raw = ch.get("description_vi")
                description_vi = description_vi_raw.strip() if isinstance(description_vi_raw, str) else ""
                
                # Normalize page values
                if page_start is not None:
                    try:
                        page_start = int(page_start)
                    except (ValueError, TypeError):
                        page_start = None
                if page_end is not None:
                    try:
                        page_end = int(page_end)
                    except (ValueError, TypeError):
                        page_end = None
                        
                # Auto-calculate page_end if missing
                if page_start is not None and page_end is None:
                    next_start = None
                    for next_ch in chapters[i+1:]:
                        n_start = next_ch.get("page_start")
                        if n_start is not None:
                            try:
                                next_start = int(n_start)
                                break
                            except (ValueError, TypeError):
                                pass
                    if next_start is not None:
                        page_end = next_start - 1
                
                # Enrich generic chapter titles using epub_file filename if available
                if epub_file:
                    enriched_name = _clean_chapter_title_from_filename(epub_file)
                    if enriched_name:
                        if _is_generic_title(title_orig):
                            prefix = title_orig if title_orig else f"Chapter {ch_num}"
                            title_orig = f"{prefix}: {enriched_name}"
                        if _is_generic_title(title_vi):
                            prefix = title_vi if title_vi else f"Chương {ch_num}"
                            # If it doesn't already have the descriptive part, combine it
                            if enriched_name.lower() not in title_vi.lower():
                                title_vi = f"{prefix}: {enriched_name}"
                
                # Build chapter title block
                ch_title = ""
                if title_vi and title_orig:
                    title_vi_clean = title_vi.lower()
                    title_orig_clean = title_orig.lower()
                    
                    if title_vi_clean == title_orig_clean:
                        ch_title = title_vi
                    elif title_vi_clean in title_orig_clean:
                        ch_title = title_orig
                    elif title_orig_clean in title_vi_clean:
                        ch_title = title_vi
                    else:
                        ch_title = f"{title_vi} ({title_orig})"
                elif title_vi:
                    ch_title = title_vi
                elif title_orig:
                    ch_title = title_orig
                else:
                    ch_title = f"Chương {ch_num}"
                    
                # Format page range
                page_info = ""
                if page_start is not None and page_end is not None:
                    page_info = f" [Trang {page_start}-{page_end}]"
                elif page_start is not None:
                    page_info = f" [Trang {page_start}]"
                    
                chapter_line = f"- Mục {ch_num}: {ch_title}{page_info}"
                structure_lines.append(chapter_line)
                
                # Append description/summary line
                summary_val = description_vi if description_vi else "(Thêm tóm tắt chương tại đây để LLM nắm ngữ cảnh phân tích)"
                structure_lines.append(f"      * Tóm tắt: {summary_val}")
        except Exception as e:
            _logger.error(f"Failed to parse _toc.json in JIT context generation: {e}")

    structure_str = "\n    ".join(structure_lines) if structure_lines else "- (Chưa có thông tin cấu trúc chi tiết)"

    # 2. Find matching Source Note to get summary
    summary_str = "Tóm tắt cốt lõi chưa được cập nhật."
    book_name_lower = workspace_dir.name.lower()
    source_notes = list(cfg.sources_dir.glob(f"*_{book_name_lower}.md"))
    
    if source_notes:
        source_note_path = source_notes[0]
        try:
            from core.frontmatter import parse_frontmatter
            fm = parse_frontmatter(source_note_path.read_text(encoding="utf-8"))
            if fm and "summary" in fm and fm["summary"]:
                summary_str = fm["summary"]
        except Exception as e:
            _logger.error(f"Failed to parse source note {source_note_path} frontmatter: {e}")

    # 3. Build XML block
    xml_block = (
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

    # 4. Write back to _context.txt to cache it
    try:
        clean_content = content.rstrip()
        new_content = f"{clean_content}\n\n---\n{xml_block}\n"
        context_file.write_text(new_content, encoding="utf-8")
        _logger.info(f"Cached JIT <BOOK_CONTEXT> to {context_file.name}")
    except Exception as e:
        _logger.error(f"Failed to write JIT <BOOK_CONTEXT> cache to {context_file}: {e}")

    return xml_block


def segment_concepts(pages_data: list[dict], book_name: str) -> list[SegmentedConcept]:
    """Analyze OCR texts of a large image batch and segment it into atomic concepts.

    Args:
        pages_data: List of dicts, each having 'page_number', 'highlighted', and 'context'.
        book_name: Display name of the book.

    Returns:
        List of SegmentedConcept dicts. Returns empty list on failure.
    """
    if not pages_data:
        _logger.warning("segment_concepts: empty pages_data list")
        return []

    # Get book macro context using the first page's image path
    book_macro_context = ""
    if pages_data and "image_path" in pages_data[0]:
        img_path = pages_data[0]["image_path"]
        if isinstance(img_path, (str, Path)):
            workspace_dir = Path(img_path).parent
            try:
                book_macro_context = get_or_create_book_context(workspace_dir)
            except Exception as e:
                _logger.error(f"Failed to obtain book macro context: {e}")

    # Sort pages by page_number if possible, to keep reading flow logical
    # Fallback to sequential index if page_number is None
    sorted_pages = sorted(
        pages_data,
        key=lambda x: x.get("page_number") if x.get("page_number") is not None else 9999
    )

    # Format concatenated OCR text with clear page breaks
    formatted_chunks: list[str] = []
    for i, p in enumerate(sorted_pages):
        page_lbl = p.get("page_number")
        page_num = str(page_lbl) if page_lbl is not None else f"Không rõ (Ảnh {i+1})"
        
        chunk = (
            f"--- TRANG {page_num} ---\n"
            f"[HIGHLIGHTED]\n{p.get('highlighted', '').strip()}\n\n"
            f"[CONTEXT]\n{p.get('context', '').strip()}\n"
        )
        formatted_chunks.append(chunk)

    formatted_ocr = "\n\n".join(formatted_chunks)

    prompt = _SEGMENTATION_PROMPT.format(
        book_name=book_name,
        book_macro_context=book_macro_context or "Không có thông tin nền vĩ mô.",
        formatted_ocr=formatted_ocr
    )

    _logger.info(f"Segmenting concepts (Map Step) for book: {book_name} over {len(pages_data)} pages")
    
    # Use Tier-1 Reasoning strategy (usually claude-opus-4-6-thinking or gemini-3.1-pro-high)
    raw_response = call_llm(prompt, task="reasoning")

    if not raw_response:
        _logger.error("Segment concepts: empty response from LLM")
        return None

    # Unconditional think-tag stripping
    from core.llm.utils import strip_think_tags
    raw_response = strip_think_tags(raw_response)

    # Try to parse JSON array from output
    try:
        json_match = re.search(r"\[\s*\{.*\}\s*\]", raw_response, re.DOTALL)
        if not json_match:
            # Try a broader search for any JSON structure
            json_match = re.search(r"\[.*\]", raw_response, re.DOTALL)
            
        if not json_match:
            _logger.error("Segment concepts: could not find JSON array block in LLM response")
            _logger.debug(f"Raw Response: {raw_response[:500]}")
            return None

        parsed = json.loads(json_match.group())
        
        # Validate elements in the array
        valid_concepts: list[SegmentedConcept] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "").strip()
            page_start = item.get("page_start")
            page_end = item.get("page_end")
            rationale = item.get("rationale", "").strip()

            if not title:
                continue

            # Ensure page_start and page_end are valid integers
            try:
                p_start = int(page_start) if page_start is not None else 0
                p_end = int(page_end) if page_end is not None else p_start
            except (ValueError, TypeError):
                p_start = 0
                p_end = 0

            valid_concepts.append({
                "title": title,
                "page_start": p_start,
                "page_end": p_end,
                "rationale": rationale
            })

        _logger.info(f"Segment concepts: successfully segmented {len(valid_concepts)} concepts")
        return valid_concepts

    except Exception as e:
        _logger.error(f"Segment concepts: failed to parse JSON array: {e}")
        _logger.debug(f"Raw Response: {raw_response[:500]}")
        return None




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
        
    # Extract metadata header (before '---') to prevent erasure by LLM
    header = ""
    if "---" in current_context:
        parts = current_context.split("---", 1)
        header = parts[0].strip()

    # Check if we actually need enrichment
    placeholders = [
        "(Thêm tóm tắt chương tại đây để LLM nắm ngữ cảnh phân tích)",
        "Định nghĩa thuật ngữ 1 (Nhập thuật ngữ chuyên ngành",
        "(Các nhân vật nổi tiếng đề cập trong sách)",
        "(Các công ty/tổ chức nổi tiếng đề cập trong sách)"
    ]
    if not any(p in current_context for p in placeholders):
        _logger.info(f"enrich_book_context: _context.txt in {workspace_dir.name} is already enriched, skipping")
        return True
        
    _logger.info(f"enrich_book_context: Starting JIT Enrichment for {workspace_dir.name}...")
    
    prompt = _ENRICHMENT_PROMPT.format(
        book_name=workspace_dir.name.replace("_", " "),
        current_context=current_context,
        toc_json=toc_json
    )
    
    try:
        # Use primary synthesis/reasoning model for high-quality context generation
        raw_response = call_llm(prompt, task="synthesis")
        if not raw_response:
            _logger.error("enrich_book_context: Empty response from LLM")
            return False
            
        # Unconditional think-tag stripping
        from core.llm.utils import strip_think_tags
        enriched_content = strip_think_tags(raw_response).strip()
        
        # Validation checks
        if "<BOOK_CONTEXT>" not in enriched_content or "</BOOK_CONTEXT>" not in enriched_content:
            _logger.error("enrich_book_context: LLM output did not contain valid <BOOK_CONTEXT> tags")
            return False
            
        # Extract <BOOK_CONTEXT> block from LLM response safely
        body_content = enriched_content
        if "---" in enriched_content:
            body_parts = enriched_content.split("---", 1)
            body_content = body_parts[1].strip()
        else:
            match = re.search(r"(<BOOK_CONTEXT>.*</BOOK_CONTEXT>)", enriched_content, re.DOTALL)
            if match:
                body_content = match.group(1).strip()

        # Reconstruct final content protecting the original header
        if header:
            final_content = f"{header}\n\n---\n{body_content}\n"
        else:
            final_content = f"{body_content}\n"

        # Write back to file
        context_file.write_text(final_content, encoding="utf-8")
        _logger.info(f"enrich_book_context: Successfully enriched _context.txt for {workspace_dir.name}!")
        return True
    except Exception as e:
        _logger.error(f"enrich_book_context: failed during JIT enrichment process: {e}")
        return False

