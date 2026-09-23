"""Tests for daemon restart logic and --restart flag."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts dir is on sys.path
scripts_dir = Path(__file__).resolve().parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

import pytest
from daemon import main, restart_existing_daemons


def test_restart_existing_daemons_executes_powershell():
    """restart_existing_daemons calls PowerShell on Windows or pkill on Linux."""
    with patch("subprocess.run") as mock_run, patch("time.sleep") as mock_sleep:
        mock_run.return_value = MagicMock(returncode=0)
        restart_existing_daemons()

        assert mock_run.called
        args = mock_run.call_args[0][0]
        if sys.platform == "win32":
            assert args[0] == "powershell"
            assert "Stop-Process" in args[4]
        else:
            assert "pgrep" in args or "pkill" in args
        assert mock_sleep.called


def test_restart_existing_daemons_handles_exception():
    """restart_existing_daemons gracefully logs warnings if subprocess fails."""
    with patch("subprocess.run", side_effect=Exception("PowerShell invocation error")):
        # Should not raise exception
        restart_existing_daemons()


def test_daemon_main_with_restart_flag():
    """daemon main(['--restart']) triggers restart_existing_daemons."""
    with patch("daemon.restart_existing_daemons") as mock_restart, \
         patch("daemon._acquire_daemon_lock", return_value=False):
        # We return False for lock to exit main early without running daemon loop
        main(["--restart"])
        assert mock_restart.called


def test_daemon_main_without_restart_flag():
    """daemon main([]) does not trigger restart_existing_daemons."""
    with patch("daemon.restart_existing_daemons") as mock_restart, \
         patch("daemon._acquire_daemon_lock", return_value=False):
        main([])
        assert not mock_restart.called
