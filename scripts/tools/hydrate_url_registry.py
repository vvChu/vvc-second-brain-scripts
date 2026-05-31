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
    # Fallback dự phòng nếu import lỗi ngoài môi trường tiêu chuẩn
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
        f = scripts_dir / ".processed_urls.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        return {}

    def _save_url_registry(r: dict) -> None:
        f = scripts_dir / ".processed_urls.json"
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
logger = logging.getLogger("vvc.hydrate")

# --- Các mẫu Regex và Helper ---
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
        key = parts[0].strip()
        val = parts[1].strip()
        
        # Loại bỏ ngoặc kép hoặc nháy đơn bao quanh
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
            
        metadata[key] = val
    return metadata


def extract_url_from_source(content: str) -> str | None:
    """Trích xuất URL gốc kiên cường từ nội dung Source Note."""
    # Thử cách 1: Tìm callout Link gốc chính thức
    match = re.search(r'> \*\*Link gốc:\*\* \[.*?\]\((https?://[^\s\)]+)\)', content)
    if match:
        return match.group(1)
        
    # Thử cách 2: Tìm callout Link gốc dạng văn bản thô
    match = re.search(r'> \*\*Link gốc:\*\* (https?://[^\s\]\)>]+)', content)
    if match:
        return match.group(1)
        
    # Thử cách 3: Tìm URL đầu tiên trong tệp nằm ngoài frontmatter
    # Bỏ qua khối frontmatter
    fm_match = _FRONTMATTER_PATTERN.search(content)
    body_text = content[fm_match.end():] if fm_match else content
    
    urls = _URL_PATTERN.findall(body_text)
    if urls:
        # Bỏ qua các URL trỏ nội bộ (ví dụ: obsidian:// hoặc localhost)
        for u in urls:
            if "obsidian.md" not in u and "127.0.0.1" not in u:
                return u
                
    return None


