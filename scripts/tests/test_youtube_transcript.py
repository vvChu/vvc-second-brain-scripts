"""VvC Second Brain — YouTube Transcript Fetcher Tests (v1.0)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from services.youtube.transcript import (
    fetch_youtube_transcript,
    _download_audio_via_ytdlp,
)


@patch("youtube_transcript_api.YouTubeTranscriptApi")
def test_fetch_youtube_transcript_success(mock_api_class):
    # Mock transcript list and fetch
    mock_api = MagicMock()
    mock_api_class.return_value = mock_api
    
    mock_transcript = MagicMock()
    mock_transcript.fetch.return_value = [
        {"text": "Hello world", "start": 1.5},
        {"text": "Secondary sentence", "start": 32.0}
    ]
    
    mock_list = MagicMock()
    mock_list.find_transcript.return_value = mock_transcript
    mock_api.list.return_value = mock_list
    
    res = fetch_youtube_transcript("https://www.youtube.com/watch?v=ABC123xyz")
    
    # Text should be grouped into 30s blocks
    assert "[00:01] Hello world" in res
    assert "[00:32] Secondary sentence" in res


@patch("youtube_transcript_api.YouTubeTranscriptApi")
@patch("services.youtube.transcript._download_audio_via_ytdlp")
@patch("services.youtube.transcript.call_audio")
def test_fetch_youtube_transcript_fallback_whisper(mock_call_audio, mock_download, mock_api_class):
    # YouTube API fails
    mock_api_class.side_effect = Exception("API error")
    
    # yt-dlp returns mocked path
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_download.return_value = mock_path
    
    # Whisper returns transcription
    mock_call_audio.return_value = "Whisper transcription result."
    
    res = fetch_youtube_transcript("https://www.youtube.com/watch?v=ABC123xyz")
    
    assert res == "Whisper transcription result."
    mock_call_audio.assert_called_once_with(mock_path, model="audio-primary", language="vi")
    # Should clean up audio file
    mock_path.unlink.assert_called_once()


@patch("yt_dlp.YoutubeDL")
def test_download_audio_via_ytdlp(mock_ytdl_class, tmp_path):
    mock_ytdl = MagicMock()
    mock_ytdl_class.return_value = mock_ytdl
    
    mock_ytdl_context = MagicMock()
    mock_ytdl.__enter__.return_value = mock_ytdl_context
    mock_ytdl_context.extract_info.return_value = {
        "id": "ABC123xyz",
        "ext": "webm"
    }
    
    # Mock config concepts_dir parents
    from core.config import cfg
    mock_concepts_dir = tmp_path / "04 - Permanent" / "concepts"
    mock_concepts_dir.mkdir(parents=True, exist_ok=True)
    
    # Create mock downloaded file
    fleeting_dir = tmp_path / "05 - Fleeting"
    fleeting_dir.mkdir(parents=True, exist_ok=True)
    downloaded_file = fleeting_dir / "ABC123xyz.webm"
    downloaded_file.write_text("audio data")
    
    with patch("services.youtube.transcript.cfg") as mock_cfg:
        mock_cfg.concepts_dir = mock_concepts_dir
        res = _download_audio_via_ytdlp("https://youtube.com/watch?v=ABC123xyz")
        
    assert res == downloaded_file
    assert res.exists()


@patch("yt_dlp.YoutubeDL")
def test_extract_transcript_via_ytdlp_json3(mock_ytdl_class):
    """Test extracting JSON3 subtitles using yt-dlp."""
    from services.youtube.transcript import extract_transcript_via_ytdlp
    
    mock_ytdl = MagicMock()
    mock_ytdl_class.return_value = mock_ytdl
    mock_context = MagicMock()
    mock_ytdl.__enter__.return_value = mock_context

    mock_context.extract_info.return_value = {
        "subtitles": {
            "vi": [{"ext": "json3", "url": "https://fake.url/sub.json3"}]
        }
    }

    import json
    fake_json3 = json.dumps({
        "events": [
            {
                "tStartMs": 1500,
                "segs": [{"utf8": "Xin chào thế giới"}]
            },
            {
                "tStartMs": 35000,
                "segs": [{"utf8": "Câu nói thứ hai"}]
            }
        ]
    })
    
    mock_response = MagicMock()
    mock_response.read.return_value = fake_json3.encode("utf-8")
    mock_context.urlopen.return_value = mock_response

    result = extract_transcript_via_ytdlp("https://youtube.com/watch?v=ABC123xyz")
    assert result is not None
    assert "[00:01] Xin chào thế giới" in result
    assert "[00:35] Câu nói thứ hai" in result

