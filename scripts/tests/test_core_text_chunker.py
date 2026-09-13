"""Unit tests for scripts/core/text_chunker.py."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from core.text_chunker import split_into_chunks, map_reduce_summarize


def test_split_into_chunks_small_text():
    """Text under chunk_size should return as a single chunk."""
    text = "Short text under chunk size."
    chunks = split_into_chunks(text, chunk_size=1000)
    assert chunks == [text]

    empty = split_into_chunks("", chunk_size=1000)
    assert empty == []


def test_split_into_chunks_heading_boundary():
    """Text exceeding chunk_size should split cleanly at markdown headings."""
    part1 = "# Header 1\n\nContent for section 1. " * 30  # ~720 chars
    part2 = "\n## Header 2\n\nContent for section 2. " * 30
    full_text = part1 + part2

    chunks = split_into_chunks(full_text, chunk_size=800, overlap=50)
    assert len(chunks) >= 2
    # The split should happen near Header 2
    assert "## Header 2" in chunks[1] or "## Header 2" in chunks[0]


def test_split_into_chunks_paragraph_boundary():
    """Text without headings should split at paragraph breaks."""
    para1 = "Paragraph 1 sentence. " * 25 + "\n\n"
    para2 = "Paragraph 2 sentence. " * 25 + "\n\n"
    para3 = "Paragraph 3 sentence. " * 25
    full_text = para1 + para2 + para3

    chunks = split_into_chunks(full_text, chunk_size=600, overlap=50)
    assert len(chunks) >= 2
    # Verify no chunk exceeds chunk_size + reasonable buffer
    for c in chunks:
        assert len(c) <= 700


def test_map_reduce_summarize_passthrough():
    """Text <= max_chars should return unchanged without calling LLM."""
    mock_llm = MagicMock()
    text = "Content within limit"
    result = map_reduce_summarize(text, max_chars=1000, call_llm_fn=mock_llm)
    assert result == text
    mock_llm.assert_not_called()


def test_map_reduce_summarize_two_phases():
    """Text > max_chars triggers Map phase for each chunk and Reduce phase for synthesis."""
    # Create large text > 5,000 chars and set max_chars=4,000
    section = "## Section\n" + ("This is detailed knowledge about systems. " * 50) + "\n\n"
    large_text = section * 8  # ~16k chars

    calls = []

    def mock_llm_fn(prompt: str, model: str = "", task: str = "") -> str:
        calls.append({"prompt": prompt, "model": model, "task": task})
        if "tóm tắt cô đọng" in prompt:
            return f"Summary of chunk with model {model}"
        elif "chuyên gia tổng hợp học thuật" in prompt:
            return f"Comprehensive synthesis by {model}"
        return "Generic response"

    result = map_reduce_summarize(
        large_text,
        target_model="claude-opus-4-6-thinking",
        max_chars=4000,
        chunk_size=3000,
        call_llm_fn=mock_llm_fn,
    )

    assert "<large_document_map_reduce_summary" in result
    assert "Comprehensive synthesis by claude-opus-4-6-thinking" in result
    assert "</large_document_map_reduce_summary>" in result

    # Check Map calls used gemini-3.8-flash-high and task=synthesis
    map_calls = [c for c in calls if c["task"] == "synthesis"]
    assert len(map_calls) > 1
    for mc in map_calls:
        assert mc["model"] == "gemini-3.8-flash-high"

    # Check Reduce call used target_model and task=reasoning
    reduce_calls = [c for c in calls if c["task"] == "reasoning"]
    assert len(reduce_calls) == 1
    assert reduce_calls[0]["model"] == "claude-opus-4-6-thinking"
