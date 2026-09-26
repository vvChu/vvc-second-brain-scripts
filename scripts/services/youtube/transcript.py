"""VvC Second Brain — YouTube Transcript Fetcher.

Extracts transcripts from YouTube via yt-dlp mobile client emulation,
with fallbacks to youtube_transcript_api and audio download + Whisper.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm import call_audio
from services.youtube.transcript_cleaner import (
    _IGNORED_SUB_KEYS,
    _extract_video_id,
    _find_lang,
    _find_native_asr,
    _find_target_sub_url,
    _group_timed_segments,
    _is_machine_translated,
    _parse_fallback_text,
    _parse_json3_subtitles,
    _select_subtitle_stream,
)

_logger = logging.getLogger("vvc.youtube")

__all__ = [
    "fetch_youtube_transcript",
    "extract_transcript_via_ytdlp",
    "get_base_ydl_opts",
    "_is_machine_translated",
    "_find_lang",
    "_find_native_asr",
    "_select_subtitle_stream",
    "_find_target_sub_url",
    "_group_timed_segments",
    "_parse_json3_subtitles",
    "_parse_fallback_text",
    "_extract_video_id",
    "_download_audio_via_ytdlp",
]


def get_base_ydl_opts() -> dict[str, Any]:
    """Base yt-dlp options configured to bypass YouTube bot checks."""
    return {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"]
            }
        },
    }


def _build_ytdlp_subtitle_opts() -> dict[str, Any]:
    """Base options for subtitle extraction via yt-dlp."""
    opts = get_base_ydl_opts()
    opts.update({
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["vi", "en"],
    })
    return opts


def extract_transcript_via_ytdlp(url: str, info_dict: dict | None = None) -> str | None:
    """Extract official or auto-generated subtitles directly using yt-dlp.

    Bypasses Botguard / IP block by using mobile client emulation.
    """
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL(_build_ytdlp_subtitle_opts()) as ydl:
            info = info_dict or ydl.extract_info(url, download=False)
            if not info or info.get("is_live"):
                if info and info.get("is_live"):
                    _logger.warning(f"Video {url} đang phát sóng trực tiếp (Live Stream). Không thể trích xuất phụ đề tĩnh.")
                return None

            subtitles = {k: v for k, v in (info.get("subtitles") or {}).items() if k not in _IGNORED_SUB_KEYS}
            auto_subtitles = {k: v for k, v in (info.get("automatic_captions") or {}).items() if k not in _IGNORED_SUB_KEYS}

            selected_sub = _select_subtitle_stream(subtitles, auto_subtitles)
            if not selected_sub:
                return None

            target_url = _find_target_sub_url(selected_sub)
            if not target_url:
                return None

            sub_content = ydl.urlopen(target_url).read().decode("utf-8")
            if sub_content.strip().lower().startswith(("<!doctype html", "<html", "<?xml", "var ytcfg", "window.yt")):
                _logger.warning(f"Phát hiện nội dung phụ đề là mã HTML/JS rác thay vì captions: {url}")
                return None

            if "json3" in target_url or sub_content.strip().startswith("{"):
                json3_res = _parse_json3_subtitles(sub_content)
                if json3_res:
                    return json3_res

            return _parse_fallback_text(sub_content)

    except Exception as e:
        _logger.warning(f"yt-dlp subtitle extraction failed: {e}")
        return None


def _download_audio_via_ytdlp(url: str, info_dict: dict | None = None) -> Path | None:
    """Download audio from URL using yt-dlp as fallback.

    Uses mobile player clients to avoid bot blocks, and supports ba/b/18
    when SABR streaming skips standalone audio-only streams.
    """
    try:
        import yt_dlp

        out_dir = cfg.concepts_dir.parent.parent / "05 - Fleeting"
        out_tmpl = str(out_dir / "%(id)s.%(ext)s")

        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            "format": "worstaudio/worst/ba/b/18",
            "outtmpl": out_tmpl,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            check_info = info_dict or ydl.extract_info(url, download=False)
            if check_info and check_info.get("is_live"):
                _logger.warning(f"Video {url} đang phát sóng trực tiếp (Live Stream). Không thể tải audio luồng live.")
                return None

            info = ydl.extract_info(url, download=True)
            if not info:
                return None

            video_id = info.get("id", "")
            if not video_id:
                return None

            for f in out_dir.glob(f"{video_id}.*"):
                if f.is_file():
                    return f
            return None
    except ImportError:
        _logger.warning("yt-dlp is not installed. Run: pip install yt-dlp")
        return None
    except Exception as e:
        _logger.warning(f"yt-dlp download failed: {e}")
        return None


def _fetch_transcript_via_api(url: str) -> str:
    """Fetch transcript via youtube_transcript_api (secondary fallback)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        video_id = _extract_video_id(url)
        if not video_id:
            return ""

        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        try:
            transcript = transcript_list.find_transcript(["vi", "en"])
        except Exception:
            codes = [t.language_code for t in transcript_list]
            if not codes:
                return ""
            transcript = transcript_list.find_transcript(codes)

        data = transcript.fetch()
        segments = [
            (
                s.start if hasattr(s, "start") else s.get("start", 0.0),
                s.text if hasattr(s, "text") else s.get("text", ""),
            )
            for s in data
        ]
        return _group_timed_segments(segments)
    except Exception as e:
        _logger.warning(f"youtube_transcript_api fetch failed: {e}")
        return ""


def fetch_youtube_transcript(url: str, info_dict: dict | None = None) -> str:
    """Fetch transcript from YouTube URL, fallback to audio download + Whisper."""
    if info_dict and info_dict.get("is_live"):
        _logger.warning(f"Video {url} đang phát sóng trực tiếp (Live Stream). Không thể trích xuất transcript tự động.")
        return ""

    # 1. Primary: Direct subtitle extraction via yt-dlp mobile client
    text = extract_transcript_via_ytdlp(url, info_dict=info_dict)
    if text:
        return text

    # 2. Secondary fallback: youtube_transcript_api
    text = _fetch_transcript_via_api(url)
    if text:
        return text

    # 3. Tertiary fallback: Audio Download via yt-dlp + Whisper AI
    _logger.info(f"Fallback to yt-dlp + Whisper for URL: {url}")
    audio_path = _download_audio_via_ytdlp(url, info_dict=info_dict)
    if audio_path:
        try:
            text = call_audio(audio_path, model="audio-primary", language=None)
            return text or ""
        except Exception as e:
            _logger.error(f"Audio transcription failed: {e}")
        finally:
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    pass
    return ""
