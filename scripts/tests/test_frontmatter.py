"""Tests for core.frontmatter module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.frontmatter import (
    build_concept_frontmatter,
    build_frontmatter,
    extract_body,
    normalize_stem,
    parse_frontmatter,
    update_field,
)


def test_parse_frontmatter_basic():
    """Should parse YAML frontmatter from markdown."""
    content = "---\ntitle: Test\ntype: concept\n---\n\n# Body"
    fm = parse_frontmatter(content)
    assert fm["title"] == "Test"
    assert fm["type"] == "concept"


def test_parse_frontmatter_empty():
    """Should return empty dict when no frontmatter."""
    assert parse_frontmatter("# No frontmatter") == {}
    assert parse_frontmatter("") == {}


def test_extract_body():
    """Should extract body after frontmatter."""
    content = "---\ntitle: Test\n---\n\n# Body\nText here"
    body = extract_body(content)
    assert body.strip().startswith("# Body")
    assert "Text here" in body


def test_build_frontmatter():
    """Should build valid YAML frontmatter."""
    fm = build_frontmatter({"title": "Test", "type": "concept"})
    assert fm.startswith("---\n")
    assert fm.endswith("---\n")
    assert "title: Test" in fm


def test_build_concept_frontmatter():
    """Should build concept-specific frontmatter with all fields."""
    fm = build_concept_frontmatter(
        "Transformer Architecture",
        tags=["domain/ai"],
        source="test_book",
        source_page="123",
        source_chapter="Chapter 1",
        ground_truth_page="456",
        ground_truth_chapter="Chapter 1 EN",
        summary="A test summary",
        people=["Jensen Huang"],
        companies=["Nvidia"],
        status="growing",
    )
    parsed = parse_frontmatter(fm + "\n# Body\n")
    assert parsed["title"] == "Transformer Architecture"
    assert "domain/ai" in parsed["tags"]
    assert "knowledge" in parsed["tags"]
    assert "type/concept" in parsed["tags"]
    assert parsed["source"] == "test_book"
    assert parsed["source_page"] == "123"
    assert parsed["source_chapter"] == "Chapter 1"
    assert parsed["ground_truth_page"] == "456"
    assert parsed["ground_truth_chapter"] == "Chapter 1 EN"
    assert parsed["type"] == "concept"
    assert parsed["people"] == ["Jensen Huang"]
    assert parsed["companies"] == ["Nvidia"]
    assert parsed["status"] == "growing"


def test_normalize_stem():
    """Should normalize filenames consistently."""
    assert normalize_stem("  foo__bar  ") == "foo_bar"
    assert normalize_stem("AI_HALLUCINATION") == "ai_hallucination"
    assert normalize_stem("test___name___") == "test_name"
    assert normalize_stem("simple") == "simple"


def test_update_field():
    """Should update a single field in frontmatter."""
    content = "---\ntitle: Old\ntype: concept\n---\n\n# Body"
    updated = update_field(content, "title", "New Title")
    fm = parse_frontmatter(updated)
    assert fm["title"] == "New Title"
    assert "# Body" in extract_body(updated)


def test_roundtrip():
    """Parse → modify → build should preserve data."""
    original = build_concept_frontmatter("Test", source="book1")
    body = "\n# Test\n\nBody content"
    full = original + body

    fm = parse_frontmatter(full)
    fm["confidence"] = "low"
    rebuilt = build_frontmatter(fm) + extract_body(full)

    fm2 = parse_frontmatter(rebuilt)
    assert fm2["title"] == "Test"
    assert fm2["confidence"] == "low"
    assert "Body content" in extract_body(rebuilt)


def test_parse_and_extract_with_utf8_bom():
    """Should correctly strip UTF-8 BOM and parse frontmatter and body."""
    bom_content = "\ufeff---\ntitle: BOM Test\ntype: topic\n---\n\n# Body with BOM"
    fm = parse_frontmatter(bom_content)
    assert fm["title"] == "BOM Test"
    assert fm["type"] == "topic"

    body = extract_body(bom_content)
    assert body.strip().startswith("# Body with BOM")
    assert not body.startswith("\ufeff")
    assert "---" not in body


def test_parse_and_extract_with_crlf():
    """Should correctly parse frontmatter and extract body with CRLF line endings."""
    crlf_content = "---\r\ntitle: CRLF Test\r\ntype: topic\r\n---\r\n\r\n# Body with CRLF"
    fm = parse_frontmatter(crlf_content)
    assert fm["title"] == "CRLF Test"
    assert fm["type"] == "topic"

    body = extract_body(crlf_content)
    assert body.strip().startswith("# Body with CRLF")

