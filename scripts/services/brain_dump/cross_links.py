"""VvC Second Brain — Brain Dump Dual-Layer Cross-Linking Engine.

Coordinates two-way linking between Source Notes (transcripts) and Concept Notes:
- Concept Note -> Source Note: appends ^ts deep-link anchors to ## References
- Source Note -> Concept Note: injects 📎 backlinks into ^ts callouts
"""

from __future__ import annotations

import logging
import re

_logger = logging.getLogger("vvc.dump.cross_links")


def _enrich_concept_references(concept_text: str, source_ref: str) -> str:
    """Enriches ## References section with precise chronological anchor-links."""
    if not source_ref or source_ref == "brain_dump":
        return concept_text

    img_matches = re.findall(r"!\[\[yt_[^\]]+_ts(\d+)\.webp\]\]", concept_text)
    if not img_matches:
        return concept_text

    timestamps = sorted(list(set(int(ts) for ts in img_matches)))
    links = [
        f"  - [[{source_ref}#^ts{ts}|Xem slide và ngữ cảnh chi tiết tại [{int(ts//60):02d}:{int(ts%60):02d}] trong ghi chép gốc]]"
        for ts in timestamps
    ]
    if not links:
        return concept_text

    target_pattern = rf"-\s*\[\[{re.escape(source_ref)}(?:\|[^\]]*)?]]"
    match = re.search(target_pattern, concept_text)
    if match:
        original_ref = match.group(0)
        enriched_ref = original_ref + "\n" + "\n".join(links)
        concept_text = concept_text.replace(original_ref, enriched_ref, 1)

    return concept_text


def _build_ts_concept_map(saved_stems: list[tuple[str, str]]) -> dict[int, list[tuple[str, str]]]:
    """Scan saved concept files and build mapping from image timestamps to concepts."""
    import services.brain_dump.concept_synthesis as cs

    ts_to_concepts: dict[int, list[tuple[str, str]]] = {}
    for stem, title in saved_stems:
        concept_file = cs.cfg.concepts_dir / f"{stem}.md"
        if not concept_file.exists():
            continue
        try:
            text = concept_file.read_text(encoding="utf-8")
        except OSError:
            continue

        for m in re.finditer(r"yt_[^\]]+_ts(\d+)\.webp", text):
            ts = int(m.group(1))
            if (stem, title) not in ts_to_concepts.get(ts, []):
                ts_to_concepts.setdefault(ts, []).append((stem, title))
    return ts_to_concepts


def _insert_backlinks_into_lines(
    lines: list[str],
    ts_to_concepts: dict[int, list[tuple[str, str]]],
    source_text: str,
) -> tuple[list[str], bool]:
    """Insert concept backlinks into lines after matching ^ts callout blocks."""
    new_lines: list[str] = []
    i = 0
    modified = False

    while i < len(lines):
        new_lines.append(lines[i])
        ts_anchor = re.search(r"\^ts(\d+)", lines[i])
        if ts_anchor:
            ts = int(ts_anchor.group(1))
            concepts = ts_to_concepts.get(ts)
            if concepts:
                while i + 1 < len(lines) and lines[i + 1].startswith(">"):
                    i += 1
                    new_lines.append(lines[i])
                for stem, title in concepts:
                    backlink = f"> 📎 [[{stem}|{title}]]"
                    if backlink not in source_text:
                        new_lines.append(backlink)
                        modified = True
        i += 1

    return new_lines, modified


def _backlink_source_to_concepts(source_ref: str, saved_stems: list[tuple[str, str]]) -> None:
    """Inserts backlinks from Source Note ^ts callouts to referencing Concept Notes."""
    import services.brain_dump.concept_synthesis as cs

    if not source_ref or source_ref == "brain_dump" or not saved_stems:
        return

    source_file = cs.cfg.sources_dir / "transcripts" / f"{source_ref}.md"
    if not source_file.exists():
        return

    ts_to_concepts = _build_ts_concept_map(saved_stems)
    if not ts_to_concepts:
        return

    try:
        source_text = source_file.read_text(encoding="utf-8")
    except OSError:
        return

    lines = source_text.split("\n")
    new_lines, modified = _insert_backlinks_into_lines(lines, ts_to_concepts, source_text)

    if modified:
        try:
            source_file.write_text("\n".join(new_lines), encoding="utf-8")
            _logger.info(f"Two-way cross-linked {len(ts_to_concepts)} anchors in Source Note: {source_ref}")
        except OSError as e:
            _logger.warning(f"Failed to backlink Source Note: {e}")
