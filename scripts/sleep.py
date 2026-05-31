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
from core.log import log, rotate_log
from core.vault import scan_all_concepts, scan_all_sources

try:
    from services.wiki_health import (
        lint_vault, heal_broken_links, heal_orthography,
        standardize_titles, enrich_domains,
    )
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


def run_sleep_consolidation() -> None:
    """Execute weekly consolidation tasks using Scan-Once architecture."""
    _logger.info("=" * 40)
    _logger.info("Sleep Consolidation v8.5 started")
    log("lifecycle", "Sleep Consolidation started")

    # ── Scan-Once: Read vault once, share everywhere ──
    _logger.info("[0/7] Scanning vault (Scan-Once)...")
    concepts = scan_all_concepts()
    sources = scan_all_sources()
    _logger.info(f"Scanned {len(concepts)} concepts, {len(sources)} sources")

    # 1. Log rotation
    _logger.info("[1/7] Log rotation...")
    try:
        rotate_log(max_age_days=30)
    except Exception as e:
        _logger.error(f"Log rotation failed: {e}")

    # 2. Legal Sync
    _logger.info("[2/7] Legal sync...")
    if _HAS_LEGAL_SYNC:
        try:
            _generate_legal_sync()
        except Exception as e:
            _logger.error(f"Legal sync failed: {e}")

    # 3. Wiki health check (uses shared concepts via VaultLinter)
    _logger.info("[3/7] Wiki health check...")
    report = None
    if _HAS_HEALTH:
        try:
            report = lint_vault()
            _logger.info(f"Lint: {report['total_concepts']} concepts, {len(report['broken_links'])} broken links")
        except Exception as e:
            _logger.error(f"Lint failed: {e}")
    else:
        _logger.info("Wiki health module not available")

    # 4. Auto-heal broken links, orthography, titles & domain tags
    _logger.info("[4/7] Auto-healing (links, orthography, titles & domains)...")
    if _HAS_HEALTH:
        try:
            heal_broken_links(report=report, max_heal_limit=15)
            heal_orthography(concepts=concepts)
            standardize_titles(batch_size=15, concepts=concepts)
            enrich_domains(batch_size=30, concepts=concepts)
        except Exception as e:
            _logger.error(f"Healing failed: {e}")

    # 5. Rebuild MOCs + Index (uses shared concepts + sources)
    _logger.info("[5/7] MOC rebuild...")
    if _rebuild_all is not None:
        try:
            # Re-scan after healing may have created/renamed files
            concepts = scan_all_concepts()
            _rebuild_all(concepts=concepts, sources=sources)
        except Exception as e:
            _logger.error(f"MOC rebuild failed: {e}")

    # 6. Write weekly synthesis (uses shared concepts)
    _logger.info("[6/7] Weekly synthesis...")
    try:
        _write_weekly_synthesis(concepts=concepts)
    except Exception as e:
        _logger.error(f"Weekly synthesis failed: {e}")

    # 7. Embedding Index Sync (uses shared concepts)
    _logger.info("[7/7] Embedding Index Sync...")
    if _HAS_EMBED_SYNC:
        try:
            sync_embeddings(concepts=concepts)
        except Exception as e:
            _logger.error(f"Embedding sync failed: {e}")

    log("sleep", "Sleep Consolidation completed")
    _logger.info("Sleep Consolidation complete")


