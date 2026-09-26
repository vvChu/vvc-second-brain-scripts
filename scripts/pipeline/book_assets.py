"""VvC Second Brain — Publisher Diagram & Book Asset Seam.

Centralized Deep Module managing book corpus markdown scanning, publisher diagram discovery,
adaptive asset naming, WebP compression, and JIT diagram catalog enrichment.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from core.config import cfg
from core.frontmatter import normalize_stem, parse_frontmatter
from pipeline.book_diagram_enricher import (
    FIGURE_ENRICH_PROMPT,
    _enrich_diagram_metadata,
    _format_diagram_xml,
    _load_figure_inventory,
    _parse_json_block,
    _resolve_vision_caller,
    _save_figure_inventory,
    build_chapter_diagrams_catalog,
)

_logger = logging.getLogger("vvc.book_assets")

__all__ = [
    "find_book_md_dir",
    "is_decorative_image",
    "shorten_chapter",
    "compute_adaptive_asset_name",
    "align_book_diagrams",
    "build_chapter_diagrams_catalog",
    "FIGURE_ENRICH_PROMPT",
    "_load_figure_inventory",
    "_resolve_vision_caller",
    "_save_figure_inventory",
    "_parse_json_block",
    "_format_diagram_xml",
    "_enrich_diagram_metadata",
]


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
            (
                d
                for d in books_dir.iterdir()
                if d.is_dir()
                and d.name.endswith("_MD")
                and (norm_book in d.name.lower() or raw_book in d.name.lower())
            ),
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
