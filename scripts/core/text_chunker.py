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


def split_into_chunks(
    text: str,
    chunk_size: int = 40_000,
    overlap: int = 1_000,
) -> list[str]:
    """Split a large text into logical chunks with semantic overlap.

    Prefers splitting at Markdown headings (H1/H2/H3) or paragraph boundaries (\\n\\n).

    Args:
        text: The source text to split.
        chunk_size: Target size in characters for each chunk. Default 40,000.
        overlap: Character overlap between consecutive chunks. Default 1,000.

    Returns:
        List of text chunks.
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    total_len = len(text)

    while start < total_len:
        end = min(start + chunk_size, total_len)

        if end < total_len:
            # Look for semantic boundaries in the window [end - 2000, end]
            search_start = max(start + chunk_size // 2, end - 2000)
            window = text[search_start:end]

            # Priority 1: Markdown headings (# , ## , ### )
            heading_matches = list(re.finditer(r"\n#{1,3}\s+", window))
            if heading_matches:
                split_offset = search_start + heading_matches[-1].start() + 1
            else:
                # Priority 2: Paragraph break (\n\n)
                para_matches = list(re.finditer(r"\n\n+", window))
                if para_matches:
                    split_offset = search_start + para_matches[-1].start() + 1
                else:
                    # Priority 3: Sentence ending (. \n or ? \n)
                    sentence_matches = list(re.finditer(r"[\.\?\!]\s+", window))
                    if sentence_matches:
                        split_offset = search_start + sentence_matches[-1].end()
                    else:
                        split_offset = end
        else:
            split_offset = end

        chunk = text[start:split_offset].strip()
        if chunk:
            chunks.append(chunk)

        if split_offset >= total_len:
            break

        # Move forward, maintaining overlap
        start = max(split_offset - overlap, start + 1)

    return chunks


def map_reduce_summarize(
    text: str,
    target_model: str = "gemini-3.8-flash-high",
    max_chars: int = 200_000,
    chunk_size: int = 40_000,
    overlap: int = 1_000,
    call_llm_fn: Callable[..., str] | None = None,
) -> str:
    """Summarize text exceeding max_chars using two-phase Map-Reduce.

    Phase 1 (Map): Each ~40k chunk is summarized into key insights using fast model.
    Phase 2 (Reduce): All chunk summaries are synthesized into a cohesive context.

    Args:
        text: Source text.
        target_model: Model for the final reduce phase. Default "gemini-3.8-flash-high".
        max_chars: Character ceiling before Map-Reduce triggers. Default 200,000.
        chunk_size: Target size in characters for each chunk. Default 40,000.
        overlap: Character overlap between consecutive chunks. Default 1,000.
        call_llm_fn: Optional callable for LLM invocation (defaults to core.llm.call_llm).

    Returns:
        Original text if under max_chars, or XML-wrapped reduced summary.
    """
    if not text or len(text) <= max_chars:
        return text

    if call_llm_fn is None:
        from core.llm import call_llm
        call_llm_fn = call_llm

    chunks = split_into_chunks(text, chunk_size=chunk_size, overlap=overlap)
    _logger.info(f"[TextChunker] Splitting {len(text):,} chars into {len(chunks)} chunks for Map-Reduce")

    # --- Phase 1: Map (Fast extraction per chunk) ---
    chunk_summaries: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        map_prompt = LARGE_DOC_MAP.format(
            idx=idx,
            total_chunks=len(chunks),
            chunk=chunk,
        )
        summary = call_llm_fn(map_prompt, model="gemini-3.8-flash-high", task="synthesis")
        chunk_summaries.append(f"#### Phân đoạn {idx}/{len(chunks)}:\n{summary.strip()}")

    # --- Phase 2: Reduce (Comprehensive synthesis) ---
    combined_notes = "\n\n".join(chunk_summaries)
    reduce_prompt = LARGE_DOC_REDUCE.format(
        total_chars=len(text),
        total_chunks=len(chunks),
        combined_notes=combined_notes,
    )

    final_reduced = call_llm_fn(reduce_prompt, model=target_model, task="reasoning")

    return (
        f'<large_document_map_reduce_summary original_chars="{len(text)}" chunks="{len(chunks)}">\n'
        f"{final_reduced.strip()}\n"
        f"</large_document_map_reduce_summary>"
    )
