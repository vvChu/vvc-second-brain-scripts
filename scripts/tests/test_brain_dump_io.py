"""VvC Second Brain — Brain Dump Inbox I/O Tests (v1.0)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.config import cfg
from services.brain_dump.inbox_io import (
    _extract_inbox_sections,
    _find_pending_dump,
    _commit_inbox_changes,
    _clear_inbox_only,
)


def test_extract_inbox_sections():
    content = (
        "# Brain Dump\n\n"
        "## Inbox\n"
        "Some pending text.\n"
        "More lines.\n"
        "## Processed\n"
        "Old links.\n"
    )
    before, inbox, after = _extract_inbox_sections(content)
    
    assert before == "# Brain Dump\n\n## Inbox\n"
    assert inbox == "Some pending text.\nMore lines."
    assert after == "\n## Processed\nOld links.\n"


def test_extract_inbox_sections_missing():
    content = "# Brain Dump\nNo inbox section here.\n"
    before, inbox, after = _extract_inbox_sections(content)
    assert before == ""
    assert inbox == ""
    assert after == ""


def test_find_pending_dump():
    content = (
        "# Brain Dump\n"
        "## Inbox\n"
        "Hello from Inbox! This is long enough.\n"
        "## Processed\n"
    )
    res = _find_pending_dump(content)
    assert res == "Hello from Inbox! This is long enough."


def test_find_pending_dump_too_short():
    content = (
        "# Brain Dump\n"
        "## Inbox\n"
        "short\n"
        "## Processed\n"
    )
    res = _find_pending_dump(content)
    assert res is None


def test_find_pending_dump_legacy():
    content = (
        "# Brain Dump\n"
        "<!-- processed -->\n"
        "This is legacy pending text which is quite long enough."
    )
    res = _find_pending_dump(content)
    assert res == "This is legacy pending text which is quite long enough."


def test_clear_inbox_only(tmp_path):
    dump_file = tmp_path / "Brain_Dump.md"
    content = (
        "# Brain Dump\n"
        "## Inbox\n"
        "Line to keep.\n"
        "Line to clear.\n"
        "## Processed\n"
    )
    dump_file.write_text(content, encoding="utf-8")
    
    mock_cfg = dataclasses.replace(cfg, dump_file=dump_file)
    
    with patch("services.brain_dump.inbox_io.cfg", mock_cfg):
        _clear_inbox_only("Line to clear.")
        
    new_content = dump_file.read_text(encoding="utf-8")
    assert "Line to keep." in new_content
    assert "Line to clear." not in new_content


def test_commit_inbox_changes(tmp_path):
    dump_file = tmp_path / "Brain_Dump.md"
    content = (
        "# Brain Dump\n"
        "## Inbox\n"
        "Line to replace.\n"
        "Line to keep.\n"
        "## Processed\n"
        "- [[old_link]]\n"
    )
    dump_file.write_text(content, encoding="utf-8")
    
    mock_cfg = dataclasses.replace(cfg, dump_file=dump_file)
    
    with patch("services.brain_dump.inbox_io.cfg", mock_cfg), patch("services.brain_dump.inbox_io._rebuild_all") as mock_rebuild:
        _commit_inbox_changes(
            dump_text_to_replace="Line to replace.",
            new_inbox_content="New inbox append",
            links_to_append=["- [[new_link]]"],
            rebuild=True,
        )
        mock_rebuild.assert_called_once()
        
    new_content = dump_file.read_text(encoding="utf-8")
    assert "Line to replace." not in new_content
    assert "Line to keep." in new_content
    assert "New inbox append" in new_content
    assert "- [[new_link]]" in new_content
    assert "- [[old_link]]" in new_content
