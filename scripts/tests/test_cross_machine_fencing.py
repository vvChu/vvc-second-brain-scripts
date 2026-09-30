"""Tests for Cross-Machine Fencing Token Layer (v8.16.0)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from core import cross_machine_fencing as cmf


def test_cross_machine_fencing_lifecycle(tmp_path: Path):
    test_epoch_file = tmp_path / ".spark_heartbeat_epoch.json"

    with patch.object(cmf, "get_epoch_path", return_value=test_epoch_file), \
         patch.object(cmf, "get_current_host", return_value="spark-CCBA"):
        
        # 1. No file initially -> allowed
        allowed, reason = cmf.check_cross_machine_lease()
        assert allowed is True
        assert "No existing lease found" in reason

        # 2. Record epoch
        assert cmf.record_active_epoch() is True
        assert test_epoch_file.exists()

        # 3. Check lease on same host -> allowed
        allowed, reason = cmf.check_cross_machine_lease()
        assert allowed is True
        assert "spark-CCBA" in reason

        # 4. Check lease from another host (e.g. Windows workstation) -> DENIED
        with patch.object(cmf, "get_current_host", return_value="windows-workstation"):
            allowed, reason = cmf.check_cross_machine_lease()
            assert allowed is False
            assert "spark-CCBA" in reason
            assert "Split-Brain" in reason

            # 4b. Force flag overrides lease
            allowed, reason = cmf.check_cross_machine_lease(force=True)
            assert allowed is True

        # 5. Clear epoch -> stopped -> allowed for another host
        assert cmf.clear_active_epoch() is True
        with patch.object(cmf, "get_current_host", return_value="windows-workstation"):
            allowed, reason = cmf.check_cross_machine_lease()
            assert allowed is True
            assert "stopped" in reason
