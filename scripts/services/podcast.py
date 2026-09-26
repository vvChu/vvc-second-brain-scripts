"""VvC Second Brain — Podcast Ingestion Service.

Handles recognition, metadata extraction (JSON-LD), audio stream resolution,
transcoding, and Whisper transcription for podcast episodes.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
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

_PODCAST_HOSTS = (
    "podcasts.apple.com", "open.spotify.com", "spotify.com",
    "simplecast.com", "transistor.fm", "podbean.com", "libsyn.com",
    "overcast.fm", "pocketcasts.com", "castbox.fm", "buzzsprout.com", "anchor.fm",
)
_AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".ogg")
_TARGET_EPISODE_TYPES = {"podcastepisode", "episode", "musicrecording", "audioobject", "radioepisode"}
_TARGET_SERIES_TYPES = {"podcastseries", "radioseries", "series"}


def is_podcast_url(url: str) -> bool:
    """Check if a URL points to a podcast episode, show, or direct audio stream."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip().rstrip('.,;:"\''))
        host, path = (parsed.hostname or "").lower(), parsed.path.lower()
        if any(host == d or host.endswith("." + d) for d in _PODCAST_HOSTS):
            return True
        return any(path.endswith(ext) for ext in _AUDIO_EXTENSIONS)
    except Exception:
        return False


def _clean_podcast_title(title: str) -> str:
    """Strip common platform suffixes from podcast titles."""
    if not title:
        return ""
    cleaned = html_lib.unescape(title).strip()
    for suf in (" - Apple Podcasts", " — Apple Podcasts", " | Podcast on Spotify", " - Spotify", " — Spotify"):
        if cleaned.endswith(suf):
            cleaned = cleaned[:-len(suf)].strip()
    return cleaned


