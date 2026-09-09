"""Tests for pipeline.ground_truth module."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_resolve_chapter_with_toc(tmp_vault):
    """Should resolve chapter from page number using _toc.json."""
    with patch("core.config.cfg") as mock_cfg:
        mock_cfg.fleeting_dir = tmp_vault / "05 - Fleeting"
        mock_cfg.resources_books_dir = tmp_vault / "03 - Resources" / "books"

        from pipeline.ground_truth import resolve_chapter

        result = resolve_chapter(25, "Test_Book")
        assert "01_CHAPTER_1.md" in result


def test_resolve_chapter_no_toc(tmp_vault):
    """Should return empty list when no _toc.json exists."""
    with patch("core.config.cfg") as mock_cfg:
        mock_cfg.fleeting_dir = tmp_vault / "05 - Fleeting"

        from pipeline.ground_truth import resolve_chapter

        result = resolve_chapter(25, "Nonexistent_Book")
        assert result == []


def test_resolve_chapter_no_page(tmp_vault):
    """Should return empty list when page is None."""
    from pipeline.ground_truth import resolve_chapter

    result = resolve_chapter(None, "Test_Book")
    assert result == []


def test_bm25_search_finds_relevant():
    """BM25 should find relevant paragraphs."""
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        pytest.skip("rank_bm25 not available")

    from pipeline.ground_truth import _bm25_search

    corpus = [
        ("ch1", "The transformer architecture uses self-attention mechanism for parallel processing"),
        ("ch2", "Cooking recipes require fresh ingredients and proper seasoning"),
        ("ch3", "Machine learning models learn from data through gradient descent"),
    ]

    results = _bm25_search("transformer attention mechanism", corpus, top_k=2)
    assert len(results) > 0
    assert results[0][0] == "ch1"


def test_bm25_search_empty_corpus():
    """BM25 should handle empty corpus."""
    from pipeline.ground_truth import _bm25_search

    results = _bm25_search("test query", [], top_k=3)
    assert results == []


def test_correct_ocr_passthrough(mock_llm):
    """Should return original text if no Ground Truth."""
    from pipeline.ground_truth import correct_ocr

    result = correct_ocr("Test OCR text", "")
    assert result == "Test OCR text"


def test_correct_ocr_empty_input(mock_llm):
    """Should handle empty inputs."""
    from pipeline.ground_truth import correct_ocr

    assert correct_ocr("", "some GT") == ""


def test_match_chapter_file():
    """Should match chapter number to file using various patterns."""
    from pipeline.ground_truth import _match_chapter_file
    from pathlib import Path
    
    md_files = [
        Path("01_Copyright.md"),
        Path("02_Contents.md"),
        Path("07_Chapter_1_Steve.md"),
        Path("08_Chapter_2_Business.md"),
        Path("09_Ch_3_Breakthrough.md"),
        Path("10_Ch04_Whats_Next.md"),
    ]
    
    assert _match_chapter_file(1, md_files).name == "07_Chapter_1_Steve.md"
    assert _match_chapter_file(2, md_files).name == "08_Chapter_2_Business.md"
    assert _match_chapter_file(3, md_files).name == "09_Ch_3_Breakthrough.md"
    assert _match_chapter_file(4, md_files).name == "10_Ch04_Whats_Next.md"
    
    # Non-existent chapter
    assert _match_chapter_file(5, md_files) is None


def test_resolve_chapter_auto_mapping(tmp_path):
    """Should dynamically calculate page_end and fuzzy map chapter files if khuyết epub_file."""
    # Setup test workspace
    fleeting_dir = tmp_path / "05 - Fleeting" / "Test_Book"
    fleeting_dir.mkdir(parents=True, exist_ok=True)
    
    books_dir = tmp_path / "03 - Resources" / "books" / "Test_Book_MD"
    books_dir.mkdir(parents=True, exist_ok=True)
    
    # Create MD chapter files
    (books_dir / "07_Chapter_1_Steve.md").write_text("Ch 1 content", encoding="utf-8")
    (books_dir / "08_Chapter_2_Business.md").write_text("Ch 2 content", encoding="utf-8")
    
    # Create _toc.json WITHOUT epub_file and WITHOUT page_end
    toc = {
        "book_title_vi": "Test Book",
        "chapters": [
            {"chapter_num": 1, "title_vi": "Chương 1", "page_start": 1},
            {"chapter_num": 2, "title_vi": "Chương 2", "page_start": 50},
        ],
    }
    
    import json
    (fleeting_dir / "_toc.json").write_text(json.dumps(toc, ensure_ascii=False), encoding="utf-8")
    
    with patch("pipeline.ground_truth.cfg") as mock_cfg:
        mock_cfg.fleeting_dir = tmp_path / "05 - Fleeting"
        mock_cfg.resources_books_dir = tmp_path / "03 - Resources" / "books"
        
        from pipeline.ground_truth import resolve_chapter
        
        # Test dynamic page_end calculation: page 30 must fall into Chapter 1 (page_start: 1, dynamic page_end: 49)
        res1 = resolve_chapter(30, "Test_Book")
        assert len(res1) == 1
        assert res1[0] == "07_Chapter_1_Steve.md"
        
        # page 60 must fall into Chapter 2 (page_start: 50, dynamic page_end: 9999)
        res2 = resolve_chapter(60, "Test_Book")
        assert len(res2) == 1
        assert res2[0] == "08_Chapter_2_Business.md"


def test_is_vietnamese():
    """Should correctly identify Vietnamese text."""
    from pipeline.ground_truth import _is_vietnamese
    
    assert _is_vietnamese("Đây là văn bản tiếng Việt có dấu") is True
    assert _is_vietnamese("Tiếng Việt vô cùng phong phú") is True
    assert _is_vietnamese("This is a pure English text.") is False
    assert _is_vietnamese("Transformer models are cool.") is False
    assert _is_vietnamese("") is False


def test_find_ground_truth_vietnamese_corpus():
    """Should detect Vietnamese corpus and bypass English JIT query translation."""
    from pipeline.ground_truth import find_ground_truth
    
    vietnamese_corpus = [
        ("ch1", "Quy trình xây dựng hệ điều hành doanh nghiệp thành công bao gồm sáu thành phần cốt lõi."),
        ("ch2", "Thành phần thứ nhất là Tầm nhìn, giúp toàn bộ tổ chức đồng lòng hướng về một tương lai chung."),
        ("ch3", "Hãy đo lường các chỉ số quan trọng hàng tuần để kiểm soát hiệu suất hoạt động."),
    ]
    
    with patch("pipeline.ground_truth._load_corpus", return_value=vietnamese_corpus), \
         patch("pipeline.ground_truth.resolve_chapter", return_value=["ch2"]), \
         patch("pipeline.ground_truth._bm25_search", return_value=[("ch2", vietnamese_corpus[1][1], 25.0)]), \
         patch("pipeline.ground_truth._translate_query_to_english") as mock_translate:
         
        ocr_query = "Thành phần thứ nhất là Tầm nhìn, giúp toàn bộ tổ chức đồng lòng hướng về một tương lai chung."
        
        result = find_ground_truth(ocr_query, "Gino_Book", page=12)
        
        # JIT translate should not be called since corpus is detected as Vietnamese
        mock_translate.assert_not_called()
        assert result.chapter == "ch2"
        assert "Tầm nhìn" in result.paragraph


def test_find_ground_truth_static_language_toc(tmp_path):
    """Should bypass JIT paragraph sampling when static language in _toc.json is 'vi'."""
    fleeting_dir = tmp_path / "05 - Fleeting" / "Gino_Book"
    fleeting_dir.mkdir(parents=True, exist_ok=True)
    
    # Create mock _toc.json with static language "vi"
    toc = {
        "book_title_vi": "Test Book",
        "language": "vi",
        "chapters": [
            {"chapter_num": 1, "title_vi": "Chương 1", "page_start": 1, "page_end": 50, "epub_file": "01_ch1.md"}
        ]
    }
    
    import json
    (fleeting_dir / "_toc.json").write_text(json.dumps(toc, ensure_ascii=False), encoding="utf-8")
    
    from pipeline.ground_truth import find_ground_truth
    
    dummy_corpus = [
        ("01_ch1", "Some dummy text in English or Vietnamese.")
    ]
    
    with patch("pipeline.ground_truth.cfg") as mock_cfg, \
         patch("pipeline.ground_truth._load_corpus", return_value=dummy_corpus), \
         patch("pipeline.ground_truth.resolve_chapter", return_value=["01_ch1.md"]), \
         patch("pipeline.ground_truth._bm25_search", return_value=[("01_ch1", dummy_corpus[0][1], 25.0)]), \
         patch("pipeline.ground_truth._translate_query_to_english") as mock_translate:
         
        mock_cfg.fleeting_dir = tmp_path / "05 - Fleeting"
        mock_cfg.resources_books_dir = tmp_path / "03 - Resources" / "books"
        
        ocr_query = "Thành phần thứ nhất"
        result = find_ground_truth(ocr_query, "Gino_Book", page=12)
        
        # JIT translate should NOT be called since static language in _toc.json is 'vi'
        mock_translate.assert_not_called()
        assert result.chapter == "01_ch1"


def test_find_images_around_ground_truth_basic():
    """Verify basic image finding with exact paragraph match and deduplication."""
    from pipeline.ground_truth import find_images_around_ground_truth

    chapter_text = """# Chapter 1
