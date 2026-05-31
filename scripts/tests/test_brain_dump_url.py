"""VvC Second Brain — Brain Dump URL Registry & Processing Tests (v1.0)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from services.brain_dump.url_registry import (
    _load_url_registry,
    _save_url_registry,
    _normalize_url,
    _check_override,
    _process_urls,
    _extract_related_links,
)


def test_load_save_url_registry(tmp_path):
    tmp_registry_file = tmp_path / ".processed_urls.json"
    
    with patch("services.brain_dump.url_registry._URL_REGISTRY_FILE", tmp_registry_file):
        # Empty registry should be loaded initially
        reg = _load_url_registry()
        assert reg == {}
        
        # Save a new registry entry
        new_reg = {"host/path": "2026-05-31"}
        _save_url_registry(new_reg)
        
        # Registry should load successfully
        reg = _load_url_registry()
        assert reg == new_reg


def test_normalize_url():
    # Normal URL
    assert _normalize_url("https://www.google.com/path/to/page/") == "google.com/path/to/page"
    assert _normalize_url("http://GOOGLE.com/Path/") == "google.com/Path"
    
    # YouTube URL keeping 'v' parameter
    assert _normalize_url("https://www.youtube.com/watch?v=12345&t=99s") == "youtube.com/watch?v=12345"
    assert _normalize_url("https://youtu.be/12345") == "youtu.be/12345"
    
    # Garbage url fallback
    assert _normalize_url("not-a-valid-url") == "not-a-valid-url"


def test_check_override():
    assert _check_override("xử lý lại url này") is True
    assert _check_override("force reprocessing") is True
    assert _check_override("reprocess: https://google.com") is True
    assert _check_override("https://google.com override") is True
    assert _check_override("just a regular line https://google.com") is False


@patch("services.brain_dump.url_registry.fetch_url")
def test_process_urls(mock_fetch):
    mock_fetch.side_effect = lambda url, visual=False: f"Scraped content of {url}"
    
    dump_text = "Check out these URLs: https://google.com and https://youtube.com/watch?v=123"
    
    # Test processing all URLs
    res = _process_urls(dump_text)
    assert "[https://google.com]" in res
    assert "Scraped content of https://google.com" in res
    assert "[https://youtube.com/watch?v=123]" in res
    assert "Scraped content of https://youtube.com/watch?v=123" in res


@patch("requests.get")
def test_extract_related_links(mock_get):
    # Mock HTML response with multiple anchors
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
    <html>
        <body>
            <a href="https://example.com/valid-article">Valid Article</a>
            <a href="https://twitter.com/intent/tweet?text=hello">Twitter Noise</a>
            <a href="/relative-path">Relative Path</a>
            <a href="https://github.com/owner/repo/tree/master/src">GitHub subpath noise</a>
            <a href="https://github.com/owner/repo">GitHub repo root (content)</a>
            <a href="https://medium.com/post-title">Medium Article</a>
            <a href="https://example.com/another-valid">Another same-domain</a>
            <a href="mailto:test@example.com">Mailto link</a>
        </body>
    </html>
    """
    mock_get.return_value = mock_resp
    
    # We scrape "https://example.com/home"
    res = _extract_related_links("https://example.com/home")
    
    # Expected results:
    # 1. example.com/valid-article (same domain)
    # 2. example.com/relative-path (resolved to https://example.com/relative-path, same domain)
    # 3. github.com/owner/repo (content domain, repo root)
    # 4. medium.com/post-title (content domain)
    # 5. example.com/another-valid (same domain)
    
    # Discarded results:
    # - twitter.com/intent/tweet (noise pattern)
    # - github.com/owner/repo/tree/master/src (GitHub subpath)
    # - mailto:test@example.com (non-http)
    
    assert "https://example.com/valid-article" in res
    assert "https://example.com/relative-path" in res
    assert "https://github.com/owner/repo" in res
    assert "https://medium.com/post-title" in res
    assert "https://example.com/another-valid" in res
    
    assert "https://twitter.com/intent/tweet?text=hello" not in res
    assert "https://github.com/owner/repo/tree/master/src" not in res
    assert "mailto:test@example.com" not in res
