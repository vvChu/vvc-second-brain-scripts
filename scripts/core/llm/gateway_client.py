"""VvC Second Brain — Gateway LLM Client.

Tier 1 logic for AI Gateway via LiteLLM.
"""

import logging
import time
from core.config import cfg
from core.llm.utils import http_session, strip_think_tags
from core.llm.model_resolver import resolve_model

_logger = logging.getLogger("vvc.llm.gateway")

CLAUDE_PROXY_PREFIXES = ("claude-",)
FALLBACK_GATEWAY_MODEL = "gemini-3.8-flash-high"

# Cooldown timestamp for Port 8045 circuit breaker
_proxy_cooldown_until: float = 0.0
_last_downgraded: bool = False


def consume_gateway_downgraded() -> bool:
    """Check and reset if the last gateway call was downgraded."""
    global _last_downgraded
    was = _last_downgraded
    _last_downgraded = False
    return was


def _is_proxy_model(model_name: str) -> bool:
    """Check if model should route to Port 8045 (Antigravity Proxy)."""
    clean = model_name.lower().strip()
    return any(clean.startswith(p) for p in CLAUDE_PROXY_PREFIXES)


def _post_chat_completion(base_url: str, api_key: str, model: str, prompt: str, timeout: int):
    """Helper to send OpenAI-compatible chat completion request."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    return http_session.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )


def call_gateway_with_meta(prompt: str, *, model: str = "", timeout: int = 60) -> tuple[str, bool]:
    """Call LLM via AI Gateway and return (response_text, was_downgraded).
    
    Routes claude-* models to Port 8045 (Antigravity Proxy).
    If Port 8045 is in cooldown or returns 503/429, gracefully downgrades
    to Gemini 3.8 Flash High on Port 8090 with was_downgraded=True.
    """
    global _proxy_cooldown_until, _last_downgraded
    if not cfg.gateway_url and not getattr(cfg, "gateway_proxy_url", ""):
        return "", False

    target_model = resolve_model(model or cfg.gateway_proxy_model, task="general")
    is_claude = _is_proxy_model(target_model)
    use_proxy = is_claude and bool(getattr(cfg, "gateway_proxy_url", ""))
    was_downgraded = False

    # Check circuit breaker cooldown for Port 8045
    if use_proxy and time.time() < _proxy_cooldown_until:
        _logger.warning(
            f"[Gateway] Port 8045 in cooldown until {_proxy_cooldown_until:.0f}. "
            f"Routing {target_model} -> {FALLBACK_GATEWAY_MODEL} on Port 8090..."
        )
        use_proxy = False
        target_model = FALLBACK_GATEWAY_MODEL
        was_downgraded = True

    base_url = cfg.gateway_proxy_url if use_proxy else cfg.gateway_url
    api_key = (getattr(cfg, "gateway_proxy_api_key", "") or cfg.gateway_api_key) if use_proxy else cfg.gateway_api_key

    try:
        resp = _post_chat_completion(base_url, api_key, target_model, prompt, timeout)

        # Handle 503 (Account limited) or 429 on Port 8045 -> Auto fallback to 8090
        if use_proxy and resp.status_code in (503, 429):
            _proxy_cooldown_until = time.time() + 30.0  # Cooldown 30s
            _logger.warning(
                f"[Gateway] Port 8045 returned {resp.status_code}. "
                f"Auto-downgrading {target_model} -> {FALLBACK_GATEWAY_MODEL} on Port 8090..."
            )
            resp = _post_chat_completion(
                cfg.gateway_url,
                cfg.gateway_api_key,
                FALLBACK_GATEWAY_MODEL,
                prompt,
                min(timeout, 120),
            )
            was_downgraded = True

        resp.raise_for_status()

        actual_model = resp.headers.get("x-litellm-model", "")
        api_base = resp.headers.get("x-litellm-model-api-base", "")
        if actual_model:
            _logger.info(f"[Gateway] Routed to: {actual_model} (Base: {api_base})")

        msg = resp.json()["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content") or ""
        if was_downgraded:
            _last_downgraded = True
        return strip_think_tags(content), was_downgraded
    except Exception as e:
        # Network or timeout error on 8045 -> Fallback attempt on 8090
        if is_claude and cfg.gateway_url and not was_downgraded:
            _proxy_cooldown_until = time.time() + 30.0
            _last_downgraded = True
            _logger.warning(
                f"[Gateway] Port 8045 error ({e}). Auto-downgrading to {FALLBACK_GATEWAY_MODEL} on Port 8090..."
            )
            try:
                resp = _post_chat_completion(
                    cfg.gateway_url,
                    cfg.gateway_api_key,
                    FALLBACK_GATEWAY_MODEL,
                    prompt,
                    min(timeout, 120),
                )
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                return strip_think_tags(content), True
            except Exception as e2:
                _logger.warning(f"[Gateway] Fallback on Port 8090 also failed: {e2}")

        _logger.warning(f"Gateway HTTP error: {e}")
        return "", was_downgraded


def call_gateway(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via AI Gateway (LiteLLM on 8090 or Antigravity Proxy on 8045)."""
    content, _ = call_gateway_with_meta(prompt, model=model, timeout=timeout)
    return content


def call_gateway_vision(image_b64: str, prompt: str, *, model: str = "", timeout: int = 300) -> str:
    """Call vision model via AI Gateway."""
    if not cfg.gateway_url:
        return ""

    try:
        raw_model = model or cfg.gateway_direct_model or cfg.gateway_proxy_model
        target_model = resolve_model(raw_model, task="vision")
        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": target_model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            "temperature": 0.1,
        }
        resp = http_session.post(
            f"{cfg.gateway_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        
        actual_model = resp.headers.get("x-litellm-model", "")
        api_base = resp.headers.get("x-litellm-model-api-base", "")
        if actual_model:
            _logger.info(f"[Gateway Vision] Routed to: {actual_model} (Base: {api_base})")
            
        content = resp.json()["choices"][0]["message"]["content"]
        return strip_think_tags(content)
    except Exception as e:
        _logger.warning(f"Gateway vision error: {e}")
        return ""
