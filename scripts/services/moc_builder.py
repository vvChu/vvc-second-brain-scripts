"""VvC Second Brain — MOC Builder & Renderer Engine.

Coordinates the construction and formatting of:
- Source MOCs (MOC_<Name>.md) with chapters, concept lists, and overview diagrams
- Domain MOCs (Domain_<Name>.md) with cross-source grouping and flowchart diagrams
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from core.config import cfg
from core.frontmatter import normalize_stem
from core.taxonomy import DOMAIN_ALIASES, normalize_domain_tag
from services.moc_mermaid import (
    build_mermaid_overview as _build_mermaid_overview,
    clean_chapter_name,
    flatten_source_list,
    format_concept_line as _format_concept_line,
    generate_mermaid_flowchart as _generate_mermaid_flowchart,
    group_by_chapter,
)

_logger = logging.getLogger("vvc.maintain.moc_builder")

DOMAIN_MOC_THRESHOLD = 15


def normalize_moc_name(name: str) -> str:
    """Normalize a display name into a clean, accent-free Title_Cased MOC name."""
    name = name.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", name)
    name = normalized.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    return "_".join(w.capitalize() for w in name.split("_") if w)


def get_source_aliases(src: dict) -> list[str]:
    """Extract and normalize all aliases from a source dictionary."""
    raw = src.get("aliases", [])
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, str)]
    return []


def get_source_moc_display_name(src: dict) -> str:
    """Get canonical display name for Source MOC, filtering test prefixes."""
    src_stem = src.get("_stem", "")
    aliases = get_source_aliases(src)
    valid_aliases = [a for a in aliases if not a.lower().startswith("test_")]
    return valid_aliases[0] if valid_aliases else (aliases[0] if aliases else src.get("title", src_stem))


def render_source_moc_content(src: dict, linked_concepts: list[dict], moc_dir: Path | None = None) -> tuple[Path, str]:
    """Render Markdown content for a single Source MOC."""
    target_moc_dir = moc_dir or cfg.moc_dir
    src_stem = src["_stem"]
    display_name = get_source_moc_display_name(src)
    moc_name = normalize_moc_name(display_name)
    moc_path = target_moc_dir / "sources" / f"MOC_{moc_name}.md"

    chapters = group_by_chapter(linked_concepts)
    has_chapters = any(k != "_ungrouped" for k in chapters)

    lines = [
        f"# 🗺️ {display_name}\n\n",
        f"> [!abstract] **📌 Thông Tin Bản Đồ Nguồn**\n",
        f"> - 📖 **Nguồn gốc:** [[{src_stem}]]\n",
        f"> - 🧠 **Quy mô:** **{len(linked_concepts)}** khái niệm cốt lõi (Concepts)\n\n",
    ]

    mermaid = _build_mermaid_overview(chapters, linked_concepts, display_name)
    if mermaid:
        lines.append("> [!visual]- 🗺️ Sơ đồ Tổng Quan (Overview Map)\n")
        lines.append("> ```mermaid\n")
        for mline in mermaid.strip().splitlines():
            lines.append(f"> {mline}\n")
        lines.append("> ```\n\n")

    lines.append("---\n\n")
    if has_chapters:
        for ch_key, ch_concepts in chapters.items():
            if ch_key == "_ungrouped":
                if len(ch_concepts) < 1:
                    continue
                lines.append("## 📦 Khái Niệm Chưa Phân Loại\n\n")
            else:
                lines.append(f"## 📖 {clean_chapter_name(ch_key)}\n\n")

            for c in sorted(ch_concepts, key=lambda x: x.get("title", "")):
                lines.append(_format_concept_line(c))
            lines.append("\n")
    else:
        lines.append("## Concepts\n\n")
        for c in sorted(linked_concepts, key=lambda x: x.get("title", "")):
            lines.append(_format_concept_line(c))
        lines.append("\n")

    return moc_path, "".join(lines)


def render_domain_moc_content(
    domain: str,
    domain_concepts: list[dict],
    known_sources: set[str] | None = None,
    moc_dir: Path | None = None,
) -> tuple[Path, str]:
    """Render Markdown content for a single Domain MOC."""
    target_moc_dir = moc_dir or cfg.moc_dir
    display = domain.replace("_", " ").title()
    moc_name = normalize_moc_name(display)
    moc_path = target_moc_dir / "domains" / f"Domain_{moc_name}.md"

    by_source: dict[str, list[dict]] = defaultdict(list)
    for c in domain_concepts:
        src_val = c.get("source") or c.get("sources") or "unknown"
        for src in flatten_source_list(src_val):
            by_source[src].append(c)

    mermaid_graph = _generate_mermaid_flowchart(domain_concepts)
    lines = [
        f"# 🏷️ Domain: {display}\n\n",
        f"> [!abstract] **📌 Tổng Quan Lĩnh Vực**\n",
        f"> - 🧠 **Quy mô:** **{len(domain_concepts)}** khái niệm (Concepts)\n",
        f"> - 📖 **Phân bổ:** **{len(by_source)}** nguồn tri thức (Sources)\n\n",
    ]
    if mermaid_graph:
        lines.append(mermaid_graph)
    lines.append("---\n\n")

    for src, src_concepts in sorted(by_source.items()):
        norm_src = normalize_stem(src)
        if known_sources and norm_src in known_sources:
            lines.append(f"### From [[{src}]]\n\n")
        elif not known_sources and src not in ("web_imputed", "query_synthesis", "unknown", "LLM OS Pipeline v7.4", ""):
            lines.append(f"### From [[{src}]]\n\n")
        else:
            lines.append(f"### From {src}\n\n")

        for c in sorted(src_concepts, key=lambda x: x.get("title", "")):
            lines.append(_format_concept_line(c))
        lines.append("\n")

    return moc_path, "".join(lines)


def _map_concepts_to_sources(concepts: list[dict]) -> dict[str, list[dict]]:
    """Build lookup map from source references to concepts."""
    source_map: dict[str, list[dict]] = defaultdict(list)
    for c in concepts:
        src_val = c.get("source") or c.get("sources") or ""
        if src_val:
            for src in flatten_source_list(src_val):
                source_map[src].append(c)
                norm = normalize_stem(src)
                if norm != src:
                    source_map[norm].append(c)
    return source_map


def build_source_mocs(
    concepts: list[dict],
    sources: list[dict],
    write_fn: Callable[[Path, str], bool],
    moc_dir: Path | None = None,
) -> list[Path]:
    """Build MOC_*.md for each source book with Mermaid concept map diagrams."""
    source_map = _map_concepts_to_sources(concepts)
    active_paths: list[Path] = []

    for src in sources:
        src_stem = src["_stem"]
        keys_to_check = {src_stem, normalize_stem(src_stem)}
        for a in get_source_aliases(src):
            keys_to_check.add(a)
            keys_to_check.add(normalize_stem(a))

        seen_concepts: set[str] = set()
        linked_concepts: list[dict] = []
        for key in keys_to_check:
            for c in source_map.get(key, []):
                c_stem = c.get("_stem")
                if c_stem and c_stem not in seen_concepts:
                    seen_concepts.add(c_stem)
                    linked_concepts.append(c)

        if not linked_concepts:
            continue

        moc_path, content = render_source_moc_content(src, linked_concepts, moc_dir=moc_dir)
        active_paths.append(moc_path.resolve())
        write_fn(moc_path, content)

    return active_paths


def build_domain_mocs(
    concepts: list[dict],
    sources: list[dict] | None = None,
    write_fn: Callable[[Path, str], bool] | None = None,
    moc_dir: Path | None = None,
) -> list[Path]:
    """Build Domain_*.md for domains with enough concepts, formatting as visual dashboards."""
    domain_map: dict[str, list[dict]] = defaultdict(list)
    active_paths: list[Path] = []

    known_sources: set[str] = set()
    if sources:
        for s in sources:
            known_sources.add(normalize_stem(s.get("_stem", "")))
            for a in get_source_aliases(s):
                known_sources.add(normalize_stem(a))

    for c in concepts:
        for tag in c.get("tags", []):
            if isinstance(tag, str) and tag.startswith("domain/"):
                raw_domain = normalize_domain_tag(tag.split("/", 1)[1])
                domain = DOMAIN_ALIASES.get(raw_domain, raw_domain)
                domain_map[domain].append(c)

    for domain, domain_concepts in domain_map.items():
        if len(domain_concepts) < DOMAIN_MOC_THRESHOLD:
            continue

        moc_path, content = render_domain_moc_content(domain, domain_concepts, known_sources=known_sources, moc_dir=moc_dir)
        active_paths.append(moc_path.resolve())
        if write_fn:
            write_fn(moc_path, content)

    return active_paths
