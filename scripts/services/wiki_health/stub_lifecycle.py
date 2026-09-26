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


def _collect_incoming_hq_links(
    concepts: list[dict],
    sources: list[dict],
    stub_stems: set[str],
) -> dict[str, list[str]]:
    """Track incoming links to stubs from high-quality concepts and sources."""
    incoming_hq_links: dict[str, list[str]] = defaultdict(list)
    for c in concepts:
        if normalize_stem(c["_stem"]) in stub_stems:
            continue
        try:
            links = c.get("_links")
            if links is None:
                links = _LINK_PATTERN.findall(c["_path"].read_text(encoding="utf-8"))
                c["_links"] = links
            for link in links:
                norm_link = normalize_stem(link)
                if norm_link in stub_stems:
                    incoming_hq_links[norm_link].append(c["_stem"])
        except OSError:
            pass

    for s in sources:
        try:
            for link in _LINK_PATTERN.findall(s["_path"].read_text(encoding="utf-8")):
                norm_link = normalize_stem(link)
                if norm_link in stub_stems:
                    incoming_hq_links[norm_link].append(s["_stem"])
        except OSError:
            pass
    return incoming_hq_links


def _purge_orphan_stubs(
    stubs: list[dict],
    incoming_hq_links: dict[str, list[str]],
) -> tuple[int, list[dict]]:
    """Delete stubs with 0 incoming links from high-quality concepts or sources."""
    purged_count = 0
    active_stubs = []
    for stub in stubs:
        norm_stem = normalize_stem(stub["_stem"])
        if not incoming_hq_links[norm_stem]:
            try:
                stub["_path"].unlink()
                _logger.info(f"[health] Purged orphan stub: {stub['_stem']}.md")
                purged_count += 1
            except OSError as e:
                _logger.warning(f"Failed to delete orphan stub {stub['_stem']}.md: {e}")
        else:
            active_stubs.append(stub)
    return purged_count, active_stubs


def _record_stale_stubs(
    active_stubs: list[dict],
    incoming_hq_links: dict[str, list[str]],
) -> int:
    """Identify stubs older than 30 days and save to state directory."""
    stale_entries = []
    today = date.today()
    for stub in active_stubs:
        created_val = stub.get("date_created")
        created_date = None
        if isinstance(created_val, str):
            try:
                created_date = date.fromisoformat(created_val)
            except ValueError:
                pass
        elif isinstance(created_val, (date, datetime)):
            created_date = created_val if isinstance(created_val, date) else created_val.date()

        if created_date:
            age_days = (today - created_date).days
            if age_days > 30:
                stale_entries.append({
                    "stem": stub["_stem"],
                    "title": stub.get("title", stub["_stem"]),
                    "age_days": age_days,
                    "date_created": created_date.isoformat(),
                    "linked_from": incoming_hq_links[normalize_stem(stub["_stem"])][:3],
                })

    if stale_entries:
        stale_file = cfg.state_dir / ".stale_stubs.json"
        try:
            stale_file.write_text(json.dumps(stale_entries, ensure_ascii=False, indent=2), encoding="utf-8")
            _logger.info(f"[health] Recorded {len(stale_entries)} stale pending stubs to {stale_file.name}")
        except Exception as e:
            _logger.warning(f"Failed to write stale stubs cache: {e}")

    return len(stale_entries)


def manage_stub_lifecycle() -> dict[str, int]:
    """Scan all stubs, purge orphan stubs and record stale stubs for Weekly Synthesis."""
    concepts = scan_all_concepts()
    sources = scan_all_sources()

    stubs = [c for c in concepts if c.get("confidence") == "low" and c.get("source_type") == "stub"]
    if not stubs:
        _logger.info("LinkHealer: No stub notes found in the vault.")
        return {"purged": 0, "stale": 0}

    stub_stems = {normalize_stem(c["_stem"]) for c in stubs}
    incoming_hq_links = _collect_incoming_hq_links(concepts, sources, stub_stems)
    purged_count, active_stubs = _purge_orphan_stubs(stubs, incoming_hq_links)
    stale_count = _record_stale_stubs(active_stubs, incoming_hq_links)

    return {"purged": purged_count, "stale": stale_count}


__all__ = [
    "manage_stub_lifecycle",
]
