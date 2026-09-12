"""Unit tests for Antigravity CLI (gemini_client.py) stream-json support."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from core.llm.gemini_client import call_gemini_cli


def test_call_gemini_cli_short_prompt():
    """Short prompt (<= 30000 chars) should use -p and --output-format json."""
    short_prompt = "Hello, what is AI?"
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "status": "SUCCESS",
        "response": "AI is artificial intelligence.",
        "duration_seconds": 1.2,
        "usage": {"input_tokens": 10, "output_tokens": 20, "thinking_tokens": 0, "cache_read_tokens": 0}
    })

    with patch("core.llm.gemini_client.subprocess.run", return_value=mock_result) as mock_run:
        resp = call_gemini_cli(short_prompt, model="gemini-3.8-flash-high")
        assert resp == "AI is artificial intelligence."
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd_args = args[0]
        assert "-p" in cmd_args
        assert short_prompt in cmd_args
        assert "--input-format" not in cmd_args
        assert kwargs.get("input") is None


def test_call_gemini_cli_long_prompt_stream_json():
    """Long prompt (> 30000 chars) should switch to stream-json over stdin."""
    long_prompt = "Context line.\n" * 2500  # ~35,000 chars
    assert len(long_prompt) > 30000

    ndjson_lines = [
        json.dumps({"event": "init", "init": {"cwd": "D:\\"}}),
        json.dumps({"event": "step_update", "step_update": {"step_index": 0}}),
        json.dumps({
            "event": "result",
            "result": {
                "status": "SUCCESS",
                "response": "Synthesized concept based on large context.",
                "duration_seconds": 5.4,
                "usage": {"input_tokens": 8000, "output_tokens": 150, "thinking_tokens": 50, "cache_read_tokens": 0}
            }
        }),
    ]
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "\n".join(ndjson_lines)

    with patch("core.llm.gemini_client.subprocess.run", return_value=mock_result) as mock_run:
        resp = call_gemini_cli(long_prompt, model="gemini-3.8-flash-high")
        assert resp == "Synthesized concept based on large context."
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd_args = args[0]
        assert "-p" not in cmd_args
        assert "--input-format" in cmd_args
        assert "stream-json" in cmd_args
        # Stdin payload must contain the prompt
        input_data = kwargs.get("input")
        assert input_data is not None
        payload = json.loads(input_data)
        assert payload.get("event") == "user"
        assert payload.get("message", {}).get("content") == long_prompt


def test_call_gemini_cli_stream_error_handling():
    """Stream-json with error status or non-zero exit code should fail safely."""
    long_prompt = "X" * 31000

    # Case 1: Non-zero exit code
    mock_fail = MagicMock()
    mock_fail.returncode = 1
    mock_fail.stderr = "Process crashed"
    with patch("core.llm.gemini_client.subprocess.run", return_value=mock_fail):
        assert call_gemini_cli(long_prompt) == ""

    # Case 2: Status ERROR in NDJSON
    mock_error_status = MagicMock()
    mock_error_status.returncode = 0
    mock_error_status.stdout = json.dumps({
        "event": "result",
        "result": {"status": "ERROR", "error": "Internal error"}
    })
    with patch("core.llm.gemini_client.subprocess.run", return_value=mock_error_status):
        assert call_gemini_cli(long_prompt) == ""
