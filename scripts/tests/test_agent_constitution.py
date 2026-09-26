"""Unit tests for Vault Living Architecture, Mental Model, and Constitution Integrity (v8.15.13).

Verifies that all context files, instructions, rules, and workspace metadata
comply with the canonical schemas and guardrails.
"""

from pathlib import Path
import yaml
import pytest


@pytest.fixture
def repo_root() -> Path:
    """Resolve the authentic repository root path independent of mocked cfg."""
    # scripts/tests/test_agent_constitution.py -> scripts/tests -> scripts -> VvC_Notes
    return Path(__file__).resolve().parent.parent.parent


def test_gitignore_unignores_md_files(repo_root: Path):
    """Verify that .gitignore allows .md markdown and yaml files (including nested) and git respects the rule."""
    import subprocess
    gitignore_path = repo_root / ".gitignore"
    assert gitignore_path.exists(), ".gitignore must exist"
    content = gitignore_path.read_text(encoding="utf-8")
    
    assert ".md/**" in content, ".gitignore must ignore .md/**"
    assert "!.md/**/" in content, ".gitignore must un-ignore nested directories !.md/**/"
    assert "!.md/**/*.md" in content, ".gitignore must un-ignore !.md/**/*.md"
    assert "!.md/**/*.yaml" in content, ".gitignore must un-ignore !.md/**/*.yaml"

    # Verify .md/** pattern precedes un-ignore patterns
    md_all_idx = content.find(".md/**")
    md_files_idx = content.find("!.md/**/*.md")
    assert md_all_idx != -1 and md_files_idx != -1 and md_all_idx < md_files_idx, (
        ".md/** must precede !.md/**/*.md in .gitignore for un-ignore to take effect"
    )

    # Verify git check-ignore returns non-zero (not ignored) for root .md files
    result_yaml = subprocess.run(
        ["git", "check-ignore", "-q", ".md/workspace_context.yaml"],
        cwd=repo_root,
        capture_output=True,
    )
    assert result_yaml.returncode != 0, ".md/workspace_context.yaml must NOT be ignored by git"

    result_md = subprocess.run(
        ["git", "check-ignore", "-q", ".md/vault_mental_model_and_architecture.md"],
        cwd=repo_root,
        capture_output=True,
    )
    assert result_md.returncode != 0, ".md/vault_mental_model_and_architecture.md must NOT be ignored by git"

    # Verify nested markdown file in .md/ subdirectory is NOT ignored
    result_nested_md = subprocess.run(
        ["git", "check-ignore", "-q", ".md/extracted_docs/sample.md"],
        cwd=repo_root,
        capture_output=True,
    )
    assert result_nested_md.returncode != 0, ".md/extracted_docs/sample.md must NOT be ignored by git"

    # Verify nested yaml file in .md/ subdirectory is NOT ignored
    result_nested_yaml = subprocess.run(
        ["git", "check-ignore", "-q", ".md/nested/sub/config.yaml"],
        cwd=repo_root,
        capture_output=True,
    )
    assert result_nested_yaml.returncode != 0, ".md/nested/sub/config.yaml must NOT be ignored by git"

    # Verify non-md non-yaml file under .md/ IS ignored
    result_txt = subprocess.run(
        ["git", "check-ignore", "-q", ".md/extracted_docs/sample.txt"],
        cwd=repo_root,
        capture_output=True,
    )
    assert result_txt.returncode == 0, ".md/extracted_docs/sample.txt MUST be ignored by git"

    # Verify transient session artifacts under .md/scratch/ ARE ignored (even if .md)
    result_scratch = subprocess.run(
        ["git", "check-ignore", "-q", ".md/scratch/sample.md"],
        cwd=repo_root,
        capture_output=True,
    )
    assert result_scratch.returncode == 0, ".md/scratch/sample.md MUST be ignored by git"


