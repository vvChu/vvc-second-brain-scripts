"""Tests for services.wiki_health Deep Module Package Interface Contracts.

Verifies:
1. Direct package imports for all 22 symbols and backward compatibility contracts.
2. Identity preservation with individual submodules.
3. Weekly synthesis re-export preservation.
4. Whitelist stubs loading contract (preventing config.yaml relative path regressions).
5. Lazy concept resolution contract (verifying internal intra-package coupling to VaultLinter).
6. Automated line budget enforcement (<= 350 lines per submodule).
7. Shadowing prevention (ensuring single file wiki_health.py no longer exists).
"""

from __future__ import annotations

from pathlib import Path
import pytest

import services.weekly_synthesis as ws
import services.wiki_health as wh
import services.wiki_health.bridge_finder as bf
import services.wiki_health.code_pill_cleaner as cpc
import services.wiki_health.domain_enricher as de
import services.wiki_health.link_healer as lh
import services.wiki_health.linter as lint
import services.wiki_health.stub_lifecycle as sl
import services.wiki_health.title_standardizer as ts


def test_package_exports_all_symbols():
    """Verify all 22 symbols are exported and accessible directly from services.wiki_health."""
    # Types & Constants
    assert hasattr(wh, "BridgeCandidate")
    assert hasattr(wh, "LintReport")
    assert hasattr(wh, "_CODE_PILL_LINK_PATTERN")
    assert hasattr(wh, "_REJECT_PATTERNS")
    assert hasattr(wh, "CANONICAL_DOMAINS")
    assert hasattr(wh, "_LINK_PATTERN")
    assert hasattr(wh, "MEDIA_EXTENSIONS")

    # Core Classes
    assert hasattr(wh, "BridgeCandidateFinder")
    assert hasattr(wh, "VaultLinter")
    assert hasattr(wh, "LinkHealer")
    assert hasattr(wh, "DomainEnricher")
    assert hasattr(wh, "OrthographicHealer")
    assert hasattr(wh, "TitleStandardizer")

    # Facade Functions
    assert hasattr(wh, "lint_vault")
    assert hasattr(wh, "heal_broken_links")
    assert hasattr(wh, "enrich_domains")
    assert hasattr(wh, "scan_wikilink_code_pills")
    assert hasattr(wh, "heal_orthography")
    assert hasattr(wh, "standardize_titles")
    assert hasattr(wh, "manage_stub_lifecycle")
    assert hasattr(wh, "_update_all_links_vault_wide_batch")

    # Re-export
    assert hasattr(wh, "generate_weekly_synthesis")


def test_symbol_identities_with_submodules():
    """Verify package symbols are identical references to their submodule origins."""
    assert wh.BridgeCandidateFinder is bf.BridgeCandidateFinder
    assert wh.BridgeCandidate is bf.BridgeCandidate

    assert wh.VaultLinter is lint.VaultLinter
    assert wh.lint_vault is lint.lint_vault
    assert wh._LINK_PATTERN is lint._LINK_PATTERN
    assert wh.MEDIA_EXTENSIONS is lint.MEDIA_EXTENSIONS

    assert wh.LinkHealer is lh.LinkHealer
    assert wh.heal_broken_links is lh.heal_broken_links
    assert wh._REJECT_PATTERNS is lh._REJECT_PATTERNS

    assert wh.manage_stub_lifecycle is sl.manage_stub_lifecycle

    assert wh.DomainEnricher is de.DomainEnricher
    assert wh.enrich_domains is de.enrich_domains
    assert wh.CANONICAL_DOMAINS is de.CANONICAL_DOMAINS

    assert wh._CODE_PILL_LINK_PATTERN is cpc._CODE_PILL_LINK_PATTERN
    assert wh.scan_wikilink_code_pills is cpc.scan_wikilink_code_pills

    assert wh.OrthographicHealer is ts.OrthographicHealer
    assert wh.TitleStandardizer is ts.TitleStandardizer
    assert wh.heal_orthography is ts.heal_orthography
    assert wh.standardize_titles is ts.standardize_titles
    assert wh._update_all_links_vault_wide_batch is ts._update_all_links_vault_wide_batch


def test_weekly_synthesis_reexport_contract():
    """Verify weekly synthesis is re-exported with identical function reference."""
    assert wh.generate_weekly_synthesis is ws.generate_weekly_synthesis


def test_whitelist_stubs_loading_contract():
    """Verify LinkHealer resolves scripts/config.yaml and loads whitelisted stubs."""
    healer = wh.LinkHealer()
    assert isinstance(healer.whitelisted_stubs, set)
    assert len(healer.whitelisted_stubs) > 0, "whitelisted_stubs must not be empty (checks config.yaml path)"
    assert "in_context_learning" in healer.whitelisted_stubs


def test_lazy_concept_resolution_contract():
    """Verify DomainEnricher, OrthographicHealer, TitleStandardizer initialize without concepts arg."""
    enricher = wh.DomainEnricher()
    assert isinstance(enricher.concepts, list)

    ortho = wh.OrthographicHealer()
    assert isinstance(ortho.concepts, list)

    std = wh.TitleStandardizer()
    assert isinstance(std.concepts, list)


def test_submodule_line_budgets():
    """Verify that every submodule in services.wiki_health stays strictly <= 350 lines."""
    pkg_dir = Path(wh.__file__).parent
    py_files = list(pkg_dir.glob("*.py"))
    assert len(py_files) >= 6

    for f in py_files:
        lines = len(f.read_text(encoding="utf-8").splitlines())
        assert lines <= 350, f"{f.name} exceeds 350 lines ({lines} lines)"


def test_shadowing_prevention():
    """Verify that the old monolithic scripts/services/wiki_health.py has been removed."""
    pkg_dir = Path(wh.__file__).parent
    legacy_file = pkg_dir.parent / "wiki_health.py"
    assert not legacy_file.exists(), f"Legacy {legacy_file} must not exist to prevent package shadowing"
