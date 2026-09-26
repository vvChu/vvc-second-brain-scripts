"""VvC Second Brain — YouTube Transcript Fetcher.

Extracts transcripts from YouTube via yt-dlp mobile client emulation,
with fallbacks to youtube_transcript_api and audio download + Whisper.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm import call_audio

_logger = logging.getLogger("vvc.youtube")


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


def _is_machine_translated(sub_formats: list) -> bool:
    """Returns True if the subtitle format entry is machine-translated (contains tlang= query param)."""
    if not sub_formats:
        return False
    first_url = sub_formats[0].get("url", "")
    return "tlang=" in first_url


def _find_lang(sub_dict: dict, lang_prefix: str) -> list | None:
    """Find matching subtitle format list by exact key, orig suffix, or prefix."""
    orig_key = f"{lang_prefix}-orig"
    if orig_key in sub_dict:
        return sub_dict[orig_key]
    if lang_prefix in sub_dict:
        return sub_dict[lang_prefix]
    for k, v in sub_dict.items():
        if k.startswith(f"{lang_prefix}-"):
            return v
    return None


def _find_native_asr(auto_dict: dict, lang_prefix: str) -> list | None:
    """Find a native ASR subtitle list for the language prefix (no tlang= param).
    Prioritizes '<lang>-orig' if present, then '<lang>', then '<lang>-*'.
    """
    orig_key = f"{lang_prefix}-orig"
    if orig_key in auto_dict and not _is_machine_translated(auto_dict[orig_key]):
        return auto_dict[orig_key]
    if lang_prefix in auto_dict and not _is_machine_translated(auto_dict[lang_prefix]):
        return auto_dict[lang_prefix]
    for k, v in auto_dict.items():
        if k.startswith(f"{lang_prefix}-") and not _is_machine_translated(v):
            return v
    return None


_IGNORED_SUB_KEYS = {"live_chat", "live_chat_replay"}


def _select_subtitle_stream(subtitles: dict, auto_subtitles: dict) -> list | None:
    """Select best subtitle format using 4-Tier Selection Hierarchy."""
    selected = _find_lang(subtitles, "vi") or _find_lang(subtitles, "en")
    if not selected and subtitles:
        selected = next(iter(subtitles.values()))
    if selected:
        return selected

    selected = _find_native_asr(auto_subtitles, "vi") or _find_native_asr(auto_subtitles, "en")
    if not selected:
        for v in auto_subtitles.values():
            if not _is_machine_translated(v):
                selected = v
                break
    if selected:
        return selected

    selected = _find_lang(auto_subtitles, "vi") or _find_lang(auto_subtitles, "en")
    if not selected and auto_subtitles:
        selected = next(iter(auto_subtitles.values()))
    return selected


def _find_target_sub_url(selected_sub: list[dict]) -> str | None:
    """Prefer JSON3 format for precise timestamps, fallback to vtt / srv3."""
    json3_url = None
    vtt_url = None
    for fmt in selected_sub:
        ext = fmt.get("ext")
        if ext == "json3":
            json3_url = fmt.get("url")
            break
        if ext == "vtt":
            vtt_url = fmt.get("url")
    return json3_url or vtt_url or (selected_sub[0].get("url") if selected_sub else None)


def _group_timed_segments(segments: list[tuple[float, str]], window_sec: float = 30.0) -> str:
    """Group timed text segments into time-windowed blocks (e.g. [00:01] text)."""
    formatted_lines: list[str] = []
    curr_start: float | None = None
    curr_texts: list[str] = []

    for t_offset, text_part in segments:
        text_clean = text_part.strip()
        if not text_clean or text_clean == "\n":
            continue
        if curr_start is None:
            curr_start = t_offset
            curr_texts.append(text_clean)
        elif t_offset - curr_start >= window_sec:
            m, s = int(curr_start // 60), int(curr_start % 60)
            formatted_lines.append(f"[{m:02d}:{s:02d}] " + " ".join(curr_texts))
            curr_start = t_offset
            curr_texts = [text_clean]
        else:
            curr_texts.append(text_clean)

    if curr_texts and curr_start is not None:
        m, s = int(curr_start // 60), int(curr_start % 60)
        formatted_lines.append(f"[{m:02d}:{s:02d}] " + " ".join(curr_texts))

    return "\n\n".join(formatted_lines)


def _parse_json3_subtitles(sub_content: str) -> str | None:
    """Parse JSON3 format subtitles into timestamped lines."""
    try:
        data = json.loads(sub_content)
        segments: list[tuple[float, str]] = []
        for event in data.get("events", []):
            segs = event.get("segs")
            if not segs:
                continue
            t_offset = event.get("tStartMs", 0) / 1000.0
            text_part = "".join(s.get("utf8", "") for s in segs).strip()
            if text_part and text_part != "\n":
                segments.append((t_offset, text_part))
        res = _group_timed_segments(segments)
        return res if res else None
    except Exception as e:
        _logger.warning(f"Failed parsing JSON3 subtitles: {e}")
        return None


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


def _parse_fallback_text(sub_content: str) -> str | None:
    """Parse fallback subtitle formats (vtt, srt, etc.)."""
    lines = [
        line.strip()
        for line in sub_content.splitlines()
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    ]
    return "\n".join(lines) if lines else None


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

        # Save to 05 - Fleeting (scratch area)
        out_dir = cfg.concepts_dir.parent.parent / "05 - Fleeting"
        out_tmpl = str(out_dir / "%(id)s.%(ext)s")

        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            "format": "worstaudio/worst/ba/b/18",
            "outtmpl": out_tmpl,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Check info before downloading to prevent infinite stream capture on active livestreams
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

            # Find the downloaded file by its ID
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


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from standard or shortened URLs."""
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path[1:]
    if parsed.hostname in ("youtube.com", "www.youtube.com"):
        if parsed.path == "/watch":
            qs = urllib.parse.parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/v/", "/live/")):
            return parsed.path.split("/")[2]
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
