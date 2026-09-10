import pytest
from pathlib import Path
from services.youtube.visual_extractor import _get_target_timestamps, _get_heatmap_peaks

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
    from services.youtube.visual_extractor import _select_best_storyboard_format
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
    from services.youtube.visual_extractor import _get_storyboard_frames

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
    from services.youtube.visual_extractor import _get_video_download_ydl_opts
    opts = _get_video_download_ydl_opts("/tmp/output.mp4")
    
    fmt = opts.get("format", "")
    assert "bestvideo[height<=720]" in fmt
    assert "b/18" in fmt
    
    extractor_args = opts.get("extractor_args", {})
    yt_args = extractor_args.get("youtube", {})
    assert "player_client" not in yt_args


def test_parse_key_frames_response_v12_and_backward_compatible():
    from services.youtube.visual_extractor import _parse_key_frames_response

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
    from services.youtube.visual_extractor import _parse_key_frames_response

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
    from services.youtube.visual_extractor import _parse_key_frames_response

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
    from services.youtube.visual_extractor import _parse_key_frames_response

    summary_mixed = (
        "Tóm tắt.\n"
        'KEY_FRAMES: [{"index": 2, "alt": "Mô tả 2"}, {"index": 2, "alt": "Mô tả 2 trùng"}, 5, "5", "invalid"]'
    )
    cleaned, indices, alts = _parse_key_frames_response(summary_mixed)
    assert cleaned == "Tóm tắt."
    assert indices == [2, 5]
    assert alts[2] == "Mô tả 2"


def test_resolve_key_frames_with_fallback_respects_empty():
    """Verify that KEY_FRAMES: [] (intentional model refusal for podcasts/talking heads) is respected and does NOT fallback."""
    from services.youtube.visual_extractor import _resolve_key_frames_with_fallback

    # Case A1: Standard explicit empty list
    summary_empty = (
        "Video là podcast thảo luận bàn tròn, 100% người nói chuyện, không chứa slide hay sơ đồ học thuật.\n\n"
        "KEY_FRAMES: []"
    )
    cleaned, indices, alts = _resolve_key_frames_with_fallback(summary_empty, total_frames=6)
    assert cleaned == "Video là podcast thảo luận bàn tròn, 100% người nói chuyện, không chứa slide hay sơ đồ học thuật."
    assert indices == []
    assert alts == {}

    # Case A2: Explicit empty list wrapped in markdown code fence
    summary_fenced_empty = (
        "Nội dung trò chuyện.\n\n"
        "KEY_FRAMES:\n```json\n[]\n```"
    )
    cleaned_f, indices_f, alts_f = _resolve_key_frames_with_fallback(summary_fenced_empty, total_frames=4)
    assert cleaned_f == "Nội dung trò chuyện."
    assert indices_f == []
    assert alts_f == {}

    # Case A3: Explicit empty list with spaces inside brackets
    summary_spaced_empty = "Trò chuyện trực tuyến.\nKEY_FRAMES: [   ]"
    cleaned_s, indices_s, alts_s = _resolve_key_frames_with_fallback(summary_spaced_empty, total_frames=5)
    assert cleaned_s == "Trò chuyện trực tuyến."
    assert indices_s == []
    assert alts_s == {}

    # Case A4: Case-insensitive and markdown bold header with empty list
    summary_bold_empty = "Video phỏng vấn.\n\n**KEY_FRAMES:** []"
    cleaned_b, indices_b, alts_b = _resolve_key_frames_with_fallback(summary_bold_empty, total_frames=5)
    assert cleaned_b == "Video phỏng vấn."
    assert indices_b == []
    assert alts_b == {}


