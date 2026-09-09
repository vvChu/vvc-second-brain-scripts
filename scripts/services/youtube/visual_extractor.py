"""VvC Second Brain — YouTube Visual Extractor.

Extract visual frames from YouTube videos.
Context-Aware Visual Judge and Two-Stage Hybrid Ingestion (v11.0).
"""

import logging
import urllib.parse
from pathlib import Path
import subprocess
import shutil
import os
import json
import re
import time

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

from core.config import cfg
from core.llm import call_llm
from core.llm.utils import http_session, encode_image

_logger = logging.getLogger("vvc.youtube")

# Safety cap cho số lượng key frames. LLM-as-Judge tự quyết số lượng
# thực tế dựa trên bản chất nội dung (2-3 cho đàm thoại, 5-8 cho học thuật).
_MAX_KEY_FRAMES = 10

# --- Smart Frame Selection Helpers ---

def _compute_frame_hash(img_path: Path, size: int = 8) -> int:
    """Compute average perceptual hash using pure PIL (no external deps).

    Resizes the image to a tiny grayscale grid and compares each pixel
    to the mean — producing a 64-bit fingerprint that is robust to
    minor visual differences (compression artifacts, slight camera moves).
    """
    try:
        img = PILImage.open(img_path).convert("L").resize(
            (size, size), PILImage.Resampling.LANCZOS
        )
    except (FileNotFoundError, OSError):
        return 0
    pixels = list(img.getdata())
    if not pixels:
        return 0
    avg = sum(pixels) / len(pixels)
    return sum(1 << i for i, px in enumerate(pixels) if px > avg)


def _dedup_frames(frames: list[Path], threshold: int = 2) -> list[Path]:
    """Remove near-duplicate frames using all-pairs perceptual hash comparison.

    Args:
        frames: List of frame file paths.
        threshold: Minimum hamming distance to keep a frame (0-64).
            Lower = stricter dedup. Default 2 works well for slides.

    Returns:
        Deduplicated list of frames preserving ordering.
    """
    if len(frames) <= 1 or PILImage is None:
        return frames
    # Guard: nếu file đầu tiên không tồn tại (mock env), skip dedup
    if not frames[0].exists():
        return frames
        
    unique = []
    hashes = []
    
    for f in frames:
        curr_hash = _compute_frame_hash(f)
        if curr_hash == 0:
            unique.append(f)
            hashes.append(curr_hash)
            continue
            
        is_dup = False
        for h in hashes:
            if h == 0:
                continue
            dist = bin(curr_hash ^ h).count("1")
            if dist < threshold:
                is_dup = True
                break
                
        if not is_dup:
            unique.append(f)
            hashes.append(curr_hash)
            
    return unique


def _get_heatmap_peaks(heatmap: list[dict], duration_sec: float, max_peaks: int = 5) -> list[float]:
    """Parse YouTube heatmap and find the top K timestamps of highest user engagement."""
    if not heatmap:
        return []
        
    valid_entries = []
    for entry in heatmap:
        start = entry.get("start_time", 0.0)
        end = entry.get("end_time", 0.0)
        val = entry.get("value")
        if val is not None:
            mid = start + (end - start) / 2.0
            if 0.0 <= mid <= duration_sec:
                valid_entries.append((val, mid))
                
    # Sắp xếp giảm dần theo mức độ tương tác (value)
    valid_entries.sort(key=lambda x: x[0], reverse=True)
    
    # Chọn top K peaks tránh bị trùng lặp quá sát nhau (trong khoảng 10 giây)
    peaks = []
    for val, ts in valid_entries:
        if not any(abs(ts - p) < 10.0 for p in peaks):
            peaks.append(ts)
            if len(peaks) >= max_peaks:
                break
                
    return sorted(peaks)


