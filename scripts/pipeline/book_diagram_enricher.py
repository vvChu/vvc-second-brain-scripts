"""VvC Second Brain — Publisher Diagram Enricher & Catalog Builder.

Provides JIT Vision API enrichment for publisher diagrams, inventory persistence,
and XML catalog assembly for Ground Truth matching.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable

from core.config import cfg
from core.llm.utils import encode_image
from core.prompts.pipeline import FIGURE_ENRICH

_logger = logging.getLogger("vvc.book_assets.enricher")

FIGURE_ENRICH_PROMPT = FIGURE_ENRICH

__all__ = [
    "FIGURE_ENRICH_PROMPT",
    "_load_figure_inventory",
    "_resolve_vision_caller",
    "_save_figure_inventory",
    "_parse_json_block",
    "_format_diagram_xml",
    "_enrich_diagram_metadata",
    "build_chapter_diagrams_catalog",
]


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


def _read_chapter_file(book_name: str, chapter_stem: str) -> tuple[Path | None, str]:
    """Resolve markdown dir and read chapter text."""
    from pipeline.book_assets import find_book_md_dir

    md_dir = find_book_md_dir(book_name)
    chapter_file = md_dir / f"{chapter_stem}.md" if md_dir else None
    if not md_dir or not chapter_file or not chapter_file.exists():
        return None, ""
    try:
        return md_dir, chapter_file.read_text(encoding="utf-8")
    except OSError:
        return None, ""


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

    from pipeline.book_assets import compute_adaptive_asset_name, is_decorative_image
    from pipeline.ground_truth import find_images_around_ground_truth

    md_dir, chapter_text = _read_chapter_file(book_name, chapter_stem)
    if not md_dir or not chapter_text:
        return ""

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