def test_resolve_key_frames_with_fallback_missing_header():
    """Verify that missing KEY_FRAMES: header (format non-compliance) triggers automatic frame selection fallback."""
    from services.youtube.visual_extractor import _resolve_key_frames_with_fallback

    # Case B1: No KEY_FRAMES: header in response at all (>= 3 frames -> start, middle, end)
    summary_no_header = "Mô tả toàn bộ visual của video nhưng model quên xuất header KEY_FRAMES."
    cleaned, indices, alts = _resolve_key_frames_with_fallback(summary_no_header, total_frames=7)
    assert cleaned == "Mô tả toàn bộ visual của video nhưng model quên xuất header KEY_FRAMES."
    assert indices == [0, 3, 6]
    assert alts == {}

    # Case B2: Missing header with exactly 3 frames
    _, indices_3, _ = _resolve_key_frames_with_fallback(summary_no_header, total_frames=3)
    assert indices_3 == [0, 1, 2]

    # Case B3: Missing header with 2 frames (< 3 frames -> list(range(total_frames)))
    _, indices_2, _ = _resolve_key_frames_with_fallback(summary_no_header, total_frames=2)
    assert indices_2 == [0, 1]

    # Case B4: Missing header with 0 frames
    _, indices_0, _ = _resolve_key_frames_with_fallback(summary_no_header, total_frames=0)
    assert indices_0 == []


def test_resolve_key_frames_with_fallback_parse_failure():
    """Verify that malformed JSON or parse failure triggers fallback instead of falsely treating as refusal."""
    from services.youtube.visual_extractor import _resolve_key_frames_with_fallback, KeyFramesParseResult

    # Case C1: Truncated JSON with unclosed bracket (e.g. token cutoff)
    summary_truncated = (
        "Video chứa slide kỹ thuật.\n\n"
        'KEY_FRAMES: [{"index": 1, "alt": "Slide kiến trúc"'
    )
    cleaned_t, indices_t, alts_t = _resolve_key_frames_with_fallback(summary_truncated, total_frames=6)
    assert cleaned_t == "Video chứa slide kỹ thuật."
    assert indices_t == [0, 3, 5]  # Fallback triggered!
    assert alts_t == {}

    # Case C2: Non-JSON payload after header
    summary_non_json = "Mô tả visual.\nKEY_FRAMES: None"
    cleaned_nj, indices_nj, _ = _resolve_key_frames_with_fallback(summary_non_json, total_frames=4)
    assert cleaned_nj == "Mô tả visual."
    assert indices_nj == [0, 2, 3]

    # Case C3: Empty text after header
    summary_empty_header = "Mô tả visual.\nKEY_FRAMES:"
    cleaned_eh, indices_eh, _ = _resolve_key_frames_with_fallback(summary_empty_header, total_frames=5)
    assert cleaned_eh == "Mô tả visual."
    assert indices_eh == [0, 2, 4]

    # Case C4: JSON objects with no valid integer indices
    summary_invalid_indices = 'Mô tả.\nKEY_FRAMES: [{"index": "invalid", "alt": "test"}]'
    cleaned_ii, indices_ii, _ = _resolve_key_frames_with_fallback(summary_invalid_indices, total_frames=6)
    assert cleaned_ii == "Mô tả."
    assert indices_ii == [0, 3, 5]


def test_resolve_key_frames_with_fallback_valid_selection():
    """Verify that normal valid KEY_FRAMES selection returns correct indices without fallback."""
    from services.youtube.visual_extractor import _resolve_key_frames_with_fallback

    summary = (
        "Mô tả visual.\n\n"
        'KEY_FRAMES: [{"index": 1, "alt": "Slide 1"}, {"index": 4, "alt": "Sơ đồ kiến trúc"}]'
    )
    cleaned, indices, alts = _resolve_key_frames_with_fallback(summary, total_frames=6)
    assert cleaned == "Mô tả visual."
    assert indices == [1, 4]
    assert alts == {1: "Slide 1", 4: "Sơ đồ kiến trúc"}


def test_keyframes_parse_result_attributes():
    """Verify KeyFramesParseResult behaves as a 3-tuple while exposing explicit flags."""
    from services.youtube.visual_extractor import _parse_key_frames_response, KeyFramesParseResult

    # Normal valid
    res_valid = _parse_key_frames_response('Tóm tắt\nKEY_FRAMES: [{"index": 0}]')
    assert isinstance(res_valid, tuple)
    assert len(res_valid) == 3
    cleaned, ind, alts = res_valid
    assert cleaned == "Tóm tắt"
    assert ind == [0]
    assert res_valid.header_present is True
    assert res_valid.parse_success is True
    assert res_valid.is_explicit_empty is False

    # Explicit empty
    res_empty = _parse_key_frames_response("Tóm tắt\nKEY_FRAMES: []")
    assert res_empty.header_present is True
    assert res_empty.parse_success is True
    assert res_empty.is_explicit_empty is True

    # Parse failure
    res_fail = _parse_key_frames_response("Tóm tắt\nKEY_FRAMES: [unclosed")
    assert res_fail.header_present is True
    assert res_fail.parse_success is False
    assert res_fail.is_explicit_empty is False

    # Missing header
    res_none = _parse_key_frames_response("Chỉ có văn bản")
    assert res_none.header_present is False
    assert res_none.parse_success is False
    assert res_none.is_explicit_empty is False


