"""VvC Second Brain — Gemini Client.

Tier 3 logic for Gemini CLI and direct REST API.
"""

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm.utils import http_session, strip_think_tags

_logger = logging.getLogger("vvc.llm.gemini")

def _resolve_cli_path() -> str:
    """Resolve absolute path to Antigravity CLI (agy.exe)."""
    cmd = cfg.gemini_cmd
    if cmd and Path(cmd).exists():
        return cmd
    which_agy = shutil.which("agy")
    if which_agy:
        return which_agy
    fallback = Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
    if fallback.exists():
        return str(fallback)
    return cmd or "agy"


def call_gemini_cli(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via Google Antigravity CLI (agy.exe) with native JSON bridge."""
    cmd = _resolve_cli_path()
    if not cmd:
        return ""

    target_model = model or cfg.gemini_model
    # Normalize reasoning tier suffix for flash models if not explicitly set
    if target_model in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"):
        target_model = f"{target_model}-high"

    _logger.info(f"[Antigravity CLI] Routed to: {target_model}")
    try:
        # Build arguments for Antigravity CLI (Headless / Print Mode with JSON output)
        args = [
            cmd,
            "--model", target_model,
            "--output-format", "json",
            "--disable-slash-commands",
            "-p", prompt,
        ]

        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            # Windows CreateProcessW character limit guard
            if len(prompt) > 30000:
                _logger.warning("Prompt length exceeds CreateProcessW limits. Skipping Antigravity CLI to prevent WinError 206.")
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

        if result.returncode != 0:
            err_snippet = result.stderr.strip()[:200] if result.stderr else "unknown error"
            _logger.warning(f"[Antigravity CLI] Non-zero exit code ({result.returncode}): {err_snippet}")
            return ""

        stdout = result.stdout.strip()
        if not stdout:
            return ""

        # Parse JSON response from agy.exe
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                status = data.get("status", "")
                if status and status != "SUCCESS":
                    _logger.warning(f"[Antigravity CLI] Execution status: {status}")
                    return ""

                resp_text = data.get("response", "")
                duration = data.get("duration_seconds", 0)
                usage = data.get("usage", {})
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                think_tok = usage.get("thinking_tokens", 0)
                cached_tok = usage.get("cache_read_tokens", 0)

                _logger.info(
                    f"[Antigravity CLI] Done in {duration:.2f}s | "
                    f"Tokens: {in_tok} in, {out_tok} out, {think_tok} think, {cached_tok} cached"
                )
                return strip_think_tags(resp_text.strip())
        except json.JSONDecodeError:
            _logger.debug("[Antigravity CLI] Output is not JSON, falling back to raw text.")

        return strip_think_tags(stdout)
    except subprocess.TimeoutExpired:
        _logger.warning("Antigravity CLI timed out")
        return ""
    except Exception as e:
        _logger.warning(f"Antigravity CLI error: {e}")
        return ""


call_antigravity_cli = call_gemini_cli


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
