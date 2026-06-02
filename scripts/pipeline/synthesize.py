"""VvC Second Brain — Concept Synthesis Stage (v7.0).

LLM generates atomic concept notes in Format v2 (Properties-First, Minimalist Body).
"""

from __future__ import annotations

import logging
import re
from datetime import date as dt_date
from pathlib import Path

from core.llm import call_llm

_logger = logging.getLogger("vvc.synth")

from core.prompts.pipeline import CONCEPT_SYNTHESIS as _SYNTHESIS_PROMPT



def synthesize_concept(
    highlighted: str,
    context: str,
    ground_truth: str,
    *,
    source_name: str = "",
    source_ref: str = "",
    chapter: str = "",
    page: str = "",
    gt_page: str = "",
    gt_chapter: str = "",
    today: str = "",
    book_macro_context: str = "",
    chapter_diagrams: str = "",
) -> str:
    """Generate an atomic concept note from OCR-extracted content.

    Args:
        highlighted: Highlighted/underlined text from OCR.
        context: Surrounding context text.
        ground_truth: English Ground Truth paragraph.
        source_name: Display name of the book.
        source_ref: Source note wiki reference.
        chapter: Chapter file reference.
        page: Page number string.
        today: Today's date (YYYY-MM-DD).
        book_macro_context: Optional XML book macro context block from _context.txt.

    Returns:
        Complete concept note content (frontmatter + body), or empty string on failure.
    """
    if not today:
        today = dt_date.today().isoformat()

    source_display = source_name or source_ref

    chapter_clean = chapter or ""
    if chapter_clean == "(không rõ)":
        chapter_clean = ""
    chapter_ref = f"[[{chapter_clean}]]" if chapter_clean else ""

    gt_chapter_clean = gt_chapter or ""
    if gt_chapter_clean == "(không rõ)":
        gt_chapter_clean = ""
    gt_chapter_ref = f"[[{gt_chapter_clean}]]" if gt_chapter_clean else ""

    prompt = _SYNTHESIS_PROMPT.format(
        book_macro_context=book_macro_context or "Không có thông tin nền vĩ mô.",
        highlighted=highlighted,
        context=context,
        ground_truth=ground_truth or "(không có)",
        source_name=source_name,
        source_ref=source_ref,
        source_display=source_display,
        chapter=chapter or "(không rõ)",
        chapter_ref=chapter_ref,
        page=page or "",
        gt_page=gt_page or "",
        gt_chapter_ref=gt_chapter_ref,
        today=today,
        ground_truth_excerpt=ground_truth if ground_truth else "(không có)",
        chapter_diagrams=chapter_diagrams,
    )

    result = call_llm(prompt, task="synthesis")

    if not result or len(result) < 100:
        _logger.error("Synthesis returned empty/short result")
        return ""

    # Strip markdown code fences if LLM wrapped the output
    result = re.sub(r"^```(?:markdown|md)?\s*\n", "", result)
    result = re.sub(r"\n```\s*$", "", result)

    # Validate structure
    result = _validate_structure(result)

    _logger.info(f"Synthesis OK ({len(result)} chars)")
    return result


def _validate_structure(content: str) -> str:
    """Post-process synthesized content for structural correctness.

    Fixes:
    - OCR noise in blockquotes (ALL-CAPS headers)
    - Section ordering (Core Idea → References → Ground Truth)
    - Duplicate headings
    """
    content = _strip_ocr_noise_from_blockquote(content)
    content = fix_section_ordering(content)
    return content


def _strip_ocr_noise_from_blockquote(content: str) -> str:
    """Remove ALL-CAPS lines from Core Idea blockquote (chapter headers from OCR)."""
    lines = content.split("\n")
    result = []
    in_core_idea = False

    for line in lines:
        if "## Core Idea" in line:
            in_core_idea = True
        elif line.startswith("## ") and in_core_idea:
            in_core_idea = False

        if in_core_idea and line.startswith("> "):
            raw = line[2:].strip()
            # Skip ALL-CAPS lines longer than 10 chars
            if raw == raw.upper() and len(raw) > 10 and not raw.startswith('"'):
                continue

        result.append(line)

    return "\n".join(result)


def fix_section_ordering(content: str) -> str:
    """Ensure sections appear in correct canonical order v7.7:
    Evidence Hook (blockquote) → Core Idea → Ground Truth → --- → References.
    """
    _SECTION_MARKERS = ["## Core Idea", "## References", "## 📖", "## Ground Truth"]

    first_section_pos = min(
        (content.find(m) for m in _SECTION_MARKERS if content.find(m) >= 0),
        default=-1,
    )
    if first_section_pos < 0:
        return content  # No recognisable sections, nothing to reorder

    preamble = content[:first_section_pos]

    # Split the rest into section blocks by ## heading (keep delimiter)
    body = content[first_section_pos:]
    raw_blocks = re.split(r"(?=^## )", body, flags=re.MULTILINE)
    raw_blocks = [b for b in raw_blocks if b.strip()]

    # Categorise each block
    core_blocks, ref_blocks, gt_blocks, other_blocks = [], [], [], []
    for block in raw_blocks:
        if block.startswith("## Core Idea"):
            core_blocks.append(block)
        elif block.startswith("## References"):
            ref_blocks.append(block)
        elif block.startswith("## 📖") or block.startswith("## Ground Truth"):
            gt_blocks.append(block)
        else:
            other_blocks.append(block)

    # v7.7 canonical order: Core Idea → Ground Truth → other → References
    ordered = core_blocks + gt_blocks + other_blocks + ref_blocks
    if ordered == raw_blocks:
        return content  # Already correct, skip expensive write

    _logger.debug("Fixing section ordering v7.7: Core Idea → Ground Truth → References")

    # Ensure a --- separator appears between Ground Truth and References
    assembled: list[str] = []
    for i, block in enumerate(ordered):
        # Strip any trailing lone "---" from the Ground Truth block itself
        # and ensure exactly one --- separator before References
        if block in gt_blocks and i + 1 < len(ordered) and ordered[i + 1] in ref_blocks:
            # Normalise: strip trailing --- from gt block, then add separator cleanly
            stripped = block.rstrip()
            if stripped.endswith("\n---"):
                stripped = stripped[: -len("\n---")]
            assembled.append(stripped.rstrip() + "\n\n---\n\n")
        else:
            assembled.append(block)

    return preamble + "".join(assembled)



def extract_title_from_content(content: str) -> str:
    """Extract the title from a concept note's frontmatter or H1.

    Args:
        content: Full markdown content.

    Returns:
        Title string, or "untitled".
    """
    # Try frontmatter title
    title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', content, re.MULTILINE)
    if title_match:
        return title_match.group(1).strip()

    # Try H1 heading
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()

    return "untitled"
