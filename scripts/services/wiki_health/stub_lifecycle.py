"""VvC Second Brain — Wiki Health: Stub Lifecycle Management.

Scans all stubs, purges orphan stubs (those not linked by any high-quality concept
or source), and records stale pending stubs (age > 30 days) to JSON for Weekly Synthesis.
Part of Deep Module package services.wiki_health.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from core.config import cfg
from core.frontmatter import normalize_stem
from core.vault import scan_all_concepts, scan_all_sources
from .linter import _LINK_PATTERN

_logger = logging.getLogger("vvc.health.stub_lifecycle")


def manage_stub_lifecycle() -> dict[str, int]:
    """Scan all stubs, purge orphan stubs (those not linked by any high-quality concept or source),
    and record stale pending stubs (exists > 30 days) to a JSON file for Weekly Synthesis.

    Returns:
        Dict containing 'purged' count and 'stale' count.
    """
    # 1. Scan concepts and sources using vault utilities
    concepts = scan_all_concepts()
    sources = scan_all_sources()

    # Identify stub concepts and gather their normalized stems
    stubs = []
    stub_stems = set()
    for c in concepts:
        is_stub = (c.get("confidence") == "low" and c.get("source_type") == "stub")
        if is_stub:
            stubs.append(c)
            stub_stems.add(normalize_stem(c["_stem"]))

    if not stubs:
        _logger.info("LinkHealer: No stub notes found in the vault.")
        return {"purged": 0, "stale": 0}

    # 2. Track incoming links to these stubs from high-quality nodes
    incoming_hq_links: dict[str, list[str]] = defaultdict(list)

    # Parse links from non-stub concepts (high-quality concepts)
    for c in concepts:
        stem_norm = normalize_stem(c["_stem"])
        if stem_norm in stub_stems:
            continue  # Skip stubs linking to stubs to prevent circular dependency keeps

        try:
            # Use _links cached in memory if available, otherwise parse file
            links = c.get("_links")
            if links is None:
                content = c["_path"].read_text(encoding="utf-8")
                links = _LINK_PATTERN.findall(content)
                c["_links"] = links

            for link in links:
                norm_link = normalize_stem(link)
                if norm_link in stub_stems:
                    incoming_hq_links[norm_link].append(c["_stem"])
        except OSError:
            pass

    # Parse links from source notes (sources are always considered high-quality)
    for s in sources:
        try:
            content = s["_path"].read_text(encoding="utf-8")
            links = _LINK_PATTERN.findall(content)
            for link in links:
                norm_link = normalize_stem(link)
                if norm_link in stub_stems:
                    incoming_hq_links[norm_link].append(s["_stem"])
        except OSError:
            pass

    # 3. Purge Orphan Stubs
    purged_count = 0
    active_stubs = []
    for stub in stubs:
        norm_stem = normalize_stem(stub["_stem"])
        # An orphan stub is one with 0 incoming links from high-quality concepts or sources
        if not incoming_hq_links[norm_stem]:
            try:
                stub["_path"].unlink()
                _logger.info(f"[health] Purged orphan stub: {stub['_stem']}.md")
                purged_count += 1
            except OSError as e:
                _logger.warning(f"Failed to delete orphan stub {stub['_stem']}.md: {e}")
        else:
            active_stubs.append(stub)

    # 4. Check Stale Pending Stubs (> 30 days) among active stubs
    stale_count = 0
    stale_entries = []
    for stub in active_stubs:
        created_val = stub.get("date_created")
        created_date = None
        if created_val:
            if isinstance(created_val, str):
                try:
                    created_date = date.fromisoformat(created_val)
                except ValueError:
                    pass
            elif isinstance(created_val, (date, datetime)):
                created_date = created_val if isinstance(created_val, date) else created_val.date()

        if created_date:
            age_days = (date.today() - created_date).days
            if age_days > 30:
                stale_count += 1
                stale_entries.append({
                    "stem": stub["_stem"],
                    "title": stub.get("title", stub["_stem"]),
                    "age_days": age_days,
                    "date_created": created_date.isoformat(),
                    "linked_from": incoming_hq_links[normalize_stem(stub["_stem"])][:3]
                })

    # 5. Record stale pending stubs to state directory for Weekly Synthesis
    if stale_entries:
        stale_file = cfg.state_dir / ".stale_stubs.json"
        try:
            stale_file.write_text(json.dumps(stale_entries, ensure_ascii=False, indent=2), encoding="utf-8")
            _logger.info(f"[health] Recorded {len(stale_entries)} stale pending stubs to {stale_file.name}")
        except Exception as e:
            _logger.warning(f"Failed to write stale stubs cache: {e}")

    return {"purged": purged_count, "stale": stale_count}


__all__ = [
    "manage_stub_lifecycle",
]
