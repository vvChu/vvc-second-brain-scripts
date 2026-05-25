"""VvC Second Brain — Audio Client.

Tier 1 logic for audio transcription via AI Gateway.
"""

import logging
import re
from pathlib import Path

from core.config import cfg
from core.llm.utils import increment_counter, is_garbage

_logger = logging.getLogger("vvc.llm.audio")

def call_gateway_audio(audio_path: Path, *, model: str = "audio-primary", language: str = "vi", timeout: int = 1800) -> str:
    """Call audio transcription via AI Gateway (LiteLLM)."""
    if not cfg.gateway_url:
        return ""

    try:
        import requests
        
        if language == "en":
            initial_prompt = "Below is the detailed content in English, with full punctuation and capitalization:"
        else:
            initial_prompt = "Dưới đây là nội dung chi tiết bằng tiếng Việt, có đầy đủ dấu câu:"

        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}"
        }
        data = {
            "model": model,
            "vad_filter": "true",
            "language": language,
            "beam_size": "5",
            "prompt": initial_prompt,
            "response_format": "text"
        }
        
        url = f"{cfg.gateway_url}/audio/transcriptions"
        
        with open(audio_path, "rb") as audio_file:
            files = {"file": audio_file}
            response = requests.post(url, headers=headers, data=data, files=files, timeout=timeout)
            response.raise_for_status()
            
            raw_result = response.text.strip()
            
            if raw_result.startswith("{") and raw_result.endswith("}"):
                try:
                    import json
                    data_json = json.loads(raw_result)
                    if "text" in data_json:
                        raw_result = str(data_json["text"]).strip()
                except Exception:
                    pass
                    
            sentences = re.split(r'(?<=[.!?])\s+', raw_result)
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
    language: str = "vi",
    timeout: int = 1800,
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
