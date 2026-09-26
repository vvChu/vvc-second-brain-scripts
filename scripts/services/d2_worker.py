"""VvC Second Brain — D2 Vector Diagram Worker (v8.13.0).

Generates D2 vector diagrams via LLM, compiles to SVG using local d2 CLI
or Kroki HTTP fallback, and saves both .svg and .d2 files to attachments.

Usage:
    from services.d2_worker import trigger_d2_generation
    trigger_d2_generation("architecture.d2.svg", context_text)
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
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
    save_fallback_diagram,
    spawn_worker,
)

_logger = logging.getLogger("vvc.d2")

__all__ = [
    "trigger_d2_generation",
    "compile_d2_via_kroki",
    "compile_d2_to_svg",
    "compile_d2",
    "find_d2_bin",
    "sanitize_d2_for_kroki",
    "_clean_d2",
]


def find_d2_bin() -> str | None:
    """Locate D2 executable binary using a prioritized resolution order.

    Resolution order:
    1. PATH via shutil.which("d2")
    2. Vault-local tools directory: cfg.vault_root / "tools" / "bin" / "d2.exe" (or "d2" on non-Windows)
    3. Windows WinGet package: %LOCALAPPDATA%/Microsoft/WinGet/Packages/Terrastruct.D2_Microsoft.Winget.Source_*/d2.exe (glob)
    4. Windows user Programs: %LOCALAPPDATA%/Programs/d2/d2.exe

    Returns:
        Absolute string path to D2 executable if found, otherwise None.
    """
    # 1. System PATH
    which_bin = shutil.which("d2")
    if which_bin:
        return which_bin

    # 2. Vault-local tools directory
    exe_name = "d2.exe" if sys.platform == "win32" else "d2"
    tools_bin = cfg.vault_root / "tools" / "bin" / exe_name
    if tools_bin.is_file():
        return str(tools_bin)

    # 3. Windows WinGet directory (glob)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_dir = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_dir.is_dir():
            matches = sorted(winget_dir.glob("Terrastruct.D2_Microsoft.Winget.Source_*/d2.exe"))
            if not matches:
                matches = sorted(winget_dir.glob("Terrastruct.D2_Microsoft.Winget.Source_*/**/d2.exe"))
            if matches and matches[-1].is_file():
                return str(matches[-1])

        # 4. Windows Programs directory
        prog_bin = Path(local_appdata) / "Programs" / "d2" / "d2.exe"
        if prog_bin.is_file():
            return str(prog_bin)

    return None


def sanitize_d2_for_kroki(d2_code: str) -> str:
    """Sanitize D2 code for Kroki HTTP API compatibility.

    Rewrites proprietary 'layout-engine: tala' to open-source 'layout-engine: elk'
    since Tala is a commercial proprietary layout engine unsupported by Kroki.

    Args:
        d2_code: D2 source code string.

    Returns:
        Sanitized D2 source code string.
    """
    return re.sub(r"layout-engine:\s*tala\b", "layout-engine: elk", d2_code, flags=re.IGNORECASE)


def _clean_d2(raw: str, sanitize_tala: bool | None = None) -> str:
    """Clean and extract D2 source code from LLM response.

    Strips markdown fences (```d2 ... ``` or ``` ... ```) and conversational filler,
    handling both closed and unclosed/truncated code fences.

    Args:
        raw: Raw LLM response string.
        sanitize_tala: Whether to rewrite 'layout-engine: tala' to 'elk'.
            If True: always sanitizes tala to elk.
            If False: preserves tala (for local D2 compiler with tala support).
            If None (default): auto-detects; only sanitizes if no local D2 binary is found.

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

    # Active guardrail: if no local binary or explicitly requested, rewrite tala for Kroki
    should_sanitize = sanitize_tala if sanitize_tala is not None else (find_d2_bin() is None)
    if should_sanitize:
        cleaned = sanitize_d2_for_kroki(cleaned)
    return cleaned


def compile_d2_via_kroki(d2_code: str, timeout: float = 15.0) -> str:
    """Send HTTP POST to Kroki to compile D2 code to SVG.

    Zero third-party dependency via standard library urllib.request.
    Always sanitizes tala layout-engine to elk before sending.

    Args:
        d2_code: Cleaned D2 source string.
        timeout: Request timeout in seconds (default 15s).

    Returns:
        SVG content string.

    Raises:
        RuntimeError: If Kroki request fails or returns non-200.
    """
    # Active guardrail: Kroki does not support proprietary Tala engine
    d2_code = sanitize_d2_for_kroki(d2_code)

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


