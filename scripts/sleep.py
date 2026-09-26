"""VvC Second Brain — Weekly Sleep Consolidation (v8.5).

Runs weekly via Task Scheduler. Performs:
1. Log rotation
2. Legal sync (CCBA registry)
3. Wiki health check (lint)
4. Auto-heal broken links, orthography, titles & domain tags
5. Rebuild MOCs + Index
6. Weekly synthesis report
7. Embedding Index Sync

Architecture: Scan-Once — vault scanned once at pipeline start, shared across all steps.

Usage:
    python sleep.py              # Manual run (debug)
    pythonw.exe sleep.py         # Headless (called by run_sleep.vbs)
    Task Scheduler: VvC_SleepDaemon (Every Sunday 02:00 AM)
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg
from core.file_lock import CrossProcessFileLock
from core.log import log, rotate_log
from core.vault import scan_all_concepts, scan_all_sources

try:
    from services.wiki_health import (
        lint_vault, heal_broken_links, heal_orthography,
        standardize_titles, enrich_domains,
    )
    from services.weekly_synthesis import generate_weekly_synthesis
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

try:
    from wiki_maintain import rebuild_all as _rebuild_all
except ImportError:
    _rebuild_all = None  # type: ignore[assignment]

try:
    from services.update_embeddings import sync_embeddings
    _HAS_EMBED_SYNC = True
except ImportError:
    _HAS_EMBED_SYNC = False

try:
    from services.legal_sync_worker import _generate_legal_sync
    _HAS_LEGAL_SYNC = True
except ImportError:
    _HAS_LEGAL_SYNC = False

import sys as _sys
# PowerShell stdout fix: prevent UnicodeEncodeError on Windows cp1252 console
try:
    _sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sleep] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(cfg.log_dir / "sleep_daemon.log", encoding="utf-8"),
        logging.StreamHandler(_sys.stdout),
    ],
)
_logger = logging.getLogger("vvc.sleep")


def _run_early_maintenance() -> None:
    """Run log rotation and legal synchronization tasks."""
    _logger.info("[1/7] Log rotation...")
    try:
        rotate_log(max_age_days=30)
    except Exception as e:
        _logger.error(f"Log rotation failed: {e}")

    _logger.info("[2/7] Legal sync...")
    if _HAS_LEGAL_SYNC:
        try:
            _generate_legal_sync()
        except Exception as e:
            _logger.error(f"Legal sync failed: {e}")


def _run_health_and_healing(concepts: list[dict]) -> tuple[dict | None, list[dict]]:
    """Run wiki linting, link healing, orthography, and tag enrichment."""
    _logger.info("[3/7] Wiki health check...")
    report = None
    if _HAS_HEALTH:
        try:
            report = lint_vault()
            _logger.info(
                f"Lint: {report['total_concepts']} concepts, "
                f"{len(report['broken_links'])} broken links"
            )
        except Exception as e:
            _logger.error(f"Lint failed: {e}")
    else:
        _logger.info("Wiki health module not available")

    _logger.info("[4/7] Auto-healing (links, orthography, titles & domains)...")
    if _HAS_HEALTH:
        try:
            heal_broken_links(report=report, max_heal_limit=15)
            heal_orthography(concepts=concepts)
            standardize_titles(batch_size=15, concepts=concepts)
            enrich_domains(batch_size=30, concepts=concepts)
        except Exception as e:
            _logger.error(f"Healing failed: {e}")

    return report, scan_all_concepts()


def _run_synthesis_and_sync(
    concepts: list[dict], sources: list[dict], report: dict | None
) -> None:
    """Run MOC rebuilds, synthesis report generation, and vector index sync."""
    _logger.info("[5/7] MOC rebuild...")
    if _rebuild_all is not None:
        try:
            _rebuild_all(concepts=concepts, sources=sources)
        except Exception as e:
            _logger.error(f"MOC rebuild failed: {e}")

    _logger.info("[6/7] Weekly synthesis...")
    try:
        _write_weekly_synthesis(concepts=concepts, sources=sources, report=report)
    except Exception as e:
        _logger.error(f"Weekly synthesis failed: {e}")

    _logger.info("[7/7] Embedding Index Sync...")
    if _HAS_EMBED_SYNC:
        try:
            sync_embeddings(concepts=concepts)
        except Exception as e:
            _logger.error(f"Embedding sync failed: {e}")


def run_sleep_consolidation() -> None:
    """Execute weekly consolidation tasks using Scan-Once architecture."""
    lock_file = cfg.state_dir / "sleep_consolidation.lock"
    try:
        with CrossProcessFileLock(lock_file, timeout=120.0):
            _logger.info("=" * 40)
            _logger.info("Sleep Consolidation v8.5 started")
            log("lifecycle", "Sleep Consolidation started")

            _logger.info("[0/7] Scanning vault (Scan-Once)...")
            concepts = scan_all_concepts()
            sources = scan_all_sources()
            _logger.info(f"Scanned {len(concepts)} concepts, {len(sources)} sources")

            _run_early_maintenance()
            report, concepts = _run_health_and_healing(concepts)
            _run_synthesis_and_sync(concepts, sources, report)

            log("sleep", "Sleep Consolidation completed")
            _logger.info("Sleep Consolidation complete")
    except TimeoutError:
        _logger.warning("Another sleep consolidation process is running; skipping.")


def _write_weekly_synthesis(
    concepts: list[dict] | None = None,
    sources: list[dict] | None = None,
    report: dict | None = None,
) -> None:
    """Generate a weekly synthesis report via SSOT generator."""
    if _HAS_HEALTH:
        generate_weekly_synthesis(
            report=report,
            concepts=concepts,
            sources=sources,
        )
        _logger.info("Weekly synthesis generated successfully via SSOT generator.")
    else:
        _logger.warning("wiki_health module not available, skipping Weekly_Synthesis generation")


if __name__ == "__main__":
    run_sleep_consolidation()
