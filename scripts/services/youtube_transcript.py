"""VvC Second Brain — YouTube Transcript Extracter.

Extracts transcripts from YouTube via API, fallbacks to yt-dlp + whisper.
"""

import logging
import urllib.parse
from pathlib import Path

from core.config import cfg
from core.llm import call_audio

_logger = logging.getLogger("vvc.youtube")

def _download_audio_via_ytdlp(url: str) -> Path | None:
    """Download audio from URL using yt-dlp as fallback."""
    try:
        import yt_dlp
        
        # Save to 05 - Fleeting (scratch area)
        out_dir = cfg.concepts_dir.parent.parent / "05 - Fleeting"
        out_tmpl = str(out_dir / "%(id)s.%(ext)s")
        
        ydl_opts = {
            'format': 'worstaudio/bestaudio',
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            if not info_dict:
                return None
            
            video_id = info_dict.get('id', '')
            if not video_id:
                return None
                
            # If ffmpeg is missing, it keeps the original extension (.webm/.m4a)
            # Find the downloaded file by its ID
            for f in out_dir.glob(f"{video_id}.*"):
                if f.is_file():
                    return f
            return None
    except ImportError:
        _logger.warning("yt-dlp is not installed. Run: pip install yt-dlp")
        return None
    except Exception as e:
        _logger.warning(f"yt-dlp download failed: {e}")
        return None


def fetch_youtube_transcript(url: str) -> str:
    """Fetch transcript from YouTube URL, fallback to audio download + Whisper."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        parsed = urllib.parse.urlparse(url)
        video_id = None
        if parsed.hostname in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path[1:]
        elif parsed.hostname in ("youtube.com", "www.youtube.com"):
            if parsed.path == "/watch":
                qs = urllib.parse.parse_qs(parsed.query)
                video_id = qs.get("v", [None])[0]
            elif parsed.path.startswith(("/embed/", "/v/")):
                video_id = parsed.path.split("/")[2]
                
        if not video_id:
            return ""
            
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        
        try:
            transcript = transcript_list.find_transcript(['vi', 'en'])
        except Exception:
            codes = [t.language_code for t in transcript_list]
            if not codes:
                return ""
            transcript = transcript_list.find_transcript(codes)
            
        data = transcript.fetch()
        text = " ".join([t.text if hasattr(t, 'text') else t['text'] for t in data])
        return text
    except Exception as e:
        _logger.warning(f"YouTube transcript fetch failed: {e}")
        _logger.info(f"Fallback to yt-dlp + Whisper for URL: {url}")
        audio_path = _download_audio_via_ytdlp(url)
        if audio_path:
            try:
                text = call_audio(audio_path, model="audio-primary", language="vi")
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass
                return text
            except Exception as e:
                _logger.error(f"Audio transcription failed: {e}")
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass
        return ""
