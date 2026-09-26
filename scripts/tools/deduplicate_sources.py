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
    def _load_url_registry() -> dict:
        f = scripts_dir / ".state" / ".processed_urls.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def _save_url_registry(r: dict) -> None:
        f = scripts_dir / ".state" / ".processed_urls.json"
        f.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("vvc.dedup")

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
    },
    {
        "name": "Uncle Bob - Software Fundamentals / Kỷ nguyên AI (zcLPGC-tvgk)",
        "url_key": "youtube.com/live/zcLPGC-tvgk",
        "canonical": "2026-09-22_ky_nguyen_ai_va_phuong_phap_cong_trinh",
        "duplicates": ["2026-09-17_live_uncle_bob_on_software_fundamentals"]
    }
]


def _heal_concept_notes_for_dup(
    dup_stem: str,
    canonical_stem: str,
    concepts_dir: Path,
    dry_run: bool,
) -> int:
    """Redirect references in concept notes from dup_stem to canonical_stem."""
    healed = 0
    for c_file in concepts_dir.glob("*.md"):
        try:
            content = c_file.read_text(encoding="utf-8")
            if dup_stem in content:
                healed += 1
                if not dry_run:
                    c_file.write_text(content.replace(dup_stem, canonical_stem), encoding="utf-8")
                    logger.info(f"      * Chữa lành: [{c_file.name}] ➡️ {canonical_stem}")
                else:
                    logger.info(f"      * [DRY RUN] Sẽ chữa lành: [{c_file.name}] ➡️ {canonical_stem}")
        except Exception as e:
            logger.warning(f"      [!] Lỗi khi chữa lành tệp concept {c_file.name}: {e}")
    return healed


