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


def _render_bridge_candidates(candidates: list[dict]) -> list[str]:
    """Render the Bridge Candidates table for cross-domain synthesis.

    Enforces visual ergonomics: table pipe escaping [[stem\\|title]] and zero code-pills.
    """
    if not candidates:
        return []
    lines = [
        f"## 🌉 Cầu Nối Tri Thức Liên Miền (Bridge Candidates) [{len(candidates)}]\n\n",
        "> [!tip]+ Top Khái Niệm Cầu Nối Tri Thức (Cross-Domain Bridges)\n",
        "> Các khái niệm có độ đa dạng kết nối cao giữa các đại lĩnh vực, thích hợp để tổng hợp chéo chủ đề.\n>\n",
        "| Điểm Cầu Nối | Khái Niệm | Lĩnh Vực Gốc | Kết Nối Đến | Bậc |\n",
        "|:---:|---|---|---|:---:|\n",
    ]
    for c in candidates:
        score = f"{c.get('bridge_score', 0.0):.3f}"
        stem = c.get("stem", "")
        raw_title = str(c.get("title") or stem)
        clean_title = raw_title.replace(r"\|", "|").replace("|", r"\|")
        domains = ", ".join(c.get("domains", [])) or "*(chưa gắn)*"
        connected = ", ".join(c.get("connected_domains", [])) or "*(không có)*"
        deg = c.get("degree", 0)
        lines.append(f"| `{score}` | [[{stem}\\|{clean_title}]] | {domains} | {connected} | {deg} |\n")
    lines.append("\n")
    return lines


def _parse_weekly_log_events(week_ago: str) -> dict[str, int]:
    """Extract weekly event counters from vault log.md."""
    events = {"merges": 0, "quality": 0, "subsumes": 0, "dumps": 0}
    if not cfg.log_file.exists():
        return events
    try:
        for line in cfg.log_file.read_text(encoding="utf-8").splitlines():
            if len(line) >= 13 and line[3:13] < week_ago:
                continue
            if "**merge**" in line:
                events["merges"] += 1
            elif "**quality**" in line:
                events["quality"] += 1
            elif "**subsume**" in line:
                events["subsumes"] += 1
            elif "**dump**" in line and "detected" in line:
                events["dumps"] += 1
    except Exception:
        pass
    return events


def _extract_broken_link_counts(
    report: LintReport,
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]], int]:
    """Classify and group broken links and prospective seeds."""
    broken_body = list(report.get("broken_body_links", []))
    prospective_seeds = list(report.get("prospective_related_seeds", []))
    if not broken_body and not prospective_seeds and report.get("broken_links"):
        for b in report["broken_links"]:
            (broken_body if b.get("origin") == "body" else prospective_seeds).append(b)

    concept_body = [
        e for e in broken_body
        if not re.search(r"(chuong|chương|\d+_ch\d+|p\d+_ch\d+)", e.get("to", ""), re.IGNORECASE)
    ]

    def _group(entries: list[dict]) -> list[tuple[str, list[str]]]:
        counts: dict[str, list[str]] = defaultdict(list)
        for e in entries:
            counts[e["to"]].append(e["from"])
        return sorted(counts.items(), key=lambda item: len(item[1]), reverse=True)

    return _group(concept_body), _group(prospective_seeds), len(concept_body)


def _render_header_kpis(
    today_str: str,
    concepts: list[dict],
    sources: list[dict],
    recent_count: int,
    events: dict[str, int],
    total_orphans: int,
    broken_body_count: int,
    healed_links: int,
    healed_typos: int,
) -> list[str]:
    """Render markdown frontmatter and summary KPI abstract callout."""
    total_src_mocs = len(list(cfg.moc_dir.rglob("MOC_*.md")))
    total_dom_mocs = len(list(cfg.moc_dir.rglob("Domain_*.md")))
    return [
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
        f"> - 🧠 **Tổng Khái Niệm (Concepts):** `{len(concepts)}` | 📖 **Tổng Nguồn (Sources):** `{len(sources)}`\n",
        f"> - 📚 **Source MOCs:** `{total_src_mocs}` | 🏷️ **Domain MOCs:** `{total_dom_mocs}`\n",
        f"> - ⚡ **Mới trong tuần:** `{recent_count}` concepts | 🔀 **Merges:** `{events['merges']}` | 🗑️ **Subsumes:** `{events['subsumes']}`\n",
        f"> - 🔗 **True Orphans:** `{total_orphans}` | 💔 **Broken Citations in Body:** `{broken_body_count}`\n",
        f"> - 🩹 **Đã tự động vá:** `{healed_links}` stubs | ✏️ **Sửa chính tả:** `{healed_typos}`\n\n",
        "---\n\n",
        "## 🔍 Sức Khỏe Liên Kết (Link Integrity)\n\n",
    ]


