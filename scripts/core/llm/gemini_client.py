"""VvC Second Brain — Gemini Client.

Tier 3 logic for Gemini CLI and direct REST API.
"""

import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm.utils import http_session, strip_think_tags
from core.llm.model_resolver import resolve_model

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


def _resolve_cli_artifact_content(
    text: str,
    full_stdout: str = "",
    *,
    min_mtime: float = 0.0,
    brain_dir: Path | None = None,
    max_age_seconds: int = 600,
) -> str:
    """Detect and ingest artifact file content if CLI agent outputted a reference link instead of full text."""
    if not text or len(text) > 5000:
        return text

    # 1. Search for local .md file URI inside text: file:///C:/... or file://C:/...
    match = re.search(r"file:///([a-zA-Z]:[^\s\)\"'>]+?\.md)", text)
    if not match:
        match = re.search(r"file://([a-zA-Z]:[^\s\)\"'>]+?\.md)", text)

    # 2. Search within full_stdout if available
    if not match and full_stdout:
        match = re.search(r"file:///([a-zA-Z]:[^\s\)\"'>]+?\.md)", full_stdout)
        if not match:
            match = re.search(r"file://([a-zA-Z]:[^\s\)\"'>]+?\.md)", full_stdout)

    if match:
        artifact_path_str = match.group(1).replace("%20", " ")
        artifact_path = Path(artifact_path_str)
        if artifact_path.exists() and artifact_path.is_file():
            try:
                artifact_content = artifact_path.read_text(encoding="utf-8").strip()
                if len(artifact_content) > len(text) * 2:
                    _logger.info(
                        f"[Antigravity CLI] Ingested full artifact content from {artifact_path.name} "
                        f"({len(artifact_content)} chars vs {len(text)} chars summary)"
                    )
                    return artifact_content
            except OSError as e:
                _logger.warning(f"[Antigravity CLI] Failed to read artifact file {artifact_path}: {e}")

    # 3. Fallback scan: If min_mtime or brain_dir is provided, scan for recently created large artifact (.md >= 10KB)
    if min_mtime > 0.0 or brain_dir is not None:
        try:
            target_brain = brain_dir or (Path.home() / ".gemini" / "antigravity-cli" / "brain")
            if target_brain.exists() and target_brain.is_dir():
                now = time.time()
                threshold_time = min_mtime if min_mtime > 0.0 else (now - max_age_seconds)
                candidates = []
                for p in target_brain.rglob("*.md"):
                    if ".system_generated" in p.parts or p.name.startswith(".") or p.name == "content.md":
                        continue
                    try:
                        stat = p.stat()
                        if stat.st_mtime >= threshold_time and stat.st_size >= 10000:
                            candidates.append((stat.st_mtime, stat.st_size, p))
                    except OSError:
                        continue
                if candidates:
                    candidates.sort(key=lambda c: c[0], reverse=True)
                    best_path = candidates[0][2]
                    try:
                        artifact_content = best_path.read_text(encoding="utf-8").strip()
                        if len(artifact_content) > len(text) * 2:
                            _logger.info(
                                f"[Antigravity CLI] Ingested fallback artifact from {best_path.name} "
                                f"({len(artifact_content)} chars vs {len(text)} chars summary)"
                            )
                            return artifact_content
                    except OSError as e:
                        _logger.warning(f"[Antigravity CLI] Failed to read fallback artifact {best_path}: {e}")
        except Exception as e:
            _logger.debug(f"[Antigravity CLI] Fallback artifact scan skipped: {e}")

    return text


