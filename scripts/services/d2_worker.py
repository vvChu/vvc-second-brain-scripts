"""VvC Second Brain — D2 Vector Diagram Worker (v8.13.0).

Generates D2 vector diagrams via LLM, compiles to SVG using local d2 CLI
or Kroki HTTP fallback, and saves both .svg and .d2 files to attachments.

Usage:
    from services.d2_worker import trigger_d2_generation
    trigger_d2_generation("architecture.d2.svg", context_text)
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.prompts.services import D2_GENERATE
from services.diagram_base import (
    find_diagram_context,
    save_diagram_file,
    spawn_worker,
)

_logger = logging.getLogger("vvc.d2")

__all__ = [
    "trigger_d2_generation",
    "compile_d2_via_kroki",
    "compile_d2_to_svg",
    "_clean_d2",
]


def _clean_d2(raw: str) -> str:
    """Clean and extract D2 source code from LLM response.

    Strips markdown fences (```d2 ... ``` or ``` ... ```) and conversational filler,
    handling both closed and unclosed/truncated code fences.

    Args:
        raw: Raw LLM response string.

    Returns:
        Clean D2 source code string.
    """
    raw = raw.strip()
    if not raw:
        return ""
    # Match fenced block with optional closing fence or end-of-string
    match = re.search(r"```(?:d2)?\s*\n?(.*?)(?:\n?```|\Z)", raw, re.DOTALL | re.IGNORECASE)
    if match and "```" in raw:
        cleaned = match.group(1).strip()
    else:
        cleaned = re.sub(r"^```(?:d2)?\s*\n?", "", raw, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    # Active guardrail: Tala is a commercial proprietary layout engine unsupported by Kroki
    cleaned = re.sub(r"layout-engine:\s*tala\b", "layout-engine: elk", cleaned, flags=re.IGNORECASE)
    return cleaned


def compile_d2_via_kroki(d2_code: str, timeout: float = 15.0) -> str:
    """Send HTTP POST to Kroki to compile D2 code to SVG.

    Zero third-party dependency via standard library urllib.request.

    Args:
        d2_code: Cleaned D2 source string.
        timeout: Request timeout in seconds (default 15s).

    Returns:
        SVG content string.

    Raises:
        RuntimeError: If Kroki request fails or returns non-200.
    """
    url = "https://kroki.io/d2/svg"
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "User-Agent": "VvC-SecondBrain-D2Worker/8.13.2 (Windows NT 10.0; Win64; x64)",
    }
    req = urllib.request.Request(
        url,
        data=d2_code.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Kroki D2 compilation failed: {e}") from e


def compile_d2_to_svg(
    d2_code: str,
    output_svg_path: Path | None = None,
    timeout: float = 15.0,
) -> str | None:
    """Compile D2 code to SVG via local CLI or Kroki fallback.

    Primary: if local d2 CLI exists on PATH (shutil.which("d2")), run `d2 - output.svg`.
    Fallback: send HTTP POST to https://kroki.io/d2/svg via urllib.request.

    Args:
        d2_code: Cleaned D2 source code.
        output_svg_path: Optional destination Path for the SVG file.
        timeout: Timeout in seconds.

    Returns:
        SVG content string, or None if compilation failed.
    """
    if not d2_code or not d2_code.strip():
        _logger.warning("Empty D2 code provided for compilation")
        return None

    if output_svg_path:
        output_svg_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Primary: local d2 CLI
    d2_bin = shutil.which("d2")
    if d2_bin:
        try:
            cmd = [d2_bin, "-", str(output_svg_path)] if output_svg_path else [d2_bin, "-", "-"]
            res = subprocess.run(
                cmd,
                input=d2_code.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=timeout,
            )
            if output_svg_path and output_svg_path.exists():
                return output_svg_path.read_text(encoding="utf-8")
            if res.stdout:
                return res.stdout.decode("utf-8")
        except Exception as e:
            _logger.warning(f"Local d2 CLI failed: {e}. Falling back to Kroki.")

    # 2. Fallback: Kroki HTTP API
    try:
        svg_content = compile_d2_via_kroki(d2_code, timeout=timeout)
        if output_svg_path:
            output_svg_path.parent.mkdir(parents=True, exist_ok=True)
            output_svg_path.write_text(svg_content, encoding="utf-8")
        return svg_content
    except Exception as e:
        _logger.error(f"D2 compilation failed on both local CLI and Kroki: {e}")
        return None


def trigger_d2_generation(diagram_name: str, source_text: str) -> None:
    """Trigger background D2 vector diagram generation.

    Args:
        diagram_name: Target diagram filename (e.g. "flow.d2.svg").
        source_text: Surrounding markdown text containing diagram placeholder.
    """
    spawn_worker(
        target=_generate_d2,
        args=(diagram_name, source_text),
        name=f"d2-{diagram_name}",
    )


def _generate_d2(diagram_name: str, source_text: str) -> None:
    """Worker function: extract context, generate D2 code, compile to SVG, and save."""
    # Sanitize diagram name (strip pipe options if present)
    diagram_name = diagram_name.split("|")[0].strip()
    if not diagram_name:
        return

    context = find_diagram_context(diagram_name, source_text)

    _logger.info(f"Generating D2 diagram: {diagram_name}")
    log("diagram", f"D2 generation started: {diagram_name}")

    prompt = D2_GENERATE.format(context=context)
    d2_code = call_llm(prompt, task="synthesis")

    if not d2_code:
        log("error", f"D2 generation failed: {diagram_name}")
        return

    d2_code = _clean_d2(d2_code)
    if not d2_code:
        log("error", f"D2 validation failed: {diagram_name}")
        return

    # Derive filenames: e.g. "arch.d2.svg" -> "arch.d2", "arch.svg" -> "arch.d2"
    if diagram_name.endswith(".d2.svg"):
        d2_filename = diagram_name[:-4]
    elif diagram_name.endswith(".svg"):
        d2_filename = diagram_name[:-4] + ".d2"
    else:
        d2_filename = f"{diagram_name}.d2"

    attachments_dir = cfg.attachments_dir
    attachments_dir.mkdir(parents=True, exist_ok=True)

    # Save raw .d2 code alongside for versioning and user inspection
    d2_path = attachments_dir / d2_filename
    try:
        d2_path.write_text(d2_code, encoding="utf-8")
        _logger.info(f"Saved raw D2 code: {d2_path.name}")
    except OSError as e:
        _logger.warning(f"Failed to save raw D2 file {d2_path.name}: {e}")

    # Compile D2 to SVG
    svg_path = attachments_dir / diagram_name
    svg_content = compile_d2_to_svg(d2_code, output_svg_path=svg_path)

    if not svg_content:
        log("error", f"D2 compilation failed: {diagram_name}")
        return

    # Ensure diagram file is recorded via save_diagram_file
    save_diagram_file(diagram_name, svg_content, "d2")
