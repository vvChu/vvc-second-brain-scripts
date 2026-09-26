"""VvC Second Brain — Brain Dump: URL Registry & Processing.

Handles URL deduplication, normalization, override detection, URL fetching,
noise link filtering, and related link extraction.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.config import cfg
from services.url_fetcher import fetch_url

_logger = logging.getLogger("vvc.dump")

# --- URL Extraction ---

_URL_PATTERN = re.compile(r"https?://[^\s\]\)>]+")


# --- URL Deduplication Registry (v8.9) ---

_URL_REGISTRY_FILE = cfg.state_dir / ".processed_urls.json"
_OVERRIDE_KEYWORDS = [
    "xử lý lại", "tải lại", "nạp lại", "chạy lại", "cập nhật",
    "reprocess", "/force", "force", "override"
]

def _load_url_registry() -> dict:
    """Tải registry lưu trữ lịch sử xử lý URL."""
    try:
        if _URL_REGISTRY_FILE.exists():
            return json.loads(_URL_REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning(f"Không thể đọc registry URL: {e}")
    return {}

def _save_url_registry(registry: dict) -> None:
    """Ghi registry lưu trữ lịch sử xử lý URL."""
    try:
        _URL_REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _logger.warning(f"Không thể ghi registry URL: {e}")

def _normalize_url(url: str) -> str:
    """Chuẩn hóa URL để đối chiếu trùng lặp chính xác nhất."""
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        
        query = ""
        # Đặc cách Youtube: giữ lại query v để phân biệt video
        if "youtube.com" in host or "youtu.be" in host:
            qs = parse_qs(parsed.query)
            if 'v' in qs:
                query = f"?v={qs['v'][0]}"
        # Apple Podcasts: Bỏ tiền tố quốc gia (/us/podcast -> /podcast), giữ query ?i=
        elif "podcasts.apple.com" in host:
            path = re.sub(r"^/[a-z]{2}/podcast", "/podcast", path, flags=re.IGNORECASE)
            qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
            if 'i' in qs:
                query = f"?i={qs['i'][0]}"
        # Spotify: Bỏ tiền tố ngôn ngữ (/intl-xx/ -> /), bỏ tracking ?si=
        elif "spotify.com" in host:
            path = re.sub(r"^/intl-[a-z0-9-]+/", "/", path, flags=re.IGNORECASE)
                
        return f"{host}{path}{query}"
    except Exception:
        return url.strip().lower()

def _check_override(line: str) -> bool:
    """Kiểm tra xem dòng chứa URL có từ khóa ghi đè hay không."""
    line_lower = line.lower()
    return any(kw in line_lower for kw in _OVERRIDE_KEYWORDS)


def _process_urls(dump_text: str, urls_to_scrape: list[str] | None = None, visual_urls: set[str] | None = None) -> str:
    urls = _URL_PATTERN.findall(dump_text)
    if not urls:
        return ""
    fetched = []
    # Lọc các URL nếu được yêu cầu
    target_urls = [u for u in urls if urls_to_scrape is None or u in urls_to_scrape]
    for url in target_urls[:5]:
        is_visual = visual_urls is not None and url in visual_urls
        text = fetch_url(url, visual=is_visual)
        if text:
            fetched.append(f"[{url}]\n{text}")
    return "\n\n".join(fetched)


# --- Noise patterns for link filtering ---
_NOISE_LINK_PATTERNS = [
    r"intent/tweet", r"intent/compose", r"intent/follow",  # Social share intents
    r"bsky\.app/intent", r"linkedin\.com/share",           # More social share
    r"\.(png|jpg|jpeg|gif|webp|svg|ico|css|js|woff|pdf)$",  # Assets
    r"^mailto:", r"^tel:", r"javascript:",                   # Non-HTTP
    r"#",                                                    # Fragment-only anchors
]
_NOISE_LINK_RE = re.compile("|".join(_NOISE_LINK_PATTERNS), re.IGNORECASE)

# Content domains worth reading (articles, docs, blogs, repos with READMEs)
_CONTENT_DOMAIN_PATTERNS = re.compile(
    r"(github\.com/[^/]+/[^/]+$"             # GitHub repo root only (not file paths)
    r"|youtube\.com/watch|youtu\.be/"         # YouTube videos
    r"|podcasts\.apple\.com|open\.spotify\.com" # Podcast platforms
    r"|substack\.com|medium\.com"             # Blog platforms
    r"|dev\.to|hashnode|hbl\.io"              # Dev blogs
    r"|npmjs\.com|pypi\.org"                  # Package registries
    r"|docs\.|documentation\."
    r")",
    re.IGNORECASE
)


def _fetch_html_soup(original_url: str):
    """Fetch HTML page and return parsed BeautifulSoup object."""
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(original_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        _logger.warning(f"[SourceEnrich] Failed to fetch HTML for link extraction: {e}")
        return None


def _is_valid_related_link(href: str, original_url: str, source_host: str, seen: set[str]) -> bool:
    """Validate and filter candidate out-links against noise and allowed domains."""
    from urllib.parse import urlparse

    if _NOISE_LINK_RE.search(href) or not href.startswith("http"):
        return False

    norm = href.rstrip("/")
    if norm in seen or norm == original_url.rstrip("/"):
        return False

    parsed = urlparse(href)
    link_host = parsed.hostname or ""
    path = parsed.path
    if "github.com" in link_host:
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) >= 3:
            return False

    same_domain = bool(source_host and link_host.endswith(source_host.lstrip("www.")))
    return same_domain or bool(_CONTENT_DOMAIN_PATTERNS.search(href))


def _extract_related_links(original_url: str) -> list[str]:
    """Extract and filter meaningful out-links from an article page.

    Returns a deduplicated list of up to 10 clean, readable URLs
    excluding noise (social share intents, assets, fragment anchors).
    """
    from urllib.parse import urljoin, urlparse

    soup = _fetch_html_soup(original_url)
    if not soup:
        return []

    source_host = urlparse(original_url).hostname or ""
    seen: set[str] = set()
    result: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = urljoin(original_url, tag["href"].strip())
        if _is_valid_related_link(href, original_url, source_host, seen):
            seen.add(href.rstrip("/"))
            result.append(href)
            if len(result) >= 10:
                break

    _logger.info(f"[SourceEnrich] Extracted {len(result)} related link(s) from {original_url}")
    return result
