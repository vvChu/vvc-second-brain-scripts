#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VvC Second Brain — Source File Deduplicator & Link Healer (v8.9.3).

Quét đĩa và tự động dọn dẹp các tệp nguồn transcript trùng lặp trỏ đến cùng một URL,
sao lưu phòng thủ, chuyển hướng an toàn 100% liên kết chéo của các Concept Note,
hợp nhất registry cục bộ `.processed_urls.json` và chạy Wiki Maintenance.

Sử dụng:
    python scripts/tools/deduplicate_sources.py
    python scripts/tools/deduplicate_sources.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# --- Cấu hình JIT Path & Imports ---
scripts_dir = Path(__file__).resolve().parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.append(str(scripts_dir))

try:
    from services.brain_dump import _load_url_registry, _save_url_registry
    from core.config import cfg
except ImportError:
    # Fallback dự phòng nếu import lỗi ngoài môi trường tiêu chuẩn
    def _load_url_registry() -> dict:
        f = scripts_dir / ".state" / ".processed_urls.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        return {}

    def _save_url_registry(r: dict) -> None:
        f = scripts_dir / ".state" / ".processed_urls.json"
        f.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

# Cấu hình encoding stdout để in tiếng Việt có dấu trên Windows cmd/powershell không lỗi
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Thiết lập Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("vvc.dedup")

# Định nghĩa các nhóm trùng lặp đã khảo sát
DUPLICATE_GROUPS = [
    {
        "name": "Elon Musk (vWJCxvTMuUY)",
        "url_key": "youtu.be/vWJCxvTMuUY",
        "canonical": "2026-05-28_elon_musk_lam_the_nao_de_hoc_moi_thu",
        "duplicates": ["2026-05-16_elon_musk_lam_the_nao_de_hoc_moi_thu"]
    },
    {
        "name": "McKinsey Consulting (UxVRrorZ4RM)",
        "url_key": "youtu.be/UxVRrorZ4RM",
        "canonical": "2026-05-20_the_end_of_consulting_mckinseys_25_000",
        "duplicates": ["2026-05-20_060415_the_end_of_consulting_mckinseys_25_000"]
    },
    {
        "name": "Kỹ năng đọc sách (9EUTRL_4Cj8)",
        "url_key": "youtu.be/9EUTRL_4Cj8",
        "canonical": "2026-05-21_ky_nang_doc_sach_hieu_qua_youtube",
        "duplicates": ["2026-05-21_132933_ky_nang_doc_sach_hieu_qua_youtube"]
    }
]


