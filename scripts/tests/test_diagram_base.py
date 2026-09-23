"""Tests for diagram base utilities and hygiene functions.

Covers wrap_label, sanitize_mermaid, and backward-compatible re-exports.
"""

from services.diagram_base import sanitize_mermaid, wrap_label
from services import moc_mermaid


def test_wrap_label_short_text():
    """Text under 20 chars should not have any <br> added."""
    text = "Short label"
    assert wrap_label(text) == "Short label"


def test_wrap_label_dynamic_threshold():
    """Text over 20 chars should be wrapped using dynamic max_chars threshold."""
    text = "This is a moderately long concept title that should wrap"
    wrapped = wrap_label(text)
    assert "<br>" in wrapped
    # Verify reconstructed words match original
    reconstructed = " ".join([part for line in wrapped.split("<br>") for part in line.split()])
    assert reconstructed == text


def test_wrap_label_custom_max_chars():
    """Explicit max_chars should constrain line lengths."""
    text = "One Two Three Four Five"
    wrapped = wrap_label(text, max_chars=10)
    lines = wrapped.split("<br>")
    for line in lines:
        assert len(line) <= 10 or " " not in line


def test_wrap_label_empty_and_whitespace():
    """Empty string and pure whitespace should handle gracefully."""
    assert wrap_label("") == ""
    assert wrap_label("   ") == ""


def test_sanitize_mermaid_characters():
    """Characters that break Mermaid syntax must be safely converted."""
    raw = 'Node "Name" (Detail) [Ref] {Block} <Tag> & Co #1'
    sanitized = sanitize_mermaid(raw)
    assert '"' not in sanitized
    assert "(" not in sanitized and ")" not in sanitized
    assert "[" not in sanitized and "]" not in sanitized
    assert "{" not in sanitized and "}" not in sanitized
    assert "<" not in sanitized and ">" not in sanitized
    assert "&" not in sanitized
    assert "#" not in sanitized

    # Check replacements
    assert "'Name'" in sanitized
    assert "❨Detail❩" in sanitized
    assert "❲Ref❲" not in sanitized and "❲Ref❳" in sanitized
    assert "❴Block❵" in sanitized
    assert "‹Tag›" in sanitized
    assert "+" in sanitized
    assert "Nr1" in sanitized


def test_moc_mermaid_reexport_contract():
    """Verify moc_mermaid re-exports the exact function instances from diagram_base."""
    assert moc_mermaid.wrap_label is wrap_label
    assert moc_mermaid.sanitize_mermaid is sanitize_mermaid
