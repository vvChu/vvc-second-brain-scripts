import pytest
from pathlib import Path
from services.youtube_transcript import _get_target_timestamps, _get_heatmap_peaks

def test_get_heatmap_peaks():
    # Mock heatmap data
    heatmap = [
        {"start_time": 10.0, "end_time": 20.0, "value": 0.5},
        {"start_time": 30.0, "end_time": 40.0, "value": 0.9},  # Peak 1 (value 0.9, mid 35)
        {"start_time": 50.0, "end_time": 60.0, "value": 0.2},
        {"start_time": 70.0, "end_time": 80.0, "value": 0.95}, # Peak 2 (value 0.95, mid 75)
    ]
    
    peaks = _get_heatmap_peaks(heatmap, duration_sec=100.0, max_peaks=2)
    assert len(peaks) == 2
    # Should sort Peak 2 first, Peak 1 second, but return sorted chronologically: [35.0, 75.0]
    assert peaks == [35.0, 75.0]

def test_get_target_timestamps_with_heatmap():
    chapters = [
        {"start_time": 0.0, "end_time": 50.0, "title": "Ch1"},
        {"start_time": 50.0, "end_time": 100.0, "title": "Ch2"},
    ]
    heatmap = [
        {"start_time": 30.0, "end_time": 40.0, "value": 0.95}, # Peak at 35.0
    ]
    
    ts = _get_target_timestamps(duration_sec=100.0, chapters=chapters, heatmap=heatmap)
    # Should contain chapter static points + heatmap peak
    assert 35.0 in ts
    assert len(ts) > 0


def test_select_best_storyboard_format_max_area():
    from services.youtube_transcript import _select_best_storyboard_format
    formats = [
        {"format_id": "sb3", "width": 48, "height": 27, "format_note": "storyboard"},
        {"format_id": "sb2", "width": 80, "height": 45, "format_note": "storyboard"},
        {"format_id": "sb1", "width": 160, "height": 90, "format_note": "storyboard"},
        {"format_id": "sb0", "width": 320, "height": 180, "format_note": "storyboard"},
    ]
    best = _select_best_storyboard_format(formats)
    assert best is not None
    assert best["format_id"] == "sb0"
    assert best["width"] * best["height"] == 57600

    # Test when width/height are omitted, sb0 is still preferred over sb2
    formats_no_dim = [
        {"format_id": "sb2", "format_note": "storyboard"},
        {"format_id": "sb0", "format_note": "storyboard"},
    ]
    best_no_dim = _select_best_storyboard_format(formats_no_dim)
    assert best_no_dim["format_id"] == "sb0"


def test_get_storyboard_frames_partial_fragment_undistorted(tmp_path):
    from unittest.mock import patch
    from PIL import Image
    from services.youtube_transcript import _get_storyboard_frames

    grid0 = Image.new("RGB", (960, 540), color="blue")
    grid1 = Image.new("RGB", (960, 180), color="red")

    sb0 = {
        "format_id": "sb0",
        "width": 320,
        "height": 180,
        "rows": 3,
        "columns": 3,
        "fragments": [
            {"url": "https://fake.url/grid0", "duration": 90.0},
            {"url": "https://fake.url/grid1", "duration": 30.0},
        ]
    }

    target_ts = [10.0, 100.0]

    with patch("services.youtube.visual_extractor._download_grid_with_retry", return_value=True), \
         patch("PIL.Image.open", side_effect=[grid0, grid1]):
        frames = _get_storyboard_frames(sb0, tmp_path, target_ts, duration_sec=120.0)

    assert len(frames) == 2
    with Image.open(frames[0]) as img0:
        assert img0.size == (320, 180)
    with Image.open(frames[1]) as img1:
        assert img1.size == (320, 180)


def test_get_video_download_ydl_opts_format18_and_no_player_client():
    from services.youtube_transcript import _get_video_download_ydl_opts
    opts = _get_video_download_ydl_opts("/tmp/output.mp4")
    
    fmt = opts.get("format", "")
    assert "bestvideo[height<=720]" in fmt
    assert "b/18" in fmt
    
    extractor_args = opts.get("extractor_args", {})
    yt_args = extractor_args.get("youtube", {})
    assert "player_client" not in yt_args