def test_workspace_context_canonical_schema(repo_root: Path):
    """Verify that .md/workspace_context.yaml conforms to the canonical schema and paths exist."""
    context_file = repo_root / ".md" / "workspace_context.yaml"
    assert context_file.exists(), ".md/workspace_context.yaml must exist"
    
    data = yaml.safe_load(context_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "workspace_context.yaml must be a valid mapping"
    
    # Required canonical schema keys
    required_keys = [
        "project",
        "databases",
        "operational_invariants",
        "must_read",
        "acknowledgment_required",
        "pipeline_mode_bypass",
        "subagent_mode_bypass",
    ]
    for key in required_keys:
        assert key in data, f"workspace_context.yaml missing required canonical key: '{key}'"
    
    # Project validations
    project = data["project"]
    assert project.get("name") == "vvc-second-brain"
    assert "v8.15.13" in str(project.get("version"))
    assert project.get("archetype") == "knowledge_corpus"
    assert "hub_path" in project
    assert "hub_path_linux" in project
    assert "hub_path_env" in project
    
    # Database paths existence on disk
    databases = data["databases"]
    for db_name, db_info in databases.items():
        assert "path" in db_info, f"database '{db_name}' missing 'path'"
        db_path = repo_root / db_info["path"]
        assert db_path.exists(), f"database path does not exist on disk: {db_path}"
    
    # Operational invariants validations (all 7 core invariants)
    invariants = data["operational_invariants"]
    expected_invariants = [
        "active_passive_single_runner",
        "stale_daemon_invariant",
        "visual_ergonomics_16_9",
        "clean_wikilinks_zero_code_pill",
        "html_entity_isolation",
        "cli_autonomous_artifact_ingestion",
        "session_artifact_buffer",
    ]
    for inv in expected_invariants:
        assert inv in invariants, f"missing operational invariant: '{inv}'"
    
    # Must read validations and path verification
    must_read = data["must_read"]
    for item in must_read.get("always", []):
        file_path = repo_root / item["path"]
        assert file_path.exists(), f"must_read.always file missing: {file_path}"
        if "canonical_topic" in item:
            topic_path = repo_root / item["canonical_topic"]
            assert topic_path.exists(), f"canonical_topic missing: {topic_path}"
        if "diagram" in item:
            diag_path = repo_root / item["diagram"]
            assert diag_path.exists(), f"diagram missing: {diag_path}"

    for trigger in ("on_pipeline_change", "on_script_change"):
        for item in must_read.get(trigger, []):
            trigger_path = repo_root / item["path"]
            assert trigger_path.exists(), f"must_read.{trigger} file missing: {trigger_path}"
    
    # Acknowledgment, Pipeline & Subagent mode bypass
    assert data["acknowledgment_required"] is True
    assert "vvc-second-brain" in data["acknowledgment_format"]
    assert data["pipeline_mode_bypass"] is True
    assert "pipeline_mode_rationale" in data
    assert data["subagent_mode_bypass"] is True
    assert "subagent_mode_rationale" in data


def test_agents_md_living_architecture_section(repo_root: Path):
    """Verify AGENTS.md §1.1 Living Architecture Reference and core invariants."""
    agents_md = repo_root / "AGENTS.md"
    assert agents_md.exists(), "AGENTS.md must exist"
    content = agents_md.read_text(encoding="utf-8")
    
    assert "### 1.1 Living Architecture Reference" in content
    assert "LLM Compiler Pattern" in content
    
    # 3 Architectural Breakthroughs
    assert "Verifiable Ground Truth RAG" in content
    assert "Noise Gating & Chống Hồi Sinh" in content
    assert "Closed-Loop Compounding Feedback" in content
    
    # 8 Pillars
    for p in range(1, 9):
        assert f"P{p}." in content, f"AGENTS.md missing Pillar P{p}"
        
    # Active-Passive Single-Active Runner
    assert "Active-Passive Single-Active Runner" in content
    assert "Server Linux Spark" in content
    
    # Mandatory Living Architecture Pointers
    assert ".md/vault_mental_model_and_architecture.md" in content
    assert "kien_truc_va_mental_model_vvc_second_brain" in content
    assert "vvc_second_brain_architecture.excalidraw.md" in content
    assert ".md/workspace_context.yaml" in content


def test_gemini_md_quick_rules_pointer(repo_root: Path):
    """Verify GEMINI.md Quick Rules contains Living Architecture & Mental Model pointer."""
    gemini_md = repo_root / "GEMINI.md"
    assert gemini_md.exists(), "GEMINI.md must exist"
    content = gemini_md.read_text(encoding="utf-8")
    
    assert "Living Architecture & Mental Model" in content
    assert "vault_mental_model_and_architecture.md" in content
    assert "workspace_context.yaml" in content


def test_changelog_living_architecture_entry(repo_root: Path):
    """Verify CHANGELOG.md records Living Architecture Reference & Workspace Context Standardization."""
    changelog_md = repo_root / "CHANGELOG.md"
    assert changelog_md.exists(), "CHANGELOG.md must exist"
    content = changelog_md.read_text(encoding="utf-8")
    
    assert "Living Architecture Reference & Workspace Context Standardization" in content


def test_claude_md_architecture_instructions(repo_root: Path):
    """Verify CLAUDE.md contains Living Architecture Reference and invariants."""
    claude_md = repo_root / "CLAUDE.md"
    assert claude_md.exists(), "CLAUDE.md must exist"
    content = claude_md.read_text(encoding="utf-8")
    
    assert "@AGENTS.md" in content
    assert "Living Architecture Reference" in content
    assert "Active-Passive Single-Active Runner" in content
    assert "Stale Daemon Invariant" in content
    assert "workspace_context.yaml" in content


def test_cursor_rules_architecture(repo_root: Path):
    """Verify .cursor/rules/vault-architecture.mdc exists and has valid MDC YAML frontmatter."""
    cursor_rule = repo_root / ".cursor" / "rules" / "vault-architecture.mdc"
    assert cursor_rule.exists(), ".cursor/rules/vault-architecture.mdc must exist"
    content = cursor_rule.read_text(encoding="utf-8")
    
    parts = content.split("---", 2)
    assert len(parts) >= 3, "MDC rule must start with YAML frontmatter enclosed in '---'"
    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict), "MDC frontmatter must parse to a valid dict"
    assert "description" in frontmatter
    assert "globs" in frontmatter
    assert frontmatter["globs"] == "*"
    assert frontmatter.get("alwaysApply") is True

    # Body content checks
    body = parts[2]
    assert "AGENTS.md" in body
    assert "vault_mental_model_and_architecture.md" in body
    assert "Active-Passive Single-Active Runner" in body


