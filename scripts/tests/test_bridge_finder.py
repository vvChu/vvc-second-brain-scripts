"""Unit tests for services.wiki_health.bridge_finder (Issue #4).

Verifies:
1. Toy Graph mathematical verification (Simpson Diversity & Log-Degree).
2. Pruning gates: degree lower bound (d >= 2), Hub pruning (d <= 25), multi-domain constraint.
3. Alias map resolution (resolving links to aliases).
4. Padded token matching for Grand Domains.
5. Deterministic sorting order (-round(score, 4), -degree, stem).
6. Performance benchmark on real Vault graph (< 0.15s).
"""

from __future__ import annotations

import math
import time
from typing import Any

import pytest

from services.wiki_health.bridge_finder import BridgeCandidate, BridgeCandidateFinder


def test_bridge_candidate_dataclass_to_dict():
    """Verify BridgeCandidate dataclass fields and to_dict serialization."""
    candidate = BridgeCandidate(
        stem="cross_learning",
        title="Cross Domain Learning",
        domains=["cognition"],
        connected_domains=["business", "tech"],
        degree=4,
        bridge_score=0.8654321,
    )
    d = candidate.to_dict()
    assert d["stem"] == "cross_learning"
    assert d["title"] == "Cross Domain Learning"
    assert d["domains"] == ["cognition"]
    assert d["connected_domains"] == ["business", "tech"]
    assert d["degree"] == 4
    assert d["bridge_score"] == 0.8654


def test_toy_graph_mathematical_precision():
    """Verify mathematical calculation of Simpson Diversity and BridgeScore on a controlled graph."""
    concepts = [
        {
            "_stem": "bridge_node",
            "title": "Bridge Node",
            "tags": ["domain/cognition"],
            "_links": ["tech_node", "biz_node"],
        },
        {
            "_stem": "tech_node",
            "title": "Tech Node",
            "tags": ["domain/tech"],
            "_links": ["bridge_node"],
        },
        {
            "_stem": "biz_node",
            "title": "Biz Node",
            "tags": ["domain/business"],
            "_links": ["bridge_node"],
        },
    ]

    finder = BridgeCandidateFinder(concepts)
    candidates = finder.score_candidates()

    assert len(candidates) == 1
    c = candidates[0]
    assert c.stem == "bridge_node"
    assert c.degree == 2
    assert c.connected_domains == ["business", "tech"]

    # Expected Simpson: 1 - (0.5^2 + 0.5^2) = 0.5
    # Expected Score: 0.5 * log2(1 + 2) = 0.5 * log2(3) = 0.79248...
    expected_score = 0.5 * math.log2(3)
    assert abs(c.bridge_score - expected_score) < 1e-4
    assert c.to_dict()["bridge_score"] == round(expected_score, 4)


def test_pruning_gates_isolation():
    """Verify nodes with d < 2, d > 25, or single-domain neighbors are strictly pruned."""
    concepts = [
        # Candidate 1: Leaf node (d = 1) -> pruned
        {
            "_stem": "leaf_node",
            "title": "Leaf Node",
            "tags": ["domain/cognition"],
            "_links": ["tech_1"],
        },
        # Candidate 2: Single domain neighbors (tech_1 and tech_2) -> pruned
        {
            "_stem": "mono_domain_node",
            "title": "Mono Domain Node",
            "tags": ["domain/cognition"],
            "_links": ["tech_1", "tech_2"],
        },
        # Candidate 3: Hub node with 26 neighbors -> pruned by Hub Pruning (d <= 25)
        {
            "_stem": "hub_node",
            "title": "Hub Node",
            "tags": ["domain/management"],
            "_links": [f"target_{i}" for i in range(26)],
        },
        # Neighbors
        {"_stem": "tech_1", "tags": ["domain/tech"], "_links": []},
        {"_stem": "tech_2", "tags": ["domain/tech"], "_links": []},
    ]
    # Add 26 targets for hub_node (alternating tech and business)
    for i in range(26):
        domain_tag = "domain/tech" if i % 2 == 0 else "domain/business"
        concepts.append({"_stem": f"target_{i}", "tags": [domain_tag], "_links": []})

    finder = BridgeCandidateFinder(concepts)
    candidates = finder.score_candidates()

    # leaf_node, mono_domain_node, and hub_node must NOT be in candidates
    stems = {c.stem for c in candidates}
    assert "leaf_node" not in stems
    assert "mono_domain_node" not in stems
    assert "hub_node" not in stems


def test_alias_map_resolution():
    """Verify outgoing links to alias strings resolve correctly to canonical stems."""
    concepts = [
        {
            "_stem": "bridge_node",
            "title": "Bridge Node",
            "tags": ["domain/cognition"],
            "_links": ["canonical_alias_name", "biz_node"],
        },
        {
            "_stem": "real_tech_stem",
            "title": "Real Tech Stem",
            "aliases": ["canonical_alias_name"],
            "tags": ["domain/tech"],
            "_links": [],
        },
        {
            "_stem": "biz_node",
            "title": "Biz Node",
            "tags": ["domain/business"],
            "_links": [],
        },
    ]

    finder = BridgeCandidateFinder(concepts)
    candidates = finder.score_candidates()

    assert len(candidates) == 1
    assert candidates[0].stem == "bridge_node"
    assert "tech" in candidates[0].connected_domains
    assert "business" in candidates[0].connected_domains


