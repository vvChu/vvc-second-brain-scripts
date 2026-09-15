"""Build AI-EOS Playbook Hero Images and embed them beneath H1 in Chapters 2-12."""

import re
import sys
from pathlib import Path

# Add scripts directory to sys.path
scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(scripts_dir))

from core.config import cfg
from services.command.hero_image import generate_hero_image, embed_hero_image_in_topic

VAULT_ROOT = Path("D:/VvC_Notes")
TOPICS_DIR = VAULT_ROOT / "04 - Permanent" / "topics"
ATTACHMENTS_DIR = VAULT_ROOT / "03 - Resources" / "attachments"

HERO_SPECS = [
    {
        "chapter": 2,
        "slug": "chuong_2_tu_ung_dung_ai_be_mat_den_kien_truc_ai_native_doanh_nghiep_50_nguoi_mang_suc_manh_tap_doan",
        "prompt": (
            "Cinematic 16:9 wide-angle visual metaphor of a high-tech corporate architecture. "
            "A compact, elite group of 50 glowing architectural monoliths and figures standing at the center of an expansive, "
            "interconnected corporate network, commanding the scale and reach of an immense enterprise. "
            "Luminous neural conduits, sleek dark slate glass surfaces, volumetric golden-amber and cool cyan rim lighting. "
            "Minimalist architectural render, dramatic depth of field, high-concept visualization, no text, no logos."
        ),
    },
    {
        "chapter": 3,
        "slug": "chuong_3_khoi_nen_tang_platform_kien_truc_hub_and_spoke_lam_bo_nao_trung_tam",
        "prompt": (
            "Cinematic 16:9 wide shot of a futuristic central hub-and-spoke enterprise architecture. "
            "A monolithic obsidian central platform pulsating with soft neural intelligence, radiating crystalline data buses "
            "and synchronized energy bridges to satellite modular pods orbiting symmetrically. "
            "Moody architectural atmosphere, deep navy and graphite environment, sharp volumetric backlighting, "
            "clean geometric minimalism, premium editorial aesthetic, no text, no typography."
        ),
    },
    {
        "chapter": 4,
        "slug": "chuong_4_van_hanh_khoi_te_bao_cells_tu_tri_nguyen_tac_toi_thuong_reuse_first_gate",
        "prompt": (
            "Cinematic 16:9 architectural rendering of autonomous cellular micro-teams. "
            "Distinct, floating hexagonal architectural cells operating independently, passing through a magnificent, "
            "glowing golden filtration portal representing a Reuse-First verification gate. "
            "Modular cubic components linking seamlessly, pristine reflections on dark polished stone floor, "
            "subtle volumetric mist, dramatic contrast, elegant academic composition, no words, no text."
        ),
    },
    {
        "chapter": 5,
        "slug": "chuong_5_khoi_lien_minh_allies_tech_stack_va_bai_toan_build_vs_buy",
        "prompt": (
            "Cinematic 16:9 wide conceptual visualization of strategic tech alliance and build versus buy balance. "
            "An elegant architectural bridge spanning across two technological realms, linking custom internal monolithic structures "
            "with external modular cloud ecosystems. A balanced kinetic sculpture of interlocking geometric forms in equilibrium. "
            "Atmospheric twilight lighting, deep bronze and slate-blue hues, cinematic depth of field, ultra-clean aesthetic, no text."
        ),
    },
    {
        "chapter": 6,
        "slug": "chuong_6_ban_dinh_huong_tam_nhin_ai_v_to_va_nhip_sinh_hoc_van_hanh_90_ngay",
        "prompt": (
            "Cinematic 16:9 visual metaphor of enterprise vision and 90-day operational rhythm. "
            "A monumental dual-horizon architectural installation: a sweeping panoramic telescope aligned toward a distant radiant North Star, "
            "anchored by a synchronized, rhythmic quarterly chronometer mechanism etched into obsidian stone. "
            "Volumetric morning light cutting through deep shadows, warm amber and dark charcoal palette, grand corporate vision, no text."
        ),
    },
    {
        "chapter": 7,
        "slug": "chuong_7_so_do_giai_trinh_moi_accountability_chart_ma_tran_role_id_ssot",
        "prompt": (
            "Cinematic 16:9 wide shot of an enterprise accountability matrix. "
            "Fifteen crystalline pedestal monoliths arranged in a precise, harmonious grid, each crowned with a distinct "
            "glowing geometric sigil representing unified human-AI roles. Single source of truth glowing crystal in the center. "
            "Dramatic architectural lighting, deep midnight blue and titanium reflections, meticulous symmetrical composition, no text, no labels."
        ),
    },
    {
        "chapter": 8,
        "slug": "chuong_8_chu_trinh_nghiep_vu_cot_loi_khep_kin_ccba_way",
        "prompt": (
            "Cinematic 16:9 visualization of an unbroken closed-loop business cycle. "
            "An expansive, glowing architectural infinity loop composed of four seamlessly transitioning segments: "
            "client intake, legal agreement, engineering execution, and final financial settlement. "
            "Liquid light and crystalline data streams flowing continuously without friction, dark graphite minimalist landscape, "
            "rich emerald and cyan highlights, sophisticated corporate elegance, no text."
        ),
    },
    {
        "chapter": 9,
        "slug": "chuong_9_van_hoa_du_lieu_okrs_va_to_chuc_mang_no_ron_tren_ha_tang_cde",
        "prompt": (
            "Cinematic 16:9 wide architectural view of a neural enterprise organization. "
            "A vast, pristine Common Data Environment foundation supporting an intricate floating network of transparent neural nodes and aligned OKR vectors. "
            "Holographic structural blueprints hovering in ambient space, cool ice-blue and white rim lighting, "
            "translucent glass layers, deep perspective, ISO 19650 precision engineering feel, no text, no typography."
        ),
    },
    {
        "chapter": 10,
        "slug": "chuong_10_luoi_dao_cao_tinh_gian_elon_musk_va_spec_driven_development",
        "prompt": (
            "Cinematic 16:9 conceptual visual metaphor of radical simplification and spec-driven engineering. "
            "A razor-sharp beam of focused golden laser light slicing through a chaotic tangle of obsolete bureaucratic machinery, "
            "revealing an immaculate, ultra-pure titanium turbine engine designed from first principles. "
            "Extreme contrast of deep shadow and brilliant warm cutting light, industrial brutalist elegance, high-concept render, no text."
        ),
    },
    {
        "chapter": 11,
        "slug": "chuong_11_case_study_toan_canh_ccba_way_va_idop",
        "prompt": (
            "Cinematic 16:9 panoramic transformation narrative of modern engineering consulting. "
            "Split visual metaphor showing the metamorphosis from traditional paper drafting rooms on the left "
            "into an illuminated, hyper-modern AI-integrated command center on the right with holographic structural models. "
            "Atmospheric lighting transition from sepia warmth to crisp architectural cyan, grand editorial storytelling, no text."
        ),
    },
    {
        "chapter": 12,
        "slug": "chuong_12_lo_trinh_chuyen_doi_90_ngay_va_bo_bieu_mau_khung_thuc_chien",
        "prompt": (
            "Cinematic 16:9 wide shot of a 90-day transformation roadmap and operational battle-tested templates. "
            "A grand architectural progression of three ascending illuminated terraces leading toward an open horizon at dawn. "
            "Crystalline modular frameworks and structured foundation blocks perfectly aligned in perspective. "
            "Subtle morning gold and deep steel-blue sky, uplifting strategic horizon, editorial architectural photography, no text."
        ),
    },
]


