"""Tests for pipeline modules (OCR, synthesis, post-process)."""

import re
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# --- OCR Tests ---

def test_parse_page_number():
    """Should extract page number from OCR output."""
    from pipeline.ocr import _parse_page

    assert _parse_page("PAGE: 42\n\nSome text") == 42
    assert _parse_page("PAGE: NONE\n\nText") is None
    assert _parse_page("No page info here") is None
    assert _parse_page("15\nSome text following") == 15


def test_parse_highlights():
    """Should split text into highlighted and context."""
    from pipeline.ocr import _parse_highlights

    text = """PAGE: 10

[HIGHLIGHTED]
This is the highlighted content.

[CONTEXT]
This is context text."""

    highlighted, context = _parse_highlights(text)
    assert "highlighted content" in highlighted
    assert "context text" in context


def test_parse_highlights_no_markers():
    """Should treat entire text as highlighted when no markers."""
    from pipeline.ocr import _parse_highlights

    highlighted, context = _parse_highlights("Just plain text here")
    assert highlighted == "Just plain text here"
    assert context == ""


def test_find_diagram_context():
    """Should extract context around placeholder."""
    from services.diagram_base import find_diagram_context

    text = "Before text. " * 100 + "![[test.excalidraw.md]]" + " After text." * 100
    context = find_diagram_context("test.excalidraw.md", text)
    assert "![[test.excalidraw.md]]" in context
    assert len(context) < len(text)


def test_clean_ocr_noise():
    """Should remove OCR noise artifacts."""
    from pipeline.ocr import _clean_ocr_noise

    text = "TÁI TẠO TÔ CHU KI NGUYEN NHAY CHIEN LUC.\nActual content here"
    cleaned = _clean_ocr_noise(text)
    assert "Actual content here" in cleaned


# --- Synthesize Tests ---

def test_strip_ocr_noise_from_blockquote():
    """Should remove ALL-CAPS lines from Core Idea blockquote."""
    from pipeline.synthesize import _strip_ocr_noise_from_blockquote

    content = """## Core Idea

> TỔNG HỢP CẤU TDP NNG LỰC HỆ SINH TAI
> Actual important content here.

## References"""

    result = _strip_ocr_noise_from_blockquote(content)
    assert "TỔNG HỢP" not in result
    assert "Actual important content" in result


def test_extract_title_from_content():
    """Should extract title from frontmatter or H1."""
    from pipeline.synthesize import extract_title_from_content

    content_fm = '---\ntitle: "My Concept"\n---\n\n# Body'
    assert extract_title_from_content(content_fm) == "My Concept"

    content_h1 = "# My Heading\n\nBody text"
    assert extract_title_from_content(content_h1) == "My Heading"

    assert extract_title_from_content("No title here") == "untitled"


# --- Post-Process Tests ---

def test_title_to_filename():
    """Should convert title to snake_case filename."""
    from pipeline.post_process import _title_to_filename

    # These work regardless of unidecode availability
    assert _title_to_filename("Simple Test") == "simple_test.md"
    assert _title_to_filename("AI & Machine Learning!") == "ai_machine_learning.md"

    # Vietnamese requires unidecode for proper conversion
    result = _title_to_filename("Chiến lược NVIDIA")
    assert result.endswith(".md")
    assert "nvidia" in result


def test_title_to_filename_truncation():
    """Should truncate very long titles."""
    from pipeline.post_process import _title_to_filename

    long_title = "A" * 200
    result = _title_to_filename(long_title)
    assert len(result) <= 84  # 80 + ".md"


@patch("pipeline.post_process._archive_image")
def test_save_concept_image_chapter_fallback(mock_archive):
    """Should fall back to ground_truth_chapter when source_chapter is empty."""
    from pipeline.post_process import save_concept
    import tempfile
    from unittest.mock import MagicMock
    from core.config import cfg
    
    content = """---
title: "Test Fallback Chapter"
source_page: "42"
source_chapter: ""
ground_truth_chapter: "[[Chương 3: Nhóm cốt lõi]]"
ground_truth_page: ""
people: []
companies: []
status: seed
---

> "This is a highlight text bằng tiếng Việt."
> — **Test Author**, trích dẫn trong *Test Book* ([[test_source|Test Book, 2026]])

## Core Idea

This is the required core idea section with enough characters to pass the quality gate of 300 characters minimum. Let's make it longer by adding some extra meaningful analysis. The business focus must be aligned with targets. We must ensure that the autonomous pipeline operates correctly under all scenarios, including empty source chapters.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> "Original English passage for verification."

---

## References

- [[test_source]]
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_concepts_dir = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", Path(tmpdir))
        
        try:
            mock_img = MagicMock(spec=Path)
            mock_img.exists.return_value = True
            mock_img.name = "test_img.jpg"
            mock_img.suffix = ".jpg"
            
            save_concept(content, image_path=mock_img, book_name="TestBook")
            
            mock_archive.assert_called_once()
            args, kwargs = mock_archive.call_args
            assert kwargs.get("concept_slug") == "test_fallback_chapter"
            assert args[3] == "[[Chương 3: Nhóm cốt lõi]]"
        finally:
            object.__setattr__(cfg, "concepts_dir", orig_concepts_dir)


# --- Self-Correct Tests ---

def test_extract_core_idea_blockquote():
    """Should extract blockquote from Core Idea section."""
    from pipeline.self_correct import _extract_core_idea_blockquote

    content = """# Title

