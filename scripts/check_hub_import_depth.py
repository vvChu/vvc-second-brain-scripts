"""CCBA Hub Import Depth Checker — Pre-commit hook for Spoke repositories.

Enforces ADR 0044 rule: Spoke code must only import from top-level Hub packages
(depth ≤ 2). Deep imports (depth ≥ 3) bypass the __all__ API contract and are
forbidden.

Examples:
    ✅ from ccba_legal import ChromeCDP
    ✅ from ccba_ai import ai
    ❌ from ccba_legal.crawler.chrome_cdp import _internal_helper
    ❌ from ccba_harness.core.locks import ProcessLock

Usage:
    python check_hub_import_depth.py [--path <spoke_root>]
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

# Canonical fallback Hub package import prefixes for Spoke environments where packages/ is absent
FALLBACK_HUB_PACKAGES: tuple[str, ...] = (
    "ccba_ai", "ccba_core", "ccba_harness", "ccba_legal", "ccba_maskara",
    "ccba_notebooklm", "ccba_ooxml", "ccba_pdf_prep", "ccba_qc_core", "mdconverter",
)

_WIN_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def _resolve_candidate_hub_path(raw: str, base_dir: Path) -> Path | None:
    """Safely resolve a candidate hub path string across Windows and POSIX."""
    raw = raw.strip().strip("'\"")
    if not raw:
        return None
    if os.name != "nt" and _WIN_DRIVE_PATTERN.match(raw):
        import shutil
        import subprocess

        if shutil.which("wslpath"):
            try:
                res = subprocess.run(["wslpath", "-u", raw], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and res.stdout.strip() and Path(res.stdout.strip()).exists():
                    return Path(res.stdout.strip())
            except Exception:
                pass
        return None

    p = Path(raw)
    return (base_dir / p).resolve() if not p.is_absolute() else p.resolve()


def _extract_hub_raw_str(content: str) -> str:
    """Extract raw hub path string from YAML text using PyYAML or line parsing."""
    try:
        import yaml

        data = yaml.safe_load(content)
        if isinstance(data, dict):
            val = data.get("hub_path") or (data.get("project") or {}).get("hub_path")
            if isinstance(val, dict):
                os_key = "windows" if os.name == "nt" else "linux"
                return str(val.get(os_key) or val.get("posix") or "")
            if isinstance(val, str):
                return val
    except Exception:
        pass

    for line in content.splitlines():
        line_s = line.strip()
        if line_s.startswith("hub_path:"):
            return line_s.split(":", 1)[1].split("#")[0].strip().strip("'\"")
    return ""


def _read_hub_path_from_dir(directory: Path) -> Path | None:
    """Extract Hub packages directory from workspace_context.yaml in directory."""
    for rel in (
        directory / ".agents" / "workspace_context.yaml",
        directory / ".md" / "workspace_context.yaml",
        directory / "workspace_context.yaml",
    ):
        if not rel.is_file():
            continue
        try:
            spoke_dir = rel.parent.parent if rel.parent.name in (".agents", ".md") else rel.parent
            raw = _extract_hub_raw_str(rel.read_text(encoding="utf-8"))
            if raw:
                hp = _resolve_candidate_hub_path(raw, spoke_dir)
                if hp:
                    pkg_dir = hp if hp.name == "packages" else hp / "packages"
                    if pkg_dir.is_dir():
                        return pkg_dir
        except OSError:
            pass
    return None


def _check_packages_candidate(cand: Path) -> Path | None:
    """Check if candidate directory or its packages/ subdirectory is valid."""
    if cand.name == "packages" and cand.is_dir():
        return cand
    pkg_cand = cand / "packages"
    if pkg_cand.is_dir() and any(pkg_cand.iterdir()):
        return pkg_cand
    return _read_hub_path_from_dir(cand)


def _find_packages_from_env() -> Path | None:
    """Locate packages/ directory from environment variables."""
    for env_key in ("CCBA_HUB_PATH", "HUB_PATH"):
        env_val = os.environ.get(env_key)
        if env_val:
            hp = Path(env_val).resolve()
            pkg_dir = hp if hp.name == "packages" else hp / "packages"
            if pkg_dir.is_dir():
                return pkg_dir
    return None


def find_hub_packages_dir(start_path: Path | None = None) -> Path | None:
    """Locate the Hub packages/ directory dynamically."""
    if start_path is not None:
        resolved = start_path.resolve()
        for cand in (resolved, *resolved.parents):
            hit = _check_packages_candidate(cand)
            if hit:
                return hit
        env_hit = _find_packages_from_env()
        if env_hit:
            return env_hit
        sibling = resolved.parent / "ccba-agent-platform" / "packages"
        return sibling if sibling.is_dir() else None

    env_hit = _find_packages_from_env()
    if env_hit:
        return env_hit

    for base in (Path(__file__).resolve().parents, Path.cwd().resolve().parents):
        for candidate in base:
            hit = _check_packages_candidate(candidate)
            if hit:
                return hit
    return None


def _discover_from_pyproject(pyproject: Path, discovered: set[str]) -> None:
    """Extract package and script names from pyproject.toml."""
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        wheel_pkgs = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {}).get("packages", [])
        for wp in wheel_pkgs:
            p_name = Path(wp).name
            if p_name and not p_name.startswith((".", "_")):
                discovered.add(p_name)

        for inc in data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("include", []):
            clean = inc.rstrip("*.").strip()
            if clean and not clean.startswith((".", "_")):
                discovered.add(clean)

        flit_mod = data.get("tool", {}).get("flit", {}).get("module", {}).get("name")
        if flit_mod and not flit_mod.startswith((".", "_")):
            discovered.add(flit_mod)

        for entry in data.get("project", {}).get("scripts", {}).values():
            if ":" in entry:
                mod = entry.split(":")[0].split(".")[0]
                if mod and not mod.startswith((".", "_")):
                    discovered.add(mod)
    except Exception:
        pass


def _discover_from_pkg_dir(pkg_dir: Path, discovered: set[str]) -> None:
    """Discover import package names inside a specific package directory."""
    src_dir = pkg_dir / "src"
    if src_dir.is_dir():
        for child in src_dir.iterdir():
            if child.is_dir() and not child.name.startswith((".", "_")) and not child.name.endswith(".egg-info"):
                discovered.add(child.name)
            elif child.is_file() and child.suffix == ".py" and not child.name.startswith((".", "_")):
                discovered.add(child.stem)
    else:
        for child in pkg_dir.iterdir():
            if child.is_dir() and not child.name.startswith((".", "_")) and (child / "__init__.py").is_file():
                discovered.add(child.name)

    pyproject = pkg_dir / "pyproject.toml"
    if pyproject.is_file():
        _discover_from_pyproject(pyproject, discovered)


def discover_hub_packages(
    hub_root: Path | None = None,
    fallback: tuple[str, ...] = FALLBACK_HUB_PACKAGES,
) -> tuple[str, ...]:
    """Dynamically discover official Hub package import names."""
    packages_dir = find_hub_packages_dir(hub_root)
    if not packages_dir or not packages_dir.is_dir():
        return fallback

    discovered: set[str] = set()
    for pkg_dir in sorted(packages_dir.iterdir(), key=lambda p: p.name):
        if pkg_dir.is_dir() and not pkg_dir.name.startswith((".", "_")):
            _discover_from_pkg_dir(pkg_dir, discovered)

    return tuple(sorted(discovered)) if discovered else fallback


HUB_PACKAGES: tuple[str, ...] = discover_hub_packages()
HUB_PACKAGE_PREFIXES: tuple[str, ...] = HUB_PACKAGES


def _check_import_node(
    node: ast.AST,
    hub_packages: tuple[str, ...],
    lines: list[str],
) -> tuple[int, str] | None:
    """Check an AST import node against Hub import depth rules."""
    if isinstance(node, ast.ImportFrom):
        if not node.module or node.level > 0:
            return None
        parts = node.module.split(".")
        if parts[0] in hub_packages:
            is_viol = (
                len(parts) >= 3
                or (len(parts) >= 2 and any(p.startswith("_") for p in parts[1:]))
                or any(
                    a.name.startswith("_") and not (a.name.startswith("__") and a.name.endswith("__"))
                    for a in node.names
                )
            )
            if is_viol:
                content = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else f"from {node.module} import ..."
                return node.lineno, content
    elif isinstance(node, ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] in hub_packages and (len(parts) >= 3 or (len(parts) >= 2 and any(p.startswith("_") for p in parts[1:]))):
                content = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else f"import {alias.name}"
                return node.lineno, content
    return None


def scan_file(
    filepath: Path,
    hub_packages: tuple[str, ...] | None = None,
) -> list[tuple[int, str]]:
    """Scans a Python file for deep Hub package imports using AST parsing."""
    if hub_packages is None:
        hub_packages = HUB_PACKAGES

    violations: list[tuple[int, str]] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except (UnicodeDecodeError, OSError, SyntaxError):
        return violations

    lines = content.splitlines()
    for node in ast.walk(tree):
        hit = _check_import_node(node, hub_packages, lines)
        if hit:
            violations.append(hit)

    return sorted(set(violations), key=lambda x: x[0])


def _collect_target_files(args_path: str, args_files: list[str]) -> list[Path]:
    """Collect candidate python files while excluding caches and venvs."""
    if args_files:
        files = [Path(f) for f in args_files if f.endswith(".py")]
    else:
        root = Path(args_path).resolve()
        files = list(root.glob("*.py"))
        for scan_dir in (root / "scripts", root / "src", root / "tests"):
            if scan_dir.exists():
                files.extend(scan_dir.rglob("*.py"))

    exclude = {".venv", "venv", "__pycache__", ".git", "node_modules", ".agents", ".md"}
    return sorted({f for f in files if not any(part in exclude for part in f.parts)})


def main() -> int:
    """Scans Spoke Python files for deep Hub package imports."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="CCBA Hub Import Depth Checker (ADR 0044)")
    parser.add_argument("--path", "-p", default=".", help="Root directory to scan (default: current dir)")
    parser.add_argument("--hub-path", default=None, help="Path to Hub root directory (optional)")
    parser.add_argument("files", nargs="*", help="Specific files to check")
    args = parser.parse_args()

    hub_root = Path(args.hub_path).resolve() if args.hub_path else None
    active_packages = (
        discover_hub_packages(hub_root=hub_root)
        if hub_root
        else discover_hub_packages(hub_root=Path(args.path).resolve())
    )
    if not hub_root and active_packages == FALLBACK_HUB_PACKAGES:
        active_packages = discover_hub_packages(hub_root=None)

    target_files = _collect_target_files(args.path, args.files)
    total_violations = 0
    for filepath in target_files:
        violations = scan_file(filepath, hub_packages=active_packages)
        if violations:
            total_violations += len(violations)
            for line_num, line_content in violations:
                print(f"{filepath}:{line_num}: {line_content}")

    if total_violations > 0:
        print(
            f"\n❌ Phát hiện {total_violations} vi phạm Import Depth (ADR 0044).\n"
            "   Quy tắc: Chỉ import từ top-level Hub package.\n"
            "   ✅ Đúng:  from ccba_legal import ChromeCDP\n"
            "   ❌ Sai:   from ccba_legal.crawler.chrome_cdp import ChromeCDP\n"
            "   Nếu cần symbol chưa có trong top-level, tạo issue đề xuất bổ sung __all__."
        )
        return 1

    if target_files:
        print(f"✅ Đã quét {len(target_files)} file(s), không có vi phạm Import Depth.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
