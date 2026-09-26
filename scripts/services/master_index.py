"""VvC Second Brain — Master Index Dashboard Compiler.

Builds the Master Index (00 - Maps of Content/index.md) featuring:
- Knowledge intelligence metrics and KPI banner
- Flagship Playbooks showcase (AI-EOS, Construction Legal 2026)
- Categorized Source MOCs (Books, Media, Articles)
- Grand Domains taxonomy distribution
- Top 30 recent concept timeline
- Dynamic Dataview dashboards (Real-time, Growing, Validation, Entities)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from core.config import cfg
from core.taxonomy import GRAND_DOMAINS

_logger = logging.getLogger("vvc.maintain.master_index")


def _get_recent_concepts(concepts: list[dict], limit: int = 30) -> list[dict]:
    """Retrieve top N recently modified or created concepts."""
    def _sort_key(c: dict) -> tuple[str, float]:
        d = c.get("date_created")
        d_str = d.isoformat() if isinstance(d, date) else (str(d) if d else "1970-01-01")
        mtime = c.get("_mtime")
        if mtime is None:
            path = c.get("_path")
            mtime = path.stat().st_mtime if path and path.exists() else 0
        return (d_str, mtime)

    return sorted(concepts, key=_sort_key, reverse=True)[:limit]


def _classify_source_mocs(
    source_mocs: list[Path],
    sources: list[dict],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """Classify source MOCs into Books, Media, and Articles."""
    from services.moc_builder import get_source_moc_display_name, normalize_moc_name

    moc_to_source = {}
    for src in sources:
        display_name = get_source_moc_display_name(src)
        moc_stem = f"MOC_{normalize_moc_name(display_name)}"
        moc_to_source[moc_stem] = src

    books_mocs: list[tuple[str, str]] = []
    media_mocs: list[tuple[str, str]] = []
    articles_mocs: list[tuple[str, str]] = []

    for moc in source_mocs:
        stem = moc.stem
        src = moc_to_source.get(stem)
        name = stem.replace("MOC_", "").replace("_", " ")
        name = re.sub(r"^\d{4}\s\d{2}\s\d{2}\s(?:\d{6}\s)?", "", name)
        name = re.sub(r"\sSource$", "", name)

        if not src:
            articles_mocs.append((stem, name))
            continue

        source_type = str(src.get("source_type", "")).lower()
        title_lower = str(src.get("title", "")).lower()
        stem_lower = str(src.get("_stem", "")).lower()

        if source_type in ("pdf", "epub", "azw3", "mobi", "chm", "epub3", "azw"):
            books_mocs.append((stem, name))
        elif source_type in ("audio", "video") or any(
            k in title_lower or k in stem_lower
            for k in ["youtube", "podcast", "video", "interview", "talk", "talks", "ss4_", "wired", "wired_interview"]
        ):
            media_mocs.append((stem, name))
        else:
            articles_mocs.append((stem, name))

    return books_mocs, media_mocs, articles_mocs


def _classify_domain_mocs(domain_mocs: list[Path]) -> dict[str, list[tuple[str, str]]]:
    """Classify Domain MOCs into Grand Domain highways and other."""
    domain_groups: dict[str, list[tuple[str, str]]] = {k: [] for k in GRAND_DOMAINS}
    domain_groups["other"] = []

    for moc in domain_mocs:
        name = moc.stem.replace("Domain_", "").replace("_", " ")
        domain_key = moc.stem.replace("Domain_", "").lower()
        matched = False
        padded_domain = f"_{domain_key}_"
        for category, info in GRAND_DOMAINS.items():
            if any(f"_{kw}_" in padded_domain or domain_key == kw for kw in info["keywords"]):
                domain_groups[category].append((moc.stem, name))
                matched = True
                break
        if not matched:
            domain_groups["other"].append((moc.stem, name))

    return domain_groups


def _render_header_and_playbooks(
    total_concepts: int, total_sources: int, num_source_mocs: int, num_domain_mocs: int
) -> list[str]:
    """Render top master index banner, stats, and flagship playbooks showcase."""
    return [
        "# 📚 VvC Second Brain — Master Index\n\n",
        "> [!abstract] **📊 Chỉ Số Thứ Tự Tri Thức (Knowledge Intelligence)**\n",
        f"> - 🧠 **{total_concepts}** khái niệm cốt lõi (Concepts)\n",
        f"> - 📖 **{total_sources}** nguồn tri thức (Sources)\n",
        f"> - 🗺️ **{num_source_mocs}** Bản đồ Nguồn (Source MOCs)\n",
        f"> - 🏷️ **{num_domain_mocs}** Bản đồ Lĩnh vực (Domain MOCs)\n\n",
        f"*Last updated: {date.today().isoformat()}*\n\n",
        "---\n\n",
        "> [!quote]+ 🌟 Kiệt Tác Chuyên Luận (Flagship Playbooks)\n",
        "> - 📘 **Bản Điều Phối Kiến Trúc 12 Chương**: [[ai_eos_playbook_master|AI-EOS Playbook Master — Cẩm Nang Vận Hành Doanh Nghiệp AI-Native]]\n",
        "> - 📑 **Toàn Văn Bản Thảo Hợp Nhất (Full Manuscript)**: [[ai_eos_playbook_full_manuscript|Toàn Văn Bản Thảo AI-EOS Playbook]]\n",
        "> - 🏛️ **Khung Pháp Lý & Tiêu Chuẩn 2026**: [[tong_quan_khung_phap_ly_xay_dung_2026|Tổng Quan Khung Pháp Lý Quản Lý Chất Lượng & Số Hóa Xây Dựng 2026]]\n\n",
        "---\n\n",
    ]


def _render_source_mocs_section(
    books_mocs: list[tuple[str, str]],
    media_mocs: list[tuple[str, str]],
    articles_mocs: list[tuple[str, str]],
) -> list[str]:
    """Render Books, Media, and Articles source topic callouts."""
    lines = ["## 📖 Source Topics (Bản Đồ Nguồn)\n\n"]
    configs = [
        ("book", "📚 1. Sách & Ấn Bản Hệ Thống (Books & Literature)", "Các bản đồ tri thức tổng hợp từ sách giấy, EPUB, PDF có tính hệ thống cao.", books_mocs, "+"),
        ("video", "🎥 2. Bài Giảng, Video & Podcasts (Media & Audio)", "Tri thức đúc kết từ các tập podcast, bài nói chuyện, video YouTube chất lượng cao.", media_mocs, "-"),
        ("note", "📰 3. Bài Báo, Nghiên Cứu & Web Clips (Articles & Web)", "Các bài viết chuyên sâu từ internet, tài liệu văn bản ngắn hoặc stubs tổng hợp.", articles_mocs, "+"),
    ]
    for c_type, title, desc, items, state in configs:
        lines.append(f"> [!{c_type}]{state} {title} [{len(items)}]\n")
        lines.append(f"> {desc}\n>\n")
        if items:
            for stem, name in items:
                lines.append(f"> - [[{stem}|{name}]]\n")
        else:
            lines.append("> - *(Chưa có)*\n")
        lines.append("\n")
    return lines


def _render_domain_mocs_section(domain_groups: dict[str, list[tuple[str, str]]]) -> list[str]:
    """Render Grand Domain and Other Domain topic callouts."""
    lines = ["## 🏷️ Domain Topics (Bản Đồ Lĩnh Vực)\n\n"]
    for category, info in GRAND_DOMAINS.items():
        mocs = domain_groups.get(category, [])
        if not mocs:
            continue
        lines.append(f"> [!info]+ {info['title']} [{len(mocs)}]\n")
        for stem, name in sorted(mocs, key=lambda x: x[1]):
            lines.append(f"> - [[{stem}|{name}]]\n")
        lines.append("\n")

    if domain_groups.get("other"):
        lines.append(f"> [!quote]- 📁 Lĩnh Vực Khác (Other Domains) [{len(domain_groups['other'])}]\n")
        for stem, name in sorted(domain_groups["other"], key=lambda x: x[1]):
            lines.append(f"> - [[{stem}|{name}]]\n")
        lines.append("\n")
    return lines


def _render_recent_and_dataview(recent: list[dict]) -> list[str]:
    """Render recent concept notes and dynamic Dataview dashboards."""
    lines = [
        "## 🆕 Concept Gần Đây Nhất\n\n",
        "> [!note]- 🆕 Top 30 Concept Mới Cập Nhật\n",
    ]
    for c in recent:
        title = c.get("title", c["_stem"])
        created = c.get("date_created", "")
        lines.append(f"> - [{created}] [[{c['_stem']}|{title}]]\n")
    lines.append("\n")

    lines.extend([
        "---\n\n",
        "## 📊 Bảng Điều Khiển & Thống Kê Động (Dataview)\n\n",
        "> [!TIP]\n",
        "> Các bảng dưới đây được render động thời gian thực bằng plugin **Dataview**. Chúng giúp anh quản lý chất lượng và vòng đời tri thức trong hệ thống một cách trực quan.\n\n",
        "> [!todo]- 🕒 30 Concepts Cập Nhật Gần Nhất (Real-time)\n",
        "> ```dataview\n",
        "> TABLE date_created AS \"Ngày Tạo\", status AS \"Trạng Thái\", confidence AS \"Độ Tin Cậy\"\n",
        "> FROM \"04 - Permanent/concepts\"\n",
        "> SORT file.mtime DESC\n",
        "> LIMIT 30\n",
        "> ```\n\n",
        "> [!seed]- 🌱 Ghi Chú Đang Phát Triển (Seed / Growing)\n",
        "> ```dataview\n",
        "> TABLE status AS \"Trạng Thái\", source AS \"Nguồn\"\n",
        "> FROM \"04 - Permanent/concepts\"\n",
        "> WHERE status = \"seed\" OR status = \"growing\"\n",
        "> SORT file.mtime DESC\n",
        "> LIMIT 10\n",
        "> ```\n\n",
        "> [!check]- 🔍 Khái Niệm Cần Kiểm Chứng (Confidence: Low / Medium)\n",
        "> ```dataview\n",
        "> TABLE confidence AS \"Độ Tin Cậy\", source AS \"Nguồn\"\n",
        "> FROM \"04 - Permanent/concepts\"\n",
        "> WHERE confidence = \"low\" OR confidence = \"medium\"\n",
        "> SORT file.mtime DESC\n",
        "> LIMIT 10\n",
        "> ```\n\n",
        "> [!people]- 👥 Nhân Vật & Tổ Chức Gần Đây\n",
        "> ```dataview\n",
        "> TABLE people AS \"Nhân Vật\", companies AS \"Tổ Chức\"\n",
        "> FROM \"04 - Permanent/concepts\"\n",
        "> WHERE length(people) > 0 OR length(companies) > 0\n",
        "> SORT file.mtime DESC\n",
        "> LIMIT 10\n",
        "> ```\n",
    ])
    return lines


def build_master_index(
    concepts: list[dict],
    sources: list[dict],
    write_fn: Callable[[Path, str], bool],
    moc_dir: Path | None = None,
    index_file: Path | None = None,
) -> None:
    """Build the Master Index (index.md) with a premium, organized visual dashboard."""
    target_moc_dir = moc_dir or cfg.moc_dir
    target_index_file = index_file or cfg.index_file

    source_mocs = sorted(target_moc_dir.rglob("MOC_*.md"))
    domain_mocs = sorted(target_moc_dir.rglob("Domain_*.md"))
    recent = _get_recent_concepts(concepts, limit=30)

    books_mocs, media_mocs, articles_mocs = _classify_source_mocs(source_mocs, sources)
    domain_groups = _classify_domain_mocs(domain_mocs)

    lines: list[str] = []
    lines.extend(_render_header_and_playbooks(len(concepts), len(sources), len(source_mocs), len(domain_mocs)))
    lines.extend(_render_source_mocs_section(books_mocs, media_mocs, articles_mocs))
    lines.extend(_render_domain_mocs_section(domain_groups))
    lines.extend(_render_recent_and_dataview(recent))

    write_fn(target_index_file, "".join(lines))
    _logger.info("Master Index rebuilt")