> Summary

## Core Idea

> "This is the quote."
> "Second line of quote."

Analysis text.

## References

- link"""

    bq = _extract_core_idea_blockquote(content)
    assert '> "This is the quote."' in bq
    assert '> "Second line of quote."' in bq


def test_extract_blockquote_missing():
    """Should return empty string when no blockquote in Core Idea."""
    from pipeline.self_correct import _extract_core_idea_blockquote

    content = "## Core Idea\n\nJust plain text.\n\n## References"
    assert _extract_core_idea_blockquote(content) == ""


# --- LLM Client Tests ---

def test_strip_think_tags():
    """Should unconditionally strip think tags."""
    from core.llm.utils import strip_think_tags

    assert strip_think_tags("<think>reasoning</think>Answer") == "Answer"
    assert strip_think_tags("<think>partial reasoning") == ""
    assert strip_think_tags("No tags here") == "No tags here"
    assert strip_think_tags("<think>a</think>B<think>c</think>D") == "BD"
    assert strip_think_tags("") == ""


def test_is_garbage():
    """Should detect garbage LLM outputs."""
    from core.llm.utils import is_garbage

    assert is_garbage("") is True
    assert is_garbage("short") is True
    assert is_garbage("Error connecting to API") is True
    assert is_garbage("This is a valid response with enough content.") is False

    # min_length parameter tests (dynamic threshold)
    assert is_garbage("Tải trọng") is True          # 9 chars, default min_length=10 → garbage
    assert is_garbage("Tải trọng", min_length=3) is False  # 9 chars, lowered threshold → OK
    assert is_garbage("Ab", min_length=3) is True    # 2 chars, still below min_length=3
    assert is_garbage("OK") is False                 # whitelisted, always passes
    assert is_garbage("MERGE", allowed_shorts=("MERGE",)) is False  # dynamic whitelist


def test_extract_blockquote_preamble():
    """Should extract blockquote from preamble (v7.7+ format) before first H2."""
    from pipeline.self_correct import _extract_core_idea_blockquote

    content = """---
title: "My Concept"
source: "book.md"
---

> "Trích dẫn nguyên văn tiếng Việt nằm ở preamble."
> — **Tác giả**, trích dẫn trong sách *Sách* ([[book|Nguồn, 2026]])

## Core Idea

Phân tích thuần tiếng Việt ở đây.

## References

