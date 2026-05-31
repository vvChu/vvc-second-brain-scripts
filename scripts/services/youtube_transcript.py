"""Backward compatibility shim — real code moved to services.youtube package."""
from services.youtube.transcript import fetch_youtube_transcript  # noqa: F401
from services.youtube.visual_extractor import extract_video_visuals  # noqa: F401

# Also re-export helpers used by tests
from services.youtube.visual_extractor import (  # noqa: F401
    _compute_frame_hash,
    _dedup_frames,
    _get_heatmap_peaks,
    _get_target_timestamps,
    _get_storyboard_frames,
    _find_ffmpeg_bin,
    _get_high_res_stream_url,
    _generate_semantic_alt_texts,
    _download_grid_with_retry,
    _MAX_KEY_FRAMES,
)
from services.youtube.transcript import _download_audio_via_ytdlp  # noqa: F401

# Re-export internal deps so test patches against this module still work
from core.llm.utils import http_session, encode_image  # noqa: F401

