"""VvC Second Brain — Wiki Health Service Package.

Consolidated Deep Module package for vault diagnostics, link healing,
Grand Domain taxonomy enrichment, title standardization, and weekly synthesis.

Usage:
    from services.wiki_health import lint_vault, heal_broken_links, enrich_domains
    report = lint_vault()
    heal_broken_links()
    enrich_domains()
"""

from __future__ import annotations

# Re-export generate_weekly_synthesis from weekly_synthesis for backward compatibility
from services.weekly_synthesis import generate_weekly_synthesis

from .bridge_finder import (
    BridgeCandidate,
    BridgeCandidateFinder,
)
from .code_pill_cleaner import (
    _CODE_PILL_LINK_PATTERN,
    scan_wikilink_code_pills,
)
from .domain_enricher import (
    CANONICAL_DOMAINS,
    DomainEnricher,
    enrich_domains,
)
from .link_healer import (
    _REJECT_PATTERNS,
    LinkHealer,
    heal_broken_links,
)
from .linter import (
    _LINK_PATTERN,
    LintReport,
    MEDIA_EXTENSIONS,
    VaultLinter,
    lint_vault,
)
from .stub_lifecycle import (
    manage_stub_lifecycle,
)
from .title_standardizer import (
    OrthographicHealer,
    TitleStandardizer,
    _update_all_links_vault_wide_batch,
    heal_orthography,
    standardize_titles,
)

__all__ = [
    # Types & Constants
    "BridgeCandidate",
    "LintReport",
    "_CODE_PILL_LINK_PATTERN",
    "_REJECT_PATTERNS",
    "CANONICAL_DOMAINS",
    "_LINK_PATTERN",
    "MEDIA_EXTENSIONS",
    # Core Classes
    "BridgeCandidateFinder",
    "VaultLinter",
    "LinkHealer",
    "DomainEnricher",
    "OrthographicHealer",
    "TitleStandardizer",
    # Facade Functions
    "lint_vault",
    "heal_broken_links",
    "enrich_domains",
    "scan_wikilink_code_pills",
    "heal_orthography",
    "standardize_titles",
    "manage_stub_lifecycle",
    "_update_all_links_vault_wide_batch",
    # Backward Compatibility Re-exports
    "generate_weekly_synthesis",
]
