"""Unit tests for services.text_chunker and Smart Bypass."""

import pytest
from unittest.mock import patch, MagicMock

from services.text_chunker import is_structured_article, orthographic_preprocess


CLEAN_MARKDOWN_ARTICLE = """# The Architecture of Modern Software

Software architecture has evolved significantly over the past decade.
Microservices, event-driven systems, and autonomous agent platforms are replacing monolithic designs.

## Decoupling and Autonomous Cells

By dividing monolithic systems into small, independent services, engineering teams
gain immense agility. Each team can deploy changes without coordinating with the entire company.

## First Principles Engineering

When designing complex distributed systems, engineers must reason from first principles.
Tools and frameworks change rapidly, but fundamental constraints remain constant.
"""

SINGLE_HEADING_ARTICLE = """# Understanding LLM Compiler Patterns

Large language models are fundamentally changing how software systems are compiled and maintained.
Instead of rigid deterministic compilers, probabilistic agents can now synthesize and heal code.

This paradigm shift requires a re-evaluation of software architectures from the ground up.
System components must be designed for non-deterministic agents rather than static scripts.

By building resilient feedback loops and self-healing mechanisms, systems can run autonomously.
This approach unlocks unprecedented scalability and self-maintaining knowledge graphs.
"""

TIMESTAMPED_TRANSCRIPT = """[00:00] Welcome everyone to today's episode.
[00:15] Today we are talking about why AI gets people wrong and what anthropologists can teach us.
[01:30] Mikkel Rasmussen explains that human insight comes from deep observation rather than statistical tokens.
[02:45] When LEGO was struggling, they discovered that kids wanted to master hard skills.
"""

AUDIO_MARKER_TRANSCRIPT = """# Podcast Episode

**Show:** Tech Talk

## 🎙️ Lời thoại âm thanh (Transcript)

Welcome to the show. We are discussing distributed agents and organizational design.
"""

WALL_OF_SPEECH_TEXT = (
    "welcome back everyone today we are going to discuss software architecture and how to build "
    "systems that scale and why people make mistakes when designing distributed services because "
    "they assume network calls are free and reliable but in reality networks are brittle and slow "
    "and when you have hundreds of microservices calling each other in synchronous chains you get "
    "cascading failures that take down your entire infrastructure and nobody knows who is responsible"
)


class TestIsStructuredArticle:
    """Tests for is_structured_article morphology analysis."""

    def test_clean_markdown_article_returns_true(self):
        assert is_structured_article(CLEAN_MARKDOWN_ARTICLE) is True

    def test_single_heading_multi_paragraph_returns_true(self):
        assert is_structured_article(SINGLE_HEADING_ARTICLE) is True

    def test_timestamps_return_false(self):
        assert is_structured_article(TIMESTAMPED_TRANSCRIPT) is False

    def test_audio_markers_return_false(self):
        assert is_structured_article(AUDIO_MARKER_TRANSCRIPT) is False

    def test_wall_of_speech_text_returns_false(self):
        assert is_structured_article(WALL_OF_SPEECH_TEXT) is False

    def test_short_text_returns_false(self):
        assert is_structured_article("Short note.") is False
        assert is_structured_article("") is False
        assert is_structured_article("# Title\n\nToo short.") is False

    def test_markdown_bullet_notes_without_headings_return_false(self):
        bullets = "- Point one.\n- Point two.\n- Point three.\n- Point four."
        assert is_structured_article(bullets) is False


class TestOrthographicPreprocessSmartBypass:
    """Tests for orthographic_preprocess with Smart Bypass."""

    @patch("services.text_chunker.call_llm")
    def test_bypasses_clean_article_without_llm_call(self, mock_call_llm):
        result = orthographic_preprocess(CLEAN_MARKDOWN_ARTICLE)
        assert result == CLEAN_MARKDOWN_ARTICLE
        mock_call_llm.assert_not_called()

    @patch("services.text_chunker.call_llm")
    def test_force_flag_triggers_llm_processing(self, mock_call_llm):
        mock_call_llm.return_value = "Corrected content from LLM."
        result = orthographic_preprocess(CLEAN_MARKDOWN_ARTICLE, force=True)
        assert mock_call_llm.called
        assert result == "Corrected content from LLM."

    @patch("services.text_chunker.call_llm")
    def test_timestamped_transcript_calls_llm(self, mock_call_llm):
        mock_call_llm.return_value = "Structured transcript with [00:00] timestamps."
        result = orthographic_preprocess(TIMESTAMPED_TRANSCRIPT)
        assert mock_call_llm.called
        assert "Structured transcript" in result

    @patch("services.text_chunker.call_llm")
    def test_large_unstructured_text_chunks_correctly(self, mock_call_llm):
        # Create a 55,000 char speech text
        large_speech = (WALL_OF_SPEECH_TEXT + ".\n\n") * 150
        assert len(large_speech) > 50000

        mock_call_llm.side_effect = lambda prompt, **kwargs: "Chunk output: " + prompt[:50]
        result = orthographic_preprocess(large_speech)

        # Should have called LLM multiple times due to chunking (> 25000 chars)
        assert mock_call_llm.call_count >= 2
        assert "Chunk output:" in result

    def test_short_text_returns_immediately(self):
        short = "Under 50 chars."
        assert orthographic_preprocess(short) == short
