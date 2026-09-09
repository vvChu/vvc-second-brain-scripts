"""VvC Second Brain — YouTube Transcript & Visual Extractor.

Split into sub-modules:
- transcript: Transcript API fetch + Whisper fallback
- visual_extractor: Video frame extraction + LLM-as-Judge
"""
from services.youtube.transcript import (  # noqa: F401
    fetch_youtube_transcript,
    get_base_ydl_opts,
    extract_transcript_via_ytdlp,
)
from services.youtube.visual_extractor import extract_video_visuals  # noqa: F401
