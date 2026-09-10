"""VvC Second Brain — Audio Client.

Tier 1 logic for audio transcription via AI Gateway.
"""

import logging
import re
from pathlib import Path

from core.config import cfg
from core.llm.utils import increment_counter, is_garbage

_logger = logging.getLogger("vvc.llm.audio")

def call_gateway_audio(
    audio_path: Path,
    *,
    model: str = "audio-primary",
    language: str | None = None,
    timeout: int | float = 1800,
) -> str:
    """Call audio transcription via AI Gateway (LiteLLM)."""
    if not cfg.gateway_url:
        return ""

    try:
        import requests

        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}"
        }
        data = {
            "model": model,
            "vad_filter": "true",
            "beam_size": "5",
            "response_format": "verbose_json",
        }

        if language and language.lower() not in ("auto", "none", ""):
            data["language"] = language
            if language == "en":
                data["prompt"] = "Below is the detailed content in English, with full punctuation and capitalization:"
            else:
                data["prompt"] = "Dưới đây là nội dung chi tiết bằng tiếng Việt, có đầy đủ dấu câu:"

        url = f"{cfg.gateway_url}/audio/transcriptions"
        req_timeout = (10.0, float(timeout)) if isinstance(timeout, (int, float)) else timeout

        with open(audio_path, "rb") as audio_file:
            files = {"file": audio_file}
            response = requests.post(url, headers=headers, data=data, files=files, timeout=req_timeout)
            response.raise_for_status()

            segments = []
            raw_text = ""
            try:
                data_json = response.json()
                if isinstance(data_json, dict):
                    segments = data_json.get("segments") or []
                    raw_text = str(data_json.get("text", "")).strip()
                elif isinstance(data_json, list):
                    segments = data_json
            except Exception:
                raw_result = response.text.strip()
                if (raw_result.startswith("{") and raw_result.endswith("}")) or (raw_result.startswith("[") and raw_result.endswith("]")):
                    try:
                        import json
                        data_json = json.loads(raw_result)
                        if isinstance(data_json, dict):
                            segments = data_json.get("segments") or []
                            raw_text = str(data_json.get("text", "")).strip()
                        elif isinstance(data_json, list):
                            segments = data_json
                    except Exception:
                        raw_text = raw_result
                else:
                    raw_text = raw_result

            if not raw_text and not segments:
                raw_text = response.text.strip()

            # Parse segments into 30s chunks with [MM:SS] timestamps
            if segments:
                formatted_lines = []
                curr_start = None
                curr_texts = []

                for seg in segments:
                    if not isinstance(seg, dict):
                        continue
                    t_start = float(seg.get("start", 0.0))
                    text_part = str(seg.get("text", "")).strip()
                    if not text_part:
                        continue
                    if curr_start is None:
                        curr_start = t_start
                        curr_texts.append(text_part)
                    elif t_start - curr_start >= 30.0:
                        m = int(curr_start // 60)
                        s = int(curr_start % 60)
                        formatted_lines.append(f"[{m:02d}:{s:02d}] " + " ".join(curr_texts))
                        curr_start = t_start
                        curr_texts = [text_part]
                    else:
                        curr_texts.append(text_part)

                if curr_texts and curr_start is not None:
                    m = int(curr_start // 60)
                    s = int(curr_start % 60)
                    formatted_lines.append(f"[{m:02d}:{s:02d}] " + " ".join(curr_texts))

                if formatted_lines:
                    return "\n\n".join(formatted_lines)

            # Fallback: group sentences 5 at a time
            sentences = re.split(r'(?<=[.!?])\s+', raw_text)
            paragraphs = []
            for i in range(0, len(sentences), 5):
                chunk = " ".join(sentences[i:i+5]).strip()
                if chunk:
                    paragraphs.append(chunk)

            return "\n\n".join(paragraphs)

    except Exception as e:
        _logger.warning(f"Gateway audio transcription error: {e}")
        return ""


def call_audio(
    audio_path: Path,
    *,
    model: str = "audio-primary",
    language: str | None = None,
    timeout: int | float = 1800,
) -> str:
    """Call audio transcription via AI Gateway."""
    _logger.info(f"[audio] Transcribing {audio_path.name} via Gateway...")
    result = call_gateway_audio(audio_path, model=model, language=language, timeout=timeout)

    if result and not is_garbage(result):
        _logger.debug(f"[audio] OK ({len(result)} chars)")
        increment_counter("audio_api")
        return result

    _logger.error("[audio] Transcription failed")
    return ""