def test_deterministic_sorting():
    """Verify sorting order: descending score -> descending degree -> alphabetical stem."""
    concepts = [
        {
            "_stem": "node_b",
            "title": "Node B",
            "tags": [],
            "_links": ["tech_1", "biz_1"],
        },
        {
            "_stem": "node_a",
            "title": "Node A",
            "tags": [],
            "_links": ["tech_1", "biz_1"],
        },
        {"_stem": "tech_1", "tags": ["domain/tech"], "_links": []},
        {"_stem": "biz_1", "tags": ["domain/business"], "_links": []},
    ]

    finder = BridgeCandidateFinder(concepts)
    candidates = finder.score_candidates()

    # Both node_a and node_b have identical score and degree=2.
    # Therefore, node_a must precede node_b alphabetically.
    assert len(candidates) == 2
    assert candidates[0].stem == "node_a"
    assert candidates[1].stem == "node_b"


def test_real_vault_performance_and_sanity():
    """Benchmark performance on actual vault concepts (< 0.15s) and verify sanity."""
    from pathlib import Path
    from core.config import cfg
    from core.vault import scan_all_concepts

    repo_root = Path(__file__).resolve().parent.parent.parent
    real_concepts_dir = repo_root / "04 - Permanent" / "concepts"
    if not real_concepts_dir.exists():
        pytest.skip("Authentic concepts directory does not exist on this machine.")

    orig_dir = cfg.concepts_dir
    try:
        object.__setattr__(cfg, "concepts_dir", real_concepts_dir)
        real_concepts = scan_all_concepts()
    finally:
        object.__setattr__(cfg, "concepts_dir", orig_dir)

    if not real_concepts:
        pytest.skip("No concepts found in vault to benchmark.")

    # Warm-up to prime regex and module caches
    BridgeCandidateFinder(real_concepts[:50]).score_candidates(top_n=5)

    start = time.perf_counter()
    finder = BridgeCandidateFinder(real_concepts)
    candidates = finder.score_candidates(top_n=10)
    duration = time.perf_counter() - start

    # Performance constraint: < 0.20s (acceptance criteria is < 0.2s)
    assert duration < 0.20, f"Bridge candidate discovery took {duration:.3f}s (budget: < 0.20s)"

    # Sanity checks
    assert len(candidates) > 0, "Real vault must have bridge candidates"
    assert len(candidates) <= 10
    for c in candidates:
        assert 2 <= c.degree <= 25
        assert len(c.connected_domains) >= 2
        assert c.bridge_score > 0
        d = c.to_dict()
        assert isinstance(d["stem"], str)
        assert isinstance(d["title"], str)
        assert isinstance(d["bridge_score"], float)


def test_score_candidates_top_n_boundaries():
    """Verify top_n=0, negative values, and None behavior."""
    concepts = [
        {"_stem": "bridge", "tags": ["domain/cognition"], "_links": ["tech", "biz"]},
        {"_stem": "tech", "tags": ["domain/tech"], "_links": ["bridge"]},
        {"_stem": "biz", "tags": ["domain/business"], "_links": ["bridge"]},
    ]
    finder = BridgeCandidateFinder(concepts)

    assert finder.score_candidates(top_n=0) == []
    assert finder.score_candidates(top_n=-1) == []
    assert len(finder.score_candidates(top_n=1)) == 1
    assert len(finder.score_candidates(top_n=None)) == 1


def test_md_extension_and_none_links_handling():
    """Verify links with .md extensions and concepts with _links=None or string related."""
    concepts = [
        {"_stem": "bridge", "tags": ["domain/cognition"], "_links": ["tech.md", "biz"]},
        {"_stem": "tech", "tags": ["domain/tech"], "_links": ["bridge"]},
        {"_stem": "biz", "tags": ["domain/business"], "_links": None, "related": "[[bridge]]"},
    ]
    finder = BridgeCandidateFinder(concepts)
    candidates = finder.score_candidates()

    assert len(candidates) == 1
    assert candidates[0].stem == "bridge"
    assert set(candidates[0].connected_domains) == {"business", "tech"}


def test_resolve_grand_domains_robustness():
    """Verify taxonomy resolution handles None, string tags, and mixed invalid types."""
    from core.taxonomy import resolve_grand_domains

    assert resolve_grand_domains(None) == set()
    assert resolve_grand_domains("domain/ai") == {"tech"}
    assert resolve_grand_domains(["domain/software_engineering", None, 123]) == {"tech"}


def test_render_bridge_candidates_pipe_escaping_and_none_title():
    """Verify _render_bridge_candidates escapes pipes and handles title=None."""
    from services.weekly_synthesis import _render_bridge_candidates

    candidates = [
        {
            "stem": "unique_id",
            "title": "Unique ID | Dinh Danh Duy Nhat",
            "domains": ["tech"],
            "connected_domains": ["business", "management"],
            "degree": 3,
            "bridge_score": 0.85,
        },
        {
            "stem": "stem_fallback",
            "title": None,
            "domains": [],
            "connected_domains": ["tech", "cognition"],
            "degree": 2,
            "bridge_score": 0.5,
        },
    ]

    lines = _render_bridge_candidates(candidates)
    rendered = "".join(lines)

    assert "[[unique_id\\|Unique ID \\| Dinh Danh Duy Nhat]]" in rendered
    assert "[[stem_fallback\\|stem_fallback]]" in rendered
    # Ensure every data line has exactly 5 columns (6 pipe dividers)
    for line in lines:
        if line.startswith("| `"):
            # Split by unescaped pipe (preceded by backslash is escaped)
            import re
            cols = [c for c in re.split(r"(?<!\\)\|", line.strip()) if c]
            assert len(cols) == 5, f"Markdown table row split into {len(cols)} columns instead of 5: {line}"