def test_github_copilot_instructions(repo_root: Path):
    """Verify .github/copilot-instructions.md exists and contains living architecture guidance."""
    copilot_md = repo_root / ".github" / "copilot-instructions.md"
    assert copilot_md.exists(), ".github/copilot-instructions.md must exist"
    content = copilot_md.read_text(encoding="utf-8")
    
    assert "LLM Compiler Pattern" in content
    assert "Active-Passive Single-Active Runner" in content
    assert "Stale Daemon Invariant" in content
    assert "vault_mental_model_and_architecture.md" in content


def test_sync_manifest_completeness(repo_root: Path):
    """Verify that AGENTS.md Sync Manifest checklist contains all mandatory files and they exist on disk."""
    agents_md = repo_root / "AGENTS.md"
    assert agents_md.exists(), "AGENTS.md must exist"
    content = agents_md.read_text(encoding="utf-8")
    
    assert "Sync Manifest — Mandatory Co-Update Checklist" in content
    
    mandatory_sync_files = [
        "GEMINI.md",
        "CHANGELOG.md",
        "scripts/GEMINI.md",
        "scripts/README.md",
        "CLAUDE.md",
        ".cursor/rules/vault-architecture.mdc",
        ".github/copilot-instructions.md",
        ".md/workspace_context.yaml",
        "scripts/core/prompts/pipeline.py",
        "scripts/core/prompts/services.py",
        "scripts/pipeline/process_markdown.py",
        "scripts/services/legal_sync_worker.py",
    ]
    for target in mandatory_sync_files:
        assert target in content, f"AGENTS.md Sync Manifest missing required entry: '{target}'"
        target_path = repo_root / target
        assert target_path.exists(), f"Sync Manifest target file does not exist on disk: {target_path}"


def test_document_ergonomics_clean_wikilink_invariant(repo_root: Path):
    """Verify that AGENTS.md and GEMINI.md preserve the full Clean Wikilink & Fenced Syntax Invariant."""
    agents_md = repo_root / "AGENTS.md"
    assert agents_md.exists(), "AGENTS.md must exist"
    agents_content = agents_md.read_text(encoding="utf-8")
    
    assert "Clean Wikilink & Zero-Code-Pill Invariant" in agents_content
    assert "fenced code block" in agents_content
    assert "số thứ tự trích dẫn trong bảng phải đồng bộ 1-1 với danh mục tham chiếu cuối bài" in agents_content
    assert "escape pipe" in agents_content

    gemini_md = repo_root / "GEMINI.md"
    assert gemini_md.exists(), "GEMINI.md must exist"
    gemini_content = gemini_md.read_text(encoding="utf-8")
    
    assert "Clean Wikilinks & Deterministic Defense" in gemini_content
    assert "fenced code block" in gemini_content
    assert "đồng bộ 100% số trích dẫn trong bảng với danh mục cuối bài" in gemini_content
    assert "Zero-Fencing Examples trong prompt SLM" in gemini_content
    assert "clean_wikilink_quotes" in gemini_content


