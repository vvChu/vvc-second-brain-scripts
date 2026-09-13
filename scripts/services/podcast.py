"""VvC Second Brain — Podcast Ingestion Service.

Handles recognition, metadata extraction (JSON-LD), audio stream resolution,
transcoding, and Whisper transcription for podcast episodes.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.media import transcode_audio_to_mp3

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

_logger = logging.getLogger("vvc.podcast")

# Supported podcast hosts
_PODCAST_HOSTS = (
    "podcasts.apple.com",
    "open.spotify.com",
    "spotify.com",
    "simplecast.com",
    "transistor.fm",
    "podbean.com",
    "libsyn.com",
    "overcast.fm",
    "pocketcasts.com",
    "castbox.fm",
    "buzzsprout.com",
    "anchor.fm",
)

_AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".ogg")


def is_podcast_url(url: str) -> bool:
    """Check if a URL points to a podcast episode, show, or direct audio stream.

    Args:
        url: URL string to check.

    Returns:
        True if URL is recognized as a podcast or direct audio source.
    """
    if not url or not isinstance(url, str):
        return False

    url_clean = url.strip().rstrip('.,;:"\'')
    try:
        parsed = urlparse(url_clean)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()

        if any(host == d or host.endswith("." + d) for d in _PODCAST_HOSTS):
            return True

        if any(path.endswith(ext) for ext in _AUDIO_EXTENSIONS):
            return True

        return False
    except Exception:
        return False


def _clean_podcast_title(title: str) -> str:
    """Strip common platform suffixes from podcast titles."""
    if not title:
        return ""
    cleaned = html_lib.unescape(title).strip()
    suffixes = [
        " - Apple Podcasts",
        " — Apple Podcasts",
        " | Podcast on Spotify",
        " - Spotify",
        " — Spotify",
    ]
    for suf in suffixes:
        if cleaned.endswith(suf):
            cleaned = cleaned[:-len(suf)].strip()
    return cleaned


def _extract_podcast_json_ld(html_content: str) -> dict[str, str]:
    """Extract clean structured podcast metadata from HTML JSON-LD tags.

    Prioritizes episode-level metadata over show/series metadata, handles
    graph hierarchies, unescapes entities, and falls back to full HTML show
    notes when platform JSON-LD summaries are truncated.

    Args:
        html_content: Raw HTML text of the podcast web page.

    Returns:
        Dictionary containing title, show, description, date_published, duration.
    """
    metadata: dict[str, str] = {
        "title": "",
        "show": "",
        "description": "",
        "date_published": "",
        "duration": "",
    }

    if not html_content:
        return metadata

    soup = None
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            _logger.debug(f"Failed to parse HTML with BeautifulSoup: {e}")

    # 1. Search for application/ld+json blocks
    json_ld_blocks: list[str] = []
    if soup is not None:
        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                json_ld_blocks.append(script.string.strip())
    else:
        # Fallback regex search for script tags
        pattern = re.compile(
            r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>',
            re.DOTALL | re.IGNORECASE,
        )
        json_ld_blocks = [m.group(1).strip() for m in pattern.finditer(html_content)]

    target_episode_types = {
        "podcastepisode",
        "episode",
        "musicrecording",
        "audioobject",
        "radioepisode",
    }
    target_series_types = {
        "podcastseries",
        "radioseries",
        "series",
    }

    episode_item: dict | None = None
    series_item: dict | None = None

    for block in json_ld_blocks:
        try:
            data = json.loads(block)
        except Exception:
            continue

        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                items = data["@graph"]
            else:
                items = [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            raw_type = item.get("@type", "")
            types = [t.lower() for t in raw_type] if isinstance(raw_type, list) else [str(raw_type).lower()]

            if any(t in target_episode_types for t in types):
                if episode_item is None:
                    episode_item = item
            elif any(t in target_series_types for t in types):
                if series_item is None:
                    series_item = item
            elif "partOfSeries" in item or "partOfPodcast" in item:
                if episode_item is None:
                    episode_item = item
            elif ("name" in item and "description" in item) and episode_item is None and series_item is None:
                series_item = item

    # Extract episode metadata with priority
    if episode_item is not None:
        name = episode_item.get("name") or ""
        if name:
            metadata["title"] = _clean_podcast_title(str(name))

        desc = episode_item.get("description") or ""
        if desc:
            clean_desc = html_lib.unescape(str(desc)).strip()
            clean_desc = re.sub(r"<[^>]+>", " ", clean_desc)
            clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
            metadata["description"] = clean_desc

        part_of = episode_item.get("partOfSeries") or episode_item.get("partOfPodcast") or episode_item.get("show")
        if part_of:
            if isinstance(part_of, dict):
                metadata["show"] = _clean_podcast_title(str(part_of.get("name", "")))
            elif isinstance(part_of, str):
                metadata["show"] = _clean_podcast_title(part_of)

        date_pub = episode_item.get("datePublished") or episode_item.get("uploadDate") or ""
        if date_pub:
            metadata["date_published"] = str(date_pub).strip()

        dur = episode_item.get("duration") or ""
        if dur:
            metadata["duration"] = str(dur).strip()

    # Extract or fallback to series metadata
    if series_item is not None:
        series_name = _clean_podcast_title(str(series_item.get("name") or ""))
        series_desc = html_lib.unescape(str(series_item.get("description") or "")).strip()
        series_desc = re.sub(r"<[^>]+>", " ", series_desc)
        series_desc = re.sub(r"\s+", " ", series_desc).strip()

        if not metadata["show"] and series_name:
            metadata["show"] = series_name
        if not metadata["title"] and series_name:
            # Show page URL without individual episode
            metadata["title"] = series_name
        if not metadata["description"] and series_desc:
            metadata["description"] = series_desc

    # 2. Rich HTML check: replace truncated JSON-LD summary with full Show Notes if present
    if soup is not None:
        wrapper = (
            soup.find("div", class_=re.compile(r"paragraph-wrapper|shelf-content|episode-description|show-description"))
            or soup.find("section", class_=re.compile(r"section--paragraph|episode-details"))
        )
        if wrapper:
            clean_wrapper_text = html_lib.unescape(wrapper.get_text(separator="\n", strip=True))
            clean_wrapper_text = re.sub(r"\n{3,}", "\n\n", clean_wrapper_text).strip()
            # Use richer HTML body if significantly longer than the platform preview
            if len(clean_wrapper_text) > len(metadata["description"]) + 50:
                metadata["description"] = clean_wrapper_text

    # 3. Fallbacks from OpenGraph / meta tags if JSON-LD was incomplete
    if soup is not None:
        if not metadata["title"]:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                metadata["title"] = _clean_podcast_title(og_title["content"].strip())
            elif soup.title and soup.title.string:
                metadata["title"] = _clean_podcast_title(soup.title.string.strip())

        if not metadata["description"]:
            og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
            if og_desc and og_desc.get("content"):
                metadata["description"] = html_lib.unescape(og_desc["content"]).strip()

        if not metadata["show"]:
            site_name = soup.find("meta", property="og:site_name")
            if site_name and site_name.get("content"):
                s_val = site_name["content"].strip()
                if s_val.lower() not in ("apple podcasts", "spotify"):
                    metadata["show"] = s_val

    metadata["title"] = html_lib.unescape(metadata["title"]).strip()
    metadata["show"] = html_lib.unescape(metadata["show"]).strip()
    return metadata


def _get_audio_stream_url(url: str) -> str | None:
    """Extract direct audio stream URL using yt-dlp.

    Skips Spotify (DRM-protected) and Apple Podcasts Show pages (missing ?i=).
    Returns direct audio URLs immediately without overhead.

    Args:
        url: Podcast page URL or direct audio link.

    Returns:
        Direct stream URL string or None.
    """
    clean_url = url.strip()
    parsed = urlparse(clean_url)
    host = (parsed.hostname or "").lower()
    path_lower = parsed.path.lower()

    # Fast return for direct audio URLs
    if any(path_lower.endswith(ext) for ext in _AUDIO_EXTENSIONS):
        return clean_url

    # Fast skip for Spotify (DRM protected)
    if "spotify.com" in host:
        _logger.info(f"Skipping yt-dlp audio download for Spotify DRM URL: {url}")
        return None

    # Fast skip for Apple Podcasts Show pages (missing episode query ?i= or &i=)
    if "podcasts.apple.com" in host:
        qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        if "i" not in qs:
            _logger.info(f"Skipping yt-dlp audio download for Apple Podcasts Show page (no ?i=): {url}")
            return None

    try:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "skip_download": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            if info:
                stream_url = info.get("url")
                if stream_url:
                    return str(stream_url)
    except Exception as e:
        _logger.warning(f"Failed to extract audio stream via yt-dlp for {url}: {e}")

    return None


def _transcode_stream_to_mp3(stream_url: str) -> Path | None:
    """Transcode an audio stream directly to 16kHz mono 32kbps MP3 via ffmpeg.

    Args:
        stream_url: Direct audio stream URL.

    Returns:
        Path to the generated temporary MP3 file, or None if transcoding failed.
    """
    if not stream_url:
        return None

    tmp_path = Path(tempfile.gettempdir()) / f"podcast_{uuid.uuid4().hex[:8]}.mp3"
    return transcode_audio_to_mp3(stream_url, output_path=tmp_path)


def fetch_podcast(url: str, transcribe: bool = True) -> str:
    """Fetch and parse a podcast episode from supported platforms or direct audio URLs.

    Orchestrates:
    1. HTTP fetch of podcast webpage with correct UTF-8 decoding.
    2. JSON-LD metadata extraction (Show Notes, Episode Title, Show Title).
    3. Audio resolution via yt-dlp (skipping DRM/Show pages).
    4. On-the-fly MP3 transcoding (16kHz mono 32kbps).
    5. Speech-to-text via AI Gateway Whisper (`audio-primary`).
    6. Graceful fallback to Show Notes if audio is unavailable.

    Args:
        url: Podcast page URL or direct audio link.

    Returns:
        Formatted markdown containing episode metadata and transcript/show notes.
    """
    url_clean = url.strip().rstrip('.,;:"\'')
    _logger.info(f"Fetching podcast: {url_clean}")

    parsed_url = urlparse(url_clean)
    path_lower = parsed_url.path.lower()
    is_direct_audio = any(path_lower.endswith(ext) for ext in _AUDIO_EXTENSIONS)

    if is_direct_audio:
        title = Path(parsed_url.path).stem.replace("_", " ").replace("-", " ").title() or "Audio Track"
        show = ""
        description = ""
        date_pub = ""
        duration = ""
        html_content = ""
        stream_url = url_clean
    else:
        if requests is None:
            _logger.warning("requests library is not available")
            return ""

        html_content = ""
        try:
            resp = requests.get(
                url_clean,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            resp.encoding = resp.apparent_encoding or "utf-8"
            resp.raise_for_status()
            html_content = resp.text
        except Exception as e:
            _logger.warning(f"Failed to fetch podcast HTML for {url_clean}: {e}")

        meta = _extract_podcast_json_ld(html_content)
        title = meta.get("title") or "Podcast Episode"
        show = meta.get("show") or ""
        description = meta.get("description") or ""
        date_pub = meta.get("date_published") or ""
        duration = meta.get("duration") or ""
        stream_url = _get_audio_stream_url(url_clean)

    # 3. Audio Stream Resolution & Whisper Transcription
    transcript_text = ""

    if transcribe and stream_url:
        _logger.info(f"Resolved audio stream for {url_clean}, transcoding to 16kHz MP3...")
        mp3_path = _transcode_stream_to_mp3(stream_url)
        if mp3_path:
            try:
                from core.llm import call_audio
                _logger.info("Transcribing podcast audio with Whisper (Server Spark)...")
                transcript_text = call_audio(mp3_path, model="audio-primary", language=None)
            except Exception as e:
                _logger.warning(f"Whisper transcription failed for {url_clean}: {e}")
            finally:
                if mp3_path.exists():
                    try:
                        mp3_path.unlink()
                    except Exception:
                        pass

    # 4. Assemble output document
    parts: list[str] = [f"# {title}"]

    meta_lines: list[str] = []
    if show:
        meta_lines.append(f"**Show:** {show}")
    if date_pub:
        meta_lines.append(f"**Date:** {date_pub}")
    if duration:
        meta_lines.append(f"**Duration:** {duration}")

    if meta_lines:
        parts.append("\n".join(meta_lines))

    if description:
        parts.append(f"## Show Notes\n\n{description}")

    if transcript_text:
        parts.append(f"## 🎙️ Lời thoại âm thanh (Transcript)\n\n{transcript_text}")
    elif not description:
        # Fallback if both description and transcript are missing: try basic text extract
        fallback_text = ""
        if BeautifulSoup is not None and html_content:
            soup = BeautifulSoup(html_content, "html.parser")
            fallback_text = soup.get_text(separator="\n", strip=True)
        if fallback_text:
            parts.append(f"## Show Notes\n\n{fallback_text[:3000]}")

    return "\n\n".join(parts)