def call_gemini_cli(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via Google Antigravity CLI (agy.exe) with native JSON bridge.

    Supports automatic streaming via stdin (stream-json) when prompt > 30,000 chars
    to bypass Win32 CreateProcessW character limits.
    """
    cmd = _resolve_cli_path()
    if not cmd:
        return ""

    target_model = resolve_model(model or cfg.gemini_model, task="general")
    # Normalize reasoning tier suffix for flash models if not explicitly set
    if re.match(r"^gemini-\d+(?:\.\d+)*-flash$", target_model) or target_model in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"):
        target_model = f"{target_model}-high"

    # For reasoning/thinking models with default short timeout, elevate to reasoning_timeout
    effective_timeout = timeout
    if ("thinking" in target_model.lower() or "opus" in target_model.lower()) and timeout <= 60:
        effective_timeout = getattr(cfg, "reasoning_timeout", 600)

    use_stream_json = len(prompt) > 30000
    mode_label = "stream-json (stdin)" if use_stream_json else "print (-p)"
    _logger.info(f"[Antigravity CLI] Routed to: {target_model} | Mode: {mode_label} ({len(prompt)} chars)")

    try:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        if use_stream_json:
            # Stream large prompt via stdin to bypass Windows CreateProcessW limits
            args = [
                cmd,
                "--model", target_model,
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--disable-slash-commands",
            ]
            if effective_timeout and effective_timeout > 300:
                args.extend(["--print-timeout", f"{effective_timeout}s"])
            input_payload: str | None = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        else:
            args = [
                cmd,
                "--model", target_model,
                "--output-format", "json",
                "--disable-slash-commands",
            ]
            if effective_timeout and effective_timeout > 300:
                args.extend(["--print-timeout", f"{effective_timeout}s"])
            args.extend(["-p", prompt])
            input_payload = None

        start_time = time.time()
        result = subprocess.run(
            args,
            input=input_payload,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
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

        if use_stream_json:
            # Parse NDJSON lines to find the 'result' event
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and data.get("event") == "result":
                        res = data.get("result", {})
                        status = res.get("status", "")
                        if status and status != "SUCCESS":
                            _logger.warning(f"[Antigravity CLI] Execution status: {status}")
                            return ""

                        resp_text = res.get("response", "")
                        duration = res.get("duration_seconds", 0)
                        usage = res.get("usage", {})
                        in_tok = usage.get("input_tokens", 0)
                        out_tok = usage.get("output_tokens", 0)
                        think_tok = usage.get("thinking_tokens", 0)
                        cached_tok = usage.get("cache_read_tokens", 0)

                        _logger.info(
                            f"[Antigravity CLI] Done in {duration:.2f}s | "
                            f"Tokens: {in_tok} in, {out_tok} out, {think_tok} think, {cached_tok} cached"
                        )
                        return _resolve_cli_artifact_content(
                            strip_think_tags(resp_text.strip()),
                            full_stdout=stdout,
                            min_mtime=start_time - 5.0,
                        )
                except json.JSONDecodeError:
                    continue
            _logger.warning("[Antigravity CLI] No valid result event found in stream-json output")
            return ""
        else:
            # Parse single JSON response from agy.exe
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
                    return _resolve_cli_artifact_content(
                        strip_think_tags(resp_text.strip()),
                        full_stdout=stdout,
                        min_mtime=start_time - 5.0,
                    )
            except json.JSONDecodeError:
                _logger.debug("[Antigravity CLI] Output is not JSON, falling back to raw text.")

            return _resolve_cli_artifact_content(
                strip_think_tags(stdout),
                full_stdout=stdout,
                min_mtime=start_time - 5.0,
            )
    except subprocess.TimeoutExpired:
        _logger.warning("Antigravity CLI timed out")
        return ""
    except Exception as e:
        _logger.warning(f"Antigravity CLI error: {e}")
        return ""


call_antigravity_cli = call_gemini_cli

ANTIGRAVITY_CLI_SUPPORTED_PREFIXES = ("gemini-", "claude-", "gpt-oss")


def is_antigravity_cli_supported(model_name: str) -> bool:
    """Check if a model is natively supported by local Antigravity CLI (agy.exe)."""
    if not model_name:
        return False
    clean = model_name.lower().strip()
    if any(clean.startswith(p) for p in ANTIGRAVITY_CLI_SUPPORTED_PREFIXES):
        # Exclude non-text modalities (image generation, embedding, specialized OCR)
        if any(sub in clean for sub in ("-image", "embedding", "embed", "vision", "ocr")):
            return False
        return True
    return False


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

    target_model = resolve_model(model or cfg.gemini_vision_model, task="vision")
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