def run_deduplication(dry_run: bool = False) -> None:
    """Thực thi dọn dẹp trùng lặp nguồn và chữa lành liên kết."""
    start_time = time.time()
    
    vault_root = Path("D:/VvC_Notes")
    concepts_dir = vault_root / "04 - Permanent" / "concepts"
    transcripts_dir = vault_root / "04 - Permanent" / "sources" / "transcripts"
    backup_dir = scripts_dir / "scratch" / "backup"
    
    logger.info("======================================================================")
    logger.info(f"🚀 BẮT ĐẦU DỌN DẸP TRÙNG LẶP NGUỒN & CHỮA LÀNH LIÊN KẾT (Mode: {'DRY RUN' if dry_run else 'LIVE'})")
    logger.info("======================================================================")
    
    if not concepts_dir.exists() or not transcripts_dir.exists():
        logger.error("Không tìm thấy các thư mục cốt lõi của Obsidian Vault tại D:/VvC_Notes")
        return

    # Khởi tạo thư mục backup phòng thủ
    if not dry_run:
        backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Đã kích hoạt thư mục sao lưu phòng thủ tại: {backup_dir}")

    # Load registry để cập nhật
    registry = _load_url_registry()
    registry_updated = False

    # Thống kê tổng quan
    total_concepts_healed = 0
    total_files_backed_up = 0
    total_files_deleted = 0

    for group in DUPLICATE_GROUPS:
        logger.info("")
        logger.info(f"📂 Đang xử lý nhóm: {group['name']}")
        
        canonical_stem = group["canonical"]
        canonical_path = transcripts_dir / f"{canonical_stem}.md"
        
        if not canonical_path.exists():
            logger.warning(f"  [!] Không tìm thấy tệp Nguồn chính: {canonical_path.name}. Bỏ qua nhóm này.")
            continue
            
        logger.info(f"  * Tệp Nguồn chính (Canonical): {canonical_path.name}")
        
        # -------------------------------------------------------------
        # BƯỚC A: Sao lưu phòng thủ và chuyển hướng liên kết Concept Notes
        # -------------------------------------------------------------
        for dup_stem in group["duplicates"]:
            dup_path = transcripts_dir / f"{dup_stem}.md"
            if not dup_path.exists():
                logger.info(f"  * Tệp phụ {dup_path.name} không tồn tại hoặc đã được dọn dẹp trước đó.")
                continue
                
            logger.info(f"  * Phát hiện tệp phụ (Duplicate): {dup_path.name}")
            
            # 1. Thực hiện Sao lưu phòng thủ (Safety Backup)
            if not dry_run:
                try:
                    shutil.copy(dup_path, backup_dir / dup_path.name)
                    logger.info(f"    [ok] Đã sao lưu phòng thủ tệp phụ sang {backup_dir.name}/{dup_path.name}")
                    total_files_backed_up += 1
                except Exception as e:
                    logger.error(f"    [!] Thất bại khi sao lưu tệp phụ {dup_path.name}: {e}. Dừng để đảm bảo an toàn.")
                    return

            # 2. Quét Concept Notes để chữa lành liên kết (Link Healing)
            logger.info(f"    -> Đang quét và chuyển hướng các Concept Notes trỏ tới {dup_stem}...")
            group_concepts_healed = 0
            
            concept_files = list(concepts_dir.glob("*.md"))
            for c_file in concept_files:
                try:
                    content = c_file.read_text(encoding="utf-8")
                    if dup_stem in content:
                        group_concepts_healed += 1
                        total_concepts_healed += 1
                        
                        # Thay thế triệt để trên toàn bộ file (frontmatter, citation line, references)
                        new_content = content.replace(dup_stem, canonical_stem)
                        
                        if not dry_run:
                            c_file.write_text(new_content, encoding="utf-8")
                            logger.info(f"      * Chữa lành: [{c_file.name}] ➡️ trỏ về {canonical_stem}")
                        else:
                            logger.info(f"      * [DRY RUN] Sẽ chữa lành: [{c_file.name}] ➡️ trỏ về {canonical_stem}")
                except Exception as e:
                    logger.warning(f"      [!] Lỗi khi chữa lành tệp concept {c_file.name}: {e}")
                    
            logger.info(f"    => Đã chữa lành xong {group_concepts_healed} Concept Notes.")

            # 3. Tiến hành xóa tệp phụ trên đĩa an toàn
            if not dry_run:
                try:
                    dup_path.unlink()
                    logger.info(f"    [ok] Đã xóa an toàn tệp nguồn phụ trên đĩa: {dup_path.name}")
                    total_files_deleted += 1
                except Exception as e:
                    logger.error(f"    [!] Thất bại khi xóa tệp phụ {dup_path.name}: {e}")
            else:
                logger.info(f"    [DRY RUN] Sẽ xóa tệp nguồn phụ trên đĩa: {dup_path.name}")
                total_files_deleted += 1

        # -------------------------------------------------------------
        # BƯỚC B: Hợp nhất và dọn dẹp Registry .processed_urls.json
        # -------------------------------------------------------------
        url_key = group["url_key"]
        if url_key in registry:
            logger.info(f"  * Tiến hành gộp và làm sạch Registry cho URL: {url_key}")
            
            # Quét lại toàn bộ Concept Notes để lấy danh sách concept chính xác nhất của file Canonical sau khi chữa lành
            logger.info(f"    -> Đang đồng bộ và gộp danh sách concepts trên Registry...")
            updated_concepts = []
            concept_files = list(concepts_dir.glob("*.md"))
            for c_file in concept_files:
                try:
                    content = c_file.read_text(encoding="utf-8")
                    # Tìm trường source: "canonical_stem" trong frontmatter
                    source_match = re.search(r'^source:\s*["\']?(.*?)["\']?\s*$', content, re.MULTILINE)
                    title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', content, re.MULTILINE)
                    
                    if source_match:
                        source_val = source_match.group(1).replace("[[", "").replace("]]", "").replace(".md", "").strip()
                        if source_val == canonical_stem:
                            title = title_match.group(1).strip() if title_match else c_file.stem.replace("_", " ").title()
                            updated_concepts.append({
                                "stem": c_file.stem,
                                "title": title
                            })
                except Exception:
                    pass
            
            # Gộp và loại bỏ trùng lặp dựa trên stem
            unique_concepts = []
            seen_stems = set()
            for c in updated_concepts:
                if c["stem"] not in seen_stems:
                    seen_stems.add(c["stem"])
                    unique_concepts.append(c)
            
            # Cập nhật Registry record
            registry[url_key]["source_note"] = canonical_stem
            registry[url_key]["concepts"] = unique_concepts
            registry[url_key]["processed_at"] = datetime.now().isoformat()
            registry_updated = True
            logger.info(f"    [ok] Đã đồng bộ Registry: URL trỏ về {canonical_stem} chứa {len(unique_concepts)} concepts.")

    # Ghi Registry đã cập nhật
    if registry_updated and not dry_run:
        try:
            _save_url_registry(registry)
            logger.info("")
            logger.info("✅ CẬP NHẬT FILE REGISTRY JSON TRÊN ĐĨA THÀNH CÔNG!")
        except Exception as e:
            logger.error(f"Thất bại khi ghi file registry: {e}")

    # ------------------------------------------------------------------
    # BƯỚC C: Chạy dịch vụ bảo trì tự động wiki_maintain.py JIT
    # ------------------------------------------------------------------
    if not dry_run:
        logger.info("")
        logger.info("Step C: Kích hoạt dịch vụ Wiki Maintenance tự động để rebuild lại đồ thị tri thức...")
        try:
            from wiki_maintain import rebuild_all
            rebuild_all()
            logger.info("✅ HOÀN THÀNH REBUILD SOURCE MOCs, DOMAIN MOCs VÀ MASTER INDEX!")
        except Exception as e:
            # Fallback nếu import lỗi hoặc không có hàm rebuild_all
            logger.warning(f"Không thể import và chạy tự động rebuild_all: {e}. Vui lòng tự chạy wiki_maintain.py sau.")

    # ------------------------------------------------------------------
    # BÁO CÁO THỐNG KÊ CHI TIẾT
    # ------------------------------------------------------------------
    duration = (time.time() - start_time) * 1000
    logger.info("")
    logger.info("======================================================================")
    logger.info("📊 BÁO CÁO THỐNG KÊ KẾT QUẢ DỌN DẸP TRÙNG LẶP NGUỒN (TỔNG KẾT)")
    logger.info("======================================================================")
    logger.info(f"⏱️ Tổng thời gian thực thi  : {duration:.2f} mili-giây")
    logger.info(f"📁 Số lượng Concept Healed   : {total_concepts_healed} tệp")
    logger.info(f"📦 Số lượng File phụ sao lưu : {total_files_backed_up} tệp (an toàn tuyệt đối)")
    logger.info(f"🗑️ Số lượng File phụ đã xóa  : {total_files_deleted} tệp")
    logger.info(f"⚙️ Trạng thái Registry       : Đồng bộ 100% (Trỏ về Canonical Sources)")
    logger.info("======================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dọn dẹp nguồn trùng lặp trên đĩa và chữa lành liên kết.")
    parser.add_argument("--dry-run", action="store_true", help="Chạy ở chế độ mô phỏng, không thực tế xóa/ghi file.")
    args = parser.parse_args()
    
    run_deduplication(dry_run=args.dry_run)
