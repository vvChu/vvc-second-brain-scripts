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
import re
import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from PIL import Image

from core.config import cfg
from services.youtube.visual_extractor import _find_ffmpeg_bin

try:
    from tools.video_heal_extractor import (
        _get_video_stream,
        _process_pending_with_download,
        _run_ffmpeg,
        download_local_video,
        extract_frame_from_local_video,
        extract_frame_via_stream,
        heal_video_id_frames,
        save_as_webp,
    )
except ImportError:
    from video_heal_extractor import (  # type: ignore[no-redef]
        _get_video_stream,
        _process_pending_with_download,
        _run_ffmpeg,
        download_local_video,
        extract_frame_from_local_video,
        extract_frame_via_stream,
        heal_video_id_frames,
        save_as_webp,
    )

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(message)s")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

_logger = logging.getLogger("vvc.heal_video_frames")
FRAMES_DIR = cfg.vault_root / "04 - Permanent" / "sources" / "assets" / "video_frames"
SCRATCH_DIR = cfg.vault_root / "scratch" / "_video_heal_tmp"

__all__ = [
    "find_low_res_frames",
    "_run_ffmpeg",
    "extract_frame_via_stream",
    "extract_frame_from_local_video",
    "save_as_webp",
    "download_local_video",
    "_get_video_stream",
    "_process_pending_with_download",
    "heal_video_id_frames",
    "align_concept_notes_for_feynman",
    "clean_scratch_directory",
    "main",
]


def find_low_res_frames(
    frames_dir: Path = FRAMES_DIR,
    threshold: int = 200,
    target_video_id: str | None = None,
) -> dict[str, list[tuple[Path, int, tuple[int, int]]]]:
    """Scan directory and find frames where max(width, height) < threshold."""
    results: dict[str, list[tuple[Path, int, tuple[int, int]]]] = {}
    if not frames_dir.exists():
        _logger.warning(f"Thư mục frames không tồn tại: {frames_dir}")
        return results

    for p in sorted(frames_dir.glob("yt_*.webp")):
        match = re.match(r"^yt_([a-zA-Z0-9_-]+)_frame_\d+_ts(\d+)\.webp$", p.name)
        if not match or (target_video_id and match.group(1) != target_video_id):
            continue
        vid, ts = match.group(1), int(match.group(2))
        try:
            with Image.open(p) as img:
                w, h = img.size
                if max(w, h) < threshold:
                    results.setdefault(vid, []).append((p, ts, (w, h)))
        except Exception as e:
            _logger.warning(f"Không thể đọc ảnh {p.name}: {e}")
    return results


def _update_note_frame(filepath: Path, frame_sub: str, anchor_sub: str) -> None:
    """Update frame embed and reference anchor for a concept note."""
    if not filepath.exists():
        return
    content = filepath.read_text(encoding="utf-8")
    content = re.sub(r"!\[\[yt_Nil0-x25E4c_frame_\d+_ts\d+\.webp\]\]", frame_sub, content)
    content = re.sub(r"\[\[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#\^ts\d+\|.*?\]\]", anchor_sub, content)
    filepath.write_text(content, encoding="utf-8")
    _logger.info(f"Đã căn chỉnh {filepath.name} -> {frame_sub}")


def _strip_frame_embeds(filepath: Path) -> None:
    """Remove erroneous frame embeds and anchors from a concept note."""
    if not filepath.exists():
        return
    content = filepath.read_text(encoding="utf-8")
    content = re.sub(r"\n*!\[\[yt_Nil0-x25E4c_frame_.*?\]\]\n*", "\n\n", content)
    content = re.sub(r"\s*-\s*\[\[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#\^ts\d+\|.*?\]\]\n?", "", content)
    filepath.write_text(content, encoding="utf-8")
    _logger.info(f"Đã loại bỏ ảnh nhúng và neo anchor khỏi {filepath.name}")


