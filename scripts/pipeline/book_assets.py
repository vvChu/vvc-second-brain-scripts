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


def align_book_diagrams(content: str, book_name: str) -> str:
    """Scan original book corpus MD files to find and align crisp publisher diagrams."""
    if not book_name:
        return content

    # 1. Parse frontmatter
    fm = parse_frontmatter(content)
    gt_ch = fm.get("ground_truth_chapter")
    if not gt_ch:
        return content

    # Extract clean chapter stem from wiki-link
    chapter_stem = str(gt_ch).replace("[[", "").replace("]]", "").strip()
    if not chapter_stem:
        return content

    # OCR page and ground truth page for metadata resolution
    page = str(fm.get("source_page", "")).strip()
    if not page:
        page = str(fm.get("ground_truth_page", "")).strip()

    # 2. Find book MD corpus folder
    md_dir = find_book_md_dir(book_name)
    if not md_dir or not md_dir.exists():
        _logger.debug(f"[JIT Image] MD directory not found for book: {book_name}")
        return content

    # 3. Locate chapter file
    chapter_file = md_dir / f"{chapter_stem}.md"
    if not chapter_file.exists():
        _logger.debug(f"[JIT Image] Chapter file '{chapter_stem}.md' not found in {md_dir}")
        return content

    try:
        chapter_text = chapter_file.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning(f"[JIT Image] Failed to read chapter file: {e}")
        return content

    # 4. Extract Ground Truth paragraphs from note content
    gt_section_match = re.search(
        r"## (?:📖|Ground Truth)[^\n]*\n+(.*?)(?:\n\n---|\n\n##|\Z)",
        content,
        re.DOTALL,
    )
    if not gt_section_match:
        _logger.debug("[JIT Image] No Ground Truth section found in note content")
        return content

    gt_block = gt_section_match.group(1)

    # 5. Search for images around Ground Truth in the chapter file
    from pipeline.ground_truth import find_images_around_ground_truth
    found_images = find_images_around_ground_truth(chapter_text, gt_block)
    if not found_images:
        _logger.debug("[JIT Image] No book images found close to Ground Truth in chapter")
        return content

    # 6. Process, copy, and compress original images
    aligned_images: list[str] = []
    book_slug = normalize_stem(book_name)[:30].rstrip("_")

    for img_name in found_images:
        original_img_path = md_dir / img_name
        if not original_img_path.exists():
            _logger.debug(f"[JIT Image] Original image file {img_name} not found in {md_dir}")
            continue

        # Filter decorative/tiny images
        if is_decorative_image(img_name, original_img_path):
            _logger.debug(f"[JIT Image] Filtered decorative image: {img_name}")
            continue

        dest_name = compute_adaptive_asset_name(
            book_name, chapter_stem, page, original_img_path.stem
        )

        assets_dir = cfg.assets_dir / book_slug
        dest_path = assets_dir / dest_name

        # Compress to WebP or copy
        if not dest_path.exists():
            try:
                from PIL import Image as PILImage
                img = PILImage.open(original_img_path)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)
                assets_dir.mkdir(parents=True, exist_ok=True)
                img.save(dest_path, "WEBP", quality=80)
                _logger.info(f"[JIT Image] Compressed and saved original image: {original_img_path.name} -> {dest_path.name}")
            except Exception as e:
                _logger.warning(f"[JIT Image] WebP compression failed for {original_img_path.name}: {e}. Falling back to copy.")
                dest_path_raw = dest_path.with_suffix(original_img_path.suffix)
                try:
                    assets_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(original_img_path), str(dest_path_raw))
                    _logger.info(f"[JIT Image] Copied original image (fallback): {original_img_path.name} -> {dest_path_raw.name}")
                    dest_name = dest_path_raw.name
                except Exception as copy_err:
                    _logger.warning(f"[JIT Image] Copy failed completely: {copy_err}")
                    continue

        aligned_images.append(dest_name)

    if not aligned_images:
        return content

    # 7. Embed aligned images right before ## 📖 Ground Truth section
    gt_heading_match = re.search(r"## (?:📖|Ground Truth)", content)
    if gt_heading_match:
        idx = gt_heading_match.start()
        embed_lines = []
        for dest_name in aligned_images:
            embed_syntax = f"![[{dest_name}]]"
            if embed_syntax not in content:
                embed_lines.append(f"\n{embed_syntax}\n")
        if embed_lines:
            embed_block = "".join(embed_lines)
            content = content[:idx].rstrip() + "\n" + embed_block + "\n" + content[idx:]
            _logger.info(f"[JIT Image] Successfully aligned {len(aligned_images)} original image(s) to concept note")

    return content


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
    if not md_dir or not md_dir.exists():
        return ""

    chapter_file = md_dir / f"{chapter_stem}.md"
    if not chapter_file.exists():
        return ""

    try:
        chapter_text = chapter_file.read_text(encoding="utf-8")
    except OSError:
        return ""

    from pipeline.ground_truth import find_images_around_ground_truth
    found_images = find_images_around_ground_truth(chapter_text, ground_truth_text)
    if not found_images:
        return ""

    # Load figure inventory if exists to fetch caption & alt-text
    if inventory_path is None:
        inventory_path = Path(__file__).parent.parent / "resources" / "figure_inventory.json"
    inventory = {}
    if inventory_path.exists():
        try:
            with open(inventory_path, "r", encoding="utf-8") as f:
                inv_data = json.load(f)
                for fig in inv_data.get("figures", []):
                    inventory[fig["filename"].lower()] = fig
        except Exception:
            pass

    # Resolve vision caller (checking monkeypatch on image_processor if any)
    if vision_caller is None:
        ip_mod = sys.modules.get("pipeline.image_processor")
        if ip_mod and hasattr(ip_mod, "call_gateway_vision"):
            vision_caller = getattr(ip_mod, "call_gateway_vision")
        else:
            from core.llm.gateway_client import call_gateway_vision
            vision_caller = call_gateway_vision

    xml_lines = ["\n<CHAPTER_DIAGRAMS>"]

    for img_name in found_images:
        original_img_path = md_dir / img_name
        if not original_img_path.exists():
            continue
        if is_decorative_image(img_name, original_img_path):
            continue

        dest_name = compute_adaptive_asset_name(
            book_name, chapter_stem, page, original_img_path.stem
        )

        fig_info = inventory.get(img_name.lower())
        caption = fig_info.get("caption") if fig_info else ""
        alt_text = fig_info.get("alt_text") if fig_info else ""

        if not caption or not alt_text:
            _logger.info(f"JIT Diagram Enrichment triggered for: {img_name}")
            try:
                img_pos = chapter_text.find(img_name)
                if img_pos != -1:
                    context_window = chapter_text[max(0, img_pos - 500) : min(len(chapter_text), img_pos + len(img_name) + 500)]
                else:
                    context_window = ground_truth_text[:1000]

                image_b64 = encode_image(original_img_path, max_pixels=1024)
                formatted_prompt = FIGURE_ENRICH_PROMPT.format(context_text=context_window)
                llm_result = vision_caller(
                    image_b64,
                    formatted_prompt,
                    timeout=cfg.gemini_vision_timeout,
                )
                if llm_result:
                    clean_result = llm_result.strip()
                    if clean_result.startswith("```"):
                        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_result, re.DOTALL)
                        if json_match:
                            clean_result = json_match.group(1)

                    parsed_res = json.loads(clean_result)
                    new_caption = parsed_res.get("caption", "").strip()
                    new_alt = parsed_res.get("alt_text", "").strip()

                    if new_caption and new_alt:
                        caption = new_caption
                        alt_text = new_alt
                        # Update inventory JIT
                        inventory[img_name.lower()] = {
                            "path": str(original_img_path),
                            "filename": img_name,
                            "book": book_name,
                            "topology": fig_info.get("topology", "other") if fig_info else "other",
                            "chapter_file": f"{chapter_stem}.md",
                            "chapter_title": chapter_stem.replace("_", " "),
                            "chapter_num": None,
                            "surrounding_context": context_window[:1000],
                            "caption": caption,
                            "alt_text": alt_text,
                        }
                        # Save back to figure_inventory.json
                        try:
                            inventory_data = {"figures": list(inventory.values())}
                            with open(inventory_path, "w", encoding="utf-8") as f_out:
                                json.dump(inventory_data, f_out, ensure_ascii=False, indent=2)
                            _logger.info(f"Successfully saved enriched diagram JIT: {img_name}")
                        except Exception as save_err:
                            _logger.warning(f"Failed to save figure_inventory.json during JIT: {save_err}")
            except Exception as enrich_err:
                _logger.warning(f"Failed to enrich diagram {img_name} JIT: {enrich_err}")

        xml_lines.append("  <DIAGRAM>")
        xml_lines.append(f"    <FILENAME>{img_name}</FILENAME>")
        xml_lines.append(f"    <ADAPTIVE_NAME>{dest_name}</ADAPTIVE_NAME>")
        if caption:
            xml_lines.append(f"    <CAPTION>{caption}</CAPTION>")
        if alt_text:
            xml_lines.append(f"    <ALT_TEXT>{alt_text}</ALT_TEXT>")
        xml_lines.append("  </DIAGRAM>")

    xml_lines.append("</CHAPTER_DIAGRAMS>\n")

    if len(xml_lines) <= 2:
        return ""

    return "\n".join(xml_lines)
