"""VvC Second Brain — Wiki Health: Vault Linter.

Single-pass read-only diagnostics across all vault knowledge surfaces:
orphans, broken links, prospective related seeds, missing frontmatter,
tag clusters, duplicate title prefixes, and code-pill links.
Part of Deep Module package services.wiki_health.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from core.config import cfg
from core.frontmatter import normalize_stem
from core.log import log
from core.vault import scan_all_concepts, scan_all_sources
from .code_pill_cleaner import _CODE_PILL_LINK_PATTERN

_logger = logging.getLogger("vvc.health.linter")

_LINK_PATTERN = re.compile(r"\[\[([^\]|]+)")
MEDIA_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".mp3", ".mp4"}


class LintReport(TypedDict, total=False):
    orphans: List[str]
    broken_links: List[Dict[str, str]]
    missing_frontmatter: List[Dict[str, List[str]]]
    duplicates: List[List[str]]
    bridge_candidates: List[str]
    tag_clusters: Dict[str, int]
    total_concepts: int
    broken_body_links: List[Dict[str, str]]
    prospective_related_seeds: List[Dict[str, str]]
    code_pill_wikilinks: List[Dict[str, Any]]


class VaultLinter:
    """Handles 6 health checks for the vault using a single-pass optimized strategy."""

    def __init__(self):
        self.concepts = scan_all_concepts()

        # Ensure _links is populated (cached by scan_all_concepts)
        for c in self.concepts:
            if "_links" not in c:
                try:
                    content = c["_path"].read_text(encoding="utf-8")
                    c["_links"] = _LINK_PATTERN.findall(content)
                except OSError:
                    c["_links"] = []

        self.existing_stems = {normalize_stem(c["_stem"]) for c in self.concepts}
        for c in self.concepts:
            aliases = c.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias and isinstance(alias, str):
                        self.existing_stems.add(normalize_stem(alias))

        # Load sources to prevent false broken links to source documents
        sources = scan_all_sources()
        for s in sources:
            self.existing_stems.add(normalize_stem(s["_stem"]))
            aliases = s.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias and isinstance(alias, str):
                        self.existing_stems.add(normalize_stem(alias))

        # Load MOC directory files to prevent false broken links to MOCs, Command, index, etc.
        for f in cfg.moc_dir.rglob("*.md"):
            self.existing_stems.add(normalize_stem(f.stem))

        # Load topic files to prevent false broken links to topics
        topics_dir = cfg.vault_root / "04 - Permanent" / "topics"
        if topics_dir.exists():
            for f in topics_dir.iterdir():
                if f.suffix == ".md":
                    self.existing_stems.add(normalize_stem(f.stem))

        # Load book corpus chapter files to prevent false broken links to source_chapter/ground_truth_chapter
        if cfg.resources_books_dir.exists():
            for f in cfg.resources_books_dir.rglob("*.md"):
                self.existing_stems.add(normalize_stem(f.stem))

        # Load fleeting notes to prevent false broken links to Brain_Dump, Command, etc.
        for fleeting_file in [cfg.dump_file, cfg.command_file]:
            if fleeting_file.exists():
                self.existing_stems.add(normalize_stem(fleeting_file.stem))

    def _evaluate_concept_metrics(
        self,
        c: dict,
        report: LintReport,
        all_linked: set,
        by_prefix: dict,
    ) -> None:
        """Helper to process a single concept during linting."""
        stem = c["_stem"]

        # Check 1: Missing frontmatter (support both 'source' and 'sources' from merged notes)
        has_source = bool(c.get("source") or c.get("sources"))
        missing = [f for f in ["title", "type", "tags"] if not c.get(f)]
        if not has_source:
            missing.append("source")
        if missing:
            report["missing_frontmatter"].append({"file": stem, "missing": missing})

        # Check 2: Tag clusters
        for tag in c.get("tags", []):
            if tag.startswith("domain/"):
                report["tag_clusters"][tag] += 1

        # Check 3: Broken links (ignore media file attachments)
        rel_field = c.get("related", [])
        rel_str = " ".join(str(r) for r in rel_field) if isinstance(rel_field, list) else str(rel_field)

        for link in c.get("_links", []):
            lower_link = link.lower()
            if any(lower_link.endswith(ext) for ext in MEDIA_EXTENSIONS):
                continue
            normalized = normalize_stem(link)
            all_linked.add(normalized)
            if normalized not in self.existing_stems:
                is_frontmatter_related = link in rel_str or normalized in normalize_stem(rel_str)
                origin = "frontmatter_related" if is_frontmatter_related else "body"
                broken_item = {"from": stem, "to": link, "origin": origin}
                report["broken_links"].append(broken_item)
                if origin == "body":
                    report["broken_body_links"].append(broken_item)
                else:
                    report["prospective_related_seeds"].append(broken_item)

        # Check 4: Prefix for duplicates
        prefix = normalize_stem(c.get("title", ""))[:20]
        if prefix:
            by_prefix[prefix].append(stem)

        # Check 5: Code-pill wikilinks
        try:
            raw_content = c["_path"].read_text(encoding="utf-8")
            pills = _CODE_PILL_LINK_PATTERN.findall(raw_content)
            if pills:
                report["code_pill_wikilinks"].append({
                    "file": stem,
                    "type": "concept",
                    "count": len(pills),
                    "matches": pills,
                })
        except OSError:
            pass

    def lint(self) -> LintReport:
        report: LintReport = {
            "orphans": [],
            "broken_links": [],
            "missing_frontmatter": [],
            "duplicates": [],
            "bridge_candidates": [],
            "tag_clusters": defaultdict(int),
            "total_concepts": len(self.concepts),
            "broken_body_links": [],
            "prospective_related_seeds": [],
            "code_pill_wikilinks": [],
        }

        all_linked = set()
        by_prefix: dict[str, list] = defaultdict(list)

        # Single pass through all concepts
        for c in self.concepts:
            self._evaluate_concept_metrics(c, report, all_linked, by_prefix)

        # Ingest outgoing links from Maps of Content (MOCs), Sources, and Topics to eliminate False Orphans
        for moc_file in cfg.moc_dir.rglob("*.md"):
            if moc_file.name == "Weekly_Synthesis.md":
                continue
            try:
                content = moc_file.read_text(encoding="utf-8")
                for link in _LINK_PATTERN.findall(content):
                    all_linked.add(normalize_stem(link))
            except OSError:
                pass

        if cfg.sources_dir.exists():
            for src_file in cfg.sources_dir.rglob("*.md"):
                try:
                    content = src_file.read_text(encoding="utf-8")
                    for link in _LINK_PATTERN.findall(content):
                        all_linked.add(normalize_stem(link))
                except OSError:
                    pass

        topics_dir = cfg.vault_root / "04 - Permanent" / "topics"
        if topics_dir.exists():
            for topic_file in topics_dir.glob("*.md"):
                try:
                    content = topic_file.read_text(encoding="utf-8")
                    for link in _LINK_PATTERN.findall(content):
                        all_linked.add(normalize_stem(link))
                    pills = _CODE_PILL_LINK_PATTERN.findall(content)
                    if pills:
                        report["code_pill_wikilinks"].append({
                            "file": topic_file.stem,
                            "type": "topic",
                            "count": len(pills),
                            "matches": pills,
                        })
                except OSError:
                    pass

        # Check 5: Orphans (Post-pass evaluation)
        for c in self.concepts:
            stem_norm = normalize_stem(c["_stem"])
            if stem_norm not in all_linked and c.get("type") == "concept":
                if not c.get("related", []):
                    report["orphans"].append(c["_stem"])

        # Check 6: Populate duplicates
        for prefix, items in by_prefix.items():
            if len(items) > 1:
                report["duplicates"].append(items)

        _logger.info(
            f"Lint: {len(report['orphans'])} orphans, "
            f"{len(report['broken_links'])} broken links ({len(report['broken_body_links'])} in body, {len(report['prospective_related_seeds'])} in frontmatter), "
            f"{len(report['missing_frontmatter'])} missing FM"
        )
        log("lint", f"Health check: {report['total_concepts']} concepts scanned, {len(report['orphans'])} true orphans")
        return report


def lint_vault() -> LintReport:
    """Run 6 health checks on the vault (Facade pattern)."""
    return VaultLinter().lint()


__all__ = [
    "LintReport",
    "_LINK_PATTERN",
    "MEDIA_EXTENSIONS",
    "VaultLinter",
    "lint_vault",
]