def _get_target_timestamps(duration_sec: float, chapters: list[dict] = None, heatmap: list[dict] = None) -> list[float]:
    """Calculate adaptive target timestamps for chapter-aware multi-sampling and heatmap peaks.

    Dynamic frame budget according to duration_sec:
    - Short (< 15m / 900s): ~15 targets (saves Vision API tokens).
    - Medium (15-60m / 900-3600s): ~25 targets (standard dense stage).
    - Long (> 60m / 3600s): ~35-40 targets (ensures lecture slide coverage).
    """
    if duration_sec <= 0:
        return []

    # Determine base budget according to duration_sec
    if duration_sec < 900:
        target_budget = 15
    elif duration_sec <= 3600:
        target_budget = 25
    else:
        target_budget = 36  # In range 35-40

    timestamps = []
    if chapters:
        num_chapters = len(chapters)
        if duration_sec > 3600:
            # Video dài (> 60m): phân bổ 35-40 targets phủ khắp các chương (kể cả khi chỉ có 1-3 chương)
            if num_chapters == 1:
                p_factors = [round((i + 1) / 37, 4) for i in range(36)]
            elif num_chapters == 2:
                p_factors = [round((i + 1) / 19, 4) for i in range(18)]
            elif num_chapters == 3:
                p_factors = [round((i + 1) / 13, 4) for i in range(12)]
            elif num_chapters <= 4:
                p_factors = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
            elif num_chapters <= 6:
                p_factors = [round((i + 1) / 7, 4) for i in range(6)]
            elif num_chapters <= 8:
                p_factors = [0.15, 0.30, 0.45, 0.60, 0.75, 0.90]
            elif num_chapters <= 14:
                p_factors = [0.20, 0.40, 0.60, 0.80, 0.95]
            else:
                p_factors = [0.33, 0.66, 0.95]
        else:
            # Video vừa và ngắn: mặc định hiện tại, bổ sung budget cho video chỉ có 1 chương duy nhất
            if num_chapters == 1:
                p_factors = [round((i + 1) / (target_budget + 1), 4) for i in range(target_budget)]
            elif num_chapters <= 3:
                p_factors = [0.15, 0.35, 0.55, 0.75, 0.95]
            elif num_chapters <= 6:
                p_factors = [0.20, 0.40, 0.60, 0.80, 0.95]
            elif num_chapters <= 12:
                p_factors = [0.25, 0.50, 0.75, 0.95]
            else:
                p_factors = [0.33, 0.66, 0.95]

        for ch in chapters:
            start = ch.get("start_time", 0.0)
            end = ch.get("end_time", duration_sec)
            if start < 0:
                start = 0.0
            if end > duration_sec:
                end = duration_sec
            if end <= start:
                continue

            for p in p_factors:
                ts = start + (end - start) * p
                if 0.0 <= ts <= duration_sec:
                    timestamps.append(ts)

    # Fallback nếu không có chapters hoặc chapters bị rỗng/lỗi không sinh ra timestamps
    if not timestamps:
        N = target_budget
        step = duration_sec / (N + 1)
        for i in range(1, N + 1):
            ts = i * step
            if 0.0 <= ts <= duration_sec:
                timestamps.append(ts)
                
    # Tích hợp Heatmap peaks (tối đa 10 peaks cho v11.0)
    if heatmap:
        peaks = _get_heatmap_peaks(heatmap, duration_sec, max_peaks=10)
        _logger.info(f"Phát hiện {len(peaks)} điểm Viewer Heatmap cực trị: {[round(p, 1) for p in peaks]}")
        timestamps.extend(peaks)
                
    # Sắp xếp và lọc các mốc thời gian quá sát nhau (dưới 2 giây)
    timestamps = sorted(list(set(timestamps)))
    filtered_ts = []
    for ts in timestamps:
        if not filtered_ts or ts - filtered_ts[-1] >= 2.0:
            filtered_ts.append(ts)
            
    return filtered_ts


def _download_grid_with_retry(url: str, dest_path: Path, max_retries: int = 3, timeout: int = 10) -> bool:
    """Tải storyboard grid với cơ chế Exponential Backoff và Timeout."""
    import urllib.request
    import urllib.error
    import time
    
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


