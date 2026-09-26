"""VvC Second Brain — YouTube Stage 2 High-Res Frame Extractor.

Handles high-res video stream selection, local video download via yt-dlp,
offline frame extraction via FFmpeg seek, and WebP compression.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
from typing import Any

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

from core.media import find_ffmpeg_bin as _find_ffmpeg_bin

_logger = logging.getLogger("vvc.youtube.stage2")
_MAX_KEY_FRAMES = 10


def _score_video_format(fmt: dict) -> tuple[int, str, str]:
    """Score video format for quality and compatibility (prefer 720p/1080p mp4 avc1)."""
    url = fmt.get("url") or ""
    if not url.startswith("http"):
        return -1, "", "Mozilla/5.0"

    vcodec = fmt.get("vcodec", "none")
    if vcodec == "none":
        return -1, "", "Mozilla/5.0"

    height = fmt.get("height") or 0
    ext = fmt.get("ext", "")

    height_scores = {720: 100, 1080: 90, 480: 50}
    score = height_scores.get(height, 40 if height > 1080 else (10 if height > 0 else 0))
    if ext == "mp4":
        score += 10
    if "avc1" in vcodec:
        score += 5

    ua = fmt.get("http_headers", {}).get("User-Agent") or "Mozilla/5.0"
    return score, url, ua


def _get_high_res_stream_url(info_dict: dict) -> tuple[str | None, str]:
    """Find the best high-res stream URL from yt-dlp info_dict."""
    if not info_dict:
        return None, "Mozilla/5.0"

    formats = info_dict.get("formats", [])
    if not formats:
        return None, "Mozilla/5.0"

    best_url: str | None = None
    best_score = -1
    best_ua = info_dict.get("http_headers", {}).get("User-Agent") or "Mozilla/5.0"

    for fmt in formats:
        score, url, ua = _score_video_format(fmt)
        if score > best_score:
            best_score = score
            best_url = url
            best_ua = ua

    return best_url, best_ua


def _get_video_download_ydl_opts(out_tmpl: str) -> dict:
    """yt-dlp options specifically for high-quality video extraction."""
    return {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/best[height<=720]/b/18/bestvideo/best",
        "outtmpl": out_tmpl,
    }


def _download_local_stage2_video(video_id: str, tmp_dir: Path) -> Path | None:
    """Download 720p/360p video locally to extract high-res frames."""
    out_tmpl = str(tmp_dir / f"{video_id}_temp.%(ext)s")
    ydl_opts = _get_video_download_ydl_opts(out_tmpl)

    try:
        _logger.info("Stage 2: Đang tải video 720p cục bộ để trích xuất frame chất lượng cao...")
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except Exception as dl_err:
        _logger.warning(f"Tải video theo selector chính thất bại ({dl_err}). Thử fallback format 18...")
        try:
            import yt_dlp
            fallback_opts = dict(ydl_opts)
            fallback_opts["format"] = "18/best"
            fallback_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        except Exception as fallback_err:
            _logger.warning(f"Không tải được video cục bộ bằng yt-dlp: {fallback_err}. Sẽ fallback sang storyboard frames.")

    for f in tmp_dir.glob(f"{video_id}_temp.*"):
        if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
            _logger.info(f"Tải video cục bộ thành công: {f.name}")
            return f
    return None


def _extract_offline_frame(
    ffmpeg_bin: str,
    video_path: Path,
    ts: float,
    out_jpg: Path,
) -> bool:
    """Run FFmpeg command to extract a single frame at timestamp."""
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cmd = [
        ffmpeg_bin, "-y",
        "-ss", str(round(ts, 2)),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(out_jpg),
    ]
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            startupinfo=startupinfo, text=True, timeout=10,
        )
        return res.returncode == 0 and out_jpg.exists()
    except Exception as exc:
        _logger.warning(f"Local seek thất bại: {exc}")
        return False


def _save_frame_as_webp(src_path: Path, dest_path: Path) -> bool:
    """Open source frame, resize thumbnail, and save as WebP."""
    if PILImage is None:
        return False
    try:
        img = PILImage.open(src_path)
        img.thumbnail((1280, 1280), PILImage.Resampling.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.save(dest_path, "WEBP", quality=80)
        return True
    except Exception as e:
        _logger.warning(f"Lỗi khi lưu ảnh WebP {dest_path.name}: {e}")
        return False


def _check_frame_need_update(save_path: Path) -> bool:
    """Check if existing frame file is missing or low quality."""
    if not save_path.exists():
        return True
    if PILImage is None:
        return False
    try:
        with PILImage.open(save_path) as img:
            return max(img.size) < 480 or img.size in ((320, 180), (80, 45))
    except Exception:
        return True


def _process_single_key_frame(
    idx: int,
    extracted_frames: list[Path],
    frame_metadata: dict[Path, dict],
    video_id: str,
    assets_dir: Path,
    tmp_dir: Path,
    sb0: dict | None,
    ffmpeg_bin: str | None,
    local_video_path: Path | None,
) -> tuple[str | None, str | None]:
    """Extract and save a single key frame as WebP."""
    if idx < 0 or idx >= len(extracted_frames):
        return None, None

    frame_path = extracted_frames[idx]
    metadata = frame_metadata.get(frame_path, {"timestamp": 0.0, "original_index": idx})
    ts = metadata["timestamp"]
    orig_idx = metadata["original_index"]
    filename = f"yt_{video_id}_frame_{orig_idx:03d}_ts{int(ts)}.webp"
    save_path = assets_dir / filename

    if not _check_frame_need_update(save_path):
        return filename, None

    src_frame_path = frame_path
    if sb0 and ffmpeg_bin and local_video_path and local_video_path.exists():
        high_res_jpg = tmp_dir / f"high_res_temp_{idx:03d}.jpg"
        if _extract_offline_frame(ffmpeg_bin, local_video_path, ts, high_res_jpg):
            src_frame_path = high_res_jpg

    if _save_frame_as_webp(src_frame_path, save_path):
        return filename, None
    return None, None


def _prepare_stage2_alt_and_download_need(
    key_frame_indices: list[int],
    key_frame_alts: dict[int, str],
    extracted_frames: list[Path],
    frame_metadata: dict[Path, dict],
    video_id: str,
    assets_dir: Path,
) -> tuple[dict[str, str], bool]:
    """Map alt texts and check if any key frame requires local video download."""
    frame_to_alt: dict[str, str] = {}
    need_download = False
    for raw_idx in key_frame_indices[:_MAX_KEY_FRAMES]:
        try:
            idx = int(raw_idx)
            if 0 <= idx < len(extracted_frames):
                p = extracted_frames[idx]
                meta = frame_metadata.get(p, {"timestamp": 0.0, "original_index": idx})
                fname = f"yt_{video_id}_frame_{meta['original_index']:03d}_ts{int(meta['timestamp'])}.webp"
                if idx in key_frame_alts:
                    frame_to_alt[fname] = key_frame_alts[idx]
                elif meta["original_index"] in key_frame_alts:
                    frame_to_alt[fname] = key_frame_alts[meta["original_index"]]
                if _check_frame_need_update(assets_dir / fname):
                    need_download = True
        except (ValueError, TypeError):
            pass
    return frame_to_alt, need_download


def extract_stage2_key_frames(
    video_id: str,
    key_frame_indices: list[int],
    key_frame_alts: dict[int, str],
    extracted_frames: list[Path],
    frame_metadata: dict[Path, dict],
    assets_dir: Path,
    tmp_dir: Path,
    sb0: dict | None,
) -> tuple[list[str], dict[str, str], Path | None]:
    """Execute Stage 2 high-res frame download, extraction, and WebP compression."""
    if not key_frame_indices or PILImage is None:
        return [], {}, None

    assets_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = _find_ffmpeg_bin()
    saved_frames: list[str] = []

    frame_to_alt, need_download = _prepare_stage2_alt_and_download_need(
        key_frame_indices, key_frame_alts, extracted_frames,
        frame_metadata, video_id, assets_dir,
    )
    local_video_path = _download_local_stage2_video(video_id, tmp_dir) if need_download else None

    for raw_idx in key_frame_indices[:_MAX_KEY_FRAMES]:
        try:
            idx = int(raw_idx)
            fname, _ = _process_single_key_frame(
                idx, extracted_frames, frame_metadata, video_id,
                assets_dir, tmp_dir, sb0, ffmpeg_bin, local_video_path,
            )
            if fname and fname not in saved_frames:
                saved_frames.append(fname)
        except Exception as e:
            _logger.warning(f"Lỗi khi lưu frame video {raw_idx}: {e}")

    return saved_frames, frame_to_alt, local_video_path
