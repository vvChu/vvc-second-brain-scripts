"""VvC Second Brain — Test Fixtures (v7.0)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_llm():
    """Mock call_llm to avoid actual API calls."""
    with patch("core.llm.call_llm") as mock:
        mock.return_value = "Mocked LLM response"
        yield mock


@pytest.fixture
def mock_vision():
    """Mock call_vision to avoid actual API calls."""
    with patch("core.llm.call_vision") as mock:
        mock.return_value = "PAGE: 42\n\n[HIGHLIGHTED]\nTest highlighted text\n\n[CONTEXT]\nTest context"
        yield mock


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault structure for testing."""
    # Create directory structure
    (tmp_path / "04 - Permanent" / "concepts").mkdir(parents=True)
    (tmp_path / "04 - Permanent" / "sources").mkdir(parents=True)
    (tmp_path / "05 - Fleeting" / "Test_Book").mkdir(parents=True)
    (tmp_path / "03 - Resources" / "books" / "Test_Book_MD").mkdir(parents=True)
    (tmp_path / "00 - Maps of Content").mkdir(parents=True)
    (tmp_path / "99 - Archive").mkdir(parents=True)

    # Create a sample book corpus
    corpus_dir = tmp_path / "03 - Resources" / "books" / "Test_Book_MD"
    (corpus_dir / "01_CHAPTER_1.md").write_text(
        "# Chapter 1\n\n"
        "This is a test paragraph about transformer architecture. "
        "The attention mechanism allows the model to focus on relevant parts "
        "of the input sequence. Self-attention computes relationships between "
        "all positions in a sequence simultaneously.\n\n"
        "Another paragraph about neural networks and deep learning approaches "
        "to natural language processing and understanding.",
        encoding="utf-8",
    )

    # Create a sample concept note (v8.3 canonical format)
    concept_path = tmp_path / "04 - Permanent" / "concepts" / "test_concept.md"
    concept_path.write_text(
        "---\n"
        "title: Test Concept\n"
        "aliases: []\n"
        "tags:\n"
        "  - knowledge\n"
        "  - type/concept\n"
        "  - domain/ai\n"
        "type: concept\n"
        "date_created: 2026-05-12\n"
        "date_modified: 2026-05-12\n"
        "source: test_book\n"
        "source_page: \"42\"\n"
        "source_chapter: \"[[Chương 1]]\"\n"
        "ground_truth_page: \"42\"\n"
        "ground_truth_chapter: \"[[Chapter 1]]\"\n"
        "source_type: image\n"
        "summary: Test concept summary\n"
        "people: []\n"
        "companies: []\n"
        "status: seed\n"
        "related:\n"
        "  - '[[other_concept]]'\n"
        "confidence: high\n"
        "---\n\n"
        "> \"Test highlighted quote bằng tiếng Việt.\"\n"
        "> — **Test Author**, trích dẫn trong *Test Book* ([[test_book|Test Book, 2026]])\n\n"
        "## Core Idea\n\n"
        "Analysis paragraph.\n\n"
        "## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)\n\n"
        "> \"Original English quote from test book.\"\n\n"
        "---\n\n"
        "## References\n\n"
        "- [[test_book]]\n",
        encoding="utf-8",
    )

    # Create TOC (canonical schema v8.0)
    import json
    toc = {
        "book_title_vi": "Test Book",
        "book_title_original": "Test Book",
        "chapters": [
            {
                "chapter_num": 1,
                "title_vi": "Chapter 1",
                "title_original": "Chapter 1",
                "description_vi": None,
                "epub_file": "01_CHAPTER_1.md",
                "page_start": 1,
                "page_end": 50,
            },
        ],
    }
    (tmp_path / "05 - Fleeting" / "Test_Book" / "_toc.json").write_text(
        json.dumps(toc, ensure_ascii=False), encoding="utf-8"
    )

    return tmp_path