def _compile_d2_locally(
    d2_bin: str, d2_code: str, output_svg_path: Path | None, timeout: float
) -> str | None:
    """Compile D2 code using local d2 CLI binary."""
    try:
        cmd = [d2_bin, "-", str(output_svg_path)] if output_svg_path else [d2_bin, "-", "-"]
        use_shell = sys.platform == "win32" and d2_bin.lower().endswith((".cmd", ".bat"))
        res = subprocess.run(
            cmd,
            input=d2_code.encode("utf-8"),
            capture_output=True,
            check=True,
            timeout=timeout,
            shell=use_shell,
        )
        if output_svg_path and output_svg_path.exists():
            return output_svg_path.read_text(encoding="utf-8")
        if res.stdout:
            content = res.stdout.decode("utf-8")
            if output_svg_path:
                output_svg_path.write_text(content, encoding="utf-8")
            return content
    except Exception as e:
        _logger.warning(f"Local d2 CLI ({d2_bin}) failed: {e}. Falling back to Kroki.")
    return None


def _compile_d2_fallback(d2_code: str, output_svg_path: Path | None, timeout: float) -> str | None:
    """Compile D2 code via Kroki HTTP API fallback."""
    try:
        svg_content = compile_d2_via_kroki(d2_code, timeout=timeout)
        if output_svg_path:
            output_svg_path.parent.mkdir(parents=True, exist_ok=True)
            output_svg_path.write_text(svg_content, encoding="utf-8")
        return svg_content
    except Exception as e:
        _logger.error(f"D2 compilation failed on both local CLI and Kroki: {e}")
        return None


def compile_d2_to_svg(
    d2_code: str,
    output_svg_path: Path | str | None = None,
    timeout: float = 15.0,
) -> str | None:
    """Compile D2 code to SVG via local CLI or Kroki fallback.

    Primary: if local d2 CLI exists via find_d2_bin(), run `d2 - output.svg`.
    Fallback: send HTTP POST to https://kroki.io/d2/svg via urllib.request.
    """
    if not d2_code or not d2_code.strip():
        _logger.warning("Empty D2 code provided for compilation")
        return None

    target_path = Path(output_svg_path) if output_svg_path else None
    if target_path:
        target_path.parent.mkdir(parents=True, exist_ok=True)

    d2_bin = find_d2_bin()
    if d2_bin:
        result = _compile_d2_locally(d2_bin, d2_code, target_path, timeout)
        if result is not None:
            return result

    return _compile_d2_fallback(d2_code, target_path, timeout)


compile_d2 = compile_d2_to_svg


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


def _generate_and_clean_d2_code(diagram_name: str, source_text: str) -> str | None:
    """Extract context and generate cleaned D2 source via LLM."""
    context = find_diagram_context(diagram_name, source_text)
    _logger.info(f"Generating D2 diagram: {diagram_name}")
    log("diagram", f"D2 generation started: {diagram_name}")

    prompt = D2_GENERATE.format(context=context)
    d2_code = call_llm(prompt, task="synthesis")
    if not d2_code:
        log("error", f"D2 generation failed: {diagram_name}")
        save_fallback_diagram(diagram_name, "Lỗi kết nối hoặc LLM không trả về phản hồi", "d2")
        return None

    cleaned = _clean_d2(d2_code)
    if not cleaned:
        log("error", f"D2 validation failed: {diagram_name}")
        save_fallback_diagram(diagram_name, "Lỗi cú pháp mã D2", "d2")
        return None
    return cleaned


def _save_raw_d2_file(diagram_name: str, d2_code: str) -> None:
    """Save raw D2 code file alongside SVG for inspection and versioning."""
    if diagram_name.endswith(".d2.svg"):
        d2_filename = diagram_name[:-4]
    elif diagram_name.endswith(".svg"):
        d2_filename = diagram_name[:-4] + ".d2"
    else:
        d2_filename = f"{diagram_name}.d2"

    d2_path = cfg.attachments_dir / d2_filename
    d2_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        d2_path.write_text(d2_code, encoding="utf-8")
        _logger.info(f"Saved raw D2 code: {d2_path.name}")
    except OSError as e:
        _logger.warning(f"Failed to save raw D2 file {d2_path.name}: {e}")


def _generate_d2(diagram_name: str, source_text: str) -> None:
    """Worker function: extract context, generate D2 code, compile to SVG, and save."""
    clean_name = diagram_name.split("|")[0].strip()
    if not clean_name:
        return

    d2_code = _generate_and_clean_d2_code(clean_name, source_text)
    if not d2_code:
        return

    _save_raw_d2_file(clean_name, d2_code)
    svg_path = cfg.attachments_dir / clean_name
    svg_content = compile_d2_to_svg(d2_code, output_svg_path=svg_path)

    if not svg_content:
        log("error", f"D2 compilation failed: {clean_name}")
        save_fallback_diagram(clean_name, "Lỗi biên dịch D2 vector sang SVG", "d2")
        return

    save_diagram_file(clean_name, svg_content, "d2")
