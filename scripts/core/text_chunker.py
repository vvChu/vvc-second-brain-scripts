"""VvC Second Brain — Adaptive Text Chunker & Map-Reduce Engine (v8.15.0).

Handles large documents (>200,000 chars) via heading-aware chunking and 
two-phase Map-Reduce summarization to prevent silent drop and context truncation.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from core.prompts.services import LARGE_DOC_MAP, LARGE_DOC_REDUCE

_logger = logging.getLogger("vvc.chunker")


def _find_semantic_split_offset(text: str, search_start: int, end: int) -> int:
    """Find the best semantic split point (heading, paragraph, or sentence boundary)."""
    window = text[search_start:end]
    heading_matches = list(re.finditer(r"\n#{1,3}\s+", window))
    if heading_matches:
        return search_start + heading_matches[-1].start() + 1
    para_matches = list(re.finditer(r"\n\n+", window))
    if para_matches:
        return search_start + para_matches[-1].start() + 1
    sentence_matches = list(re.finditer(r"[\.\?\!]\s+", window))
    if sentence_matches:
        return search_start + sentence_matches[-1].end()
    return end


def split_into_chunks(
    text: str,
    chunk_size: int = 40_000,
    overlap: int = 1_000,
) -> list[str]:
    """Split a large text into logical chunks with semantic overlap."""
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    chunks: list[str] = []
    start, total_len = 0, len(text)

    while start < total_len:
        end = min(start + chunk_size, total_len)
        if end < total_len:
            search_start = max(start + chunk_size // 2, end - 2000)
            split_offset = _find_semantic_split_offset(text, search_start, end)
        else:
            split_offset = end

        chunk = text[start:split_offset].strip()
        if chunk:
            chunks.append(chunk)

        if split_offset >= total_len:
            break
        start = max(split_offset - overlap, start + 1)

    return chunks


def _execute_map_phase(chunks: list[str], call_llm_fn: Callable[..., str]) -> list[str]:
    """Map phase: summarize each chunk into key insights."""
    summaries: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        prompt = LARGE_DOC_MAP.format(idx=idx, total_chunks=len(chunks), chunk=chunk)
        summary = call_llm_fn(prompt, model="gemini-3.8-flash-high", task="synthesis")
        summaries.append(f"#### Phân đoạn {idx}/{len(chunks)}:\n{summary.strip()}")
    return summaries


def _execute_reduce_phase(
    combined_notes: str,
    total_chars: int,
    total_chunks: int,
    target_model: str,
    call_llm_fn: Callable[..., str],
) -> str:
    """Reduce phase: synthesize chunk summaries into final document overview."""
    prompt = LARGE_DOC_REDUCE.format(
        total_chars=total_chars, total_chunks=total_chunks, combined_notes=combined_notes
    )
    final_reduced = call_llm_fn(prompt, model=target_model, task="reasoning")
    return (
        f'<large_document_map_reduce_summary original_chars="{total_chars}" chunks="{total_chunks}">\n'
        f"{final_reduced.strip()}\n"
        f"</large_document_map_reduce_summary>"
    )


def map_reduce_summarize(
    text: str,
    target_model: str = "gemini-3.8-flash-high",
    max_chars: int = 200_000,
    chunk_size: int = 40_000,
    overlap: int = 1_000,
    call_llm_fn: Callable[..., str] | None = None,
) -> str:
    """Summarize text exceeding max_chars using two-phase Map-Reduce."""
    if not text or len(text) <= max_chars:
        return text

    if call_llm_fn is None:
        from core.llm import call_llm
        call_llm_fn = call_llm

    chunks = split_into_chunks(text, chunk_size=chunk_size, overlap=overlap)
    _logger.info(f"[TextChunker] Splitting {len(text):,} chars into {len(chunks)} chunks for Map-Reduce")

    chunk_summaries = _execute_map_phase(chunks, call_llm_fn)
    combined_notes = "\n\n".join(chunk_summaries)
    return _execute_reduce_phase(combined_notes, len(text), len(chunks), target_model, call_llm_fn)
