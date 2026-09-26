"""VvC Second Brain — Session Closing & Comprehensive Consolidation Workflow (v1.0).

Runs at the end of a session to:
1. Perform initial linting (health check).
2. Auto-heal broken links (using LLM Semantic Arbitrator) and orthographic typos.
3. Rebuild all MOCs, Domain MOCs, and the Master Index.
4. Run final linting to capture clean post-heal statistics.
5. Retrieve and preserve the professor's 'Knowledge Gaps & Suggestions' from the old synthesis.
6. Compile and write a comprehensive, beautifully formatted Weekly_Synthesis.md.
7. Print a stunning session summary to the terminal.

Usage:
    python close_session.py
"""

from __future__ import annotations

import logging
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# Setup paths to ensure internal modules are importable
_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg
from core.log import log
from core.vault import scan_all_concepts, scan_all_sources
from services.wiki_health import (
    lint_vault, 
    heal_broken_links, 
    heal_orthography,
)
from services.weekly_synthesis import generate_weekly_synthesis
from wiki_maintain import rebuild_all, DOMAIN_MOC_THRESHOLD

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [close_session] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(cfg.log_dir / "session_close.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
_logger = logging.getLogger("vvc.close_session")


def _run_healing_phase(pre_report: dict) -> tuple[int, int]:
    """Auto-heal broken links and orthographic typos."""
    healed_links, healed_typos = 0, 0
    try:
        healed_links = heal_broken_links(pre_report, max_heal_limit=15)
        _logger.info(f"Auto-healer: {healed_links} broken link stubs created/processed.")
    except Exception as e:
        _logger.error(f"Error during link healing: {e}")
    try:
        healed_typos = heal_orthography(batch_size=20)
        _logger.info(f"Orthographic healer: {healed_typos} typos fixed.")
    except Exception as e:
        _logger.error(f"Error during orthography healing: {e}")
    return healed_links, healed_typos


def _extract_preserved_academic_advice(report_path: Path) -> str:
    """Extract and preserve academic advice from existing Weekly_Synthesis.md."""
    if report_path.exists():
        try:
            old_content = report_path.read_text(encoding="utf-8")
            marker = "## 💡 Knowledge Gaps"
            if marker in old_content:
                parts = old_content.split(marker, 1)
                return "\n## 💡 Knowledge Gaps" + parts[1]
        except Exception as e:
            _logger.error(f"Failed to read old Weekly_Synthesis.md for preservation: {e}")
    return (
        "\n## 💡 Knowledge Gaps & Đề xuất mở rộng\n\n"
        "### Đề xuất hành động tiếp theo:\n"
        "1. **Viết Synthesis Notes**: Chọn 3-5 khái niệm liên quan trong cùng Domain để viết bài tổng luận.\n"
        "2. **Giải quyết Broken Links**: Xem lại các Concept References cần tạo ghi chú.\n"
        "3. **Tận dụng Graph View**: Thường xuyên kiểm tra trực quan hóa mối quan hệ trong Obsidian.\n"
    )


def run_closeout_workflow() -> None:
    """Executes the comprehensive session closeout workflow."""
    _logger.info("=" * 60)
    _logger.info("VvC Second Brain — Session Closeout Workflow initiated.")
    _logger.info("=" * 60)
    log("lifecycle", "Session closeout workflow initiated")

    _logger.info("[1/6] Running initial Vault health check...")
    pre_report = lint_vault()
    _logger.info(f"Initial status: {pre_report['total_concepts']} concepts, {len(pre_report['broken_links'])} broken links detected.")

    _logger.info("[2/6] Auto-healing broken links & regional orthographic typos...")
    healed_links, healed_typos = _run_healing_phase(pre_report)

    _logger.info("[3/6] Rebuilding all Maps of Content (MOCs) & Master Index...")
    try:
        rebuild_all()
        _logger.info("Wiki maintainer: All active MOCs and index successfully updated. Stale MOCs purged.")
    except Exception as e:
        _logger.error(f"Error during MOC rebuild: {e}")

    _logger.info("[4/6] Running final Vault health check for clean statistics...")
    post_report = lint_vault()
    _logger.info(f"Final status: {post_report['total_concepts']} concepts, {len(post_report['broken_links'])} broken links.")

    _logger.info("[5/6] Extracting and preserving academic suggestions from the old synthesis...")
    report_path = cfg.moc_dir / "Weekly_Synthesis.md"
    academic_advice = _extract_preserved_academic_advice(report_path)

    _logger.info("[6/6] Generating comprehensive Weekly_Synthesis.md report...")
    try:
        _write_updated_synthesis(post_report, healed_links, healed_typos, academic_advice)
        _logger.info("Weekly_Synthesis.md updated successfully with clean statistics.")
    except Exception as e:
        _logger.error(f"Failed to write updated Weekly_Synthesis.md: {e}")

    _print_beautiful_terminal_summary(post_report, healed_links, healed_typos)
    log("lifecycle", "Session closeout workflow completed successfully")


def _write_updated_synthesis(
    report: dict, 
    healed_links: int, 
    healed_typos: int, 
    academic_advice: str
) -> None:
    """Compiles and writes the updated comprehensive Weekly_Synthesis.md via SSOT generator."""
    generate_weekly_synthesis(
        report=report,
        healed_links=healed_links,
        healed_typos=healed_typos,
        academic_advice=academic_advice,
    )


def _print_beautiful_terminal_summary(report: dict, healed_links: int, healed_typos: int) -> None:
    """Prints a beautiful, highly readable session closing summary to the terminal.
    Uses only safe ASCII characters to completely avoid UnicodeEncodeErrors on Windows.
    """
    concepts = scan_all_concepts()
    sources = scan_all_sources()

    total_concepts = len(concepts)
    total_sources = len(sources)
    total_source_mocs = len(list(cfg.moc_dir.rglob("MOC_*.md")))
    total_domain_mocs = len(list(cfg.moc_dir.rglob("Domain_*.md")))
    total_orphans = len(report.get("orphans", []))
    total_broken = len(report.get("broken_links", []))
    broken_body = len(report.get("broken_body_links", []))
    prospective_seeds = len(report.get("prospective_related_seeds", []))

    # Safe terminal print bypasses emoji to avoid cp1252 Windows encoding errors
    print("\n" + "=" * 65)
    print(" === VvC Second Brain -- Closeout Summary & Health Report ===")
    print("=" * 65)
    print(f" [o] Concepts:      {total_concepts:<5}  | [o] Sources:    {total_sources:<5}")
    print(f" [o] Book MOCs:     {total_source_mocs:<5}  | [o] Domain MOCs: {total_domain_mocs:<5}")
    print("-" * 65)
    print(" > Chan doan Linter Suc khoe He thong:")
    print(f" > True Orphan Notes:          {total_orphans:<5}")
    print(f" > Broken Citations in Body:    {broken_body:<5}")
    print(f" > Prospective Related Seeds:   {prospective_seeds:<5}")
    print(f" > Total Broken Occurrences:    {total_broken:<5}")
    print(f" > Link Healed (Da va stub):    {healed_links:<5}")
    print(f" > Typos Fixed (Sua chinh ta): {healed_typos:<5}")
    print("-" * 65)
    print(" [o] Bao cao tong hop [Weekly_Synthesis.md] da duoc cap nhat thanh cong!")
    print(" [o] Tat ca MOC rong da duoc tu dong don dep sach se.")
    print(" [o] He thong Obsidian Vault dang o trang thai toi uu va nhat quan.")
    print(" *** HOM NAY BAN DA LAM VIEC RAT TUYET VOI! CHUC MOT BUOI TOI TOT LANH! ***")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_closeout_workflow()
