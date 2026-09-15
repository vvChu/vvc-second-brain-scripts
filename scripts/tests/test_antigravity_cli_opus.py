"""Unit tests for Antigravity CLI Opus Tier 1 routing in core/llm/__init__.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from core.config import cfg
import core.llm as llm_module
from core.llm import call_llm
import core.llm.gemini_client as gemini_client


def test_call_llm_reasoning_routes_to_antigravity_cli_tier1(monkeypatch):
    """Verify that task='reasoning' routes to Antigravity CLI as Tier 1 with Opus."""
    calls = []

    def mock_agy(prompt, model="", timeout=60):
        calls.append(("antigravity-cli", model, timeout))
        return "Opus Deep Reasoning Result"

    def mock_gw(prompt, model="", timeout=60):
        calls.append(("gateway", model, timeout))
        return "Gateway Result"

    monkeypatch.setattr(llm_module, "call_antigravity_cli", mock_agy)
    monkeypatch.setattr(llm_module, "call_gateway", mock_gw)

    result = call_llm("Phân tích kiến trúc", task="reasoning")

    assert result == "Opus Deep Reasoning Result"
    assert len(calls) == 1
    tier, model_called, timeout = calls[0]
    assert tier == "antigravity-cli"
    assert model_called == "claude-opus-4-6-thinking"
    assert timeout == cfg.reasoning_timeout


def test_call_llm_explicit_claude_routes_to_antigravity_cli(monkeypatch):
    """Verify that explicit claude-* model routes to Antigravity CLI as Tier 1."""
    calls = []

    def mock_agy(prompt, model="", timeout=60):
        calls.append(("antigravity-cli", model, timeout))
        return "Sonnet Result"

    monkeypatch.setattr(llm_module, "call_antigravity_cli", mock_agy)

    result = call_llm("Viết code", model="claude-sonnet-4-6")

    assert result == "Sonnet Result"
    assert len(calls) == 1
    assert calls[0][0] == "antigravity-cli"
    assert calls[0][1] == "claude-sonnet-4-6"


def test_call_llm_fallback_to_gateway_when_cli_fails(monkeypatch):
    """Verify that if Antigravity CLI fails, call_llm seamlessly falls back to Gateway."""
    calls = []

    def mock_agy(prompt, model="", timeout=60):
        calls.append("antigravity-cli")
        return ""  # Failure or unavailable

    def mock_gw(prompt, model="", timeout=60):
        calls.append("gateway")
        return "Fallback Gateway Result"

    monkeypatch.setattr(llm_module, "call_antigravity_cli", mock_agy)
    monkeypatch.setattr(llm_module, "call_gateway", mock_gw)

    result = call_llm("Phân tích sâu", task="reasoning")

    assert result == "Fallback Gateway Result"
    assert calls == ["antigravity-cli", "gateway"]


def test_call_llm_synthesis_preserves_antigravity_cli_tier1(monkeypatch):
    """Verify that task='synthesis' prioritizes Gemini Flash via Antigravity CLI."""
    calls = []

    def mock_gemini_cli(prompt, model="", timeout=60):
        calls.append(("antigravity-cli", model))
        return "Synthesis Note"

    monkeypatch.setattr(llm_module, "call_gemini_cli", mock_gemini_cli)

    result = call_llm("Tóm tắt sách", task="synthesis")

    assert result == "Synthesis Note"
    assert len(calls) == 1
    assert calls[0][0] == "antigravity-cli"
    assert "flash" in calls[0][1]


def test_call_llm_general_flash_uses_antigravity_cli_tier1(monkeypatch):
    """Verify that task='general' with gemini-3.8-flash-high uses Antigravity CLI as Tier 1."""
    calls = []

    def mock_cli(prompt, model="", timeout=60):
        calls.append(("antigravity-cli", model))
        return "General Flash Response"

    monkeypatch.setattr(llm_module, "call_gemini_cli", mock_cli)

    result = call_llm("Câu hỏi chung", model="gemini-3.8-flash-high", task="general")

    assert result == "General Flash Response"
    assert len(calls) == 1
    assert calls[0][0] == "antigravity-cli"
    assert calls[0][1] == "gemini-3.8-flash-high"


def test_call_llm_non_cli_model_routes_to_gateway_tier1(monkeypatch):
    """Verify that models not supported by local CLI (e.g. qwen-local-primary) use Gateway as Tier 1."""
    calls = []

    def mock_gw(prompt, model="", timeout=60):
        calls.append(("gateway", model))
        return "Qwen Local GPU Response"

    monkeypatch.setattr(llm_module, "call_gateway", mock_gw)

    result = call_llm("GPU task", model="qwen-local-primary")

    assert result == "Qwen Local GPU Response"
    assert len(calls) == 1
    assert calls[0][0] == "gateway"
    assert calls[0][1] == "qwen-local-primary"


def test_call_gemini_cli_elevates_timeout_for_opus(monkeypatch):
    """Verify call_gemini_cli auto-elevates timeout to reasoning_timeout for Opus."""
    captured_args = {}

    def mock_run(args, **kwargs):
        captured_args["args"] = args
        captured_args["timeout"] = kwargs.get("timeout")
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = '{"status": "SUCCESS", "response": "OK"}'
        return mock_res

    monkeypatch.setattr(gemini_client, "_resolve_cli_path", lambda: "agy.exe")
    monkeypatch.setattr(gemini_client.subprocess, "run", mock_run)

    gemini_client.call_gemini_cli("Test prompt", model="claude-opus-4-6-thinking", timeout=60)

    assert captured_args["timeout"] == cfg.reasoning_timeout
    assert "--print-timeout" in captured_args["args"]
    assert f"{cfg.reasoning_timeout}s" in captured_args["args"]
