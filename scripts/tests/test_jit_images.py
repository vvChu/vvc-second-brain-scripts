"""Tests for JIT Image Alignment stage (v8.12.0)."""

import sys
import shutil
import re
import random
from pathlib import Path
import pytest
from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import cfg
from pipeline.post_process import save_concept, _align_jit_images, _is_decorative_image


@pytest.fixture
def mock_vault_dirs(tmp_path):
    """Fixture to mock config directories to prevent writing to real vault."""
    # Create temporary directories
    books_dir = tmp_path / "books"
    sources_dir = tmp_path / "sources"
    concepts_dir = tmp_path / "concepts"
    archive_dir = tmp_path / "archive"

    books_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    concepts_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Save original values
    orig_books = cfg.resources_books_dir
    orig_sources = cfg.sources_dir
    orig_concepts = cfg.concepts_dir
    orig_archive = cfg.archive_dir

    # Overwrite using object.__setattr__ (bypasses frozen dataclass restrictions)
    object.__setattr__(cfg, "resources_books_dir", books_dir)
    object.__setattr__(cfg, "sources_dir", sources_dir)
    object.__setattr__(cfg, "concepts_dir", concepts_dir)
    object.__setattr__(cfg, "archive_dir", archive_dir)

    yield books_dir, sources_dir, concepts_dir, archive_dir

    # Restore original values
    object.__setattr__(cfg, "resources_books_dir", orig_books)
    object.__setattr__(cfg, "sources_dir", orig_sources)
    object.__setattr__(cfg, "concepts_dir", orig_concepts)
    object.__setattr__(cfg, "archive_dir", orig_archive)


def test_is_decorative_image(tmp_path):
    """Test decorative image detection."""
    # Test keyword matching
    assert _is_decorative_image("book_cover.jpg", tmp_path) is True
    assert _is_decorative_image("logo_vibe.png", tmp_path) is True
    assert _is_decorative_image("some_credits_page.png", tmp_path) is True
    
    # Test file size matching
    small_file = tmp_path / "small.jpg"
    small_file.write_bytes(b"\x00" * 4000)  # 4 KB
    assert _is_decorative_image("normal_fig.jpg", small_file) is True

    large_file = tmp_path / "large.jpg"
    large_file.write_bytes(b"\x00" * 8000)  # 8 KB
    assert _is_decorative_image("normal_fig.jpg", large_file) is False


def _create_noise_image(path: Path, fmt: str):
    """Create a random noise image that is guaranteed to be > 5KB when compressed."""
    img = PILImage.new("RGB", (200, 200))
    pixels = img.load()
    for x in range(200):
        for y in range(200):
            pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    img.save(path, fmt)


def test_align_jit_images_success(mock_vault_dirs):
    """Test successful JIT Image Alignment with Adaptive Naming."""
    books_dir, sources_dir, concepts_dir, archive_dir = mock_vault_dirs

    # Setup mock book MD corpus
    book_name = "Test_Book_Volume_1"
    book_md_dir = books_dir / f"{book_name}_MD"
    book_md_dir.mkdir(parents=True, exist_ok=True)

    # Create real valid noise images (guaranteed to be > 5KB)
    orig_img_name = "Test_Book_Volume_1_Ch14_Figure_07-01.jpg"
    orig_img_file = book_md_dir / orig_img_name
    _create_noise_image(orig_img_file, "JPEG")

    # Standard image file (generic name to test adaptive naming)
    generic_img_name = "00003.png"
    generic_img_file = book_md_dir / generic_img_name
    _create_noise_image(generic_img_file, "PNG")

    # Mock chapter file
    chapter_content = """# Chapter 14

This is a beautiful introduction to the performance accountability topic.

![[Test_Book_Volume_1_Ch14_Figure_07-01.jpg]]![[Test_Book_Volume_1_Ch14_Figure_07-01.jpg]]

Dave Ulrich and Arthur Yeung explain outcomes and behaviors:
In any positive conversation, clarity of expectations is vital. Figure 7-1 presents an outcome-behavior matrix that serves as a useful diagnostic tool for managers.

![[00003.png]]
"""
    chapter_file = book_md_dir / "14_7_Performance_Accountability.md"
    chapter_file.write_text(chapter_content, encoding="utf-8")

    # Mock concept note content
    concept_note = """---
title: "Ma trận Kết quả - Hành vi"
aliases:
  - "Outcome-Behavior Matrix"
tags:
  - knowledge
  - domain/organization
type: concept
ground_truth_chapter: "[[14_7_Performance_Accountability]]"
source_page: "198"
status: seed
---

> "Trong bất kỳ cuộc đối thoại tích cực nào, sự rõ ràng về kỳ vọng là điều tối quan trọng. Hình 7-1 trình bày ma trận kết quả - hành vi đóng vai trò là một công cụ chẩn đoán hữu ích cho các nhà quản lý."
> — **Dave Ulrich & Arthur Yeung**, trích dẫn trong sách *Reinventing the Organization* (Nguồn phụ, [[Test_Book_Volume_1|NXB Trẻ, 2026]])

## Core Idea

Đây là phân tích tiếng Việt sâu sắc về 4 góc phần tư của ma trận kết quả và hành vi.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> In any positive conversation, clarity of expectations is vital. Figure 7-1 presents an outcome-behavior matrix that serves as a useful diagnostic tool for managers.

---

## References
- [[Reinventing_the_Organization]]
"""

    # Run JIT Image Alignment helper
    aligned_content = _align_jit_images(concept_note, book_name)

    # 1. Assert image name is correctly resolved and embedded
    # "Test_Book_Volume_1_Ch14_Figure_07-01.jpg" should be copied to:
    # sources/assets/test_book_volume_1/test_book_volume_1_ch14_figure_07_01.webp
    # Generic "00003.png" should be renamed to:
    # sources/assets/test_book_volume_1/test_book_volume_1_14_7_performanc_p198_00003.webp
    expected_img1 = "test_book_volume_1_ch14_figure_07_01.webp"
    expected_img2 = "test_book_volume_1_14_7_performanc_p198_00003.webp"

    assert f"![[{expected_img1}]]" in aligned_content
    assert f"![[{expected_img2}]]" in aligned_content

    # 2. Check position of the embedded images (should be right before ## 📖 Bản gốc)
    assert aligned_content.index(f"![[{expected_img1}]]") < aligned_content.index("## 📖 Bản gốc")
    assert aligned_content.index(f"![[{expected_img2}]]") < aligned_content.index("## 📖 Bản gốc")

    # 3. Check assets created
    assets_dir = sources_dir / "assets" / "test_book_volume_1"
    assert assets_dir.exists()
    assert (assets_dir / expected_img1).exists()
    assert (assets_dir / expected_img2).exists()

    # 4. Check double run prevention (running again shouldn't duplicate embeds)
    twice_aligned = _align_jit_images(aligned_content, book_name)
    assert twice_aligned.count(f"![[{expected_img1}]]") == 1
    assert twice_aligned.count(f"![[{expected_img2}]]") == 1
