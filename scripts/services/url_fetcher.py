"""VvC Second Brain — URL Fetcher.

Fetches content from URLs using trafilatura and BeautifulSoup.
"""

import logging
import re
import concurrent.futures

try:
    import requests
except ImportError:
    requests = None

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from services.youtube_transcript import fetch_youtube_transcript

_logger = logging.getLogger("vvc.url_fetcher")

# Module-level ThreadPoolExecutor for trafilatura (reused across URL fetches)
_trafilatura_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_trafilatura_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Lazily initialise and return the shared trafilatura thread pool."""
    global _trafilatura_executor
    if _trafilatura_executor is None or _trafilatura_executor._shutdown:
        _trafilatura_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="trafilatura"
        )
    return _trafilatura_executor

# --- Garbage URL Detection ---

_GARBAGE_PATTERNS = [
    r"javascript is (?:disabled|not available)",
    r"enable javascript",
    r"something went wrong.*(?:try again|let.s give it another shot)",
    r"we.ve detected that javascript",
    r"noscript",
    r"this browser is no longer supported",
    r"please enable cookies",
    r"access denied.*cloudflare",
    r"just a moment.*cloudflare",
    r"checking your browser",
]


def _is_garbage_fetch(text: str) -> bool:
    """Check if fetched URL content is garbage (JS required, Cloudflare, etc.)."""
    if len(text.strip()) < 100:
        return True
    text_lower = text.lower()
    match_count = sum(1 for pat in _GARBAGE_PATTERNS if re.search(pat, text_lower))
    return match_count >= 2


def fetch_url_title(url: str) -> str:
    """Fetch the title of a web page."""
    if requests is None:
        return ""
    try:
        url = url.rstrip('.,;:"\'')
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        if BeautifulSoup is not None:
            soup = BeautifulSoup(resp.text, "html.parser")
            if soup.title and soup.title.string:
                return soup.title.string.strip()
    except Exception as e:
        _logger.warning(f"Failed to fetch URL title for {url}: {e}")
    return ""


def _extract_with_trafilatura(html: str) -> str:
    if trafilatura is not None:
        return trafilatura.extract(html) or ""
    return ""


def fetch_url(url: str) -> str:
    """Fetch and extract article text from a URL."""
    if requests is None:
        return ""
    
    url = url.rstrip('.,;:"\'')
    
    if "youtube.com" in url or "youtu.be" in url:
        yt_text = fetch_youtube_transcript(url)
        # Never fallback to HTML scraping for YouTube URLs. 
        # If transcript/audio fails, return empty string so Semantic Arbitrator rejects it.
        return yt_text[:40000] if yt_text else ""
            
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        # Try trafilatura first with a 10s timeout to prevent hanging
        text = ""
        if trafilatura is not None:
            executor = _get_trafilatura_executor()
            future = executor.submit(_extract_with_trafilatura, resp.text)
            try:
                text = future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                _logger.warning(f"Trafilatura parsing timed out: {url}")
            except Exception:
                pass

        if text and not _is_garbage_fetch(text):
            return text[:40000]

        # Fallback: basic HTML text
        if BeautifulSoup is not None:
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

        if _is_garbage_fetch(text):
            _logger.warning(f"Garbage fetch detected: {url}")
            return ""

        return text[:40000]
    except Exception as e:
        _logger.warning(f"URL fetch failed: {url}: {e}")
        return ""
