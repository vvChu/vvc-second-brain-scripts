"""Tests for Antigravity CLI autonomous artifact ingestion mechanism."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts dir is on sys.path
scripts_dir = Path(__file__).resolve().parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

import pytest
from core.llm.gemini_client import (
    _resolve_cli_artifact_content,
    call_antigravity_cli,
    is_antigravity_cli_supported,
)


def test_resolve_cli_artifact_content_empty_or_long():
    """Returns text as-is if empty or already exceeding 5000 chars."""
    assert _resolve_cli_artifact_content("") == ""
    long_text = "A" * 5001
    assert _resolve_cli_artifact_content(long_text) == long_text


def test_resolve_cli_artifact_content_no_match():
    """Returns text as-is if no file URI is found."""
    text = "Here is a standard response with no file URI."
    assert _resolve_cli_artifact_content(text) == text


def test_resolve_cli_artifact_content_success(tmp_path):
    """Successfully reads artifact content when URI points to valid file with sufficient size."""
    artifact_file = tmp_path / "article.md"
    content = "# Chapter 4: Autonomous Cells\n" + ("Detailed analysis paragraph.\n" * 50)
    artifact_file.write_text(content, encoding="utf-8")

    # Format URI like file:///C:/path...
    uri = artifact_file.as_uri()
    summary_text = f"I have written the complete chapter. You can inspect it at {uri}."

    result = _resolve_cli_artifact_content(summary_text)
    assert result == content.strip()
    assert len(result) > len(summary_text) * 2


def test_resolve_cli_artifact_content_two_slashes(tmp_path):
    """Successfully reads artifact content when URI format uses file://."""
    artifact_file = tmp_path / "document.md"
    content = "# Title\n" + ("Long essay content here.\n" * 40)
    artifact_file.write_text(content, encoding="utf-8")

    # Path format: file://C:/path...
    path_str = str(artifact_file).replace("\\", "/")
    uri = f"file://{path_str}"
    summary_text = f"Created artifact at: {uri}"

    result = _resolve_cli_artifact_content(summary_text)
    assert result == content.strip()


def test_resolve_cli_artifact_content_file_not_found():
    """Falls back to original text if referenced artifact file does not exist."""
    summary_text = "File written to file:///C:/non_existent_path_12345/non_existent.md"
    assert _resolve_cli_artifact_content(summary_text) == summary_text


def test_resolve_cli_artifact_content_size_too_small(tmp_path):
    """Falls back to original text if artifact size is not substantially larger than summary."""
    artifact_file = tmp_path / "tiny.md"
    artifact_file.write_text("Short text.", encoding="utf-8")

    uri = artifact_file.as_uri()
    summary_text = f"I have written the summary to {uri} which describes the issue."

    # Artifact is smaller than summary * 2
    assert _resolve_cli_artifact_content(summary_text) == summary_text


def test_resolve_cli_artifact_content_os_error(tmp_path):
    """Falls back to original text if reading file raises OSError."""
    artifact_file = tmp_path / "unreadable.md"
    artifact_file.write_text("Valid text" * 20, encoding="utf-8")
    uri = artifact_file.as_uri()
    summary_text = f"Done at {uri}"

    with patch.object(Path, "read_text", side_effect=OSError("Read failure")):
        assert _resolve_cli_artifact_content(summary_text) == summary_text


def test_call_antigravity_cli_with_artifact_ingestion(tmp_path):
    """call_antigravity_cli automatically ingests artifact content from CLI stdout."""
    artifact_file = tmp_path / "generated_chapter.md"
    full_content = "# Academic Chapter\n" + ("Comprehensive section text.\n" * 60)
    artifact_file.write_text(full_content, encoding="utf-8")

    uri = artifact_file.as_uri()
    mock_stdout = json.dumps({
        "status": "SUCCESS",
        "response": f"The chapter has been compiled at {uri}.",
    })

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = mock_stdout
    mock_run.stderr = ""

    with patch("subprocess.run", return_value=mock_run):
        output = call_antigravity_cli("Generate chapter 4", model="claude-opus-4-6-thinking")
        assert output == full_content.strip()


def test_is_antigravity_cli_supported():
    """Verifies prefix matching and modality filtering for Antigravity CLI."""
    assert is_antigravity_cli_supported("gemini-3.8-flash-low") is True
    assert is_antigravity_cli_supported("claude-opus-4-6-thinking") is True
    assert is_antigravity_cli_supported("gpt-oss-120b") is True

    # Excluded modalities & unsupported lite models
    assert is_antigravity_cli_supported("gemini-vision") is False
    assert is_antigravity_cli_supported("gemini-3.1-flash-lite-preview") is False
    assert is_antigravity_cli_supported("text-embedding-3") is False
    assert is_antigravity_cli_supported("imagen-3-image-generation") is False
    assert is_antigravity_cli_supported("") is False
    assert is_antigravity_cli_supported("random-unsupported-model") is False


def test_resolve_cli_artifact_content_from_full_stdout(tmp_path):
    """Resolves artifact content when URI is in full_stdout instead of final response text."""
    artifact_file = tmp_path / "stream_artifact.md"
    content = "# Chapter via Stream\n" + ("Paragraph from stream tool call.\n" * 50)
    artifact_file.write_text(content, encoding="utf-8")

    uri = artifact_file.as_uri()
    summary_text = "Chapter has been created. Here is the outline summary."
    full_stdout = f'{{"event": "tool_call", "output": "Created file {uri}"}}\n{{"event": "result", "response": "{summary_text}"}}'

    result = _resolve_cli_artifact_content(summary_text, full_stdout=full_stdout)
    assert result == content.strip()


def test_resolve_cli_artifact_content_fallback_scan(tmp_path):
    """Resolves artifact content via brain_dir fallback scan when URI is completely missing."""
    import time

    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    sub_session = brain_dir / "session-123"
    sub_session.mkdir()

    artifact_file = sub_session / "large_topic.md"
    content = "# Large Topic\n" + ("Detailed analysis section.\n" * 400)
    assert len(content.encode("utf-8")) >= 10000
    artifact_file.write_text(content, encoding="utf-8")

    summary_text = "Completed writing topic note. Summary provided here."
    t0 = time.time() - 10.0

    result = _resolve_cli_artifact_content(
        summary_text,
        min_mtime=t0,
        brain_dir=brain_dir,
    )
    assert result == content.strip()


def test_resolve_cli_artifact_content_fallback_scan_too_old(tmp_path):
    """Ignores artifact in brain_dir if it was modified before min_mtime threshold."""
    import time

    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    artifact_file = brain_dir / "old_topic.md"
    content = "# Old Topic\n" + ("Detailed analysis section.\n" * 200)
    artifact_file.write_text(content, encoding="utf-8")

    summary_text = "Standard response text."
    # min_mtime is in the future relative to file mtime
    future_time = time.time() + 1000.0

    result = _resolve_cli_artifact_content(
        summary_text,
        min_mtime=future_time,
        brain_dir=brain_dir,
    )
    assert result == summary_text

