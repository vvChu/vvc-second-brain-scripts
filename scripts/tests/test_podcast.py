"""Unit tests for Podcast ingestion service and integrations."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.llm.audio_client import call_gateway_audio
from services.brain_dump.url_registry import _CONTENT_DOMAIN_PATTERNS, _normalize_url
from services.podcast import (
    _clean_podcast_title,
    _extract_podcast_json_ld,
    _get_audio_stream_url,
    _transcode_stream_to_mp3,
    fetch_podcast,
    is_podcast_url,
)


# --- 1. is_podcast_url tests ---

def test_is_podcast_url_apple_podcasts():
    assert is_podcast_url("https://podcasts.apple.com/us/podcast/no-priors/id1721313249?i=1000784231799")
    assert is_podcast_url("https://podcasts.apple.com/vn/podcast/t%E1%BA%ADp-1/id123456")


def test_is_podcast_url_spotify():
    assert is_podcast_url("https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk")
    assert is_podcast_url("https://open.spotify.com/intl-en/episode/4rOoJ6Egrf8K2IrywzwOMk?si=abcdef123")


def test_is_podcast_url_hosts_and_extensions():
    assert is_podcast_url("https://feeds.simplecast.com/54nAGcIl")
    assert is_podcast_url("https://share.transistor.fm/s/e12345")
    assert is_podcast_url("https://overcast.fm/+abc123xyz")
    assert is_podcast_url("https://pocketcasts.com/episode/123")
    assert is_podcast_url("https://example.com/audio/test_episode.mp3")
    assert is_podcast_url("https://cdn.podcasts.org/episodes/show_45.m4a?auth=123")


def test_is_podcast_url_negative_cases():
    assert not is_podcast_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_podcast_url("https://youtu.be/dQw4w9WgXcQ")
    assert not is_podcast_url("https://example.com/blog/ai-future")
    assert not is_podcast_url("https://github.com/anthropics/anthropic-sdk-python")
    assert not is_podcast_url("")
    assert not is_podcast_url(None)  # type: ignore


# --- 2. URL normalization & registry patterns ---

def test_normalize_url_apple_podcasts():
    us_url = "https://podcasts.apple.com/us/podcast/no-priors/id1721313249?i=1000784231799"
    vn_url = "https://podcasts.apple.com/vn/podcast/no-priors/id1721313249?i=1000784231799"
    other_ep_url = "https://podcasts.apple.com/us/podcast/no-priors/id1721313249?i=1000784231800"

    norm_us = _normalize_url(us_url)
    norm_vn = _normalize_url(vn_url)
    norm_other = _normalize_url(other_ep_url)

    # Country codes /us/ and /vn/ are stripped
    assert norm_us == "podcasts.apple.com/podcast/no-priors/id1721313249?i=1000784231799"
    assert norm_us == norm_vn
    # Different episode IDs remain distinct
    assert norm_us != norm_other


def test_normalize_url_spotify():
    intl_url = "https://open.spotify.com/intl-en/episode/4rOoJ6Egrf8K2IrywzwOMk?si=12345678"
    plain_url = "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"

    norm_intl = _normalize_url(intl_url)
    norm_plain = _normalize_url(plain_url)

    # Strips /intl-xx/ and tracking ?si=
    assert norm_intl == "open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"
    assert norm_intl == norm_plain


def test_content_domain_patterns_includes_podcasts():
    assert bool(_CONTENT_DOMAIN_PATTERNS.search("https://podcasts.apple.com/us/podcast/test/id1"))
    assert bool(_CONTENT_DOMAIN_PATTERNS.search("https://open.spotify.com/episode/123"))


# --- 3. JSON-LD Extraction ---

def test_extract_podcast_json_ld_apple_style():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "PodcastEpisode",
            "name": "What Happens When AI Adoption Actually Works - Apple Podcasts",
            "description": "Eric Schmidt discusses the future of AI &amp; enterprise compute...",
            "datePublished": "2026-03-01T10:00:00Z",
            "duration": "PT45M30S",
            "partOfSeries": {
                "@type": "PodcastSeries",
                "name": "No Priors: AI, Machine Learning, Tech"
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    meta = _extract_podcast_json_ld(html)
    assert meta["title"] == "What Happens When AI Adoption Actually Works"
    assert meta["show"] == "No Priors: AI, Machine Learning, Tech"
    assert "Eric Schmidt discusses the future of AI & enterprise compute..." in meta["description"]
    assert meta["date_published"] == "2026-03-01T10:00:00Z"
    assert meta["duration"] == "PT45M30S"


def test_extract_podcast_json_ld_graph_format():
    html = """
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "name": "Example"
            },
            {
                "@type": "PodcastEpisode",
                "name": "Deep Dive into LLMs | Podcast on Spotify",
                "description": "A comprehensive analysis of frontier models.",
                "partOfPodcast": {
                    "name": "Tech Breakdown"
                }
            }
        ]
    }
    </script>
    """
    meta = _extract_podcast_json_ld(html)
    assert meta["title"] == "Deep Dive into LLMs"
    assert meta["show"] == "Tech Breakdown"
    assert meta["description"] == "A comprehensive analysis of frontier models."


def test_clean_podcast_title():
    assert _clean_podcast_title("Episode 1 - Apple Podcasts") == "Episode 1"
    assert _clean_podcast_title("Episode 2 — Apple Podcasts") == "Episode 2"
    assert _clean_podcast_title("Episode 3 | Podcast on Spotify") == "Episode 3"
    assert _clean_podcast_title("Episode 4 - Spotify") == "Episode 4"
    assert _clean_podcast_title("Clean Title") == "Clean Title"


# --- 4. Audio stream resolution (skipping DRM & Show pages) ---

def test_get_audio_stream_url_skips_spotify():
    spotify_url = "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"
    assert _get_audio_stream_url(spotify_url) is None


def test_get_audio_stream_url_skips_apple_show_page():
    show_url = "https://podcasts.apple.com/us/podcast/no-priors/id1721313249"
    assert _get_audio_stream_url(show_url) is None


@patch("yt_dlp.YoutubeDL")
def test_get_audio_stream_url_resolves_apple_episode(mock_ydl_class):
    episode_url = "https://podcasts.apple.com/us/podcast/no-priors/id1721313249?i=1000784231799"
    mock_instance = MagicMock()
    mock_instance.extract_info.return_value = {"url": "https://audio.example.com/stream.mp3"}
    mock_ydl_class.return_value.__enter__.return_value = mock_instance

    stream_url = _get_audio_stream_url(episode_url)
    assert stream_url == "https://audio.example.com/stream.mp3"
    mock_instance.extract_info.assert_called_once_with(episode_url, download=False)


# --- 5. Stream Transcoding ---

@patch("subprocess.run")
def test_transcode_stream_to_mp3_success(mock_subproc, tmp_path):
    mock_file = tmp_path / "mock_audio.mp3"
    mock_file.write_bytes(b"fake mp3 data" * 10)

    with patch("tempfile.gettempdir", return_value=str(tmp_path)):
        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "test1234abcd"
            expected_path = tmp_path / "podcast_test1234.mp3"
            expected_path.write_bytes(b"fake mp3 bytes")

            mock_subproc.return_value = MagicMock(returncode=0)
            res_path = _transcode_stream_to_mp3("https://stream.url/audio.mp3")

            assert res_path == expected_path
            assert res_path.exists()
            # Clean up
            res_path.unlink()


@patch("subprocess.run")
def test_transcode_stream_to_mp3_failure(mock_subproc):
    mock_subproc.return_value = MagicMock(returncode=1, stderr=b"ffmpeg decode error")
    res = _transcode_stream_to_mp3("https://stream.url/broken.mp3")
    assert res is None


# --- 6. Full fetch_podcast orchestration & Fallback ---

@patch("services.podcast.requests.get")
@patch("services.podcast._get_audio_stream_url")
@patch("services.podcast._transcode_stream_to_mp3")
@patch("core.llm.call_audio")
def test_fetch_podcast_full_success(mock_call_audio, mock_transcode, mock_get_stream, mock_requests_get, tmp_path):
    html_content = """
    <script type="application/ld+json">
    {
        "@type": "PodcastEpisode",
        "name": "Agentic Workflows in Production",
        "description": "Detailed discussion on autonomous coding.",
        "partOfSeries": {"name": "AI Frontier"},
        "datePublished": "2026-09-01"
    }
    </script>
    """
    mock_resp = MagicMock()
    mock_resp.text = html_content
    mock_resp.apparent_encoding = "utf-8"
    mock_requests_get.return_value = mock_resp

    mock_get_stream.return_value = "https://stream.org/audio.mp3"
    fake_mp3 = tmp_path / "test_ep.mp3"
    fake_mp3.write_bytes(b"1234")
    mock_transcode.return_value = fake_mp3

    mock_call_audio.return_value = "[00:00] Xin chào mọi người.\n\n[00:30] Hôm nay chúng ta bàn về Agentic workflows."

    result = fetch_podcast("https://podcasts.apple.com/us/podcast/ep/id1?i=100")

    assert "# Agentic Workflows in Production" in result
    assert "**Show:** AI Frontier" in result
    assert "**Date:** 2026-09-01" in result
    assert "## Show Notes\n\nDetailed discussion on autonomous coding." in result
    assert "## 🎙️ Lời thoại âm thanh (Transcript)" in result
    assert "[00:00] Xin chào mọi người." in result
    # Ensure call_audio was called with language=None
    mock_call_audio.assert_called_once_with(fake_mp3, model="audio-primary", language=None)
    # Ensure temporary file was cleaned up
    assert not fake_mp3.exists()


@patch("services.podcast.requests.get")
def test_fetch_podcast_graceful_fallback_spotify_drm(mock_requests_get):
    spotify_url = "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"
    html_content = """
    <script type="application/ld+json">
    {
        "@type": "PodcastEpisode",
        "name": "State of AI 2026 | Podcast on Spotify",
        "description": "Comprehensive review of 2026 models.",
        "partOfPodcast": {"name": "AI Weekly"}
    }
    </script>
    """
    mock_resp = MagicMock()
    mock_resp.text = html_content
    mock_resp.apparent_encoding = "utf-8"
    mock_requests_get.return_value = mock_resp

    result = fetch_podcast(spotify_url)

    # Has metadata and Show Notes
    assert "# State of AI 2026" in result
    assert "**Show:** AI Weekly" in result
    assert "## Show Notes\n\nComprehensive review of 2026 models." in result
    # No transcript section since Spotify skips audio
    assert "## 🎙️ Lời thoại âm thanh (Transcript)" not in result


# --- 7. audio_client segments parsing & language parameter tests ---

@patch("requests.post")
def test_call_gateway_audio_segments_parsing(mock_post, tmp_path):
    mock_audio = tmp_path / "test.mp3"
    mock_audio.write_bytes(b"fake audio")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "text": "Hello world. We are testing Whisper.",
        "segments": [
            {"start": 0.0, "end": 4.5, "text": "Hello world."},
            {"start": 10.2, "end": 15.0, "text": "This is segment one."},
            {"start": 35.0, "end": 40.0, "text": "This is segment two after 30s."},
        ],
    }
    mock_post.return_value = mock_resp

    with patch("core.llm.audio_client.cfg") as mock_cfg:
        mock_cfg.gateway_url = "http://gateway.test:8090"
        mock_cfg.gateway_api_key = "test_key"
        res = call_gateway_audio(mock_audio, language=None, timeout=120)

    assert "[00:00] Hello world. This is segment one." in res
    assert "[00:35] This is segment two after 30s." in res

    # Verify requests.post call: timeout tuple and no language/prompt in data
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["timeout"] == (10.0, 120.0)
    data = kwargs["data"]
    assert "language" not in data
    assert "prompt" not in data
    assert data["response_format"] == "verbose_json"


@patch("requests.post")
def test_call_gateway_audio_language_vi_passes_prompt(mock_post, tmp_path):
    mock_audio = tmp_path / "test.mp3"
    mock_audio.write_bytes(b"fake audio")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "text": "Một hai ba bốn năm sáu bảy tám.",
        "segments": [],
    }
    mock_post.return_value = mock_resp

    with patch("core.llm.audio_client.cfg") as mock_cfg:
        mock_cfg.gateway_url = "http://gateway.test:8090"
        mock_cfg.gateway_api_key = "test_key"
        res = call_gateway_audio(mock_audio, language="vi", timeout=60)

    assert "Một hai ba bốn năm sáu bảy tám." in res
    _, kwargs = mock_post.call_args
    data = kwargs["data"]
    assert data["language"] == "vi"
    assert "tiếng Việt" in data["prompt"]


# --- 8. Integration: url_fetcher routing, save_transcript, daemon poller ---

@patch("services.podcast.fetch_podcast")
def test_fetch_url_routes_podcast(mock_fetch_podcast):
    from services.url_fetcher import fetch_url
    mock_fetch_podcast.return_value = "# Podcast Content\n\nShow Notes"
    podcast_url = "https://podcasts.apple.com/us/podcast/ep1/id123?i=100"
    res = fetch_url(podcast_url)
    assert res == "# Podcast Content\n\nShow Notes"
    mock_fetch_podcast.assert_called_once_with(podcast_url)


@patch("services.brain_dump.concept_synthesis.fetch_url_title")
@patch("services.brain_dump.concept_synthesis._extract_related_links")
def test_save_transcript_podcast_heading_and_no_related_links(mock_related, mock_fetch_title, tmp_path):
    from services.brain_dump.concept_synthesis import _save_transcript

    with patch("services.brain_dump.concept_synthesis.cfg") as mock_cfg:
        mock_cfg.sources_dir = tmp_path
        transcript_content = (
            "# AI & Software Engineering in 2026\n\n"
            "**Show:** Tech Talk\n\n"
            "Here is the transcript body text that is long enough to be saved as a source note."
        )
        url = "https://podcasts.apple.com/us/podcast/ai-sw/id123?i=456"
        stem = _save_transcript(transcript_content, original_url=url)

        # Did NOT call fetch_url_title because title was in heading
        mock_fetch_title.assert_not_called()
        # Did NOT extract related links for podcast
        mock_related.assert_not_called()
        assert stem
        saved_files = list((tmp_path / "transcripts").glob("*.md"))
        assert len(saved_files) == 1
        content = saved_files[0].read_text(encoding="utf-8")
        assert "AI & Software Engineering in 2026" in content


@patch("services.brain_dump.handle_brain_dump")
def test_daemon_poll_brain_dump_threading(mock_handle_dump, tmp_path):
    import time
    import daemon

    fake_dump_file = tmp_path / "Brain_Dump.md"
    fake_dump_file.write_text("https://podcasts.apple.com/us/podcast/test/id1?i=1", encoding="utf-8")

    with patch("daemon.cfg") as mock_cfg:
        mock_cfg.dump_file = fake_dump_file
        daemon._poller_state.dump_mtime = 0.0
        daemon._dump_in_progress = False
        daemon._poll_brain_dump()

        for _ in range(40):
            if mock_handle_dump.called and not daemon._dump_in_progress:
                break
            time.sleep(0.05)

        mock_handle_dump.assert_called_once()
        assert daemon._dump_in_progress is False


def test_extract_podcast_json_ld_series_precedes_episode():
    """Verify episode metadata takes precedence even if PodcastSeries appears first in @graph."""
    html = """
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "PodcastSeries",
                "name": "The Master Show",
                "description": "Show-level description of The Master Show."
            },
            {
                "@type": "PodcastEpisode",
                "name": "Episode 42: The Answer",
                "description": "Deep discussion on universe computation.",
                "partOfSeries": {
                    "name": "The Master Show"
                },
                "datePublished": "2026-09-05"
            }
        ]
    }
    </script>
    """
    meta = _extract_podcast_json_ld(html)
    assert meta["title"] == "Episode 42: The Answer"
    assert meta["show"] == "The Master Show"
    assert meta["description"] == "Deep discussion on universe computation."
    assert meta["date_published"] == "2026-09-05"


def test_extract_podcast_json_ld_show_only_page():
    """Verify show page without episode extracts show metadata cleanly."""
    html = """
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "PodcastSeries",
        "name": "Acquired - Apple Podcasts",
        "description": "Stories and playbooks of great companies."
    }
    </script>
    """
    meta = _extract_podcast_json_ld(html)
    assert meta["title"] == "Acquired"
    assert meta["show"] == "Acquired"
    assert meta["description"] == "Stories and playbooks of great companies."


def test_extract_podcast_json_ld_unescapes_html_entities():
    html = """
    <script type="application/ld+json">
    {
        "@type": "PodcastEpisode",
        "name": "Hardware &amp; Silicon | Podcast on Spotify",
        "partOfSeries": {"name": "Chips &amp; Bits"}
    }
    </script>
    """
    meta = _extract_podcast_json_ld(html)
    assert meta["title"] == "Hardware & Silicon"
    assert meta["show"] == "Chips & Bits"


def test_extract_podcast_json_ld_rich_html_fallback():
    """Verify truncated JSON-LD description is replaced by full HTML show notes."""
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "PodcastEpisode",
            "name": "AI Systems",
            "description": "Short truncated preview..."
        }
        </script>
    </head>
    <body>
        <div class="paragraph-wrapper">
            <p>This is the complete and full detailed show notes that contain in-depth information, references, and timestamps about the episode that were truncated in JSON-LD.</p>
        </div>
    </body>
    </html>
    """
    meta = _extract_podcast_json_ld(html)
    assert "This is the complete and full detailed show notes" in meta["description"]


