"""VvC Second Brain — Weekly Synthesis Report Generator.

Compiles and writes the standardized, graph-safe 00 - Maps of Content/Weekly_Synthesis.md.
Extracted from services.wiki_health to enforce Single Responsibility Principle.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.wiki_health import LintReport

from core.config import cfg
from core.vault import scan_all_concepts, scan_all_sources

_logger = logging.getLogger("vvc.weekly_synthesis")

__all__ = ["generate_weekly_synthesis"]


def generate_weekly_synthesis(
    report: LintReport | None = None,
    healed_links: int = 0,
    healed_typos: int = 0,
    academic_advice: str = "",
    concepts: list[dict] | None = None,
    sources: list[dict] | None = None,
) -> Path:
    """Compiles and writes the standardized, graph-safe Weekly_Synthesis.md."""
    today = date.today()
    today_str = today.isoformat()
    week_ago = (today - timedelta(days=7)).isoformat()

    if concepts is None:
        concepts = scan_all_concepts()
    if sources is None:
        sources = scan_all_sources()
    if report is None:
        from services.wiki_health import lint_vault
        report = lint_vault()

    report_path = cfg.moc_dir / "Weekly_Synthesis.md"

    # Count recent concepts created in the last 7 days
    recent = []
    for fm in concepts:
        created = fm.get("date_created", "")
        if isinstance(created, (date, datetime)):
            created = created.isoformat()
        else:
            created = str(created)
        if created >= week_ago:
            recent.append(fm.get("title") or fm["_stem"])

    # Count weekly events from log.md
    merges = quality_rejects = subsumes = dumps = 0
    if cfg.log_file.exists():
        try:
            for line in cfg.log_file.read_text(encoding="utf-8").splitlines():
                if len(line) >= 13 and line[3:13] < week_ago:
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

    total_concepts = len(concepts)
    total_sources = len(sources)
    total_source_mocs = len(list(cfg.moc_dir.rglob("MOC_*.md")))
    total_domain_mocs = len(list(cfg.moc_dir.rglob("Domain_*.md")))
    total_orphans = len(report.get("orphans", []))

    broken_body = report.get("broken_body_links", [])
    prospective_seeds = report.get("prospective_related_seeds", [])

    if not broken_body and not prospective_seeds and report.get("broken_links"):
        for b in report["broken_links"]:
            if b.get("origin") == "body":
                broken_body.append(b)
            else:
                prospective_seeds.append(b)

    # Classify broken body links
    chapter_refs = []
    concept_body_refs = []
    for entry in broken_body:
        to_link = entry["to"]
        if re.search(r"(chuong|chương|\d+_ch\d+|p\d+_ch\d+)", to_link, re.IGNORECASE):
            chapter_refs.append(entry)
        else:
            concept_body_refs.append(entry)

    # Group concept references for display
    concept_counts: dict[str, list[str]] = defaultdict(list)
    for entry in concept_body_refs:
        concept_counts[entry["to"]].append(entry["from"])

    sorted_body_concepts = sorted(concept_counts.items(), key=lambda item: len(item[1]), reverse=True)

    # Group prospective seeds for top display
    seed_counts: dict[str, list[str]] = defaultdict(list)
    for entry in prospective_seeds:
        seed_counts[entry["to"]].append(entry["from"])
    sorted_seeds = sorted(seed_counts.items(), key=lambda item: len(item[1]), reverse=True)

    # Assemble lines
    lines = [
        "---\n",
        f'title: "🌙 Weekly Synthesis — {today_str}"\n',
        "tags: [meta/synthesis, meta/lint]\n",
        "type: topic\n",
        f"date_created: {today_str}\n",
        f"date_modified: {today_str}\n",
        'summary: "Báo cáo tổng hợp đóng phiên và củng cố tri thức tự động."\n',
        "---\n\n",
        f"# 🌙 Weekly Synthesis — {today_str}\n\n",
        "> [!abstract] **📊 Chỉ Số Sức Khỏe Vault & Hoạt Động Tuần**\n",
        f"> - 🧠 **Tổng Khái Niệm (Concepts):** `{total_concepts}` | 📖 **Tổng Nguồn (Sources):** `{total_sources}`\n",
        f"> - 📚 **Source MOCs:** `{total_source_mocs}` | 🏷️ **Domain MOCs:** `{total_domain_mocs}`\n",
        f"> - ⚡ **Mới trong tuần:** `{len(recent)}` concepts | 🔀 **Merges:** `{merges}` | 🗑️ **Subsumes:** `{subsumes}`\n",
        f"> - 🔗 **True Orphans:** `{total_orphans}` | 💔 **Broken Citations in Body:** `{len(concept_body_refs)}`\n",
        f"> - 🩹 **Đã tự động vá:** `{healed_links}` stubs | ✏️ **Sửa chính tả:** `{healed_typos}`\n\n",
        "---\n\n",
        "## 🔍 Sức Khỏe Liên Kết (Link Integrity)\n\n",
    ]

    # Orphans section (Graph-safe: backtick instead of [[...]])
    if not report.get("orphans"):
        lines.append("### 🔗 Ghi Chú Mồ Côi (Orphans)\n\n")
        lines.append("_Không phát hiện ghi chú mồ côi nào trong Vault._ ✅\n\n")
    else:
        lines.append(f"### 🔗 Ghi Chú Mồ Côi Thực Tế ({total_orphans})\n\n")
        lines.append("Các khái niệm chưa có liên kết từ MOCs, Sources hoặc bài viết khác:\n\n")

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
            lines.append(f"- **Nguồn `{src}`:** " + ", ".join(f"`{stem}`" for stem in stems) + "\n")
        lines.append("\n")

    # Broken Citations in Body section
    lines.append(f"### 💔 Trích Dẫn Gãy trong Bài Viết ({len(concept_body_refs)})\n\n")
    if not concept_body_refs:
        lines.append("_Nội dung các bài viết không có trích dẫn nào bị hỏng._ ✅\n\n")
    else:
        lines.append("Các liên kết cần rà soát và bổ sung alias hoặc sửa cú pháp trích dẫn:\n\n")
        lines.append("| Trạng thái | Liên kết cần kiểm tra | Xuất hiện tại | Số lần |\n")
        lines.append("|:---:|---|---|:---:|\n")
        for target, src_list in sorted_body_concepts[:15]:
            ref_by = ", ".join(f"[[{s}]]" for s in src_list[:3])
            if len(src_list) > 3:
                ref_by += f" *(+{len(src_list) - 3})*"
            lines.append(f"| ❌ | `{target}` | {ref_by} | {len(src_list)} |\n")
        lines.append("\n")

    # Prospective seeds in frontmatter callout
    if sorted_seeds:
        lines.append(f"### 🧠 Khái Niệm Hạt Giống trong Frontmatter ({len(sorted_seeds)})\n\n")
        lines.append(
            f"> [!tip]- 💡 Xem Top 15/{len(sorted_seeds)} Khái niệm Hạt giống Tiềm năng (Gợi mở tương lai)\n"
            "> Các liên kết này nằm trong trường YAML `related:` do AI đề xuất khi tổng hợp, không phải liên kết hỏng trong bài viết.\n"
            ">\n"
            "> | Hạt giống gợi mở | Được gợi ý bởi | Số lần |\n"
            "> |---|---|:---:|\n"
        )
        for seed, src_list in sorted_seeds[:15]:
            ref_by = ", ".join(f"[[{s}]]" for s in src_list[:2])
            if len(src_list) > 2:
                ref_by += f" *(+{len(src_list) - 2})*"
            lines.append(f"> | `{seed}` | {ref_by} | {len(src_list)} |\n")
        lines.append("\n")

    # Healing results
    if healed_links > 0:
        lines.append(f"> [!success] **Wiki Healer:** Đã tự động tạo thành công **{healed_links}** ghi chú stub cho các liên kết hợp lệ.\n\n")

    # Knowledge Gaps & Advice
    if academic_advice and academic_advice.strip():
        lines.append(academic_advice.strip() + "\n\n")

    # Check for domain suggestions from sleep
    suggestion_file = cfg.state_dir / ".domain_suggestions.json"
    if suggestion_file.exists():
        try:
            suggestions = json.loads(suggestion_file.read_text(encoding="utf-8"))
            if suggestions:
                lines.append("## 💡 Đề Xuất Mở Rộng Lĩnh Vực (Domain Suggestions)\n\n")
                for s in suggestions:
                    stem = s.get("concept_stem")
                    title = s.get("concept_title", stem)
                    domain = s.get("suggested_domain")
                    summary = s.get("summary", "")
                    summary_part = f" — *{summary}*" if summary else ""
                    lines.append(f"- **domain/{domain}**: Gợi ý từ [[{stem}|{title}]]{summary_part}\n")
                lines.append("\n")
                suggestion_file.unlink(missing_ok=True)
        except Exception:
            pass

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
                lines.append("## 🔄 SUBSUME Review (Concepts trùng lặp đã được gộp)\n\n")
                lines.append(
                    "> Các concept dưới đây đã bị Arbitrator đánh giá là **tập con hoàn toàn** của concept hiện có. "
                    "Chúng không được tạo mới để giữ Zettelkasten tinh gọn.\n\n"
                )
                lines.append("| Ngày | Concept mới (bị bỏ) | Đã có trong | Score |\n")
                lines.append("|:---:|---|---|:---:|\n")
                for e in entries:
                    ts = e.get("timestamp", "")[:10]
                    new_title = e.get("new_title", "?")
                    existing = e.get("existing_concept", "?").replace(".md", "")
                    score = e.get("similarity_score", 0)
                    lines.append(f"| {ts} | `{new_title}` | [[{existing}]] | {score:.3f} |\n")
                lines.append("\n")
                subsume_journal.unlink(missing_ok=True)
        except Exception:
            pass

    # Read and append stale stubs warning if any
    stale_file = cfg.state_dir / ".stale_stubs.json"
    if stale_file.exists():
        try:
            stale_entries = json.loads(stale_file.read_text(encoding="utf-8"))
            if stale_entries:
                total_stale = len(stale_entries)
                sorted_stale = sorted(
                    stale_entries,
                    key=lambda x: x.get("age_days", 0) if isinstance(x.get("age_days"), (int, float)) else 0,
                    reverse=True,
                )
                top_stale = sorted_stale[:15]
                lines.append(f"## ⚠️ Ghi Chú Stub Quá Hạn ({total_stale})\n\n")
                lines.append(
                    f"> [!warning]- ⚠️ Xem Top {len(top_stale)}/{total_stale} Ghi Chú Stub Quá Hạn (>30 ngày chưa mở rộng)\n"
                    "> Các ghi chú stub dưới đây cần được ưu tiên bồi đắp tri thức hoặc dọn dẹp:\n"
                    ">\n"
                    "> | Tên Stub | Ngày tạo | Tuổi (ngày) | Liên kết từ |\n"
                    "> |---|---|---|---|\n"
                )
                for s in top_stale:
                    stem = s.get("stem", "?")
                    created = s.get("created", "?")
                    age = s.get("age_days", "?")
                    referrers = ", ".join(f"[[{r}]]" for r in s.get("referrers", [])[:2])
                    lines.append(f"> | `{stem}` | {created} | {age} | {referrers} |\n")
                lines.append("\n")
        except Exception:
            pass

    report_path.write_text("".join(lines), encoding="utf-8")
    return report_path
