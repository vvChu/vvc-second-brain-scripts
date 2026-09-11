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

from services.url_fetcher import fetch_url_content, _is_garbage_fetch


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
    article_title = _get_youtube_title(url) if is_youtube else None

    # Fetch content via centralized url_fetcher (handles YouTube, Podcasts, Articles, and JIT images)
    article_text = fetch_url_content(url)

    if not article_text:
        _logger.error(f"Failed to extract content from: {url}")
        return None

    # Check for garbage
    if _is_garbage_fetch(article_text) or len(article_text.strip()) < 100:
        _logger.error("Garbage content detected")
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


def _get_youtube_title(url: str) -> str | None:
    """Extract YouTube video title via oEmbed."""
    try:
        import requests
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        resp = requests.get(oembed_url, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("title")
    except Exception as e:
        _logger.debug(f"Could not fetch YouTube title: {e}")
    return None


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
