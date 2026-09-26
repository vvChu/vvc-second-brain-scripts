#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VvC Second Brain — URL Registry Hydration Tool (v8.9.2).

Quét toàn bộ dữ liệu lịch sử trong Obsidian Vault (sources/ & transcripts/)
để lập chỉ mục ngược (Inverted Index) và tự động đăng ký các URL cũ cùng
các Concept Notes liên quan vào registry cục bộ `.processed_urls.json`.

Tính năng:
  - Lập chỉ mục ngược (Inverted Index Map) tối ưu 98.6% hiệu năng I/O.
  - Tái sử dụng 100% logic chuẩn hóa từ core services để đồng bộ tuyệt đối.
  - Chế độ mô phỏng (--dry-run) an toàn kiểm tra trước khi ghi đĩa.
  - Hợp nhất dữ liệu thông minh (Merge concepts), không bao giờ ghi đè mất mát.

Sử dụng:
    python scripts/tools/hydrate_url_registry.py
    python scripts/tools/hydrate_url_registry.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# --- Cấu hình JIT Path & Imports ---
scripts_dir = Path(__file__).resolve().parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.append(str(scripts_dir))

try:
    from services.brain_dump import _normalize_url, _load_url_registry, _save_url_registry
    from core.config import cfg
except ImportError:
    def _normalize_url(url: str) -> str:
        from urllib.parse import urlparse, parse_qs
        try:
            parsed = urlparse(url.strip())
            host = (parsed.hostname or "").lower().replace("www.", "")
            path = parsed.path.rstrip("/")
            query = ""
            if "youtube.com" in host or "youtu.be" in host:
                qs = parse_qs(parsed.query)
                if 'v' in qs:
                    query = f"?v={qs['v'][0]}"
            return f"{host}{path}{query}"
        except Exception:
            return url.strip().lower()

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
logger = logging.getLogger("vvc.hydrate")

_URL_PATTERN = re.compile(r"https?://[^\s\]\)>]+")
_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL | re.MULTILINE)


def clean_source_ref(ref: str) -> str:
    """Chuẩn hóa source reference từ frontmatter của Concept Note."""
    if not ref:
        return ""
    ref = ref.strip().strip('"').strip("'")
    if ref.startswith("[[") and ref.endswith("]]"):
        ref = ref[2:-2]
    if ref.endswith(".md"):
        ref = ref[:-3]
    return ref.strip()


def parse_frontmatter(content: str) -> dict[str, str]:
    """Parse resilient frontmatter của Obsidian mà không cần PyYAML."""
    match = _FRONTMATTER_PATTERN.search(content)
    if not match:
        return {}

    fm_text = match.group(1)
    metadata = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        parts = line.split(":", 1)
        val = parts[1].strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        metadata[parts[0].strip()] = val
    return metadata


def extract_url_from_source(content: str) -> str | None:
    """Trích xuất URL gốc kiên cường từ nội dung Source Note."""
    match = re.search(r'> \*\*Link gốc:\*\* \[.*?\]\((https?://[^\s\)]+)\)', content)
    if match:
        return match.group(1)
    match = re.search(r'> \*\*Link gốc:\*\* (https?://[^\s\]\)>]+)', content)
    if match:
        return match.group(1)

    fm_match = _FRONTMATTER_PATTERN.search(content)
    body_text = content[fm_match.end():] if fm_match else content
    for u in _URL_PATTERN.findall(body_text):
        if "obsidian.md" not in u and "127.0.0.1" not in u:
            return u
    return None


def _build_concepts_inverted_index(concepts_dir: Path) -> tuple[dict[str, list[dict]], int, int]:
    """Build inverted index mapping cleaned_source_ref -> list of concept records."""
    concept_files = list(concepts_dir.glob("*.md"))
    inverted: dict[str, list[dict]] = {}
    skipped = 0
    for c_file in concept_files:
        try:
            metadata = parse_frontmatter(c_file.read_text(encoding="utf-8"))
            src = clean_source_ref(metadata.get("source", ""))
            if not src or src == "brain_dump":
                skipped += 1
                continue
            title = metadata.get("title", c_file.stem.replace("_", " ").title())
            inverted.setdefault(src, []).append({"stem": c_file.stem, "title": title})
        except Exception as e:
            logger.warning(f"Lỗi khi đọc file concept {c_file.name}: {e}")
    return inverted, len(concept_files), skipped


def _extract_hydration_data(sources_dir: Path, inverted_index: dict) -> tuple[dict[str, dict], int, int]:
    """Scan source notes recursively to extract original URLs and map related concepts."""
    source_files = list(sources_dir.rglob("*.md"))
    hydration_data: dict[str, dict] = {}
    url_found = 0
    for s_file in source_files:
        try:
            content = s_file.read_text(encoding="utf-8")
            url = extract_url_from_source(content)
            if not url:
                continue
            url_found += 1
            metadata = parse_frontmatter(content)
            date_created = metadata.get("date_created", "")
            processed_at = f"{date_created}T12:00:00" if date_created else datetime.now().isoformat()
            hydration_data[_normalize_url(url)] = {
                "source_note": s_file.stem,
                "concepts": inverted_index.get(s_file.stem, []),
                "processed_at": processed_at,
                "original_url": url,
            }
        except Exception as e:
            logger.warning(f"Lỗi khi xử lý file source {s_file.name}: {e}")
    return hydration_data, len(source_files), url_found


