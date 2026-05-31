"""VvC Second Brain — Figure Inventory Context Enrichment Tool.

Scans book markdown files to locate references to diagram figures,
extracts surrounding context and chapter data, calls Vision API to
enrich each figure with high-quality captions and RAG-friendly alt-text descriptions.

Usage:
    # Enrich only 3 figures for dry run
    python scripts/tools/enrich_figure_inventory.py --limit 3

    # Enrich all figures in Sieu tang truong EOS book
    python scripts/tools/enrich_figure_inventory.py --book "Sieu_tang_truong"

    # Enrich all figures in the entire inventory
    python scripts/tools/enrich_figure_inventory.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from core.config import cfg
from core.llm.gateway_client import call_gateway_vision
from core.llm.utils import encode_image

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(message)s")
sys.stdout.reconfigure(encoding="utf-8")
_logger = logging.getLogger("vvc.enrich_figure_inventory")

# ── Paths ──────────────────────────────────────────────────────────────────────

INVENTORY_PATH = _SCRIPT_DIR.parent / "resources" / "figure_inventory.json"

# ── Prompts ────────────────────────────────────────────────────────────────────

FIGURE_ENRICH_PROMPT = """Bạn là chuyên gia phân tích tài liệu và tri thức hệ thống.
Dưới đây là một sơ đồ/hình ảnh từ sách chuyên môn, cùng với đoạn văn bản ngữ cảnh xung quanh hình ảnh này trong sách.

NGỮ CẢNH TRONG SÁCH:
---
{context_text}
---

Nhiệm vụ của bạn là phân tích hình ảnh và ngữ cảnh để trích xuất các thông tin sau bằng TIẾNG VIỆT:
1. "caption": Tiêu đề chính thức của sơ đồ/hình ảnh (ví dụ: "Sơ đồ 1-4: Khung năng lực sáu phần..."). Nếu sách không ghi rõ caption, hãy tự tạo một tiêu đề ngắn gọn phản ánh đúng bản chất của sơ đồ. Dịch sang tiếng Việt nếu nguyên bản tiếng Anh.
2. "alt_text": Mô tả chi tiết cấu trúc thị giác (topology), các thành phần chính (các nút, luồng chuyển động, các trục ma trận), và ý nghĩa cốt lõi của sơ đồ này. Mô tả này phải cực kỳ chi tiết (100-200 từ) để phục vụ cho công cụ tìm kiếm ngữ nghĩa (RAG) sau này.

