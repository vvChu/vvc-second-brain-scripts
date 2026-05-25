"""Tests for Map-Reduce segmentation and post-process enhancements."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_shorten_chapter():
    """Should correctly extract and shorten chapter names."""
    from pipeline.post_process import _shorten_chapter

    assert _shorten_chapter("[[Chương 7: Đối phó]]") == "ch7"
    assert _shorten_chapter("[[chapter 15]]") == "ch15"
    assert _shorten_chapter("[[04_Ch3]]") == "ch3"
    assert _shorten_chapter("[[04 - Permanent/sources/some_chapter]]") == "some_chapter"
    assert _shorten_chapter("") == ""


@patch("pipeline.map_reduce.call_llm")
def test_segment_concepts_success(mock_call):
    """Should return a parsed, validated list of SegmentedConcepts from LLM JSON response."""
    from pipeline.map_reduce import segment_concepts

    # Mock successful LLM JSON response with think tag
    mock_call.return_value = """<think>
    Thinking process...
    </think>
    [
      {
        "title": "Phản Ứng Với Tinh Thể",
        "page_start": 12,
        "page_end": 14,
        "rationale": "Jobs phản ứng với LCD."
      },
      {
        "title": "Sự Tự Phủ Định Liên Tục",
        "page_start": 15,
        "page_end": 16,
        "rationale": "Sự tự phủ định để tiến bộ."
      }
    ]"""

    pages_data = [
        {"page_number": 12, "highlighted": "Text 12", "context": ""},
        {"page_number": 13, "highlighted": "Text 13", "context": ""},
        {"page_number": 15, "highlighted": "Text 15", "context": ""},
    ]

    result = segment_concepts(pages_data, "Becoming_Steve_Jobs")

    assert len(result) == 2
    assert result[0]["title"] == "Phản Ứng Với Tinh Thể"
    assert result[0]["page_start"] == 12
    assert result[0]["page_end"] == 14
    assert result[1]["title"] == "Sự Tự Phủ Định Liên Tục"
    assert result[1]["page_start"] == 15
    assert result[1]["page_end"] == 16


@patch("pipeline.map_reduce.call_llm")
def test_segment_concepts_malformed_json(mock_call):
    """Should fallback and return empty list on malformed JSON response."""
    from pipeline.map_reduce import segment_concepts

    mock_call.return_value = "This is not a JSON array at all!"
    pages_data = [{"page_number": 12, "highlighted": "Text 12", "context": ""}]

    result = segment_concepts(pages_data, "Becoming_Steve_Jobs")
    assert result == []


def test_get_or_create_book_context():
    """Should perform JIT generation of macro book context and cache it, respecting human overrides."""
    from pipeline.map_reduce import get_or_create_book_context
    from core.config import cfg
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_path = Path(tmpdir) / "test_book_workspace"
        workspace_path.mkdir()
        
        # 1. Create initial _context.txt
        context_file = workspace_path / "_context.txt"
        context_file.write_text(
            "book_title: Test Book\n"
            "book_file: test_book.epub\n"
            "status: active\n",
            encoding="utf-8"
        )
        
        # 2. Create mock _toc.json
        toc_file = workspace_path / "_toc.json"
        toc_file.write_text(json.dumps({
            "book_title_vi": "Sách Thử Nghiệm",
            "chapters": [
                {
                    "chapter_num": 1, 
                    "title_vi": "Chương Một", 
                    "title_original": "Chapter One",
                    "page_start": 10,
                    "page_end": 20,
                    "description_vi": "Tóm tắt chương 1 rất hay."
                },
                {
                    "chapter_num": 2,
                    "title_vi": "Chương Hai",
                    "title_original": "Chapter Two",
                    "page_start": 21,
                    "page_end": None,
                    "description_vi": ""
                },
                {
                    "chapter_num": 3,
                    "title_vi": "Chương Ba",
                    "title_original": "Chapter Three",
                    "page_start": 35,
                    "page_end": 45,
                    "description_vi": "Mô tả chương 3."
                }
            ]
        }), encoding="utf-8")
        
        # Mock cfg.sources_dir and create source note
        mock_sources_dir = Path(tmpdir) / "sources"
        mock_sources_dir.mkdir()
        
        source_note = mock_sources_dir / "2026-05-21_test_book_workspace.md"
        source_note.write_text(
            "---\n"
            "title: Sách Thử Nghiệm\n"
            "summary: Đây là một cuốn sách test phục vụ unit test.\n"
            "---\n"
            "# Sách Thử Nghiệm\n",
            encoding="utf-8"
        )
        
        # Backup original sources_dir and bypass Frozen dataclass check using object.__setattr__
        orig_sources_dir = cfg.sources_dir
        object.__setattr__(cfg, "sources_dir", mock_sources_dir)
        
        try:
            # First call: Should generate JIT and cache
            xml_block = get_or_create_book_context(workspace_path)
            
            assert "<BOOK_CONTEXT>" in xml_block
            assert "Đây là một cuốn sách test phục vụ unit test." in xml_block
            assert "Mục 1: Chương Một (Chapter One) [Trang 10-20]" in xml_block
            assert "Tóm tắt chương 1 rất hay." in xml_block
            assert "Mục 2: Chương Hai (Chapter Two) [Trang 21-34]" in xml_block  # Auto-calculated from Chapter 3's page_start
            assert "(Thêm tóm tắt chương tại đây để LLM nắm ngữ cảnh phân tích)" in xml_block
            assert "Mục 3: Chương Ba (Chapter Three) [Trang 35-45]" in xml_block
            assert "Mô tả chương 3." in xml_block
            
            # Verify file was updated
            updated_content = context_file.read_text(encoding="utf-8")
            assert "book_title: Test Book" in updated_content
            assert "---" in updated_content
            assert "<BOOK_CONTEXT>" in updated_content
            
            # Modify the file context to simulate manual override
            manual_override = updated_content.replace(
                "Đây là một cuốn sách test phục vụ unit test.",
                "USER OVERRIDE SUMMARY!"
            )
            context_file.write_text(manual_override, encoding="utf-8")
            
            # Second call: Should read from cache and respect manual override
            xml_block_2 = get_or_create_book_context(workspace_path)
            assert "USER OVERRIDE SUMMARY!" in xml_block_2
            assert "Đây là một cuốn sách test" not in xml_block_2
            
        finally:
            # Restore original state
            object.__setattr__(cfg, "sources_dir", orig_sources_dir)
