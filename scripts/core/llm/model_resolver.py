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


def fetch_available_models(force_refresh: bool = False, cache_path: Path | None = None) -> list[str]:
    """Fetch available models from Gateway or Gemini API, utilizing 24h cache.

    Args:
        force_refresh: Bypass cache if True.
        cache_path: Optional custom path to cache file.

    Returns:
        List of discovered model identifiers.
    """
    path = cache_path or _get_cache_path()

    # 1. Check cache if not force_refresh
    cached = load_models_cache(path)
    if not force_refresh and cached:
        cache_age = time.time() - cached.get("timestamp", 0)
        if cache_age < CACHE_TTL_SECONDS and cached.get("models"):
            _logger.debug(f"Using cached model list (age: {cache_age:.0f}s)")
            return cached["models"]

    models: list[str] = []

    # 2. Try Gateway /models endpoint
    gateway_url = getattr(cfg, "gateway_url", "")
    if gateway_url:
        endpoint = f"{gateway_url.rstrip('/')}/models"
        headers: dict[str, str] = {}
        api_key = getattr(cfg, "gateway_api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            resp = http_session.get(endpoint, headers=headers, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("models") or []
                for item in items:
                    if isinstance(item, dict):
                        mid = item.get("id") or item.get("name")
                        if mid:
                            models.append(str(mid))
                    elif isinstance(item, str):
                        models.append(item)
                if models:
                    _logger.info(f"[model_resolver] Discovered {len(models)} models from Gateway")
                    save_models_cache(models, path)
                    return models
        except Exception as e:
            _logger.debug(f"[model_resolver] Gateway query failed: {e}")

    # 3. Try Direct Gemini API models endpoint as secondary source
    gemini_key = getattr(cfg, "gemini_api_key", "")
    if gemini_key:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
        try:
            resp = http_session.get(endpoint, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("models") or []
                for item in items:
                    if isinstance(item, dict):
                        mid = item.get("name") or item.get("id")
                        if mid:
                            clean_id = str(mid).removeprefix("models/")
                            models.append(clean_id)
                    elif isinstance(item, str):
                        models.append(item.removeprefix("models/"))
                if models:
                    _logger.info(f"[model_resolver] Discovered {len(models)} models from Gemini API")
                    save_models_cache(models, path)
                    return models
        except Exception as e:
            _logger.debug(f"[model_resolver] Gemini API query failed: {e}")

    # 4. Fall back to stale cache if available
    if cached and cached.get("models"):
        _logger.warning("[model_resolver] Network unreachable; using stale models cache")
        return cached["models"]

    return []


def is_dynamic_model(model_name: str) -> bool:
    """Check if model_name is an alias for latest/auto resolution.

    Args:
        model_name: Model identifier or alias.

    Returns:
        True if the name matches dynamic aliases, False otherwise.
    """
    if not model_name:
        return False
    return bool(DYNAMIC_MODEL_PATTERN.match(model_name.strip()))


def resolve_model(
    model_name: str,
    task: str = "general",
    default_tier: str = "high",
    *,
    force_refresh: bool = False,
    cache_path: Path | None = None,
) -> str:
    """Dynamically resolve model name to latest version when aliases are used.

    If model_name is explicit (e.g. 'gemini-3.8-flash-high', 'claude-opus-4-6-thinking'),
    it passes through untouched.

    If model_name is 'latest', 'auto', 'gemini-latest', 'gemini-flash-latest',
    'gemini-latest-low', etc., it queries cached/live models to find the highest
    Gemini Flash version and applies the requested or task-appropriate tier.

    Args:
        model_name: Name or alias of the model.
        task: Task category ('synthesis', 'reasoning', 'vision', 'fast', 'correction', 'general').
        default_tier: Fallback tier ('high', 'medium', 'low') if not specified in model_name or task.
        force_refresh: Whether to bypass the 24h cache.
        cache_path: Optional custom cache file path (used in testing).

    Returns:
        Resolved model identifier string.
    """
    if not model_name:
        return ""

    model_clean = model_name.strip()
    match = DYNAMIC_MODEL_PATTERN.match(model_clean)
    if not match:
        return model_clean

    specified_tier = match.group(1)
    if specified_tier:
        target_tier = specified_tier.lower()
    else:
        if task in ("synthesis", "reasoning"):
            target_tier = "high"
        elif task in ("vision", "fast", "ocr", "correction"):
            target_tier = "low"
        else:
            target_tier = default_tier or "high"

    models = fetch_available_models(force_refresh=force_refresh, cache_path=cache_path)
    highest_result = find_highest_gemini_flash(models) if models else None

    if highest_result:
        _, v_str, _ = highest_result
        return f"gemini-{v_str}-flash-{target_tier}"

    if target_tier and target_tier != "high":
        return f"gemini-3.8-flash-{target_tier}"
    return STATIC_LATEST_GEMINI_FLASH