Hãy trả về một chuỗi JSON hợp lệ với cấu trúc sau (KHÔNG dùng markdown code fences, không giải thích gì thêm):
{{
  "caption": "tiêu đề hình vẽ bằng tiếng Việt",
  "alt_text": "mô tả chi tiết cấu trúc sơ đồ phục vụ RAG"
}}"""

# ── Business Logic ─────────────────────────────────────────────────────────────

def _locate_context_in_book(book_name: str, filename: str, books_dir: Path | None = None) -> dict[str, Any] | None:
    """Scan all MD files in the book's MD folder to find the image reference and context.

    Args:
        book_name: Directory name ending in _MD
        filename: Image filename (e.g. Reinventing_the_Organization_H_Ch05_Figure_01-01.jpg)
        books_dir: Optional custom books directory (defaults to cfg.resources_books_dir)

    Returns:
        Dict with context metadata or None if not found.
    """
    if books_dir is None:
        books_dir = cfg.resources_books_dir

    if not books_dir.exists():
        return None

    md_dir = next(
        (d for d in books_dir.iterdir()
         if d.is_dir() and d.name.endswith("_MD") and book_name.lower() in d.name.lower()),
        None,
    )
    if not md_dir or not md_dir.exists():
        return None

    # Search for markdown reference to filename
    # Support standard wiki-link ![[filename]] and markdown ![](/path/to/filename)
    ref_patterns = [
        re.compile(re.escape(filename), re.IGNORECASE),
        re.compile(re.escape(filename.replace(" ", "%20")), re.IGNORECASE)
    ]

    for md_path in sorted(md_dir.glob("*.md")):
        # Skip copyright/title/index unless no other choice, priority to chapters
        if md_path.name.lower() in {"01_title_page.md", "02_copyright.md", "23_index.md", "notes.md"}:
            continue
            
        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for idx, line in enumerate(lines):
            if any(pattern.search(line) for pattern in ref_patterns):
                # Found the line!
                # 1. Resolve chapter title: look for H1 in the file
                chapter_title = ""
                for l in lines:
                    if l.strip().startswith("# "):
                        chapter_title = l.lstrip("# ").strip()
                        break
                if not chapter_title:
                    chapter_title = md_path.stem.replace("_", " ")

                # 2. Resolve chapter number from chapter file name (e.g. 05_1_... or Ch05 or 11_Chuong_8...)
                chapter_num = None
                num_match = re.search(r"(\d+)", md_path.name)
                if num_match:
                    chapter_num = int(num_match.group(1))

                # 3. Extract surrounding context (5 lines before, 5 lines after)
                start_idx = max(0, idx - 5)
                end_idx = min(len(lines), idx + 6)
                context_lines = [lines[i].strip() for i in range(start_idx, end_idx)]
                context_text = "\n".join([cl for cl in context_lines if cl])

                return {
                    "chapter_file": md_path.name,
                    "chapter_title": chapter_title,
                    "chapter_num": chapter_num,
                    "surrounding_context": context_text,
                }
                
    return None


def enrich_inventory(book_filter: str | None = None, limit: int | None = None) -> None:
    """Enrich figure_inventory.json with caption, chapter details, surrounding context, and alt-text."""
    if not INVENTORY_PATH.exists():
        _logger.error(f"Inventory path does not exist: {INVENTORY_PATH}")
        sys.exit(1)

    with open(INVENTORY_PATH, "r", encoding="utf-8") as f:
        inventory = json.load(f)

    figures = inventory.get("figures", [])
    _logger.info(f"Loaded {len(figures)} figures from inventory.")

    # Filter figures by book if filter provided
    figures_to_enrich = []
    for fig in figures:
        if book_filter and book_filter.lower() not in fig["book"].lower():
            continue
        # Skip if already fully enriched (has caption and alt_text)
        if fig.get("caption") and fig.get("alt_text") and fig.get("chapter_title"):
            continue
        figures_to_enrich.append(fig)

    if not figures_to_enrich:
        _logger.info("No figures need enrichment (all selected are already enriched).")
        return

    if limit:
        figures_to_enrich = figures_to_enrich[:limit]
        _logger.info(f"Applying limit: only enriching the first {limit} figures.")

    _logger.info(f"Starting enrichment process for {len(figures_to_enrich)} figures...")

    success_count = 0
    error_count = 0

    for idx, fig in enumerate(figures_to_enrich):
        filename = fig["filename"]
        book_name = fig["book"]
        _logger.info(f"[{idx+1}/{len(figures_to_enrich)}] Enriching {filename} ({book_name})...")

        # Step 1: Locate figure reference in chapter markdown
        books_dir = cfg.resources_books_dir
        context_data = _locate_context_in_book(book_name, filename, books_dir=books_dir)
        if not context_data:
            _logger.warning(f"Could not locate image reference in MD files for {filename}")
            # Try a fallback if possible
            context_data = {
                "chapter_file": "unknown",
                "chapter_title": "unknown",
                "chapter_num": None,
                "surrounding_context": "No surrounding text available.",
            }

        fig["chapter_file"] = context_data["chapter_file"]
        fig["chapter_title"] = context_data["chapter_title"]
        fig["chapter_num"] = context_data["chapter_num"]
        fig["surrounding_context"] = context_data["surrounding_context"]

        # Step 2: Use Vision LLM to generate high quality Caption & Alt-text
        img_path = Path(fig["path"])
        if not img_path.exists():
            # Fallback path resolve (in case of path mismatch across OS/users)
            # Find the actual path under books dir
            resolved_path = next(
                (books_dir.glob(f"**/{filename}")),
                None
            )
            if resolved_path:
                img_path = resolved_path
                fig["path"] = str(resolved_path)

        if not img_path.exists():
            _logger.error(f"Image file does not exist: {img_path}")
            error_count += 1
            continue

        try:
            image_b64 = encode_image(img_path, max_pixels=1024)
            formatted_prompt = FIGURE_ENRICH_PROMPT.format(context_text=context_data["surrounding_context"])
            
            _logger.info(f"  Calling LLM Vision API for visual analysis...")
            llm_result = call_gateway_vision(
                image_b64, 
                formatted_prompt, 
                timeout=cfg.gemini_vision_timeout
            )
            
            if llm_result:
                # Strip markdown json block fences if any
                clean_result = llm_result.strip()
                if clean_result.startswith("```"):
                    # Find json content
                    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_result, re.DOTALL)
                    if json_match:
                        clean_result = json_match.group(1)
                
                parsed_res = json.loads(clean_result)
                fig["caption"] = parsed_res.get("caption", "").strip()
                fig["alt_text"] = parsed_res.get("alt_text", "").strip()
                _logger.info(f"  Successfully enriched: Caption='{fig['caption'][:30]}...'")
                success_count += 1
            else:
                _logger.warning(f"  Vision API returned empty result for {filename}")
                error_count += 1

        except Exception as e:
            _logger.error(f"  Failed to enrich via Vision API: {e}")
            error_count += 1

        # Intermediate save after each step to prevent losing progress
        with open(INVENTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(inventory, f, ensure_ascii=False, indent=2)

        # Throttle
        time.sleep(1.0)

    _logger.info(f"\nEnrichment complete! Success: {success_count}, Errors/Skipped: {error_count}")
    _logger.info(f"Inventory fully updated and saved: {INVENTORY_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VvC Diagram Context Enricher — locates image references and calls Vision LLM for caption & alt-text enrichment"
    )
    parser.add_argument(
        "--book",
        type=str,
        default=None,
        help="Filter figures by book name substring (case-insensitive)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of figures to enrich in this run"
    )
    args = parser.parse_args()

    enrich_inventory(book_filter=args.book, limit=args.limit)
