"""Unit tests for core.llm.model_resolver module.

Tests dynamic model resolution, version parsing, 24h caching, TTL expiration,
offline fallback to STATIC_LATEST_GEMINI_FLASH, and passthrough of explicit models.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.llm.model_resolver import (
    STATIC_LATEST_GEMINI_FLASH,
    CACHE_TTL_SECONDS,
    DYNAMIC_MODEL_PATTERN,
    GEMINI_FLASH_VERSION_PATTERN,
    fetch_available_models,
    find_highest_gemini_flash,
    is_dynamic_model,
    load_models_cache,
    parse_version_tuple,
    resolve_model,
    save_models_cache,
)


# ── 1. Passthrough of Explicit Model Names ──


def test_explicit_model_passthrough():
    """Explicit model names must pass through untouched without making network calls."""
    explicit_models = [
        "gemini-3.8-flash-high",
        "gemini-3.8-flash-low",
        "gemini-3.7-flash-high",
        "gemini-3.1-flash-lite",
        "claude-opus-4-6-thinking",
        "claude-3-7-sonnet",
        "gpt-5-mini",
        "gpt-4o",
        "ocr-primary",
    ]
    with patch("core.llm.model_resolver.http_session.get") as mock_get:
        for model in explicit_models:
            resolved = resolve_model(model)
            assert resolved == model
        assert mock_get.call_count == 0


def test_empty_model_passthrough():
    """Empty or whitespace-only model names should return empty string."""
    assert resolve_model("") == ""
    assert resolve_model("   ") == ""


# ── 2. Dynamic Alias Detection ──


def test_is_dynamic_model():
    """Verify alias detection logic for various latest/auto forms."""
    assert is_dynamic_model("latest")
    assert is_dynamic_model("auto")
    assert is_dynamic_model("gemini-latest")
    assert is_dynamic_model("gemini-flash-latest")
    assert is_dynamic_model("gemini-latest-high")
    assert is_dynamic_model("gemini-latest-low")
    assert is_dynamic_model("gemini-latest-medium")
    assert is_dynamic_model("latest-high")
    assert is_dynamic_model("latest-low")
    assert is_dynamic_model("auto-low")
    assert is_dynamic_model("gemini-flash-latest-high")
    assert is_dynamic_model("LATEST")
    assert is_dynamic_model("Auto")
    assert is_dynamic_model("  latest  ")

    # Non-dynamic models
    assert not is_dynamic_model("gemini-3.8-flash-high")
    assert not is_dynamic_model("claude-opus-4-6-thinking")
    assert not is_dynamic_model("gpt-5-mini")
    assert not is_dynamic_model("")


# ── 3. Version Parsing & Numeric Comparison ──


def test_parse_version_tuple():
    """Verify numeric version parsing."""
    assert parse_version_tuple("3.8") == (3, 8)
    assert parse_version_tuple("3.10") == (3, 10)
    assert parse_version_tuple("3.10.1") == (3, 10, 1)
    assert parse_version_tuple("2") == (2,)
    assert parse_version_tuple("invalid") == (0,)


def test_numeric_version_ordering():
    """Verify that version comparison is numeric, e.g. 3.10 > 3.9 > 3.8 > 3.7 > 3.5."""
    v_3_5 = parse_version_tuple("3.5")
    v_3_7 = parse_version_tuple("3.7")
    v_3_8 = parse_version_tuple("3.8")
    v_3_9 = parse_version_tuple("3.9")
    v_3_10 = parse_version_tuple("3.10")

    assert v_3_10 > v_3_9 > v_3_8 > v_3_7 > v_3_5


def test_find_highest_gemini_flash():
    """Find highest version among a list of models."""
    sample_models = [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-3.5-flash-low",
        "gemini-3.7-flash-high",
        "gemini-3.8-flash-high",
        "gemini-3.8-flash-low",
        "claude-opus-4-6-thinking",
        "gpt-5-mini",
    ]
    res = find_highest_gemini_flash(sample_models)
    assert res is not None
    v_tuple, v_str, matched = res
    assert v_tuple == (3, 8)
    assert v_str == "3.8"
    assert "gemini-3.8-flash-high" in matched
    assert "gemini-3.8-flash-low" in matched


def test_find_highest_gemini_flash_future_version():
    """Demonstrate future-proofing: detects 3.10 over 3.8."""
    future_models = [
        "gemini-3.7-flash-high",
        "gemini-3.8-flash-high",
        "gemini-3.10-flash-high",
        "gemini-3.9-flash-high",
    ]
    res = find_highest_gemini_flash(future_models)
    assert res is not None
    v_tuple, v_str, matched = res
    assert v_tuple == (3, 10)
    assert v_str == "3.10"
    assert "gemini-3.10-flash-high" in matched


# ── 4. Dynamic Resolution with Cache & Mock Gateway ──


def test_resolve_model_with_mock_gateway(tmp_path):
    """Dynamic resolution queries Gateway and applies correct tiers."""
    cache_file = tmp_path / "models_cache.json"

    mock_models_response = {
        "object": "list",
        "data": [
            {"id": "gemini-2.0-flash"},
            {"id": "gemini-3.7-flash-high"},
            {"id": "gemini-3.8-flash-high"},
            {"id": "gemini-3.8-flash-low"},
            {"id": "gemini-3.8-flash-medium"},
            {"id": "claude-3-7-sonnet"},
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_models_response

    with patch("core.llm.model_resolver.http_session.get", return_value=mock_resp):
        # Default tier is high for general
        assert resolve_model("latest", cache_path=cache_file) == "gemini-3.8-flash-high"
        assert resolve_model("auto", cache_path=cache_file) == "gemini-3.8-flash-high"
        assert resolve_model("gemini-latest", cache_path=cache_file) == "gemini-3.8-flash-high"
        assert resolve_model("gemini-flash-latest", cache_path=cache_file) == "gemini-3.8-flash-high"

        # Explicit tier in alias
        assert resolve_model("gemini-latest-low", cache_path=cache_file) == "gemini-3.8-flash-low"
        assert resolve_model("latest-low", cache_path=cache_file) == "gemini-3.8-flash-low"
        assert resolve_model("gemini-latest-high", cache_path=cache_file) == "gemini-3.8-flash-high"
        assert resolve_model("latest-medium", cache_path=cache_file) == "gemini-3.8-flash-medium"
        assert resolve_model("auto-low", cache_path=cache_file) == "gemini-3.8-flash-low"

        # Task defaults
        assert resolve_model("latest", task="synthesis", cache_path=cache_file) == "gemini-3.8-flash-high"
        assert resolve_model("latest", task="reasoning", cache_path=cache_file) == "gemini-3.8-flash-high"
        assert resolve_model("latest", task="vision", cache_path=cache_file) == "gemini-3.8-flash-low"
        assert resolve_model("latest", task="correction", cache_path=cache_file) == "gemini-3.8-flash-low"
        assert resolve_model("latest", task="fast", cache_path=cache_file) == "gemini-3.8-flash-low"


# ── 5. Offline Fallback to Static Constant ──


def test_offline_fallback_when_gateway_unreachable(tmp_path):
    """When Gateway and API are unreachable and cache is empty, fallback deterministically."""
    cache_file = tmp_path / "nonexistent_cache.json"

    with patch("core.llm.model_resolver.http_session.get", side_effect=requests.ConnectionError("Offline")):
        # High tier fallback equals STATIC_LATEST_GEMINI_FLASH
        res_high = resolve_model("latest", cache_path=cache_file)
        assert res_high == STATIC_LATEST_GEMINI_FLASH
        assert res_high == "gemini-3.8-flash-high"

        # Auto resolves to high
        assert resolve_model("auto", cache_path=cache_file) == "gemini-3.8-flash-high"

        # Low tier fallback
        res_low = resolve_model("latest-low", cache_path=cache_file)
        assert res_low == "gemini-3.8-flash-low"

        # Vision task resolves to low tier fallback
        res_vision = resolve_model("latest", task="vision", cache_path=cache_file)
        assert res_vision == "gemini-3.8-flash-low"


# ── 6. Cache File Generation & TTL Reading ──


def test_cache_file_generation_and_saving(tmp_path):
    """Saving and loading cache writes timestamp and models correctly."""
    cache_file = tmp_path / ".models_cache.json"
    models = ["gemini-3.8-flash-high", "gemini-3.8-flash-low"]

    save_models_cache(models, cache_path=cache_file)
    assert cache_file.exists()

    data = load_models_cache(cache_file)
    assert data is not None
    assert data["models"] == models
    assert isinstance(data["timestamp"], (int, float))
    assert time.time() - data["timestamp"] < 5


def test_cache_ttl_fresh_does_not_hit_network(tmp_path):
    """Fresh cache (< 24 hours) bypasses network request entirely."""
    cache_file = tmp_path / ".models_cache.json"
    models = ["gemini-3.8-flash-high", "gemini-3.8-flash-low"]
    # Write fresh cache (1 hour old)
    data = {
        "timestamp": time.time() - 3600,
        "models": models,
    }
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    with patch("core.llm.model_resolver.http_session.get") as mock_get:
        fetched = fetch_available_models(cache_path=cache_file)
        assert fetched == models
        assert mock_get.call_count == 0


def test_cache_ttl_expired_triggers_refresh(tmp_path):
    """Expired cache (> 24 hours) triggers network refresh."""
    cache_file = tmp_path / ".models_cache.json"
    stale_models = ["gemini-3.5-flash-high"]
    # Write expired cache (25 hours old)
    data = {
        "timestamp": time.time() - (CACHE_TTL_SECONDS + 3600),
        "models": stale_models,
    }
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    refreshed_models = ["gemini-3.8-flash-high", "gemini-3.8-flash-low"]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": m} for m in refreshed_models]}

    with patch("core.llm.model_resolver.http_session.get", return_value=mock_resp) as mock_get:
        fetched = fetch_available_models(cache_path=cache_file)
        assert fetched == refreshed_models
        assert mock_get.call_count == 1


def test_stale_cache_fallback_when_offline(tmp_path):
    """If cache is expired but network fails, stale cache is used rather than failing."""
    cache_file = tmp_path / ".models_cache.json"
    cached_models = ["gemini-3.8-flash-high"]
    data = {
        "timestamp": time.time() - (CACHE_TTL_SECONDS + 7200),  # 26 hours old
        "models": cached_models,
    }
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    with patch("core.llm.model_resolver.http_session.get", side_effect=requests.ConnectionError("Offline")):
        fetched = fetch_available_models(cache_path=cache_file)
        assert fetched == cached_models


# ── 7. Integration with call_llm & Clients ──


def test_call_llm_with_latest_alias():
    """call_llm with model='latest' resolves to latest model for the tier."""
    from core.llm import call_llm

    with patch("core.llm.call_antigravity_cli") as mock_agy, \
         patch("core.llm.call_gemini_cli") as mock_gcli:
        mock_agy.return_value = "Resolved successfully"
        mock_gcli.return_value = "Resolved successfully"
        res = call_llm("test prompt", model="latest", task="general")
        assert res == "Resolved successfully"
        called = mock_agy.call_args or mock_gcli.call_args
        assert called[1]["model"] == "gemini-3.8-flash-high"


def test_call_gateway_resolves_latest():
    """call_gateway with model='latest-low' passes resolved model in payload."""
    from core.llm.gateway_client import call_gateway

    with patch("core.llm.gateway_client.http_session.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"x-litellm-model": "gemini-3.8-flash-low"}
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Gateway response"}}]
        }
        mock_post.return_value = mock_resp

        res = call_gateway("test prompt", model="latest-low")
        assert res == "Gateway response"
        called_payload = mock_post.call_args[1]["json"]
        assert called_payload["model"] == "gemini-3.8-flash-low"


def test_gemini_client_normalization_supports_gemini_3_8():
    """Verify gemini_client normalizes gemini-3.8-flash to gemini-3.8-flash-high."""
    from core.llm.gemini_client import call_gemini_cli

    with patch("core.llm.gemini_client._resolve_cli_path", return_value="agy.exe"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.return_value.returncode = 0
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"status": "SUCCESS", "response": "OK"})
        mock_run.return_value = mock_proc

        call_gemini_cli("hello", model="gemini-3.8-flash")
        args = mock_run.call_args[0][0]
        model_idx = args.index("--model") + 1
        assert args[model_idx] == "gemini-3.8-flash-high"
