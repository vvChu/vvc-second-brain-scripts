"""Tests for AI-EOS Playbook Chapters, Hero Images, Master Manuscript, and Showcase."""

import re
import sys
from pathlib import Path
import pytest
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.frontmatter import parse_frontmatter, extract_body
from wiki_maintain import _build_master_index
from core.config import cfg

VAULT_ROOT = Path("D:/VvC_Notes")
TOPICS_DIR = VAULT_ROOT / "04 - Permanent" / "topics"
ATTACHMENTS_DIR = VAULT_ROOT / "03 - Resources" / "attachments"
INDEX_FILE = VAULT_ROOT / "00 - Maps of Content" / "index.md"
MANUSCRIPT_FILE = TOPICS_DIR / "ai_eos_playbook_full_manuscript.md"
MASTER_FILE = TOPICS_DIR / "ai_eos_playbook_master.md"

CHAPTER_SLUGS = [
    "chuong_1_cai_chet_cua_kim_tu_thap_quan_tri_dinh_luat_conway_dao_nguoc",
    "chuong_2_tu_ung_dung_ai_be_mat_den_kien_truc_ai_native_doanh_nghiep_50_nguoi_mang_suc_manh_tap_doan",
    "chuong_3_khoi_nen_tang_platform_kien_truc_hub_and_spoke_lam_bo_nao_trung_tam",
    "chuong_4_van_hanh_khoi_te_bao_cells_tu_tri_nguyen_tac_toi_thuong_reuse_first_gate",
    "chuong_5_khoi_lien_minh_allies_tech_stack_va_bai_toan_build_vs_buy",
    "chuong_6_ban_dinh_huong_tam_nhin_ai_v_to_va_nhip_sinh_hoc_van_hanh_90_ngay",
    "chuong_7_so_do_giai_trinh_moi_accountability_chart_ma_tran_role_id_ssot",
    "chuong_8_chu_trinh_nghiep_vu_cot_loi_khep_kin_ccba_way",
    "chuong_9_van_hoa_du_lieu_okrs_va_to_chuc_mang_no_ron_tren_ha_tang_cde",
    "chuong_10_luoi_dao_cao_tinh_gian_elon_musk_va_spec_driven_development",
    "chuong_11_case_study_toan_canh_ccba_way_va_idop",
    "chuong_12_lo_trinh_chuyen_doi_90_ngay_va_bo_bieu_mau_khung_thuc_chien",
]


def test_ai_eos_chapters_exist_and_structured():
    """Verify all 12 chapters exist with proper frontmatter, H1, and hero embeds."""
    for i, slug in enumerate(CHAPTER_SLUGS, 1):
        ch_path = TOPICS_DIR / f"{slug}.md"
        assert ch_path.exists(), f"Missing chapter {i}: {slug}.md"

        text = ch_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        assert fm, f"Chapter {i} frontmatter is empty: {slug}.md"
        assert fm.get("type") == "topic", f"Chapter {i} type must be 'topic'"
        assert "title" in fm, f"Chapter {i} missing title"

        # Check H1
        h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        assert h1_match, f"Chapter {i} missing H1 header"

        # Check hero image embed right after H1
        after_h1 = text[h1_match.end():h1_match.end() + 300]
        expected_img = f"{slug}_hero.jpg|100%"
        assert f"![[{expected_img}]]" in after_h1, f"Chapter {i} missing hero embed ![[{expected_img}]]"


def test_ai_eos_hero_images_in_attachments():
    """Verify all 12 hero images exist as valid 16:9 JPEGs in attachments."""
    for i, slug in enumerate(CHAPTER_SLUGS, 1):
        img_name = f"{slug}_hero.jpg"
        img_path = ATTACHMENTS_DIR / img_name
        assert img_path.exists(), f"Missing hero image for chapter {i}: {img_name}"

        # Check file size (> 100 KB)
        size_kb = img_path.stat().st_size / 1024
        assert size_kb > 100, f"Image {img_name} too small: {size_kb:.1f} KB"

        # Check image validity and aspect ratio
        with Image.open(img_path) as im:
            assert im.format == "JPEG"
            w, h = im.size
            ratio = w / h
            # Aspect ratio 16:9 is ~1.78
            assert 1.6 <= ratio <= 1.9, f"Image {img_name} ratio {ratio:.2f} not 16:9"


def test_ai_eos_master_manuscript():
    """Verify Master Manuscript compilation integrity, frontmatter, and chapter concatenation."""
    assert MANUSCRIPT_FILE.exists(), "Master manuscript file missing"
    m_text = MANUSCRIPT_FILE.read_text(encoding="utf-8")

    # Verify frontmatter parses cleanly with standard yaml safe loader
    fm = parse_frontmatter(m_text)
    assert fm, "Manuscript frontmatter could not be parsed"
    assert "Toàn Văn Bản Thảo" in fm.get("title", "")
    assert fm.get("type") == "topic"
    assert fm.get("status") == "evergreen"

    # Verify all 12 chapters are concatenated
    for i, slug in enumerate(CHAPTER_SLUGS, 1):
        assert f"<!-- CHAPTER {i} START -->" in m_text, f"Manuscript missing Chapter {i} marker"
        assert f"{slug}_hero.jpg" in m_text, f"Manuscript missing hero image for Chapter {i}"

    # Verify NO redundant individual frontmatters inside chapter bodies
    # Ensure there's no dangling --- right after chapter start markers
    for i in range(1, 13):
        start_idx = m_text.find(f"<!-- CHAPTER {i} START -->")
        end_idx = m_text.find(f"<!-- CHAPTER {i} END -->", start_idx)
        ch_slice = m_text[start_idx:end_idx]
        # Shouldn't contain frontmatter headers like "title: " or "source: "
        assert "tags:\n  - knowledge" not in ch_slice, f"Chapter {i} still has redundant frontmatter in manuscript!"

    # Verify TOC has navigation anchors
    assert '<span id="muc-luc-toan-van"></span>' in m_text
    assert "## 🗺️ Mục Lục Toàn Văn (Table of Contents)" in m_text
    for i in range(1, 13):
        assert f'<span id="chuong-{i}"></span>' in m_text


def test_ai_eos_master_index_showcase():
    """Verify Master Index has Flagship Playbooks showcase and wiki_maintain preserves it."""
    assert INDEX_FILE.exists(), "index.md missing"
    idx_content = INDEX_FILE.read_text(encoding="utf-8")

    # Check showcase callout in index.md
    assert "> [!quote]+ 🌟 Kiệt Tác Chuyên Luận (Flagship Playbooks)" in idx_content
    assert "[[ai_eos_playbook_master" in idx_content
    assert "[[ai_eos_playbook_full_manuscript" in idx_content

    # Check that wiki_maintain._build_master_index generates this callout
    from wiki_maintain import _build_master_index
    import inspect
    source_code = inspect.getsource(_build_master_index)
    assert "Kiệt Tác Chuyên Luận (Flagship Playbooks)" in source_code


def test_ai_eos_playbook_bidirectional_linking():
    """Verify master playbook and full manuscript link to each other."""
    assert MASTER_FILE.exists()
    assert MANUSCRIPT_FILE.exists()

    master_text = MASTER_FILE.read_text(encoding="utf-8")
    manuscript_text = MANUSCRIPT_FILE.read_text(encoding="utf-8")

    assert "[[ai_eos_playbook_full_manuscript" in master_text
    assert "[[ai_eos_playbook_master" in manuscript_text
