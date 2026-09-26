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
    # Linux fallback
    linux_fallback = Path.home() / ".local" / "bin" / "agy"
    if linux_fallback.exists():
        return str(linux_fallback)
    # Windows fallback
    fallback = Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
    if fallback.exists():
        return str(fallback)
    return cmd or "agy"


def _find_artifact_by_uri(text: str, full_stdout: str) -> Path | None:
    """Find and return valid Path if text or stdout contains local markdown file URI."""
    _URI_PATTERN = (
        r"file://(?:localhost)?(?:/([a-zA-Z]:[^\s\)\"'\<]+?\.md)|"
        r"([a-zA-Z]:[^\s\)\"'\<]+?\.md)|(/+[^\s\)\"'\<]+?\.md))"
    )
    match = re.search(_URI_PATTERN, text) or (
        re.search(_URI_PATTERN, full_stdout) if full_stdout else None
    )
    if not match:
        return None
    raw_path = match.group(1) or match.group(2) or match.group(3)
    p = Path(raw_path.replace("%20", " "))
    return p if (p.exists() and p.is_file()) else None


def _find_fallback_artifact(
    min_mtime: float, brain_dir: Path | None, max_age_seconds: int
) -> Path | None:
    """Scan brain directory for recently created large markdown artifact."""
    target_brain = brain_dir or (Path.home() / ".gemini" / "antigravity-cli" / "brain")
    if not (target_brain.exists() and target_brain.is_dir()):
        return None
    threshold = min_mtime if min_mtime > 0.0 else (time.time() - max_age_seconds)
    candidates: list[tuple[float, Path]] = []
    for p in target_brain.rglob("*.md"):
        if ".system_generated" in p.parts or p.name.startswith(".") or p.name == "content.md":
            continue
        try:
            stat = p.stat()
            if stat.st_mtime >= threshold and stat.st_size >= 10000:
                candidates.append((stat.st_mtime, p))
        except OSError:
            continue
    if candidates:
        candidates.sort(key=lambda c: -c[0])
        return candidates[0][1]
    return None


def _resolve_cli_artifact_content(
    text: str,
    full_stdout: str = "",
    *,
    min_mtime: float = 0.0,
    brain_dir: Path | None = None,
    max_age_seconds: int = 600,
) -> str:
    """Detect and ingest artifact file content if CLI agent outputted a reference link."""
    if not text or len(text) > 5000:
        return text

    artifact_path = _find_artifact_by_uri(text, full_stdout)
    if not artifact_path and (min_mtime > 0.0 or brain_dir is not None):
        try:
            artifact_path = _find_fallback_artifact(min_mtime, brain_dir, max_age_seconds)
        except Exception as e:
            _logger.debug(f"[Antigravity CLI] Fallback artifact scan skipped: {e}")

    if artifact_path:
        try:
            content = artifact_path.read_text(encoding="utf-8").strip()
            if len(content) > len(text) * 2:
                _logger.info(
                    f"[Antigravity CLI] Ingested artifact from {artifact_path.name} "
                    f"({len(content)} chars vs {len(text)} chars summary)"
                )
                return content
        except OSError as e:
            _logger.warning(f"[Antigravity CLI] Failed to read artifact file {artifact_path}: {e}")

    return text


def _build_cli_args(
    cmd: str, target_model: str, prompt: str, timeout: int, use_stream_json: bool
) -> tuple[list[str], str | None]:
    """Construct commandline arguments and payload for Antigravity CLI invocation."""
    args = [cmd, "--model", target_model]
    if use_stream_json:
        args.extend(
            ["--input-format", "stream-json", "--output-format", "stream-json", "--disable-slash-commands"]
        )
        if timeout > 300:
            args.extend(["--print-timeout", f"{timeout}s"])
        return args, json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"

    args.extend(["--output-format", "json", "--disable-slash-commands"])
    if timeout > 300:
        args.extend(["--print-timeout", f"{timeout}s"])
    args.extend(["-p", prompt])
    return args, None


def _extract_cli_json_payload(data: dict) -> tuple[str, str]:
    """Extract status and response text from parsed CLI JSON event."""
    status = data.get("status", "")
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
    return status, resp_text


def _parse_stream_json_stdout(stdout: str) -> str:
    """Parse NDJSON lines from stream-json CLI execution."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict) and data.get("event") == "result":
                res = data.get("result", {})
                status, resp_text = _extract_cli_json_payload(res)
                if status and status != "SUCCESS":
                    _logger.warning(f"[Antigravity CLI] Execution status: {status}")
                    return ""
                return resp_text
        except json.JSONDecodeError:
            continue
    _logger.warning("[Antigravity CLI] No valid result event found in stream-json output")
    return ""


def _parse_print_json_stdout(stdout: str) -> str:
    """Parse single JSON payload from print mode CLI execution."""
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            status, resp_text = _extract_cli_json_payload(data)
            if status and status != "SUCCESS":
                _logger.warning(f"[Antigravity CLI] Execution status: {status}")
                return ""
            return resp_text
    except json.JSONDecodeError:
        _logger.debug("[Antigravity CLI] Output is not JSON, falling back to raw text.")
    return stdout


def _resolve_cli_target_model(model: str, timeout: int) -> tuple[str, int]:
    """Resolve target model and adjust reasoning timeout if needed."""
    target_model = resolve_model(model or cfg.gemini_model, task="general")
    if re.match(r"^gemini-\d+(?:\.\d+)*-flash$", target_model) or target_model in (
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"
    ):
        target_model = f"{target_model}-high"

    effective_timeout = (
        getattr(cfg, "reasoning_timeout", 600)
        if (("thinking" in target_model.lower() or "opus" in target_model.lower()) and timeout <= 60)
        else timeout
    )
    return target_model, effective_timeout


def _run_cli_subprocess(
    args: list[str], input_payload: str | None, timeout: int
) -> tuple[int, str, str]:
    """Execute CLI process and return (returncode, stdout, stderr)."""
    kwargs: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    )
    result = subprocess.run(
        args,
        input=input_payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        cwd=str(Path(__file__).parent.parent.parent),
        **kwargs,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def call_gemini_cli(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via Google Antigravity CLI (agy.exe) with native JSON bridge."""
    cmd = _resolve_cli_path()
    if not cmd:
        return ""

    target_model, effective_timeout = _resolve_cli_target_model(model, timeout)
    use_stream_json = len(prompt) > 30000
    mode_label = "stream-json (stdin)" if use_stream_json else "print (-p)"
    _logger.info(f"[Antigravity CLI] Routed to: {target_model} | Mode: {mode_label} ({len(prompt)} chars)")

    try:
        args, input_payload = _build_cli_args(cmd, target_model, prompt, effective_timeout, use_stream_json)
        start_time = time.time()
        retcode, stdout, stderr = _run_cli_subprocess(args, input_payload, effective_timeout)
        if retcode != 0:
            err = stderr[:200] if stderr else "unknown error"
            _logger.warning(f"[Antigravity CLI] Non-zero exit code ({retcode}): {err}")
            return ""

        if not stdout:
            return ""

        raw_text = (
            _parse_stream_json_stdout(stdout)
            if use_stream_json
            else _parse_print_json_stdout(stdout)
        )
        if not raw_text:
            return ""
        return _resolve_cli_artifact_content(
            strip_think_tags(raw_text.strip()), full_stdout=stdout, min_mtime=start_time - 5.0
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
        # Exclude non-text modalities (image generation, embedding, specialized OCR) and unsupported lite models
        if any(sub in clean for sub in ("-image", "embedding", "embed", "vision", "ocr", "-lite")):
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
