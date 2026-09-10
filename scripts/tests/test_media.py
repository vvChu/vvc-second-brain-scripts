"""VvC Second Brain — Unit Tests for Media Utility Seam (v1.0).

Tests binary discovery (find_ffmpeg_bin, find_ffprobe_bin) and audio transcoding
utility (transcode_audio_to_mp3) in scripts/core/media.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.media import (
    find_ffmpeg_bin,
    find_ffprobe_bin,
    transcode_audio_to_mp3,
)


def test_find_ffmpeg_bin_which():
    """Should return path from shutil.which when available."""
    with patch("shutil.which", return_value="C:\\ffmpeg\\bin\\ffmpeg.exe"):
        path = find_ffmpeg_bin()
        assert path == "C:\\ffmpeg\\bin\\ffmpeg.exe"


def test_find_ffmpeg_bin_fallback_path():
    """Should check fallback paths when shutil.which returns None."""
    with patch("shutil.which", return_value=None):
        with patch.object(Path, "exists", autospec=True) as mock_exists:
            mock_exists.side_effect = lambda self: "C:\\ffmpeg\\bin\\ffmpeg.exe" in str(self)
            path = find_ffmpeg_bin()
            assert path == "C:\\ffmpeg\\bin\\ffmpeg.exe"


def test_find_ffmpeg_bin_none_when_not_found():
    """Should return None when neither which nor fallbacks exist."""
    with patch("shutil.which", return_value=None):
        with patch.object(Path, "exists", autospec=True, return_value=False):
            path = find_ffmpeg_bin()
            assert path is None


def test_find_ffprobe_bin_which():
    """Should return path from shutil.which when available."""
    with patch("shutil.which", return_value="C:\\ffmpeg\\bin\\ffprobe.exe"):
        path = find_ffprobe_bin()
        assert path == "C:\\ffmpeg\\bin\\ffprobe.exe"


def test_find_ffprobe_bin_fallback_path():
    """Should check fallback paths when shutil.which returns None."""
    with patch("shutil.which", return_value=None):
        with patch.object(Path, "exists", autospec=True) as mock_exists:
            mock_exists.side_effect = lambda self: "C:\\ffmpeg\\bin\\ffprobe.exe" in str(self)
            path = find_ffprobe_bin()
            assert path == "C:\\ffmpeg\\bin\\ffprobe.exe"


def test_transcode_audio_to_mp3_empty_source():
    """Should immediately return None if source is empty."""
    assert transcode_audio_to_mp3("") is None


@patch("subprocess.run")
def test_transcode_audio_to_mp3_success_default_path(mock_subproc, tmp_path):
    """Should transcode to auto-generated temporary MP3 on success."""
    out_file = tmp_path / "mock_target.mp3"
    out_file.write_bytes(b"dummy mp3 data")

    with patch("tempfile.gettempdir", return_value=str(tmp_path)):
        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "test1234abcd"
            expected_path = tmp_path / "media_test1234.mp3"
            expected_path.write_bytes(b"fake audio bytes")

            mock_subproc.return_value = MagicMock(returncode=0)
            res = transcode_audio_to_mp3("https://stream.url/podcast.mp3")

            assert res == expected_path
            assert res.exists()
            assert mock_subproc.called
            # Verify command arguments
            cmd_args = mock_subproc.call_args[0][0]
            assert "-ar" in cmd_args
            assert "16000" in cmd_args
            assert "-ac" in cmd_args
            assert "1" in cmd_args
            assert "-b:a" in cmd_args
            assert "32k" in cmd_args


@patch("subprocess.run")
def test_transcode_audio_to_mp3_success_custom_path(mock_subproc, tmp_path):
    """Should transcode to explicitly provided output_path."""
    custom_target = tmp_path / "custom_audio.mp3"
    custom_target.write_bytes(b"dummy mp3 data")

    mock_subproc.return_value = MagicMock(returncode=0)
    res = transcode_audio_to_mp3("https://stream.url/audio.aac", output_path=custom_target)

    assert res == custom_target
    assert res.exists()


@patch("subprocess.run")
def test_transcode_audio_to_mp3_failure_cleanup(mock_subproc, tmp_path):
    """Should delete target file and return None if ffmpeg exits non-zero."""
    target = tmp_path / "failed_transcode.mp3"
    target.write_bytes(b"incomplete corrupt data")

    mock_subproc.return_value = MagicMock(returncode=1, stderr=b"decode error")
    res = transcode_audio_to_mp3("https://stream.url/bad.mp3", output_path=target)

    assert res is None
    assert not target.exists()


@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300))
def test_transcode_audio_to_mp3_timeout_exception(mock_subproc, tmp_path):
    """Should catch timeout exception, cleanup, and return None."""
    target = tmp_path / "timeout.mp3"
    target.write_bytes(b"partial")

    res = transcode_audio_to_mp3("https://stream.url/slow.mp3", output_path=target)

    assert res is None
    assert not target.exists()
