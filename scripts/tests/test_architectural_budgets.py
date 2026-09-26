"""Architectural Budget & Ratchet Governance Tests (v8.15.13).

Enforces structural invariants across the codebase:
1. Module Line Budget: All non-test Python files <= 350 lines, except for constitutional
   prompts allowlist and legacy files governed by a monotonic ratchet (can only decrease).
2. Function Length Budget: Enforces Global Rule 5 (functions <= 50 lines) via AST.
   Legacy functions over 50 lines are ratcheted per file; all new files/functions must be <= 50 lines.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Paths to script root
SCRIPTS_DIR = Path(__file__).resolve().parent.parent

# Constitutional prompts allowlist: synchronized with Constitution (AGENTS.md)
PROMPT_FILE_ALLOWLIST = {
    "core/prompts/pipeline.py",
    "core/prompts/services.py",
}

# Monotonic line budget ratchets for legacy production files > 350 lines (0 files).
# 100% of production files comply with the 350-line standard.
LEGACY_LINE_RATCHET: dict[str, int] = {}

# Monotonic function count ratchets for legacy files with functions > 50 lines (26 files).
# Any new file not listed here defaults to budget 0 (Global Rule 5: no functions > 50 lines).
LEGACY_FUNC_OVER_50_BUDGET: dict[str, int] = {
    "services/brain_dump/inbox_io.py": 1,
    "services/brain_dump/orchestrator.py": 1,
    "services/brain_dump/url_registry.py": 1,
    "services/command/citations.py": 1,
    "services/command/inbox.py": 1,
    "services/command/styles.py": 1,
    "services/command/topic_saver.py": 1,
    "services/d2_worker.py": 2,
    "services/doc_worker.py": 1,
    "services/legal_sync_worker.py": 1,
    "services/orthography.py": 2,
    "services/rag/context_builder.py": 2,
    "services/rag/hybrid_search.py": 2,
    "services/url_fetcher.py": 1,
    "services/vision_qc_worker.py": 1,
    "services/weekly_synthesis.py": 1,
    "services/wiki_health/domain_enricher.py": 1,
    "services/wiki_health/link_healer.py": 1,
    "services/wiki_health/linter.py": 2,
    "services/wiki_health/stub_lifecycle.py": 1,
    "services/wiki_health/title_standardizer.py": 2,
    "tools/audit_playbook.py": 1,
    "tools/deduplicate_sources.py": 1,
    "tools/enrich_figure_inventory.py": 2,
    "tools/hydrate_url_registry.py": 1,
    "web_clip.py": 1,
}


def _get_production_py_files() -> list[tuple[Path, str]]:
    """Collect all production Python files (excluding virtualenv, tests, and temporary residue)."""
    result = []
    for p in sorted(SCRIPTS_DIR.rglob("*.py")):
        parts = p.parts
        if ".venv" in parts or ".agents" in parts or "tests" in parts:
            continue
        rel = p.relative_to(SCRIPTS_DIR).as_posix()
        result.append((p, rel))
    return result


def test_production_file_line_budgets():
    """Verify that all production files adhere to the 350-line limit or their ratchet limits."""
    violations: list[str] = []
    py_files = _get_production_py_files()

    for file_path, rel_path in py_files:
        if rel_path in PROMPT_FILE_ALLOWLIST:
            continue

        line_count = len(file_path.read_text(encoding="utf-8").splitlines())

        if rel_path in LEGACY_LINE_RATCHET:
            allowed_max = LEGACY_LINE_RATCHET[rel_path]
            if line_count > allowed_max:
                violations.append(
                    f"{rel_path}: {line_count} lines exceeds ratchet limit of {allowed_max} "
                    f"(+{line_count - allowed_max} lines). Decompose into submodules."
                )
        else:
            if line_count > 350:
                violations.append(
                    f"{rel_path}: {line_count} lines exceeds standard architectural budget of 350 lines "
                    f"(+{line_count - 350} lines). Decompose into deep module package."
                )

    assert not violations, f"Found {len(violations)} line budget violation(s):\n" + "\n".join(violations)


def test_function_length_ratchet_budget():
    """Verify that functions adhere to Global Rule 5 (<= 50 lines) or their ratchet budget."""
    violations: list[str] = []
    py_files = _get_production_py_files()

    for file_path, rel_path in py_files:
        content = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            violations.append(f"{rel_path}: SyntaxError during AST parse: {e}")
            continue

        funcs_over_50 = 0
        long_func_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                if length > 50:
                    funcs_over_50 += 1
                    long_func_names.append(f"{node.name} ({length} lines)")

        budget = LEGACY_FUNC_OVER_50_BUDGET.get(rel_path, 0)
        if funcs_over_50 > budget:
            violations.append(
                f"{rel_path}: has {funcs_over_50} function(s) > 50 lines, "
                f"exceeding allowed budget of {budget} (excess functions: {', '.join(long_func_names)}). "
                f"Refactor functions to adhere to Global Rule 5."
            )

    assert not violations, f"Found {len(violations)} function length ratchet violation(s):\n" + "\n".join(violations)