def _render_orphans(orphans: list[str], concepts: list[dict]) -> list[str]:
    """Render graph-safe orphan notes section."""
    if not orphans:
        return ["### 🔗 Ghi Chú Mồ Côi (Orphans)\n\n_Không phát hiện ghi chú mồ côi nào trong Vault._ ✅\n\n"]
    lines = [
        f"### 🔗 Ghi Chú Mồ Côi Thực Tế ({len(orphans)})\n\n",
        "Các khái niệm chưa có liên kết từ MOCs, Sources hoặc bài viết khác:\n\n",
    ]
    by_source: dict[str, list[str]] = defaultdict(list)
    concept_map = {c.get("_stem"): c for c in concepts if "_stem" in c}
    for stem in orphans:
        c = concept_map.get(stem, {})
        src_val = c.get("source") or c.get("sources", "unknown")
        if isinstance(src_val, list):
            src_val = src_val[0] if src_val else "unknown"
        if isinstance(src_val, dict):
            src = src_val.get("title") or src_val.get("name") or "unknown"
        else:
            src = str(src_val) if src_val else "unknown"
        if src.endswith(".md"):
            src = src[:-3]
        by_source[src].append(stem)
    for src, stems in sorted(by_source.items()):
        lines.append(f"- **Nguồn `{src}`:** " + ", ".join(f"`{st}`" for st in stems) + "\n")
    lines.append("\n")
    return lines


def _render_broken_tables(
    body_concepts: list[tuple[str, list[str]]],
    seeds: list[tuple[str, list[str]]],
    broken_body_count: int,
) -> list[str]:
    """Render broken citations table and prospective seed callout."""
    lines = [f"### 💔 Trích Dẫn Gãy trong Bài Viết ({broken_body_count})\n\n"]
    if not body_concepts:
        lines.append("_Nội dung các bài viết không có trích dẫn nào bị hỏng._ ✅\n\n")
    else:
        lines.extend([
            "Các liên kết cần rà soát và bổ sung alias hoặc sửa cú pháp trích dẫn:\n\n",
            "| Trạng thái | Liên kết cần kiểm tra | Xuất hiện tại | Số lần |\n|:---:|---|---|:---:|\n",
        ])
        for target, src_list in body_concepts[:15]:
            ref_by = ", ".join(f"[[{s}]]" for s in src_list[:3])
            if len(src_list) > 3:
                ref_by += f" *(+{len(src_list) - 3})*"
            lines.append(f"| ❌ | `{target}` | {ref_by} | {len(src_list)} |\n")
        lines.append("\n")

    if seeds:
        lines.append(
            f"### 🧠 Khái Niệm Hạt Giống trong Frontmatter ({len(seeds)})\n\n"
            f"> [!tip]- 💡 Xem Top 15/{len(seeds)} Khái niệm Hạt giống Tiềm năng (Gợi mở tương lai)\n"
            "> Các liên kết này nằm trong trường YAML `related:` do AI đề xuất khi tổng hợp, không phải liên kết hỏng trong bài viết.\n>\n"
            "> | Hạt giống gợi mở | Được gợi ý bởi | Số lần |\n> |---|---|:---:|\n"
        )
        for seed, src_list in seeds[:15]:
            ref_by = ", ".join(f"[[{s}]]" for s in src_list[:2])
            if len(src_list) > 2:
                ref_by += f" *(+{len(src_list) - 2})*"
            lines.append(f"> | `{seed}` | {ref_by} | {len(src_list)} |\n")
        lines.append("\n")
    return lines


