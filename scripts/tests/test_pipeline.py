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
