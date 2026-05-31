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

from services.youtube_transcript import fetch_youtube_transcript, extract_video_visuals
from services.article_images import extract_article_images, format_image_metadata

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


def fetch_url(url: str, visual: bool = False) -> str:
    """Fetch and extract article text from a URL.

    For non-YouTube articles, images are automatically extracted via
    Smart Filter and appended as structured metadata so the downstream
    LLM can embed ``![[image.webp]]`` references in concept notes.

    Args:
        url: Web page URL.
        visual: For YouTube URLs, enable video frame extraction.

    Returns:
        Extracted text (with optional image metadata appended).
    """
    if requests is None:
        return ""
    
    url = url.rstrip('.,;:"\'')    
    if "youtube.com" in url or "youtu.be" in url:
        info_dict = None
        if visual:
            try:
                import yt_dlp
                _logger.info(f"Đang tải JIT metadata cho YouTube URL: {url}")
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
            except Exception as e:
                _logger.warning(f"Lỗi khi tải JIT metadata qua yt_dlp (sẽ tự động fallback): {e}")
        
        yt_text = fetch_youtube_transcript(url, info_dict=info_dict)
        if visual and yt_text:
            visual_text = extract_video_visuals(url, transcript_text=yt_text, info_dict=info_dict)
            if visual_text:
                yt_text = f"{yt_text}\n\n## 🎞️ Nội dung trực quan từ video (Visual Slide Summary)\n\n{visual_text}"
        # Never fallback to HTML scraping for YouTube URLs. 
        # If transcript/audio fails, return empty string so Semantic Arbitrator rejects it.
        return yt_text or ""
            
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        raw_html = resp.text

        # Try trafilatura first with a 10s timeout to prevent hanging
        text = ""
        if trafilatura is not None:
            executor = _get_trafilatura_executor()
            future = executor.submit(_extract_with_trafilatura, raw_html)
            try:
                text = future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                _logger.warning(f"Trafilatura parsing timed out: {url}")
            except Exception:
                pass

        if not text or _is_garbage_fetch(text):
            # Fallback: basic HTML text
            if BeautifulSoup is not None:
                soup = BeautifulSoup(raw_html, "html.parser")
                text = soup.get_text(separator="\n", strip=True)

        if _is_garbage_fetch(text):
            _logger.warning(f"Garbage fetch detected: {url}")
            return ""

        # --- Article Image Extraction (auto, zero-touch) ---
        try:
            images = extract_article_images(raw_html, url)
            if images:
                image_metadata = format_image_metadata(images)
                text = f"{text}{image_metadata}"
                _logger.info(f"Appended {len(images)} image metadata entries for {url}")
        except Exception as img_exc:
            _logger.warning(f"Article image extraction failed (non-fatal): {img_exc}")

        return text
    except Exception as e:
        _logger.warning(f"URL fetch failed: {url}: {e}")
        return ""
