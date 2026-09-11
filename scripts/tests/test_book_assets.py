"""Tests for pipeline/book_assets.py."""

import random
import sys
from pathlib import Path
from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import cfg
from pipeline.book_assets import (
    find_book_md_dir,
    is_decorative_image,
    shorten_chapter,
    compute_adaptive_asset_name,
    align_book_diagrams,
    build_chapter_diagrams_catalog,
)


def test_find_book_md_dir(tmp_path):
    """Test finding book MD directory."""
    books_dir = tmp_path / "books"
    books_dir.mkdir()

    # Create dummy MD dir
    (books_dir / "Atomic_Habits_MD").mkdir()
    (books_dir / "Other_Folder").mkdir()

    assert find_book_md_dir("Atomic_Habits", books_dir=books_dir) == books_dir / "Atomic_Habits_MD"
    assert find_book_md_dir("atomic habits", books_dir=books_dir) == books_dir / "Atomic_Habits_MD"
    assert find_book_md_dir("Non_Existent", books_dir=books_dir) is None
    assert find_book_md_dir("", books_dir=books_dir) is None


def test_is_decorative_image(tmp_path):
    """Test decorative image filter."""
    assert is_decorative_image("book_cover.jpg", tmp_path) is True
    assert is_decorative_image("logo_publisher.png", tmp_path) is True
    assert is_decorative_image("credits_page.jpg", tmp_path) is True
    assert is_decorative_image("nav_icon.png", tmp_path) is True
    assert is_decorative_image("decorative_border.png", tmp_path) is True

    # Size check (< 5KB)
    small_file = tmp_path / "small.png"
    small_file.write_bytes(b"0" * 3000)
    assert is_decorative_image("figure_1.png", small_file) is True

    large_file = tmp_path / "large.png"
    large_file.write_bytes(b"0" * 8000)
    assert is_decorative_image("figure_1.png", large_file) is False


def test_shorten_chapter():
    """Test chapter shortening logic."""
    assert shorten_chapter("[[Chương 14: Lãnh đạo]]") == "ch14"
    assert shorten_chapter("[[chapter_07_flow]]") == "ch07"
    assert shorten_chapter("ch_03") == "ch03"
    assert shorten_chapter("14_7_Performance_Accountability") == "14_7_performanc"
    assert shorten_chapter("") == ""


def test_compute_adaptive_asset_name():
    """Test adaptive naming for book diagram assets."""
    # Case 1: Image already contains book prefix words (>3 chars)
    name1 = compute_adaptive_asset_name(
        book_name="Thinking_Fast_And_Slow",
        chapter_stem="ch01",
        page="25",
        original_stem="Thinking_Fast_And_Slow_Figure_01",
    )
    assert name1 == "thinking_fast_and_slow_figure_01.webp"

    # Case 2: Generic image stem without book prefix
    name2 = compute_adaptive_asset_name(
        book_name="Thinking_Fast_And_Slow",
        chapter_stem="14_7_Performance_Accountability",
        page="198",
        original_stem="00042",
    )
    assert name2 == "thinking_fast_and_slow_14_7_performanc_p198_00042.webp"


def _create_noise_image(path: Path, fmt: str = "JPEG"):
    """Create a random noise image that is > 5KB."""
    img = PILImage.new("RGB", (200, 200))
    pixels = img.load()
    for x in range(200):
        for y in range(200):
            pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    img.save(path, fmt)


def test_align_book_diagrams(tmp_path):
    """Test aligning book diagrams into concept note content."""
    books_dir = tmp_path / "books"
    sources_dir = tmp_path / "sources"
    books_dir.mkdir(parents=True)
    sources_dir.mkdir(parents=True)

    orig_books = cfg.resources_books_dir
    orig_sources = cfg.sources_dir
    object.__setattr__(cfg, "resources_books_dir", books_dir)
    object.__setattr__(cfg, "sources_dir", sources_dir)

    try:
        book_name = "Leadership_Secrets"
        book_md = books_dir / f"{book_name}_MD"
        book_md.mkdir()

        fig_file = book_md / "Figure_3_Matrix.jpg"
        _create_noise_image(fig_file)

        ch_file = book_md / "03_Matrix_Chapter.md"
        ch_file.write_text(
            "# Chapter 3\n\nHere is the matrix:\n![[Figure_3_Matrix.jpg]]\n\nThe leaders utilize 4 quadrants.",
            encoding="utf-8",
        )

        note_content = """---
title: "Ma trận lãnh đạo"
ground_truth_chapter: "[[03_Matrix_Chapter]]"
source_page: "45"
---

## Core Idea
Phân tích ma trận.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)
> The leaders utilize 4 quadrants.

---
## References
- [[Leadership_Secrets]]
"""
        aligned = align_book_diagrams(note_content, book_name)

        expected_dest = "leadership_secrets_03_matrix_chapt_p45_figure_3_matrix.webp"
        assert f"![[{expected_dest}]]" in aligned
        assert aligned.index(f"![[{expected_dest}]]") < aligned.index("## 📖 Bản gốc")

        # Idempotence: align twice doesn't duplicate
        twice = align_book_diagrams(aligned, book_name)
        assert twice.count(f"![[{expected_dest}]]") == 1
    finally:
        object.__setattr__(cfg, "resources_books_dir", orig_books)
        object.__setattr__(cfg, "sources_dir", orig_sources)


def test_build_chapter_diagrams_catalog(tmp_path):
    """Test building chapter diagrams catalog XML with isolated inventory."""
    books_dir = tmp_path / "books"
    books_dir.mkdir(parents=True)

    orig_books = cfg.resources_books_dir
    object.__setattr__(cfg, "resources_books_dir", books_dir)

    inventory_path = tmp_path / "test_figure_inventory.json"

    try:
        book_name = "Leadership_Secrets"
        book_md = books_dir / f"{book_name}_MD"
        book_md.mkdir()

        fig_file = book_md / "Figure_3_Matrix.jpg"
        _create_noise_image(fig_file)

        ch_file = book_md / "03_Matrix_Chapter.md"
        ch_file.write_text(
            "# Chapter 3\n\n![[Figure_3_Matrix.jpg]]\n\nThe leaders utilize 4 quadrants.",
            encoding="utf-8",
        )

        def mock_vision(b64, prompt, timeout=None):
            return '{"caption": "Ma trận Lãnh đạo", "alt_text": "Chi tiết ma trận"}'

        xml = build_chapter_diagrams_catalog(
            book_name=book_name,
            chapter_stem="03_Matrix_Chapter",
            ground_truth_text="The leaders utilize 4 quadrants.",
            page="45",
            vision_caller=mock_vision,
            inventory_path=inventory_path,
        )
        assert "<CHAPTER_DIAGRAMS>" in xml
        assert "<FILENAME>Figure_3_Matrix.jpg</FILENAME>" in xml
        assert "<ADAPTIVE_NAME>leadership_secrets_03_matrix_chapt_p45_figure_3_matrix.webp</ADAPTIVE_NAME>" in xml
        assert "<CAPTION>Ma trận Lãnh đạo</CAPTION>" in xml
        assert inventory_path.exists()
    finally:
        object.__setattr__(cfg, "resources_books_dir", orig_books)
