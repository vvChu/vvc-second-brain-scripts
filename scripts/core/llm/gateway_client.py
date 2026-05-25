"""VvC Second Brain — Gateway LLM Client.

Tier 1 logic for AI Gateway via LiteLLM.
"""

import logging
from core.config import cfg
from core.llm.utils import http_session, strip_think_tags

_logger = logging.getLogger("vvc.llm.gateway")

def call_gateway(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via AI Gateway (LiteLLM on Server Spark)."""
    if not cfg.gateway_url:
        return ""

    try:
        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or cfg.gateway_proxy_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        resp = http_session.post(
            f"{cfg.gateway_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        
        # Log actual routed model from LiteLLM headers
        actual_model = resp.headers.get("x-litellm-model", "")
        api_base = resp.headers.get("x-litellm-model-api-base", "")
        if actual_model:
            _logger.info(f"[Gateway] Routed to: {actual_model} (Base: {api_base})")
            
        content = resp.json()["choices"][0]["message"]["content"]
        return strip_think_tags(content)
    except Exception as e:
        _logger.warning(f"Gateway HTTP error: {e}")
        return ""


def call_gateway_vision(image_b64: str, prompt: str, *, model: str = "", timeout: int = 300) -> str:
    """Call vision model via AI Gateway."""
    if not cfg.gateway_url:
        return ""

    try:
        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or cfg.gateway_direct_model or cfg.gateway_proxy_model,
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
