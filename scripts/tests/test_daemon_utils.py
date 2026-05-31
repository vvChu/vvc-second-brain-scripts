"""VvC Second Brain — Shared Daemon Utilities Tests (v1.0)."""

from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.daemon_utils import harden_headless_stdio, is_file_stable


def test_harden_headless_stdio():
    # Mock sys stream objects
    mock_stdout = MagicMock()
    mock_stderr = MagicMock()
    
    with patch.object(sys, "stdout", mock_stdout), patch.object(sys, "stderr", mock_stderr):
        harden_headless_stdio()
        if hasattr(mock_stdout, "reconfigure"):
            mock_stdout.reconfigure.assert_called_with(encoding="utf-8")
        if hasattr(mock_stderr, "reconfigure"):
            mock_stderr.reconfigure.assert_called_with(encoding="utf-8")


def test_harden_headless_stdio_broken_streams():
    # Test broken streams redirection
    mock_broken = MagicMock()
    mock_broken.write.side_effect = Exception("Broken pipe")
    
    with patch.object(sys, "stdout", mock_broken), patch.object(sys, "stderr", None), patch("builtins.open", return_value=MagicMock()) as mock_open:
        harden_headless_stdio()
        mock_open.assert_called()


def test_is_file_stable_not_exists():
    path = Path("/nonexistent/file")
    assert is_file_stable(path, wait_s=0.001, max_retries=2) is False


def test_is_file_stable_success(tmp_path):
    test_file = tmp_path / "stable.txt"
    test_file.write_text("hello", encoding="utf-8")
    assert is_file_stable(test_file, wait_s=0.001, max_retries=2) is True


def test_is_file_stable_size_changing(tmp_path):
    test_file = tmp_path / "changing.txt"
    test_file.write_text("hello", encoding="utf-8")
    
    with patch.object(Path, "stat") as mock_stat:
        # First check size is 10, second check is 20 (changing).
        # Third check is 20, fourth check is 20 (stable).
        mock_stat.side_effect = [
            MagicMock(st_size=10),
            MagicMock(st_size=20),
            MagicMock(st_size=20),
            MagicMock(st_size=20)
        ]
        assert is_file_stable(test_file, wait_s=0.001, max_retries=3) is True


def test_is_file_stable_os_error(tmp_path):
    test_file = tmp_path / "error.txt"
    test_file.write_text("hello", encoding="utf-8")
    
    with patch.object(Path, "stat", side_effect=OSError("Access denied")):
        assert is_file_stable(test_file, wait_s=0.001, max_retries=2) is False
