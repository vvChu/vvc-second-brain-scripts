"""VvC Second Brain — Media & External Binary Utility Seam (v1.0).

Centralized service for locating external multimedia binaries (FFmpeg, FFprobe)
and performing standardized audio conversions (16kHz mono 32kbps MP3) across
the vault's ingestion pipelines.
"""

from __future__ import annotations

import functools
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

_logger = logging.getLogger("vvc.core.media")


def find_ffmpeg_bin() -> str | None:
    """Find the system path to the FFmpeg executable.

    Uses shutil.which first, then searches known Windows fallback directories
    such as C:\\ffmpeg\\bin and WinGet packages.

    Returns:
        Absolute path to ffmpeg executable as string, or None if not found.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return ffmpeg_bin

    fallbacks: list[Path] = [
        Path("C:\\ffmpeg\\bin\\ffmpeg.exe"),
        Path(
            "C:\\Users\\chuvu\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
            "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-8.1.1-full_build\\bin\\ffmpeg.exe"
        ),
    ]

    pkg_dir = Path("C:\\Users\\chuvu\\AppData\\Local\\Microsoft\\WinGet\\Packages")
    if pkg_dir.exists():
        try:
            for fb in pkg_dir.glob("**/ffmpeg.exe"):
                fallbacks.append(fb)
        except Exception as e:
            _logger.debug(f"Failed to scan WinGet packages directory for ffmpeg: {e}")

    for fb in fallbacks:
        if fb.exists():
            return str(fb)

    return None


def find_ffprobe_bin() -> str | None:
    """Find the system path to the FFprobe executable.

    Uses shutil.which first, then searches known Windows fallback directories
    such as C:\\ffmpeg\\bin and WinGet packages.

    Returns:
        Absolute path to ffprobe executable as string, or None if not found.
    """
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        return ffprobe_bin

    fallbacks: list[Path] = [
        Path("C:\\ffmpeg\\bin\\ffprobe.exe"),
        Path(
            "C:\\Users\\chuvu\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
            "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-8.1.1-full_build\\bin\\ffprobe.exe"
        ),
    ]

    pkg_dir = Path("C:\\Users\\chuvu\\AppData\\Local\\Microsoft\\WinGet\\Packages")
    if pkg_dir.exists():
        try:
            for fb in pkg_dir.glob("**/ffprobe.exe"):
                fallbacks.append(fb)
        except Exception as e:
            _logger.debug(f"Failed to scan WinGet packages directory for ffprobe: {e}")

    for fb in fallbacks:
        if fb.exists():
            return str(fb)

    return None


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