Introduction to systems thinking.

![[system_diagram_01.png]]

A feedback loop is a circuit of cause-and-effect relationship where information about the system is fed back.

![[feedback_loop.jpg]]
Some other trailing text here.
"""
    gt_text = "A feedback loop is a circuit of cause-and-effect relationship where information about the system is fed back."
    images = find_images_around_ground_truth(chapter_text, gt_text, window_radius=200)
    assert images == ["system_diagram_01.png", "feedback_loop.jpg"]


def test_find_images_around_ground_truth_multi_paragraph_and_formats():
    """Verify scanning across multiple paragraphs, blockquotes, and Markdown image syntax."""
    from pipeline.ground_truth import find_images_around_ground_truth

    chapter_text = """# Chapter 5

First main concept discussion.
![[first_concept.webp]]
This is the first substantive paragraph detailing how elements connect in complex networks.

Middle section with no images.

![Architecture](diagrams/arch_overview.png)
Second key discussion covers the overarching architectural patterns for high-reliability systems.
![[second_concept.webp]]
"""
    # Ground truth formatted with Markdown blockquotes
    gt_text = """> This is the first substantive paragraph detailing how elements connect in complex networks.
>
> Second key discussion covers the overarching architectural patterns for high-reliability systems."""

    images = find_images_around_ground_truth(chapter_text, gt_text, window_radius=300)
    assert "first_concept.webp" in images
    assert "diagrams/arch_overview.png" in images
    assert "second_concept.webp" in images
    assert len(images) == 3


def test_find_images_around_ground_truth_prefix_middle_fallback():
    """Verify prefix and middle fallback matching for long paragraphs."""
    from pipeline.ground_truth import find_images_around_ground_truth

    # Chapter text has different ending
    chapter_text = """# Section 3
