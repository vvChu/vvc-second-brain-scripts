"""VvC Second Brain — YouTube Subtitle Cleaner & Parser.

Provides parsing, stream selection, and time-windowed segmentation for YouTube subtitles.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

_logger = logging.getLogger("vvc.youtube.cleaner")

_IGNORED_SUB_KEYS = {"live_chat", "live_chat_replay"}


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


def _parse_fallback_text(sub_content: str) -> str | None:
    """Parse fallback subtitle formats (vtt, srt, etc.)."""
    lines = [
        line.strip()
        for line in sub_content.splitlines()
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    ]
    return "\n".join(lines) if lines else None


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