def test_get_target_timestamps_dynamic_budget_by_duration():
    """Verify dynamic target timestamps budget according to duration_sec."""
    # 1. Short video (< 15 min / 900s) -> ~15 targets
    ts_short = _get_target_timestamps(duration_sec=600.0)
    assert len(ts_short) == 15
    assert all(0.0 < t < 600.0 for t in ts_short)

    # 2. Medium video (15-60 min / 900s - 3600s) -> ~25 targets
    ts_medium = _get_target_timestamps(duration_sec=1800.0)
    assert len(ts_medium) == 25
    assert all(0.0 < t < 1800.0 for t in ts_medium)

    # 3. Long video (> 60 min / 3600s) -> 35-40 targets
    ts_long = _get_target_timestamps(duration_sec=5400.0)
    assert 35 <= len(ts_long) <= 40
    assert len(ts_long) == 36
    assert all(0.0 < t < 5400.0 for t in ts_long)

    # 4. Long video with chapters (> 60 min, 4 chapters) -> 35-40 targets
    chapters_long = [
        {"start_time": 0.0, "end_time": 1200.0, "title": "Part 1"},
        {"start_time": 1200.0, "end_time": 2400.0, "title": "Part 2"},
        {"start_time": 2400.0, "end_time": 3600.0, "title": "Part 3"},
        {"start_time": 3600.0, "end_time": 4800.0, "title": "Part 4"},
    ]
    ts_long_ch = _get_target_timestamps(duration_sec=4800.0, chapters=chapters_long)
    assert 35 <= len(ts_long_ch) <= 40
    assert len(ts_long_ch) == 36

    # 5. Boundary conditions
    ts_899 = _get_target_timestamps(duration_sec=899.0)
    assert len(ts_899) == 15
    ts_900 = _get_target_timestamps(duration_sec=900.0)
    assert len(ts_900) == 25
    ts_3600 = _get_target_timestamps(duration_sec=3600.0)
    assert len(ts_3600) == 25
    ts_3601 = _get_target_timestamps(duration_sec=3601.0)
    assert len(ts_3601) == 36

    # 6. Long video with 1 or 2 chapters (ensure lecture slide coverage is not throttled)
    ts_long_1ch = _get_target_timestamps(duration_sec=5400.0, chapters=[{"start_time": 0.0, "end_time": 5400.0, "title": "Full"}])
    assert 35 <= len(ts_long_1ch) <= 40
    assert len(ts_long_1ch) == 36

    chapters_2 = [
        {"start_time": 0.0, "end_time": 2700.0, "title": "Part 1"},
        {"start_time": 2700.0, "end_time": 5400.0, "title": "Part 2"},
    ]
    ts_long_2ch = _get_target_timestamps(duration_sec=5400.0, chapters=chapters_2)
    assert 35 <= len(ts_long_2ch) <= 40
    assert len(ts_long_2ch) == 36

    # 7. Medium video with 1 chapter
    ts_medium_1ch = _get_target_timestamps(duration_sec=1800.0, chapters=[{"start_time": 0.0, "end_time": 1800.0, "title": "Single Talk"}])
    assert len(ts_medium_1ch) == 25

    # 8. Edge cases: zero/negative duration, and malformed chapters fallback
    assert _get_target_timestamps(duration_sec=0.0) == []
    assert _get_target_timestamps(duration_sec=-10.0) == []
    malformed_chapters = [{"start_time": 500.0, "end_time": 200.0, "title": "Broken"}]
    ts_malformed = _get_target_timestamps(duration_sec=1800.0, chapters=malformed_chapters)
    assert len(ts_malformed) == 25




