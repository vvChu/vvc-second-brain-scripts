"""VvC Second Brain — Diagram Template Builder (v1.0).

CLI tool to incrementally classify vault figures and auto-update
the Diagram Template Library (diagram_templates.yaml).

Usage:
    python scripts/tools/diagram_template_builder.py classify
    python scripts/tools/diagram_template_builder.py classify --book "Sieu_tang_truong_EOS"
    python scripts/tools/diagram_template_builder.py classify --full-rebuild
    python scripts/tools/diagram_template_builder.py update
    python scripts/tools/diagram_template_builder.py update --dry-run
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

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
_logger = logging.getLogger("vvc.diagram_template_builder")

BOOKS_DIR = Path(cfg.vault_root) / "03 - Resources" / "books"
INVENTORY_PATH = _SCRIPT_DIR.parent / "resources" / "figure_inventory.json"
TEMPLATES_PATH = _SCRIPT_DIR.parent / "resources" / "diagram_templates.yaml"

TOPOLOGY_TYPES = [
    "hierarchy", "hub_spoke", "matrix", "flow",
    "cycle", "timeline", "pie", "table", "other",
]

_INCLUDE_PATTERNS = re.compile(r"(Figure|Table|Ch\d+_\d+|Ch\d+_Figure)", re.IGNORECASE)
_EXCLUDE_PATTERNS = re.compile(r"(cover|credit|EPIGRAPH|TITLE|NOTES_|9\d{12})", re.IGNORECASE)
_API_DELAY_SECONDS = 0.5

_SYNONYMS: dict[str, tuple[str, float]] = {
    "tree": ("hierarchy", 0.85), "org": ("hierarchy", 0.85),
    "hub": ("hub_spoke", 0.85), "radial": ("hub_spoke", 0.85), "star": ("hub_spoke", 0.85),
    "scatter": ("matrix", 0.85), "quadrant": ("matrix", 0.85),
    "process": ("flow", 0.80), "pipeline": ("flow", 0.85), "chain": ("flow", 0.80),
    "loop": ("cycle", 0.85), "pdca": ("cycle", 0.90),
    "evolution": ("timeline", 0.85), "staircase": ("timeline", 0.90),
    "wheel": ("pie", 0.85), "proportion": ("pie", 0.80),
    "grid": ("table", 0.85), "scorecard": ("table", 0.90),
}

_CLASSIFY_PROMPT = """Classify this diagram image into EXACTLY ONE of these topology types:

TYPES:
- hierarchy: tree, org chart, decomposition, parent-child structure
- hub_spoke: central hub connecting to satellites, star/radial layout
- matrix: 2x2 quadrant, scatter plot, two-axis comparison
- flow: left-to-right or sequential pipeline, value chain, process stages
- cycle: circular feedback loop, PDCA wheel, iterative process
- timeline: progression over time, staircase, evolution, milestones
- pie: proportional breakdown, wheel with segments, percentage chart
- table: structured rows/columns, scorecard, comparison grid
- other: complex hybrid or not classifiable as above

