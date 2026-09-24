"""Automated Guardrail Tests for Codebase Cleanliness and Hub Import Depth (ADR-0044, ADR-0058)."""

from pathlib import Path
import pytest
from check_spoke_cleanliness import scan_spoke_cleanliness
from check_hub_import_depth import discover_hub_packages, scan_file, FALLBACK_HUB_PACKAGES


@pytest.fixture
def repo_root() -> Path:
    """Resolve authentic repository root."""
    return Path(__file__).resolve().parent.parent.parent


def test_spoke_cleanliness_zero_violations(repo_root: Path):
    """Verify that Spoke codebase has 0 machine-state leakages and stays within script budget."""
    exit_code, messages = scan_spoke_cleanliness(
        spoke_root=repo_root,
        max_scripts=15,
        strict=True,
    )
    full_output = "\n".join(messages)
    assert exit_code == 0, f"Spoke cleanliness check failed with exit code {exit_code}:\n{full_output}"
    assert "0 vi phạm Machine-State Leakage" in full_output or "Không phát hiện rò rỉ đường dẫn máy tuyệt đối" in full_output


def test_hub_import_depth_zero_violations(repo_root: Path):
    """Verify that all Python files in the Spoke repository adhere to Hub import depth <= 2 (ADR-0044)."""
    hub_packages = discover_hub_packages(repo_root) or set(FALLBACK_HUB_PACKAGES)

    target_files = []
    target_files.extend(repo_root.glob("*.py"))
    for scan_dir in [repo_root / "scripts", repo_root / "src", repo_root / "tests"]:
        if scan_dir.exists():
            target_files.extend(scan_dir.rglob("*.py"))

    # Exclude virtualenvs, caches, .agents, .md
    target_files = [
        f
        for f in target_files
        if not any(
            part in (".venv", "venv", "__pycache__", ".git", "node_modules", ".agents", ".md")
            for part in f.parts
        )
    ]

    all_violations = []
    for filepath in sorted(set(target_files)):
        violations = scan_file(filepath, hub_packages=hub_packages)
        if violations:
            for line_num, line_content in violations:
                all_violations.append(f"{filepath.relative_to(repo_root)}:{line_num}: {line_content}")

    assert len(all_violations) == 0, (
        f"Found {len(all_violations)} Hub Import Depth violations (ADR 0044):\n" + "\n".join(all_violations)
    )
