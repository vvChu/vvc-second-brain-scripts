"""VvC Second Brain — Copilot CLI Client.

Tier 2 logic for Github Copilot CLI fallback.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.config import cfg
from core.llm.utils import strip_think_tags

_logger = logging.getLogger("vvc.llm.copilot")

def call_copilot(prompt: str, *, model: str = "", timeout: int = 60) -> str:
    """Call LLM via GitHub Copilot CLI."""
    cmd = cfg.copilot_cmd
    if not cmd or not Path(cmd).exists():
        return ""

    target_model = model or cfg.copilot_model
    _logger.info(f"[Copilot CLI] Routed to: {target_model}")
    
    # Strip problematic env vars to force Copilot CLI to use 'gh' auth
    import os
    env = os.environ.copy()
    for k in ["GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN"]:
        env.pop(k, None)

    try:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            # Windows command line limit is technically 8191 for cmd.exe, or 32767 for CreateProcess.
            # Since copilot.exe is a native executable, it bypasses cmd.exe and uses the 32767 limit.
            if len(prompt) > 30000:
                _logger.warning("Prompt length exceeds CreateProcessW limits. Skipping Copilot CLI to prevent WinError 206.")
                return ""

        args = [cmd]
        if target_model:
            args.extend(["--model", target_model])
        args.extend(["-p", prompt])
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent.parent),
            env=env,
            **kwargs,
        )
        if result.returncode == 0 and result.stdout.strip():
            return strip_think_tags(result.stdout.strip())
        _logger.warning(f"Copilot CLI returned code {result.returncode}")
        return ""
    except subprocess.TimeoutExpired:
        _logger.warning("Copilot CLI timed out")
        return ""
    except Exception as e:
        _logger.warning(f"Copilot CLI error: {e}")
        return ""