OUTPUT: Reply with ONLY the type name (one word). Nothing else."""


def _load_inventory() -> dict[str, Any]:
    """Load existing figure inventory or return empty skeleton."""
    if INVENTORY_PATH.exists():
        with open(INVENTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for fig in data.get("figures", []):
            fig.setdefault("confidence", 1.0)
            fig.setdefault("auto_classified", False)
        return data
    return {"total_figures": 0, "figures": [], "summary": {t: 0 for t in TOPOLOGY_TYPES}}


def _save_inventory(inventory: dict[str, Any]) -> None:
    """Persist inventory to disk with recalculated summary."""
    summary = {t: 0 for t in TOPOLOGY_TYPES}
    for fig in inventory["figures"]:
        topo = fig.get("topology", "other")
        if topo in summary:
            summary[topo] += 1
    inventory["summary"] = summary
    inventory["total_figures"] = len(inventory["figures"])

    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INVENTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)


def _scan_figures(book_filter: str | None = None) -> list[Path]:
    """Scan books directory for diagram figure images."""
    figures: list[Path] = []
    if not BOOKS_DIR.exists():
        return figures

    for md_dir in BOOKS_DIR.iterdir():
        if not md_dir.is_dir() or not md_dir.name.endswith("_MD"):
            continue
        if book_filter and book_filter.lower() not in md_dir.name.lower():
            continue
        for img in md_dir.iterdir():
            if img.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                if not _EXCLUDE_PATTERNS.search(img.name) and _INCLUDE_PATTERNS.search(img.name):
                    figures.append(img)
    return sorted(figures)


def _parse_topology(result: str) -> tuple[str, float]:
    """Parse topology and confidence from LLM response."""
    result_lower = result.strip().lower().split()[0] if result.strip() else ""
    for t in TOPOLOGY_TYPES:
        if result_lower == t:
            return t, 1.0
    for t in TOPOLOGY_TYPES:
        if t in result_lower or result_lower in t:
            return t, 0.9
    for word, (topo, conf) in _SYNONYMS.items():
        if word in result_lower:
            return topo, conf
    return "other", 0.7


def _classify_figure(img_path: Path) -> tuple[str, float]:
    """Classify a single figure image using Vision API."""
    try:
        image_b64 = encode_image(img_path, max_pixels=1024)
        result = call_gateway_vision(image_b64, _CLASSIFY_PROMPT, timeout=cfg.gemini_vision_timeout)
        return _parse_topology(result) if result else ("other", 0.5)
    except Exception as e:
        _logger.warning(f"Classification failed for {img_path.name}: {e}")
        return "error", 0.0


def _run_classification_loop(to_classify: list[Path], inventory: dict[str, Any]) -> tuple[int, int]:
    """Classify figure batch with rate limiting and append valid results."""
    new_count, error_count = 0, 0
    for i, fig_path in enumerate(to_classify):
        _logger.info(f"  [{i + 1}/{len(to_classify)}] {fig_path.name}")
        topology, confidence = _classify_figure(fig_path)
        if topology == "error":
            error_count += 1
        else:
            inventory["figures"].append({
                "path": str(fig_path),
                "filename": fig_path.name,
                "book": fig_path.parent.name.replace("_MD", ""),
                "topology": topology,
                "confidence": confidence,
                "auto_classified": True,
            })
            new_count += 1
        time.sleep(_API_DELAY_SECONDS)
    return new_count, error_count


def cmd_classify(book: str | None = None, full_rebuild: bool = False) -> None:
    """Classify figures incrementally and update figure_inventory.json."""
    inventory = _load_inventory()
    existing_filenames = {fig["filename"] for fig in inventory["figures"]}
    all_figures = _scan_figures(book_filter=book)
    _logger.info(f"Found {len(all_figures)} diagram figures in vault")

    to_classify = all_figures if full_rebuild else [f for f in all_figures if f.name not in existing_filenames]
    if not to_classify:
        _logger.info("Nothing new to classify. Use --full-rebuild to re-classify all.")
        _print_summary(inventory["summary"])
        return

    _logger.info(f"Classifying {len(to_classify)} figures ({'full rebuild' if full_rebuild else 'new only'})...")
    if full_rebuild:
        inventory["figures"] = []

    new_count, error_count = _run_classification_loop(to_classify, inventory)
    _save_inventory(inventory)
    _logger.info(f"\nDone. +{new_count} classified, {error_count} errors skipped.")
    _logger.info(f"Inventory saved: {INVENTORY_PATH}")
    _print_summary(inventory["summary"])


def _find_best_candidates(figures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Find the best auto-classified candidate per topology with tie-breaking."""
    best: dict[str, dict[str, Any]] = {}
    preferred = ("EOS", "Reinventing")
    for fig in figures:
        if not fig.get("auto_classified", False):
            continue
        topo = fig.get("topology", "other")
        if topo in ("other", "error"):
            continue
        conf = fig.get("confidence", 1.0)
        curr = best.get(topo)
        if curr is None or conf > curr.get("confidence", 1.0):
            best[topo] = fig
        elif conf == curr.get("confidence", 1.0):
            curr_pref = any(p in curr.get("book", "") for p in preferred)
            new_pref = any(p in fig.get("book", "") for p in preferred)
            if new_pref and not curr_pref:
                best[topo] = fig
    return best


