"""VvC Second Brain — Centralized Configuration (v7.0).

Loads config.yaml and exposes a frozen VaultConfig dataclass singleton.
All paths are resolved to absolute. Environment variables override YAML values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _resolve(root: Path, rel: str) -> Path:
    """Resolve a relative path against vault root."""
    return (root / rel).resolve()


def _load_env_file(env_path: Path) -> None:
    """Load variables from a .env file into os.environ if it exists."""
    if not env_path.exists():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    os.environ.setdefault(key, val)
    except Exception as e:
        import sys
        print(f"Warning: Failed to load .env file at {env_path}: {e}", file=sys.stderr)





@dataclass(frozen=True)
class VaultConfig:
    """Immutable configuration for the entire pipeline."""

    # --- Vault Paths (absolute) ---
    vault_root: Path
    fleeting_dir: Path
    concepts_dir: Path
    sources_dir: Path
    archive_dir: Path
    resources_books_dir: Path
    moc_dir: Path
    attachments_dir: Path
    command_file: Path
    dump_file: Path
    log_file: Path
    index_file: Path
    log_dir: Path
    state_dir: Path

    # --- AI Gateway ---
    gateway_url: str = ""
    gateway_api_key: str = ""
    gateway_proxy_url: str = ""
    gateway_proxy_api_key: str = ""
    gateway_proxy_model: str = ""
    gateway_direct_model: str = ""
    gateway_synthesis_model: str = ""
    gateway_correction_model: str = ""
    gateway_image_model: str = ""

    # --- Backend Selection ---
    backend: str = "gateway"
    fallback: str = "copilot-cli"

    # --- Gemini CLI + API ---
    gemini_cmd: str = ""
    gemini_model: str = ""
    gemini_vision_model: str = ""
    gemini_vision_model_batch: str = ""
    gemini_text_synthesis_model: str = ""
    gemini_text_correction_model: str = ""
    gemini_api_key: str = ""
    gemini_vision_rpd_limit: int = 15
    gemini_text_rpd_limit: int = 450
    gemini_timeout: int = 60
    gemini_vision_timeout: int = 300

    # --- Copilot CLI ---
    copilot_cmd: str = ""
    copilot_model: str = ""
    copilot_vision_model: str = ""
    copilot_correction_model: str = ""
    copilot_timeout: int = 60
    copilot_vision_timeout: int = 300

    # --- Reasoning ---
    reasoning_primary_tier: str = "antigravity-cli"
    reasoning_cli_model: str = "claude-opus-4-6-thinking"
    reasoning_gateway_model: str = ""
    reasoning_timeout: int = 600

    # --- Model Aliases ---
    model_default: str = ""
    model_ocr_vision: str = ""
    model_ocr_vision_fallback: str = ""

    # --- Excalidraw Theme ---
    excalidraw_stroke_color: str = "#000000"
    excalidraw_background_color: str = "transparent"
    excalidraw_font_family: int = 3
    excalidraw_stroke_width: int = 2

    @property
    def assets_dir(self) -> Path:
        """Central asset folder located in 04-Permanent/sources/assets/"""
        return self.sources_dir / "assets"



def _build_vault_paths(root: Path, vault: dict) -> dict[str, Any]:
    """Build filesystem directory paths for VaultConfig."""
    return {
        "vault_root": root,
        "fleeting_dir": _resolve(root, vault.get("fleeting_dir", "05 - Fleeting")),
        "concepts_dir": _resolve(root, vault.get("concepts_dir", "04 - Permanent/concepts")),
        "sources_dir": _resolve(root, vault.get("sources_dir", "04 - Permanent/sources")),
        "archive_dir": _resolve(root, vault.get("archive_dir", "99 - Archive")),
        "resources_books_dir": _resolve(root, vault.get("resources_books_dir", "03 - Resources/books")),
        "moc_dir": _resolve(root, vault.get("moc_dir", "00 - Maps of Content")),
        "attachments_dir": _resolve(root, vault.get("attachments_dir", "03 - Resources/attachments")),
        "command_file": _resolve(root, vault.get("command_file", "00 - Maps of Content/Command.md")),
        "dump_file": _resolve(root, vault.get("dump_file", "05 - Fleeting/Brain_Dump.md")),
        "log_file": _resolve(root, vault.get("log_file", "log.md")),
        "index_file": _resolve(root, vault.get("index_file", "00 - Maps of Content/index.md")),
        "log_dir": _resolve(root, vault.get("log_dir", "scripts/logs")),
        "state_dir": _resolve(root, vault.get("state_dir", "scripts/.state")),
    }


def _build_ai_gateway_params(gw: dict) -> dict[str, Any]:
    """Build AI Gateway parameters for VaultConfig."""
    return {
        "gateway_url": os.environ.get("VVC_GATEWAY_URL", gw.get("url", "")),
        "gateway_api_key": os.environ.get("VVC_GATEWAY_KEY", gw.get("api_key", "")),
        "gateway_proxy_url": os.environ.get("VVC_GATEWAY_PROXY_URL", gw.get("proxy_url", "http://100.83.192.30:8045/v1")),
        "gateway_proxy_api_key": os.environ.get("VVC_GATEWAY_PROXY_KEY", gw.get("proxy_api_key", "")),
        "gateway_proxy_model": gw.get("proxy_model", ""),
        "gateway_direct_model": gw.get("direct_model", ""),
        "gateway_synthesis_model": gw.get("synthesis_model", ""),
        "gateway_correction_model": gw.get("correction_model", ""),
        "gateway_image_model": os.environ.get("VVC_GATEWAY_IMAGE_MODEL", gw.get("image_model", "gemini-3.1-flash-image")),
    }


def _build_cli_and_model_params(gcli: dict, ccli: dict, reasoning: dict, models: dict, theme: dict, raw: dict) -> dict[str, Any]:
    """Build CLI backends, models, reasoning, and theme parameters."""
    return {
        "backend": raw.get("backend", "gateway"),
        "fallback": raw.get("fallback", "copilot-cli"),
        "gemini_cmd": gcli.get("cmd", ""),
        "gemini_model": gcli.get("model", ""),
        "gemini_vision_model": gcli.get("vision_model", ""),
        "gemini_vision_model_batch": gcli.get("vision_model_batch", ""),
        "gemini_text_synthesis_model": gcli.get("text_synthesis_model", ""),
        "gemini_text_correction_model": gcli.get("text_correction_model", ""),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", gcli.get("api_key", "")),
        "gemini_vision_rpd_limit": gcli.get("vision_rpd_limit", 15),
        "gemini_text_rpd_limit": gcli.get("text_rpd_limit", 450),
        "gemini_timeout": gcli.get("timeout", 60),
        "gemini_vision_timeout": gcli.get("vision_timeout", 300),
        "copilot_cmd": ccli.get("cmd", ""),
        "copilot_model": ccli.get("model", ""),
        "copilot_vision_model": ccli.get("vision_model", ""),
        "copilot_correction_model": ccli.get("correction_model", ""),
        "copilot_timeout": ccli.get("timeout", 60),
        "copilot_vision_timeout": ccli.get("vision_timeout", 300),
        "reasoning_primary_tier": reasoning.get("primary_tier", "antigravity-cli"),
        "reasoning_cli_model": reasoning.get("cli_model", "claude-opus-4-6-thinking"),
        "reasoning_gateway_model": reasoning.get("gateway_model", ""),
        "reasoning_timeout": reasoning.get("timeout", 600),
        "model_default": models.get("default", ""),
        "model_ocr_vision": models.get("ocr_vision", ""),
        "model_ocr_vision_fallback": models.get("ocr_vision_fallback", ""),
        "excalidraw_stroke_color": theme.get("stroke_color", "#000000"),
        "excalidraw_background_color": theme.get("background_color", "transparent"),
        "excalidraw_font_family": theme.get("font_family", 3),
        "excalidraw_stroke_width": theme.get("stroke_width", 2),
    }


def load_config(config_path: Path | None = None) -> VaultConfig:
    """Load configuration from YAML file with env var overrides."""
    scripts_dir = Path(__file__).parent.parent
    _load_env_file(scripts_dir / ".env")

    if config_path is None:
        config_path = scripts_dir / "config.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    vault = raw.get("vault", {})
    root = Path(os.environ.get("VVC_VAULT_ROOT", vault.get("root", "D:\\VvC_Notes")))  # ccba:allow-machine-path
    _load_env_file(root / ".env")

    params: dict[str, Any] = {}
    params.update(_build_vault_paths(root, vault))
    params.update(_build_ai_gateway_params(raw.get("ai_gateway", {})))
    params.update(_build_cli_and_model_params(
        raw.get("gemini_cli", {}), raw.get("copilot_cli", {}),
        raw.get("reasoning", {}), raw.get("models", {}),
        raw.get("excalidraw_theme", {}), raw,
    ))
    return VaultConfig(**params)


# --- Singleton ---
cfg = load_config()
cfg.log_dir.mkdir(parents=True, exist_ok=True)
cfg.state_dir.mkdir(parents=True, exist_ok=True)
