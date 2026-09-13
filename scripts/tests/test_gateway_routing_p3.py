"""Unit tests for Port 8045 Smart Routing and Tier 1 Self-Healing in gateway_client.py."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from core.config import cfg
from core.llm.gateway_client import (
    _is_proxy_model,
    call_gateway,
    call_gateway_with_meta,
    consume_gateway_downgraded,
)
import core.llm.gateway_client as gc


def test_is_proxy_model():
    """Verify that only claude-* models trigger the proxy route."""
    assert _is_proxy_model("claude-opus-4-6-thinking") is True
    assert _is_proxy_model("claude-sonnet-4-6") is True
    assert _is_proxy_model("Claude-3-Haiku") is True
    assert _is_proxy_model("gemini-3.8-flash-high") is False
    assert _is_proxy_model("gemini-3.1-pro") is False
    assert _is_proxy_model("qwen-local-primary") is False


def test_route_claude_to_port_8045(monkeypatch):
    """Verify that claude-* requests are sent to gateway_proxy_url."""
    posted_urls = []

    def mock_post(url, headers, json, timeout):
        posted_urls.append(url)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Response from Claude on 8045"}}]
        }
        mock_resp.headers = {}
        return mock_resp

    monkeypatch.setattr(gc.http_session, "post", mock_post)
    monkeypatch.setattr(gc, "_proxy_cooldown_until", 0.0)

    res, downgraded = call_gateway_with_meta("Hello", model="claude-opus-4-6-thinking")
    assert res == "Response from Claude on 8045"
    assert downgraded is False
    assert any(":8045/v1/chat/completions" in u for u in posted_urls)


def test_route_gemini_to_port_8090(monkeypatch):
    """Verify that gemini-* requests are sent to standard gateway_url (8090)."""
    posted_urls = []

    def mock_post(url, headers, json, timeout):
        posted_urls.append(url)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Response from Gemini on 8090"}}]
        }
        mock_resp.headers = {}
        return mock_resp

    monkeypatch.setattr(gc.http_session, "post", mock_post)
    monkeypatch.setattr(gc, "_proxy_cooldown_until", 0.0)

    res, downgraded = call_gateway_with_meta("Hello", model="gemini-3.8-flash-high")
    assert res == "Response from Gemini on 8090"
    assert downgraded is False
    assert any(":8090/v1/chat/completions" in u for u in posted_urls)


def test_503_fallback_and_cooldown(monkeypatch):
    """Verify that HTTP 503 on 8045 triggers immediate fallback to 8090 and sets cooldown."""
    posted_urls = []

    def mock_post(url, headers, json, timeout):
        posted_urls.append(url)
        mock_resp = MagicMock()
        if ":8045" in url:
            mock_resp.status_code = 503
            mock_resp.text = "All accounts limited. Wait 20s."
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "Fallback response from Gemini Flash"}}]
            }
            mock_resp.headers = {}
        return mock_resp

    monkeypatch.setattr(gc.http_session, "post", mock_post)
    monkeypatch.setattr(gc, "_proxy_cooldown_until", 0.0)

    res, downgraded = call_gateway_with_meta("Deep query", model="claude-opus-4-6-thinking")
    assert res == "Fallback response from Gemini Flash"
    assert downgraded is True
    assert gc._proxy_cooldown_until > time.time()
    assert consume_gateway_downgraded() is True
    # Verify tracker is reset
    assert consume_gateway_downgraded() is False

    # Second call should bypass 8045 immediately due to active cooldown
    posted_urls.clear()
    res2, downgraded2 = call_gateway_with_meta("Another query", model="claude-opus-4-6-thinking")
    assert res2 == "Fallback response from Gemini Flash"
    assert downgraded2 is True
    assert not any(":8045" in u for u in posted_urls)
    assert any(":8090" in u for u in posted_urls)