def _apply_template_updates(yaml_text: str, best: dict[str, dict[str, Any]]) -> tuple[str, list[tuple[str, str, str]]]:
    """Patch source_figure fields into raw diagram templates YAML string."""
    changes: list[tuple[str, str, str]] = []
    updated = yaml_text
    for topo, fig in best.items():
        new_name, conf = fig["filename"], fig.get("confidence", 1.0)
        match = re.search(rf'(  {topo}:.*?source_figure:\s*")([^"]*)(")', updated, re.DOTALL)
        if match:
            old_name = match.group(2)
            if old_name != new_name:
                changes.append((topo, old_name, new_name))
                new_line = f'{match.group(1)}{new_name}{match.group(3)}'
                updated = updated[:match.start()] + new_line + updated[match.end():]
        else:
            src_match = re.search(rf'(  {topo}:.*?source:\s*"[^"]*"\n)', updated, re.DOTALL)
            if src_match:
                insert_pos = src_match.end()
                new_field = f'    source_figure: "{new_name}"  # auto-selected (confidence={conf:.2f})\n'
                updated = updated[:insert_pos] + new_field + updated[insert_pos:]
                changes.append((topo, "(none)", new_name))
    return updated, changes


def cmd_update(dry_run: bool = False) -> None:
    """Auto-update source_figure in diagram_templates.yaml."""
    if not INVENTORY_PATH.exists() or not TEMPLATES_PATH.exists():
        _logger.error("Missing inventory or templates path. Exiting.")
        sys.exit(1)

    inventory = _load_inventory()
    best = _find_best_candidates(inventory.get("figures", []))
    if not best:
        _logger.info("No auto-classified figures found in inventory to update.")
        return

    yaml_text = TEMPLATES_PATH.read_text(encoding="utf-8")
    updated_yaml, changes = _apply_template_updates(yaml_text, best)
    if not changes:
        _logger.info("No updates needed — all source_figure fields already optimal.")
        return

    _logger.info(f"\n{'DRY RUN — ' if dry_run else ''}Changes to diagram_templates.yaml:")
    _logger.info(f"  {'Topology':<12} {'Old':<45} {'New'}")
    _logger.info("  " + "-" * 90)
    for topo, old, new in changes:
        _logger.info(f"  {topo:<12} {old:<45} {new}")

    if not dry_run:
        TEMPLATES_PATH.write_text(updated_yaml, encoding="utf-8")
        _logger.info(f"\nUpdated {len(changes)} source_figure field(s) in {TEMPLATES_PATH}")


def _print_summary(summary: dict[str, int]) -> None:
    """Print topology distribution table."""
    total = sum(summary.values())
    _logger.info(f"\n{'Topology':<12} {'Count':>6}  {'Bar'}")
    _logger.info("-" * 35)
    for topo in TOPOLOGY_TYPES:
        count = summary.get(topo, 0)
        bar = "█" * min(count, 40)
        _logger.info(f"{topo:<12} {count:>6}  {bar}")
    _logger.info(f"{'TOTAL':<12} {total:>6}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="VvC Diagram Template Builder — classify figures and update templates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify_parser = subparsers.add_parser("classify", help="Classify vault figures using Vision API")
    classify_parser.add_argument("--book", type=str, default=None, metavar="BOOK_NAME", help="Filter by book name")
    classify_parser.add_argument("--full-rebuild", action="store_true", help="Re-classify all figures")

    update_parser = subparsers.add_parser("update", help="Auto-update source_figure in diagram_templates.yaml")
    update_parser.add_argument("--dry-run", action="store_true", help="Print proposed changes without writing")

    args = parser.parse_args()
    if args.command == "classify":
        cmd_classify(book=args.book, full_rebuild=args.full_rebuild)
    elif args.command == "update":
        cmd_update(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