def test_deep_manifest_version_synchronization(repo_root: Path):
    """Enforce canonical version synchronization across all manifest layers and internal sections."""
    from core.__version__ import __version__, VERSION
    canonical = VERSION  # e.g. "v8.15.13"

    # 1. SSoT Workspace Context
    ctx_path = repo_root / ".md/workspace_context.yaml"
    ctx_text = ctx_path.read_text(encoding="utf-8")
    ctx_data = yaml.safe_load(ctx_text)
    assert ctx_data["project"]["version"] == canonical, f"workspace_context.yaml version mismatch"
    assert canonical in ctx_data["project"]["current_milestone"], (
        f"workspace_context.yaml current_milestone must contain {canonical}"
    )
    assert canonical in ctx_data.get("acknowledgment_format", ""), (
        f"workspace_context.yaml acknowledgment_format is stale! Expected {canonical}"
    )

    # 2. Header and Internal Section Scan
    target_surfaces = {
        "AGENTS.md": [canonical],
        "GEMINI.md": [canonical, f"Living Architecture & Mental Model** ({canonical})"],
        "CHANGELOG.md": [f"## {canonical}"],
        "scripts/GEMINI.md": [canonical, f"Architecture Reference ({canonical}"],
        "scripts/README.md": [canonical],
        ".md/vault_mental_model_and_architecture.md": [f"# 🧠 VvC Second Brain — Mental Model & Kiến Trúc Tổng Thể ({canonical})"],
        "scripts/daemon.py": [f'"""VvC Second Brain — Main Daemon ({canonical}).'],
        "scripts/book_ingest.py": [f'"""VvC Second Brain — Book Ingestion Daemon ({canonical}).'],
    }
    for rel_path, required_tokens in target_surfaces.items():
        content = (repo_root / rel_path).read_text(encoding="utf-8")
        for token in required_tokens:
            assert token in content, f"File {rel_path} is missing expected version token: '{token}'"

    # 3. Test Docstring Consistency
    const_test_text = (repo_root / "scripts/tests/test_agent_constitution.py").read_text(encoding="utf-8")
    assert canonical in const_test_text.splitlines()[0], (
        f"test_agent_constitution.py module docstring header must be updated to {canonical}"
    )


def test_readme_directory_tree_parity(repo_root: Path):
    """Enforce that all deep module packages in scripts/core/ and scripts/services/ are in scripts/README.md."""
    readme_path = repo_root / "scripts/README.md"
    assert readme_path.exists(), "scripts/README.md must exist"
    readme_content = readme_path.read_text(encoding="utf-8")

    scripts_dir = repo_root / "scripts"
    deep_packages: list[str] = []
    for parent in ["core", "services"]:
        parent_dir = scripts_dir / parent
        if not parent_dir.exists():
            continue
        for child in sorted(parent_dir.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                deep_packages.append(f"{child.name}/")

    missing = [pkg for pkg in deep_packages if pkg not in readme_content]
    assert not missing, (
        f"The following deep module packages are missing from scripts/README.md directory tree: {missing}. "
        f"Update scripts/README.md § 2. Directory Structure."
    )


def test_no_stale_legacy_ratchet_mentions_in_context_files(repo_root: Path):
    """Ensure context and constitution files do not contain stale legacy ratchet numbers."""
    stale_patterns = [
        "29 tệp logic legacy",
        "83 tệp legacy",
        "83 tệp hàm legacy",
        "55 legacy function files",
    ]
    context_files = [
        "AGENTS.md",
        "CLAUDE.md",
        ".cursor/rules/vault-architecture.mdc",
        ".github/copilot-instructions.md",
        "scripts/GEMINI.md",
        "GEMINI.md",
    ]
    for rel_path in context_files:
        target = repo_root / rel_path
        if not target.exists():
            continue
        content = target.read_text(encoding="utf-8")
        for pat in stale_patterns:
            assert pat not in content, f"{rel_path} contains stale ratchet phrase: '{pat}'"


