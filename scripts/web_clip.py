"""VvC Second Brain — Web Clipper (v7.0).

CLI tool: extracts clean article text from URLs and saves to 05-Fleeting/.

Usage:
    python web_clip.py "https://example.com/article"
    python web_clip.py "https://url1" "https://url2"
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import date
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg

logging.basicConfig(level=logging.INFO, format="%(message)s")
_logger = logging.getLogger("vvc.clip")

# Garbage detection patterns
_GARBAGE_PATTERNS = [
    r"javascript is (?:disabled|not available)",
    r"enable javascript",
    r"something went wrong",
    r"access denied.*cloudflare",
    r"just a moment.*checking",
    r"please enable cookies",
]


def clip_url(url: str) -> Path | None:
    """Fetch article from URL and save as Fleeting markdown.

    Args:
        url: Article URL.

    Returns:
        Path to saved markdown file, or None on failure.
    """
    _logger.info(f"Clipping: {url}")

    # Identify if YouTube
    is_youtube = "youtube.com/" in url or "youtu.be/" in url

    # Fetch content
    if is_youtube:
        article_text, article_title = _fetch_youtube(url)
    else:
        article_text, article_title = _fetch_article(url), None

    if not article_text:
        _logger.error(f"Failed to extract content from: {url}")
        return None

    # Check for garbage
    text_lower = article_text.lower()
    garbage_hits = sum(1 for p in _GARBAGE_PATTERNS if re.search(p, text_lower))
    if garbage_hits >= 2 or len(article_text.strip()) < 100:
        _logger.error(f"Garbage content detected (hits={garbage_hits})")
        return None

    # Generate filename
    today = date.today().isoformat()
    if article_title:
        # Keep ascii and alphanumerics for slug
        slug = re.sub(r"[^a-zA-Z0-9_]", "_", article_title.lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        if len(slug) > 60:
            slug = slug[:60].rsplit("_", 1)[0]
        title_display = article_title
    else:
        slug = _url_to_slug(url)
        title_display = slug.replace('_', ' ').title()

    filename = f"{today}_{slug}.md"

    # Build markdown content
    content = (
        f"---\n"
        f"source_url: \"{url}\"\n"
        f"date_clipped: {today}\n"
        f"---\n\n"
        f"# {title_display}\n\n"
        f"> Clipped from: [{url}]({url})\n\n"
        f"{article_text}\n"
    )

    # Save to Fleeting
    output = cfg.fleeting_dir / filename
    try:
        output.write_text(content, encoding="utf-8")
        _logger.info(f"Saved: {output.name} ({len(article_text)} chars)")
        return output
    except OSError as e:
        _logger.error(f"Save failed: {e}")
        return None


def _fetch_article(url: str) -> str:
    """Fetch and extract clean article text."""
    # Try trafilatura first (best quality)
    try:
        import trafilatura
        import requests

        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        text = trafilatura.extract(
            resp.text,
            include_comments=False,
            include_tables=True,
            output_format="txt",
        )
        if text and len(text) > 100:
            return text
    except ImportError:
        _logger.debug("trafilatura not available, using BeautifulSoup")
    except Exception as e:
        _logger.warning(f"trafilatura failed: {e}")

    # Fallback: BeautifulSoup
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style/nav
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        # Basic cleanup
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n\n".join(lines)
    except Exception as e:
        _logger.error(f"Fetch failed: {e}")
        return ""


def _fetch_youtube(url: str) -> tuple[str, str | None]:
    """Extract YouTube transcript and title.
    
    Returns:
        (transcript_text, title)
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        import requests
    except ImportError:
        _logger.error("youtube-transcript-api is not installed.")
        return "", None

    # Extract video ID
    video_id = None
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0]
    elif "v=" in url:
        video_id = url.split("v=")[1].split("&")[0]

    if not video_id:
        _logger.error("Could not extract YouTube video ID")
        return "", None

    # Get title via oEmbed
    title = None
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        resp = requests.get(oembed_url, timeout=10)
        if resp.status_code == 200:
            title = resp.json().get("title")
    except Exception as e:
        _logger.warning(f"Could not fetch YouTube title: {e}")

    # Fetch transcript
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        transcript_obj = transcript_list.find_transcript(['vi', 'en'])
        transcript = transcript_obj.fetch()
        
        # Format transcript into paragraphs (e.g. group every 5-10 sentences, or just join with spaces)
        # We will just join with spaces and let the LLM handle grouping later
        text_chunks = [entry.text.replace("\n", " ") for entry in transcript]
        text = " ".join(text_chunks)
        
        # Make it a bit more readable by adding double newlines occasionally 
        # (naively split into chunks of ~150 words)
        words = text.split()
        chunks = [" ".join(words[i:i+150]) for i in range(0, len(words), 150)]
        clean_text = "\n\n".join(chunks)

        return clean_text, title
    except Exception as e:
        _logger.error(f"YouTube transcript extraction failed: {e}")
        return "", title


def _url_to_slug(url: str) -> str:
    """Convert URL to a filename-safe slug."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_")

    if not path:
        path = parsed.netloc.replace(".", "_")

    # Clean
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", path)
    slug = re.sub(r"_+", "_", slug).strip("_")

    # Truncate
    if len(slug) > 60:
        slug = slug[:60].rsplit("_", 1)[0]

    return slug or "web_clip"


# --- CLI ---

if __name__ == "__main__":
    import sys
    # Reconfigure stdout for utf-8 if possible
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    if len(sys.argv) < 2:
        print("Usage: python web_clip.py <url> [url2] ...")
        sys.exit(1)

    for url in sys.argv[1:]:
        result = clip_url(url)
        if result:
            print(f"[SUCCESS] {result.name}")
        else:
            print(f"[ERROR]   {url}")
