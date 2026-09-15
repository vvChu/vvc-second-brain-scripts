"""Compile AI-EOS Playbook 12 Chapters into a Single Master Manuscript."""

import re
import sys
from pathlib import Path

# Add scripts directory to sys.path
scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(scripts_dir))

from core.frontmatter import extract_body, parse_frontmatter

VAULT_ROOT = Path("D:/VvC_Notes")
TOPICS_DIR = VAULT_ROOT / "04 - Permanent" / "topics"
OUTPUT_FILE = TOPICS_DIR / "ai_eos_playbook_full_manuscript.md"

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

PARTS_TOC = """## 🗺️ Mục Lục Toàn Văn (Table of Contents)

### PHẦN I: BỐI CẢNH & CUỘC ĐẠI DỊCH CHUYỂN (The Paradigm Shift)
- **[[chuong_1_cai_chet_cua_kim_tu_thap_quan_tri_dinh_luat_conway_dao_nguoc|Chương 1: Cái Chết Của Kim Tự Tháp Quản Trị & Định Luật Conway Đảo Ngược]]**
- **[[chuong_2_tu_ung_dung_ai_be_mat_den_kien_truc_ai_native_doanh_nghiep_50_nguoi_mang_suc_manh_tap_doan|Chương 2: Từ "Ứng Dụng AI Bề Mặt" Đến "Kiến Trúc AI-Native": Doanh Nghiệp 50 Người Mang Sức Mạnh Tập Đoàn]]**

### PHẦN II: CẤU TRÚC HÌNH THÁI & HẠ TẦNG (Arthur Yeung & CCBA Platform)
- **[[chuong_3_khoi_nen_tang_platform_kien_truc_hub_and_spoke_lam_bo_nao_trung_tam|Chương 3: Khối Nền Tảng (Platform) & Kiến Trúc Hub-and-Spoke Làm Bộ Não Trung Tâm]]**
- **[[chuong_4_van_hanh_khoi_te_bao_cells_tu_tri_nguyen_tac_toi_thuong_reuse_first_gate|Chương 4: Khối Tế Bào (Cells) & Nguyên Tắc Tối Thượng Reuse-First Gate]]**
- **[[chuong_5_khoi_lien_minh_allies_tech_stack_va_bai_toan_build_vs_buy|Chương 5: Khối Liên Minh (Allies), Khung Lựa Chọn Tech Stack & Bài Toán Build vs Buy]]**

### PHẦN III: BỘ MÁY VẬN HÀNH & TRÁCH NHIỆM GIẢI TRÌNH (EOS Gino Wickman & CCBA WAY)
- **[[chuong_6_ban_dinh_huong_tam_nhin_ai_v_to_va_nhip_sinh_hoc_van_hanh_90_ngay|Chương 6: Bản Định Hướng Tầm Nhìn AI (AI-V/TO) & Nhịp Sinh Học Vận Hành 90 Ngày]]**
- **[[chuong_7_so_do_giai_trinh_moi_accountability_chart_ma_tran_role_id_ssot|Chương 7: Sơ Đồ Giải Trình Mới (Accountability Chart): Ma Trận 15 ROLE_ID SSOT Cho Người & AI]]**
- **[[chuong_8_chu_trinh_nghiep_vu_cot_loi_khep_kin_ccba_way|Chương 8: Chu Trình Nghiệp Vụ Cốt Lõi Khép Kín (CCBA WAY): CRM → HĐKT → Dự Án → Quyết Toán]]**

### PHẦN IV: VĂN HÓA, TỐC ĐỘ & BỘ LỌC TINH GIẢN (Google, NVIDIA, Musk & IDOP)
- **[[chuong_9_van_hoa_du_lieu_okrs_va_to_chuc_mang_no_ron_tren_ha_tang_cde|Chương 9: Văn Hóa Dữ Liệu, OKRs & Tổ Chức Dạng Mạng Nơ-ron Trên Hạ Tầng CDE (ISO 19650)]]**
- **[[chuong_10_luoi_dao_cao_tinh_gian_elon_musk_va_spec_driven_development|Chương 10: Lưỡi Dao Cạo Tinh Giản Elon Musk & Phương Pháp Spec-Driven Development]]**

### PHẦN V: BẢN ĐỒ TRIỂN KHAI & CASE STUDY THỰC NGHIỆM
- **[[chuong_11_case_study_toan_canh_ccba_way_va_idop|Chương 11: Case Study Toàn Cảnh: CCBA WAY & IDOP — Hành Trình Chuyển Mình Sang AI-Native]]**
- **[[chuong_12_lo_trinh_chuyen_doi_90_ngay_va_bo_bieu_mau_khung_thuc_chien|Chương 12: Lộ Trình Chuyển Đổi 90 Ngày (90-Day Roadmap) & Bộ Biểu Mẫu Khung Thực Chiến]]**
"""

