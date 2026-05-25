"""Tests for services modules."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# --- Command Handler Tests ---

def test_parse_style():
    """Should parse style prefix from query."""
    from services.command import _parse_style

    style, query = _parse_style("/tim-urban What is AI?")
    assert style == "tim-urban"
    assert query == "What is AI?"

    style, query = _parse_style("Normal query without prefix")
    assert style == "professional"
    assert query == "Normal query without prefix"

    style, query = _parse_style("/eli5 Quantum computing")
    assert style == "eli5"
    assert query == "Quantum computing"


def test_find_pending_query():
    """Should find unanswered @AI queries inside the correct Input section."""
    from services.command import _find_pending_query
    from services.chat_history import INPUT_MARKER, HISTORY_MARKER

    # Must use exact markers from command.py (## \U0001f4e5 Input / ## \U0001f570\ufe0f Lịch sử)
    content = f"{INPUT_MARKER}\n@AI: What is transformer? ---\n\n{HISTORY_MARKER}\n"
    result = _find_pending_query(content)
    assert result is not None
    assert "What is transformer?" in result


def test_find_pending_query_answered():
    """Should return None when Inbox has no pending @AI query."""
    from services.command import _find_pending_query
    from services.chat_history import INPUT_MARKER, HISTORY_MARKER

    # Inbox is empty — query is only in history (already answered)
    content = f"{INPUT_MARKER}\n\n{HISTORY_MARKER}\n@AI: Old question ---\n> [!done] Answer here\n"
    result = _find_pending_query(content)
    assert result is None


def test_writing_styles_count():
    """Should have exactly 8 writing styles."""
    from services.command import WRITING_STYLES

    assert len(WRITING_STYLES) == 8
    assert "professional" in WRITING_STYLES
    assert "tim-urban" in WRITING_STYLES
    assert "eli5" in WRITING_STYLES


# --- Brain Dump Tests ---

def test_is_garbage_fetch():
    """Should detect garbage URL fetches."""
    from services.url_fetcher import _is_garbage_fetch

    assert _is_garbage_fetch("short") is True
    assert _is_garbage_fetch("javascript is disabled. Please enable javascript") is True
    assert _is_garbage_fetch("This is a legitimate article with enough content." * 5) is False


def test_find_pending_dump_processed():
    """Should return None when there is no ## Inbox section."""
    from services.brain_dump import _find_pending_dump

    # No Inbox section at all — nothing to process
    content = "## Processed\nSome old dump\n"
    assert _find_pending_dump(content) is None


def test_find_pending_dump_new():
    """Should return content from ## Inbox section."""
    from services.brain_dump import _find_pending_dump

    content = "## Inbox\nNew idea about AI and machine learning concepts.\n\n## Processed\n"
    result = _find_pending_dump(content)
    assert result is not None
    assert "AI" in result


# --- Wiki Health Tests ---

def test_reject_patterns():
    """Should reject garbage link targets."""
    import re
    from services.wiki_health import _REJECT_PATTERNS

    garbage = ["2012", "AI", "Ví dụ", "Chương 3", "42"]
    for g in garbage:
        assert any(re.match(pat, g) for pat in _REJECT_PATTERNS), f"Should reject: {g}"

    valid = ["transformer_architecture", "Bayesian Inference"]
    for v in valid:
        assert not any(re.match(pat, v) for pat in _REJECT_PATTERNS), f"Should accept: {v}"


def test_canonical_domains():
    """Should have canonical domain taxonomy."""
    from services.wiki_health import CANONICAL_DOMAINS

    assert "ai" in CANONICAL_DOMAINS
    assert "business" in CANONICAL_DOMAINS
    assert len(CANONICAL_DOMAINS) >= 10


# --- Mermaid Worker Tests ---

def test_clean_mermaid_valid():
    """Should accept valid Mermaid syntax."""
    from services.mermaid_worker import _clean_mermaid

    valid = "graph TD\n  A[Start] --> B[End]"
    assert _clean_mermaid(valid) == valid

    fenced = "```mermaid\nflowchart LR\n  A --> B\n```"
    cleaned = _clean_mermaid(fenced)
    assert cleaned.startswith("flowchart")
    assert "```" not in cleaned


def test_clean_mermaid_invalid():
    """Should reject invalid Mermaid syntax."""
    from services.mermaid_worker import _clean_mermaid

    assert _clean_mermaid("This is just text") == ""
    assert _clean_mermaid("") == ""
