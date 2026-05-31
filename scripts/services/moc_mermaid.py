"""VvC Second Brain — MOC Mermaid Diagram Generators.

Extracted from wiki_maintain.py to enforce Single Responsibility Principle.
Provides Mermaid flowchart generation for Source MOCs and Domain MOCs.

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


def wrap_label(text: str, max_chars: int = 15) -> str:
    """Wrap label text at word boundaries using <br> for neat visual layout in Mermaid nodes.

    Args:
        text: Label text to wrap.
        max_chars: Maximum characters per line.

    Returns:
        Text with <br> separators at word boundaries.
    """
    words = text.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0
    
    for word in words:
        added_len = len(word) + (1 if current_line else 0)
        if current_len + added_len > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
        else:
            current_line.append(word)
            current_len += added_len
            
    if current_line:
        lines.append(" ".join(current_line))
        
    return "<br>".join(lines)


def sanitize_mermaid(text: str) -> str:
    """Escape characters that break Mermaid syntax.

    Args:
        text: Raw text to sanitize.

    Returns:
        Mermaid-safe string with special chars replaced.
    """
    return (text.replace('"', "'").replace("(", "❨").replace(")", "❩")
            .replace("[", "❲").replace("]", "❳").replace("{", "❴")
            .replace("}", "❵").replace("<", "‹").replace(">", "›")
            .replace("&", "+").replace("#", "Nr"))


def generate_mermaid_flowchart(concepts_in_group: list[dict]) -> str:
    """Generate a clean, professional Mermaid flowchart TD representing connections between concepts.

    Used for Domain MOC diagrams.

    Args:
        concepts_in_group: List of concept dicts with _stem, related, and optionally _links.

    Returns:
        Mermaid diagram string inside a callout, or empty string if no edges.
    """
    # Find active stems in this group
    stems = {c["_stem"] for c in concepts_in_group}
    
    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    
    for c in concepts_in_group:
        stem = c["_stem"]
        
        # 1. Parse related links
        related = c.get("related", [])
        if isinstance(related, list):
            for rel in related:
                if isinstance(rel, list):
                    rel = rel[0] if rel else None
                if not isinstance(rel, str):
                    continue
                # Strip obsidian wiki brackets if present in the related string
                rel_cleaned = rel.replace("[[", "").replace("]]", "").strip()
                rel_norm = normalize_stem(rel_cleaned)
                if rel_norm in stems and rel_norm != stem:
                    edge = (stem, rel_norm)
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        edges.append(edge)
                        
        # 2. Parse links inside the body if they point to concepts in the same group
        links = c.get("_links")
        if links is None:
            # Lazy load links from file to support standalone runs and daemon triggers
            try:
                path = c.get("_path")
                if path and Path(path).exists():
                    content = Path(path).read_text(encoding="utf-8")
                    links = re.findall(r"\[\[([^\]|]+)", content)
                    c["_links"] = links
                else:
                    links = []
                    c["_links"] = []
            except OSError:
                links = []
                c["_links"] = []

        if isinstance(links, list):
            for link in links:
                normalized_link = normalize_stem(link)
                if normalized_link in stems and normalized_link != stem:
                    edge = (stem, normalized_link)
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        edges.append(edge)

    # If there are no connections, don't generate the diagram
    if not edges:
        return ""
        
    # Limit edges to 20 to prevent visual chaos
    if len(edges) > 20:
        edges = edges[:20]
        
    # Build diagram lines
    lines = [
        "\n> [!visual]- 🗺️ Sơ đồ Kết Nối Ý Niệm (Concept Map)\n",
        "> ```mermaid\n",
        "> flowchart TD\n",
        ">     %% Grayscale Academic Theme Style\n",
        ">     classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;\n"
    ]
    
    # Render nodes and edges
    unique_stems: set[str] = set()
    for src, tgt in edges:
        unique_stems.add(src)
        unique_stems.add(tgt)
        
    # Render node label maps
    for stem in sorted(unique_stems):
        # Find display title in group
        matching = [c for c in concepts_in_group if c["_stem"] == stem]
        title = matching[0].get("title", stem) if matching else stem
        # Trim title to 45 chars first if extremely long, then wrap it nicely
        trimmed_title = title[:45] + "..." if len(title) > 48 else title
        trimmed_title = trimmed_title.replace('"', "'").replace("(", "[").replace(")", "]")
        display_title = wrap_label(trimmed_title)
        lines.append(f'>     {stem}["{display_title}"]\n')
        
    # Render edges
    for src, tgt in sorted(edges):
        lines.append(f">     {src} --> {tgt}\n")
        
    lines.append("> ```\n\n")
    return "".join(lines)


def build_mermaid_overview(
    chapters: dict[str, list[dict]],
    all_concepts: list[dict],
    source_title: str,
) -> str:
    """Build a Mermaid flowchart for the MOC overview.

    Multi-chapter sources: chapter nodes + cross-links.
    Flat sources: top connected concept nodes.

    Args:
        chapters: Dict from group_by_chapter().
        all_concepts: All linked concepts.
        source_title: Display title for the hub node.

    Returns:
        Mermaid diagram string, or empty string if not enough data.
    """
    from services.moc_diagram import clean_chapter_name

    real_chapters = {k: v for k, v in chapters.items() if k != "_ungrouped"}
    has_chapters = len(real_chapters) >= 2

    if has_chapters:
        return _mermaid_chapter_overview(real_chapters, all_concepts, source_title)
    elif len(all_concepts) >= 3:
        return _mermaid_flat_overview(all_concepts)
    return ""


def _mermaid_chapter_overview(
    real_chapters: dict[str, list[dict]],
    all_concepts: list[dict],
    source_title: str,
) -> str:
    """Build chapter-level Mermaid flowchart.

    Args:
        real_chapters: Dict of real (non-ungrouped) chapters.
        all_concepts: All linked concepts.
        source_title: Display title for the hub node.

    Returns:
        Mermaid diagram string.
    """
    from services.moc_diagram import clean_chapter_name

    lines = ["flowchart TD"]
    safe_title = sanitize_mermaid(source_title[:50])
    lines.append(f'    HUB["{safe_title}"]')
    lines.append(f"    style HUB fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#000")

    ch_ids: dict[str, str] = {}
    for idx, (ch_key, ch_concepts) in enumerate(real_chapters.items()):
        ch_id = f"CH{idx}"
        ch_ids[ch_key] = ch_id
        display = sanitize_mermaid(clean_chapter_name(ch_key))
        lines.append(f'    {ch_id}["{display}<br/>({len(ch_concepts)} concepts)"]')
        lines.append(f"    style {ch_id} fill:#e0f2fe,stroke:#1e3a8a,stroke-width:1px,color:#000")
        lines.append(f"    HUB --- {ch_id}")

    # Find cross-chapter links
    concept_to_ch: dict[str, str] = {}
    for ch_key, ch_concepts in real_chapters.items():
        for c in ch_concepts:
            concept_to_ch[c["_stem"]] = ch_key

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

    for (ch_a, ch_b), count in cross_edges.items():
        if ch_a in ch_ids and ch_b in ch_ids:
            lines.append(f"    {ch_ids[ch_a]} -.-> |{count}| {ch_ids[ch_b]}")

    return "\n".join(lines) + "\n"


def _mermaid_flat_overview(all_concepts: list[dict]) -> str:
    """Build flat concept-level Mermaid graph for sources without chapters.

    Args:
        all_concepts: All linked concepts for this source.

    Returns:
        Mermaid diagram string, or empty string if no edges.
    """
    stems = {c["_stem"] for c in all_concepts}
    edges: list[tuple[str, str]] = []
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
                            edges.append((stem, rel_stem))
                            edge_count[stem] += 1
                            edge_count[rel_stem] += 1

    if not edges:
        return ""

    # Keep top 12 most-connected
    max_nodes = 12
    top_stems = sorted(edge_count, key=lambda s: edge_count[s], reverse=True)[:max_nodes]
    top_set = set(top_stems)
    edges = [(s, t) for s, t in edges if s in top_set and t in top_set][:20]

    stem_to_title: dict[str, str] = {}
    for c in all_concepts:
        if c["_stem"] in top_set:
            title = c.get("title", c["_stem"])
            if len(title) > 30:
                title = title[:27] + "..."
            stem_to_title[c["_stem"]] = title

    # Collect active stems from edges
    active: set[str] = set()
    for s, t in edges:
        active.add(s)
        active.add(t)

    lines = ["flowchart LR"]
    id_map: dict[str, str] = {}
    for idx, stem in enumerate(sorted(active)):
        nid = f"N{idx}"
        id_map[stem] = nid
        label = sanitize_mermaid(stem_to_title.get(stem, stem))
        lines.append(f'    {nid}["{label}"]')
        lines.append(f"    style {nid} fill:#f5f5f5,stroke:#334155,stroke-width:1px,color:#000")

    for s, t in edges:
        if s in id_map and t in id_map:
            lines.append(f"    {id_map[s]} --- {id_map[t]}")

    return "\n".join(lines) + "\n"


def format_concept_line(c: dict) -> str:
    """Format a single concept as a bullet point with visual indicators.

    Args:
        c: Concept dict with _stem, title, summary, status, confidence.

    Returns:
        Markdown bullet string.
    """
    title = c.get("title", c["_stem"])
    summary = c.get("summary", "")
    status = str(c.get("status", "seed")).lower()
    status_icon = "🌱" if status == "seed" else ("🌿" if status == "growing" else "🌳")
    confidence = str(c.get("confidence", "high")).lower()
    conf_indicator = " 🔍" if confidence in ("low", "medium") else ""
    return f"- {status_icon} [[{c['_stem']}|{title}]]{conf_indicator}{' — ' + summary if summary else ''}\n"


def flatten_source_list(src_val) -> list[str]:
    """Recursively flatten a potentially nested source list.

    Args:
        src_val: Source value — string, list, or nested list.

    Returns:
        Flat list of source strings.
    """
    result: list[str] = []
    if isinstance(src_val, str):
        result.append(src_val)
    elif isinstance(src_val, list):
        for item in src_val:
            result.extend(flatten_source_list(item))
    return result
