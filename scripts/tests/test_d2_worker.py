"""VvC Second Brain — Unit Tests for D2 Vector Diagram Worker (v8.13.0).

Verifies:
1. _clean_d2 strips fences (```d2 ... ``` and ``` ... ```) and handles edge cases.
2. compile_d2_via_kroki sends correct HTTP POST and returns SVG content.
3. compile_d2_to_svg routes to local d2 CLI when available.
4. compile_d2_to_svg falls back to Kroki when d2 CLI is absent or fails.
5. _generate_d2 saves both .svg and .d2 files and logs to diagram log.
6. Error handling when LLM returns empty or compilation fails.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from services.d2_worker import (
    _clean_d2,
    compile_d2_via_kroki,
    compile_d2_to_svg,
    trigger_d2_generation,
    _generate_d2,
)


# --- Test 1: _clean_d2 ---

def test_clean_d2_with_d2_fence():
    raw = "```d2\na -> b: connects\n```"
    assert _clean_d2(raw) == "a -> b: connects"


def test_clean_d2_with_generic_fence():
    raw = "```\nserver -> client: response\n```"
    assert _clean_d2(raw) == "server -> client: response"


def test_clean_d2_with_surrounding_text():
    raw = (
        "Here is the architecture diagram in D2 format:\n\n"
        "```d2\n"
        "frontend -> backend: API call\n"
        "backend -> database: query\n"
        "```\n\n"
        "I hope this helps visualize the system."
    )
    expected = "frontend -> backend: API call\nbackend -> database: query"
    assert _clean_d2(raw) == expected


def test_clean_d2_no_fences():
    raw = "x -> y: link"
    assert _clean_d2(raw) == "x -> y: link"


def test_clean_d2_empty():
    assert _clean_d2("") == ""
    assert _clean_d2("   \n\n  ") == ""


# --- Test 2: compile_d2_via_kroki ---

@patch("urllib.request.urlopen")
def test_compile_d2_via_kroki_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<svg><g>d2-diagram</g></svg>"
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    svg = compile_d2_via_kroki("nodeA -> nodeB", timeout=10.0)

    assert svg == "<svg><g>d2-diagram</g></svg>"
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://kroki.io/d2/svg"
    assert req.data == b"nodeA -> nodeB"
    assert req.headers["Content-type"] == "text/plain; charset=utf-8"


@patch("urllib.request.urlopen")
def test_compile_d2_via_kroki_failure(mock_urlopen):
    mock_urlopen.side_effect = TimeoutError("Kroki timed out")

    with pytest.raises(RuntimeError, match="Kroki D2 compilation failed"):
        compile_d2_via_kroki("nodeA -> nodeB")


# --- Test 3: compile_d2_to_svg with local d2 CLI ---

@patch("shutil.which")
@patch("subprocess.run")
def test_compile_d2_to_svg_local_cli(mock_subproc, mock_which, tmp_path):
    mock_which.return_value = "C:\\bin\\d2.exe"
    out_svg = tmp_path / "diagram.svg"
    out_svg.write_text("<svg>from-local-d2</svg>", encoding="utf-8")

    mock_res = MagicMock()
    mock_subproc.return_value = mock_res

    res = compile_d2_to_svg("a -> b", output_svg_path=out_svg)

    assert res == "<svg>from-local-d2</svg>"
    mock_subproc.assert_called_once()
    assert mock_subproc.call_args[0][0] == ["C:\\bin\\d2.exe", "-", str(out_svg)]


def test_compile_d2_to_svg_empty_code():
    assert compile_d2_to_svg("") is None
    assert compile_d2_to_svg("   \n\n  ") is None


def test_clean_d2_unclosed_fence():
    raw = "Here is the diagram:\n```d2\nx -> y: link"
    assert _clean_d2(raw) == "x -> y: link"


# --- Test 4: compile_d2_to_svg fallback to Kroki ---

@patch("shutil.which")
@patch("services.d2_worker.compile_d2_via_kroki")
def test_compile_d2_to_svg_fallback_when_cli_missing(mock_kroki, mock_which, tmp_path):
    mock_which.return_value = None
    mock_kroki.return_value = "<svg>from-kroki</svg>"
    out_svg = tmp_path / "diagram.svg"

    res = compile_d2_to_svg("a -> b", output_svg_path=out_svg)

    assert res == "<svg>from-kroki</svg>"
    assert out_svg.read_text(encoding="utf-8") == "<svg>from-kroki</svg>"
    mock_kroki.assert_called_once_with("a -> b", timeout=15.0)


@patch("shutil.which")
@patch("subprocess.run")
@patch("services.d2_worker.compile_d2_via_kroki")
def test_compile_d2_to_svg_fallback_when_cli_fails(mock_kroki, mock_subproc, mock_which, tmp_path):
    mock_which.return_value = "/usr/bin/d2"
    mock_subproc.side_effect = RuntimeError("d2 syntax error")
    mock_kroki.return_value = "<svg>fallback-kroki</svg>"
    out_svg = tmp_path / "diagram.svg"

    res = compile_d2_to_svg("a -> b", output_svg_path=out_svg)

    assert res == "<svg>fallback-kroki</svg>"
    mock_kroki.assert_called_once_with("a -> b", timeout=15.0)


# --- Test 5: _generate_d2 end-to-end saving .svg and .d2 ---

@patch("services.d2_worker.call_llm")
@patch("services.d2_worker.compile_d2_to_svg")
def test_generate_d2_saves_svg_and_raw_d2(mock_compile, mock_llm, tmp_path, monkeypatch):
    import dataclasses
    from core.config import cfg

    mock_cfg = dataclasses.replace(cfg, attachments_dir=tmp_path)
    monkeypatch.setattr("services.d2_worker.cfg", mock_cfg)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    mock_llm.return_value = "```d2\nsubsystem -> gateway\n```"
    mock_compile.return_value = "<svg>compiled-vector</svg>"

    source_text = "Here is the diagram: ![[architecture.d2.svg|100%]] and details."
    _generate_d2("architecture.d2.svg|100%", source_text)

    # Check that raw .d2 code was saved
    d2_file = tmp_path / "architecture.d2"
    assert d2_file.exists()
    assert d2_file.read_text(encoding="utf-8") == "subsystem -> gateway"

    # Check that .svg file was saved
    svg_file = tmp_path / "architecture.d2.svg"
    assert svg_file.exists()
    assert svg_file.read_text(encoding="utf-8") == "<svg>compiled-vector</svg>"


# --- Test 6: _generate_d2 gracefully handles empty LLM response ---

@patch("services.d2_worker.call_llm")
def test_generate_d2_handles_empty_llm_response(mock_llm, tmp_path, monkeypatch):
    import dataclasses
    from core.config import cfg

    mock_cfg = dataclasses.replace(cfg, attachments_dir=tmp_path)
    monkeypatch.setattr("services.d2_worker.cfg", mock_cfg)

    mock_llm.return_value = ""

    _generate_d2("empty.d2.svg", "text without content")

    svg_file = tmp_path / "empty.d2.svg"
    assert not svg_file.exists()
