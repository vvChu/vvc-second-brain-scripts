"""Tests for core.config module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config_loads():
    """Config should load from config.yaml and resolve paths."""
    from core.config import cfg

    assert cfg.vault_root.exists()
    assert cfg.concepts_dir.is_absolute()
    assert cfg.fleeting_dir.is_absolute()
    assert cfg.backend in ("gateway", "gemini-cli", "copilot-cli")


def test_config_has_models():
    """Config should have model routing fields."""
    from core.config import cfg

    assert isinstance(cfg.gemini_vision_model, str)
    assert isinstance(cfg.gemini_text_synthesis_model, str)
    assert isinstance(cfg.gemini_timeout, int)
    assert cfg.gemini_timeout > 0


def test_config_gateway():
    """Config should have gateway fields."""
    from core.config import cfg

    assert isinstance(cfg.gateway_url, str)
    assert isinstance(cfg.gateway_proxy_model, str)
