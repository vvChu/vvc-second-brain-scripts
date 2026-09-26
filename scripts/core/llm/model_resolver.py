"""VvC Second Brain — Dynamic LLM Model Resolver.

Resolves dynamic model aliases (e.g. 'latest', 'auto', 'gemini-latest-low')
to the highest available Gemini Flash version by querying AI Gateway / Google API
with 24-hour persistent caching and static fallback protection.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm.utils import http_session

_logger = logging.getLogger("vvc.llm.resolver")

STATIC_LATEST_GEMINI_FLASH: str = "gemini-3.8-flash-high"
CACHE_TTL_SECONDS: int = 86400  # 24 hours

DYNAMIC_MODEL_PATTERN = re.compile(
    r"^(?:gemini-)?(?:flash-)?(?:latest|auto)(?:-flash)?(?:-(high|medium|low|lite))?$",
    re.IGNORECASE,
)

GEMINI_FLASH_VERSION_PATTERN = re.compile(
    r"^(?:models/)?gemini-(\d+(?:\.\d+)*)-flash(?:-([a-zA-Z0-9_-]+))?$",
    re.IGNORECASE,
)


def _get_cache_path() -> Path:
    """Resolve path to .models_cache.json in state dir."""
    if hasattr(cfg, "state_dir") and cfg.state_dir:
        state_dir = Path(cfg.state_dir)
    else:
        state_dir = Path(__file__).resolve().parent.parent.parent / ".state"
    return state_dir / ".models_cache.json"


def load_models_cache(cache_path: Path | None = None) -> dict[str, Any] | None:
    """Load models cache if it exists and contains valid data.

    Args:
        cache_path: Optional custom path to cache file.

    Returns:
        Dict with 'timestamp' and 'models' keys, or None if invalid/missing.
    """
    path = cache_path or _get_cache_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "timestamp" in data and "models" in data:
            return data
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning(f"Error reading model cache {path}: {e}")
    return None


def save_models_cache(models: list[str], cache_path: Path | None = None) -> None:
    """Save models list to cache atomically with current timestamp.

    Args:
        models: List of model identifier strings.
        cache_path: Optional custom path to cache file.
    """
    path = cache_path or _get_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        data = {
            "timestamp": time.time(),
            "models": models,
        }
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(path)
    except OSError as e:
        _logger.warning(f"Error saving model cache {path}: {e}")


def parse_version_tuple(version_str: str) -> tuple[int, ...]:
    """Parse version string '3.8' or '3.10.1' into a tuple of ints.

    Args:
        version_str: Dot-separated version numbers.

    Returns:
        Tuple of integers for accurate numeric comparison.
    """
    try:
        return tuple(int(part) for part in version_str.split("."))
    except ValueError:
        return (0,)


def find_highest_gemini_flash(models: list[str]) -> tuple[tuple[int, ...], str, list[str]] | None:
    """Find the highest Gemini Flash version from a list of model identifiers.

    Args:
        models: List of model identifiers.

    Returns:
        Tuple of (version_tuple, version_string, list_of_matching_model_ids) or None.
    """
    version_map: dict[tuple[int, ...], tuple[str, list[str]]] = {}
    for m in models:
        m_clean = m.strip()
        match = GEMINI_FLASH_VERSION_PATTERN.match(m_clean)
        if match:
            v_str = match.group(1)
            v_tuple = parse_version_tuple(v_str)
            if v_tuple not in version_map:
                version_map[v_tuple] = (v_str, [])
            version_map[v_tuple][1].append(m_clean)

    if not version_map:
        return None

    highest_v = max(version_map.keys())
    v_str, matched_models = version_map[highest_v]
    return highest_v, v_str, matched_models


def _fetch_models_from_gateway(gateway_url: str, api_key: str) -> list[str]:
    """Query AI Gateway for list of available models."""
    endpoint = f"{gateway_url.rstrip('/')}/models"
    headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    models: list[str] = []
    try:
        resp = http_session.get(endpoint, headers=headers, timeout=2.5)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data") or data.get("models") or []
            for item in items:
                mid = (item.get("id") or item.get("name")) if isinstance(item, dict) else item
                if mid:
                    models.append(str(mid))
    except Exception as e:
        _logger.debug(f"[model_resolver] Gateway query failed: {e}")
    return models


def _fetch_models_from_gemini_api(gemini_key: str) -> list[str]:
    """Query Gemini API directly for available models."""
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
    models: list[str] = []
    try:
        resp = http_session.get(endpoint, timeout=2.5)
        if resp.status_code == 200:
            items = resp.json().get("models") or []
            for item in items:
                mid = (item.get("name") or item.get("id")) if isinstance(item, dict) else item
                if mid:
                    models.append(str(mid).removeprefix("models/"))
    except Exception as e:
        _logger.debug(f"[model_resolver] Gemini API query failed: {e}")
    return models


def fetch_available_models(
    force_refresh: bool = False, cache_path: Path | None = None
) -> list[str]:
    """Fetch available models from Gateway or Gemini API, utilizing 24h cache."""
    path = cache_path or _get_cache_path()
    cached = load_models_cache(path)
    if not force_refresh and cached:
        cache_age = time.time() - cached.get("timestamp", 0)
        if cache_age < CACHE_TTL_SECONDS and cached.get("models"):
            _logger.debug(f"Using cached model list (age: {cache_age:.0f}s)")
            return cached["models"]

    gateway_url = getattr(cfg, "gateway_url", "")
    if gateway_url:
        models = _fetch_models_from_gateway(gateway_url, getattr(cfg, "gateway_api_key", ""))
        if models:
            _logger.info(f"[model_resolver] Discovered {len(models)} models from Gateway")
            save_models_cache(models, path)
            return models

    gemini_key = getattr(cfg, "gemini_api_key", "")
    if gemini_key:
        models = _fetch_models_from_gemini_api(gemini_key)
        if models:
            _logger.info(f"[model_resolver] Discovered {len(models)} models from Gemini API")
            save_models_cache(models, path)
            return models

    if cached and cached.get("models"):
        _logger.warning("[model_resolver] Network unreachable; using stale models cache")
        return cached["models"]

    return []


def is_dynamic_model(model_name: str) -> bool:
    """Check if model_name is an alias for latest/auto resolution."""
    if not model_name:
        return False
    return bool(DYNAMIC_MODEL_PATTERN.match(model_name.strip()))


def _determine_target_tier(specified_tier: str | None, task: str, default_tier: str) -> str:
    """Determine target tier suffix based on explicit specification or task category."""
    if specified_tier:
        return specified_tier.lower()
    if task in ("synthesis", "reasoning"):
        return "high"
    if task in ("vision", "fast", "ocr", "correction"):
        return "low"
    return default_tier or "high"


def resolve_model(
    model_name: str,
    task: str = "general",
    default_tier: str = "high",
    *,
    force_refresh: bool = False,
    cache_path: Path | None = None,
) -> str:
    """Dynamically resolve model name to latest version when aliases are used."""
    if not model_name:
        return ""
    model_clean = model_name.strip()
    match = DYNAMIC_MODEL_PATTERN.match(model_clean)
    if not match:
        return model_clean

    target_tier = _determine_target_tier(match.group(1), task, default_tier)
    models = fetch_available_models(force_refresh=force_refresh, cache_path=cache_path)
    highest_result = find_highest_gemini_flash(models) if models else None

    if highest_result:
        return f"gemini-{highest_result[1]}-flash-{target_tier}"
    if target_tier and target_tier != "high":
        return f"gemini-3.8-flash-{target_tier}"
    return STATIC_LATEST_GEMINI_FLASH
