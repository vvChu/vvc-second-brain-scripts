import re
import sys
from pathlib import Path
import yaml
from PIL import Image

# Add scripts directory to sys.path
scripts_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(scripts_dir))

from core.config import cfg

VAULT_ROOT = Path(cfg.vault_root)
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

def audit():
    print("=== AUDIT START ===")
    issues = []

    # 1. Check Images in Attachments
    print("\n--- 1. Hero Images in Attachments ---")
    for i, slug in enumerate(CHAPTER_SLUGS, 1):
        img_name = f"{slug}_hero.jpg"
        img_path = ATTACHMENTS_DIR / img_name
        if not img_path.exists():
            issues.append(f"Image missing: {img_name}")
            print(f"[-] Missing: {img_name}")
            continue
        try:
            with Image.open(img_path) as im:
                w, h = im.size
                ratio = w / h if h else 0
                size_kb = img_path.stat().st_size / 1024
                print(f"[+] Ch{i:02d}: {img_name} ({w}x{h}, ratio={ratio:.2f}, {size_kb:.1f} KB, format={im.format})")
                if ratio < 1.6 or ratio > 1.9:
                    issues.append(f"Ch{i:02d} image ratio not 16:9: {w}x{h} ({ratio:.2f})")
        except Exception as e:
            issues.append(f"Ch{i:02d} image error: {e}")
            print(f"[-] Error opening {img_name}: {e}")

    # 2. Check 12 Chapters in Topics
    print("\n--- 2. Chapters Markdown Files ---")
    for i, slug in enumerate(CHAPTER_SLUGS, 1):
        ch_path = TOPICS_DIR / f"{slug}.md"
        if not ch_path.exists():
            issues.append(f"Chapter file missing: {slug}.md")
            print(f"[-] Missing: {slug}.md")
            continue
        text = ch_path.read_text(encoding="utf-8")
        
        # Check frontmatter
        fm_match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n", text, re.DOTALL)
        if not fm_match:
            issues.append(f"{slug}.md missing frontmatter")
            print(f"[-] {slug}.md missing frontmatter")
        else:
            try:
                fm = yaml.safe_load(fm_match.group(1))
            except Exception as e:
                issues.append(f"{slug}.md frontmatter parse error: {e}")
                print(f"[-] {slug}.md frontmatter error: {e}")

        # Check H1
        h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if not h1_match:
            issues.append(f"{slug}.md missing H1")
            print(f"[-] {slug}.md missing H1")
        else:
            h1 = h1_match.group(1).strip()
            # Check hero embed right after H1
            after_h1 = text[h1_match.end():h1_match.end()+300]
            embed_match = re.search(r"!\[\[(.*?)\]\]", after_h1)
            if not embed_match:
                issues.append(f"{slug}.md missing hero image embed after H1")
                print(f"[-] {slug}.md missing hero embed after H1: {h1[:40]}")
            else:
                embed_target = embed_match.group(1)
                expected_target = f"{slug}_hero.jpg|100%"
                if embed_target != expected_target:
                    print(f"[?] {slug}.md embed target is '{embed_target}', expected '{expected_target}'")
                else:
                    print(f"[+] {slug}.md embed OK: {embed_target}")

        # Check for HTML entity leakage outside mermaid: #40; or #41;
        non_mermaid_parts = re.split(r"```mermaid.*?```", text, flags=re.DOTALL)
        for part_idx, part in enumerate(non_mermaid_parts):
            if "#40;" in part or "#41;" in part:
                issues.append(f"{slug}.md has leaked #40; or #41; outside mermaid!")
                print(f"[-] {slug}.md has leaked #40; or #41; outside mermaid in section {part_idx}!")

        # Check for backticks around wikilinks
        code_pill_links = re.findall(r"`\[\[.*?\]\]`", text)
        if code_pill_links:
            issues.append(f"{slug}.md has {len(code_pill_links)} code-pill wikilinks: {code_pill_links[:3]}")
            print(f"[-] {slug}.md code-pill wikilinks found: {code_pill_links[:3]}")

    # 3. Check Master Manuscript
    print("\n--- 3. Master Manuscript File ---")
    if not MANUSCRIPT_FILE.exists():
        issues.append("Master manuscript missing!")
        print("[-] Master manuscript missing!")
    else:
        m_text = MANUSCRIPT_FILE.read_text(encoding="utf-8")
        print(f"[+] Manuscript size: {len(m_text):,} chars, {len(m_text.split()):,} words")
        
        # Frontmatter
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", m_text, re.DOTALL)
        if not fm_match:
            issues.append("Manuscript missing frontmatter")
        else:
            try:
                fm = yaml.safe_load(fm_match.group(1))
                print(f"[+] Manuscript frontmatter valid: title='{fm.get('title')}'")
            except Exception as e:
                issues.append(f"Manuscript frontmatter error: {e}")

        # Check all 12 chapters are present
        for i, slug in enumerate(CHAPTER_SLUGS, 1):
            if f"<!-- CHAPTER {i} START -->" not in m_text:
                issues.append(f"Manuscript missing CHAPTER {i} START comment")
            expected_img = f"{slug}_hero.jpg"
            if expected_img not in m_text:
                issues.append(f"Manuscript missing hero image for Ch{i}: {expected_img}")
            else:
                print(f"[+] Manuscript contains Ch{i} hero image: {expected_img}")

        # Check Mermaid blocks in manuscript
        mermaid_blocks = re.findall(r"```mermaid(.*?)```", m_text, re.DOTALL)
        print(f"[+] Manuscript contains {len(mermaid_blocks)} Mermaid blocks")
        for idx, block in enumerate(mermaid_blocks, 1):
            # Check edge label syntax
            chimeric_edges = re.findall(r"(?:={3,}|-\.{1,}-)<*\"[^\"]+\">*(?:={3,}|-\.{1,}-)>", block)
            if chimeric_edges:
                issues.append(f"Manuscript Mermaid block {idx} has chimeric edge: {chimeric_edges}")
            if re.search(r"(?<![<=-])>=|(?<![<=-])<=(?![=>-])", block):
                issues.append(f"Manuscript Mermaid block {idx} has raw >= or <= operators")

        # Check HTML entity leakage outside mermaid
        non_mermaid_m = re.split(r"```mermaid.*?```", m_text, flags=re.DOTALL)
        for part_idx, part in enumerate(non_mermaid_m):
            if "#40;" in part or "#41;" in part:
                issues.append(f"Manuscript has leaked #40; or #41; outside mermaid in section {part_idx}!")
                print(f"[-] Manuscript has leaked #40; or #41; outside mermaid!")

        # Check code pills
        m_code_pills = re.findall(r"`\[\[.*?\]\]`", m_text)
        if m_code_pills:
            issues.append(f"Manuscript has {len(m_code_pills)} code-pill wikilinks: {m_code_pills[:3]}")

        # Check Excalidraw embeds
        excalidraw_embeds = re.findall(r"!\[\[(.*?.excalidraw\.md)(?:\|.*?)?\]\]", m_text)
        print(f"[+] Manuscript contains {len(excalidraw_embeds)} Excalidraw embeds: {excalidraw_embeds}")
        for exc in excalidraw_embeds:
            exc_path = ATTACHMENTS_DIR / exc
            if not exc_path.exists():
                exc_path_top = TOPICS_DIR / exc
                if not exc_path_top.exists():
                    issues.append(f"Excalidraw file missing: {exc}")
                    print(f"[-] Missing Excalidraw: {exc}")
                else:
                    print(f"[+] Excalidraw in topics: {exc}")
            else:
                print(f"[+] Excalidraw in attachments: {exc}")

        # Check TOC links in manuscript
        print("\n--- Checking Manuscript TOC Navigation ---")
        toc_match = re.search(r"## 🗺️ Mục Lục Toàn Văn.*?(?=\n---|\n<!-- CHAPTER 1 START -->)", m_text, re.DOTALL)
        if toc_match:
            toc_content = toc_match.group(0)
            print("[+] Found TOC content")
            links = re.findall(r"\[\[(.*?)\]\]", toc_content)
            print(f"[+] TOC links ({len(links)}): {links}")

    # 4. Check index.md & wiki_maintain.py
    print("\n--- 4. Master Index & Maintenance ---")
    if not INDEX_FILE.exists():
        issues.append("index.md missing!")
    else:
        idx_text = INDEX_FILE.read_text(encoding="utf-8")
        if "Kiệt Tác Chuyên Luận (Flagship Playbooks)" in idx_text:
            print("[+] index.md has Flagship Playbooks showcase")
        else:
            issues.append("index.md MISSING Flagship Playbooks showcase!")
            print("[-] index.md MISSING Flagship Playbooks showcase!")

    # Check wiki_maintain.py
    wm_path = VAULT_ROOT / "scripts" / "wiki_maintain.py"
    wm_text = wm_path.read_text(encoding="utf-8")
    if "Kiệt Tác Chuyên Luận" in wm_text:
        print("[+] wiki_maintain.py preserves Flagship Playbooks showcase")
    else:
        issues.append("wiki_maintain.py does NOT generate/preserve Flagship Playbooks showcase! Running wiki_maintain will destroy it!")
        print("[-] wiki_maintain.py will overwrite and destroy the Flagship Playbooks showcase!")

    # 5. Check Master file
    print("\n--- 5. Master Playbook File ---")
    if not MASTER_FILE.exists():
        issues.append("ai_eos_playbook_master.md missing!")
    else:
        mf_text = MASTER_FILE.read_text(encoding="utf-8")
        if "ai_eos_playbook_full_manuscript" in mf_text:
            print("[+] Master file links to full manuscript")
        else:
            issues.append("Master file does NOT link to full manuscript")

    print("\n=== AUDIT SUMMARY ===")
    print(f"Total issues found: {len(issues)}")
    for issue in issues:
        print(f" - {issue}")

if __name__ == "__main__":
    audit()
