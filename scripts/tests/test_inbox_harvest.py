"""Tests for inbox queue harvesting and sync conflict resolution."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import cfg
from services.brain_dump.inbox_io import (
    harvest_inbox_and_conflicts,
    has_pending_inbox_or_conflicts,
)


@pytest.fixture
def mock_inbox_env(tmp_path: Path):
    """Set up temporary vault directories for inbox testing."""
    fleeting = tmp_path / "05 - Fleeting"
    inbox = fleeting / "inbox"
    archive = tmp_path / "99 - Archive"
    dump_file = fleeting / "Brain_Dump.md"

    fleeting.mkdir(parents=True, exist_ok=True)
    inbox.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    dump_file.write_text("# Brain Dump\n\n## Inbox\n- existing item\n", encoding="utf-8")

    mock_cfg = dataclasses.replace(
        cfg,
        fleeting_dir=fleeting,
        archive_dir=archive,
        dump_file=dump_file,
        vault_root=tmp_path,
    )

    with (
        patch("services.brain_dump.inbox_io.cfg", mock_cfg),
        patch("core.daemon_utils.is_file_stable", return_value=True),
    ):
        yield {
            "fleeting": fleeting,
            "inbox": inbox,
            "archive": archive,
            "dump_file": dump_file,
        }


def test_has_pending_inbox_empty(mock_inbox_env):
    """Verify that empty inbox returns False."""
    assert has_pending_inbox_or_conflicts() is False


def test_harvest_timestamped_inbox_file(mock_inbox_env):
    """Verify harvesting discrete files from 05 - Fleeting/inbox/."""
    inbox_dir = mock_inbox_env["inbox"]
    dump_file = mock_inbox_env["dump_file"]
    archive_inbox = mock_inbox_env["archive"] / "inbox"

    note1 = inbox_dir / "2026-09-30_100000.md"
    note1.write_text("- https://example.com/insight1\n- Note content 1\n", encoding="utf-8")

    assert has_pending_inbox_or_conflicts() is True
    count = harvest_inbox_and_conflicts()

    assert count == 1
    assert not note1.exists()
    assert (archive_inbox / "2026-09-30_100000.md").exists()

    content = dump_file.read_text(encoding="utf-8")
    assert "https://example.com/insight1" in content
    assert "Note content 1" in content
    assert "existing item" in content


def test_harvest_conflict_dump_file(mock_inbox_env):
    """Verify harvesting Brain_Dump (1).md conflict files."""
    fleeting = mock_inbox_env["fleeting"]
    dump_file = mock_inbox_env["dump_file"]
    archive_inbox = mock_inbox_env["archive"] / "inbox"

    conflict_file = fleeting / "Brain_Dump (1).md"
    conflict_file.write_text("## Inbox\n- https://x.com/conflict_link\n- Mobile thought\n", encoding="utf-8")

    assert has_pending_inbox_or_conflicts() is True
    count = harvest_inbox_and_conflicts()

    assert count == 1
    assert not conflict_file.exists()
    assert (archive_inbox / "Brain_Dump (1).md").exists()

    content = dump_file.read_text(encoding="utf-8")
    assert "https://x.com/conflict_link" in content
    assert "Mobile thought" in content
