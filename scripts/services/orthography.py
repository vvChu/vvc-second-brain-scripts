"""VvC Second Brain — Orthographic Corrector & Speech Transcript Preprocessor.

Handles semantic chunking for orthographic corrections and smart markdown article bypass.
"""

from __future__ import annotations

import logging
import re

from core.llm import call_llm
from core.prompts.services import (
    ORTHOGRAPHIC_CORRECTION_PLAIN,
    ORTHOGRAPHIC_CORRECTION_TIMESTAMPED,
)

_logger = logging.getLogger("vvc.orthography")

__all__ = [
    "is_structured_article",
    "orthographic_preprocess",
]


def _has_spoken_transcript_markers(clean_text: str) -> bool:
    """Check if text contains timestamps [MM:SS] or known speech audio markers."""
    if re.search(r"\[\d+:\d+(?::\d+)?\]", clean_text):
        return True
    audio_markers = ["## 🎙️ Lời thoại âm thanh", "## 🎬 Hình ảnh trực quan", "## 🎞️"]
    return any(marker in clean_text for marker in audio_markers)


def _has_healthy_punctuation(clean_text: str) -> tuple[int, bool]:
    """Verify healthy sentence punctuation density in prose (speech-to-text lacks punctuation)."""
    prose_sample = re.sub(r"```[\s\S]*?```", "", clean_text)
    prose_sample = re.sub(r"^#{1,6}\s+.*$", "", prose_sample, flags=re.MULTILINE)
    words = re.findall(r"\b\w+\b", prose_sample)
    punctuations = re.findall(r"[.!?]", prose_sample)
    word_count, punc_count = len(words), len(punctuations)
    if word_count >= 50 and punc_count < max(1, word_count // 40):
        return punc_count, False
    return punc_count, True


def is_structured_article(text: str) -> bool:
    """Determine if a text is already a well-structured markdown article.

    A structured article has clean headings, distinct paragraphs, and standard
    sentence punctuation, while lacking spoken audio artifacts like timestamps
    [MM:SS] or transcript section headers.
    """
    if not text or len(text.strip()) < 200:
        return False

    clean_text = text.strip()
    if _has_spoken_transcript_markers(clean_text):
        return False

    headings = re.findall(r"^#{1,4}\s+\S.*$", clean_text, flags=re.MULTILINE)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_text) if p.strip()]
    punc_count, healthy_punc = _has_healthy_punctuation(clean_text)
    if not healthy_punc:
        return False

    if len(headings) >= 2 and len(paragraphs) >= 2:
        return True
    return len(headings) >= 1 and len(paragraphs) >= 3 and punc_count >= 5


def _split_long_sentences(raw_sentences: list[str], max_chunk_size: int) -> list[str]:
    """Break oversized sentences by whitespace into segments <= max_chunk_size."""
    sentences = []
    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) <= max_chunk_size:
            sentences.append(s)
            continue
        temp_s, temp_len = [], 0
        for w in s.split():
            if temp_len + len(w) > max_chunk_size and temp_s:
                sentences.append(" ".join(temp_s))
                temp_s, temp_len = [w], len(w) + 1
            else:
                temp_s.append(w)
                temp_len += len(w) + 1
        if temp_s:
            sentences.append(" ".join(temp_s))
    return sentences


def _chunk_text_semantically(text: str, max_chunk_size: int = 25000) -> list[str]:
    """Split text into semantic chunks up to max_chunk_size chars."""
    if len(text) <= max_chunk_size:
        return [text]
    _logger.info(f"Text is {len(text)} chars. Chunking into {max_chunk_size}-char segments.")
    sentences = _split_long_sentences(re.split(r"(?<=[.!?])\s+", text), max_chunk_size)
    chunks, current_chunk, current_len = [], [], 0
    for s in sentences:
        s_len = len(s)
        if current_len + s_len > max_chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk, current_len = [s], s_len + 1
        else:
            current_chunk.append(s)
            current_len += s_len + 1
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks


def _format_single_chunk(chunk: str, i: int, total: int, has_timestamps: bool) -> str:
    """Format single chunk with LLM orthographic correction."""
    _logger.info(f"Processing chunk {i}/{total}...")
    prompt = (
        ORTHOGRAPHIC_CORRECTION_TIMESTAMPED.format(chunk=chunk)
        if has_timestamps
        else ORTHOGRAPHIC_CORRECTION_PLAIN.format(chunk=chunk)
    )
    result = call_llm(prompt, task="correction", validator=lambda x: len(x) > 300)
    if result:
        return result.strip()
    _logger.warning(f"Chunk {i} formatting failed all tiers. Using original.")
    return chunk.strip()


def orthographic_preprocess(text: str, force: bool = False) -> str:
    """Adaptive orthographic correction and markdown formatting with semantic chunking.

    Args:
        text: Input text to preprocess.
        force: If True, forces orthographic chunking and LLM correction even for
            well-structured articles. Defaults to False.

    Returns:
        Processed text, either bypassed verbatim or corrected via LLM chunks.
    """
    if not text or len(text) < 50:
        return text

    if not force and is_structured_article(text):
        _logger.info("Text is already a well-structured markdown article. Bypassing orthographic preprocessing.")
        return text

    chunks = _chunk_text_semantically(text)
    has_timestamps = bool(re.search(r"\[\d+:\d+\]", text))
    _logger.info(f"Processing {len(chunks)} chunk(s) for formatting and correction. Timestamps: {has_timestamps}")
    formatted = [_format_single_chunk(c, i, len(chunks), has_timestamps) for i, c in enumerate(chunks, 1)]
    return "\n\n---\n\n".join(formatted)
