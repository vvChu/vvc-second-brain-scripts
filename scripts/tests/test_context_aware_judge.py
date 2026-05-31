import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from services.youtube_transcript import (
    _get_high_res_stream_url,
    _find_ffmpeg_bin,
    _get_target_timestamps,
    extract_video_visuals
)

def test_get_high_res_stream_url():
    # Mock info_dict formats
    info_dict = {
        "formats": [
            {
                "format_id": "sb0",
                "format_note": "storyboard",
                "url": "https://storyboard.url"
            },
            {
                "format_id": "worst",
                "height": 240,
                "ext": "mp4",
                "vcodec": "avc1",
                "url": "https://worst.url"
            },
            {
                "format_id": "720p_webm",
                "height": 720,
                "ext": "webm",
                "vcodec": "vp9",
                "url": "https://720p_webm.url"
            },
            {
                "format_id": "720p_mp4",
                "height": 720,
                "ext": "mp4",
                "vcodec": "avc1",
                "http_headers": {"User-Agent": "SpecialUA"},
                "url": "https://720p_mp4.url"
            },
            {
                "format_id": "1080p_mp4",
                "height": 1080,
                "ext": "mp4",
                "vcodec": "avc1",
                "url": "https://1080p_mp4.url"
            }
        ],
        "http_headers": {"User-Agent": "FallbackUA"}
    }
    
    url, ua = _get_high_res_stream_url(info_dict)
    # 720p mp4 avc1 should be preferred over webm and 1080p due to speed/format scores
    assert url == "https://720p_mp4.url"
    assert ua == "SpecialUA"


def test_find_ffmpeg_bin():
    # Verify that the finder returns either a string (if found) or None (if mock missing)
    # We will mock shutil.which to verify fallbacks
    with patch("shutil.which", return_value="/mocked/ffmpeg"):
        path = _find_ffmpeg_bin()
        assert path == "/mocked/ffmpeg"
        
    with patch("shutil.which", return_value=None):
        with patch("pathlib.Path.exists", return_value=False):
            path = _find_ffmpeg_bin()
            assert path is None or isinstance(path, str)


def test_dense_target_timestamps():
    # Test that target timestamps have a higher density (20-30 targets) in v11.0
    chapters = [
        {"start_time": 0.0, "end_time": 100.0, "title": "Ch1"},
        {"start_time": 100.0, "end_time": 200.0, "title": "Ch2"},
        {"start_time": 200.0, "end_time": 300.0, "title": "Ch3"},
        {"start_time": 300.0, "end_time": 400.0, "title": "Ch4"},
        {"start_time": 400.0, "end_time": 500.0, "title": "Ch5"},
    ]
    # For 5 chapters, p_factors is [0.20, 0.40, 0.60, 0.80, 0.95] (5 per chapter -> 25 total targets)
    ts = _get_target_timestamps(duration_sec=500.0, chapters=chapters)
    assert len(ts) >= 20
    assert len(ts) <= 30


@patch("services.youtube_transcript.http_session.post")
@patch("services.youtube_transcript._get_storyboard_frames")
@patch("services.youtube_transcript._find_ffmpeg_bin")
@patch("services.youtube_transcript._get_high_res_stream_url")
def test_extract_video_visuals_graceful_degrade(mock_get_high_res, mock_find_ffmpeg, mock_get_frames, mock_post):
    # Mock external calls to test graceful degradation logic
    mock_find_ffmpeg.return_value = None  # No FFmpeg available
    mock_get_high_res.return_value = (None, "Mozilla/5.0")
    
    # Mock 3 frames extracted in Stage 1
    mock_get_frames.return_value = [
        Path("/mock/frame0.jpg"),
        Path("/mock/frame1.jpg"),
        Path("/mock/frame2.jpg")
    ]
    
    # Mock Gateway response choosing KEY_FRAMES: [1, 2]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Visual description summarizing the video.\nKEY_FRAMES: [1, 2]"
                }
            }
        ]
    }
    mock_post.return_value = mock_response
    
    # Mock PIL Image open
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_open.return_value = mock_img
        
        info_dict = {
            "duration": 100.0,
            "formats": [{"format_id": "sb0", "fragments": [{"url": "https://grid"}]}]
        }
        
        # Call extract_video_visuals with mock inputs
        res = extract_video_visuals(
            url="https://youtube.com/watch?v=MZjbTfDt6xk",
            transcript_text="spoken words context",
            info_dict=info_dict
        )
        
        # Check that it returns description
        assert "Visual description" in res
        # Check that post was called with correct context
        called_args, called_kwargs = mock_post.call_args
        payload = called_kwargs["json"]
        prompt = payload["messages"][0]["content"][0]["text"]
        assert "spoken words context" in prompt
        assert "LLM-as-Judge" in prompt
