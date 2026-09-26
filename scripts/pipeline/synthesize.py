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



def _build_synthesis_prompt(
    highlighted: str,
    context: str,
    ground_truth: str,
    source_name: str,
    source_ref: str,
    chapter: str,
    page: str,
    gt_page: str,
    gt_chapter: str,
    today: str,
    book_macro_context: str,
    chapter_diagrams: str,
) -> str:
    """Format the full synthesis prompt with chapter and context references."""
    chapter_clean = chapter if chapter and chapter != "(không rõ)" else ""
    gt_chapter_clean = gt_chapter if gt_chapter and gt_chapter != "(không rõ)" else ""
    return _SYNTHESIS_PROMPT.format(
        book_macro_context=book_macro_context or "Không có thông tin nền vĩ mô.",
        highlighted=highlighted,
        context=context,
        ground_truth=ground_truth or "(không có)",
        source_name=source_name,
        source_ref=source_ref,
        source_display=source_name or source_ref,
        chapter=chapter or "(không rõ)",
        chapter_ref=f"[[{chapter_clean}]]" if chapter_clean else "",
        page=page or "",
        gt_page=gt_page or "",
        gt_chapter_ref=f"[[{gt_chapter_clean}]]" if gt_chapter_clean else "",
        today=today,
        ground_truth_excerpt=ground_truth if ground_truth else "(không có)",
        chapter_diagrams=chapter_diagrams,
    )


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
    """Generate an atomic concept note from OCR content, returning frontmatter + body."""
    prompt = _build_synthesis_prompt(
        highlighted=highlighted,
        context=context,
        ground_truth=ground_truth,
        source_name=source_name,
        source_ref=source_ref,
        chapter=chapter,
        page=page,
        gt_page=gt_page,
        gt_chapter=gt_chapter,
        today=today or dt_date.today().isoformat(),
        book_macro_context=book_macro_context,
        chapter_diagrams=chapter_diagrams,
    )
    result = call_llm(prompt, task="synthesis")
    if not result or len(result) < 100:
        _logger.error("Synthesis returned empty/short result")
        return ""

    result = re.sub(r"^```(?:markdown|md)?\s*\n", "", result)
    result = re.sub(r"\n```\s*$", "", result)
    result = _validate_structure(result)
    _logger.info(f"Synthesis OK ({len(result)} chars)")
    return result


def _validate_structure(content: str) -> str:
    """Post-process synthesized content for structural correctness."""
    content = _strip_ocr_noise_from_blockquote(content)
    return fix_section_ordering(content)


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
            if raw == raw.upper() and len(raw) > 10 and not raw.startswith('"'):
                continue

        result.append(line)

    return "\n".join(result)


def _categorize_section_blocks(raw_blocks: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Group markdown heading blocks into core, gt, other, and references categories."""
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
    return core_blocks, gt_blocks, other_blocks, ref_blocks


def _assemble_ordered_sections(ordered: list[str], gt_blocks: list[str], ref_blocks: list[str]) -> str:
    """Ensure clean --- separator between Ground Truth and References."""
    assembled: list[str] = []
    for i, block in enumerate(ordered):
        if block in gt_blocks and i + 1 < len(ordered) and ordered[i + 1] in ref_blocks:
            stripped = block.rstrip()
            if stripped.endswith("\n---"):
                stripped = stripped[:-len("\n---")]
            assembled.append(stripped.rstrip() + "\n\n---\n\n")
        else:
            assembled.append(block)
    return "".join(assembled)


def fix_section_ordering(content: str) -> str:
    """Ensure sections appear in correct canonical order v7.7:
    Evidence Hook (blockquote) → Core Idea → Ground Truth → --- → References.
    """
    markers = ["## Core Idea", "## References", "## 📖", "## Ground Truth"]
    first_pos = min((content.find(m) for m in markers if content.find(m) >= 0), default=-1)
    if first_pos < 0:
        return content

    preamble = content[:first_pos]
    raw_blocks = [b for b in re.split(r"(?=^## )", content[first_pos:], flags=re.MULTILINE) if b.strip()]
    core_b, gt_b, other_b, ref_b = _categorize_section_blocks(raw_blocks)
    ordered = core_b + gt_b + other_b + ref_b
    if ordered == raw_blocks:
        return content

    _logger.debug("Fixing section ordering v7.7: Core Idea → Ground Truth → References")
    return preamble + _assemble_ordered_sections(ordered, gt_b, ref_b)



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
