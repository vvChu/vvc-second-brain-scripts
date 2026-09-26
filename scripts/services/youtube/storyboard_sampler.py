"""VvC Second Brain — YouTube Storyboard Sampler.

Handles perceptual hash deduplication, adaptive chapter/heatmap target timestamps,
storyboard format selection, grid downloading, and tile cropping.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error
import time

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

_logger = logging.getLogger("vvc.youtube.sampler")


# --- Perceptual Hash Deduplication ---

def _compute_frame_hash(img_path: Path, size: int = 8) -> int:
    """Compute average perceptual hash using pure PIL (no external deps)."""
    if PILImage is None:
        return 0
    try:
        img = PILImage.open(img_path).convert("L").resize((size, size), PILImage.Resampling.LANCZOS)
        pixels = list(img.getdata())
        if not pixels:
            return 0
        avg = sum(pixels) / len(pixels)
        return sum(1 << i for i, px in enumerate(pixels) if px > avg)
    except (FileNotFoundError, OSError):
        return 0


def _dedup_frames(frames: list[Path], threshold: int = 2) -> list[Path]:
    """Remove near-duplicate frames using all-pairs perceptual hash comparison."""
    if len(frames) <= 1 or PILImage is None:
        return frames
    if not frames[0].exists():
        return frames

    unique: list[Path] = []
    hashes: list[int] = []

    for f in frames:
        curr_hash = _compute_frame_hash(f)
        if curr_hash == 0:
            unique.append(f)
            hashes.append(curr_hash)
            continue

        is_dup = any(
            h != 0 and bin(curr_hash ^ h).count("1") < threshold
            for h in hashes
        )
        if not is_dup:
            unique.append(f)
            hashes.append(curr_hash)

    return unique


# --- Heatmap & Target Timestamps ---

def _get_heatmap_peaks(heatmap: list[dict], duration_sec: float, max_peaks: int = 5) -> list[float]:
    """Parse YouTube heatmap and find the top K timestamps of highest user engagement."""
    if not heatmap:
        return []

    valid_entries: list[tuple[float, float]] = []
    for entry in heatmap:
        start = entry.get("start_time", 0.0)
        end = entry.get("end_time", 0.0)
        val = entry.get("value")
        if val is not None:
            mid = start + (end - start) / 2.0
            if 0.0 <= mid <= duration_sec:
                valid_entries.append((val, mid))

    valid_entries.sort(key=lambda x: x[0], reverse=True)

    peaks: list[float] = []
    for _val, ts in valid_entries:
        if not any(abs(ts - p) < 10.0 for p in peaks):
            peaks.append(ts)
            if len(peaks) >= max_peaks:
                break

    return sorted(peaks)


def _calculate_long_video_factors(num_chapters: int) -> list[float]:
    """Calculate sampling factors for videos over 60 minutes."""
    if num_chapters == 1:
        return [round((i + 1) / 37, 4) for i in range(36)]
    if num_chapters == 2:
        return [round((i + 1) / 19, 4) for i in range(18)]
    if num_chapters == 3:
        return [round((i + 1) / 13, 4) for i in range(12)]
    if num_chapters <= 4:
        return [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    if num_chapters <= 6:
        return [round((i + 1) / 7, 4) for i in range(6)]
    if num_chapters <= 8:
        return [0.15, 0.30, 0.45, 0.60, 0.75, 0.90]
    return [0.20, 0.40, 0.60, 0.80, 0.95] if num_chapters <= 14 else [0.33, 0.66, 0.95]


def _calculate_medium_video_factors(num_chapters: int, target_budget: int) -> list[float]:
    """Calculate sampling factors for short and medium videos."""
    if num_chapters == 1:
        return [round((i + 1) / (target_budget + 1), 4) for i in range(target_budget)]
    if num_chapters <= 3:
        return [0.15, 0.35, 0.55, 0.75, 0.95]
    if num_chapters <= 6:
        return [0.20, 0.40, 0.60, 0.80, 0.95]
    return [0.25, 0.50, 0.75, 0.95] if num_chapters <= 12 else [0.33, 0.66, 0.95]


def _sample_chapter_timestamps(
    chapters: list[dict],
    duration_sec: float,
    p_factors: list[float],
) -> list[float]:
    """Sample timestamps within each chapter using given percentage factors."""
    timestamps: list[float] = []
    for ch in chapters:
        start = max(0.0, ch.get("start_time", 0.0))
        end = min(duration_sec, ch.get("end_time", duration_sec))
        if end <= start:
            continue
        for p in p_factors:
            ts = start + (end - start) * p
            if 0.0 <= ts <= duration_sec:
                timestamps.append(ts)
    return timestamps


def _filter_dense_timestamps(timestamps: list[float], min_gap: float = 2.0) -> list[float]:
    """Deduplicate and sort timestamps, ensuring a minimum time gap."""
    sorted_ts = sorted(list(set(timestamps)))
    filtered: list[float] = []
    for ts in sorted_ts:
        if not filtered or ts - filtered[-1] >= min_gap:
            filtered.append(ts)
    return filtered


def _get_target_timestamps(
    duration_sec: float,
    chapters: list[dict] | None = None,
    heatmap: list[dict] | None = None,
) -> list[float]:
    """Calculate adaptive target timestamps for chapter-aware multi-sampling and heatmap peaks."""
    if duration_sec <= 0:
        return []

    target_budget = 15 if duration_sec < 900 else (25 if duration_sec <= 3600 else 36)
    timestamps: list[float] = []

    if chapters:
        num_ch = len(chapters)
        p_factors = (
            _calculate_long_video_factors(num_ch)
            if duration_sec > 3600
            else _calculate_medium_video_factors(num_ch, target_budget)
        )
        timestamps = _sample_chapter_timestamps(chapters, duration_sec, p_factors)

    if not timestamps:
        step = duration_sec / (target_budget + 1)
        timestamps = [i * step for i in range(1, target_budget + 1) if 0.0 <= i * step <= duration_sec]

    if heatmap:
        peaks = _get_heatmap_peaks(heatmap, duration_sec, max_peaks=10)
        _logger.info(f"Phát hiện {len(peaks)} điểm Viewer Heatmap cực trị: {[round(p, 1) for p in peaks]}")
        timestamps.extend(peaks)

    return _filter_dense_timestamps(timestamps, min_gap=2.0)


# --- Storyboard Slicing & Grid Download ---

def _download_grid_with_retry(
    url: str,
    dest_path: Path,
    max_retries: int = 3,
    timeout: int = 10,
) -> bool:
    """Tải storyboard grid với cơ chế Exponential Backoff và Timeout."""
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                dest_path.write_bytes(resp.read())
            return True
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _logger.warning(f"Tải grid thất bại (Lần thử {attempt}/{max_retries}) với lỗi: {e}")
            if attempt == max_retries:
                break
            time.sleep(delay)
            delay *= 2.0
        except Exception as e:
            _logger.error(f"Lỗi không xác định khi tải grid: {e}")
            break
    return False


def _select_best_storyboard_format(formats: list[dict]) -> dict | None:
    """Select the storyboard format with the largest tile area (width * height)."""
    if not formats:
        return None

    sb_candidates = [
        fmt for fmt in formats
        if fmt.get("format_id", "").startswith("sb") or "storyboard" in fmt.get("format_note", "")
    ]
    if not sb_candidates:
        return None

    def _tile_score(fmt: dict) -> tuple[int, int]:
        w = fmt.get("width") or 0
        h = fmt.get("height") or 0
        area = w * h
        fid = fmt.get("format_id", "")
        fid_score = {"sb0": 4, "sb1": 3, "sb2": 2}.get(fid, 1 if fid.startswith("sb") else 0)
        return (area, fid_score)

    sb_candidates.sort(key=_tile_score, reverse=True)
    return sb_candidates[0]


def _calc_tile_duration(sb0: dict, fragments: list[dict], duration_sec: float, num_tiles: int) -> float:
    """Calculate the duration in seconds covered by a single storyboard tile."""
    base_frag_duration = fragments[0].get("duration") or sb0.get("fragment_duration")
    if not base_frag_duration or base_frag_duration <= 0:
        base_frag_duration = (duration_sec / len(fragments)) if (duration_sec and fragments) else 89.18
    tile_duration = base_frag_duration / num_tiles
    return tile_duration if tile_duration > 0 else 9.91


def _crop_and_save_tile(
    grid_img: Any,
    tile_idx: int,
    rows: int,
    columns: int,
    fixed_w: int | None,
    fixed_h: int | None,
    out_path: Path,
) -> bool:
    """Crop a single tile from storyboard grid image and save to disk."""
    w, h = grid_img.size
    tile_w = fixed_w or (w // columns)
    tile_h = fixed_h or (h // rows)
    r = tile_idx // columns
    c = tile_idx % columns
    if (r + 1) * tile_h > h:
        r = max(0, (h // tile_h) - 1)
    if (c + 1) * tile_w > w:
        c = max(0, (w // tile_w) - 1)
    try:
        tile = grid_img.crop((c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h))
        tile.save(out_path, "JPEG")
        return True
    except Exception as e:
        _logger.warning(f"Lỗi khi crop storyboard tile {tile_idx}: {e}")
        return False


def _get_download_fn():
    """Retrieve _download_grid_with_retry respecting module-level monkeypatches."""
    import sys
    mod = sys.modules.get("services.youtube.visual_extractor")
    if mod and hasattr(mod, "_download_grid_with_retry"):
        return getattr(mod, "_download_grid_with_retry")
    return _download_grid_with_retry


def _get_cached_grid(
    frag_idx: int,
    grid_url: str,
    grid_cache: dict[int, Any],
    tmp_dir: Path,
) -> Any | None:
    """Retrieve grid image from cache or download and cache it."""
    if frag_idx in grid_cache:
        return grid_cache[frag_idx]
    grid_path = tmp_dir / f"grid_{frag_idx}.jpg"
    download_fn = _get_download_fn()
    if not download_fn(grid_url, grid_path):
        _logger.warning(f"Không thể tải storyboard grid {frag_idx} sau nhiều lần thử.")
        return None
    try:
        grid_cache[frag_idx] = PILImage.open(grid_path)
        return grid_cache[frag_idx]
    except Exception as e:
        _logger.warning(f"Không thể mở ảnh storyboard grid {frag_idx}: {e}")
        return None


def _get_storyboard_frames(
    sb0: dict,
    tmp_dir: Path,
    target_timestamps: list[float],
    duration_sec: float = 600.0,
) -> list[Path]:
    """Download storyboard grids and crop target timestamps into static frame files."""
    fragments = sb0.get("fragments") or []
    if not fragments or PILImage is None:
        return []

    rows = sb0.get("rows") or 3
    columns = sb0.get("columns") or 3
    num_tiles = max(1, rows * columns)
    fixed_w, fixed_h = sb0.get("width"), sb0.get("height")
    tile_dur = _calc_tile_duration(sb0, fragments, duration_sec, num_tiles)
    max_tile = len(fragments) * num_tiles - 1
    grid_cache: dict[int, Any] = {}
    static_frames: list[Path] = []

    for i, ts in enumerate(target_timestamps):
        g_idx = max(0, min(int(ts / tile_dur), max_tile))
        frag_idx, tile_idx = g_idx // num_tiles, g_idx % num_tiles
        actual_ts = min(g_idx * tile_dur, duration_sec)
        grid_url = fragments[frag_idx].get("url")
        if not grid_url:
            continue

        grid_img = _get_cached_grid(frag_idx, grid_url, grid_cache, tmp_dir)
        if grid_img is None:
            continue

        out_path = tmp_dir / f"frame_static_{i:04d}_ts{int(actual_ts)}.jpg"
        if _crop_and_save_tile(grid_img, tile_idx, rows, columns, fixed_w, fixed_h, out_path):
            static_frames.append(out_path)

    return static_frames