def test_parse_key_frames_response_v12_and_backward_compatible():
    from services.youtube_transcript import _parse_key_frames_response

    # v12.0 format: JSON array of objects with index and alt
    v12_summary = (
        "Mô tả chi tiết trực quan của slide bài giảng.\n\n"
        'KEY_FRAMES: [{"index": 0, "alt": "Sơ đồ kiến trúc"}, {"index": 2, "alt": "Bảng số liệu"}]'
    )
    cleaned, indices, alts = _parse_key_frames_response(v12_summary)
    assert cleaned == "Mô tả chi tiết trực quan của slide bài giảng."
    assert indices == [0, 2]
    assert alts == {0: "Sơ đồ kiến trúc", 2: "Bảng số liệu"}

    # v11.0 format: list of integers
    v11_summary = "Mô tả slide cũ.\nKEY_FRAMES: [1, 3]"
    cleaned11, indices11, alts11 = _parse_key_frames_response(v11_summary)
    assert cleaned11 == "Mô tả slide cũ."
    assert indices11 == [1, 3]
    assert alts11 == {}

    # Empty format
    empty_summary = "Không có slide nào.\nKEY_FRAMES: []"
    cleaned_e, indices_e, alts_e = _parse_key_frames_response(empty_summary)
    assert cleaned_e == "Không có slide nào."
    assert indices_e == []
    assert alts_e == {}


def test_parse_key_frames_response_square_brackets_in_alt():
    """Verify parser does not fail with JSONDecodeError when alt text contains square brackets."""
    from services.youtube_transcript import _parse_key_frames_response

    summary_with_brackets = (
        "Bản tóm tắt học thuật trực quan.\n\n"
        'KEY_FRAMES: [{"index": 0, "alt": "Sơ đồ kiến trúc [VvC] của hệ thống [2026]"}, '
        '{"index": 1, "alt": "Slide phương pháp [Feynman] 4 bước"}]'
    )
    cleaned, indices, alts = _parse_key_frames_response(summary_with_brackets)
    assert cleaned == "Bản tóm tắt học thuật trực quan."
    assert indices == [0, 1]
    assert alts[0] == "Sơ đồ kiến trúc [VvC] của hệ thống [2026]"
    assert alts[1] == "Slide phương pháp [Feynman] 4 bước"


def test_parse_key_frames_response_with_markdown_code_fences():
    """Verify parser correctly handles JSON wrapped in markdown code blocks."""
    from services.youtube_transcript import _parse_key_frames_response

    summary_fenced = (
        "Nội dung tóm tắt.\n\n"
        "KEY_FRAMES:\n```json\n"
        '[\n  {"index": 3, "alt": "Đồ thị tối ưu hóa"}, \n  {"index": 7, "alt": "Bảng thuật ngữ"}\n]\n'
        "```"
    )
    cleaned, indices, alts = _parse_key_frames_response(summary_fenced)
    assert cleaned == "Nội dung tóm tắt."
    assert indices == [3, 7]
    assert alts[3] == "Đồ thị tối ưu hóa"
    assert alts[7] == "Bảng thuật ngữ"


def test_parse_key_frames_response_dedup_and_mixed():
    """Verify duplicate indices are deduplicated preserving order, and mixed types are handled."""
    from services.youtube_transcript import _parse_key_frames_response

    summary_mixed = (
        "Tóm tắt.\n"
        'KEY_FRAMES: [{"index": 2, "alt": "Mô tả 2"}, {"index": 2, "alt": "Mô tả 2 trùng"}, 5, "5", "invalid"]'
    )
    cleaned, indices, alts = _parse_key_frames_response(summary_mixed)
    assert cleaned == "Tóm tắt."
    assert indices == [2, 5]
    assert alts[2] == "Mô tả 2"

