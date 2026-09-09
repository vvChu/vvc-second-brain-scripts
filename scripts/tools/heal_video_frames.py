"""VvC Second Brain — Video Frame Healer & Concept Aligner (v12.0).

Scans 04 - Permanent/sources/assets/video_frames/ for low-resolution frames (<200px),
re-extracts high-definition frames from YouTube streams or local downloads,
converts them to crisp WebP (quality=80), and corrects note alignments for Nil0-x25E4c.

Usage:
    python scripts/tools/heal_video_frames.py
    python scripts/tools/heal_video_frames.py --video-id Nil0-x25E4c
    python scripts/tools/heal_video_frames.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Ensure scripts directory is on sys.path
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from PIL import Image
import yt_dlp

from core.config import cfg
from services.youtube.visual_extractor import (
    _find_ffmpeg_bin,
    _get_high_res_stream_url,
    _get_video_download_ydl_opts,
)

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

_logger = logging.getLogger("vvc.heal_video_frames")

FRAMES_DIR = cfg.vault_root / "04 - Permanent" / "sources" / "assets" / "video_frames"
SCRATCH_DIR = cfg.vault_root / "scratch" / "_video_heal_tmp"


def find_low_res_frames(
    frames_dir: Path = FRAMES_DIR,
    threshold: int = 200,
    target_video_id: str | None = None,
) -> dict[str, list[tuple[Path, int, tuple[int, int]]]]:
    """Scan directory and find frames where max(width, height) < threshold.

    Returns:
        Dictionary mapping video_id to list of (frame_path, timestamp, (width, height)).
    """
    results: dict[str, list[tuple[Path, int, tuple[int, int]]]] = {}
    if not frames_dir.exists():
        _logger.warning(f"Thư mục frames không tồn tại: {frames_dir}")
        return results

    for p in sorted(frames_dir.glob("yt_*.webp")):
        match = re.match(r"^yt_([a-zA-Z0-9_-]+)_frame_\d+_ts(\d+)\.webp$", p.name)
        if not match:
            continue

        vid = match.group(1)
        if target_video_id and vid != target_video_id:
            continue

        ts = int(match.group(2))
        try:
            with Image.open(p) as img:
                w, h = img.size
                if max(w, h) < threshold:
                    if vid not in results:
                        results[vid] = []
                    results[vid].append((p, ts, (w, h)))
        except Exception as e:
            _logger.warning(f"Không thể đọc ảnh {p.name}: {e}")

    return results


def extract_frame_via_stream(
    ffmpeg_bin: str,
    stream_url: str,
    user_agent: str,
    timestamp: int,
    out_path: Path,
) -> bool:
    """Extract a single frame directly from a remote stream URL via FFmpeg seek."""
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        str(timestamp),
        "-user_agent",
        user_agent,
        "-i",
        stream_url,
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            timeout=25,
        )
        return res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        _logger.warning(f"Lỗi direct stream seek tại {timestamp}s: {e}")
        return False


def extract_frame_from_local_video(
    ffmpeg_bin: str,
    video_path: Path,
    timestamp: int,
    out_path: Path,
) -> bool:
    """Extract a single frame from a locally downloaded video file via FFmpeg."""
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            timeout=15,
        )
        return res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        _logger.warning(f"Lỗi local video seek tại {timestamp}s: {e}")
        return False


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

    try:
        _logger.info(f"Đang tải video {video_id} bằng selector chuẩn...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except Exception as err:
        _logger.warning(f"Tải video thất bại ({err}). Thử fallback format 18...")
        try:
            fb_opts = dict(ydl_opts)
            fb_opts["format"] = "18/best"
            fb_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
            with yt_dlp.YoutubeDL(fb_opts) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        except Exception as fb_err:
            _logger.error(f"Tải video fallback cũng thất bại: {fb_err}")
            return None

    for f in out_dir.glob(f"{video_id}_dl.*"):
        if f.is_file() and f.suffix in (".mp4", ".webm", ".mkv", ".m4v"):
            return f
    return None


def heal_video_id_frames(
    video_id: str,
    frames: list[tuple[Path, int, tuple[int, int]]],
    ffmpeg_bin: str,
    tmp_dir: Path,
) -> int:
    """Heal all low-res frames for a specific video ID."""
    _logger.info(f"=== Bắt đầu phục hồi video {video_id} ({len(frames)} frames) ===")
    url = f"https://www.youtube.com/watch?v={video_id}"

    local_cached = cfg.vault_root / "scratch" / "_heal_test" / f"test_{video_id}.mp4"
    if not local_cached.exists():
        local_cached = None

    stream_url = None
    user_agent = "Mozilla/5.0"
    try:
        opts = {
            "quiet": True,
            "skip_download": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                stream_url, user_agent = _get_high_res_stream_url(info)
    except Exception as e:
        _logger.warning(f"Không thể lấy stream URL cho {video_id}: {e}")

    healed_count = 0
    pending_frames = []

    for frame_path, ts, old_size in frames:
        temp_out = tmp_dir / f"temp_{video_id}_{ts}.jpg"
        success = False

        if local_cached and local_cached.exists():
            success = extract_frame_from_local_video(ffmpeg_bin, local_cached, ts, temp_out)
        elif stream_url:
            success = extract_frame_via_stream(ffmpeg_bin, stream_url, user_agent, ts, temp_out)

        if success and temp_out.exists():
            new_size = save_as_webp(temp_out, frame_path)
            if new_size and max(new_size) >= 200:
                _logger.info(f"  [OK] {frame_path.name}: {old_size} -> {new_size}")
                healed_count += 1
                try:
                    temp_out.unlink()
                except OSError:
                    pass
                continue

        pending_frames.append((frame_path, ts, old_size))

    if pending_frames:
        _logger.info(f"Cần tải video cục bộ cho {len(pending_frames)} frames của {video_id}...")
        dl_video = download_local_video(video_id, tmp_dir)
        if dl_video and dl_video.exists():
            for frame_path, ts, old_size in pending_frames:
                temp_out = tmp_dir / f"temp_dl_{video_id}_{ts}.jpg"
                if extract_frame_from_local_video(ffmpeg_bin, dl_video, ts, temp_out):
                    new_size = save_as_webp(temp_out, frame_path)
                    if new_size and max(new_size) >= 200:
                        _logger.info(f"  [OK-DL] {frame_path.name}: {old_size} -> {new_size}")
                        healed_count += 1
                try:
                    if temp_out.exists():
                        temp_out.unlink()
                except OSError:
                    pass
            try:
                dl_video.unlink()
            except OSError:
                pass

    return healed_count


def align_concept_notes_for_feynman() -> None:
    """Align Feynman concept notes and source transcript for video Nil0-x25E4c."""
    concepts_dir = cfg.vault_root / "04 - Permanent" / "concepts"
    sources_dir = cfg.vault_root / "04 - Permanent" / "sources" / "transcripts"

    # 1. ky_thuat_feynman.md: embed frame_018_ts541, anchor #^ts541 [09:01]
    feynman_file = concepts_dir / "ky_thuat_feynman.md"
    if feynman_file.exists():
        content = feynman_file.read_text(encoding="utf-8")
        content = re.sub(
            r"!\[\[yt_Nil0-x25E4c_frame_\d+_ts\d+\.webp\]\]",
            "![[yt_Nil0-x25E4c_frame_018_ts541.webp]]",
            content,
        )
        content = re.sub(
            r"\[\[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#\^ts\d+\|.*?\]\]",
            "[[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#^ts541|Xem slide và ngữ cảnh chi tiết tại [09:01] trong ghi chép gốc]]",
            content,
        )
        feynman_file.write_text(content, encoding="utf-8")
        _logger.info("Đã căn chỉnh ky_thuat_feynman.md -> frame_018_ts541 & #^ts541")

    # 2. phan_dinh_giua_dinh_danh_va_thau_hieu_ban_chat.md: ensure frame_011_ts414
    phan_dinh_file = concepts_dir / "phan_dinh_giua_dinh_danh_va_thau_hieu_ban_chat.md"
    if phan_dinh_file.exists():
        content = phan_dinh_file.read_text(encoding="utf-8")
        if "yt_Nil0-x25E4c_frame_011_ts414.webp" not in content:
            content = re.sub(
                r"!\[\[yt_Nil0-x25E4c_frame_\d+_ts\d+\.webp\]\]",
                "![[yt_Nil0-x25E4c_frame_011_ts414.webp]]",
                content,
            )
        content = re.sub(
            r"\[\[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#\^ts\d+\|.*?\]\]",
            "[[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#^ts414|Xem slide và ngữ cảnh chi tiết tại [06:54] trong ghi chép gốc]]",
            content,
        )
        phan_dinh_file.write_text(content, encoding="utf-8")
        _logger.info("Đã căn chỉnh phan_dinh_giua_dinh_danh_va_thau_hieu_ban_chat.md -> frame_011_ts414")

    # 3. tam_the_don_nhan_su_bat_tri.md: remove frame embed & reference anchor
    bat_tri_file = concepts_dir / "tam_the_don_nhan_su_bat_tri.md"
    if bat_tri_file.exists():
        content = bat_tri_file.read_text(encoding="utf-8")
        content = re.sub(r"\n*!\[\[yt_Nil0-x25E4c_frame_.*?\]\]\n*", "\n\n", content)
        content = re.sub(
            r"\s*-\s*\[\[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#\^ts\d+\|.*?\]\]\n?",
            "",
            content,
        )
        bat_tri_file.write_text(content, encoding="utf-8")
        _logger.info("Đã loại bỏ ảnh nhúng và neo anchor sai lệch khỏi tam_the_don_nhan_su_bat_tri.md")

    # 4. tinh_trung_thuc_tri_tue_va_tu_phan_tinh.md: remove frame embed & reference anchor
    trung_thuc_file = concepts_dir / "tinh_trung_thuc_tri_tue_va_tu_phan_tinh.md"
    if trung_thuc_file.exists():
        content = trung_thuc_file.read_text(encoding="utf-8")
        content = re.sub(r"\n*!\[\[yt_Nil0-x25E4c_frame_.*?\]\]\n*", "\n\n", content)
        content = re.sub(
            r"\s*-\s*\[\[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#\^ts\d+\|.*?\]\]\n?",
            "",
            content,
        )
        trung_thuc_file.write_text(content, encoding="utf-8")
        _logger.info("Đã loại bỏ ảnh nhúng và neo anchor sai lệch khỏi tinh_trung_thuc_tri_tue_va_tu_phan_tinh.md")

    # 5. Source Note: 2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill.md
    source_file = sources_dir / "2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill.md"
    if source_file.exists():
        content = source_file.read_text(encoding="utf-8")
        old_slides_pattern = r"## 🖼️ Danh sách Slide HD[\s\S]*?\[IMG:yt_Nil0-x25E4c_frame_018_ts541\.webp\|.*?\]"
        new_slides_block = (
            "## 🖼️ Danh sách Slide HD\n\n"
            "### 📊 Sơ đồ / Kiến trúc tại 414s ^ts414\n"
            "> 📎 [[phan_dinh_giua_dinh_danh_va_thau_hieu_ban_chat|Phân định giữa định danh và thấu hiểu bản chất]]\n"
            "![[yt_Nil0-x25E4c_frame_011_ts414.webp]]\n\n"
            "### 📊 Sơ đồ / Kiến trúc tại 541s ^ts541\n"
            "> 📎 [[ky_thuat_feynman|Kỹ thuật học tập Feynman]]\n"
            "![[yt_Nil0-x25E4c_frame_018_ts541.webp]]\n\n\n"
            "## 🎬 Hình ảnh trực quan từ video (Đã tải cục bộ)\n"
            "[IMG:yt_Nil0-x25E4c_frame_011_ts414.webp|alt=Ảnh tư liệu đen trắng thời thơ ấu của Richard Feynman cùng cha mẹ, phản ánh nguồn gốc hình thành tư duy phân định tên gọi và bản chất.]\n"
            "[IMG:yt_Nil0-x25E4c_frame_018_ts541.webp|alt=Slide Kỹ thuật học tập Feynman 4 bước: Chọn khái niệm, Dạy cho trẻ em, Lấp đầy lỗ hổng, Đơn giản hóa.]"
        )
        if re.search(old_slides_pattern, content):
            content = re.sub(old_slides_pattern, new_slides_block, content)
            source_file.write_text(content, encoding="utf-8")
            _logger.info("Đã cập nhật danh sách Slide HD và markers trong source note transcript.")


def clean_scratch_directory() -> None:
    """Clean up temporary test files in scratch."""
    scratch_dir = cfg.vault_root / "scratch"
    heal_test_dir = scratch_dir / "_heal_test"
    if heal_test_dir.exists():
        try:
            shutil.rmtree(heal_test_dir)
            _logger.info("Đã dọn dẹp thư mục scratch/_heal_test")
        except OSError as e:
            _logger.warning(f"Không thể xóa {heal_test_dir}: {e}")

    if SCRATCH_DIR.exists():
        try:
            shutil.rmtree(SCRATCH_DIR)
            _logger.info("Đã dọn dẹp thư mục tạm _video_heal_tmp")
        except OSError as e:
            _logger.warning(f"Không thể xóa {SCRATCH_DIR}: {e}")


def main() -> None:
    """Main execution entrance."""
    parser = argparse.ArgumentParser(description="Heal low-resolution YouTube video frames in Vault.")
    parser.add_argument("--video-id", type=str, default=None, help="Process only specific video ID")
    parser.add_argument("--threshold", type=int, default=200, help="Resolution threshold in pixels (default: 200)")
    parser.add_argument("--dry-run", action="store_true", help="Only list low-res frames without healing")
    parser.add_argument("--skip-wiki", action="store_true", help="Skip running wiki_maintain rebuild_all")
    args = parser.parse_args()

    ffmpeg_bin = _find_ffmpeg_bin()
    if not ffmpeg_bin:
        _logger.error("Không tìm thấy FFmpeg binary trên hệ thống! Thoát.")
        sys.exit(1)

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    low_res = find_low_res_frames(
        threshold=args.threshold,
        target_video_id=args.video_id,
    )

    total_frames = sum(len(frames) for frames in low_res.values())
    _logger.info(f"Tìm thấy {total_frames} khung hình <{args.threshold}px thuộc {len(low_res)} video.")

    if args.dry_run:
        for vid, frames in low_res.items():
            _logger.info(f"Video {vid}: {len(frames)} frames")
            for p, ts, sz in frames:
                _logger.info(f"  {p.name}: {sz} (ts={ts}s)")
        return

    try:
        # Heal frames video by video
        total_healed = 0
        for vid, frames in low_res.items():
            total_healed += heal_video_id_frames(vid, frames, ffmpeg_bin, SCRATCH_DIR)

        _logger.info(f"Đã phục hồi thành công {total_healed}/{total_frames} khung hình.")

        # Always align Feynman concept notes
        align_concept_notes_for_feynman()

        # Rebuild wiki
        if not args.skip_wiki:
            _logger.info("Đang xây dựng lại MOC và Master Index...")
            try:
                from wiki_maintain import maintain_wiki
                maintain_wiki()
                _logger.info("Xây dựng lại wiki thành công.")
            except Exception as e:
                _logger.error(f"Lỗi khi rebuild wiki: {e}", exc_info=True)
    finally:
        # Clean temporary files unconditionally
        clean_scratch_directory()
        _logger.info("Hoàn tất quy trình phục hồi hình ảnh và chuẩn hóa liên kết.")


if __name__ == "__main__":
    main()
