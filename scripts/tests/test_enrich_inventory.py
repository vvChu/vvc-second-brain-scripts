"""Tests for Figure Inventory Context Enrichment Tool."""

import sys
import json
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import cfg
from tools.enrich_figure_inventory import _locate_context_in_book, enrich_inventory


@pytest.fixture
def mock_vault_dirs(tmp_path):
    """Fixture to mock config directories and prevent writing to real vault/inventory."""
    books_dir = tmp_path / "books"
    books_dir.mkdir(parents=True, exist_ok=True)

    # Save original values
    orig_books = cfg.resources_books_dir
    
    # Overwrite using object.__setattr__
    object.__setattr__(cfg, "resources_books_dir", books_dir)
    object.__setattr__(cfg, "vault_root", str(tmp_path))

    yield books_dir

    # Restore original values
    object.__setattr__(cfg, "resources_books_dir", orig_books)
    object.__setattr__(cfg, "vault_root", str(Path(cfg.resources_books_dir).parent.parent))


def test_locate_context_in_book(mock_vault_dirs):
    """Test locating context, chapter title, number, and surrounding text."""
    books_dir = mock_vault_dirs

    # Setup mock book MD corpus
    book_name = "Reinventing_the_Organization_H_Arthur_Yeung"
    book_md_dir = books_dir / f"{book_name}_MD"
    book_md_dir.mkdir(parents=True, exist_ok=True)

    # Mock chapter file
    chapter_content = """# Chapter 5: Morphology
    
Emerging models of organizations are very dynamic.
Line 2 of text.
Line 3 of text.
Line 4 of text.
Line 5 of text.
FIGURE 1-1
The Market-Oriented Ecosystem (MOE) model.
![[Reinventing_the_Organization_H_Ch05_Figure_01-01.jpg]]
Line 7 of text.
Line 8 of text.
Line 9 of text.
Line 10 of text.
Line 11 of text.
"""
    chapter_file = book_md_dir / "11_5_Morphology_How_Should_You_Be_Organized.md"
    chapter_file.write_text(chapter_content, encoding="utf-8")

    # Locate context
    context = _locate_context_in_book(book_name, "Reinventing_the_Organization_H_Ch05_Figure_01-01.jpg", books_dir=books_dir)
    
    assert context is not None
    assert context["chapter_file"] == "11_5_Morphology_How_Should_You_Be_Organized.md"
    assert context["chapter_title"] == "Chapter 5: Morphology"
    assert context["chapter_num"] == 11
    
    # Check context contains lines before and after
    assert "FIGURE 1-1" in context["surrounding_context"]
    assert "Line 9 of text." in context["surrounding_context"]


@patch("tools.enrich_figure_inventory.call_gateway_vision")
def test_enrich_inventory_flow(mock_vision, mock_vault_dirs, tmp_path):
    """Test full enrichment flow and incremental write back."""
    books_dir = mock_vault_dirs

    # Setup inventory path mock in tools module
    mock_inventory_path = tmp_path / "figure_inventory.json"
    
    inventory_data = {
        "total_figures": 1,
        "figures": [
            {
                "path": str(tmp_path / "test_fig.jpg"),
                "filename": "test_fig.jpg",
                "book": "TestBook",
                "topology": "hierarchy"
            }
        ],
        "summary": {"hierarchy": 1}
    }
    
    with open(mock_inventory_path, "w", encoding="utf-8") as f:
        json.dump(inventory_data, f, ensure_ascii=False, indent=2)

    # Setup book dir and chapter
    book_md_dir = books_dir / "TestBook_MD"
    book_md_dir.mkdir(parents=True, exist_ok=True)
    
    # Create the mock image file so path.exists() is true
    img_file = tmp_path / "test_fig.jpg"
    img_file.write_bytes(b"dummy image bytes")

    chapter_content = """# Chapter 1: Hierarchy
Some description.
![[test_fig.jpg]]
Some other text.
"""
    chapter_file = book_md_dir / "01_Ch1.md"
    chapter_file.write_text(chapter_content, encoding="utf-8")

    # Mock Vision LLM Response
    mock_vision.return_value = '{"caption": "Sơ đồ phân cấp", "alt_text": "Mô tả cấu trúc sơ đồ phân cấp RAG"}'

    # Run enrich_inventory
    with patch("tools.enrich_figure_inventory.INVENTORY_PATH", mock_inventory_path):
        enrich_inventory()

    # Load back the enriched inventory
    with open(mock_inventory_path, "r", encoding="utf-8") as f:
        enriched_data = json.load(f)

    enriched_fig = enriched_data["figures"][0]
    assert enriched_fig["chapter_file"] == "01_Ch1.md"
    assert enriched_fig["chapter_title"] == "Chapter 1: Hierarchy"
    assert enriched_fig["chapter_num"] == 1
    assert enriched_fig["caption"] == "Sơ đồ phân cấp"
    assert enriched_fig["alt_text"] == "Mô tả cấu trúc sơ đồ phân cấp RAG"
    assert "![[test_fig.jpg]]" in enriched_fig["surrounding_context"]