def _update_feynman_source_note(source_file: Path) -> None:
    """Update slides and visual markers in Feynman source note."""
    if not source_file.exists():
        return
    content = source_file.read_text(encoding="utf-8")
    old_pattern = r"## 🖼️ Danh sách Slide HD[\s\S]*?\[IMG:yt_Nil0-x25E4c_frame_018_ts541\.webp\|.*?\]"
    new_slides = (
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
    if re.search(old_pattern, content):
        source_file.write_text(re.sub(old_pattern, new_slides, content), encoding="utf-8")
        _logger.info("Đã cập nhật danh sách Slide HD và markers trong source note transcript.")


def align_concept_notes_for_feynman() -> None:
    """Align Feynman concept notes and source transcript for video Nil0-x25E4c."""
    cdir = cfg.vault_root / "04 - Permanent" / "concepts"
    sdir = cfg.vault_root / "04 - Permanent" / "sources" / "transcripts"
    _update_note_frame(
        cdir / "ky_thuat_feynman.md", "![[yt_Nil0-x25E4c_frame_018_ts541.webp]]",
        "[[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#^ts541|Xem slide và ngữ cảnh chi tiết tại [09:01] trong ghi chép gốc]]",
    )
    _update_note_frame(
        cdir / "phan_dinh_giua_dinh_danh_va_thau_hieu_ban_chat.md", "![[yt_Nil0-x25E4c_frame_011_ts414.webp]]",
        "[[2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill#^ts414|Xem slide và ngữ cảnh chi tiết tại [06:54] trong ghi chép gốc]]",
    )
    _strip_frame_embeds(cdir / "tam_the_don_nhan_su_bat_tri.md")
    _strip_frame_embeds(cdir / "tinh_trung_thuc_tri_tue_va_tu_phan_tinh.md")
    _update_feynman_source_note(sdir / "2026-09-08_tu_duy_nhu_feynman_steve_jobs_bill.md")


def clean_scratch_directory() -> None:
    """Clean up temporary test files in scratch."""
    for p in (cfg.vault_root / "scratch" / "_heal_test", SCRATCH_DIR):
        if p.exists():
            try:
                shutil.rmtree(p)
                _logger.info(f"Đã dọn dẹp {p.name}")
            except OSError as e:
                _logger.warning(f"Không thể xóa {p}: {e}")


def _execute_healing(
    low_res: dict[str, list[tuple[Path, int, tuple[int, int]]]],
    ffmpeg_bin: str,
    skip_wiki: bool,
) -> None:
    """Run full healing process for all low-res frames and align notes."""
    total_frames = sum(len(frames) for frames in low_res.values())
    total_healed = sum(heal_video_id_frames(v, f, ffmpeg_bin, SCRATCH_DIR) for v, f in low_res.items())
    _logger.info(f"Đã phục hồi thành công {total_healed}/{total_frames} khung hình.")
    align_concept_notes_for_feynman()
    if not skip_wiki:
        _logger.info("Đang xây dựng lại MOC và Master Index...")
        try:
            from wiki_maintain import maintain_wiki
            maintain_wiki()
        except Exception as e:
            _logger.error(f"Lỗi khi rebuild wiki: {e}", exc_info=True)


def main() -> None:
    """Main execution entrance."""
    parser = argparse.ArgumentParser(description="Heal low-resolution YouTube video frames in Vault.")
    parser.add_argument("--video-id", type=str, default=None, help="Process only specific video ID")
    parser.add_argument("--threshold", type=int, default=200, help="Resolution threshold in pixels")
    parser.add_argument("--dry-run", action="store_true", help="Only list low-res frames without healing")
    parser.add_argument("--skip-wiki", action="store_true", help="Skip running wiki_maintain rebuild_all")
    args = parser.parse_args()

    ffmpeg_bin = _find_ffmpeg_bin()
    if not ffmpeg_bin:
        _logger.error("Không tìm thấy FFmpeg binary trên hệ thống! Thoát.")
        sys.exit(1)

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    low_res = find_low_res_frames(threshold=args.threshold, target_video_id=args.video_id)
    _logger.info(f"Tìm thấy {sum(len(f) for f in low_res.values())} khung hình <{args.threshold}px thuộc {len(low_res)} video.")

    if args.dry_run:
        for vid, frames in low_res.items():
            _logger.info(f"Video {vid}: {len(frames)} frames")
            for p, ts, sz in frames:
                _logger.info(f"  {p.name}: {sz} (ts={ts}s)")
        return

    try:
        _execute_healing(low_res, ffmpeg_bin, args.skip_wiki)
    finally:
        clean_scratch_directory()
        _logger.info("Hoàn tất quy trình phục hồi hình ảnh và chuẩn hóa liên kết.")


if __name__ == "__main__":
    main()
