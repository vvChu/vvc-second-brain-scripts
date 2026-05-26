"""VvC Second Brain — Unified LLM Client (v7.4).

Facade module for the LLM package. Provides unified routing.
"""

import logging

from core.config import cfg
from core.llm.utils import strip_think_tags, encode_image, is_garbage, increment_counter
from core.llm.gateway_client import call_gateway
from core.llm.copilot_client import call_copilot
from core.llm.gemini_client import call_gemini_cli, call_gemini_api
from core.llm.vision_client import call_vision
from core.llm.audio_client import call_audio

_logger = logging.getLogger("vvc.llm")

# Global state for Round-Robin load balancing
_rr_index = 0

from typing import Callable

def call_llm(
    prompt: str,
    *,
    model: str = "",
    task: str = "general",
    strategy: str = "fallback",
    validator: Callable[[str], bool] | None = None,
    allowed_shorts: tuple[str, ...] = (),
    min_length: int = 10,
) -> str:
    """Call LLM with automatic 3-tier fallback routing.

    Routing order: Gateway → Copilot CLI → Gemini CLI.

    Args:
        prompt: Text prompt.
        model: Explicit model name (bypasses routing).
        task: Task type for model selection:
            - "synthesis": Use text_synthesis_model
            - "correction": Use text_correction_model
            - "reasoning": Use reasoning model
            - "general": Use default model
        strategy: Routing strategy:
            - "fallback": Always try Gateway -> Copilot -> Gemini CLI -> API (default).
            - "round_robin": Rotate the primary tier for each call to balance load.
        validator: Optional function to validate the output. If it returns False, fallback to next tier.
        allowed_shorts: Optional list of short strings permitted in is_garbage check.
        min_length: Minimum character threshold for is_garbage check. Default 10.
            Lower this when expecting legitimately short responses (e.g. titles).

    Returns:
        LLM response text, or empty string if all tiers fail.
    """
    gw_timeout = cfg.reasoning_timeout if task == "reasoning" else cfg.gemini_timeout
    cp_timeout = cfg.reasoning_timeout if task == "reasoning" else cfg.copilot_timeout

    # Determine Models based on Task
    gw_model = model or (cfg.reasoning_gateway_model if task == "reasoning" else (cfg.gateway_correction_model if task == "correction" else cfg.gateway_proxy_model))
    cp_model = model or (cfg.copilot_correction_model if task == "correction" else cfg.copilot_model)
    gemini_model = model or (cfg.gemini_text_synthesis_model if task == "synthesis" else (cfg.gemini_text_correction_model if task == "correction" else cfg.gemini_model))

    # Try each tier
    tiers = [
        ("gateway", lambda: call_gateway(prompt, model=gw_model, timeout=gw_timeout)),
        ("copilot", lambda: call_copilot(prompt, model=cp_model, timeout=cp_timeout)),
        ("gemini-cli", lambda: call_gemini_cli(prompt, model=gemini_model, timeout=gw_timeout)),
        ("gemini-api", lambda: call_gemini_api(prompt, model=gemini_model, timeout=gw_timeout)),
    ]

    # Apply Round-Robin Strategy
    if strategy == "round_robin":
        global _rr_index
        start_idx = _rr_index % len(tiers)
        tiers = tiers[start_idx:] + tiers[:start_idx]
        _rr_index += 1
        _logger.debug(f"[llm] Round-Robin selected primary tier: {tiers[0][0]}")

    for tier_name, tier_fn in tiers:
        try:
            result = tier_fn()
            if result and not is_garbage(result, allowed_shorts=allowed_shorts, min_length=min_length):
                if validator is not None and not validator(result):
                    _logger.warning(f"[llm] {tier_name} OK but failed validation. Triggering fallback...")
                    continue
                _logger.debug(f"[llm] {tier_name} OK ({len(result)} chars)")
                increment_counter(f"llm_{tier_name}")
                return result
        except Exception as e:
            _logger.warning(f"[llm] {tier_name} failed: {e}")
            continue

    _logger.error("[llm] ALL tiers failed")
    return ""

__all__ = [
    "call_llm",
    "call_vision",
    "call_audio",
    "strip_think_tags",
    "encode_image",
]