def _find_json_ld_blocks(soup: Any, html_content: str) -> list[str]:
    """Find application/ld+json script tag contents."""
    if soup is not None:
        return [s.string.strip() for s in soup.find_all("script", type="application/ld+json") if s.string]
    pat = re.compile(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', re.DOTALL | re.I)
    return [m.group(1).strip() for m in pat.finditer(html_content)]


def _categorize_json_ld_items(blocks: list[str]) -> tuple[dict | None, dict | None]:
    """Parse JSON-LD blocks and extract best candidate episode and series items."""
    ep_item, ser_item = None, None
    for block in blocks:
        try: data = json.loads(block)
        except Exception: continue
        items = data if isinstance(data, list) else (data["@graph"] if isinstance(data, dict) and isinstance(data.get("@graph"), list) else [data])
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_type = item.get("@type", "")
            types = [t.lower() for t in raw_type] if isinstance(raw_type, list) else [str(raw_type).lower()]
            if any(t in _TARGET_EPISODE_TYPES for t in types):
                if ep_item is None: ep_item = item
            elif any(t in _TARGET_SERIES_TYPES for t in types):
                if ser_item is None: ser_item = item
            elif "partOfSeries" in item or "partOfPodcast" in item:
                if ep_item is None: ep_item = item
            elif ("name" in item and "description" in item) and ep_item is None and ser_item is None:
                ser_item = item
    return ep_item, ser_item


def _populate_episode_metadata(metadata: dict[str, str], ep: dict) -> None:
    """Populate metadata dictionary from episode JSON-LD item."""
    if ep.get("name"):
        metadata["title"] = _clean_podcast_title(str(ep["name"]))
    if ep.get("description"):
        clean_desc = re.sub(r"<[^>]+>", " ", html_lib.unescape(str(ep["description"])).strip())
        metadata["description"] = re.sub(r"\s+", " ", clean_desc).strip()
    part_of = ep.get("partOfSeries") or ep.get("partOfPodcast") or ep.get("show")
    if part_of:
        metadata["show"] = _clean_podcast_title(str(part_of.get("name", "") if isinstance(part_of, dict) else part_of))
    date_pub = ep.get("datePublished") or ep.get("uploadDate")
    if date_pub:
        metadata["date_published"] = str(date_pub).strip()
    dur = ep.get("duration")
    if dur:
        metadata["duration"] = str(dur).strip()


def _populate_series_fallback(metadata: dict[str, str], ser: dict) -> None:
    """Fallback missing show/title/description to series-level metadata."""
    name = _clean_podcast_title(str(ser.get("name") or ""))
    desc = re.sub(r"<[^>]+>", " ", html_lib.unescape(str(ser.get("description") or "")).strip())
    desc = re.sub(r"\s+", " ", desc).strip()
    if not metadata["show"] and name:
        metadata["show"] = name
    if not metadata["title"] and name:
        metadata["title"] = name
    if not metadata["description"] and desc:
        metadata["description"] = desc


def _apply_html_meta_fallbacks(metadata: dict[str, str], soup: Any) -> None:
    """Apply rich show notes wrapper and OpenGraph fallback tags from HTML."""
    wrapper = soup.find("div", class_=re.compile(r"paragraph-wrapper|shelf-content|episode-description|show-description")) or soup.find("section", class_=re.compile(r"section--paragraph|episode-details"))
    if wrapper:
        rich_text = re.sub(r"\n{3,}", "\n\n", html_lib.unescape(wrapper.get_text(separator="\n", strip=True))).strip()
        if len(rich_text) > len(metadata["description"]) + 50:
            metadata["description"] = rich_text

    if not metadata["title"]:
        og_t = soup.find("meta", property="og:title")
        if og_t and og_t.get("content"):
            metadata["title"] = _clean_podcast_title(og_t["content"].strip())
        elif soup.title and soup.title.string:
            metadata["title"] = _clean_podcast_title(soup.title.string.strip())

    if not metadata["description"]:
        og_d = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_d and og_d.get("content"):
            metadata["description"] = html_lib.unescape(og_d["content"]).strip()

    if not metadata["show"]:
        sn = soup.find("meta", property="og:site_name")
        if sn and sn.get("content") and sn["content"].strip().lower() not in ("apple podcasts", "spotify"):
            metadata["show"] = sn["content"].strip()


def _extract_podcast_json_ld(html_content: str) -> dict[str, str]:
    """Extract clean structured podcast metadata from HTML JSON-LD tags."""
    metadata = {"title": "", "show": "", "description": "", "date_published": "", "duration": ""}
    if not html_content:
        return metadata

    soup = None
    if BeautifulSoup is not None:
        try: soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e: _logger.debug(f"Failed to parse HTML with BeautifulSoup: {e}")

    blocks = _find_json_ld_blocks(soup, html_content)
    ep_item, ser_item = _categorize_json_ld_items(blocks)
    if ep_item is not None:
        _populate_episode_metadata(metadata, ep_item)
    if ser_item is not None:
        _populate_series_fallback(metadata, ser_item)
    if soup is not None:
        _apply_html_meta_fallbacks(metadata, soup)

    metadata["title"] = html_lib.unescape(metadata["title"]).strip()
    metadata["show"] = html_lib.unescape(metadata["show"]).strip()
    return metadata


def _can_extract_audio_stream(url: str, host: str, path_lower: str, query: str) -> tuple[bool, str | None]:
    """Check fast return or fast skip conditions for audio extraction."""
    if any(path_lower.endswith(ext) for ext in _AUDIO_EXTENSIONS):
        return False, url
    if "spotify.com" in host:
        _logger.info(f"Skipping yt-dlp audio download for Spotify DRM URL: {url}")
        return False, None
    if "podcasts.apple.com" in host:
        if "i" not in {k.lower(): v for k, v in parse_qs(query).items()}:
            _logger.info(f"Skipping yt-dlp audio download for Apple Podcasts Show page (no ?i=): {url}")
            return False, None
    return True, None


def _get_audio_stream_url(url: str) -> str | None:
    """Extract direct audio stream URL using yt-dlp."""
    clean_url = url.strip()
    parsed = urlparse(clean_url)
    should_extract, direct = _can_extract_audio_stream(
        clean_url, (parsed.hostname or "").lower(), parsed.path.lower(), parsed.query
    )
    if not should_extract:
        return direct

    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "no_warnings": True, "format": "bestaudio/best", "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            if info and info.get("url"):
                return str(info["url"])
    except Exception as e:
        _logger.warning(f"Failed to extract audio stream via yt-dlp for {url}: {e}")
    return None


def _transcode_stream_to_mp3(stream_url: str) -> Path | None:
    """Transcode an audio stream directly to 16kHz mono 32kbps MP3 via ffmpeg."""
    if not stream_url:
        return None
    tmp_path = Path(tempfile.gettempdir()) / f"podcast_{uuid.uuid4().hex[:8]}.mp3"
    return transcode_audio_to_mp3(stream_url, output_path=tmp_path)


def _resolve_podcast_metadata(url_clean: str, is_direct: bool) -> tuple[dict[str, str], str | None, str]:
    """Resolve metadata, stream URL, and raw HTML for direct or web podcast."""
    if is_direct:
        stem = Path(urlparse(url_clean).path).stem.replace("_", " ").replace("-", " ").title()
        return {"title": stem or "Audio Track", "show": "", "description": "", "date_published": "", "duration": ""}, url_clean, ""

    if requests is None:
        _logger.warning("requests library is not available")
        return {"title": "Podcast Episode", "show": "", "description": "", "date_published": "", "duration": ""}, None, ""

    html_content = ""
    try:
        resp = requests.get(url_clean, timeout=15, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        resp.encoding = resp.apparent_encoding or "utf-8"
        resp.raise_for_status()
        html_content = resp.text
    except Exception as e:
        _logger.warning(f"Failed to fetch podcast HTML for {url_clean}: {e}")

    meta = _extract_podcast_json_ld(html_content)
    if not meta.get("title"):
        meta["title"] = "Podcast Episode"
    return meta, _get_audio_stream_url(url_clean), html_content


def _transcribe_audio_stream(stream_url: str, url_clean: str) -> str:
    """Transcode and transcribe podcast audio with Whisper."""
    _logger.info(f"Resolved audio stream for {url_clean}, transcoding to 16kHz MP3...")
    mp3_path = _transcode_stream_to_mp3(stream_url)
    if not mp3_path:
        return ""
    try:
        from core.llm import call_audio
        _logger.info("Transcribing podcast audio with Whisper (Server Spark)...")
        return call_audio(mp3_path, model="audio-primary", language=None)
    except Exception as e:
        _logger.warning(f"Whisper transcription failed for {url_clean}: {e}")
        return ""
    finally:
        if mp3_path.exists():
            try: mp3_path.unlink()
            except Exception: pass


def _format_podcast_markdown(meta: dict[str, str], transcript: str, html_content: str) -> str:
    """Assemble final markdown document for podcast."""
    parts = [f"# {meta.get('title', 'Podcast Episode')}"]
    meta_lines = []
    if meta.get("show"): meta_lines.append(f"**Show:** {meta['show']}")
    if meta.get("date_published"): meta_lines.append(f"**Date:** {meta['date_published']}")
    if meta.get("duration"): meta_lines.append(f"**Duration:** {meta['duration']}")
    if meta_lines:
        parts.append("\n".join(meta_lines))
    if meta.get("description"):
        parts.append(f"## Show Notes\n\n{meta['description']}")

    if transcript:
        parts.append(f"## 🎙️ Lời thoại âm thanh (Transcript)\n\n{transcript}")
    elif not meta.get("description") and BeautifulSoup is not None and html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        fallback_text = soup.get_text(separator="\n", strip=True)
        if fallback_text:
            parts.append(f"## Show Notes\n\n{fallback_text[:3000]}")
    return "\n\n".join(parts)


def fetch_podcast(url: str, transcribe: bool = True) -> str:
    """Fetch and parse a podcast episode from supported platforms or direct audio URLs."""
    url_clean = url.strip().rstrip('.,;:"\'')
    _logger.info(f"Fetching podcast: {url_clean}")

    is_direct = any(urlparse(url_clean).path.lower().endswith(ext) for ext in _AUDIO_EXTENSIONS)
    meta, stream_url, html_content = _resolve_podcast_metadata(url_clean, is_direct)

    transcript = ""
    if transcribe and stream_url:
        transcript = _transcribe_audio_stream(stream_url, url_clean)

    return _format_podcast_markdown(meta, transcript, html_content)