- [[book]]
"""

    bq = _extract_core_idea_blockquote(content)
    assert '> "Trích dẫn nguyên văn tiếng Việt nằm ở preamble."' in bq
    assert '> — **Tác giả**' in bq


# --- Archive / WebP Compression Tests ---

def test_archive_image_webp_compression():
    """Should archive image as WebP with reduced file size."""
    import tempfile
    from PIL import Image
    from core.config import cfg
    from pipeline.post_process import _archive_image

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create a dummy 200x300 RGB JPEG image (~15KB)
        src_img = Image.new("RGB", (200, 300), color=(255, 200, 50))
        src_path = tmpdir / "test_photo.jpg"
        src_img.save(src_path, "JPEG", quality=95)
        src_img.close()
        original_size = src_path.stat().st_size

        # Temporarily redirect archive_dir
        orig_archive = cfg.archive_dir
        object.__setattr__(cfg, "archive_dir", tmpdir / "archive")

        try:
            result_name = _archive_image(src_path, book_name="TestBook")

            # Verify output is .webp
            assert result_name.endswith(".webp"), f"Expected .webp, got {result_name}"

            # Verify the file exists
            dest_path = tmpdir / "archive" / "TestBook" / result_name
            assert dest_path.exists(), f"Archived file not found at {dest_path}"

            # Verify WebP is smaller than original JPEG
            webp_size = dest_path.stat().st_size
            assert webp_size < original_size, (
                f"WebP ({webp_size}) should be smaller than JPEG ({original_size})"
            )

            # Verify the WebP is a valid image (close handle to avoid Windows lock)
            reopened = Image.open(dest_path)
            assert reopened.format == "WEBP"
            reopened.close()
        finally:
            object.__setattr__(cfg, "archive_dir", orig_archive)


def test_sync_source_note_fuzzy_match():
    """_sync_source_note should successfully fuzzy match truncated workspace names to correct Source Note."""
    from pipeline.ocr import _sync_source_note
    from core.config import cfg
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        mock_sources_dir = tmpdir_path / "sources"
        mock_sources_dir.mkdir()
        
        # Create full-name Source Note
        source_note_file = mock_sources_dir / "2026-05-22_Becoming_Steve_Jobs_The_Evolution_of_a_Reckless_Upstart_Brent_Schlender.md"
        source_note_file.write_text(
            "---\n"
            "title: \"Becoming Steve Jobs\"\n"
            "aliases:\n"
            "  - \"Steve Jobs\"\n"
            "date_modified: 2026-05-20\n"
            "---\n"
            "# Becoming Steve Jobs\n",
            encoding="utf-8"
        )
        
        # Redirect config sources_dir
        orig_sources_dir = cfg.sources_dir
        object.__setattr__(cfg, "sources_dir", mock_sources_dir)
        
        try:
            # Workspace name is truncated (simulating GDrive/Syncthing or human naming truncation)
            truncated_workspace_name = "Becoming_Steve_Jobs_The_Evolut_Brent_Schlender"
            
            mock_toc_data = {
                "book_title_vi": "Trở Thành Steve Jobs (Bản Việt hóa)",
                "chapters": [
                    {
                        "chapter_num": 1,
                        "title_vi": "Chương 1: Khởi đầu",
                        "page_start": 20
                    }
                ]
            }
            
            # Call sync
            _sync_source_note(truncated_workspace_name, mock_toc_data)
            
            # Verify file was fuzzy matched and successfully updated!
            updated_content = source_note_file.read_text(encoding="utf-8")
            assert "title: \"Trở Thành Steve Jobs (Bản Việt hóa)\"" in updated_content
            assert "aliases:\n  - \"Trở Thành Steve Jobs (Bản Việt hóa)\"" in updated_content
            assert "## 📚 Mục lục" in updated_content
            assert "| 1 | Chương 1: Khởi đầu | 20 |" in updated_content
            
        finally:
            object.__setattr__(cfg, "sources_dir", orig_sources_dir)


def test_save_concept_deterministic_sanitization(tmp_path, monkeypatch):
    """save_concept must deterministically sanitize wikilinks, chimeric edges, and HTML entity leaks."""
    import dataclasses
    from core.config import cfg
    from pipeline.post_process import save_concept

    mock_concepts_dir = tmp_path / "concepts"
    mock_concepts_dir.mkdir()
    mock_cfg = dataclasses.replace(cfg, concepts_dir=mock_concepts_dir)
    monkeypatch.setattr("pipeline.post_process.cfg", mock_cfg)
    monkeypatch.setattr("pipeline.post_process.find_semantic_overlap", lambda content: None)
    monkeypatch.setattr("pipeline.post_process._hot_insert_embedding", lambda path, content: None)

    raw_note = """---
title: "Khái Niệm Kiểm Thử Khử Lỗi"
aliases:
  - "Test Sanitization"
tags:
  - knowledge
  - domain/software
  - type/concept
type: concept
date_created: 2026-09-15
date_modified: 2026-09-15
source: "test_source.md"
summary: "Một insight súc tích phục vụ kiểm thử đơn vị vệ sinh nội dung trước khi lưu."
related:
  - "`[[related_seed_concept]]`"
status: seed
confidence: high
---

> "Đây là câu trích dẫn chứng cứ tiếng Việt hoàn hảo cho bài test."
> — **Tác giả**, *Sách Kiểm Thử* ([[test_source|Kiểm Thử, 2026]])

## Core Idea

Khái niệm này mô tả quy trình làm sạch tất định trước khi ghi đĩa.
Bảng đối chiếu #40;Phiên bản VN#41;:

| Tiêu chí | Mô tả |
|---|---|
| Mã nguồn | Tham chiếu đến `[[target_concept|[1]]]` |

```mermaid
graph TD
    A ===="Nối luồng >= 5"====> B
```

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

This is the original English context for verification.

---

## References

- [[test_source]]
"""
    saved_path = save_concept(raw_note)
    assert saved_path is not None
    assert saved_path.exists()

    saved_content = saved_path.read_text(encoding="utf-8")
    # 1. Backticks around wikilinks stripped (Zero Code-Pill Invariant)
    assert "`[[target_concept|[1]]]`" not in saved_content
    assert "[[target_concept|[1]]]" in saved_content
    assert "`[[related_seed_concept]]`" not in saved_content
    assert "[[related_seed_concept]]" in saved_content

    # 2. Leaked HTML entities in text/table reverted to standard parentheses
    assert "#40;Phiên bản VN#41;" not in saved_content
    assert "(Phiên bản VN)" in saved_content

    # 3. Chimeric Mermaid edge transformed to pipe label and operators normalized
    assert '===>|"Nối luồng ≥ 5"|' in saved_content

