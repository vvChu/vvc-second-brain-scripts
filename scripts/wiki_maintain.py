"""VvC Second Brain — Wiki Maintainer (v8.15.14).

Builds and maintains MOC pages, Domain MOCs, and the Master Index.

Usage:
    python wiki_maintain.py          # Manual full rebuild
    from wiki_maintain import rebuild_all, rebuild_incremental
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config import cfg
from core.file_lock import CrossProcessFileLock
from core.frontmatter import normalize_stem
from core.log import log
from core.taxonomy import (
    DOMAIN_ALIASES,
    GRAND_DOMAINS,
    normalize_domain_tag,
    resolve_grand_domains,
)
from core.vault import scan_all_concepts, scan_all_sources, update_concept_cache
from services.master_index import build_master_index
from services.moc_builder import (
    DOMAIN_MOC_THRESHOLD,
    build_domain_mocs,
    build_source_mocs,
    get_source_aliases,
    get_source_moc_display_name,
    normalize_moc_name,
    render_domain_moc_content,
    render_source_moc_content,
)
from services.moc_mermaid import flatten_source_list

_logger = logging.getLogger("vvc.maintain")
_normalize_domain_tag = normalize_domain_tag

# Re-exported for backward compatibility
_normalize_moc_name = normalize_moc_name
_get_source_aliases = get_source_aliases
_get_source_moc_display_name = get_source_moc_display_name


def _safe_write_text(path: Path, content: str) -> bool:
    """Write content to file only if it has changed, preventing sync storms.

    Returns:
        True if the file was written, False if content was identical.
    """
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _render_source_moc_content(src: dict, linked_concepts: list[dict]) -> tuple[Path, str]:
    """Render Markdown content for a single Source MOC."""
    return render_source_moc_content(src, linked_concepts, moc_dir=cfg.moc_dir)


def _render_domain_moc_content(
    domain: str,
    domain_concepts: list[dict],
    known_sources: set[str] | None = None,
) -> tuple[Path, str]:
    """Render Markdown content for a single Domain MOC."""
    return render_domain_moc_content(domain, domain_concepts, known_sources=known_sources, moc_dir=cfg.moc_dir)


def _build_source_mocs(concepts: list[dict], sources: list[dict]) -> list[Path]:
    """Build MOC_*.md for each source book with Mermaid concept map diagrams."""
    return build_source_mocs(concepts, sources, _safe_write_text, moc_dir=cfg.moc_dir)


def _build_domain_mocs(concepts: list[dict], sources: list[dict] | None = None) -> list[Path]:
    """Build Domain_*.md for domains with enough concepts, formatting as visual dashboards."""
    return build_domain_mocs(concepts, sources, _safe_write_text, moc_dir=cfg.moc_dir)


def _build_master_index(concepts: list[dict], sources: list[dict]) -> None:
    """Build the Master Index (index.md) featuring Kiệt Tác Chuyên Luận (Flagship Playbooks) showcase."""
    build_master_index(concepts, sources, _safe_write_text, moc_dir=cfg.moc_dir, index_file=cfg.index_file)


def _resolve_incremental_concept_data(concept: dict | Path) -> dict[str, Any] | None:
    """Resolve concept dictionary and refresh cache if path provided."""
    if isinstance(concept, Path):
        return update_concept_cache(concept)
    if isinstance(concept, dict) and "_path" in concept:
        update_concept_cache(concept["_path"])
    return concept


def _rebuild_incremental_sources(
    concept_data: dict[str, Any],
    all_concepts: list[dict[str, Any]],
    all_sources: list[dict[str, Any]],
) -> None:
    """Rebuild source MOCs linked to the given concept."""
    src_val = concept_data.get("source") or concept_data.get("sources") or ""
    if not src_val:
        return

    src_stems = flatten_source_list(src_val)
    for src_stem in src_stems:
        matched = next((s for s in all_sources if s.get("_stem") == src_stem), None)
        if not matched:
            continue
        linked = [
            c for c in all_concepts
            if src_stem in flatten_source_list(c.get("source") or c.get("sources") or "")
        ]
        if linked:
            moc_path, content = _render_source_moc_content(matched, linked)
            _safe_write_text(moc_path, content)


def _rebuild_incremental_domains(
    concept_data: dict[str, Any],
    all_concepts: list[dict[str, Any]],
    all_sources: list[dict[str, Any]],
) -> None:
    """Rebuild affected Domain MOCs if threshold is met."""
    known_sources = {normalize_stem(s.get("_stem", "")) for s in all_sources}
    for s in all_sources:
        for a in _get_source_aliases(s):
            known_sources.add(normalize_stem(a))

    tags = concept_data.get("tags", [])
    for tag in tags:
        if not (isinstance(tag, str) and tag.startswith("domain/")):
            continue
        raw_domain = _normalize_domain_tag(tag.split("/", 1)[1])
        domain = DOMAIN_ALIASES.get(raw_domain, raw_domain)
        domain_concepts = [
            c for c in all_concepts
            if any(
                DOMAIN_ALIASES.get(_normalize_domain_tag(t.split("/", 1)[1]), _normalize_domain_tag(t.split("/", 1)[1])) == domain
                for t in c.get("tags", [])
                if isinstance(t, str) and t.startswith("domain/")
            )
        ]
        if len(domain_concepts) >= DOMAIN_MOC_THRESHOLD:
            moc_path, content = _render_domain_moc_content(domain, domain_concepts, known_sources=known_sources)
            _safe_write_text(moc_path, content)


def rebuild_incremental(concept: dict | Path) -> None:
    """Incrementally update only affected MOCs and Master Index for a new/modified concept.

    Much faster than rebuild_all: avoids scanning or rewriting unaffected MOCs.
    """
    concept_data = _resolve_incremental_concept_data(concept)
    if not concept_data:
        return

    all_concepts = scan_all_concepts()
    all_sources = scan_all_sources()

    _rebuild_incremental_sources(concept_data, all_concepts, all_sources)
    _rebuild_incremental_domains(concept_data, all_concepts, all_sources)
    _build_master_index(all_concepts, all_sources)


def _cleanup_stale_mocs(active_paths: set[Path], preserved_names: set[str]) -> None:
    """Remove orphaned MOC and Domain files that are no longer active."""
    for f in list(cfg.moc_dir.rglob("*.md")):
        if f.name in preserved_names:
            continue
        if f.resolve() not in active_paths:
            if f.name.startswith("MOC_") or f.name.startswith("Domain_"):
                try:
                    f.unlink()
                    _logger.info(f"Cleaned up stale MOC file: {f.name}")
                except OSError as e:
                    _logger.warning(f"Failed to delete stale MOC file {f.name}: {e}")


def rebuild_all(concepts: list[dict] | None = None, sources: list[dict] | None = None) -> None:
    """Rebuild all MOCs and the Master Index, unlinking stale MOCs."""
    lock_file = cfg.state_dir / "wiki_maintain.lock"
    try:
        with CrossProcessFileLock(lock_file, timeout=60.0):
            if concepts is None:
                concepts = scan_all_concepts()
            if sources is None:
                sources = scan_all_sources()

            active_paths: set[Path] = set()
            active_paths.update(_build_source_mocs(concepts, sources))
            active_paths.update(_build_domain_mocs(concepts, sources))
            active_paths.add(cfg.index_file.resolve())
            if cfg.command_file:
                active_paths.add(Path(cfg.command_file).resolve())

            _cleanup_stale_mocs(active_paths, preserved_names={"Weekly_Synthesis.md"})
            _build_master_index(concepts, sources)

            _logger.info(f"Wiki maintained: {len(concepts)} concepts, {len(sources)} sources")
            log("lint", f"Rebuilt MOCs: {len(concepts)} concepts")
    except TimeoutError:
        _logger.warning("Another process is maintaining wiki; skipping concurrent rebuild")


# Canonical alias
maintain_wiki = rebuild_all


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    parser = argparse.ArgumentParser(description="VvC Second Brain — Wiki Maintainer")
    parser.add_argument("--check-only", action="store_true", help="Dry-run vault health check without modifying MOCs")
    parser.add_argument("--fix-code-pills", action="store_true", help="Automatically heal code-pill wikilinks")
    args = parser.parse_args()

    if args.check_only:
        from services.wiki_health import scan_wikilink_code_pills
        concepts = scan_all_concepts()
        sources = scan_all_sources()
        code_pills = scan_wikilink_code_pills(fix=args.fix_code_pills)
        print(f"Vault Verification: {len(concepts)} concepts, {len(sources)} sources.")
        if code_pills:
            print(f"WARNING: Found {len(code_pills)} files with code-pill wikilinks (total matches: {sum(c['count'] for c in code_pills)}):")
            for item in code_pills:
                print(f"  - {item['file']}: {item['count']} pills")
        else:
            print("Clean Wikilink Invariant check: PASS (0 code-pill wikilinks found).")
        print("Vault health check complete.")
    else:
        rebuild_all()
        print("Wiki maintenance complete.")