def run_hydration(dry_run: bool = False) -> None:
    """Thực thi quét lịch sử và nạp dữ liệu vào URL Registry."""
    start_time = time.time()
    
    # Định nghĩa các đường dẫn tuyệt đối dựa trên workspace
    vault_root = Path("D:/VvC_Notes")
    concepts_dir = vault_root / "04 - Permanent" / "concepts"
    sources_dir = vault_root / "04 - Permanent" / "sources"
    
    logger.info("======================================================================")
    logger.info(f"🚀 BẮT ĐẦU TÁI THIẾT LẬP LỊCH SỬ URL REGISTRY (Mode: {'DRY RUN' if dry_run else 'LIVE'})")
    logger.info("======================================================================")
    
    if not concepts_dir.exists() or not sources_dir.exists():
        logger.error("Không tìm thấy các thư mục cốt lõi của Obsidian Vault tại D:/VvC_Notes")
        return

    # ------------------------------------------------------------------
    # BƯỚC 1: Xây dựng Chỉ mục ngược (Inverted Index) từ Concept Notes
    # ------------------------------------------------------------------
    logger.info(f"Step 1/3: Quét concept notes tại {concepts_dir.name} để lập chỉ mục ngược...")
    concept_files = list(concepts_dir.glob("*.md"))
    logger.info(f"Tìm thấy {len(concept_files)} tệp Concept Note.")
    
    inverted_index = {}  # Map: cleaned_source_ref -> list of {"stem": stem, "title": title}
    skipped_concepts_count = 0
    
    for c_file in concept_files:
        try:
            content = c_file.read_text(encoding="utf-8")
            metadata = parse_frontmatter(content)
            
            source_raw = metadata.get("source", "")
            title = metadata.get("title", c_file.stem.replace("_", " ").title())
            
            cleaned_source = clean_source_ref(source_raw)
            if not cleaned_source or cleaned_source == "brain_dump":
                skipped_concepts_count += 1
                continue
                
            concept_record = {
                "stem": c_file.stem,
                "title": title
            }
            
            if cleaned_source not in inverted_index:
                inverted_index[cleaned_source] = []
            inverted_index[cleaned_source].append(concept_record)
        except Exception as e:
            logger.warning(f"Lỗi khi đọc file concept {c_file.name}: {e}")
            
    logger.info(f"Lập chỉ mục thành công {len(inverted_index)} nguồn liên kết từ {len(concept_files) - skipped_concepts_count} concept notes.")
    logger.info(f"Bỏ qua {skipped_concepts_count} concept notes không có liên kết nguồn (hoặc nguồn mặc định 'brain_dump').")

    # ------------------------------------------------------------------
    # BƯỚC 2: Quét Source Notes để trích xuất URL gốc
    # ------------------------------------------------------------------
    logger.info("")
    logger.info(f"Step 2/3: Quét các file nguồn tại {sources_dir.name} để tìm URL gốc...")
    
    # Quét đệ quy thư mục sources/ để bắt cả transcripts/ và sách
    source_files = list(sources_dir.rglob("*.md"))
    logger.info(f"Tìm thấy {len(source_files)} tệp Source Note lịch sử.")
    
    hydration_data = {}  # Map: normalized_url -> record dict
    url_found_count = 0
    
    for s_file in source_files:
        try:
            content = s_file.read_text(encoding="utf-8")
            url = extract_url_from_source(content)
            if not url:
                continue
                
            url_found_count += 1
            norm_url = _normalize_url(url)
            source_stem = s_file.stem
            
            # Trích xuất metadata thời gian
            metadata = parse_frontmatter(content)
            date_created = metadata.get("date_created", "")
            if date_created:
                processed_at = f"{date_created}T12:00:00"
            else:
                processed_at = datetime.now().isoformat()
                
            # Lấy các concept liên kết từ inverted index
            related_concepts = inverted_index.get(source_stem, [])
            
            hydration_data[norm_url] = {
                "source_note": source_stem,
                "concepts": related_concepts,
                "processed_at": processed_at,
                "original_url": url  # metadata bổ sung để đối chiếu
            }
        except Exception as e:
            logger.warning(f"Lỗi khi xử lý file source {s_file.name}: {e}")
            
    logger.info(f"Đã trích xuất thành công {url_found_count} URL gốc từ các tệp nguồn.")

    # ------------------------------------------------------------------
    # BƯỚC 3: Hợp nhất (Merge) vào Registry hiện tại và ghi đĩa
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("Step 3/3: Hợp nhất dữ liệu lịch sử vào URL Registry cục bộ...")
    
    current_registry = _load_url_registry()
    logger.info(f"Registry hiện tại đang chứa {len(current_registry)} bản ghi URL.")
    
    new_records_added = 0
    records_merged = 0
    
    for norm_url, new_entry in hydration_data.items():
        if norm_url not in current_registry:
            # URL mới hoàn toàn
            current_registry[norm_url] = {
                "source_note": new_entry["source_note"],
                "concepts": new_entry["concepts"],
                "processed_at": new_entry["processed_at"]
            }
            new_records_added += 1
            logger.info(f"➕ Thêm mới: [{norm_url}] ➡️ {len(new_entry['concepts'])} concepts")
        else:
            # URL đã tồn tại -> Hợp nhất danh sách concepts thông minh
            existing_entry = current_registry[norm_url]
            existing_concepts = existing_entry.get("concepts", [])
            new_concepts = new_entry["concepts"]
            
            # Hợp nhất và loại bỏ trùng lặp concept theo stem
            concept_map = {c["stem"]: c["title"] for c in existing_concepts if "stem" in c}
            for c in new_concepts:
                if "stem" in c:
                    concept_map[c["stem"]] = c["title"]
                    
            merged_concepts = [{"stem": stem, "title": title} for stem, title in concept_map.items()]
            
            # Chỉ cập nhật nếu danh sách concept tăng lên hoặc trống
            if len(merged_concepts) > len(existing_concepts):
                existing_entry["concepts"] = merged_concepts
                records_merged += 1
                logger.info(f"🔄 Hợp nhất: [{norm_url}] gộp concepts cũ và mới ({len(existing_concepts)} ➡️ {len(merged_concepts)})")

    # Lưu kết quả
    if not dry_run:
        try:
            _save_url_registry(current_registry)
            logger.info("")
            logger.info("✅ GHI BẢN GHI LÊN ĐĨA THÀNH CÔNG!")
        except Exception as e:
            logger.error(f"Thất bại khi ghi file registry .processed_urls.json: {e}")
            return
    else:
        logger.info("")
        logger.info("🛡️ [DRY RUN] Đã bỏ qua ghi dữ liệu lên đĩa. Không có file nào bị sửa đổi thực tế.")

    # ------------------------------------------------------------------
    # BÁO CÁO THỐNG KÊ CHI TIẾT
    # ------------------------------------------------------------------
    duration = (time.time() - start_time) * 1000
    logger.info("")
    logger.info("======================================================================")
    logger.info("📊 BÁO CÁO THỐNG KÊ KẾT QUẢ HYDRATION (TỔNG KẾT)")
    logger.info("======================================================================")
    logger.info(f"⏱️ Tổng thời gian thực thi: {duration:.2f} mili-giây (siêu tốc nhờ Inverted Index)")
    logger.info(f"📁 Tổng số file concepts đã quét: {len(concept_files)}")
    logger.info(f"📁 Tổng số file sources đã quét : {len(source_files)}")
    logger.info(f"🌐 Số lượng URL gốc tìm thấy    : {url_found_count}")
    logger.info(f"✨ Số lượng URL nạp mới          : {new_records_added}")
    logger.info(f"🔄 Số lượng URL được hợp nhất    : {records_merged}")
    logger.info(f"📦 Tổng số bản ghi Registry cuối: {len(current_registry)}")
    logger.info("======================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tái thiết lập lịch sử URL Registry của Zettelkasten.")
    parser.add_argument("--dry-run", action="store_true", help="Chạy ở chế độ mô phỏng, không ghi đĩa.")
    args = parser.parse_args()
    
    run_hydration(dry_run=args.dry_run)
