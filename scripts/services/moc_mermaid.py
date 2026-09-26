"""VvC Second Brain — MOC Mermaid Diagram Generators.

Extracted from wiki_maintain.py to enforce Single Responsibility Principle.
Provides Mermaid flowchart generation for Source MOCs and Domain MOCs.
Source MOC diagram generators extracted to services/moc_source_diagram.py.

Functions:
    wrap_label: Word-wrap text using <br> for Mermaid node labels.
    generate_mermaid_flowchart: Concept connection graph for Domain MOCs.
    build_mermaid_overview: Router for Source MOC overview diagrams.
    format_concept_line: Format a concept as a Markdown bullet with icons.
    flatten_source_list: Recursively flatten nested source lists.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from core.frontmatter import normalize_stem
from services.diagram_base import sanitize_mermaid, wrap_label
from services.moc_source_diagram import (
    build_mermaid_overview,
    _mermaid_chapter_overview,
    _mermaid_flat_overview,
)

__all__ = [
    "wrap_label",
    "sanitize_mermaid",
    "generate_mermaid_flowchart",
    "build_mermaid_overview",
    "format_concept_line",
    "flatten_source_list",
    "group_by_chapter",
    "clean_chapter_name",
    "clean_source_reference",
]


def _get_node_label_and_indicator(concept_dict: dict, max_title_len: int = 45) -> str:
    """Helper to retrieve trimmed and decorated concept title with status & confidence icons."""
    stem = concept_dict.get("_stem", "")
    title = str(concept_dict.get("title") or stem)

    trimmed_title = title[:max_title_len] + "..." if len(title) > (max_title_len + 3) else title
    status = str(concept_dict.get("status", "seed")).lower()
    status_icon = "🌱" if status == "seed" else ("🌿" if status == "growing" else "🌳")

    confidence = str(concept_dict.get("confidence", "high")).lower()
    conf_flag = " 🔍" if confidence in ("low", "medium") else ""

    decorated = f"{status_icon} {trimmed_title}{conf_flag}"
    return wrap_label(sanitize_mermaid(decorated))


def _calculate_dynamic_caps(raw_edges: list[tuple[str, str]], all_stems: set[str]) -> tuple[int, int]:
    """Helper to calculate connectivity density ratio R and return dynamic limits for nodes and edges."""
    connected_stems = {u for u, v in raw_edges} | {v for u, v in raw_edges}
    num_conn_nodes = len(connected_stems)
    num_edges = len(raw_edges)

    R = num_edges / num_conn_nodes if num_conn_nodes > 0 else 0.0
    if R >= 1.5:
        return 12, 18
    elif R >= 1.0:
        return 18, 25
    return 25, 35


def _extract_concept_links(
    c: dict,
    stems: set[str],
    stem: str,
    seen_edges: set[tuple[str, str]],
    raw_edges: list[tuple[str, str]],
) -> None:
    """Extract related and body links from a concept note and append valid edges."""
    related = c.get("related", [])
    if isinstance(related, list):
        for rel in related:
            if isinstance(rel, list):
                rel = rel[0] if rel else None
            if not isinstance(rel, str):
                continue
            rel_cleaned = rel.replace("[[", "").replace("]]", "").strip()
            rel_norm = normalize_stem(rel_cleaned)
            if rel_norm in stems and rel_norm != stem:
                edge = (stem, rel_norm)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    raw_edges.append(edge)

    links = c.get("_links")
    if links is None:
        try:
            path = c.get("_path")
            if path and Path(path).exists():
                content = Path(path).read_text(encoding="utf-8")
                links = re.findall(r"\[\[([^\]|]+)", content)
            else:
                links = []
        except OSError:
            links = []
        c["_links"] = links

    if isinstance(links, list):
        for link in links:
            normalized_link = normalize_stem(link)
            if normalized_link in stems and normalized_link != stem:
                edge = (stem, normalized_link)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    raw_edges.append(edge)


def _extract_raw_edges(concepts_in_group: list[dict], stems: set[str]) -> list[tuple[str, str]]:
    """Scan all concepts in group to extract internal cross-link edges."""
    raw_edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for c in concepts_in_group:
        _extract_concept_links(c, stems, c["_stem"], seen_edges, raw_edges)
    return raw_edges


def _rank_and_filter_edges(
    raw_edges: list[tuple[str, str]],
    stems: set[str],
) -> list[tuple[str, str]]:
    """Rank nodes by degree and filter edges based on dynamic density caps."""
    unique_undirected = {tuple(sorted(e)) for e in raw_edges}
    max_nodes, max_edges = _calculate_dynamic_caps(list(unique_undirected), stems)

    edge_count: defaultdict[str, int] = defaultdict(int)
    for u, v in raw_edges:
        edge_count[u] += 1
        edge_count[v] += 1

    top_stems = sorted(edge_count, key=lambda s: edge_count[s], reverse=True)[:max_nodes]
    top_set = set(top_stems)
    filtered = [e for e in raw_edges if e[0] in top_set and e[1] in top_set]
    return filtered[:max_edges]


def generate_mermaid_flowchart(concepts_in_group: list[dict]) -> str:
    """Generate a clean, professional Mermaid flowchart TD for concepts in a Domain MOC."""
    stems = {c["_stem"] for c in concepts_in_group}
    raw_edges = _extract_raw_edges(concepts_in_group, stems)
    if not raw_edges:
        return ""

    final_edges = _rank_and_filter_edges(raw_edges, stems)
    if not final_edges:
        return ""

    active_nodes = {u for u, v in final_edges} | {v for u, v in final_edges}
    lines = [
        "\n> [!visual]- 🗺️ Sơ đồ Kết Nối Ý Niệm (Concept Map)\n",
        "> ```mermaid\n",
        "> flowchart TD\n",
        ">     %% Grayscale Academic Theme Style\n",
        ">     classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;\n",
    ]

    stem_to_concept = {c["_stem"]: c for c in concepts_in_group}
    for stem in sorted(active_nodes):
        concept_dict = stem_to_concept.get(stem, {"_stem": stem})
        display_title = _get_node_label_and_indicator(concept_dict, max_title_len=45)
        lines.append(f'>     {stem}["{display_title}"]\n')

    for src, tgt in sorted(final_edges):
        lines.append(f">     {src} --> {tgt}\n")

    lines.append("> ```\n\n")
    return "".join(lines)


def group_by_chapter(concepts: list[dict]) -> dict[str, list[dict]]:
    """Group concepts by ground_truth_chapter (fallback source_chapter)."""
    groups: dict[str, list[dict]] = {}
    for c in concepts:
        chapter = str(c.get("ground_truth_chapter", "")).strip() or str(c.get("source_chapter", "")).strip()
        if not chapter:
            chapter = "_ungrouped"
        else:
            chapter = chapter.replace("[[", "").replace("]]", "").strip('"').strip("'").strip()
        groups.setdefault(chapter, []).append(c)
    return groups


def clean_chapter_name(raw: str) -> str:
    """Clean chapter key into a display-friendly name."""
    name = re.sub(r"^\d+_", "", raw).replace("_", " ").strip().title()
    return name[:37] + "..." if len(name) > 40 else name


def format_concept_line(c: dict) -> str:
    """Format a single concept as a bullet point with visual indicators."""
    title = c.get("title", c["_stem"])
    summary = c.get("summary", "")
    status = str(c.get("status", "seed")).lower()
    status_icon = "🌱" if status == "seed" else ("🌿" if status == "growing" else "🌳")
    confidence = str(c.get("confidence", "high")).lower()
    conf_indicator = " 🔍" if confidence in ("low", "medium") else ""
    return f"- {status_icon} [[{c['_stem']}|{title}]]{conf_indicator}{' — ' + summary if summary else ''}\n"


def clean_source_reference(src: str) -> str:
    """Extract clean source stem from raw string, filename, or Obsidian wikilink."""
    s = src.strip()
    if s.startswith("[[") and "]]" in s:
        s = s[2:s.find("]]")].split("|")[0].strip()
    if s.endswith(".md"):
        s = s[:-3]
    return s


def flatten_source_list(src_val) -> list[str]:
    """Recursively flatten and normalize a potentially nested source list."""
    result: list[str] = []
    if isinstance(src_val, str):
        cleaned = clean_source_reference(src_val)
        if cleaned:
            result.append(cleaned)
    elif isinstance(src_val, dict):
        if "source" in src_val:
            result.extend(flatten_source_list(src_val["source"]))
    elif isinstance(src_val, list):
        for item in src_val:
            result.extend(flatten_source_list(item))
    return result
