"""VvC Second Brain — MOC Diagram Utilities.

Provides chapter grouping and name cleaning for MOC page generation.

Usage:
    from services.moc_diagram import group_by_chapter, clean_chapter_name
"""

from __future__ import annotations

import re


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
