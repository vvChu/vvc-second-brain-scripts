"""VvC Second Brain — YouTube Transcript Extracter.

Extracts transcripts from YouTube via API, fallbacks to yt-dlp + whisper.
"""

import logging
import urllib.parse
from pathlib import Path
import subprocess
import shutil
import os
import json
import re

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

from core.config import cfg
from core.llm import call_audio
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


def _get_target_timestamps(duration_sec: float, chapters: list[dict], heatmap: list[dict] = None) -> list[float]:
    """Calculate adaptive target timestamps for chapter-aware multi-sampling and heatmap peaks.
    
    Upgraded in v11.0 to sample at a higher density (20-30 targets) to support Two-Stage visual reasoning.
    """
    timestamps = []
    if chapters:
        num_chapters = len(chapters)
        if num_chapters <= 3:
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
    else:
        # Fallback: Sample 20 evenly spaced points for v11.0 dense coarse stage
        N = 20
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


def _get_storyboard_frames(sb0: dict, tmp_dir: Path, target_timestamps: list[float]) -> list[Path]:
    """Download storyboard grids and crop target timestamps into static frame files.
    
    Bypasses decoding the raw video by extracting small frame tiles directly from
    Google CDN storyboard grid images in RAM.
    """
    fragments = sb0.get("fragments") or []
    if not fragments or PILImage is None:
        return []

    rows = sb0.get("rows", 3)
    columns = sb0.get("columns", 3)
    num_tiles = rows * columns
    fragment_duration = sb0.get("fragment_duration")
    if not fragment_duration:
        total_dur = sum(f.get("duration", 0) for f in fragments)
        fragment_duration = total_dur / len(fragments) if fragments else 88.62

    tile_duration = fragment_duration / num_tiles
    grid_cache = {}
    static_frames = []

    for i, ts in enumerate(target_timestamps):
        frag_idx = int(ts // fragment_duration)
        if frag_idx >= len(fragments):
            frag_idx = len(fragments) - 1
        if frag_idx < 0:
            frag_idx = 0

        tile_idx = int((ts % fragment_duration) // tile_duration)
        if tile_idx >= num_tiles:
            tile_idx = num_tiles - 1
        if tile_idx < 0:
            tile_idx = 0

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
        tile_w = w // columns
        tile_h = h // rows

        r = tile_idx // columns
        c = tile_idx % columns
        box = (c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)

        try:
            tile = grid_img.crop(box)
            out_path = tmp_dir / f"frame_static_{i:04d}.jpg"
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


def _download_audio_via_ytdlp(url: str, info_dict: dict = None) -> Path | None:
    """Download audio from URL using yt-dlp as fallback."""
    try:
        import yt_dlp
        
        # Save to 05 - Fleeting (scratch area)
        out_dir = cfg.concepts_dir.parent.parent / "05 - Fleeting"
        out_tmpl = str(out_dir / "%(id)s.%(ext)s")
        
        ydl_opts = {
            'format': 'worstaudio/bestaudio',
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Nếu đã có sẵn info_dict, ta vẫn gọi extract_info để download,
            # nhưng quá trình sẽ được tối ưu hơn
            info = ydl.extract_info(url, download=True)
            if not info:
                return None
            
            video_id = info.get('id', '')
            if not video_id:
                return None
                
            # If ffmpeg is missing, it keeps the original extension (.webm/.m4a)
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


def fetch_youtube_transcript(url: str, info_dict: dict = None) -> str:
    """Fetch transcript from YouTube URL, fallback to audio download + Whisper."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        parsed = urllib.parse.urlparse(url)
        video_id = None
        if parsed.hostname in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path[1:]
        elif parsed.hostname in ("youtube.com", "www.youtube.com"):
            if parsed.path == "/watch":
                qs = urllib.parse.parse_qs(parsed.query)
                video_id = qs.get("v", [None])[0]
            elif parsed.path.startswith(("/embed/", "/v/", "/live/")):
                video_id = parsed.path.split("/")[2]
                
        if not video_id:
            return ""
            
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        
        try:
            transcript = transcript_list.find_transcript(['vi', 'en'])
        except Exception:
            codes = [t.language_code for t in transcript_list]
            if not codes:
                return ""
            transcript = transcript_list.find_transcript(codes)
            
        data = transcript.fetch()
        formatted_lines = []
        current_group_start = None
        current_group_texts = []
        
        for segment in data:
            val_text = segment.text if hasattr(segment, 'text') else segment.get('text', '')
            val_text = val_text.strip()
            if not val_text:
                continue
                
            start = segment.start if hasattr(segment, 'start') else segment.get('start', 0.0)
            
            if current_group_start is None:
                current_group_start = start
                current_group_texts.append(val_text)
            elif start - current_group_start >= 30.0:
                minutes = int(current_group_start // 60)
                seconds = int(current_group_start % 60)
                time_str = f"[{minutes:02d}:{seconds:02d}]"
                formatted_lines.append(f"{time_str} " + " ".join(current_group_texts))
                current_group_start = start
                current_group_texts = [val_text]
            else:
                current_group_texts.append(val_text)
                
        if current_group_texts and current_group_start is not None:
            minutes = int(current_group_start // 60)
            seconds = int(current_group_start % 60)
            time_str = f"[{minutes:02d}:{seconds:02d}]"
            formatted_lines.append(f"{time_str} " + " ".join(current_group_texts))
            
        text = "\n\n".join(formatted_lines)
        return text
    except Exception as e:
        _logger.warning(f"YouTube transcript fetch failed: {e}")
        _logger.info(f"Fallback to yt-dlp + Whisper for URL: {url}")
        audio_path = _download_audio_via_ytdlp(url, info_dict=info_dict)
        if audio_path:
            try:
                text = call_audio(audio_path, model="audio-primary", language="vi")
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass
                return text
            except Exception as e:
                _logger.error(f"Audio transcription failed: {e}")
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass
        return ""


def extract_video_visuals(url: str, transcript_text: str = None, info_dict: dict = None) -> str:
    """Trích xuất hình ảnh trực quan từ video YouTube sử dụng Context-Aware Visual Judge & Two-Stage Hybrid Ingestion (v11.0)
    hoặc tự động fallback về tải video thô + FFmpeg hybrid (v9.1).
    """
    tmp_dir = Path(__file__).parent.parent / "scratch" / "_video_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    video_path = None
    extracted_frames = []
    duration_sec = 600
    chapters = []
    heatmap = []
    video_id = None
    
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
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                
        if not info_dict:
            return ""
            
        duration_sec = info_dict.get("duration") or 600
        chapters = info_dict.get("chapters") or []
        heatmap = info_dict.get("heatmap") or []
        
        # Tìm cấu hình Storyboard sb0 (hoặc sb1/sb2 làm fallback)
        sb0 = None
        for fmt in info_dict.get("formats", []):
            if fmt.get("format_id") == "sb0":
                sb0 = fmt
                break
        if not sb0:
            for fmt in info_dict.get("formats", []):
                if "storyboard" in fmt.get("format_note", "") or fmt.get("format_id", "").startswith("sb"):
                    sb0 = fmt
                    break
                    
        # 2. Thực hiện trích xuất theo Pipeline v11.0 (Serverless coarse) hoặc Fallback v9.1
        target_timestamps = _get_target_timestamps(duration_sec, chapters, heatmap)
        
        frame_metadata = {}
        if sb0:
            _logger.info("Step 3: Two-Stage Hybrid Ingestion (Stage 1 Storyboard coarse sampling)...")
            extracted_frames = _get_storyboard_frames(sb0, tmp_dir, target_timestamps)
            extraction_method = "storyboard_slice"
            _logger.info(f"Đã trích xuất {len(extracted_frames)} coarse frames từ storyboards CDN.")
            for i, p in enumerate(extracted_frames):
                frame_metadata[p] = {
                    "timestamp": target_timestamps[i] if i < len(target_timestamps) else 0.0,
                    "original_index": i
                }
        else:
            _logger.info("Không tìm thấy storyboard CDN. Khởi động fallback tải video + hybrid FFmpeg (v9.1)...")
            
            # Tải video chất lượng thấp
            out_tmpl = str(tmp_dir / f"{video_id}.%(ext)s")
            ydl_opts = {
                'format': 'bestvideo[height<=720][ext=mp4]/bestvideo[height<=480]/worstvideo',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
            }
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
            "Ở DÒNG CUỐI CÙNG của câu trả lời, xuất ra chính xác định dạng:\n"
            "KEY_FRAMES: [index1, index2, ...]\n"
            "trong đó chọn ra các chỉ số index (0-indexed của ảnh đầu vào) thỏa mãn quy tắc trên. Nếu không có khung hình nào chứa sơ đồ/slide trực quan giá trị học thuật thực sự, hãy xuất ra: KEY_FRAMES: []\n\n"
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
        
        # 6. Parse KEY_FRAMES từ response
        key_frame_indices = []
        if "KEY_FRAMES:" in summary:
            parts = summary.split("KEY_FRAMES:", 1)
            summary_text = parts[0].strip()
            try:
                json_str = parts[1].strip()
                match = re.search(r"\[\s*\d+\s*(?:,\s*\d+\s*)*\]", json_str)
                if match:
                    key_frame_indices = json.loads(match.group(0))
                else:
                    key_frame_indices = json.loads(json_str)
            except Exception as e:
                _logger.warning(f"Không thể parse KEY_FRAMES từ response: {e}")
                key_frame_indices = []
            summary = summary.strip()
            
        if not key_frame_indices and len(extracted_frames) > 0:
            _logger.info("Không tìm thấy KEY_FRAMES từ mô tả của model. Áp dụng fallback tự động chọn frame...")
            if len(extracted_frames) >= 3:
                key_frame_indices = [0, len(extracted_frames) // 2, len(extracted_frames) - 1]
            else:
                key_frame_indices = list(range(len(extracted_frames)))
                
        # 7. Stage 2 — High-Resolution Targeted FFmpeg Extraction
        saved_frames = []
        if key_frame_indices and PILImage is not None:
            assets_dir = cfg.sources_dir / "assets" / "video_frames"
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
                        # Nếu ảnh chưa tồn tại HOẶC tồn tại nhưng có độ phân giải thấp (320x180) -> cần tải video để nâng cấp lên HD 720p
                        save_path = assets_dir / filename
                        if not save_path.exists():
                            need_download = True
                        else:
                            try:
                                with PILImage.open(save_path) as img_check:
                                    if img_check.size == (320, 180):
                                        need_download = True
                            except Exception:
                                need_download = True
                except Exception:
                    pass



            # Triển khai lớp 1: Tải video 720p cục bộ bằng yt-dlp
            local_video_path = None
            if need_download:
                try:
                    _logger.info("Stage 2: Đang tải video 720p cục bộ để trích xuất frame chất lượng cao...")
                    out_tmpl = str(tmp_dir / f"{video_id}_temp.%(ext)s")
                    ydl_opts = {
                        'format': 'bestvideo[height<=720][ext=mp4]/bestvideo[height<=480]/worstvideo',
                        'outtmpl': out_tmpl,
                        'quiet': True,
                        'no_warnings': True,
                    }
                    import yt_dlp
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
                        
                    for f in tmp_dir.glob(f"{video_id}_temp.*"):
                        if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
                            local_video_path = f
                            _logger.info(f"Tải video cục bộ thành công: {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")
                            break
                except Exception as dl_err:
                    _logger.warning(f"Không tải được video cục bộ bằng yt-dlp: {dl_err}. Sẽ fallback sang seek remote stream URL.")

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
                                    if img_check.size == (320, 180):
                                        _logger.info(f"Phát hiện ảnh chất lượng thấp {filename} (320x180). Sẽ trích xuất lại cục bộ để nâng cấp lên 720p...")
                                    else:
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
                                        _logger.info(f"Stage 2 trích xuất thành công frame cục bộ {idx} (720p).")
                                except Exception as local_exc:
                                    _logger.warning(f"Lớp 1 Local seek thất bại: {local_exc}. Fallback sang Lớp 2.")
                                    
                            # Lớp 2: Trích xuất từ remote stream URL (Online Seek)
                            if not is_high_res and high_res_url:
                                cmd_remote = [
                                    ffmpeg_bin, "-y",
                                    "-user_agent", user_agent,
                                    "-reconnect", "1",
                                    "-reconnect_streamed", "1",
                                    "-reconnect_delay_max", "5",
                                    "-timeout", "10000000",
                                    "-ss", str(round(ts, 2)),
                                    "-i", high_res_url,
                                    "-vframes", "1",
                                    "-q:v", "2",
                                    str(high_res_jpg)
                                ]
                                _logger.info(f"Stage 2 (Lớp 2 - Remote Seek): Trích xuất từ stream từ xa tại {round(ts,1)}s...")
                                import time
                                for _attempt in range(2):
                                    try:
                                        res = subprocess.run(
                                            cmd_remote, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            startupinfo=startupinfo, text=True, timeout=20
                                        )
                                        if res.returncode == 0 and high_res_jpg.exists():
                                            src_frame_path = high_res_jpg
                                            is_high_res = True
                                            _logger.info(f"Stage 2 trích xuất thành công frame từ xa {idx} (720p).")
                                            break
                                        else:
                                            if _attempt == 0:
                                                _logger.info(f"Stage 2 High-Res từ xa thất bại (code {res.returncode}), thử lại...")
                                                time.sleep(2)
                                            else:
                                                _logger.warning(f"Stage 2 High-Res từ xa thất bại sau 2 lần thử (code {res.returncode}).")
                                    except Exception as ffmpeg_exc:
                                        if _attempt == 0:
                                            _logger.info(f"Stage 2 từ xa gặp lỗi lần 1: {ffmpeg_exc}. Thử lại...")
                                            time.sleep(2)
                                        else:
                                            _logger.warning(f"Stage 2 từ xa gặp lỗi sau 2 lần thử: {ffmpeg_exc}.")
                                            
                            if not is_high_res:
                                _logger.warning(f"Stage 2 trích xuất chất lượng cao thất bại cho frame {idx}. Lớp 3: Degrade về storyboard frame.")
                        
                        # Tiến hành nén WebP từ src_frame_path (hoặc high-res hoặc storyboard)
                        img = PILImage.open(src_frame_path)
                        img.thumbnail((1280, 1280), PILImage.Resampling.LANCZOS)
                        if img.mode not in ("RGB", "RGBA"):
                            img = img.convert("RGB")
                        img.save(save_path, "WEBP", quality=80)
                        
                        res_label = "720p" if is_high_res else "320x180"
                        _logger.info(f"Đã lưu frame {idx} ({res_label}) thành công thành WebP: {filename}")
                        saved_frames.append(filename)
                except Exception as e:
                    _logger.warning(f"Lỗi khi lưu frame video {idx}: {e}")
                    
        # Nhúng các IMG markers vào visual summary để brain_dump.py nhận diện và bảo toàn
        if saved_frames:
            alt_texts = {}
            try:
                alt_texts = _generate_semantic_alt_texts(summary, saved_frames)
            except Exception as e:
                _logger.warning(f"Lỗi khi tạo semantic alt-text: {e}")
                
            img_section = "\n\n## 🎬 Hình ảnh trực quan từ video (Đã tải cục bộ)"
            for f in saved_frames:
                desc = alt_texts.get(f, "Video frame - diagram/slide")
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