![[prefix_matched.png]]
This is an extraordinarily detailed paragraph that is well over one hundred and fifty characters in length and begins with a very specific prefix that matches perfectly but diverges slightly at the very end of the sentence.
"""
    gt_text = "This is an extraordinarily detailed paragraph that is well over one hundred and fifty characters in length and begins with a very specific prefix that matches perfectly but has some OCR error here at the end."

    images = find_images_around_ground_truth(chapter_text, gt_text, window_radius=200)
    assert images == ["prefix_matched.png"]


def test_find_images_around_ground_truth_edge_cases():
    """Verify behavior on empty inputs, out of radius images, and no matches."""
    from pipeline.ground_truth import find_images_around_ground_truth

    # Empty inputs
    assert find_images_around_ground_truth("", "some text") == []
    assert find_images_around_ground_truth("some text", "") == []
    assert find_images_around_ground_truth("", "") == []

    # Image outside radius
    padding = "x" * 1500
    chapter_text = f"![[far_away.png]]{padding}Target paragraph content for testing window limits.{padding}"
    gt_text = "Target paragraph content for testing window limits."
    assert find_images_around_ground_truth(chapter_text, gt_text, window_radius=300) == []
    assert find_images_around_ground_truth(chapter_text, gt_text, window_radius=2000) == ["far_away.png"]

    # No match
    assert find_images_around_ground_truth("![[foo.png]] Completely different text.", "Unrelated search query text.") == []


def test_find_images_around_ground_truth_quotes_newlines_and_callouts():
    """Verify ground truth with surrounding quotes, wrapped newlines, and callouts."""
    from pipeline.ground_truth import find_images_around_ground_truth

    # 1. Quoted ground truth against unquoted book text
    chapter_text = """# Chapter 1
![[model_flow.png]]
A feedback loop is a circuit of cause-and-effect relationship where information about the system is fed back.
"""
    gt_quoted = '> "A feedback loop is a circuit of cause-and-effect relationship where information about the system is fed back."'
    assert find_images_around_ground_truth(chapter_text, gt_quoted, window_radius=200) == ["model_flow.png"]

    # 2. Wrapped newlines inside chapter text (e.g. hard wrapped EPUB/Markdown)
    chapter_wrapped = """# Chapter 2
![[wrapped_diagram.webp]]
A feedback loop is a circuit of cause-and-effect
relationship where information about the system is fed back.
"""
    assert find_images_around_ground_truth(chapter_wrapped, gt_quoted, window_radius=200) == ["wrapped_diagram.webp"]

    # 3. Ground truth with Obsidian callout headers and citation lines
    gt_with_callout = """> [!quote] Ground Truth
> "A feedback loop is a circuit of cause-and-effect relationship where information about the system is fed back."
> — **Donella Meadows**, trích dẫn trong sách *Thinking in Systems*
"""
    assert find_images_around_ground_truth(chapter_text, gt_with_callout, window_radius=200) == ["model_flow.png"]

