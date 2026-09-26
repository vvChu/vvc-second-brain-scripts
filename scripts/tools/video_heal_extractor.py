"""VvC Second Brain — Video Frame Extraction & Stream Healing Engine.

Provides low-level FFmpeg execution, YouTube stream resolution,
local video download fallback, and WebP frame conversion.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from PIL import Image
import yt_dlp

from core.config import cfg
from services.youtube.visual_extractor import (
    _get_high_res_stream_url,
    _get_video_download_ydl_opts,
)

_logger = logging.getLogger("vvc.heal_video_frames.extractor")


def _run_ffmpeg(cmd: list[str], timeout: int) -> bool:
    """Execute FFmpeg command with proper platform flags and timeout."""
    startupinfo = subprocess.STARTUPINFO() if os.name == "nt" else None
    if startupinfo:
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            startupinfo=startupinfo, timeout=timeout,
        )
        return res.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        _logger.warning(f"FFmpeg error: {e}")
        return False


def extract_frame_via_stream(
    ffmpeg_bin: str, stream_url: str, user_agent: str, timestamp: int, out_path: Path,
) -> bool:
    """Extract a single frame directly from a remote stream URL via FFmpeg seek."""
    cmd = [
        ffmpeg_bin, "-y", "-ss", str(timestamp), "-user_agent", user_agent,
        "-i", stream_url, "-vframes", "1", "-q:v", "2", str(out_path),
    ]
    return _run_ffmpeg(cmd, 25) and out_path.exists() and out_path.stat().st_size > 0


def extract_frame_from_local_video(
    ffmpeg_bin: str, video_path: Path, timestamp: int, out_path: Path,
) -> bool:
    """Extract a single frame from a locally downloaded video file via FFmpeg."""
    cmd = [
        ffmpeg_bin, "-y", "-ss", str(timestamp), "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(out_path),
    ]
    return _run_ffmpeg(cmd, 15) and out_path.exists() and out_path.stat().st_size > 0


def save_as_webp(src_img_path: Path, dest_webp_path: Path) -> tuple[int, int] | None:
    """Convert and save image to WebP format with quality=80."""
    try:
        with Image.open(src_img_path) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.save(dest_webp_path, "WEBP", quality=80)
            return img.size
    except Exception as e:
        _logger.error(f"Lỗi khi lưu WebP {dest_webp_path.name}: {e}")
        return None


def download_local_video(video_id: str, out_dir: Path) -> Path | None:
    """Download video with format selector and format 18 fallback."""
    out_tmpl = str(out_dir / f"{video_id}_dl.%(ext)s")
    ydl_opts = _get_video_download_ydl_opts(out_tmpl)
    variants = (
        ydl_opts,
        dict(ydl_opts, format="18/best", extractor_args={"youtube": {"player_client": ["android", "web"]}}),
    )
    for opts in variants:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            for f in out_dir.glob(f"{video_id}_dl.*"):
                if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
                    return f
        except Exception as err:
            _logger.warning(f"Tải video {video_id} thử nghiệm thất bại: {err}")
    return None


def _get_video_stream(video_id: str) -> tuple[str | None, str]:
    """Retrieve stream URL and user agent for a YouTube video."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "skip_download": True, "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                return _get_high_res_stream_url(info)
    except Exception as e:
        _logger.warning(f"Không thể lấy stream URL cho {video_id}: {e}")
    return None, "Mozilla/5.0"


def _process_pending_with_download(
    video_id: str,
    pending: list[tuple[Path, int, tuple[int, int]]],
    ffmpeg_bin: str,
    tmp_dir: Path,
) -> int:
    """Download video locally and extract remaining pending frames."""
    _logger.info(f"Cần tải video cục bộ cho {len(pending)} frames của {video_id}...")
    dl_video = download_local_video(video_id, tmp_dir)
    if not dl_video or not dl_video.exists():
        return 0

    healed = 0
    try:
        for frame_path, ts, old_size in pending:
            temp_out = tmp_dir / f"temp_dl_{video_id}_{ts}.jpg"
            if extract_frame_from_local_video(ffmpeg_bin, dl_video, ts, temp_out):
                new_size = save_as_webp(temp_out, frame_path)
                if new_size and max(new_size) >= 200:
                    _logger.info(f"  [OK-DL] {frame_path.name}: {old_size} -> {new_size}")
                    healed += 1
            if temp_out.exists():
                temp_out.unlink()
    finally:
        if dl_video.exists():
            dl_video.unlink()
    return healed


def heal_video_id_frames(
    video_id: str,
    frames: list[tuple[Path, int, tuple[int, int]]],
    ffmpeg_bin: str,
    tmp_dir: Path,
) -> int:
    """Heal all low-res frames for a specific video ID."""
    _logger.info(f"=== Bắt đầu phục hồi video {video_id} ({len(frames)} frames) ===")
    local_cached = cfg.vault_root / "scratch" / "_heal_test" / f"test_{video_id}.mp4"
    stream_url, user_agent = _get_video_stream(video_id)
    healed_count = 0
    pending_frames: list[tuple[Path, int, tuple[int, int]]] = []

    for frame_path, ts, old_size in frames:
        temp_out = tmp_dir / f"temp_{video_id}_{ts}.jpg"
        success = (
            extract_frame_from_local_video(ffmpeg_bin, local_cached, ts, temp_out)
            if local_cached and local_cached.exists()
            else (extract_frame_via_stream(ffmpeg_bin, stream_url, user_agent, ts, temp_out) if stream_url else False)
        )
        if success and temp_out.exists():
            new_size = save_as_webp(temp_out, frame_path)
            if temp_out.exists():
                temp_out.unlink()
            if new_size and max(new_size) >= 200:
                _logger.info(f"  [OK] {frame_path.name}: {old_size} -> {new_size}")
                healed_count += 1
                continue
        pending_frames.append((frame_path, ts, old_size))

    if pending_frames:
        healed_count += _process_pending_with_download(video_id, pending_frames, ffmpeg_bin, tmp_dir)
    return healed_count
