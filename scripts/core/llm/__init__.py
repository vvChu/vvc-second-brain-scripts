"""VvC Second Brain — Unified LLM Client (v7.4).

Facade module for the LLM package. Provides unified routing.
"""

import logging
import threading

from core.config import cfg
from core.llm.utils import strip_think_tags, encode_image, is_garbage, increment_counter
from core.llm.gateway_client import call_gateway
from core.llm.copilot_client import call_copilot
from core.llm.gemini_client import (
    call_gemini_cli,
    call_antigravity_cli,
    call_gemini_api,
    is_antigravity_cli_supported,
)
from core.llm.vision_client import call_vision
from core.llm.audio_client import call_audio
from core.llm.embedding_client import get_embedding, get_embedding_via_gateway
from core.llm.model_resolver import resolve_model, STATIC_LATEST_GEMINI_FLASH

_logger = logging.getLogger("vvc.llm")

# Global state for Round-Robin load balancing (thread-safe)
_rr_index = 0
_rr_lock = threading.Lock()


import core.llm.gemini_client as _gc_orig


def _invoke_cli(prompt: str, model: str, timeout: int) -> str:
    """Invoke CLI tier, supporting monkeypatching of either call_antigravity_cli or call_gemini_cli."""
    if call_antigravity_cli is not _gc_orig.call_gemini_cli:
        return call_antigravity_cli(prompt, model=model, timeout=timeout)
    if call_gemini_cli is not _gc_orig.call_gemini_cli:
        return call_gemini_cli(prompt, model=model, timeout=timeout)
    return call_antigravity_cli(prompt, model=model, timeout=timeout)

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
    """Call LLM with automatic 4-tier fallback routing.

    Routing order: Gateway → Antigravity CLI (agy) → Copilot CLI → Gemini API.

    Args:
        prompt: Text prompt.
        model: Explicit model name (bypasses routing).
        task: Task type for model selection:
            - "synthesis": Use text_synthesis_model
            - "correction": Use text_correction_model
            - "reasoning": Use reasoning model
            - "general": Use default model
        strategy: Routing strategy:
            - "fallback": Always try Gateway -> Gemini CLI -> Copilot -> API (default).
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

    resolved_model = resolve_model(model, task=task) if model else ""

    # Determine Models based on Task
    if task == "reasoning":
        gw_model = resolved_model or resolve_model(cfg.reasoning_gateway_model, task=task)
        agy_model = resolved_model or getattr(cfg, "reasoning_cli_model", "") or "claude-opus-4-6-thinking"
    elif task == "synthesis":
        gw_model = resolved_model or resolve_model(cfg.gateway_synthesis_model or "gemini-3.8-flash-high", task=task)
        agy_model = resolved_model or (cfg.gemini_text_synthesis_model if task == "synthesis" else cfg.gemini_model)
    elif task == "correction":
        gw_model = resolved_model or resolve_model(cfg.gateway_correction_model, task=task)
        agy_model = resolved_model or cfg.gemini_text_correction_model
    else:
        gw_model = resolved_model or resolve_model(cfg.gateway_proxy_model, task=task)
        agy_model = resolved_model or cfg.gemini_model

    cp_model = resolved_model or (cfg.copilot_correction_model if task == "correction" else cfg.copilot_model)
    gemini_raw = resolved_model or (cfg.gemini_text_synthesis_model if task == "synthesis" else (cfg.gemini_text_correction_model if task == "correction" else cfg.gemini_model))
    gemini_model = resolve_model(gemini_raw, task=task)

    # Check if target model is supported by local Antigravity CLI (agy.exe)
    use_antigravity_cli_primary = is_antigravity_cli_supported(agy_model)

    # Try each tier:
    if use_antigravity_cli_primary:
        # Priority 1: Local Antigravity CLI (Zero VPN, Zero 429, native Claude Opus / Gemini Flash / Gemini Pro)
        # Fallback: Gateway Port 8045/8090 -> Copilot CLI -> Gemini API
        tiers = [
            ("antigravity-cli", lambda: _invoke_cli(prompt, model=agy_model, timeout=gw_timeout)),
            ("gateway", lambda: call_gateway(prompt, model=gw_model, timeout=gw_timeout)),
            ("copilot", lambda: call_copilot(prompt, model=cp_model, timeout=cp_timeout)),
            ("gemini-api", lambda: call_gemini_api(prompt, model=gemini_model, timeout=gw_timeout)),
        ]
    else:
        # For non-CLI models (e.g. qwen-local-primary on GPU, specialized ocr-primary), Gateway remains Tier 1
        tiers = [
            ("gateway", lambda: call_gateway(prompt, model=gw_model, timeout=gw_timeout)),
            ("antigravity-cli", lambda: _invoke_cli(prompt, model=agy_model, timeout=gw_timeout)),
            ("copilot", lambda: call_copilot(prompt, model=cp_model, timeout=cp_timeout)),
            ("gemini-api", lambda: call_gemini_api(prompt, model=gemini_model, timeout=gw_timeout)),
        ]

    # Apply Round-Robin Strategy
    if strategy == "round_robin":
        global _rr_index
        with _rr_lock:
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
    "call_antigravity_cli",
    "call_vision",
    "call_audio",
    "resolve_model",
    "STATIC_LATEST_GEMINI_FLASH",
    "strip_think_tags",
    "encode_image",
]
