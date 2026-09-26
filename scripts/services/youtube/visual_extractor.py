"""VvC Second Brain — YouTube Visual Extractor.

Extract visual frames from YouTube videos.
Context-Aware Visual Judge and Two-Stage Hybrid Ingestion (v12.0).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
from typing import Any

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

from core.config import cfg
from core.llm.utils import http_session, encode_image  # noqa: F401
from core.media import find_ffmpeg_bin as _find_ffmpeg_bin

# Re-exports from storyboard_sampler
from services.youtube.storyboard_sampler import (
    _compute_frame_hash,
    _dedup_frames,
    _get_heatmap_peaks,
    _get_target_timestamps,
    _download_grid_with_retry,
    _select_best_storyboard_format,
    _get_storyboard_frames,
)

# Re-exports from visual_judge
from services.youtube.visual_judge import (
    KeyFramesParseResult,
    _parse_key_frames_response,
    _resolve_key_frames_with_fallback,
    _generate_semantic_alt_texts,
    _build_judge_prompt,
    _call_vision_judge_api,
)

# Re-exports from stage2_extractor
from services.youtube.stage2_extractor import (
    _get_high_res_stream_url,
    _get_video_download_ydl_opts,
    extract_stage2_key_frames,
)

_logger = logging.getLogger("vvc.youtube")
_MAX_KEY_FRAMES = 10

__all__ = [
    "extract_video_visuals",
    "_compute_frame_hash",
    "_dedup_frames",
    "_get_heatmap_peaks",
    "_get_target_timestamps",
    "_download_grid_with_retry",
    "_select_best_storyboard_format",
    "_get_storyboard_frames",
    "KeyFramesParseResult",
    "_parse_key_frames_response",
    "_resolve_key_frames_with_fallback",
    "_generate_semantic_alt_texts",
    "_get_high_res_stream_url",
    "_get_video_download_ydl_opts",
    "_find_ffmpeg_bin",
    "http_session",
]


def _parse_video_id(url: str) -> str | None:
    """Parse stable video ID from various YouTube URL formats."""
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path.lstrip("/")
    if parsed.hostname in ("youtube.com", "www.youtube.com"):
        if parsed.path == "/watch":
            qs = urllib.parse.parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/v/", "/live/")):
            parts = parsed.path.split("/")
            return parts[2] if len(parts) > 2 else None
    return None


def _fetch_video_info(url: str, info_dict: dict | None) -> dict | None:
    """Fetch video info dict JIT if not already provided."""
    if info_dict:
        return info_dict
    _logger.info(f"Đang phân tích siêu dữ liệu JIT cho: {url}")
    try:
        import yt_dlp
        from services.youtube.transcript import get_base_ydl_opts
        with yt_dlp.YoutubeDL(get_base_ydl_opts()) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        _logger.warning(f"Lỗi khi tải metadata video: {e}")
        return None


def _download_fallback_video(video_id: str, url: str, tmp_dir: Path) -> Path | None:
    """Download video with low resolution for FFmpeg fallback frame extraction."""
    out_tmpl = str(tmp_dir / f"{video_id}.%(ext)s")
    ydl_opts = _get_video_download_ydl_opts(out_tmpl)
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        for f in tmp_dir.glob(f"{video_id}.*"):
            if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
                return f
    except Exception as e:
        _logger.warning(f"Không tải được video fallback: {e}")
    return None


def _extract_fallback_static_frames(
    ffmpeg_bin: str,
    video_path: Path,
    target_timestamps: list[float],
    tmp_dir: Path,
) -> tuple[list[Path], dict[Path, dict]]:
    """Extract static frames at target timestamps via FFmpeg."""
    static_frames: list[Path] = []
    metadata: dict[Path, dict] = {}
    for i, ts in enumerate(target_timestamps):
        out_p = tmp_dir / f"frame_static_{i:04d}.jpg"
        cmd = [ffmpeg_bin, "-y", "-ss", str(round(ts, 2)), "-i", str(video_path), "-vframes", "1", str(out_p)]
        if subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0 and out_p.exists():
            static_frames.append(out_p)
            metadata[out_p] = {"timestamp": ts, "original_index": i}
    return static_frames, metadata


def _extract_fallback_dynamic_frames(
    ffmpeg_bin: str,
    video_path: Path,
    duration_sec: float,
    start_idx: int,
    tmp_dir: Path,
) -> tuple[list[Path], dict[Path, dict]]:
    """Extract scene-change frames via FFmpeg select=gt(scene,0.3)."""
    scene_pattern = tmp_dir / "frame_scene_%04d.jpg"
    cmd = [ffmpeg_bin, "-y", "-i", str(video_path), "-vf", "select=gt(scene\\,0.3)", "-vsync", "vfr", str(scene_pattern)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    frames = sorted(list(tmp_dir.glob("frame_scene_*.jpg")))
    metadata: dict[Path, dict] = {}
    for i, p in enumerate(frames):
        est_ts = (i / max(1, len(frames))) * duration_sec
        metadata[p] = {"timestamp": est_ts, "original_index": start_idx + i}
    return frames, metadata


def _run_ffmpeg_fallback_sampling(
    ffmpeg_bin: str,
    video_path: Path,
    target_timestamps: list[float],
    duration_sec: float,
    tmp_dir: Path,
) -> tuple[list[Path], dict[Path, dict]]:
    """Run FFmpeg static + scene change sampling, with uniform FPS fallback."""
    static_frames, meta = _extract_fallback_static_frames(ffmpeg_bin, video_path, target_timestamps, tmp_dir)
    dyn_frames, dyn_meta = _extract_fallback_dynamic_frames(ffmpeg_bin, video_path, duration_sec, len(target_timestamps), tmp_dir)
    meta.update(dyn_meta)
    extracted = static_frames + dyn_frames

    if not extracted:
        pat = tmp_dir / "frame_fallback_%04d.jpg"
        cmd = [ffmpeg_bin, "-y", "-i", str(video_path), "-vf", "fps=1/10", "-vsync", "vfr", str(pat)]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        extracted = sorted(list(tmp_dir.glob("frame_fallback_*.jpg")))
        for i, p in enumerate(extracted):
            meta[p] = {"timestamp": (i / max(1, len(extracted))) * duration_sec, "original_index": i}

    return extracted, meta


def _build_img_markdown_section(
    saved_frames: list[str],
    frame_to_alt: dict[str, str],
    summary: str,
) -> str:
    """Format and append IMG markers with semantic alt text to summary."""
    if not saved_frames:
        return summary
    missing_alts = [f for f in saved_frames if f not in frame_to_alt]
    if missing_alts:
        try:
            fallback_alts = _generate_semantic_alt_texts(summary, missing_alts)
            frame_to_alt.update(fallback_alts)
        except Exception as e:
            _logger.warning(f"Lỗi khi tạo semantic alt-text fallback: {e}")

    img_section = "\n\n## 🎬 Hình ảnh trực quan từ video (Đã tải cục bộ)"
    for f in saved_frames:
        desc = frame_to_alt.get(f, "Video frame - diagram/slide")
        img_section += f"\n[IMG:{f}|alt={desc}]"
    return f"{summary}{img_section}"


def _cleanup_temporary_files(
    tmp_dir: Path,
    video_path: Path | None,
    local_video_path: Path | None,
) -> None:
    """Safely unlink all temporary video and image files."""
    for p in (video_path, local_video_path):
        if p and p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    for f in tmp_dir.glob("*.jpg"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        tmp_dir.rmdir()
    except OSError:
        pass


def _extract_coarse_frames(
    sb0: dict | None,
    url: str,
    video_id: str,
    target_timestamps: list[float],
    duration_sec: float,
    tmp_dir: Path,
) -> tuple[list[Path], dict[Path, dict], Path | None]:
    """Execute coarse frame extraction via Storyboards or FFmpeg fallback."""
    if sb0:
        extracted = _get_storyboard_frames(sb0, tmp_dir, target_timestamps, duration_sec)
        meta = {}
        for i, p in enumerate(extracted):
            m = re.search(r"_ts(\d+)", p.name)
            ts = float(m.group(1)) if m else (target_timestamps[i] if i < len(target_timestamps) else 0.0)
            meta[p] = {"timestamp": ts, "original_index": i}
        return extracted, meta, None

    v_path = _download_fallback_video(video_id, url, tmp_dir)
    ffmpeg_bin = _find_ffmpeg_bin()
    if not v_path or not ffmpeg_bin:
        return [], {}, v_path
    extracted, meta = _run_ffmpeg_fallback_sampling(ffmpeg_bin, v_path, target_timestamps, duration_sec, tmp_dir)
    return extracted, meta, v_path


def extract_video_visuals(url: str, transcript_text: str = None, info_dict: dict = None) -> str:
    """Trích xuất hình ảnh trực quan từ video YouTube sử dụng Context-Aware Visual Judge (v12.0)."""
    tmp_dir = Path(__file__).parent.parent.parent / "scratch" / "_video_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    video_path: Path | None = None
    local_video_path: Path | None = None

    try:
        video_id = _parse_video_id(url)
        if not video_id:
            return ""

        info_dict = _fetch_video_info(url, info_dict)
        if not info_dict:
            return ""

        duration_sec = info_dict.get("duration") or 600
        chapters = info_dict.get("chapters") or []
        heatmap = info_dict.get("heatmap") or []
        sb0 = _select_best_storyboard_format(info_dict.get("formats", []))
        target_timestamps = _get_target_timestamps(duration_sec, chapters, heatmap)

        extracted_frames, frame_meta, video_path = _extract_coarse_frames(
            sb0, url, video_id, target_timestamps, duration_sec, tmp_dir
        )
        if PILImage is not None and len(extracted_frames) > 1:
            extracted_frames = _dedup_frames(extracted_frames)
        if not extracted_frames:
            return ""

        _find_ffmpeg_bin()
        _get_high_res_stream_url(info_dict)

        prompt_text = _build_judge_prompt(transcript_text)
        summary = _call_vision_judge_api(extracted_frames, prompt_text, session=http_session)
        summary, key_indices, key_alts = _resolve_key_frames_with_fallback(summary, len(extracted_frames))

        assets_dir = cfg.assets_dir / "video_frames"
        saved_frames, frame_to_alt, local_video_path = extract_stage2_key_frames(
            video_id, key_indices, key_alts, extracted_frames, frame_meta,
            assets_dir, tmp_dir, sb0,
        )
        return _build_img_markdown_section(saved_frames, frame_to_alt, summary)
    except Exception as e:
        _logger.error(f"Lỗi khi trích xuất visual của video: {e}", exc_info=True)
        return ""
    finally:
        _cleanup_temporary_files(tmp_dir, video_path, local_video_path)
