"""VvC Second Brain — Gemini Client.

Tier 3 logic for Gemini CLI and direct REST API.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm.utils import http_session, strip_think_tags

_logger = logging.getLogger("vvc.llm.gemini")

def call_gemini_cli(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via Gemini CLI (OAuth-authenticated)."""
    cmd = cfg.gemini_cmd
    if not cmd:
        return ""

    target_model = model or cfg.gemini_model
    _logger.info(f"[Gemini CLI] Routed to: {target_model}")
    try:
        # To bypass cmd.exe's 8191 character limit and utilize CreateProcessW's 32767 limit,
        # we directly invoke node.exe with the gemini.js path instead of using gemini.cmd.
        if cmd.endswith(".cmd"):
            js_path = Path(cmd).parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
            if js_path.exists():
                args = ["node", str(js_path), "-m", target_model, "-p", prompt]
            else:
                args = [cmd, "-m", target_model, "-p", prompt]
        else:
            args = [cmd, "-m", target_model, "-p", prompt]

        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            # Windows command line limit is technically 8191 for cmd.exe, or 32767 for CreateProcess.
            if len(prompt) > 30000:
                _logger.warning("Prompt length exceeds CreateProcessW limits. Skipping Gemini CLI to prevent WinError 206.")
                return ""

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent.parent),
            **kwargs,
        )
        if result.returncode == 0 and result.stdout.strip():
            return strip_think_tags(result.stdout.strip())
        return ""
    except subprocess.TimeoutExpired:
        _logger.warning("Gemini CLI timed out")
        return ""
    except Exception as e:
        _logger.warning(f"Gemini CLI error: {e}")
        return ""


def call_gemini_api(
    prompt: str,
    *,
    model: str = "",
    image_b64: str = "",
    timeout: int = 60,
) -> str:
    """Call Gemini REST API directly (for vision and text)."""
    api_key = cfg.gemini_api_key
    if not api_key:
        return ""

    target_model = model or cfg.gemini_vision_model
    _logger.info(f"[Gemini API] Routed to: {target_model}")
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={api_key}"

        parts: list[dict[str, Any]] = [{"text": prompt}]
        if image_b64:
            parts.insert(0, {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_b64,
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            },
        }

        resp = http_session.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if candidates:
            content_parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in content_parts)
            return strip_think_tags(text)
        return ""
    except Exception as e:
        _logger.warning(f"Gemini API error: {e}")
        return ""
