"""VvC Second Brain — Twitter / X Ingestion Service.

Handles metadata extraction, text recovery, media processing,
and automatic Whisper transcription for video posts from X (Twitter)
via fxtwitter/vxtwitter public APIs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from core.media import transcode_audio_to_mp3

try:
    import requests
except ImportError:
    requests = None

_logger = logging.getLogger("vvc.twitter")

_TWITTER_HOSTS = (
    "x.com",
    "twitter.com",
    "mobile.twitter.com",
    "fxtwitter.com",
    "vxtwitter.com",
    "fixupx.com",
)
_TWEET_ID_PATTERN = re.compile(r"(?:status(?:es)?)/(\d+)")


def is_twitter_url(url: str) -> bool:
    """Check if a URL points to an X or Twitter post."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip().rstrip('.,;:"\''))
        host = (parsed.hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in _TWITTER_HOSTS)
    except Exception:
        return False


def extract_tweet_id(url: str) -> str | None:
    """Extract numeric tweet ID from an X/Twitter URL."""
    match = _TWEET_ID_PATTERN.search(url)
    return match.group(1) if match else None


def _fetch_fxtwitter_payload(tweet_id: str) -> dict | None:
    """Fetch structured tweet JSON from fxtwitter or vxtwitter API."""
    if requests is None:
        _logger.warning("requests library is not available")
        return None

    endpoints = [
        f"https://api.fxtwitter.com/i/status/{tweet_id}",
        f"https://api.vxtwitter.com/i/status/{tweet_id}",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for ep in endpoints:
        try:
            resp = requests.get(ep, timeout=12, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if "tweet" in data:
                    return data["tweet"]
                if "text" in data or "tweetID" in data:
                    return data
        except Exception as e:
            _logger.debug(f"API endpoint {ep} failed: {e}")

    return None


def _extract_media_items(tweet_data: dict) -> tuple[list[str], list[str]]:
    """Extract photo and video URLs from fxtwitter or vxtwitter tweet dict."""
    photo_urls: list[str] = []
    video_urls: list[str] = []

    media = tweet_data.get("media")
    if isinstance(media, dict):
        for p in media.get("photos", []):
            if isinstance(p, dict) and p.get("url"):
                photo_urls.append(p["url"])
        for v in media.get("videos", []):
            if isinstance(v, dict) and v.get("url"):
                video_urls.append(v["url"])

    media_ext = tweet_data.get("media_extended")
    if isinstance(media_ext, list):
        for item in media_ext:
            if not isinstance(item, dict):
                continue
            itype, iurl = item.get("type"), item.get("url")
            if itype == "video" and iurl and iurl not in video_urls:
                video_urls.append(iurl)
            elif itype == "image" and iurl and iurl not in photo_urls:
                photo_urls.append(iurl)

    return photo_urls, video_urls


def _transcribe_twitter_video(video_url: str, tweet_id: str) -> str:
    """Download audio stream via ffmpeg and transcribe with Whisper."""
    _logger.info(f"Transcoding video audio for tweet {tweet_id}...")
    mp3_path = transcode_audio_to_mp3(video_url)
    if not mp3_path:
        return ""

    try:
        from core.llm import call_audio

        _logger.info(f"Transcribing tweet video {tweet_id} via Whisper...")
        return call_audio(mp3_path, model="audio-primary", language=None)
    except Exception as e:
        _logger.warning(f"Whisper transcription failed for tweet {tweet_id}: {e}")
        return ""
    finally:
        if mp3_path.exists():
            try:
                mp3_path.unlink()
            except OSError:
                pass


def _format_twitter_markdown(
    tweet_data: dict,
    transcript: str,
    original_url: str,
    photo_urls: list[str],
) -> str:
    """Assemble final structured markdown document for the tweet."""
    author = tweet_data.get("author") or {}
    name = author.get("name") or tweet_data.get("user_name") or "Tác giả"
    screen_name = author.get("screen_name") or tweet_data.get("user_screen_name") or "twitter"
    text = tweet_data.get("text") or ""
    date_val = tweet_data.get("created_at") or tweet_data.get("date") or ""

    parts = [
        f"# Bài đăng từ @{screen_name} ({name})",
        f"**Tác giả:** {name} (@{screen_name})\n"
        f"**Ngày đăng:** {date_val}\n"
        f"**Liên kết gốc:** {original_url}",
        f"## 📝 Nội dung bài đăng (Tweet)\n\n{text}",
    ]

    quote = tweet_data.get("quote") or tweet_data.get("qrt")
    if isinstance(quote, dict) and quote.get("text"):
        q_author = quote.get("author", {})
        q_name = q_author.get("name") or quote.get("user_name") or "Người trích dẫn"
        q_screen = q_author.get("screen_name") or quote.get("user_screen_name") or ""
        quoted_body = quote['text'].replace('\n', '\n> ')
        parts.append(f"### 💬 Trích dẫn từ @{q_screen} ({q_name})\n\n> {quoted_body}")

    if photo_urls:
        img_lines = [f"- ![]({p})" for p in photo_urls[:4]]
        parts.append("## 🖼️ Hình ảnh đính kèm\n\n" + "\n".join(img_lines))

    if transcript:
        parts.append(f"## 🎙️ Lời thoại Video (Transcript)\n\n{transcript}")

    return "\n\n".join(parts)


def fetch_twitter(url: str, transcribe: bool = True) -> str:
    """Fetch tweet text and transcribe any attached videos."""
    url_clean = url.strip().rstrip('.,;:"\'')
    tweet_id = extract_tweet_id(url_clean)
    if not tweet_id:
        _logger.warning(f"Could not extract tweet ID from {url_clean}")
        return ""

    _logger.info(f"Fetching Twitter/X post: ID {tweet_id}")
    tweet_data = _fetch_fxtwitter_payload(tweet_id)
    if not tweet_data:
        _logger.warning(f"Failed to fetch Twitter/X payload for ID {tweet_id}")
        return ""

    photo_urls, video_urls = _extract_media_items(tweet_data)

    transcript = ""
    if transcribe and video_urls:
        transcript = _transcribe_twitter_video(video_urls[0], tweet_id)

    return _format_twitter_markdown(tweet_data, transcript, url_clean, photo_urls)


def fetch_twitter_title(url: str) -> str:
    """Fetch short title for a Twitter/X post."""
    url_clean = url.strip().rstrip('.,;:"\'')
    tweet_id = extract_tweet_id(url_clean)
    if not tweet_id:
        return ""
    data = _fetch_fxtwitter_payload(tweet_id)
    if not data:
        return ""
    author = data.get("author") or {}
    name = author.get("name") or data.get("user_name") or ""
    screen_name = author.get("screen_name") or data.get("user_screen_name") or ""
    text = data.get("text") or ""
    snippet = text.replace("\n", " ")[:60].strip()
    if screen_name and snippet:
        return f"@{screen_name}: {snippet}"
    if name and snippet:
        return f"{name}: {snippet}"
    return snippet or f"Tweet {tweet_id}"
