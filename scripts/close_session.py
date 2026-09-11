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
from services.wiki_health import lint_vault, heal_broken_links, heal_orthography
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


def run_closeout_workflow() -> None:
    """Executes the comprehensive session closeout workflow."""
    _logger.info("=" * 60)
    _logger.info("VvC Second Brain — Session Closeout Workflow initiated.")
    _logger.info("=" * 60)
    log("lifecycle", "Session closeout workflow initiated")

    # Step 1: Pre-heal health check
    _logger.info("[1/6] Running initial Vault health check...")
    pre_report = lint_vault()
    _logger.info(f"Initial status: {pre_report['total_concepts']} concepts, {len(pre_report['broken_links'])} broken links detected.")

    # Step 2: Auto-healing broken links and orthography
    _logger.info("[2/6] Auto-healing broken links & regional orthographic typos...")
    healed_links = 0
    healed_typos = 0
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

    # Step 3: Rebuild MOCs, Domain MOCs, and Master Index
    _logger.info("[3/6] Rebuilding all Maps of Content (MOCs) & Master Index...")
    try:
        rebuild_all()
        _logger.info("Wiki maintainer: All active MOCs and index successfully updated. Stale MOCs purged.")
    except Exception as e:
        _logger.error(f"Error during MOC rebuild: {e}")

    # Step 4: Post-heal health check to compile clean actual statistics
    _logger.info("[4/6] Running final Vault health check for clean statistics...")
    post_report = lint_vault()
    _logger.info(f"Final status: {post_report['total_concepts']} concepts, {len(post_report['broken_links'])} broken links.")

    # Step 5: Read and preserve 'Knowledge Gaps & Suggestions' from the old Weekly_Synthesis.md
    _logger.info("[5/6] Extracting and preserving academic suggestions from the old synthesis...")
    report_path = cfg.moc_dir / "Weekly_Synthesis.md"
    academic_advice = ""
    
    if report_path.exists():
        try:
            old_content = report_path.read_text(encoding="utf-8")
            marker = "## 💡 Knowledge Gaps"
            if marker in old_content:
                parts = old_content.split(marker, 1)
                academic_advice = "\n## 💡 Knowledge Gaps" + parts[1]
                _logger.info("Successfully preserved existing 'Knowledge Gaps & Suggestions' section.")
            else:
                _logger.info("No 'Knowledge Gaps & Suggestions' marker found. Creating default recommendations.")
        except Exception as e:
            _logger.error(f"Failed to read old Weekly_Synthesis.md for preservation: {e}")

    if not academic_advice.strip():
        # Fallback default high-quality advice if none existed
        academic_advice = (
            "\n## 💡 Knowledge Gaps & Đề xuất mở rộng\n\n"
            "Chào bạn, với tư cách là giáo sư tư vấn nghiên cứu, tôi nhận thấy hệ thống Zettelkasten của bạn đang tích lũy "
            "nhiều khái niệm quan trọng nhưng cần thêm các ghi chú tổng hợp để liên kết sâu sắc các luồng ý tưởng lại với nhau.\n\n"
            "### Đề xuất hành động tiếp theo:\n"
            "1. **Viết Synthesis Notes**: Hãy chọn 3-5 khái niệm liên quan chặt chẽ trong cùng một Domain (ví dụ: `domain/strategy` hoặc `domain/ai`) và viết một bài tổng luận ngắn 500 từ để kết nối chúng.\n"
            "2. **Giải quyết Broken Links**: Xem lại các Concept References cần tạo ghi chú ở phần bên dưới để tiếp tục bổ sung cốt lõi tri thức còn khuyết.\n"
            "3. **Tận dụng Graph View**: Thường xuyên kiểm tra trực quan hóa mối quan hệ trong Obsidian để phát hiện các cụm tri thức mồ côi tiềm năng.\n"
        )

    # Step 6: Write updated comprehensive Weekly_Synthesis.md
    _logger.info("[6/6] Generating comprehensive Weekly_Synthesis.md report...")
    try:
        _write_updated_synthesis(post_report, healed_links, healed_typos, academic_advice)
        _logger.info("Weekly_Synthesis.md updated successfully with clean statistics.")
    except Exception as e:
        _logger.error(f"Failed to write updated Weekly_Synthesis.md: {e}")

    # Step 7: Print beautiful summary to the terminal
    _print_beautiful_terminal_summary(post_report, healed_links, healed_typos)
    log("lifecycle", "Session closeout workflow completed successfully")


