"""VvC Second Brain — Vision Client.

Routing: Gemini API (primary) → Gateway Vision → Copilot Vision.
"""

import logging
from pathlib import Path

from core.config import cfg
from core.llm.utils import encode_image, increment_counter, get_counter, is_garbage
from core.llm.gemini_client import call_gemini_api
from core.llm.gateway_client import call_gateway_vision

_logger = logging.getLogger("vvc.llm.vision")

def call_vision(
    image_path: Path,
    prompt: str,
    *,
    model: str = "",
    max_pixels: int = 1536,
) -> str:
    """Call vision model with image + text prompt."""
    image_b64 = encode_image(image_path, max_pixels=max_pixels)

    # Tier 1: AI Gateway (Primary - routes via ocr-primary on Spark with key-pooling)
    gateway_model = model or "ocr-primary"
    result = call_gateway_vision(image_b64, prompt, model=gateway_model, timeout=cfg.gemini_vision_timeout)
    if result and not is_garbage(result):
        increment_counter("vision_gateway")
        _logger.debug(f"[vision] AI Gateway OK ({len(result)} chars)")
        return result

    # Tier 2: Direct Gemini API (Fallback - direct call using local GEMINI_API_KEY)
    vision_count = get_counter("vision_api")
    target_model = model or cfg.gemini_vision_model
    if vision_count >= cfg.gemini_vision_rpd_limit:
        target_model = cfg.gemini_vision_model_batch or target_model
        _logger.info(f"[vision] Switched to batch model ({vision_count} calls today)")

    result = call_gemini_api(prompt, model=target_model, image_b64=image_b64, timeout=cfg.gemini_vision_timeout)
    if result and not is_garbage(result):
        increment_counter("vision_api")
        _logger.debug(f"[vision] Direct Gemini API OK ({len(result)} chars)")
        return result

    _logger.error("[vision] ALL vision tiers failed")
    return ""
