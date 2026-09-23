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


# Re-export consolidated diagram hygiene from diagram_base for backward compatibility
from services.diagram_base import sanitize_mermaid, wrap_label


def _get_node_label_and_indicator(concept_dict: dict, max_title_len: int = 45) -> str:
    """Helper to retrieve trimmed and decorated concept title with status & confidence icons,
    then word-wrap using <br>.
    """
    stem = concept_dict.get("_stem", "")
    title = str(concept_dict.get("title") or stem)
    
    # 1. Trim title
    trimmed_title = title[:max_title_len] + "..." if len(title) > (max_title_len + 3) else title
    
    # 2. Get status icon
    status = str(concept_dict.get("status", "seed")).lower()
    status_icon = "🌱" if status == "seed" else ("🌿" if status == "growing" else "🌳")
    
    # 3. Get confidence warning
    confidence = str(concept_dict.get("confidence", "high")).lower()
    conf_flag = " 🔍" if confidence in ("low", "medium") else ""
    
    # 4. Combine and sanitize
    decorated = f"{status_icon} {trimmed_title}{conf_flag}"
    sanitized = sanitize_mermaid(decorated)
    
    # 5. Wrap label
    return wrap_label(sanitized)


def _calculate_dynamic_caps(raw_edges: list[tuple[str, str]], all_stems: set[str]) -> tuple[int, int]:
    """Helper to calculate connectivity density ratio R and return dynamic limits for nodes and edges.
    
    Density R = num_edges / num_connected_nodes if num_connected_nodes > 0 else 0
    
    Thresholds calibrated on empirical vault data:
      R >= 1.5 (Dense): max_nodes = 12, max_edges = 18
      1.0 <= R < 1.5 (Moderate): max_nodes = 18, max_edges = 25
      R < 1.0 (Sparse): max_nodes = 25, max_edges = 35
    """
    # 1. Identify connected stems from edges
    connected_stems = set()
    for u, v in raw_edges:
        connected_stems.add(u)
        connected_stems.add(v)
        
    num_conn_nodes = len(connected_stems)
    num_edges = len(raw_edges)
    
    # 2. Calculate R
    R = num_edges / num_conn_nodes if num_conn_nodes > 0 else 0.0
    
    # 3. Determine caps
    if R >= 1.5:
        return 12, 18
    elif R >= 1.0:
        return 18, 25
    else:
        return 25, 35


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
    
    raw_edges: list[tuple[str, str]] = []
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
                        raw_edges.append(edge)
                        
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
                        raw_edges.append(edge)

    # If there are no connections, don't generate the diagram
    if not raw_edges:
        return ""

    # Compute unique undirected edges for density check
    unique_undirected_edges = {tuple(sorted(e)) for e in raw_edges}
    
    # Calculate dynamic caps based on density ratio
    max_nodes, max_edges = _calculate_dynamic_caps(list(unique_undirected_edges), stems)

    # Rank nodes by degree (number of connections in raw_edges)
    edge_count: defaultdict[str, int] = defaultdict(int)
    for u, v in raw_edges:
        edge_count[u] += 1
        edge_count[v] += 1
        
    top_stems = sorted(edge_count, key=lambda s: edge_count[s], reverse=True)[:max_nodes]
    top_set = set(top_stems)

    # Filter edges to only keep those connecting top nodes
    filtered_edges = [e for e in raw_edges if e[0] in top_set and e[1] in top_set]
    
    # Limit edges to max_edges
    final_edges = filtered_edges[:max_edges]
    if not final_edges:
        return ""

    # Find final active nodes to prevent orphans (orphan nodes are excluded)
    active_nodes = {u for u, v in final_edges} | {v for u, v in final_edges}

    # Build diagram lines
    lines = [
        "\n> [!visual]- 🗺️ Sơ đồ Kết Nối Ý Niệm (Concept Map)\n",
        "> ```mermaid\n",
        "> flowchart TD\n",
        ">     %% Grayscale Academic Theme Style\n",
        ">     classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;\n"
    ]
    
    # Map from stem to concept dict for quick lookup of status/confidence
    stem_to_concept = {c["_stem"]: c for c in concepts_in_group}

    # Render node label maps
    for stem in sorted(active_nodes):
        concept_dict = stem_to_concept.get(stem, {"_stem": stem})
        display_title = _get_node_label_and_indicator(concept_dict, max_title_len=45)
        lines.append(f'>     {stem}["{display_title}"]\n')
        
    # Render edges
    for src, tgt in sorted(final_edges):
        lines.append(f">     {src} --> {tgt}\n")
        
    lines.append("> ```\n\n")
    return "".join(lines)


def group_by_chapter(concepts: list[dict]) -> dict[str, list[dict]]:
    """Group concepts by ground_truth_chapter (fallback source_chapter).

    Args:
        concepts: List of concept dicts with frontmatter metadata.

    Returns:
        Dict mapping chapter key to list of concepts.
        Concepts without chapter → key "_ungrouped".
    """
    groups: dict[str, list[dict]] = {}

    for c in concepts:
        chapter = str(c.get("ground_truth_chapter", "")).strip()
        if not chapter:
            chapter = str(c.get("source_chapter", "")).strip()
        if not chapter:
            chapter = "_ungrouped"
        else:
            # Clean wiki-link brackets and quotes
            chapter = chapter.replace("[[", "").replace("]]", "")
            chapter = chapter.strip('"').strip("'").strip()

        groups.setdefault(chapter, []).append(c)

    return groups


