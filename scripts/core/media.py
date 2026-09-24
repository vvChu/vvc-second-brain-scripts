"""VvC Second Brain — Media & External Binary Utility Seam (v1.0).

Centralized service for locating external multimedia binaries (FFmpeg, FFprobe)
and performing standardized audio conversions (16kHz mono 32kbps MP3) across
the vault's ingestion pipelines.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

_logger = logging.getLogger("vvc.core.media")


def _find_win_binary(bin_name: str) -> str | None:
    """Find Windows executable for ffmpeg or ffprobe with fallback resolution."""
    found = shutil.which(bin_name)
    if found:
        return found

    # Dynamic WinGet packages directory resolution
    local_appdata = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    pkg_dir = base_dir / "Microsoft" / "WinGet" / "Packages"
    if pkg_dir.exists():
        try:
            for match in pkg_dir.glob(f"**/{bin_name}.exe"):
                if match.is_file():
                    return str(match)
        except Exception as e:
            _logger.debug(f"Failed to scan WinGet packages directory for {bin_name}: {e}")

    # Standard Windows root fallback
    system_drive = os.environ.get("SystemDrive", "C:")
    standard_fallback = Path(f"{system_drive}\\ffmpeg\\bin\\{bin_name}.exe")  # ccba:allow-machine-path
    if standard_fallback.exists():
        return str(standard_fallback)

    return None


def find_ffmpeg_bin() -> str | None:
    """Find the system path to the FFmpeg executable.

    Uses shutil.which first, then searches known Windows fallback directories
    such as WinGet packages and standard C:\\ffmpeg\\bin.

    Returns:
        Absolute path to ffmpeg executable as string, or None if not found.
    """
    return _find_win_binary("ffmpeg")


def find_ffprobe_bin() -> str | None:
    """Find the system path to the FFprobe executable.

    Uses shutil.which first, then searches known Windows fallback directories
    such as WinGet packages and standard C:\\ffmpeg\\bin.

    Returns:
        Absolute path to ffprobe executable as string, or None if not found.
    """
    return _find_win_binary("ffprobe")


def transcode_audio_to_mp3(
    source: str | Path,
    output_path: Path | None = None,
    sample_rate: int = 16000,
    channels: int = 1,
    bitrate: str = "32k",
    timeout: float = 300.0,
) -> Path | None:
    """Transcode an audio stream URL or file to normalized MP3 via FFmpeg.

    Standard output format defaults to 16kHz mono 32kbps MP3, optimized for
    speech recognition (Faster-Whisper and Gateway Audio).

    Args:
        source: Audio stream URL or path to local audio/video file.
        output_path: Optional destination Path. If None, creates a temporary file.
        sample_rate: Audio sampling rate in Hz (default 16000).
        channels: Number of audio channels (default 1 for mono).
        bitrate: Audio bitrate (default '32k').
        timeout: Execution timeout in seconds (default 300.0).

    Returns:
        Path to the generated MP3 file, or None if transcoding failed.
    """
    if not source:
        return None

    ffmpeg_bin = find_ffmpeg_bin() or "ffmpeg"

    target_path = (
        Path(output_path)
        if output_path is not None
        else Path(tempfile.gettempdir()) / f"media_{uuid.uuid4().hex[:8]}.mp3"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "-i",
        str(source),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-b:a",
        bitrate,
        str(target_path),
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if res.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0:
            return target_path

        err_msg = res.stderr.decode("utf-8", errors="replace")[:200]
        _logger.warning(f"ffmpeg failed (exit {res.returncode}): {err_msg}")
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        _logger.warning(f"ffmpeg transcoding exception: {e}")

    # Cleanup temp file on failure
    if target_path.exists():
        try:
            target_path.unlink()
        except OSError:
            pass

    return None