def _write_weekly_synthesis(concepts: list[dict] | None = None) -> None:
    """Generate a weekly synthesis report."""
    from datetime import timedelta
    import json

    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()

    # Count recent concepts
    if concepts is None:
        concepts = scan_all_concepts()

    recent = []
    for fm in concepts:
        created = fm.get("date_created", "")
        if isinstance(created, (date, datetime)):
            created = created.isoformat()
        else:
            created = str(created)
        if created >= week_ago:
            recent.append(fm.get("title", fm["_stem"]))

    # Count weekly events from log.md (simple line matching)
    merges = quality_rejects = subsumes = dumps = 0
    try:
        for line in cfg.log_file.read_text(encoding="utf-8").splitlines():
            if line[3:13] < week_ago:
                continue
            if "**merge**" in line:
                merges += 1
            elif "**quality**" in line:
                quality_rejects += 1
            elif "**subsume**" in line:
                subsumes += 1
            elif "**dump**" in line and "detected" in line:
                dumps += 1
    except Exception:
        pass

    # Safe count of total concepts and sources to prevent crash if unmounted
    total_concepts = sum(1 for f in cfg.concepts_dir.iterdir() if f.suffix == '.md') if cfg.concepts_dir.exists() else 0
    total_sources = sum(1 for f in cfg.sources_dir.rglob("*.md")) if cfg.sources_dir.exists() else 0

    # Write report
    report_path = cfg.moc_dir / "Weekly_Synthesis.md"
    lines = [
        f"# 📊 Weekly Synthesis — {today.isoformat()}\n\n",
        f"## Stats\n\n",
        f"- **New concepts this week:** {len(recent)}\n",
        f"- **Merges:** {merges}\n",
        f"- **Quality rejections:** {quality_rejects}\n",
        f"- **Subsumed (trùng lặp):** {subsumes}\n",
        f"- **Brain Dumps:** {dumps}\n",
        f"- **Total concepts:** {total_concepts}\n",
        f"- **Total sources:** {total_sources}\n\n",
    ]

    if recent:
        lines.append("## New Concepts\n\n")
        for title in recent[:20]:
            lines.append(f"- {title}\n")
        lines.append("\n")

    # Read and append domain suggestions if any
    suggestion_file = Path(__file__).parent / ".domain_suggestions.json"
    if suggestion_file.exists():
        try:
            suggestions = json.loads(suggestion_file.read_text(encoding="utf-8"))
            if suggestions:
                lines.append("## 💡 Đề Xuất Mở Rộng Lĩnh Vực (Domain Suggestions)\n\n")
                lines.append(
                    "Phát hiện các khái niệm có xu hướng thuộc lĩnh vực mới chưa nằm trong danh mục chuẩn hóa. "
                    "Hãy xem xét bổ sung các từ khóa này vào `CANONICAL_DOMAINS` trong `wiki_health.py` nếu cần thiết:\n\n"
                )
                for s in suggestions:
                    stem = s.get("concept_stem")
                    title = s.get("concept_title", stem)
                    domain = s.get("suggested_domain")
                    summary = s.get("summary", "")
                    summary_part = f" — *{summary}*" if summary else ""
                    lines.append(f"- **domain/{domain}**: Gợi ý từ [[{stem}|{title}]]{summary_part}\n")
                lines.append("\n")
                
                # Delete suggestion file so it starts fresh next week
                suggestion_file.unlink(missing_ok=True)
                _logger.info(f"Appended {len(suggestions)} domain suggestions to Weekly Synthesis and cleared cache.")
        except Exception as e:
            _logger.error(f"Failed to read or process domain suggestions: {e}")

    # Read and append SUBSUME journal for weekly review
    subsume_journal = cfg.state_dir / ".subsume_journal.jsonl"
    if subsume_journal.exists():
        try:
            entries = []
            for raw_line in subsume_journal.read_text(encoding="utf-8").splitlines():
                raw_line = raw_line.strip()
                if raw_line:
                    entries.append(json.loads(raw_line))
            if entries:
                lines.append("## 🔄 SUBSUME Review (Concepts bị bỏ qua do trùng lặp)\n\n")
                lines.append(
                    "> Các concept dưới đây đã bị Arbitrator đánh giá là **tập con hoàn toàn** của concept hiện có. "
                    "Chúng không được tạo mới. Hãy review nếu cần bổ sung thông tin bị bỏ sót.\n\n"
                )
                lines.append("| Ngày | Concept mới (bị bỏ) | Đã có trong | Score |\n")
                lines.append("|---|---|---|---|\n")
                for e in entries:
                    ts = e.get("timestamp", "")[:10]
                    new_title = e.get("new_title", "?")
                    existing = e.get("existing_concept", "?").replace(".md", "")
                    score = e.get("similarity_score", 0)
                    lines.append(f"| {ts} | {new_title} | [[{existing}]] | {score:.3f} |\n")
                lines.append("\n")
                
                # Clear journal after processing
                subsume_journal.unlink(missing_ok=True)
                _logger.info(f"Appended {len(entries)} SUBSUME events to Weekly Synthesis and cleared journal.")
        except Exception as e:
            _logger.error(f"Failed to read subsume journal: {e}")

    try:
        report_path.write_text("".join(lines), encoding="utf-8")
        _logger.info(f"Weekly synthesis: {len(recent)} new concepts")
    except OSError as e:
        _logger.error(f"Failed to write synthesis: {e}")


if __name__ == "__main__":
    run_sleep_consolidation()