def _render_subsume_journal() -> list[str]:
    """Read and format SUBSUME review table from state journal."""
    sub_file = cfg.state_dir / ".subsume_journal.jsonl"
    if not sub_file.exists():
        return []
    try:
        entries = [json.loads(line) for line in sub_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not entries:
            return []
        lines = [
            "## 🔄 SUBSUME Review (Concepts trùng lặp đã được gộp)\n\n",
            "> Các concept dưới đây đã bị Arbitrator đánh giá là **tập con hoàn toàn** của concept hiện có. "
            "Chúng không được tạo mới để giữ Zettelkasten tinh gọn.\n\n",
            "| Ngày | Concept mới (bị bỏ) | Đã có trong | Score |\n|:---:|---|---|:---:|\n",
        ]
        for e in entries:
            target = str(e.get("existing_concept", "?")).replace(".md", "")
            lines.append(
                f"| {e.get('timestamp', '')[:10]} | `{e.get('new_title', '?')}` | "
                f"[[{target}]] | {e.get('similarity_score', 0):.3f} |\n"
            )
        lines.append("\n")
        sub_file.unlink(missing_ok=True)
        return lines
    except Exception:
        return []


def _render_state_sections() -> list[str]:
    """Read and format state persistence files: suggestions, subsumes, stubs."""
    lines: list[str] = []
    sug_file = cfg.state_dir / ".domain_suggestions.json"
    if sug_file.exists():
        try:
            sugs = json.loads(sug_file.read_text(encoding="utf-8"))
            if sugs:
                lines.append("## 💡 Đề Xuất Mở Rộng Lĩnh Vực (Domain Suggestions)\n\n")
                for s in sugs:
                    stem, title, domain = s.get("concept_stem"), s.get("concept_title") or s.get("concept_stem"), s.get("suggested_domain")
                    summary = f" — *{s['summary']}*" if s.get("summary") else ""
                    lines.append(f"- **domain/{domain}**: Gợi ý từ [[{stem}|{title}]]{summary}\n")
                lines.append("\n")
                sug_file.unlink(missing_ok=True)
        except Exception:
            pass

    lines.extend(_render_subsume_journal())

    stale_file = cfg.state_dir / ".stale_stubs.json"
    if stale_file.exists():
        try:
            stales = json.loads(stale_file.read_text(encoding="utf-8"))
            if stales:
                top = sorted(stales, key=lambda x: x.get("age_days", 0) if isinstance(x.get("age_days"), (int, float)) else 0, reverse=True)[:15]
                lines.extend([
                    f"## ⚠️ Ghi Chú Stub Quá Hạn ({len(stales)})\n\n",
                    f"> [!warning]- ⚠️ Xem Top {len(top)}/{len(stales)} Ghi Chú Stub Quá Hạn (>30 ngày chưa mở rộng)\n",
                    "> Các ghi chú stub dưới đây cần được ưu tiên bồi đắp tri thức hoặc dọn dẹp:\n>\n",
                    "> | Tên Stub | Ngày tạo | Tuổi (ngày) | Liên kết từ |\n> |---|---|---|---|\n",
                ])
                for s in top:
                    ref = ", ".join(f"[[{r}]]" for r in s.get("referrers", [])[:2])
                    lines.append(f"> | `{s.get('stem', '?')}` | {s.get('created', '?')} | {s.get('age_days', '?')} | {ref} |\n")
                lines.append("\n")
        except Exception:
            pass
    return lines


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

    concepts = scan_all_concepts() if concepts is None else concepts
    sources = scan_all_sources() if sources is None else sources
    if report is None:
        from services.wiki_health import lint_vault
        report = lint_vault()

    recent_count = sum(
        1 for fm in concepts
        if str(fm.get("date_created", "") if not isinstance(fm.get("date_created"), (date, datetime)) else fm["date_created"].isoformat()) >= week_ago
    )
    events = _parse_weekly_log_events(week_ago)
    body_concepts, seeds, broken_body_count = _extract_broken_link_counts(report)

    lines = _render_header_kpis(
        today_str, concepts, sources, recent_count, events,
        len(report.get("orphans", [])), broken_body_count, healed_links, healed_typos,
    )
    lines.extend(_render_orphans(report.get("orphans", []), concepts))
    lines.extend(_render_broken_tables(body_concepts, seeds, broken_body_count))

    if healed_links > 0:
        lines.append(f"> [!success] **Wiki Healer:** Đã tự động tạo thành công **{healed_links}** ghi chú stub cho các liên kết hợp lệ.\n\n")
    if academic_advice and academic_advice.strip():
        lines.append(academic_advice.strip() + "\n\n")

    lines.extend(_render_bridge_candidates(report.get("bridge_candidates", [])))
    lines.extend(_render_state_sections())

    report_path = cfg.moc_dir / "Weekly_Synthesis.md"
    report_path.write_text("".join(lines), encoding="utf-8")
    return report_path
