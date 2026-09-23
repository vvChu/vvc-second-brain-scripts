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


def is_structured_article(text: str) -> bool:
    """Determine if a text is already a well-structured markdown article.

    A structured article has clean headings, distinct paragraphs, and standard
    sentence punctuation, while lacking spoken audio artifacts like timestamps
    [MM:SS] or transcript section headers.

    Such texts do not need destructive LLM rewriting/chunking, preserving the
    author's original wording and saving significant latency and token costs.

    Args:
        text: Raw input text.

    Returns:
        True if the text is deemed an already-structured article eligible for bypass.
    """
    if not text or len(text.strip()) < 200:
        return False

    clean_text = text.strip()

    # 1. Any timestamps [MM:SS], [H:MM:SS], or [HH:MM:SS] indicate video/audio transcripts
    if re.search(r"\[\d+:\d+(?::\d+)?\]", clean_text):
        return False

    # 2. Known transcript / video section markers
    audio_markers = [
        "## 🎙️ Lời thoại âm thanh",
        "## 🎬 Hình ảnh trực quan",
        "## 🎞️",
    ]
    if any(marker in clean_text for marker in audio_markers):
        return False

    # 3. Check for Markdown headings (^#{1,4}\s+)
    headings = re.findall(r"^#{1,4}\s+\S.*$", clean_text, flags=re.MULTILINE)

    # 4. Check for paragraph breaks (\n\n+)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_text) if p.strip()]

    # 5. Check punctuation density (sentence-ending punctuation . ! ?)
    # Exclude code fences and headings when measuring prose punctuation
    prose_sample = re.sub(r"```[\s\S]*?```", "", clean_text)
    prose_sample = re.sub(r"^#{1,6}\s+.*$", "", prose_sample, flags=re.MULTILINE)
    words = re.findall(r"\b\w+\b", prose_sample)
    punctuations = re.findall(r"[.!?]", prose_sample)

    word_count = len(words)
    punc_count = len(punctuations)

    # If text has substantial words, verify healthy punctuation density (speech-to-text lacks punctuation)
    if word_count >= 50:
        if punc_count < max(1, word_count // 40):
            return False

    # 6. Structural Criteria:
    # Option A: At least 2 distinct markdown headings and at least 2 paragraphs
    if len(headings) >= 2 and len(paragraphs) >= 2:
        return True

    # Option B: At least 1 markdown heading and at least 3 well-formed paragraphs with healthy punctuation
    if len(headings) >= 1 and len(paragraphs) >= 3 and punc_count >= 5:
        return True

    return False


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

    # Smart Bypass: Keep well-structured markdown articles intact
    if not force and is_structured_article(text):
        _logger.info("Text is already a well-structured markdown article. Bypassing orthographic preprocessing.")
        return text

    # Semantic Chunking
    max_chunk_size = 25000
    chunks = []

    if len(text) <= max_chunk_size:
        chunks = [text]
    else:
        _logger.info(f"Text is {len(text)} chars. Chunking into {max_chunk_size}-char segments.")
        # Split by sentence boundaries
        raw_sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = []
        for s in raw_sentences:
            s = s.strip()
            if not s:
                continue
            if len(s) <= max_chunk_size:
                sentences.append(s)
            else:
                # Fallback: split huge sentences by space (e.g. YouTube transcripts without punctuation)
                words = s.split()
                temp_s = []
                temp_len = 0
                for w in words:
                    if temp_len + len(w) > max_chunk_size and temp_s:
                        sentences.append(" ".join(temp_s))
                        temp_s = [w]
                        temp_len = len(w) + 1
                    else:
                        temp_s.append(w)
                        temp_len += len(w) + 1
                if temp_s:
                    sentences.append(" ".join(temp_s))

        current_chunk = []
        current_len = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            if current_len + sentence_len > max_chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_len = sentence_len + 1
            else:
                current_chunk.append(sentence)
                current_len += sentence_len + 1  # +1 for space

        if current_chunk:
            chunks.append(" ".join(current_chunk))

    # Detect if raw text contains any timestamps [MM:SS]
    has_timestamps = bool(re.search(r"\[\d+:\d+\]", text))

    _logger.info(f"Processing {len(chunks)} chunk(s) for formatting and correction. Timestamps detected: {has_timestamps}")

    formatted_chunks = []
    for i, chunk in enumerate(chunks, 1):
        _logger.info(f"Processing chunk {i}/{len(chunks)}...")

        if has_timestamps:
            prompt = ORTHOGRAPHIC_CORRECTION_TIMESTAMPED.format(chunk=chunk)
        else:
            prompt = ORTHOGRAPHIC_CORRECTION_PLAIN.format(chunk=chunk)

        result = call_llm(
            prompt,
            task="correction",
            validator=lambda x: len(x) > 300
        )
        if result:
            formatted_chunks.append(result.strip())
        else:
            _logger.warning(f"Chunk {i} formatting failed all tiers. Using original.")
            formatted_chunks.append(chunk.strip())

    return "\n\n---\n\n".join(formatted_chunks)
