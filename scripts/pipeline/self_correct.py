"""VvC Second Brain — Independent Self-Correction Stage (v7.0).

Verifies blockquote accuracy in Core Idea against Ground Truth.
This module runs INDEPENDENTLY of the synthesizer for quality assurance.
"""

from __future__ import annotations

import logging
import re

from core.llm import call_llm

_logger = logging.getLogger("vvc.selfcorrect")

_VERIFY_PROMPT = """So sánh đoạn trích dẫn (blockquote) dưới đây với bản gốc tiếng Anh.

BLOCKQUOTE (từ concept note):
---
{blockquote}
---

GROUND TRUTH (bản gốc tiếng Anh):
---
{ground_truth}
---

NHIỆM VỤ:
1. Kiểm tra xem blockquote có phản ánh ĐÚNG nội dung Ground Truth không
2. Tìm các lỗi OCR còn sót: ký tự sai, thiếu dấu, thừa/thiếu từ
3. Nếu có lỗi, trả về blockquote ĐÃ SỬA (bắt đầu bằng "> ")
4. Nếu không có lỗi, trả về CHÍNH XÁC: "OK"

CHỈ trả về "OK" hoặc blockquote đã sửa. KHÔNG giải thích."""


def verify_and_correct(concept_content: str, ground_truth: str) -> str:
    """Verify and correct blockquote accuracy in a concept note.

    Args:
        concept_content: Full concept note markdown.
        ground_truth: English Ground Truth paragraph.

    Returns:
        Corrected concept content (or unchanged if no issues found).
    """
    if not ground_truth:
        _logger.debug("No Ground Truth, skipping self-correction")
        return concept_content

    # Extract blockquote from Core Idea
    blockquote = _extract_core_idea_blockquote(concept_content)
    if not blockquote:
        _logger.debug("No blockquote found in Core Idea, skipping")
        return concept_content

    # Ask LLM to verify
    result = call_llm(
        _VERIFY_PROMPT.format(blockquote=blockquote, ground_truth=ground_truth),
        task="correction",
        allowed_shorts=("OK",),
    )

    if not result:
        _logger.warning("Self-correction returned empty, keeping original")
        return concept_content

    result = result.strip()

    # If LLM says OK, no changes needed
    if result.upper().startswith("OK"):
        _logger.info("Self-correction: verified OK")
        return concept_content

    # LLM returned corrected blockquote — replace in content
    if result.startswith(">"):
        corrected = _replace_core_idea_blockquote(concept_content, blockquote, result)
        _logger.info(f"Self-correction: blockquote updated ({len(result)} chars)")
        return corrected

    _logger.debug("Self-correction result unclear, keeping original")
    return concept_content


def _extract_core_idea_blockquote(content: str) -> str:
    """Extract blockquote lines from the preamble (v7.7+) or fallback to ## Core Idea (old format)."""
    lines = content.split("\n")
    bq_lines: list[str] = []

    # Try finding in the preamble (between frontmatter and first H2)
    yaml_count = 0
    preamble_lines: list[str] = []

    for line in lines:
        if line.strip() == "---":
            yaml_count += 1
            continue
        # Skip frontmatter content
        if yaml_count == 1:
            continue
        # We are after the frontmatter
        if yaml_count >= 2:
            if line.startswith("## "):
                # Stop when we hit the first section heading
                break
            preamble_lines.append(line)

    # Extract blockquotes from the collected preamble lines
    for line in preamble_lines:
        if line.startswith("> "):
            bq_lines.append(line)

    if bq_lines:
        return "\n".join(bq_lines)

    # Fallback to old format: extract blockquotes from ## Core Idea section
    in_core = False
    bq_lines = []
    for line in lines:
        if "## Core Idea" in line:
            in_core = True
            continue
        if line.startswith("## ") and in_core:
            break
        if in_core and line.startswith("> "):
            bq_lines.append(line)

    return "\n".join(bq_lines)


def _replace_core_idea_blockquote(content: str, old_bq: str, new_bq: str) -> str:
    """Replace blockquote in the file content."""
    if old_bq in content:
        return content.replace(old_bq, new_bq, 1)
    return content
