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

def _resolve_tier_models(task: str, resolved_model: str) -> tuple[str, str, str, str]:
    """Resolve specific model names across all tiers for given task."""
    if task == "reasoning":
        gw_model = resolved_model or resolve_model(cfg.reasoning_gateway_model, task=task)
        agy_model = resolved_model or getattr(cfg, "reasoning_cli_model", "") or "claude-opus-4-6-thinking"
    elif task == "synthesis":
        gw_model = resolved_model or resolve_model(cfg.gateway_synthesis_model or "gemini-3.8-flash-high", task=task)
        agy_model = resolved_model or cfg.gemini_text_synthesis_model
    elif task == "correction":
        gw_model = resolved_model or resolve_model(cfg.gateway_correction_model, task=task)
        agy_model = resolved_model or cfg.gemini_text_correction_model
    else:
        gw_model = resolved_model or resolve_model(cfg.gateway_proxy_model, task=task)
        agy_model = resolved_model or cfg.gemini_model

    cp_model = resolved_model or (cfg.copilot_correction_model if task == "correction" else cfg.copilot_model)
    gemini_raw = resolved_model or (
        cfg.gemini_text_synthesis_model if task == "synthesis"
        else (cfg.gemini_text_correction_model if task == "correction" else cfg.gemini_model)
    )
    gemini_model = resolve_model(gemini_raw, task=task)
    return gw_model, agy_model, cp_model, gemini_model


def _build_tier_pipeline(
    prompt: str,
    gw_model: str,
    agy_model: str,
    cp_model: str,
    gemini_model: str,
    gw_timeout: int,
    cp_timeout: int,
    strategy: str,
) -> list[tuple[str, Callable[[], str]]]:
    """Assemble prioritized list of tier callable invokers."""
    use_cli_primary = is_antigravity_cli_supported(agy_model)
    cli_tier = ("antigravity-cli", lambda: _invoke_cli(prompt, model=agy_model, timeout=gw_timeout))
    gw_tier = ("gateway", lambda: call_gateway(prompt, model=gw_model, timeout=gw_timeout))
    cp_tier = ("copilot", lambda: call_copilot(prompt, model=cp_model, timeout=cp_timeout))
    api_tier = ("gemini-api", lambda: call_gemini_api(prompt, model=gemini_model, timeout=gw_timeout))

    tiers = [cli_tier, gw_tier, cp_tier, api_tier] if use_cli_primary else [gw_tier, cli_tier, cp_tier, api_tier]

    if strategy == "round_robin":
        global _rr_index
        with _rr_lock:
            start_idx = _rr_index % len(tiers)
            tiers = tiers[start_idx:] + tiers[:start_idx]
            _rr_index += 1
        _logger.debug(f"[llm] Round-Robin selected primary tier: {tiers[0][0]}")

    return tiers


def _execute_tier_pipeline(
    tiers: list[tuple[str, Callable[[], str]]],
    validator: Callable[[str], bool] | None,
    allowed_shorts: tuple[str, ...],
    min_length: int,
) -> str:
    """Iterate through tiers with validation and garbage checking."""
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
    """Call LLM with automatic 4-tier fallback routing."""
    gw_timeout = cfg.reasoning_timeout if task == "reasoning" else cfg.gemini_timeout
    cp_timeout = cfg.reasoning_timeout if task == "reasoning" else cfg.copilot_timeout
    resolved_model = resolve_model(model, task=task) if model else ""

    gw_model, agy_model, cp_model, gemini_model = _resolve_tier_models(task, resolved_model)
    tiers = _build_tier_pipeline(
        prompt, gw_model, agy_model, cp_model, gemini_model, gw_timeout, cp_timeout, strategy
    )
    return _execute_tier_pipeline(tiers, validator, allowed_shorts, min_length)

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