def run():
    print(f"Starting Hero Image Generation for {len(HERO_SPECS)} chapters...")
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

    success_count = 0
    for item in HERO_SPECS:
        ch_num = item["chapter"]
        slug = item["slug"]
        prompt = item["prompt"]
        img_name = f"{slug}_hero.jpg"
        img_path = ATTACHMENTS_DIR / img_name
        note_path = TOPICS_DIR / f"{slug}.md"

        print(f"\n--- Chapter {ch_num}: {slug[:30]}... ---")
        if not img_path.exists():
            print(f"Generating image: {img_name}...")
            ok = generate_hero_image(prompt, img_path)
            if ok:
                print(f"-> SUCCESS: Generated {img_name} ({img_path.stat().st_size} bytes)")
            else:
                print(f"-> FAILED: Could not generate {img_name}")
                continue
        else:
            print(f"-> Image already exists: {img_name} ({img_path.stat().st_size} bytes)")

        # Embed into topic note
        if note_path.exists():
            content = note_path.read_text(encoding="utf-8")
            if f"![[{img_name}" not in content:
                updated = embed_hero_image_in_topic(content, img_name)
                note_path.write_text(updated, encoding="utf-8")
                print(f"-> EMBEDDED into {note_path.name}")
            else:
                print(f"-> Already embedded in {note_path.name}")
            success_count += 1
        else:
            print(f"-> WARNING: Topic note not found: {note_path}")

    print(f"\nCompleted: {success_count}/{len(HERO_SPECS)} chapters updated with hero images.")


if __name__ == "__main__":
    run()
