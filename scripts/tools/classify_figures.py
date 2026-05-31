"""VvC Second Brain — Figure Classification Tool (One-Time Use).

Scans all book figure images in 03 - Resources/books/*_MD/ directories,
classifies each figure's topology type using Vision API,
and outputs a structured inventory to resources/figure_inventory.json.

Usage:
    python scripts/tools/classify_figures.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from core.config import cfg
from core.llm.gateway_client import call_gateway_vision
from core.llm.utils import encode_image

_logger = logging.getLogger("vvc.classify_figures")

BOOKS_DIR = Path(cfg.vault_root) / "03 - Resources" / "books"
OUTPUT_PATH = _SCRIPT_DIR.parent / "resources" / "figure_inventory.json"

# Patterns to identify actual diagram figures (exclude covers, credits, photos)
_INCLUDE_PATTERNS = re.compile(
    r"(Figure|Table|Ch\d+_\d+|Ch\d+_Figure)", re.IGNORECASE
)
_EXCLUDE_PATTERNS = re.compile(
    r"(cover|credit|EPIGRAPH|TITLE|NOTES_|9\d{12})", re.IGNORECASE
)

TOPOLOGY_TYPES = [
    "hierarchy",    # org chart, tree, decomposition
    "hub_spoke",    # radial, star, central hub
    "matrix",       # 2x2, quadrant, scatter plot
    "flow",         # pipeline, value chain, process
    "cycle",        # feedback loop, PDCA
    "timeline",     # staircase, evolution, progression
    "pie",          # wheel, proportional breakdown
    "table",        # scorecard, comparison grid
    "other",        # hybrid, complex, not classifiable
]

from core.prompts.services import DIAGRAM_CLASSIFY as _CLASSIFY_PROMPT  # noqa: E402


def _scan_figures() -> list[Path]:
    """Scan books directory for diagram figure images.

    Returns:
        List of image paths that match diagram patterns.
    """
    figures: list[Path] = []

    for md_dir in BOOKS_DIR.iterdir():
        if not md_dir.is_dir() or not md_dir.name.endswith("_MD"):
            continue

        for img_path in md_dir.iterdir():
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue

            # Filter: include only likely diagrams
            name = img_path.name
            if _EXCLUDE_PATTERNS.search(name):
                continue
            if _INCLUDE_PATTERNS.search(name):
                figures.append(img_path)

    return sorted(figures)


def _parse_topology(result: str) -> str:
    """Parse topology type from LLM response string.

    Args:
        result: Raw LLM response.

    Returns:
        Matched topology type or 'other'.
    """
    result_lower = result.strip().lower().split()[0] if result.strip() else ""
    for t in TOPOLOGY_TYPES:
        if t in result_lower or result_lower in t:
            return t
    # Fuzzy match common synonyms
    if "tree" in result_lower or "org" in result_lower:
        return "hierarchy"
    if "hub" in result_lower or "radial" in result_lower or "star" in result_lower:
        return "hub_spoke"
    if "scatter" in result_lower or "quadrant" in result_lower:
        return "matrix"
    if "process" in result_lower or "pipeline" in result_lower or "chain" in result_lower:
        return "flow"
    if "loop" in result_lower or "pdca" in result_lower:
        return "cycle"
    if "evolution" in result_lower or "staircase" in result_lower:
        return "timeline"
    if "wheel" in result_lower or "proportion" in result_lower:
        return "pie"
    if "grid" in result_lower or "scorecard" in result_lower:
        return "table"
    return "other"


def _classify_figure(img_path: Path) -> str:
    """Classify a single figure image using Vision API.

    Calls Gateway directly to bypass is_garbage() which rejects short
    1-word classification responses (< 10 chars, e.g. 'hub_spoke' = 9).

    Args:
        img_path: Path to the image file.

    Returns:
        Topology type string.
    """
    try:
        # Call Gateway directly — avoids is_garbage() rejecting short 1-word responses
        image_b64 = encode_image(img_path, max_pixels=1024)
        result = call_gateway_vision(image_b64, _CLASSIFY_PROMPT, timeout=cfg.gemini_vision_timeout)
        if result:
            return _parse_topology(result)
        return "other"
    except Exception as e:
        _logger.warning(f"Classification failed for {img_path.name}: {e}")
        return "error"


def classify_all() -> dict:
    """Classify all figures and save inventory.

    Returns:
        Classification results dict.
    """
    figures = _scan_figures()
    _logger.info(f"Found {len(figures)} diagram figures to classify")

    results: dict = {
        "total_figures": len(figures),
        "figures": [],
        "summary": {t: 0 for t in TOPOLOGY_TYPES},
    }

    for i, fig_path in enumerate(figures):
        book_name = fig_path.parent.name.replace("_MD", "")
        _logger.info(f"[{i + 1}/{len(figures)}] Classifying: {fig_path.name}")

        topology = _classify_figure(fig_path)
        results["figures"].append({
            "path": str(fig_path),
            "filename": fig_path.name,
            "book": book_name,
            "topology": topology,
        })

        if topology in results["summary"]:
            results["summary"][topology] += 1

        # Throttle to avoid rate limits
        time.sleep(0.5)

    # Save inventory
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    _logger.info(f"Classification complete. Saved to: {OUTPUT_PATH}")
    _logger.info(f"Summary: {results['summary']}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    sys.stdout.reconfigure(encoding="utf-8")
    classify_all()
