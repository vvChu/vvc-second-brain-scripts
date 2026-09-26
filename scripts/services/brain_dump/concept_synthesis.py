"""VvC Second Brain — Concept Synthesis (Map-Reduce).

Handles Map-Reduce concept extraction, synthesis, and saving into Permanent notes.
Re-exports transcript writing and cross-linking functions for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.prompts.services import BRAIN_DUMP_MAP as _MAP_PROMPT
from core.prompts.services import BRAIN_DUMP_REDUCE as _REDUCE_PROMPT
from core.vector_store import VectorStore
from pipeline.post_process import save_concept
from pipeline.synthesize import fix_section_ordering
from services.brain_dump.cross_links import (
    _backlink_source_to_concepts,
    _enrich_concept_references,
)
from services.brain_dump.transcript_writer import (
    _determine_callout_style,
    _save_transcript,
    _weave_images_into_transcript,
)
from services.brain_dump.url_registry import _URL_PATTERN, _extract_related_links
from services.url_fetcher import fetch_url_title

# Re-export public API symbols for callers and unit test mocking contracts
__all__ = [
    "cfg",
    "call_llm",
    "save_concept",
    "fetch_url_title",
    "_extract_related_links",
    "_determine_callout_style",
    "_weave_images_into_transcript",
    "_save_transcript",
    "_enrich_concept_references",
    "_backlink_source_to_concepts",
    "_synthesize_and_save_concepts",
]

_logger = logging.getLogger("vvc.dump")


def _presummarize_large_inputs(dump_text: str, url_content: str) -> tuple[str, str]:
    """Adaptive chunking and Map-Reduce pre-summarization for massive inputs (>200k chars)."""
    if len(dump_text) > 200_000:
        try:
            from core.text_chunker import map_reduce_summarize

            _logger.info(f"Dump text exceeds 200k ({len(dump_text)} chars). Pre-summarizing with Map-Reduce.")
            dump_text = map_reduce_summarize(dump_text, max_chars=200_000)
        except Exception as e:
            _logger.warning(f"Failed to pre-summarize large dump text: {e}")

    if len(url_content) > 200_000:
        try:
            from core.text_chunker import map_reduce_summarize

            _logger.info(f"URL content exceeds 200k ({len(url_content)} chars). Pre-summarizing with Map-Reduce.")
            url_content = map_reduce_summarize(url_content, max_chars=200_000)
        except Exception as e:
            _logger.warning(f"Failed to pre-summarize large URL content: {e}")

    return dump_text, url_content


def _calculate_dynamic_concept_limits(total_len: int) -> tuple[int, int]:
    """Calculate proportional dynamic concept extraction limits based on raw input length."""
    if total_len < 5000:
        return 1, 3
    if total_len < 20000:
        return 3, 7
    if total_len < 50000:
        return 5, 12
    return 8, 18


def _execute_map_extraction(dump_text: str, url_content: str, min_c: int, max_c: int) -> list[dict]:
    """Execute LLM Map step to extract atomic concept candidates."""
    map_prompt = _MAP_PROMPT.format(
        dump_text=dump_text,
        url_content=url_content or "(không có URL content)",
        min_concepts=min_c,
        max_concepts=max_c,
    )
    _logger.info("Executing Map step: Extracting atomic concepts via Synthesis tier...")
    map_result = call_llm(map_prompt, task="synthesis")
    if not map_result:
        log("error", "Brain Dump MAP step failed")
        return []

    try:
        json_match = re.search(r"\[\s*\{.*\}\s*\]", map_result, re.DOTALL)
        json_str = json_match.group(0) if json_match else map_result
        concepts_list = json.loads(json_str)
        if not isinstance(concepts_list, list):
            raise ValueError("Expected a JSON array")
        return concepts_list
    except Exception as e:
        _logger.error(f"Failed to parse MAP step JSON: {e}")
        log("error", "Brain Dump MAP step failed to parse JSON")
        return []


def _clean_and_enrich_concept(concept_body: str, source_ref: str, original_url: str) -> str | None:
    """Extract YAML, apply canonical section ordering, enrich references, and append source callout."""
    match = re.search(r"(---\r?\n.*)", concept_body, re.DOTALL)
    if not match:
        return None

    concept_clean = match.group(1)
    concept_clean = re.sub(r"\n```\s*$", "", concept_clean)
    concept_clean = fix_section_ordering(concept_clean)
    concept_clean = _enrich_concept_references(concept_clean, source_ref)

    if original_url:
        import datetime as dt

        time_str = dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        source_callout = (
            f"\n\n> [!info]- 🌐 Nguồn thu thập\n"
            f"> Ghi chép được thu thập từ internet (click để mở)\n"
            f"> - **Đường dẫn gốc:** [{original_url}]({original_url})\n"
            f"> - **Thời gian thu thập:** {time_str}\n"
            f"> - **Tệp nguồn thô:** [[{source_ref}]]\n"
        )
        concept_clean = f"{concept_clean.rstrip()}{source_callout}"

    return concept_clean


def _synthesize_concept_item(
    dump_text: str,
    url_content: str,
    meta: dict,
    today: str,
    source_ref: str,
    original_url: str,
) -> tuple[str, str] | None:
    """Run LLM Reduce step for one concept and persist to disk via save_concept."""
    c_title = meta.get("title", "Untitled Concept")
    c_summary = meta.get("summary", "")
    _logger.info(f"Reducing concept: {c_title}")

    reduce_prompt = _REDUCE_PROMPT.format(
        dump_text=dump_text,
        url_content=url_content or "(không có URL content)",
        concept_title=c_title,
        concept_summary=c_summary,
        today=today,
        source_ref=source_ref,
    )
    concept_body = call_llm(reduce_prompt, task="synthesis")
    if not concept_body or len(concept_body) < 100:
        _logger.warning(f"Failed to generate concept: {c_title}")
        return None

    concept_clean = _clean_and_enrich_concept(concept_body, source_ref, original_url)
    if not concept_clean:
        _logger.warning(f"Failed to find YAML frontmatter for: {c_title}")
        return None

    saved_path = save_concept(concept_clean)
    return (saved_path.stem, c_title) if saved_path else None


def _synthesize_and_save_concepts(dump_text: str, url_content: str, source_ref: str) -> list[tuple[str, str]]:
    """Synthesize concepts via Map-Reduce pipeline and save to vault."""
    today = date.today().isoformat()
    dump_text, url_content = _presummarize_large_inputs(dump_text, url_content)

    total_len = len(dump_text) + len(url_content)
    min_c, max_c = _calculate_dynamic_concept_limits(total_len)
    _logger.info(f"[Map-Reduce] Dynamic limits ({total_len} chars): min={min_c}, max={max_c} concepts.")

    concepts_list = _execute_map_extraction(dump_text, url_content, min_c, max_c)
    if not concepts_list:
        return []

    _logger.info(f"Map step found {len(concepts_list)} concepts. Starting Reduce step...")
    urls = _URL_PATTERN.findall(dump_text)
    original_url = urls[0] if urls else ""

    saved_stems: list[tuple[str, str]] = []
    with VectorStore.get_instance().batch():
        for meta in concepts_list:
            res = _synthesize_concept_item(dump_text, url_content, meta, today, source_ref, original_url)
            if res:
                saved_stems.append(res)

    if saved_stems:
        _backlink_source_to_concepts(source_ref, saved_stems)

    return saved_stems
