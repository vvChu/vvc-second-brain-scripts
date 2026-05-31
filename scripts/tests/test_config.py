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


def test_load_env_file(tmp_path):
    """_load_env_file should parse .env file and load into os.environ."""
    import os
    from core.config import _load_env_file

    env_file = tmp_path / "test.env"
    env_file.write_text(
        "# This is a comment\n"
        "TEST_KEY_1=test_val_1\n"
        "TEST_KEY_2 = 'test_val_2'\n"
        "TEST_KEY_3 = \"test_val_3\"\n"
        "  TEST_KEY_4  =  test_val_4  \n",
        encoding="utf-8"
    )

    # Ensure keys do not exist beforehand
    for k in [f"TEST_KEY_{i}" for i in range(1, 5)]:
        if k in os.environ:
            del os.environ[k]

    _load_env_file(env_file)

    assert os.environ.get("TEST_KEY_1") == "test_val_1"
    assert os.environ.get("TEST_KEY_2") == "test_val_2"
    assert os.environ.get("TEST_KEY_3") == "test_val_3"
    assert os.environ.get("TEST_KEY_4") == "test_val_4"

    # Cleanup
    for k in [f"TEST_KEY_{i}" for i in range(1, 5)]:
        if k in os.environ:
            del os.environ[k]

