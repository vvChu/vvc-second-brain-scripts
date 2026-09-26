"""VvC Second Brain — Source MOC Mermaid Overview Generator (v8.15.13).

Generates chapter-level and flat concept-level Mermaid overview diagrams
for Source MOCs in 00 - Maps of Content/sources/.
"""

from __future__ import annotations

import re
from collections import defaultdict

from core.frontmatter import normalize_stem
from services.diagram_base import sanitize_mermaid


def _build_interconnected_graph(
    raw_edges: list[tuple[str, str]],
    stems: set[str],
    edge_count: defaultdict[str, int],
    stem_to_concept: dict[str, dict],
    get_label_fn,
    calc_caps_fn,
) -> str:
    """Build interconnected Mermaid flowchart LR for concepts with internal cross-links."""
    max_nodes, max_edges = calc_caps_fn(raw_edges, stems)
    top_stems = sorted(edge_count, key=lambda s: edge_count[s], reverse=True)[:max_nodes]
    top_set = set(top_stems)
    filtered = [(s, t) for s, t in raw_edges if s in top_set and t in top_set][:max_edges]
    if not filtered:
        return ""

    active: set[str] = set()
    for s, t in filtered:
        active.add(s)
        active.add(t)

    lines = ["flowchart LR"]
    id_map: dict[str, str] = {}
    for idx, stem in enumerate(sorted(active)):
        nid = f"N{idx}"
        id_map[stem] = nid
        concept_dict = stem_to_concept.get(stem, {"_stem": stem})
        label = get_label_fn(concept_dict, max_title_len=30)
        lines.append(f'    {nid}["{label}"]')
        lines.append(f"    style {nid} fill:#f5f5f5,stroke:#334155,stroke-width:1px,color:#000")

    for s, t in filtered:
        if s in id_map and t in id_map:
            lines.append(f"    {id_map[s]} --- {id_map[t]}")

    return "\n".join(lines) + "\n"


def _build_hub_and_spoke_graph(
    all_concepts: list[dict],
    source_title: str,
    get_label_fn,
) -> str:
    """Build Hub-and-Spoke mind map flowchart TD for independent concepts."""
    lines = ["flowchart TD"]
    safe_hub_title = sanitize_mermaid(source_title[:45] if source_title else "Nguồn Tri Thức")
    lines.append(f'    HUB["📖 {safe_hub_title}"]')
    lines.append("    style HUB fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#000")

    selected = sorted(all_concepts, key=lambda x: x.get("title", ""))[:15]
    for idx, c in enumerate(selected):
        nid = f"N{idx}"
        label = get_label_fn(c, max_title_len=32)
        lines.append(f'    {nid}["{label}"]')
        lines.append(f"    style {nid} fill:#f8fafc,stroke:#475569,stroke-width:1px,color:#000")
        lines.append(f"    HUB --- {nid}")

    return "\n".join(lines) + "\n"