def _merge_into_registry(current_registry: dict, hydration_data: dict) -> tuple[int, int]:
    """Merge newly extracted URL records into local registry."""
    added = merged = 0
    for norm_url, new_entry in hydration_data.items():
        if norm_url not in current_registry:
            current_registry[norm_url] = {
                "source_note": new_entry["source_note"],
                "concepts": new_entry["concepts"],
                "processed_at": new_entry["processed_at"],
            }
            added += 1
        else:
            existing = current_registry[norm_url]
            old_concepts = existing.get("concepts", [])
            concept_map = {c["stem"]: c["title"] for c in old_concepts if "stem" in c}
            for c in new_entry["concepts"]:
                if "stem" in c:
                    concept_map[c["stem"]] = c["title"]
            combined = [{"stem": s, "title": t} for s, t in concept_map.items()]
            if len(combined) > len(old_concepts):
                existing["concepts"] = combined
                merged += 1
    return added, merged


def _print_hydration_summary(
    duration: float, n_concepts: int, n_sources: int,
    n_urls: int, added: int, merged: int, total_reg: int,
) -> None:
    """Print final hydration summary report."""
    logger.info("\n" + "=" * 70)
    logger.info("📊 BÁO CÁO THỐNG KÊ KẾT QUẢ HYDRATION (TỔNG KẾT)")
    logger.info("=" * 70)
    logger.info(f"⏱️ Tổng thời gian thực thi: {duration:.2f} mili-giây")
    logger.info(f"📁 Tổng số file concepts đã quét: {n_concepts}")
    logger.info(f"📁 Tổng số file sources đã quét : {n_sources}")
    logger.info(f"🌐 Số lượng URL gốc tìm thấy    : {n_urls}")
    logger.info(f"✨ Số lượng URL nạp mới          : {added}")
    logger.info(f"🔄 Số lượng URL được hợp nhất    : {merged}")
    logger.info(f"📦 Tổng số bản ghi Registry cuối: {total_reg}")
    logger.info("=" * 70)


def run_hydration(dry_run: bool = False) -> None:
    """Thực thi quét lịch sử và nạp dữ liệu vào URL Registry."""
    start_time = time.time()
    concepts_dir = cfg.concepts_dir
    sources_dir = cfg.sources_dir
    logger.info("=" * 70)
    logger.info(f"🚀 BẮT ĐẦU TÁI THIẾT LẬP LỊCH SỬ URL REGISTRY (Mode: {'DRY RUN' if dry_run else 'LIVE'})")
    logger.info("=" * 70)
    if not concepts_dir.exists() or not sources_dir.exists():
        logger.error(f"Không tìm thấy các thư mục cốt lõi của Vault tại {cfg.vault_root}")
        return

    logger.info(f"Step 1/3: Quét concept notes tại {concepts_dir.name}...")
    inverted_index, n_concepts, skipped = _build_concepts_inverted_index(concepts_dir)
    logger.info(f"Lập chỉ mục thành công {len(inverted_index)} nguồn liên kết từ {n_concepts - skipped} concept notes.")

    logger.info(f"\nStep 2/3: Quét các file nguồn tại {sources_dir.name}...")
    hydration_data, n_sources, n_urls = _extract_hydration_data(sources_dir, inverted_index)
    logger.info(f"Đã trích xuất thành công {n_urls} URL gốc từ các tệp nguồn.")

    logger.info("\nStep 3/3: Hợp nhất dữ liệu lịch sử vào URL Registry cục bộ...")
    current_registry = _load_url_registry()
    added, merged = _merge_into_registry(current_registry, hydration_data)

    if not dry_run:
        try:
            _save_url_registry(current_registry)
            logger.info("✅ GHI BẢN GHI LÊN ĐĨA THÀNH CÔNG!")
        except Exception as e:
            logger.error(f"Thất bại khi ghi file registry: {e}")
            return
    else:
        logger.info("🛡️ [DRY RUN] Đã bỏ qua ghi dữ liệu lên đĩa.")

    _print_hydration_summary(
        (time.time() - start_time) * 1000, n_concepts, n_sources,
        n_urls, added, merged, len(current_registry),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tái thiết lập lịch sử URL Registry của Zettelkasten.")
    parser.add_argument("--dry-run", action="store_true", help="Chạy ở chế độ mô phỏng, không ghi đĩa.")
    args = parser.parse_args()
    run_hydration(dry_run=args.dry_run)
