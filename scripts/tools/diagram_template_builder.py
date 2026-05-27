"""VvC Second Brain — Diagram Template Builder (v1.0).

CLI tool to incrementally classify vault figures and auto-update
the Diagram Template Library (diagram_templates.yaml).

Usage:
    # Classify all unclassified figures (incremental)
    python scripts/tools/diagram_template_builder.py classify

    # Classify only one book's figures
    python scripts/tools/diagram_template_builder.py classify --book "Sieu_tang_truong_EOS"

    # Force re-classify everything
    python scripts/tools/diagram_template_builder.py classify --full-rebuild

    # Auto-update source_figure in diagram_templates.yaml
    python scripts/tools/diagram_template_builder.py update

    # Preview what update would do (no write)
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
sys.stdout.reconfigure(encoding="utf-8")
_logger = logging.getLogger("vvc.diagram_template_builder")

# ── Paths ──────────────────────────────────────────────────────────────────────

BOOKS_DIR = Path(cfg.vault_root) / "03 - Resources" / "books"
INVENTORY_PATH = _SCRIPT_DIR.parent / "resources" / "figure_inventory.json"
TEMPLATES_PATH = _SCRIPT_DIR.parent / "resources" / "diagram_templates.yaml"

# ── Constants ──────────────────────────────────────────────────────────────────

TOPOLOGY_TYPES = [
    "hierarchy",    # org chart, tree, decomposition
    "hub_spoke",    # radial, star, central hub
    "matrix",       # 2x2, quadrant, scatter plot
    "flow",         # pipeline, value chain, process stages
    "cycle",        # feedback loop, PDCA
    "timeline",     # staircase, evolution, milestones
    "pie",          # wheel, proportional breakdown
    "table",        # scorecard, comparison grid
    "other",        # hybrid, complex, not classifiable
]

_INCLUDE_PATTERNS = re.compile(
    r"(Figure|Table|Ch\d+_\d+|Ch\d+_Figure)", re.IGNORECASE
)
_EXCLUDE_PATTERNS = re.compile(
    r"(cover|credit|EPIGRAPH|TITLE|NOTES_|9\d{12})", re.IGNORECASE
)

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

# Throttle: 2 req/sec to avoid Gateway overload
_API_DELAY_SECONDS = 0.5


# ── Inventory I/O ──────────────────────────────────────────────────────────────

def _load_inventory() -> dict[str, Any]:
    """Load existing figure inventory or return empty skeleton.

    Returns:
        Inventory dict with 'figures' list and 'summary' dict.
    """
    if INVENTORY_PATH.exists():
        with open(INVENTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Migrate legacy schema (no 'confidence' or 'auto_classified' field)
        for fig in data.get("figures", []):
            fig.setdefault("confidence", 1.0)
            # Legacy entries (no 'auto_classified' key) were manually curated
            fig.setdefault("auto_classified", False)
        return data
    return {"total_figures": 0, "figures": [], "summary": {t: 0 for t in TOPOLOGY_TYPES}}



def _save_inventory(inventory: dict[str, Any]) -> None:
    """Persist inventory to disk.

    Args:
        inventory: Full inventory dict.
    """
    # Recompute summary
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


# ── Figure Scanning ────────────────────────────────────────────────────────────

def _scan_figures(book_filter: str | None = None) -> list[Path]:
    """Scan books directory for diagram figure images.

    Args:
        book_filter: Optional book name substring to filter (case-insensitive).

    Returns:
        Sorted list of image paths matching diagram patterns.
    """
    figures: list[Path] = []

    for md_dir in BOOKS_DIR.iterdir():
        if not md_dir.is_dir() or not md_dir.name.endswith("_MD"):
            continue
        if book_filter and book_filter.lower() not in md_dir.name.lower():
            continue

        for img_path in md_dir.iterdir():
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            name = img_path.name
            if _EXCLUDE_PATTERNS.search(name):
                continue
            if _INCLUDE_PATTERNS.search(name):
                figures.append(img_path)

    return sorted(figures)


# ── Topology Classification ────────────────────────────────────────────────────

def _parse_topology(result: str) -> tuple[str, float]:
    """Parse topology and confidence from LLM response.

    Note: Calls Gateway directly (not call_vision()) to bypass is_garbage()
    which incorrectly rejects short 1-word responses like 'flow' (4 chars).

    Args:
        result: Raw LLM text response.

    Returns:
        Tuple of (topology_type, confidence_score 0.0-1.0).
    """
    result_lower = result.strip().lower().split()[0] if result.strip() else ""

    # Direct match: highest confidence
    for t in TOPOLOGY_TYPES:
        if result_lower == t:
            return t, 1.0

    # Substring match: slightly lower confidence
    for t in TOPOLOGY_TYPES:
        if t in result_lower or result_lower in t:
            return t, 0.9

    # Fuzzy synonym matching: medium confidence
    synonyms: dict[str, tuple[str, float]] = {
        "tree": ("hierarchy", 0.85), "org": ("hierarchy", 0.85),
        "hub": ("hub_spoke", 0.85), "radial": ("hub_spoke", 0.85), "star": ("hub_spoke", 0.85),
        "scatter": ("matrix", 0.85), "quadrant": ("matrix", 0.85),
        "process": ("flow", 0.80), "pipeline": ("flow", 0.85), "chain": ("flow", 0.80),
        "loop": ("cycle", 0.85), "pdca": ("cycle", 0.90),
        "evolution": ("timeline", 0.85), "staircase": ("timeline", 0.90),
        "wheel": ("pie", 0.85), "proportion": ("pie", 0.80),
        "grid": ("table", 0.85), "scorecard": ("table", 0.90),
    }
    for word, (topo, conf) in synonyms.items():
        if word in result_lower:
            return topo, conf

    return "other", 0.7


def _classify_figure(img_path: Path) -> tuple[str, float]:
    """Classify a single figure image using Vision API.

    Calls Gateway directly to bypass is_garbage() which rejects short
    1-word classification responses (< 10 chars).

    Args:
        img_path: Path to the image file.

    Returns:
        Tuple of (topology_type, confidence_score).
    """
    try:
        image_b64 = encode_image(img_path, max_pixels=1024)
        result = call_gateway_vision(image_b64, _CLASSIFY_PROMPT, timeout=cfg.gemini_vision_timeout)
        if result:
            return _parse_topology(result)
        return "other", 0.5
    except Exception as e:
        _logger.warning(f"Classification failed for {img_path.name}: {e}")
        return "error", 0.0


# ── Command: classify ──────────────────────────────────────────────────────────

def cmd_classify(book: str | None = None, full_rebuild: bool = False) -> None:
    """Classify figures incrementally and update figure_inventory.json.

    Args:
        book: Optional book name filter.
        full_rebuild: If True, re-classify already-classified figures.
    """
    inventory = _load_inventory()
    existing_filenames: set[str] = {
        fig["filename"] for fig in inventory["figures"]
    }

    all_figures = _scan_figures(book_filter=book)
    _logger.info(f"Found {len(all_figures)} diagram figures in vault")

    # Filter: skip already classified unless full rebuild
    to_classify = all_figures if full_rebuild else [
        f for f in all_figures if f.name not in existing_filenames
    ]

    if not to_classify:
        _logger.info("Nothing new to classify. Use --full-rebuild to re-classify all.")
        _print_summary(inventory["summary"])
        return

    _logger.info(
        f"Classifying {len(to_classify)} figures "
        f"({'full rebuild' if full_rebuild else 'new only'})..."
    )

    # Remove existing entries for full rebuild
    if full_rebuild:
        inventory["figures"] = []

    new_count = 0
    error_count = 0

    for i, fig_path in enumerate(to_classify):
        book_name = fig_path.parent.name.replace("_MD", "")
        _logger.info(f"  [{i + 1}/{len(to_classify)}] {fig_path.name}")

        topology, confidence = _classify_figure(fig_path)

        if topology == "error":
            error_count += 1
        else:
            inventory["figures"].append({
                "path": str(fig_path),
                "filename": fig_path.name,
                "book": book_name,
                "topology": topology,
                "confidence": confidence,
                "auto_classified": True,  # Classified by this tool (not manually curated)
            })
            new_count += 1

        time.sleep(_API_DELAY_SECONDS)

    _save_inventory(inventory)
    _logger.info(f"\nDone. +{new_count} classified, {error_count} errors skipped.")
    _logger.info(f"Inventory saved: {INVENTORY_PATH}")
    _print_summary(inventory["summary"])


# ── Command: update ────────────────────────────────────────────────────────────

def cmd_update(dry_run: bool = False) -> None:
    """Auto-update source_figure in diagram_templates.yaml.

    Selects highest-confidence candidate per topology from inventory.
    Tie-breaking: prefer figures from EOS/Reinventing over other books.

    Args:
        dry_run: If True, print proposed changes without writing.
    """
    if not INVENTORY_PATH.exists():
        _logger.error(f"Inventory not found: {INVENTORY_PATH}. Run 'classify' first.")
        sys.exit(1)
    if not TEMPLATES_PATH.exists():
        _logger.error(f"Templates not found: {TEMPLATES_PATH}")
        sys.exit(1)

    inventory = _load_inventory()

    # Find best AUTO-CLASSIFIED candidate per topology
    # Legacy entries (auto_classified=False) are manually curated — don't override with them.
    best: dict[str, dict] = {}
    has_auto_classified = any(fig.get("auto_classified", False) for fig in inventory["figures"])

    if not has_auto_classified:
        _logger.info(
            "No auto-classified figures found in inventory.\n"
            "All existing entries are manually curated — nothing to auto-update.\n"
            "Run 'classify' first to classify new figures, then re-run 'update'."
        )
        return

    for fig in inventory["figures"]:
        if not fig.get("auto_classified", False):
            continue  # Skip manually curated legacy entries
        topo = fig.get("topology", "other")
        if topo in ("other", "error"):
            continue
        conf = fig.get("confidence", 1.0)
        current_best = best.get(topo)
        if current_best is None:
            best[topo] = fig
        else:
            current_conf = current_best.get("confidence", 1.0)
            if conf > current_conf:
                best[topo] = fig
            elif conf == current_conf:
                # Tie-break: prefer EOS or Reinventing sources
                preferred = ("EOS", "Reinventing")
                curr_is_preferred = any(p in current_best.get("book", "") for p in preferred)
                new_is_preferred = any(p in fig.get("book", "") for p in preferred)
                if new_is_preferred and not curr_is_preferred:
                    best[topo] = fig

    # Read YAML as raw text (preserve comments + formatting)
    yaml_text = TEMPLATES_PATH.read_text(encoding="utf-8")

    changes: list[tuple[str, str, str]] = []  # (topology, old, new)
    updated_yaml = yaml_text

    for topo, fig in best.items():
        new_filename = fig["filename"]
        confidence = fig.get("confidence", 1.0)

        # Find existing source_figure line for this topology in mermaid section
        # Pattern: matches "    source_figure: ..." under the topology block
        pattern = re.compile(
            rf'(  {topo}:.*?source_figure:\s*")([^"]*)(")' ,
            re.DOTALL,
        )
        match = pattern.search(updated_yaml)
        if match:
            old_filename = match.group(2)
            if old_filename != new_filename:
                changes.append((topo, old_filename, new_filename))
                new_line = f'{match.group(1)}{new_filename}{match.group(3)}'
                updated_yaml = updated_yaml[:match.start()] + new_line + updated_yaml[match.end():]
        else:
            # source_figure field doesn't exist yet — insert after 'source:' line
            src_pattern = re.compile(
                rf'(  {topo}:.*?source:\s*"[^"]*"\n)',
                re.DOTALL,
            )
            src_match = src_pattern.search(updated_yaml)
            if src_match:
                insert_after = src_match.end()
                new_field = f'    source_figure: "{new_filename}"  # auto-selected (confidence={confidence:.2f})\n'
                updated_yaml = updated_yaml[:insert_after] + new_field + updated_yaml[insert_after:]
                changes.append((topo, "(none)", new_filename))

    # Print changelog
    if not changes:
        _logger.info("No updates needed — all source_figure fields already optimal.")
        return

    _logger.info(f"\n{'DRY RUN — ' if dry_run else ''}Changes to diagram_templates.yaml:")
    _logger.info(f"  {'Topology':<12} {'Old':<45} {'New'}")
    _logger.info("  " + "-" * 90)
    for topo, old, new in changes:
        _logger.info(f"  {topo:<12} {old:<45} {new}")

    if dry_run:
        _logger.info("\nDry run complete. No files written.")
        return

    # Write updated YAML
    TEMPLATES_PATH.write_text(updated_yaml, encoding="utf-8")
    _logger.info(f"\nUpdated {len(changes)} source_figure field(s) in {TEMPLATES_PATH}")

    # Log topologies with no candidates
    no_candidate = [t for t in TOPOLOGY_TYPES if t not in best and t not in ("other", "error")]
    if no_candidate:
        _logger.info(f"NOTE: No candidates found for: {no_candidate} — keeping existing values.")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _print_summary(summary: dict[str, int]) -> None:
    """Print topology distribution table.

    Args:
        summary: Dict mapping topology type to count.
    """
    total = sum(summary.values())
    _logger.info(f"\n{'Topology':<12} {'Count':>6}  {'Bar'}")
    _logger.info("-" * 35)
    for topo in TOPOLOGY_TYPES:
        count = summary.get(topo, 0)
        bar = "█" * min(count, 40)
        _logger.info(f"{topo:<12} {count:>6}  {bar}")
    _logger.info(f"{'TOTAL':<12} {total:>6}")


# ── CLI Entry Point ────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="VvC Diagram Template Builder — classify figures and update templates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # classify subcommand
    classify_parser = subparsers.add_parser(
        "classify",
        help="Classify vault figures using Vision API (incremental by default)",
    )
    classify_parser.add_argument(
        "--book",
        type=str,
        default=None,
        metavar="BOOK_NAME",
        help="Filter by book name substring (case-insensitive)",
    )
    classify_parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Re-classify all figures, including already-classified ones",
    )

    # update subcommand
    update_parser = subparsers.add_parser(
        "update",
        help="Auto-update source_figure in diagram_templates.yaml",
    )
    update_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed changes without writing to disk",
    )

    args = parser.parse_args()

    if args.command == "classify":
        cmd_classify(book=args.book, full_rebuild=args.full_rebuild)
    elif args.command == "update":
        cmd_update(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