def _get_storyboard_frames(sb0: dict, tmp_dir: Path, target_timestamps: list[float], duration_sec: float = 600.0) -> list[Path]:
    """Download storyboard grids and crop target timestamps into static frame files.
    
    Uses invariant tile dimensions and fragment 0 duration to calculate accurate
    timestamps, preventing distortion on partial last fragments and eliminating phase shift.
    """
    fragments = sb0.get("fragments") or []
    if not fragments or PILImage is None:
        return []

    rows = sb0.get("rows") or 3
    columns = sb0.get("columns") or 3
    num_tiles = rows * columns
    if num_tiles <= 0:
        num_tiles = 9

    fixed_tile_w = sb0.get("width")
    fixed_tile_h = sb0.get("height")

    base_frag_duration = fragments[0].get("duration") or sb0.get("fragment_duration")
    if not base_frag_duration or base_frag_duration <= 0:
        if duration_sec and len(fragments) > 0:
            base_frag_duration = duration_sec / len(fragments)
        else:
            base_frag_duration = 89.18

    tile_duration = base_frag_duration / num_tiles
    if tile_duration <= 0:
        tile_duration = 9.91

    max_global_tile = len(fragments) * num_tiles - 1
    grid_cache = {}
    static_frames = []

    for i, ts in enumerate(target_timestamps):
        global_tile_idx = int(ts / tile_duration)
        if global_tile_idx > max_global_tile:
            global_tile_idx = max_global_tile
        if global_tile_idx < 0:
            global_tile_idx = 0

        frag_idx = global_tile_idx // num_tiles
        tile_idx = global_tile_idx % num_tiles

        actual_ts = min(global_tile_idx * tile_duration, duration_sec)

        grid_url = fragments[frag_idx].get("url")
        if not grid_url:
            continue

        if frag_idx not in grid_cache:
            grid_path = tmp_dir / f"grid_{frag_idx}.jpg"
            if _download_grid_with_retry(grid_url, grid_path):
                try:
                    grid_cache[frag_idx] = PILImage.open(grid_path)
                except Exception as e:
                    _logger.warning(f"Không thể mở ảnh storyboard grid {frag_idx}: {e}")
                    continue
            else:
                _logger.warning(f"Không thể tải storyboard grid {frag_idx} sau nhiều lần thử.")
                continue

        grid_img = grid_cache[frag_idx]
        w, h = grid_img.size

        tile_w = fixed_tile_w or (w // columns)
        tile_h = fixed_tile_h or (h // rows)
        if not fixed_tile_w:
            fixed_tile_w = tile_w
        if not fixed_tile_h:
            fixed_tile_h = tile_h

        r = tile_idx // columns
        c = tile_idx % columns

        # Bound check against partial fragment grids to prevent distorted aspect ratios
        if (r + 1) * tile_h > h:
            r = max(0, (h // tile_h) - 1)
        if (c + 1) * tile_w > w:
            c = max(0, (w // tile_w) - 1)

        box = (c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)

        try:
            tile = grid_img.crop(box)
            out_path = tmp_dir / f"frame_static_{i:04d}_ts{int(actual_ts)}.jpg"
            tile.save(out_path, "JPEG")
            static_frames.append(out_path)
        except Exception as e:
            _logger.warning(f"Lỗi khi crop storyboard tile {tile_idx} từ grid {frag_idx}: {e}")

    return static_frames


def _find_ffmpeg_bin() -> str | None:
    """Find the system path to the FFmpeg executable."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return ffmpeg_bin
        
    fallbacks = [
        Path("C:\\ffmpeg\\bin\\ffmpeg.exe"),
        Path("C:\\Users\\chuvu\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-8.1.1-full_build\\bin\\ffmpeg.exe"),
    ]
    pkg_dir = Path("C:\\Users\\chuvu\\AppData\\Local\\Microsoft\\WinGet\\Packages")
    if pkg_dir.exists():
        try:
            for fb in pkg_dir.glob("**/ffmpeg.exe"):
                fallbacks.append(fb)
        except Exception:
            pass
            
    for fb in fallbacks:
        if fb.exists():
            return str(fb)
            
    return None


def _get_high_res_stream_url(info_dict: dict) -> tuple[str | None, str]:
    """Find the best high-res stream URL (720p or 1080p, prefer mp4/avc1) from yt-dlp info_dict.
    
    Returns:
        tuple: (stream_url, user_agent)
    """
    if not info_dict:
        return None, "Mozilla/5.0"
        
    formats = info_dict.get("formats", [])
    if not formats:
        return None, "Mozilla/5.0"
        
    best_url = None
    best_score = -1
    best_ua = "Mozilla/5.0"
    
    for fmt in formats:
        url = fmt.get("url")
        if not url or not url.startswith("http"):
            continue
            
        vcodec = fmt.get("vcodec", "none")
        if vcodec == "none":
            continue
            
        height = fmt.get("height") or 0
        ext = fmt.get("ext", "")
        
        score = 0
        if height == 720:
            score += 100
        elif height == 1080:
            score += 90
        elif height == 480:
            score += 50
        elif height > 1080:
            score += 40
        elif 0 < height < 480:
            score += 10
            
        if ext == "mp4":
            score += 10
        if "avc1" in vcodec:
            score += 5
            
        if score > best_score:
            best_score = score
            best_url = url
            best_ua = fmt.get("http_headers", {}).get("User-Agent") or info_dict.get("http_headers", {}).get("User-Agent") or "Mozilla/5.0"
            
    return best_url, best_ua


def _select_best_storyboard_format(formats: list[dict]) -> dict | None:
    """Select the storyboard format with the largest tile area (width * height).
    
    Prioritizes sb0 (320x180 = 57,600 px²/tile) over lower resolution boards
    like sb1 (160x90 = 14,400 px²) and sb2 (80x45 = 3,600 px²).
    """
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
        fid_score = 0
        if fid == "sb0":
            fid_score = 4
        elif fid == "sb1":
            fid_score = 3
        elif fid == "sb2":
            fid_score = 2
        elif fid.startswith("sb"):
            fid_score = 1
        return (area, fid_score)

    sb_candidates.sort(key=_tile_score, reverse=True)
    return sb_candidates[0]


def _get_video_download_ydl_opts(out_tmpl: str) -> dict:
    """yt-dlp options specifically for high-quality video extraction.
    
    CRITICAL: Does NOT use mobile player_client (android/ios/mweb) from transcript
    options because mobile emulation drops 720p DASH video streams on YouTube.
    Supports both progressive format 18 (640x360) and DASH 720p streams.
    """
    return {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/best[height<=720]/b/18/bestvideo/best",
        "outtmpl": out_tmpl,
    }


class KeyFramesParseResult(tuple):
    """3-tuple subclass preserving (cleaned_summary, key_frame_indices, key_frame_alts)
    while exposing explicit parsing status flags."""
    is_explicit_empty: bool = False
    parse_success: bool = False
    header_present: bool = False

    def __new__(
        cls,
        cleaned_summary: str,
        key_frame_indices: list[int],
        key_frame_alts: dict[int, str],
        *,
        is_explicit_empty: bool = False,
        parse_success: bool = False,
        header_present: bool = False,
    ):
        obj = super().__new__(cls, (cleaned_summary, key_frame_indices, key_frame_alts))
        obj.is_explicit_empty = is_explicit_empty
        obj.parse_success = parse_success
        obj.header_present = header_present
        return obj


def _parse_key_frames_response(summary: str) -> KeyFramesParseResult:
    """Parse KEY_FRAMES from LLM-as-Judge output.
    
    Supports both v12.0 format:
        KEY_FRAMES: [{"index": 1, "alt": "..."}, ...]
    and backward-compatible integer list:
        KEY_FRAMES: [1, 2, 3]
        
    Returns:
        KeyFramesParseResult (3-tuple): (cleaned_summary, list_of_indices, dict_of_alts)
        with flags: .is_explicit_empty, .parse_success, .header_present.
    """
    key_frame_indices: list[int] = []
    key_frame_alts: dict[int, str] = {}
    cleaned_summary = summary
    
    matches = list(re.finditer(r"(?:\*\*|__)?KEY_FRAMES(?:\*\*|__)?\s*:(?:\*\*|__)?", summary, flags=re.IGNORECASE))
    if not matches:
        return KeyFramesParseResult(
            cleaned_summary, key_frame_indices, key_frame_alts,
            is_explicit_empty=False, parse_success=False, header_present=False
        )
        
    match = matches[-1]
    cleaned_summary = summary[:match.start()].strip()
    json_part = summary[match.end():].strip()

    # Strip markdown code fences if output is wrapped
    json_part = re.sub(r"^```(?:json)?\s*", "", json_part, flags=re.IGNORECASE)
    json_part = re.sub(r"\s*```$", "", json_part)

    # Strategy 1: Greedy match from outermost '[' to last ']'
    # (prevents premature cutoffs when alt text contains square brackets)
    raw_list = None
    greedy_match = re.search(r"\[[\s\S]*\]", json_part)
    if greedy_match:
        try:
            parsed = json.loads(greedy_match.group(0))
            if isinstance(parsed, list):
                raw_list = parsed
        except Exception:
            pass

    # Strategy 2: Non-greedy match if greedy parsing failed
    if raw_list is None:
        lazy_match = re.search(r"\[[\s\S]*?\]", json_part)
        if lazy_match:
            try:
                parsed = json.loads(lazy_match.group(0))
                if isinstance(parsed, list):
                    raw_list = parsed
            except Exception:
                pass

    if not isinstance(raw_list, list):
        _logger.warning("Không thể parse JSON KEY_FRAMES từ response.")
        return KeyFramesParseResult(
            cleaned_summary, key_frame_indices, key_frame_alts,
            is_explicit_empty=False, parse_success=False, header_present=True
        )

    if len(raw_list) == 0:
        return KeyFramesParseResult(
            cleaned_summary, key_frame_indices, key_frame_alts,
            is_explicit_empty=True, parse_success=True, header_present=True
        )

    seen_indices = set()
    for item in raw_list:
        if isinstance(item, dict):
            idx = item.get("index")
            alt = str(item.get("alt", "")).strip()
            if idx is not None:
                try:
                    idx_int = int(idx)
                    if idx_int not in seen_indices:
                        seen_indices.add(idx_int)
                        key_frame_indices.append(idx_int)
                    if alt and idx_int not in key_frame_alts:
                        key_frame_alts[idx_int] = alt
                except (ValueError, TypeError):
                    pass
        elif isinstance(item, (int, str)):
            try:
                idx_int = int(item)
                if idx_int not in seen_indices:
                    seen_indices.add(idx_int)
                    key_frame_indices.append(idx_int)
            except (ValueError, TypeError):
                pass
        
    return KeyFramesParseResult(
        cleaned_summary, key_frame_indices, key_frame_alts,
        is_explicit_empty=False, parse_success=True, header_present=True
    )


def _resolve_key_frames_with_fallback(
    summary: str,
    total_frames: int,
) -> tuple[str, list[int], dict[int, str]]:
    """Phân giải KEY_FRAMES từ phản hồi của model, phân biệt rõ quyết định từ chối và lỗi format / parse thất bại.
    
    - Trường hợp 1 (Từ chối có chủ ý): Phản hồi chứa 'KEY_FRAMES:' và danh sách parse được là rỗng []
      (video 100% talking heads/podcast không có slide/sơ đồ). Tôn trọng quyết định, key_frame_indices = [].
    - Trường hợp 2 (Chọn frames thành công): Phản hồi chứa 'KEY_FRAMES:' và parse được danh sách indices hợp lệ.
    - Trường hợp 3 (Lỗi format / Parse thất bại): Chuỗi 'KEY_FRAMES:' hoàn toàn không xuất hiện HOẶC
      parse JSON thất bại / không trích xuất được frame hợp lệ nào -> Kích hoạt fallback tự động chọn frame (đầu, giữa, cuối).
    """
    parse_result = _parse_key_frames_response(summary)
    cleaned_summary, key_frame_indices, key_frame_alts = parse_result
    
    if parse_result.is_explicit_empty:
        _logger.info("Model từ chối chọn frame có chủ ý (KEY_FRAMES: []). Tôn trọng quyết định, không trích xuất frame.")
        return cleaned_summary, [], {}
        
    if key_frame_indices:
        return cleaned_summary, key_frame_indices, key_frame_alts
        
    # Trường hợp 3: Header thiếu hoặc parse thất bại
    if total_frames > 0:
        if not parse_result.header_present:
            _logger.warning("Không tìm thấy chuỗi KEY_FRAMES: trong mô tả của model (lỗi format). Áp dụng fallback tự động chọn frame...")
        else:
            _logger.warning("Phát hiện chuỗi KEY_FRAMES: nhưng không parse được frame hợp lệ (parse thất bại). Áp dụng fallback tự động chọn frame...")
            
        if total_frames >= 3:
            key_frame_indices = [0, total_frames // 2, total_frames - 1]
        else:
            key_frame_indices = list(range(total_frames))
            
    return cleaned_summary, key_frame_indices, key_frame_alts


def _generate_semantic_alt_texts(visual_summary: str, saved_frames: list[str]) -> dict[str, str]:
    """Gọi LLM cực nhanh để ánh xạ và tạo alt-text giàu ngữ nghĩa cho từng frame ảnh dựa trên Visual Summary."""
    if not saved_frames:
        return {}
    
    prompt = (
        "Bạn là chuyên gia phân tích đa phương thức. Dưới đây là bản tóm tắt nội dung trực quan (Visual Summary) của một video học thuật, "
        "và danh sách các tệp tin ảnh slide đã được trích xuất (có chứa mốc thời gian ts<seconds> trong tên file).\n\n"
        "NHIỆM VỤ CỦA BẠN:\n"
        "Hãy dựa vào bản tóm tắt dưới đây và mốc thời gian của từng file ảnh để viết một mô tả ngắn gọn (alt text) bằng tiếng Việt khoảng 10-20 từ cho mỗi ảnh. "
        "Mô tả phải tập trung vào nội dung học thuật trực quan xuất hiện trong slide đó (ví dụ: 'Sơ đồ kiến trúc Deep Module', 'Bảng thuật ngữ chuyên ngành', 'Đồ thị phân tích hiệu suất').\n\n"
        f"VISUAL SUMMARY:\n---\n{visual_summary}\n---\n\n"
        f"DANH SÁCH FILE ẢNH:\n{saved_frames}\n\n"
        "BẮT BUỘC TRẢ VỀ định dạng JSON object dạng:\n"
        "{\n"
        "  \"tên_file_1.webp\": \"mô tả slide 1 bằng tiếng Việt\",\n"
        "  \"tên_file_2.webp\": \"mô tả slide 2 bằng tiếng Việt\"\n"
        "}\n"
        "Chỉ trả về chuỗi JSON hợp lệ, không giải thích gì thêm, không bọc trong code block markdown."
    )
    
    try:
        from core.llm import call_llm
        res = call_llm(prompt, task="correction")
        if res:
            match = re.search(r"\{.*\}", res, re.DOTALL)
            if match:
                res_str = match.group(0)
            else:
                res_str = res
            return json.loads(res_str)
    except Exception as e:
        _logger.warning(f"Không thể tạo semantic alt-text JIT: {e}")
    return {}



def extract_video_visuals(url: str, transcript_text: str = None, info_dict: dict = None) -> str:
    """Trích xuất hình ảnh trực quan từ video YouTube sử dụng Context-Aware Visual Judge & Two-Stage Hybrid Ingestion (v11.0)
    hoặc tự động fallback về tải video thô + FFmpeg hybrid (v9.1).
    """
    tmp_dir = Path(__file__).parent.parent.parent / "scratch" / "_video_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    video_path = None
    extracted_frames = []
    duration_sec = 600
    chapters = []
    heatmap = []
    video_id = None
    local_video_path = None
    
    try:
        import yt_dlp
        
        # Lấy video_id để làm tên file ổn định
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path[1:]
        elif parsed.hostname in ("youtube.com", "www.youtube.com"):
            if parsed.path == "/watch":
                qs = urllib.parse.parse_qs(parsed.query)
                video_id = qs.get("v", [None])[0]
            elif parsed.path.startswith(("/embed/", "/v/", "/live/")):
                video_id = parsed.path.split("/")[2]
                
        if not video_id:
            _logger.warning(f"Không thể phân tích video_id từ URL: {url}")
            return ""
            
        # 1. Phân tích JIT siêu dữ liệu nếu chưa được truyền vào
        if not info_dict:
            _logger.info(f"Đang phân tích siêu dữ liệu JIT cho: {url}")
            from services.youtube.transcript import get_base_ydl_opts
            with yt_dlp.YoutubeDL(get_base_ydl_opts()) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                
        if not info_dict:
            return ""
            
        duration_sec = info_dict.get("duration") or 600
        chapters = info_dict.get("chapters") or []
        heatmap = info_dict.get("heatmap") or []
        
        # 1. Tìm cấu hình Storyboard có diện tích tile lớn nhất (ưu tiên sb0: 320x180 px)
        sb0 = _select_best_storyboard_format(info_dict.get("formats", []))
        if sb0:
            w = sb0.get("width") or 0
            h = sb0.get("height") or 0
            _logger.info(f"Đã chọn cấu hình Storyboard: {sb0.get('format_id')} ({w}x{h} px/tile)")

        # 2. Thực hiện trích xuất theo Pipeline v12.0 (Serverless coarse) hoặc Fallback v9.1
        target_timestamps = _get_target_timestamps(duration_sec, chapters, heatmap)
        
        frame_metadata = {}
        if sb0:
            _logger.info("Step 3: Two-Stage Hybrid Ingestion (Stage 1 Storyboard coarse sampling)...")
            extracted_frames = _get_storyboard_frames(sb0, tmp_dir, target_timestamps, duration_sec)
            extraction_method = "storyboard_slice"
            _logger.info(f"Đã trích xuất {len(extracted_frames)} coarse frames từ storyboards CDN.")
            for i, p in enumerate(extracted_frames):
                ts_match = re.search(r"_ts(\d+)", p.name)
                frame_ts = float(ts_match.group(1)) if ts_match else (target_timestamps[i] if i < len(target_timestamps) else 0.0)
                frame_metadata[p] = {
                    "timestamp": frame_ts,
                    "original_index": i
                }
        else:
            _logger.info("Không tìm thấy storyboard CDN. Khởi động fallback tải video + hybrid FFmpeg (v9.1)...")
            
            # Tải video chất lượng thấp
            out_tmpl = str(tmp_dir / f"{video_id}.%(ext)s")
            ydl_opts = _get_video_download_ydl_opts(out_tmpl)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                
            for f in tmp_dir.glob(f"{video_id}.*"):
                if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
                    video_path = f
                    break
                    
            if not video_path or not video_path.exists():
                _logger.warning(f"Không tải được video fallback cho URL: {url}")
                return ""
                
            try:
                sz = video_path.stat().st_size / 1024 / 1024
                sz_str = f" ({sz:.2f} MB)"
            except Exception:
                sz_str = ""
            _logger.info(f"Đã tải xong video fallback: {video_path.name}{sz_str}")
            
            # Khởi tạo ffmpeg
            ffmpeg_bin = _find_ffmpeg_bin()
            if not ffmpeg_bin:
                _logger.error("Không tìm thấy ffmpeg trên hệ thống.")
                return ""
                
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _run_kwargs = dict(
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                startupinfo=startupinfo, text=True, timeout=180
            )
            
            # Step 3A: Chapter-aware static multi-sampling
            _logger.info("Step 3A: Chapter-aware adaptive static sampling (Fallback)...")
            _logger.info(f"Target timestamps ({len(target_timestamps)}): {[round(ts, 1) for ts in target_timestamps]}")
            
            static_frames = []
            for i, ts in enumerate(target_timestamps):
                out_path = tmp_dir / f"frame_static_{i:04d}.jpg"
                cmd_static = [
                    ffmpeg_bin, "-y",
                    "-ss", str(round(ts, 2)),
                    "-i", str(video_path),
                    "-vframes", "1",
                    str(out_path)
                ]
                res_static = subprocess.run(cmd_static, **_run_kwargs)
                if res_static.returncode == 0 and out_path.exists():
                    static_frames.append(out_path)
                    frame_metadata[out_path] = {
                        "timestamp": ts,
                        "original_index": i
                    }
                    
            # Step 3B: Scene Change Detection (Dynamic)
            _logger.info("Step 3B: Dynamic Scene Change Detection (threshold 0.3) (Fallback)...")
            scene_pattern = tmp_dir / "frame_scene_%04d.jpg"
            cmd_scene = [
                ffmpeg_bin, "-y",
                "-i", str(video_path),
                "-vf", "select=gt(scene\\,0.3)",
                "-vsync", "vfr",
                str(scene_pattern)
            ]
            res_scene = subprocess.run(cmd_scene, **_run_kwargs)
            dynamic_frames = sorted(list(tmp_dir.glob("frame_scene_*.jpg")))
            for i, p in enumerate(dynamic_frames):
                estimated_ts = (i / max(1, len(dynamic_frames))) * duration_sec
                frame_metadata[p] = {
                    "timestamp": estimated_ts,
                    "original_index": len(target_timestamps) + i
                }
            
            extracted_frames = static_frames + dynamic_frames
            extraction_method = "hybrid_chapters_scene"
            
            if not extracted_frames:
                _logger.warning("Không trích xuất được frame nào. Fallback về uniform FPS...")
                frame_pattern = tmp_dir / "frame_fallback_%04d.jpg"
                cmd_uniform = [
                    ffmpeg_bin, "-y",
                    "-i", str(video_path),
                    "-vf", "fps=1/10",
                    "-vsync", "vfr",
                    str(frame_pattern)
                ]
                res_fallback = subprocess.run(cmd_uniform, **_run_kwargs)
                if res_fallback.returncode != 0:
                    _logger.error("FFmpeg fallback thất bại.")
                    return ""
                extracted_frames = sorted(list(tmp_dir.glob("frame_fallback_*.jpg")))
                for i, p in enumerate(extracted_frames):
                    uniform_ts = (i / max(1, len(extracted_frames))) * duration_sec
                    frame_metadata[p] = {
                        "timestamp": uniform_ts,
                        "original_index": i
                    }
                extraction_method = "fallback_uniform_fps"
                
            _logger.info(f"Tổng cộng trước khi dedup: {len(extracted_frames)} frames (Static: {len(static_frames)}, Dynamic: {len(dynamic_frames)}) ({extraction_method})")
            
        # ── Phase 2: Perceptual Hash Deduplication ──
        if PILImage is not None and len(extracted_frames) > 1:
            before_dedup = len(extracted_frames)
            extracted_frames = _dedup_frames(extracted_frames)
            removed = before_dedup - len(extracted_frames)
            if removed > 0:
                _logger.info(
                    f"Phase 2 Dedup: {before_dedup} → {len(extracted_frames)} "
                    f"(loại {removed} frame trùng lặp)"
                )
                
        if not extracted_frames:
            _logger.warning("Không trích xuất được frame nào.")
            return ""
            
        _logger.info(f"Gửi toàn bộ {len(extracted_frames)} frames lên LLM-as-Judge với ngữ cảnh âm thanh...")
            
        # 4. Chuẩn bị tin nhắn gửi Gateway với Context-Aware Judge
        prompt_text = (
            "Bạn là một LLM-as-Judge chuyên nghiệp, chịu trách nhiệm phân tích các khung hình của một video bài giảng/học thuật để lọc ra các khung hình có giá trị tri thức trực quan cao nhất.\n\n"
            "NHIỆM VỤ CỦA BẠN:\n"
            "1. Phân tích sự tiến triển trực quan qua các khung hình được cung cấp (đã được đánh chỉ số 0, 1, 2... theo thứ tự thời gian).\n"
            "2. Đọc và đối chiếu chặt chẽ với phần AUDIO TRANSCRIPT CONTEXT bên dưới để hiểu nội dung học thuật được thảo luận tại thời điểm tương ứng.\n"
            "3. Viết một bản tóm tắt nội dung trực quan (Visual Slide Summary) bằng TIẾNG VIỆT chi tiết, khoa học, tóm lược đầy đủ các sơ đồ, công thức, mã nguồn hoặc tiêu đề slide xuất hiện trong ảnh. Không được viết ad-hoc kiểu 'ở khung hình 1', hãy diễn giải mượt mà như một báo cáo học thuật chuyên sâu.\n"
            "4. BẮT BUỘC lọc KEY_FRAMES theo nguyên tắc khắt khe bên dưới để tránh đưa ảnh rác vào Zettelkasten.\n\n"
            "⚠️ QUY TẮC CẤM (REJECTION RULES) - BẮT BUỘC TUÂN THỦ:\n"
            "- CẤM TUYỆT ĐỐI chọn các khung hình 'Talking Head' (chân dung diễn giả đứng nói trước máy quay, cận cảnh khuôn mặt) mà không có slide chữ, biểu đồ, mã nguồn hay sơ đồ hiển thị đi kèm. Cho dù lời thoại (transcript) tại giây đó có hay đến mấy, nếu hình ảnh chỉ là mặt người nói -> KHÔNG ĐƯỢC CHỌN.\n"
            "- LƯU Ý ĐẶC BIỆT: Các khung hình ghép (split-screen, picture-in-picture, hoặc slide lớn có ghép mặt nhỏ diễn giả ở góc) vẫn ĐƯỢC CHẤP NHẬN và vô cùng giá trị. Chỉ từ chối khi khung hình CHỈ có duy nhất khuôn mặt người nói phóng to mà không có bất kỳ thông tin slide học thuật nào.\n"
            "- CẤM chọn các khung hình chứa nút kêu gọi 'SUBSCRIBE' (Đăng ký kênh), nút Like, intro, outro, logo chuyển cảnh, hoặc hình ảnh phong cảnh chung chung không mang tính học thuật cô đọng trực quan.\n"
            "- CHỈ CHẤP NHẬN các khung hình là phương tiện truyền tải thông tin trực quan độc lập và rõ ràng: slide bài giảng đọc được chữ, sơ đồ kiến trúc hệ thống, sơ đồ tư duy (mindmap), bảng so sánh số liệu, mã nguồn (code snippet) thực tế, hoặc công thức toán học.\n\n"
            "Ở DÒNG CUỐI CÙNG của câu trả lời, xuất ra chính xác định dạng JSON:\n"
            "KEY_FRAMES: [{\"index\": <index>, \"alt\": \"<mô tả ngắn 10-20 từ về slide/sơ đồ bằng tiếng Việt>\"}, ...]\n"
            "trong đó chọn ra các chỉ số index (0-indexed của ảnh đầu vào) kèm mô tả alt-text tương ứng. Nếu không có khung hình nào chứa sơ đồ/slide trực quan giá trị học thuật thực sự, hãy xuất ra: KEY_FRAMES: []\n\n"
        )
        if transcript_text:
            prompt_text += f"=== [AUDIO TRANSCRIPT CONTEXT] ===\n{transcript_text}\n==================================\n\n"
            
        content = [
            {
                "type": "text",
                "text": prompt_text
            }
        ]
        
        for f_path in extracted_frames:
            b64_data = encode_image(f_path, max_pixels=768, quality=70)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_data}"
                }
            })
            
        # 5. Gọi Gateway qua http_session
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.gateway_api_key}"
        }
        
        payload = {
            "model": cfg.gateway_proxy_model or "gemini-3.5-flash-low",
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": 0.2,
            "max_tokens": 8192
        }
        
        _logger.info(f"Đang gửi {len(extracted_frames)} frames lên Gateway API ({payload['model']}) (Context-Aware)...")
        resp = http_session.post(
            f"{cfg.gateway_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=300
        )
        resp.raise_for_status()
        
        result_json = resp.json()
        summary = result_json["choices"][0]["message"]["content"]
        
        # Dọn dẹp instruction echoes
        summary = re.sub(
            r"(?i)Refining\s+the\s+Vietnamese\s+text\s+for\s+50%\s+reduced\s+verbosity\*\*:\s*Keep\s+it\s+extremely\s+punchy\s+and\s+direct\.\s*",
            "",
            summary
        )
        summary = summary.strip()
        
        _logger.info("Đã nhận được mô tả visual thành công từ Gateway API.")
        
        # 6. Parse KEY_FRAMES từ response (hỗ trợ cả JSON object list v12.0 lẫn int list v11.0)
        summary, key_frame_indices, key_frame_alts = _resolve_key_frames_with_fallback(
            summary, len(extracted_frames)
        )
                
        # 7. Stage 2 — High-Resolution Targeted FFmpeg Extraction
        saved_frames = []
        frame_to_alt = {}
        if key_frame_indices and PILImage is not None:
            assets_dir = cfg.assets_dir / "video_frames"
            assets_dir.mkdir(parents=True, exist_ok=True)
            
            ffmpeg_bin = _find_ffmpeg_bin()
            high_res_url, user_agent = _get_high_res_stream_url(info_dict)
            
            # Xác định danh sách tên file hợp lệ cho lượt chạy này
            keep_filenames = set()
            need_download = False
            for idx in key_frame_indices[:_MAX_KEY_FRAMES]:
                try:
                    idx = int(idx)
                    if 0 <= idx < len(extracted_frames):
                        frame_path = extracted_frames[idx]
                        metadata = frame_metadata.get(frame_path, {"timestamp": 0.0, "original_index": idx})
                        ts = metadata["timestamp"]
                        original_idx = metadata["original_index"]
                        ts_int = int(ts)
                        filename = f"yt_{video_id}_frame_{original_idx:03d}_ts{ts_int}.webp"
                        keep_filenames.add(filename)
                        if idx in key_frame_alts:
                            frame_to_alt[filename] = key_frame_alts[idx]
                        elif original_idx in key_frame_alts:
                            frame_to_alt[filename] = key_frame_alts[original_idx]
                        save_path = assets_dir / filename
                        if not save_path.exists():
                            need_download = True
                        else:
                            try:
                                with PILImage.open(save_path) as img_check:
                                    if max(img_check.size) < 480 or img_check.size == (320, 180) or img_check.size == (80, 45):
                                        need_download = True
                            except Exception:
                                need_download = True
                except Exception:
                    pass

            # Triển khai lớp 1: Tải video 720p/360p cục bộ bằng yt-dlp
            local_video_path = None
            if need_download:
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
                        fallback_opts = dict(ydl_opts)
                        fallback_opts["format"] = "18/best"
                        fallback_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
                        with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                            ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
                    except Exception as fallback_err:
                        _logger.warning(f"Không tải được video cục bộ bằng yt-dlp: {fallback_err}. Sẽ fallback sang storyboard frames.")
                        
                for f in tmp_dir.glob(f"{video_id}_temp.*"):
                    if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
                        local_video_path = f
                        try:
                            sz = f.stat().st_size / 1024 / 1024
                            sz_str = f" ({sz:.2f} MB)"
                        except Exception:
                            sz_str = ""
                        _logger.info(f"Tải video cục bộ thành công: {f.name}{sz_str}")
                        break

            # Trích xuất key frames đắt giá nhất (LLM tự quyết số lượng, safety cap: _MAX_KEY_FRAMES)
            for idx in key_frame_indices[:_MAX_KEY_FRAMES]:
                try:
                    idx = int(idx)
                    if 0 <= idx < len(extracted_frames):
                        frame_path = extracted_frames[idx]
                        metadata = frame_metadata.get(frame_path, {"timestamp": 0.0, "original_index": idx})
                        ts = metadata["timestamp"]
                        original_idx = metadata["original_index"]
                        ts_int = int(ts)
                        filename = f"yt_{video_id}_frame_{original_idx:03d}_ts{ts_int}.webp"
                        save_path = assets_dir / filename
                        
                        if save_path.exists():
                            try:
                                with PILImage.open(save_path) as img_check:
                                    if max(img_check.size) < 480 or img_check.size == (320, 180) or img_check.size == (80, 45):
                                        _logger.info(f"Phát hiện ảnh chất lượng thấp {filename} ({img_check.size}). Sẽ trích xuất lại cục bộ để nâng cấp lên HD...")
                                    else:
                                        if filename not in saved_frames:
                                            saved_frames.append(filename)
                                        continue
                            except Exception:
                                pass
                            
                        # Khởi tạo nguồn ảnh là frame thô storyboard của Stage 1
                        src_frame_path = frame_path
                        is_high_res = False
                        
                        # Thử trích xuất chất lượng cao
                        if sb0 and ffmpeg_bin:
                            high_res_jpg = tmp_dir / f"high_res_temp_{idx:03d}.jpg"
                            
                            startupinfo = None
                            if os.name == 'nt':
                                startupinfo = subprocess.STARTUPINFO()
                                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                                
                            # Lớp 1: Trích xuất từ video cục bộ (Offline Seek - Siêu nhanh & siêu ổn định)
                            if local_video_path and local_video_path.exists():
                                cmd_local = [
                                    ffmpeg_bin, "-y",
                                    "-ss", str(round(ts, 2)),
                                    "-i", str(local_video_path),
                                    "-vframes", "1",
                                    "-q:v", "2",
                                    str(high_res_jpg)
                                ]
                                _logger.info(f"Stage 2 (Lớp 1 - Local Seek): Trích xuất frame offline tại {round(ts,1)}s...")
                                try:
                                    res = subprocess.run(
                                        cmd_local, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        startupinfo=startupinfo, text=True, timeout=10
                                    )
                                    if res.returncode == 0 and high_res_jpg.exists():
                                        src_frame_path = high_res_jpg
                                        is_high_res = True
                                        _logger.info(f"Stage 2 trích xuất thành công frame cục bộ {idx} (HD).")
                                except Exception as local_exc:
                                    _logger.warning(f"Lớp 1 Local seek thất bại: {local_exc}. Fallback sang Lớp 3 (Storyboard).")
                                    
                            if not is_high_res:
                                _logger.warning(f"Stage 2 trích xuất chất lượng cao cục bộ thất bại cho frame {idx}. Lớp 3: Degrade về storyboard frame.")
                        
                        # Tiến hành nén WebP từ src_frame_path (hoặc high-res hoặc storyboard)
                        img = PILImage.open(src_frame_path)
                        img.thumbnail((1280, 1280), PILImage.Resampling.LANCZOS)
                        if img.mode not in ("RGB", "RGBA"):
                            img = img.convert("RGB")
                        img.save(save_path, "WEBP", quality=80)
                        
                        res_label = "HD" if is_high_res else "Storyboard"
                        _logger.info(f"Đã lưu frame {idx} ({res_label}) thành công thành WebP: {filename}")
                        if filename not in saved_frames:
                            saved_frames.append(filename)
                except Exception as e:
                    _logger.warning(f"Lỗi khi lưu frame video {idx}: {e}")
                    
        # Nhúng các IMG markers vào visual summary để brain_dump.py nhận diện và bảo toàn
        if saved_frames:
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
            summary = f"{summary}{img_section}"
            
        return summary
        
    except Exception as e:
        _logger.error(f"Lỗi khi trích xuất visual của video: {e}", exc_info=True)
        return ""
        
    finally:
        # Cleanup các file tạm
        if video_path and video_path.exists():
            try:
                video_path.unlink()
            except OSError:
                pass
        if local_video_path and local_video_path.exists():
            try:
                local_video_path.unlink()
                _logger.info(f"Đã dọn dẹp video tạm Stage 2: {local_video_path.name}")
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