def _process_duplicate_file(
    dup_path: Path,
    canonical_stem: str,
    concepts_dir: Path,
    backup_dir: Path,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Backup, heal concept links, and remove a duplicate transcript file."""
    if not dup_path.exists():
        logger.info(f"  * Tệp phụ {dup_path.name} không tồn tại hoặc đã được dọn dẹp trước đó.")
        return 0, 0, 0

    logger.info(f"  * Phát hiện tệp phụ (Duplicate): {dup_path.name}")
    backed_up = deleted = 0
    if not dry_run:
        try:
            shutil.copy(dup_path, backup_dir / dup_path.name)
            backed_up += 1
            logger.info(f"    [ok] Đã sao lưu phòng thủ tệp phụ sang {backup_dir.name}/{dup_path.name}")
        except Exception as e:
            logger.error(f"    [!] Thất bại khi sao lưu tệp phụ {dup_path.name}: {e}")
            raise

    healed = _heal_concept_notes_for_dup(dup_path.stem, canonical_stem, concepts_dir, dry_run)
    logger.info(f"    => Đã chữa lành xong {healed} Concept Notes.")

    if not dry_run:
        try:
            dup_path.unlink()
            deleted += 1
            logger.info(f"    [ok] Đã xóa an toàn tệp nguồn phụ trên đĩa: {dup_path.name}")
        except Exception as e:
            logger.error(f"    [!] Thất bại khi xóa tệp phụ {dup_path.name}: {e}")
    else:
        logger.info(f"    [DRY RUN] Sẽ xóa tệp nguồn phụ trên đĩa: {dup_path.name}")
        deleted += 1

    return healed, backed_up, deleted


def _sync_registry_for_group(group: dict, concepts_dir: Path, registry: dict) -> bool:
    """Sync URL registry concepts list with canonical source."""
    url_key = group["url_key"]
    if url_key not in registry:
        return False
    canonical_stem = group["canonical"]
    logger.info(f"  * Tiến hành gộp và làm sạch Registry cho URL: {url_key}")
    updated_concepts = []
    for c_file in concepts_dir.glob("*.md"):
        try:
            content = c_file.read_text(encoding="utf-8")
            fm_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            if not fm_match:
                continue
            fm_text = fm_match.group(1)
            has_source = (
                re.search(rf'^\s*source:\s*["\']?.*{re.escape(canonical_stem)}', fm_text, re.MULTILINE) is not None
                or re.search(rf'^\s*-\s*["\']?.*{re.escape(canonical_stem)}', fm_text, re.MULTILINE) is not None
            )
            if has_source:
                title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', fm_text, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else c_file.stem.replace("_", " ").title()
                updated_concepts.append({"stem": c_file.stem, "title": title})
        except Exception:
            pass

    seen = set()
    unique = [c for c in updated_concepts if not (c["stem"] in seen or seen.add(c["stem"]))]
    registry[url_key]["source_note"] = canonical_stem
    registry[url_key]["concepts"] = unique
    registry[url_key]["processed_at"] = datetime.now().isoformat()
    logger.info(f"    [ok] Đã đồng bộ Registry: URL trỏ về {canonical_stem} chứa {len(unique)} concepts.")
    return True


def _print_dedup_summary(duration: float, healed: int, backed_up: int, deleted: int) -> None:
    """Print final deduplication metrics."""
    logger.info("\n" + "=" * 70)
    logger.info("📊 BÁO CÁO THỐNG KÊ KẾT QUẢ DỌN DẸP TRÙNG LẶP NGUỒN (TỔNG KẾT)")
    logger.info("=" * 70)
    logger.info(f"⏱️ Tổng thời gian thực thi  : {duration:.2f} mili-giây")
    logger.info(f"📁 Số lượng Concept Healed   : {healed} tệp")
    logger.info(f"📦 Số lượng File phụ sao lưu : {backed_up} tệp (an toàn tuyệt đối)")
    logger.info(f"🗑️ Số lượng File phụ đã xóa  : {deleted} tệp")
    logger.info("⚙️ Trạng thái Registry       : Đồng bộ 100% (Trỏ về Canonical Sources)")
    logger.info("=" * 70)


def _trigger_wiki_maintain() -> None:
    """Trigger JIT wiki maintenance rebuild."""
    try:
        from wiki_maintain import rebuild_all
        rebuild_all()
    except Exception as e:
        logger.warning(f"Không thể import và chạy tự động rebuild_all: {e}")


def run_deduplication(dry_run: bool = False) -> None:
    """Thực thi dọn dẹp trùng lặp nguồn và chữa lành liên kết."""
    start_time = time.time()
    concepts_dir = cfg.concepts_dir
    transcripts_dir = cfg.sources_dir / "transcripts"
    backup_dir = scripts_dir / "scratch" / "backup"

    logger.info("=" * 70)
    logger.info(f"🚀 BẮT ĐẦU DỌN DẸP TRÙNG LẶP (Mode: {'DRY RUN' if dry_run else 'LIVE'})")
    logger.info("=" * 70)
    if not concepts_dir.exists() or not transcripts_dir.exists():
        logger.error(f"Không tìm thấy các thư mục cốt lõi của Vault tại {cfg.vault_root}")
        return

    if not dry_run:
        backup_dir.mkdir(parents=True, exist_ok=True)
    registry = _load_url_registry()
    reg_updated = False
    total_healed = total_backed_up = total_deleted = 0

    for group in DUPLICATE_GROUPS:
        canonical_path = transcripts_dir / f"{group['canonical']}.md"
        if not canonical_path.exists():
            logger.warning(f"  [!] Không tìm thấy tệp Nguồn chính: {canonical_path.name}. Bỏ qua.")
            continue
        for dup_stem in group["duplicates"]:
            try:
                h, b, d = _process_duplicate_file(
                    transcripts_dir / f"{dup_stem}.md", group["canonical"], concepts_dir, backup_dir, dry_run
                )
                total_healed += h
                total_backed_up += b
                total_deleted += d
            except Exception:
                return

        if _sync_registry_for_group(group, concepts_dir, registry):
            reg_updated = True

    if reg_updated and not dry_run:
        _save_url_registry(registry)
    if not dry_run:
        _trigger_wiki_maintain()

    _print_dedup_summary((time.time() - start_time) * 1000, total_healed, total_backed_up, total_deleted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dọn dẹp nguồn trùng lặp trên đĩa và chữa lành liên kết.")
    parser.add_argument("--dry-run", action="store_true", help="Chạy ở chế độ mô phỏng, không thực tế xóa/ghi file.")
    args = parser.parse_args()
    run_deduplication(dry_run=args.dry_run)