def _mermaid_flat_overview(
    all_concepts: list[dict],
    source_title: str = "",
    get_label_fn=None,
    calc_caps_fn=None,
) -> str:
    """Build flat concept-level Mermaid graph for sources without chapters."""
    if get_label_fn is None or calc_caps_fn is None:
        from services.moc_mermaid import _get_node_label_and_indicator, _calculate_dynamic_caps
        get_label_fn = get_label_fn or _get_node_label_and_indicator
        calc_caps_fn = calc_caps_fn or _calculate_dynamic_caps

    stems = {c["_stem"] for c in all_concepts}
    raw_edges: list[tuple[str, str]] = []
    edge_count: defaultdict[str, int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()

    for c in all_concepts:
        stem = c["_stem"]
        related = c.get("related", [])
        if isinstance(related, list):
            for rel in related:
                if isinstance(rel, list):
                    rel = rel[0] if rel else None
                if isinstance(rel, str):
                    rel_stem = normalize_stem(rel.replace("[[", "").replace("]]", ""))
                    if rel_stem in stems and rel_stem != stem:
                        edge = tuple(sorted([stem, rel_stem]))
                        if edge not in seen:
                            seen.add(edge)
                            raw_edges.append((stem, rel_stem))
                            edge_count[stem] += 1
                            edge_count[rel_stem] += 1

    stem_to_concept = {c["_stem"]: c for c in all_concepts}
    if raw_edges:
        res = _build_interconnected_graph(raw_edges, stems, edge_count, stem_to_concept, get_label_fn, calc_caps_fn)
        if res:
            return res

    if len(all_concepts) >= 3:
        return _build_hub_and_spoke_graph(all_concepts, source_title, get_label_fn)

    return ""


def _extract_cross_chapter_edges(
    all_concepts: list[dict],
    concept_to_ch: dict[str, str],
) -> dict[tuple[str, str], int]:
    """Find and count cross-chapter links between concepts."""
    cross_edges: dict[tuple[str, str], int] = {}
    for c in all_concepts:
        src_ch = concept_to_ch.get(c["_stem"])
        if not src_ch:
            continue
        related = c.get("related", [])
        if isinstance(related, list):
            for rel in related:
                if isinstance(rel, list):
                    rel = rel[0] if rel else None
                if isinstance(rel, str):
                    rel_stem = normalize_stem(rel.replace("[[", "").replace("]]", ""))
                    tgt_ch = concept_to_ch.get(rel_stem)
                    if tgt_ch and tgt_ch != src_ch:
                        edge = tuple(sorted([src_ch, tgt_ch]))
                        cross_edges[edge] = cross_edges.get(edge, 0) + 1
    return cross_edges


def _mermaid_chapter_overview(
    real_chapters: dict[str, list[dict]],
    all_concepts: list[dict],
    source_title: str,
    clean_chapter_fn=None,
) -> str:
    """Build chapter-level Mermaid flowchart."""
    if clean_chapter_fn is None:
        from services.moc_mermaid import clean_chapter_name
        clean_chapter_fn = clean_chapter_name

    lines = ["flowchart TD"]
    safe_title = sanitize_mermaid(source_title[:50])
    lines.append(f'    HUB["{safe_title}"]')
    lines.append("    style HUB fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#000")

    ch_ids: dict[str, str] = {}
    for idx, (ch_key, ch_concepts) in enumerate(real_chapters.items()):
        ch_id = f"CH{idx}"
        ch_ids[ch_key] = ch_id
        display = sanitize_mermaid(clean_chapter_fn(ch_key))
        lines.append(f'    {ch_id}["{display}<br/>({len(ch_concepts)} concepts)"]')
        lines.append(f"    style {ch_id} fill:#e0f2fe,stroke:#1e3a8a,stroke-width:1px,color:#000")
        lines.append(f"    HUB --- {ch_id}")

    concept_to_ch: dict[str, str] = {}
    for ch_key, ch_concepts in real_chapters.items():
        for c in ch_concepts:
            concept_to_ch[c["_stem"]] = ch_key

    cross_edges = _extract_cross_chapter_edges(all_concepts, concept_to_ch)
    for (ch_a, ch_b), count in cross_edges.items():
        if ch_a in ch_ids and ch_b in ch_ids:
            lines.append(f"    {ch_ids[ch_a]} -.-> |{count}| {ch_ids[ch_b]}")

    return "\n".join(lines) + "\n"


def build_mermaid_overview(
    chapters: dict[str, list[dict]],
    all_concepts: list[dict],
    source_title: str,
) -> str:
    """Build a Mermaid flowchart for the MOC overview."""
    real_chapters = {k: v for k, v in chapters.items() if k != "_ungrouped"}
    if len(real_chapters) >= 2:
        return _mermaid_chapter_overview(real_chapters, all_concepts, source_title)
    if len(all_concepts) >= 3:
        return _mermaid_flat_overview(all_concepts, source_title)
    return ""