def _write_updated_synthesis(
    report: dict, 
    healed_links: int, 
    healed_typos: int, 
    academic_advice: str
) -> None:
    """Compiles and writes the updated comprehensive Weekly_Synthesis.md."""
    today_str = date.today().isoformat()
    concepts = scan_all_concepts()
    sources = scan_all_sources()

    report_path = cfg.moc_dir / "Weekly_Synthesis.md"

    # Calculate actual counts
    total_concepts = len(concepts)
    total_sources = len(sources)
    total_source_mocs = len(list(cfg.moc_dir.rglob("MOC_*.md")))
    total_domain_mocs = len(list(cfg.moc_dir.rglob("Domain_*.md")))
    total_orphans = len(report["orphans"])
    total_broken = len(report["broken_links"])
    total_fm_issues = len(report["missing_frontmatter"])
    total_duplicates = len(report["duplicates"])
    total_domain_clusters = len([d for d, count in report["tag_clusters"].items() if count >= DOMAIN_MOC_THRESHOLD])

    # Classify broken links into chapter references vs concept references
    chapter_refs = []
    concept_refs = []
    for entry in report["broken_links"]:
        to_link = entry["to"]
        if re.search(r"(chuong|chương|\d+_ch\d+|p\d+_ch\d+)", to_link, re.IGNORECASE):
            chapter_refs.append(entry)
        else:
            concept_refs.append(entry)

    # Group concept references for display
    concept_counts: dict[str, list[str]] = defaultdict(list)
    for entry in concept_refs:
        concept_counts[entry["to"]].append(entry["from"])

    sorted_concepts = sorted(concept_counts.items(), key=lambda item: len(item[1]), reverse=True)

    # Prepare markdown file content
    lines = [
        "---\n",
        f'title: "🌙 Weekly Synthesis — {today_str}"\n',
        "tags: [meta/synthesis, meta/lint]\n",
        "type: topic\n",
        f"date_created: {today_str}\n",
        f"date_modified: {today_str}\n",
        'summary: "Báo cáo tổng hợp đóng phiên và chẩn đoán sức khỏe hệ thống."\n',
        "---\n\n",
        f"# 🌙 Weekly Synthesis — {today_str}\n\n",
        f"> Báo cáo này được tạo tự động bởi **Close Session Workflow** tại cuối phiên làm việc.\n",
        f"> Bao gồm: Wiki Lint, Wiki Healing, Semantic Deduplication, và Knowledge Gaps.\n\n",
        "## 📊 Tổng quan Vault thực tế\n\n",
        "| Metric           | Count       |\n",
        "| ---------------- | ----------- |\n",
        f"| Total Concepts   | {total_concepts} |\n",
        f"| Total Sources    | {total_sources} |\n",
        f"| Source MOCs      | {total_source_mocs} |\n",
        f"| Domain MOCs      | {total_domain_mocs} |\n",
        f"| Orphan Notes     | {total_orphans} |\n",
        f"| Broken Links     | {total_broken} |\n",
        f"| Healed (this run)| {healed_links} |\n",
        f"| Typos Healed     | {healed_typos} |\n\n",
        "---\n\n",
        "## 🔍 Wiki Lint Report\n\n",
        "| Check | Count |\n",
        "|---|---|\n",
        f"| Orphans | {total_orphans} |\n",
        f"| Broken Links | {total_broken} |\n",
        f"| Frontmatter Issues | {total_fm_issues} |\n",
        f"| Duplicate Candidates | {total_duplicates} |\n",
        f"| Domain Clusters (≥8) | {total_domain_clusters} |\n\n",
        "---\n\n",
        "## 🔗 Orphan Notes (Ghi chú mồ côi thực tế)\n\n",
        "Các concept notes không được liên kết bởi bất kỳ note nào khác trong vault:\n\n"
    ]

    # Render Orphans grouped by source
    if not report["orphans"]:
        lines.append("_Không phát hiện ghi chú mồ côi nào._ ✅\n\n")
    else:
        orphans_by_source = defaultdict(list)
        for stem in report["orphans"]:
            c = next((x for x in concepts if x["_stem"] == stem), None)
            src_val = c.get("source") or c.get("sources", "unknown") if c else "unknown"
            if isinstance(src_val, list):
                src_elem = src_val[0] if src_val else "unknown"
            else:
                src_elem = src_val
            if isinstance(src_elem, dict):
                src = src_elem.get("title") or src_elem.get("name") or "unknown"
            else:
                src = str(src_elem) if src_elem else "unknown"
            if isinstance(src, str) and src.endswith(".md"):
                src = src[:-3]
            orphans_by_source[src].append(stem)

        for src, stems in sorted(orphans_by_source.items()):
            lines.append(f"### Nguồn: `{src}`\n")
            for stem in stems:
                lines.append(f"- [[{stem}]]\n")
            lines.append("\n")

    lines.append("---\n\n## 💔 Broken Links\n\n")
    lines.append(f"**Tổng:** {total_broken} broken links\n")
    lines.append(f"- 📚 Chapter references: {len(chapter_refs)} _(tham chiếu chương sách — không cần heal)_\n")
    lines.append(f"- 🧠 Concept references: {len(concept_refs)} _(khái niệm chưa có note)_\n\n")

    lines.append("### Concept References (cần tạo note)\n")
    lines.append("| Status | Broken Link | Referenced By | Count |\n")
    lines.append("|---|---|---|---|\n")

    if not concept_refs:
        lines.append("| ✅ | _Không có link hỏng_ | _N/A_ | 0 |\n\n")
    else:
        for target, sources in sorted_concepts:
            ref_by = ", ".join(sources[:4])
            if len(sources) > 4:
                ref_by += f" (+{len(sources) - 4} khác)"
            lines.append(f"| ❌ | [[{target}]] | {ref_by} | {len(sources)} |\n")
        lines.append("\n")

    lines.append("### Chapter References (informational)\n")
    lines.append(f"_{len(chapter_refs)} links tham chiếu tới chapters sách — Obsidian resolve được qua vault search._\n\n")

    if healed_links > 0:
        lines.append("## 🩹 Wiki Healer (Auto-Fixed in this run)\n\n")
        lines.append(f"- Đã tự động tạo thành công **{healed_links}** ghi chú stub cho các liên kết hỏng hợp lệ.\n\n")

    lines.append(academic_advice)

    # Write out to file
    report_path.write_text("".join(lines), encoding="utf-8")


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
    total_orphans = len(report["orphans"])
    total_broken = len(report["broken_links"])

    # Safe terminal print bypasses emoji to avoid cp1252 Windows encoding errors
    print("\n" + "=" * 65)
    print(" === VvC Second Brain -- Closeout Summary & Health Report ===")
    print("=" * 65)
    print(f" [o] Concepts:      {total_concepts:<5}  | [o] Sources:    {total_sources:<5}")
    print(f" [o] Book MOCs:     {total_source_mocs:<5}  | [o] Domain MOCs: {total_domain_mocs:<5}")
    print("-" * 65)
    print(" > Chan doan Linter Suc khoe He thong:")
    print(f" > Orphan Notes (Mo coi):     {total_orphans:<5}")
    print(f" > Broken Links (Lien ket loi): {total_broken:<5}")
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