def test_get_audio_stream_url_direct_audio():
    mp3_url = "https://cdn.example.org/podcasts/episode_42.mp3"
    assert _get_audio_stream_url(mp3_url) == mp3_url


@patch("services.podcast._transcode_stream_to_mp3")
@patch("core.llm.call_audio")
def test_fetch_podcast_direct_audio(mock_call_audio, mock_transcode, tmp_path):
    fake_mp3 = tmp_path / "audio.mp3"
    fake_mp3.write_bytes(b"data")
    mock_transcode.return_value = fake_mp3
    mock_call_audio.return_value = "[00:00] Direct audio transcription."

    url = "https://media.blubrry.com/show/p/example.com/episode_interview.mp3"
    res = fetch_podcast(url)

    assert "# Episode Interview" in res
    assert "[00:00] Direct audio transcription." in res
    mock_transcode.assert_called_once_with(url)


def test_daemon_poll_brain_dump_in_progress_preserves_mtime(tmp_path):
    import daemon

    fake_file = tmp_path / "Brain_Dump.md"
    fake_file.write_text("initial", encoding="utf-8")

    with patch("daemon.cfg") as mock_cfg:
        mock_cfg.dump_file = fake_file
        daemon._poller_state.dump_mtime = 100.0
        daemon._dump_in_progress = True

        # When polling while in progress, it must return immediately
        # and NOT advance dump_mtime to stat().st_mtime
        daemon._poll_brain_dump()
        assert daemon._poller_state.dump_mtime == 100.0


def test_normalize_url_case_and_locale_variations():
    upper_apple = "https://podcasts.apple.com/US/podcast/show-name/id123?I=999"
    norm_apple = _normalize_url(upper_apple)
    assert norm_apple == "podcasts.apple.com/podcast/show-name/id123?i=999"

    multi_locale_spotify = "https://open.spotify.com/intl-pt-br/episode/4rOoJ6Egrf8K2IrywzwOMk?si=abcdef"
    norm_spotify = _normalize_url(multi_locale_spotify)
    assert norm_spotify == "open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"


