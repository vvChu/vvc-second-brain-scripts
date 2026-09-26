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
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass
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

def _extract_image_context_from_md(md_path: Path, ref_patterns: list[re.Pattern]) -> dict[str, Any] | None:
    """Scan lines of a markdown file for image reference and return surrounding context."""
    try:
        lines = md_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for idx, line in enumerate(lines):
        if any(p.search(line) for p in ref_patterns):
            chapter_title = next(
                (l.lstrip("# ").strip() for l in lines if l.strip().startswith("# ")),
                md_path.stem.replace("_", " "),
            )
            num_match = re.search(r"(\d+)", md_path.name)
            chapter_num = int(num_match.group(1)) if num_match else None
            start_idx = max(0, idx - 5)
            end_idx = min(len(lines), idx + 6)
            context_text = "\n".join(lines[i].strip() for i in range(start_idx, end_idx) if lines[i].strip())
            return {
                "chapter_file": md_path.name,
                "chapter_title": chapter_title,
                "chapter_num": chapter_num,
                "surrounding_context": context_text,
            }
    return None


def _locate_context_in_book(book_name: str, filename: str, books_dir: Path | None = None) -> dict[str, Any] | None:
    """Scan all MD files in the book's MD folder to find the image reference and context."""
    books_dir = cfg.resources_books_dir if books_dir is None else books_dir
    if not books_dir.exists():
        return None

    md_dir = next(
        (d for d in books_dir.iterdir()
         if d.is_dir() and d.name.endswith("_MD") and book_name.lower() in d.name.lower()),
        None,
    )
    if not md_dir or not md_dir.exists():
        return None

    ref_patterns = [
        re.compile(re.escape(filename), re.IGNORECASE),
        re.compile(re.escape(filename.replace(" ", "%20")), re.IGNORECASE),
    ]
    ignored = {"01_title_page.md", "02_copyright.md", "23_index.md", "notes.md"}
    for md_path in sorted(md_dir.glob("*.md")):
        if md_path.name.lower() in ignored:
            continue
        res = _extract_image_context_from_md(md_path, ref_patterns)
        if res:
            return res
    return None


def _resolve_image_path(fig: dict, filename: str, books_dir: Path) -> Path | None:
    """Resolve physical image path on disk with fallback search."""
    img_path = Path(fig["path"])
    if not img_path.exists():
        resolved = next(books_dir.glob(f"**/{filename}"), None)
        if resolved:
            img_path = resolved
            fig["path"] = str(resolved)
    return img_path if img_path.exists() else None


def _enrich_single_figure(fig: dict, books_dir: Path) -> bool:
    """Perform context lookup and Vision LLM captioning on a single figure dict."""
    filename = fig["filename"]
    context_data = _locate_context_in_book(fig["book"], filename, books_dir=books_dir) or {
        "chapter_file": "unknown",
        "chapter_title": "unknown",
        "chapter_num": None,
        "surrounding_context": "No surrounding text available.",
    }
    fig.update(context_data)

    img_path = _resolve_image_path(fig, filename, books_dir)
    if not img_path:
        _logger.error(f"Image file does not exist: {fig['path']}")
        return False

    try:
        image_b64 = encode_image(img_path, max_pixels=1024)
        prompt = FIGURE_ENRICH_PROMPT.format(context_text=context_data["surrounding_context"])
        llm_result = call_gateway_vision(image_b64, prompt, timeout=cfg.gemini_vision_timeout)
        if not llm_result:
            _logger.warning(f"Vision API returned empty result for {filename}")
            return False

        clean_result = llm_result.strip()
        if clean_result.startswith("```"):
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_result, re.DOTALL)
            if m:
                clean_result = m.group(1)

        parsed = json.loads(clean_result)
        fig["caption"] = parsed.get("caption", "").strip()
        fig["alt_text"] = parsed.get("alt_text", "").strip()
        _logger.info(f"  Successfully enriched: Caption='{fig['caption'][:30]}...'")
        return True
    except Exception as e:
        _logger.error(f"Failed to enrich via Vision API: {e}")
        return False


def enrich_inventory(book_filter: str | None = None, limit: int | None = None) -> None:
    """Enrich figure_inventory.json with caption, chapter details, context, and alt-text."""
    if not INVENTORY_PATH.exists():
        _logger.error(f"Inventory path does not exist: {INVENTORY_PATH}")
        sys.exit(1)

    with open(INVENTORY_PATH, "r", encoding="utf-8") as f:
        inventory = json.load(f)

    figures = inventory.get("figures", [])
    to_enrich = [
        fig for fig in figures
        if (not book_filter or book_filter.lower() in fig["book"].lower())
        and not (fig.get("caption") and fig.get("alt_text") and fig.get("chapter_title"))
    ]
    if not to_enrich:
        _logger.info("No figures need enrichment (all selected are already enriched).")
        return

    if limit:
        to_enrich = to_enrich[:limit]

    _logger.info(f"Starting enrichment process for {len(to_enrich)} figures...")
    success_count = error_count = 0
    books_dir = cfg.resources_books_dir

    for idx, fig in enumerate(to_enrich):
        _logger.info(f"[{idx+1}/{len(to_enrich)}] Enriching {fig['filename']} ({fig['book']})...")
        if _enrich_single_figure(fig, books_dir):
            success_count += 1
        else:
            error_count += 1

        with open(INVENTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(inventory, f, ensure_ascii=False, indent=2)
        time.sleep(1.0)

    _logger.info(f"\nEnrichment complete! Success: {success_count}, Errors/Skipped: {error_count}")
    _logger.info(f"Inventory fully updated and saved: {INVENTORY_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VvC Diagram Context Enricher — locates image references and calls Vision LLM"
    )
    parser.add_argument("--book", type=str, default=None, help="Filter figures by book name substring")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of figures to enrich")
    args = parser.parse_args()

    enrich_inventory(book_filter=args.book, limit=args.limit)