def clean_chapter_name(raw: str) -> str:
    """Clean chapter key into a display-friendly name.

    Args:
        raw: Raw chapter string (e.g. "09_Chuong_6_Hop_phan_van_de").

    Returns:
        Cleaned display name (e.g. "Chuong 6 Hop Phan Van De").
    """
    # Remove leading number prefix like "07_" or "08_"
    name = re.sub(r"^\d+_", "", raw)
    # Replace underscores with spaces
    name = name.replace("_", " ")
    # Title case
    name = name.strip().title()
    # Trim if too long
    if len(name) > 40:
        name = name[:37] + "..."
    return name


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
    real_chapters = {k: v for k, v in chapters.items() if k != "_ungrouped"}
    has_chapters = len(real_chapters) >= 2

    if has_chapters:
        return _mermaid_chapter_overview(real_chapters, all_concepts, source_title)
    elif len(all_concepts) >= 3:
        return _mermaid_flat_overview(all_concepts, source_title)
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


def _mermaid_flat_overview(all_concepts: list[dict], source_title: str = "") -> str:
    """Build flat concept-level Mermaid graph for sources without chapters.

    Supports both interconnected graphs (when cross-links exist) and
    Hub-and-Spoke mind maps (when concepts are independent).

    Args:
        all_concepts: All linked concepts for this source.
        source_title: Display title for the hub node in Hub-and-Spoke mode.

    Returns:
        Mermaid diagram string, or empty string if not enough data.
    """
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

    # Map from stem to concept dict for quick lookup of status/confidence
    stem_to_concept = {c["_stem"]: c for c in all_concepts}

    # Case 1: Internal cross-links exist -> Interconnected graph
    if raw_edges:
        max_nodes, max_edges = _calculate_dynamic_caps(raw_edges, stems)
        top_stems = sorted(edge_count, key=lambda s: edge_count[s], reverse=True)[:max_nodes]
        top_set = set(top_stems)
        filtered_edges = [(s, t) for s, t in raw_edges if s in top_set and t in top_set]
        final_edges = filtered_edges[:max_edges]
        if final_edges:
            active: set[str] = set()
            for s, t in final_edges:
                active.add(s)
                active.add(t)

            lines = ["flowchart LR"]
            id_map: dict[str, str] = {}
            for idx, stem in enumerate(sorted(active)):
                nid = f"N{idx}"
                id_map[stem] = nid
                concept_dict = stem_to_concept.get(stem, {"_stem": stem})
                label = _get_node_label_and_indicator(concept_dict, max_title_len=30)
                lines.append(f'    {nid}["{label}"]')
                lines.append(f"    style {nid} fill:#f5f5f5,stroke:#334155,stroke-width:1px,color:#000")

            for s, t in final_edges:
                if s in id_map and t in id_map:
                    lines.append(f"    {id_map[s]} --- {id_map[t]}")

            return "\n".join(lines) + "\n"

    # Case 2: No internal cross-links but >= 3 concepts -> Hub-and-Spoke Mind Map
    if len(all_concepts) >= 3:
        lines = ["flowchart TD"]
        safe_hub_title = sanitize_mermaid(source_title[:45] if source_title else "Nguồn Tri Thức")
        lines.append(f'    HUB["📖 {safe_hub_title}"]')
        lines.append("    style HUB fill:#fef3c7,stroke:#92400e,stroke-width:2px,color:#000")

        # Select top concepts (up to 15) to keep diagram clean and readable
        selected_concepts = sorted(all_concepts, key=lambda x: x.get("title", ""))[:15]
        id_map: dict[str, str] = {}
        for idx, c in enumerate(selected_concepts):
            nid = f"N{idx}"
            stem = c["_stem"]
            id_map[stem] = nid
            label = _get_node_label_and_indicator(c, max_title_len=32)
            lines.append(f'    {nid}["{label}"]')
            lines.append(f"    style {nid} fill:#f8fafc,stroke:#475569,stroke-width:1px,color:#000")
            lines.append(f"    HUB --- {nid}")

        return "\n".join(lines) + "\n"

    return ""


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


def clean_source_reference(src: str) -> str:
    """Extract clean source stem from raw string, filename, or Obsidian wikilink.

    Handles:
        - "[[2024-01-01_Book_Title|Custom Title]]" -> "2024-01-01_Book_Title"
        - "[[2024-01-01_Book_Title]]" -> "2024-01-01_Book_Title"
        - "2024-01-01_Book_Title.md" -> "2024-01-01_Book_Title"
        - "2024-01-01_Book_Title" -> "2024-01-01_Book_Title"
    """
    s = src.strip()
    if s.startswith("[[") and "]]" in s:
        s = s[2:s.find("]]")].split("|")[0].strip()
    if s.endswith(".md"):
        s = s[:-3]
    return s


def flatten_source_list(src_val) -> list[str]:
    """Recursively flatten and normalize a potentially nested source list.

    Args:
        src_val: Source value — string, list, dict, or nested structure.

    Returns:
        Flat list of clean source stem strings.
    """
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