MANUSCRIPT_FRONTMATTER = """---
title: "Toàn Văn Bản Thảo Cẩm Nang Vận Hành Doanh Nghiệp AI-Native (AI-EOS Playbook — Full Manuscript)"
aliases:
  - "AI-EOS Playbook Full Manuscript"
  - "Toàn Văn Bản Thảo AI-EOS Playbook"
  - "Bản Thảo Toàn Văn AI-EOS"
tags:
  - knowledge
  - domain/ai-engineering
  - domain/management
  - type/topic
type: topic
date_created: '2026-09-15'
date_modified: '2026-09-15'
source: compiled
source_type: compiled
summary: "Bản thảo toàn văn hợp nhất 12 chương của Cẩm nang Vận hành Doanh nghiệp AI-Native (AI-EOS Playbook): Tích hợp hoàn chỉnh triết lý Arthur Yeung (MOE), EOS Gino Wickman, Google, NVIDIA Jensen Huang, Elon Musk với Kiến trúc Hub-and-Spoke và Mô hình thực chứng CCBA WAY & IDOP."
people:
  - "Arthur Yeung"
  - "Dave Ulrich"
  - "Gino Wickman"
  - "Laszlo Bock"
  - "Jensen Huang"
  - "Elon Musk"
companies:
  - "CCBA"
  - "IBST"
  - "NVIDIA"
  - "Google"
  - "Amazon"
  - "Tesla"
status: evergreen
related:
  - "[[ai_eos_playbook_master]]"
  - "[[chuong_1_cai_chet_cua_kim_tu_thap_quan_tri_dinh_luat_conway_dao_nguoc]]"
  - "[[chuong_2_tu_ung_dung_ai_be_mat_den_kien_truc_ai_native_doanh_nghiep_50_nguoi_mang_suc_manh_tap_doan]]"
  - "[[chuong_3_khoi_nen_tang_platform_kien_truc_hub_and_spoke_lam_bo_nao_trung_tam]]"
  - "[[chuong_4_van_hanh_khoi_te_bao_cells_tu_tri_nguyen_tac_toi_thuong_reuse_first_gate]]"
  - "[[chuong_5_khoi_lien_minh_allies_tech_stack_va_bai_toan_build_vs_buy]]"
  - "[[chuong_6_ban_dinh_huong_tam_nhin_ai_v_to_va_nhip_sinh_hoc_van_hanh_90_ngay]]"
  - "[[chuong_7_so_do_giai_trinh_moi_accountability_chart_ma_tran_role_id_ssot]]"
  - "[[chuong_8_chu_trinh_nghiep_vu_cot_loi_khep_kin_ccba_way]]"
  - "[[chuong_9_van_hoa_du_lieu_okrs_va_to_chuc_mang_no_ron_tren_ha_tang_cde]]"
  - "[[chuong_10_luoi_dao_cao_tinh_gian_elon_musk_va_spec_driven_development]]"
  - "[[chuong_11_case_study_toan_canh_ccba_way_va_idop]]"
  - "[[chuong_12_lo_trinh_chuyen_doi_90_ngay_va_bo_bieu_mau_khung_thuc_chien]]"
confidence: high
---
"""

MANUSCRIPT_PROLOGUE = """# 📚 CẨM NANG VẬN HÀNH DOANH NGHIỆP AI-NATIVE (AI-EOS PLAYBOOK)
## TOÀN VĂN BẢN THẢO HỢP NHẤT 12 CHƯƠNG (COMPREHENSIVE MASTER MANUSCRIPT)

> *"Đừng số hóa mô hình kim tự tháp cũ kỹ. Hãy tái kiến trúc doanh nghiệp thành một mạng lưới tế bào tự trị được trang bị bệ phóng AI dùng chung."*

---

> [!abstract] 📌 Giới Thiệu Chuyên Luận
> Cuốn cẩm nang này là bản thiết kế kiến trúc toàn diện (Architectural Master Blueprint) hợp nhất tri thức quản trị hiện đại và công nghệ tác tử AI (AI Agents). 
> Bản thảo toàn văn này tập hợp đầy đủ 12 chương chuyên luận, bảo lưu nguyên vẹn toàn bộ hệ thống sơ đồ kiến trúc (Mermaid, Excalidraw), bảng đặc tả ma trận, và trích dẫn kiểm chứng.
> Bản đồ điều phối các chương độc lập: [[ai_eos_playbook_master|AI-EOS Playbook Master]].

---
"""


def compile_manuscript():
    sections = [MANUSCRIPT_FRONTMATTER.strip(), MANUSCRIPT_PROLOGUE.strip(), PARTS_TOC.strip()]

    total_words = 0
    total_chars = 0

    for i, slug in enumerate(CHAPTER_SLUGS, 1):
        ch_path = TOPICS_DIR / f"{slug}.md"
        if not ch_path.exists():
            print(f"ERROR: Missing chapter file {ch_path}")
            continue

        raw_text = ch_path.read_text(encoding="utf-8")
        body = extract_body(raw_text).strip()
        chars = len(body)
        words = len(body.split())
        total_chars += chars
        total_words += words

        sections.append(f"\n\n---\n\n<!-- CHAPTER {i} START -->\n\n{body}\n\n<!-- CHAPTER {i} END -->\n")

    full_manuscript = "\n\n".join(sections)
    OUTPUT_FILE.write_text(full_manuscript, encoding="utf-8")
    print(f"Master manuscript generated successfully: {OUTPUT_FILE.name}")
    print(f"Total Chapters: {len(CHAPTER_SLUGS)}")
    print(f"Total Words: {total_words:,} words")
    print(f"Total Characters: {total_chars:,} characters")
    print(f"File Size: {OUTPUT_FILE.stat().st_size:,} bytes")


if __name__ == "__main__":
    compile_manuscript()
