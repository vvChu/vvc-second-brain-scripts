"""VvC Second Brain — Publisher Diagram & Book Asset Seam.

Centralized Deep Module managing book corpus markdown scanning, publisher diagram discovery,
adaptive asset naming, WebP compression, and JIT diagram catalog enrichment.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

from core.config import cfg
from core.frontmatter import parse_frontmatter, normalize_stem
from core.llm.utils import encode_image
from core.prompts.pipeline import FIGURE_ENRICH

_logger = logging.getLogger("vvc.book_assets")

FIGURE_ENRICH_PROMPT = FIGURE_ENRICH


def find_book_md_dir(book_name: str, books_dir: Path | None = None) -> Path | None:
    """Find the extracted markdown corpus directory for the given book name."""
    if not book_name:
        return None
    if books_dir is None:
        books_dir = cfg.resources_books_dir
    if not books_dir.exists():
        return None
    try:
        norm_book = book_name.lower().replace(" ", "_")
        raw_book = book_name.lower()
        return next(
            (d for d in books_dir.iterdir()
             if d.is_dir() and d.name.endswith("_MD") and (norm_book in d.name.lower() or raw_book in d.name.lower())),
            None,
        )
    except OSError:
        return None


def is_decorative_image(filename: str, file_path: Path) -> bool:
    """Check if an image is decorative based on filename keywords or small file size (< 5KB)."""
    filename_lower = filename.lower()
    decorative_keywords = {"cover", "logo", "credit", "title_page", "icon", "decorative"}
    if any(kw in filename_lower for kw in decorative_keywords):
        return True
    if file_path.exists():
        try:
            if file_path.stat().st_size < 5120:  # 5 KB
                return True
        except OSError:
            pass
    return False


def shorten_chapter(chapter_ref: str) -> str:
    """Extract a clean, short chapter identifier (e.g. 'ch7' from '[[Chương 7: Đối phó]]')."""
    clean = chapter_ref.replace("[[", "").replace("]]", "").strip()
    if not clean:
        return ""

    if "/" in clean:
        clean = clean.split("/")[-1]

    norm = normalize_stem(clean)
    match = re.search(r"(?:chuong|chapter|ch)_*(\d+)", norm, re.IGNORECASE)
    if match:
        return f"ch{match.group(1)}"

    return norm[:15]


def compute_adaptive_asset_name(
    book_name: str,
    chapter_stem: str,
    page: str,
    original_stem: str,
) -> str:
    """Compute normalized WebP filename for a book diagram asset using Adaptive Naming Strategy.
    
    If the image already contains words from the book slug, it retains its stem.
    Otherwise, it is prefixed with book_slug, short_ch, and page.
    """
    book_slug = normalize_stem(book_name)[:30].rstrip("_")
    orig_stem = normalize_stem(original_stem)
    book_words = [w for w in book_slug.split("_") if len(w) > 3]
    has_book_prefix = any(w in orig_stem for w in book_words)

    if has_book_prefix:
        return f"{orig_stem}.webp"

    short_ch = shorten_chapter(chapter_stem)
    parts = [book_slug]
    if short_ch:
        parts.append(short_ch)
    if page:
        parts.append(f"p{page}")
    parts.append(orig_stem)
    return f"{'_'.join(parts)}.webp"


def _compress_or_copy_diagram(
    orig_path: Path, dest_path: Path, assets_dir: Path
) -> str | None:
    """Compress image to WebP or fallback to raw copy, returning saved filename."""
    if dest_path.exists():
        return dest_path.name
    try:
        from PIL import Image as PILImage
        img = PILImage.open(orig_path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)
        assets_dir.mkdir(parents=True, exist_ok=True)
        img.save(dest_path, "WEBP", quality=80)
        _logger.info(f"[JIT Image] Compressed image: {orig_path.name} -> {dest_path.name}")
        return dest_path.name
    except Exception as e:
        _logger.warning(f"[JIT Image] WebP failed for {orig_path.name}: {e}. Fallback to copy.")
        dest_raw = dest_path.with_suffix(orig_path.suffix)
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(orig_path), str(dest_raw))
            return dest_raw.name
        except Exception as copy_err:
            _logger.warning(f"[JIT Image] Copy failed: {copy_err}")
            return None


def _embed_aligned_diagrams(content: str, aligned_images: list[str]) -> str:
    """Embed aligned diagram wikilinks right before Ground Truth heading."""
    gt_match = re.search(r"## (?:📖|Ground Truth)", content)
    if not gt_match:
        return content

    embed_lines = [f"\n![[{name}]]\n" for name in aligned_images if f"![[{name}]]" not in content]
    if not embed_lines:
        return content

    idx = gt_match.start()
    _logger.info(f"[JIT Image] Aligned {len(aligned_images)} original image(s)")
    return content[:idx].rstrip() + "\n" + "".join(embed_lines) + "\n" + content[idx:]


def align_book_diagrams(content: str, book_name: str) -> str:
    """Scan original book corpus MD files to find and align crisp publisher diagrams."""
    if not book_name:
        return content

    fm = parse_frontmatter(content)
    gt_ch = fm.get("ground_truth_chapter")
    chapter_stem = str(gt_ch).replace("[[", "").replace("]]", "").strip() if gt_ch else ""
    if not chapter_stem:
        return content

    page = str(fm.get("source_page", "")).strip() or str(fm.get("ground_truth_page", "")).strip()
    md_dir = find_book_md_dir(book_name)
    chapter_file = md_dir / f"{chapter_stem}.md" if md_dir else None
    if not md_dir or not chapter_file or not chapter_file.exists():
        return content

    try:
        chapter_text = chapter_file.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning(f"[JIT Image] Failed to read chapter file: {e}")
        return content

    gt_match = re.search(r"## (?:📖|Ground Truth)[^\n]*\n+(.*?)(?:\n\n---|\n\n##|\Z)", content, re.DOTALL)
    if not gt_match:
        return content

    from pipeline.ground_truth import find_images_around_ground_truth
    found_images = find_images_around_ground_truth(chapter_text, gt_match.group(1))
    if not found_images:
        return content

    aligned_images: list[str] = []
    book_slug = normalize_stem(book_name)[:30].rstrip("_")
    assets_dir = cfg.assets_dir / book_slug

    for img_name in found_images:
        orig_path = md_dir / img_name
        if not orig_path.exists() or is_decorative_image(img_name, orig_path):
            continue
        dest_name = compute_adaptive_asset_name(book_name, chapter_stem, page, orig_path.stem)
        dest_path = assets_dir / dest_name
        saved_name = _compress_or_copy_diagram(orig_path, dest_path, assets_dir)
        if saved_name:
            aligned_images.append(saved_name)

    return _embed_aligned_diagrams(content, aligned_images) if aligned_images else content


def _load_figure_inventory(inventory_path: Path) -> dict[str, Any]:
    """Load existing figure inventory map indexed by lowercase filename."""
    if not inventory_path.exists():
        return {}
    try:
        inv_data = json.loads(inventory_path.read_text(encoding="utf-8"))
        return {fig["filename"].lower(): fig for fig in inv_data.get("figures", [])}
    except Exception:
        return {}


def _resolve_vision_caller(vision_caller: Callable[..., str] | None) -> Callable[..., str]:
    """Resolve vision API caller with image_processor monkeypatch fallback."""
    if vision_caller is not None:
        return vision_caller
    ip_mod = sys.modules.get("pipeline.image_processor")
    if ip_mod and hasattr(ip_mod, "call_gateway_vision"):
        return getattr(ip_mod, "call_gateway_vision")
    from core.llm.gateway_client import call_gateway_vision
    return call_gateway_vision


def _save_figure_inventory(inventory: dict[str, Any], inventory_path: Path) -> None:
    """Save enriched figure inventory back to disk."""
    try:
        inventory_data = {"figures": list(inventory.values())}
        inventory_path.write_text(json.dumps(inventory_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as save_err:
        _logger.warning(f"Failed to save figure_inventory.json during JIT: {save_err}")


def _parse_json_block(text: str) -> dict[str, Any]:
    """Parse JSON object from LLM response, stripping markdown code fences."""
    clean = text.strip()
    if clean.startswith("```"):
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.DOTALL)
        clean = m.group(1) if m else clean
    return json.loads(clean)


def _format_diagram_xml(img_name: str, dest_name: str, caption: str, alt_text: str) -> list[str]:
    """Format XML lines for a single book diagram entry."""
    lines = ["  <DIAGRAM>", f"    <FILENAME>{img_name}</FILENAME>", f"    <ADAPTIVE_NAME>{dest_name}</ADAPTIVE_NAME>"]
    if caption:
        lines.append(f"    <CAPTION>{caption}</CAPTION>")
    if alt_text:
        lines.append(f"    <ALT_TEXT>{alt_text}</ALT_TEXT>")
    lines.append("  </DIAGRAM>")
    return lines


def _enrich_diagram_metadata(
    img_name: str,
    orig_path: Path,
    chapter_text: str,
    gt_text: str,
    book_name: str,
    chapter_stem: str,
    caller: Callable[..., str],
    inventory: dict[str, Any],
    inventory_path: Path,
) -> tuple[str, str]:
    """Perform JIT vision enrichment to generate caption and alt-text for a book diagram."""
    fig_info = inventory.get(img_name.lower())
    caption = fig_info.get("caption", "") if fig_info else ""
    alt_text = fig_info.get("alt_text", "") if fig_info else ""
    if caption and alt_text:
        return caption, alt_text

    _logger.info(f"JIT Diagram Enrichment triggered for: {img_name}")
    try:
        img_pos = chapter_text.find(img_name)
        ctx = (
            chapter_text[max(0, img_pos - 500) : min(len(chapter_text), img_pos + len(img_name) + 500)]
            if img_pos != -1 else gt_text[:1000]
        )
        image_b64 = encode_image(orig_path, max_pixels=1024)
        res = caller(image_b64, FIGURE_ENRICH_PROMPT.format(context_text=ctx), timeout=cfg.gemini_vision_timeout)
        if not res:
            return caption, alt_text

        parsed = _parse_json_block(res)
        new_caption, new_alt = parsed.get("caption", "").strip(), parsed.get("alt_text", "").strip()
        if new_caption and new_alt:
            caption, alt_text = new_caption, new_alt
            inventory[img_name.lower()] = {
                "path": str(orig_path), "filename": img_name, "book": book_name,
                "topology": fig_info.get("topology", "other") if fig_info else "other",
                "chapter_file": f"{chapter_stem}.md", "chapter_title": chapter_stem.replace("_", " "),
                "chapter_num": None, "surrounding_context": ctx[:1000],
                "caption": caption, "alt_text": alt_text,
            }
            _save_figure_inventory(inventory, inventory_path)
    except Exception as enrich_err:
        _logger.warning(f"Failed to enrich diagram {img_name} JIT: {enrich_err}")

    return caption, alt_text


def build_chapter_diagrams_catalog(
    book_name: str,
    chapter_stem: str,
    ground_truth_text: str,
    page: str,
    vision_caller: Callable[..., str] | None = None,
    inventory_path: Path | None = None,
) -> str:
    """Find publisher diagrams close to the Ground Truth in the chapter and build an XML catalog."""
    if not book_name or not chapter_stem or not ground_truth_text:
        return ""

    md_dir = find_book_md_dir(book_name)
    chapter_file = md_dir / f"{chapter_stem}.md" if md_dir else None
    if not md_dir or not chapter_file or not chapter_file.exists():
        return ""

    try:
        chapter_text = chapter_file.read_text(encoding="utf-8")
    except OSError:
        return ""

    from pipeline.ground_truth import find_images_around_ground_truth
    found_images = find_images_around_ground_truth(chapter_text, ground_truth_text)
    if not found_images:
        return ""

    if inventory_path is None:
        inventory_path = Path(__file__).parent.parent / "resources" / "figure_inventory.json"
    inventory = _load_figure_inventory(inventory_path)
    caller = _resolve_vision_caller(vision_caller)

    xml_lines = ["\n<CHAPTER_DIAGRAMS>"]
    for img_name in found_images:
        orig_path = md_dir / img_name
        if not orig_path.exists() or is_decorative_image(img_name, orig_path):
            continue

        dest_name = compute_adaptive_asset_name(book_name, chapter_stem, page, orig_path.stem)
        caption, alt_text = _enrich_diagram_metadata(
            img_name, orig_path, chapter_text, ground_truth_text,
            book_name, chapter_stem, caller, inventory, inventory_path,
        )
        xml_lines.extend(_format_diagram_xml(img_name, dest_name, caption, alt_text))

    xml_lines.append("</CHAPTER_DIAGRAMS>\n")
    return "\n".join(xml_lines) if len(xml_lines) > 2 else ""
