"""VvC Second Brain — Wiki Health: Bridge Candidate Finder.

Identifies and ranks cross-domain bridge concepts in the Zettelkasten knowledge graph
using Simpson Diversity of neighboring Grand Domains scaled by log-degree.
Part of Deep Module package services.wiki_health (Issue #4).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.frontmatter import normalize_stem
from core.taxonomy import resolve_grand_domains


@dataclass
class BridgeCandidate:
    """Dataclass representing a cross-domain bridge concept candidate."""

    stem: str
    title: str
    domains: list[str]
    connected_domains: list[str]
    degree: int
    bridge_score: float

    def to_dict(self) -> dict[str, Any]:
        """Convert candidate to serializable dictionary format."""
        return {
            "stem": self.stem,
            "title": self.title,
            "domains": self.domains,
            "connected_domains": self.connected_domains,
            "degree": self.degree,
            "bridge_score": round(self.bridge_score, 4),
        }


class BridgeCandidateFinder:
    """Discovers and ranks cross-domain bridge concepts in the vault graph."""

    def __init__(self, concepts: list[dict] | None = None) -> None:
        """Initialize with concepts list or lazy-load from vault."""
        if concepts is not None:
            self.concepts = concepts
        else:
            from core.vault import scan_all_concepts

            self.concepts = scan_all_concepts()

    def _build_alias_resolver(self) -> dict[str, str]:
        """Build resolver mapping stems and aliases to canonical concept stems."""
        resolver: dict[str, str] = {}
        # First pass: map exact stems and normalized stems
        for c in self.concepts:
            stem = c.get("_stem", "")
            if not stem:
                continue
            resolver[stem] = stem
            resolver[stem.lower()] = stem
            resolver[normalize_stem(stem)] = stem

        # Second pass: map aliases without overwriting existing stems
        for c in self.concepts:
            stem = c.get("_stem", "")
            if not stem:
                continue
            aliases = c.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(aliases, list):
                for alias in aliases:
                    if isinstance(alias, str) and alias.strip():
                        a_str = alias.strip()
                        norm_a = normalize_stem(a_str)
                        if norm_a not in resolver:
                            resolver[norm_a] = stem
                        if a_str.lower() not in resolver:
                            resolver[a_str.lower()] = stem
                        if a_str not in resolver:
                            resolver[a_str] = stem
        return resolver

    def _extract_concept_links(self, c: dict) -> list[str]:
        """Extract outgoing links from cached _links, file content, or related field."""
        if c.get("_links") is not None:
            return list(c["_links"])
        path = c.get("_path")
        if path and isinstance(path, Path) and path.exists():
            try:
                import re

                content = path.read_text(encoding="utf-8")
                return re.findall(r"\[\[([^\]|#\n]+)", content)
            except OSError:
                pass
        rel = c.get("related", [])
        if isinstance(rel, str):
            rel = [rel]
        if isinstance(rel, list):
            links = []
            for r in rel:
                if isinstance(r, str):
                    clean = r.replace("[[", "").replace("]]", "").strip()
                    if clean:
                        links.append(clean)
            return links
        return []

    def _build_graph(
        self, resolver: dict[str, str]
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
        """Construct undirected adjacency list and pre-resolve domains and titles."""
        adj: dict[str, set[str]] = {c["_stem"]: set() for c in self.concepts if c.get("_stem")}
        domains: dict[str, set[str]] = {}
        titles: dict[str, str] = {}

        for c in self.concepts:
            stem = c.get("_stem", "")
            if not stem:
                continue
            domains[stem] = resolve_grand_domains(c.get("tags", []))
            titles[stem] = str(c.get("title") or stem)

            raw_links = self._extract_concept_links(c)
            for raw_link in raw_links:
                clean_target = raw_link.split("|", 1)[0].split("#", 1)[0].strip()
                if clean_target.endswith(".md"):
                    clean_target = clean_target[:-3].strip()
                target_stem = resolver.get(clean_target) or resolver.get(clean_target.lower())
                if not target_stem:
                    target_stem = resolver.get(normalize_stem(clean_target))
                if target_stem and target_stem != stem and target_stem in adj:
                    adj[stem].add(target_stem)
                    adj[target_stem].add(stem)

        return adj, domains, titles

    def _score_single_candidate(
        self,
        u: str,
        neighbors: set[str],
        domains: dict[str, set[str]],
        titles: dict[str, str],
        min_degree: int = 2,
        max_degree: int = 25,
    ) -> BridgeCandidate | None:
        """Calculate BridgeCandidate metrics for a single node if passing pruning gates."""
        degree = len(neighbors)
        if degree < min_degree or degree > max_degree:
            return None

        domain_counts: dict[str, int] = defaultdict(int)
        connected_domains_set: set[str] = set()

        for v in neighbors:
            for d in domains.get(v, set()):
                domain_counts[d] += 1
                connected_domains_set.add(d)

        # Multi-domain requirement: neighbors must span >= 2 Grand Domains
        if len(connected_domains_set) < 2:
            return None

        total_domain_links = sum(domain_counts.values())
        if total_domain_links == 0:
            return None

        sum_sq_p = sum((count / total_domain_links) ** 2 for count in domain_counts.values())
        simpson_diversity = max(0.0, 1.0 - sum_sq_p)
        bridge_score = simpson_diversity * math.log2(1 + degree)
        if bridge_score <= 0.0:
            return None

        return BridgeCandidate(
            stem=u,
            title=titles.get(u, u),
            domains=sorted(domains.get(u, set())),
            connected_domains=sorted(connected_domains_set),
            degree=degree,
            bridge_score=bridge_score,
        )

    def score_candidates(
        self,
        top_n: int | None = None,
        min_degree: int = 2,
        max_degree: int = 25,
    ) -> list[BridgeCandidate]:
        """Find and rank all bridge candidates matching topological constraints."""
        resolver = self._build_alias_resolver()
        adj, domains, titles = self._build_graph(resolver)

        candidates: list[BridgeCandidate] = []
        for u, neighbors in adj.items():
            candidate = self._score_single_candidate(
                u, neighbors, domains, titles, min_degree=min_degree, max_degree=max_degree
            )
            if candidate is not None:
                candidates.append(candidate)

        # Deterministic sort: -round(score, 4), -degree, stem ascending
        candidates.sort(key=lambda c: (-round(c.bridge_score, 4), -c.degree, c.stem))

        if top_n is not None:
            return candidates[:max(0, top_n)]
        return candidates


__all__ = ["BridgeCandidate", "BridgeCandidateFinder"]
