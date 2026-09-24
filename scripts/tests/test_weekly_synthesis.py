"""Tests for Weekly Synthesis report generator and shim contract.

Verifies isolated report compilation, broken links categorization,
and backward-compatible re-export from services.wiki_health.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.config import cfg
import services.wiki_health as wh
import services.weekly_synthesis as ws


@pytest.fixture
def isolated_vault(tmp_path: Path):
    """Isolate state_dir and log_file on frozen cfg dataclass."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "log.md"
    log_file.write_text("# Test Log\n", encoding="utf-8")

    orig_state_dir = cfg.state_dir
    orig_log_file = cfg.log_file

    object.__setattr__(cfg, "state_dir", state_dir)
    object.__setattr__(cfg, "log_file", log_file)

    yield tmp_path

    object.__setattr__(cfg, "state_dir", orig_state_dir)
    object.__setattr__(cfg, "log_file", orig_log_file)


def test_weekly_synthesis_shim_contract():
    """Verify that wiki_health re-exports the exact generate_weekly_synthesis function."""
    assert wh.generate_weekly_synthesis is ws.generate_weekly_synthesis


def test_weekly_synthesis_compilation(isolated_vault: Path):
    """Verify compilation of Weekly_Synthesis.md with mock report and concepts."""
    report = {
        "orphans": ["orphan_concept"],
        "broken_links": [
            {"from": "note_a", "to": "broken_target", "origin": "body"},
            {"from": "note_b", "to": "prospective_idea", "origin": "related"},
        ],
        "broken_body_links": [{"from": "note_a", "to": "broken_target", "origin": "body"}],
        "prospective_related_seeds": [{"from": "note_b", "to": "prospective_idea", "origin": "related"}],
    }
    concepts = [
        {"_stem": "orphan_concept", "title": "Orphan Concept", "source": "Book A.md", "date_created": "2026-09-20"},
        {"_stem": "note_a", "title": "Note A", "date_created": "2026-09-21"},
    ]
    sources = [{"_stem": "2026-09-20_Book_A", "title": "Book A"}]

    out_file = ws.generate_weekly_synthesis(
        report=report,  # type: ignore[arg-type]
        healed_links=2,
        healed_typos=1,
        academic_advice="Focus on Core Modules.",
        concepts=concepts,
        sources=sources,
    )

    assert out_file.exists()
    assert out_file.name == "Weekly_Synthesis.md"
    content = out_file.read_text(encoding="utf-8")

    assert "Weekly Synthesis" in content
    assert "Orphan Concept" in content or "orphan_concept" in content
    assert "broken_target" in content
    assert "prospective_idea" in content
    assert "Focus on Core Modules." in content


def test_weekly_synthesis_consumes_domain_and_subsume_state(isolated_vault: Path):
    """Verify consumption and cleanup of .domain_suggestions.json and .subsume_journal.jsonl."""
    state_dir = cfg.state_dir

    # Create dummy suggestions and subsume journal
    sugg_file = state_dir / ".domain_suggestions.json"
    sugg_file.write_text(json.dumps([{"concept_stem": "test_stem", "suggested_domain": "ai", "summary": "test"}]), encoding="utf-8")

    subsume_file = state_dir / ".subsume_journal.jsonl"
    subsume_file.write_text(
        json.dumps({"timestamp": "2026-09-22", "new_title": "Old Concept", "existing_concept": "target.md", "similarity_score": 0.92}) + "\n",
        encoding="utf-8",
    )

    out_file = ws.generate_weekly_synthesis(
        report={"orphans": []},  # type: ignore[arg-type]
        concepts=[],
        sources=[],
    )

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "domain/ai" in content
    assert "Old Concept" in content

    # Verify state files are safely cleaned up
    assert not sugg_file.exists()
    assert not subsume_file.exists()
