"""VvC Second Brain — Wiki Maintainer (v7.0).

Builds and maintains MOC pages, Domain MOCs, and the Master Index.

Usage:
    python wiki_maintain.py          # Manual full rebuild
    from wiki_maintain import rebuild_all, rebuild_incremental
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from core.config import cfg
from core.file_lock import CrossProcessFileLock
from core.frontmatter import normalize_stem
from core.log import log
from core.taxonomy import (
    DOMAIN_ALIASES,
    GRAND_DOMAINS,
    normalize_domain_tag,
    resolve_grand_domains,
)
from core.vault import scan_all_concepts, scan_all_sources
from services.moc_mermaid import (
    build_mermaid_overview as _build_mermaid_overview,
    clean_chapter_name,
    flatten_source_list,
    format_concept_line as _format_concept_line,
    generate_mermaid_flowchart as _generate_mermaid_flowchart,
    group_by_chapter,
)

_logger = logging.getLogger("vvc.maintain")

DOMAIN_MOC_THRESHOLD = 15  # Min concepts to create a Domain MOC
_normalize_domain_tag = normalize_domain_tag


def _safe_write_text(path: Path, content: str) -> bool:
    """Write content to file only if it has changed, preventing sync storms.

    Returns:
        True if the file was written, False if content was identical.
    """
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _normalize_moc_name(name: str) -> str:
    """Normalize a display name into a clean, accent-free Title_Cased MOC name."""
    # Replace đ/Đ manually since NFKD does not decompose them
    name = name.replace("đ", "d").replace("Đ", "D")
    # Decompose unicode to separate base characters and accents, then strip accents
    normalized = unicodedata.normalize("NFKD", name)
    name = normalized.encode("ascii", "ignore").decode("ascii")
    # Replace non-alphanumeric with underscores
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    # Capitalize each word for proper Title_Casing
    return "_".join(w.capitalize() for w in name.split("_") if w)


def _get_source_aliases(src: dict) -> list[str]:
    """Extract and normalize all aliases from a source dictionary."""
    raw = src.get("aliases", [])
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, str)]
    return []


def _get_source_moc_display_name(src: dict) -> str:
    """Get canonical display name for Source MOC, filtering test prefixes."""
    src_stem = src.get("_stem", "")
    aliases = _get_source_aliases(src)
    valid_aliases = [a for a in aliases if not a.lower().startswith("test_")]
    return valid_aliases[0] if valid_aliases else (aliases[0] if aliases else src.get("title", src_stem))


def _render_source_moc_content(src: dict, linked_concepts: list[dict]) -> tuple[Path, str]:
    """Render Markdown content for a single Source MOC."""
    src_stem = src["_stem"]
    display_name = _get_source_moc_display_name(src)
    moc_name = _normalize_moc_name(display_name)
    moc_path = cfg.moc_dir / "sources" / f"MOC_{moc_name}.md"

    chapters = group_by_chapter(linked_concepts)
    has_chapters = any(k != "_ungrouped" for k in chapters)

    lines = [
        f"# 🗺️ {display_name}\n\n",
        f"> [!abstract] **📌 Thông Tin Bản Đồ Nguồn**\n",
        f"> - 📖 **Nguồn gốc:** [[{src_stem}]]\n",
        f"> - 🧠 **Quy mô:** **{len(linked_concepts)}** khái niệm cốt lõi (Concepts)\n\n",
    ]

    # Generate Mermaid overview diagram wrapped in an Obsidian collapsible callout
    mermaid = _build_mermaid_overview(chapters, linked_concepts, display_name)
    if mermaid:
        lines.append("> [!visual]- 🗺️ Sơ đồ Tổng Quan (Overview Map)\n")
        lines.append("> ```mermaid\n")
        for mline in mermaid.strip().splitlines():
            lines.append(f"> {mline}\n")
        lines.append("> ```\n\n")

    lines.append("---\n\n")

    if has_chapters:
        for ch_key in chapters:
            ch_concepts = chapters[ch_key]
            if ch_key == "_ungrouped":
                if len(ch_concepts) < 1:
                    continue
                lines.append("## 📦 Khái Niệm Chưa Phân Loại\n\n")
            else:
                ch_display = clean_chapter_name(ch_key)
                lines.append(f"## 📖 {ch_display}\n\n")

            for c in sorted(ch_concepts, key=lambda x: x.get("title", "")):
                lines.append(_format_concept_line(c))
            lines.append("\n")
    else:
        lines.append("## Concepts\n\n")
        for c in sorted(linked_concepts, key=lambda x: x.get("title", "")):
            lines.append(_format_concept_line(c))
        lines.append("\n")

    return moc_path, "".join(lines)


def _render_domain_moc_content(
    domain: str, 
    domain_concepts: list[dict],
    known_sources: set[str] | None = None,
) -> tuple[Path, str]:
    """Render Markdown content for a single Domain MOC."""
    display = domain.replace("_", " ").title()
    moc_name = _normalize_moc_name(display)
    moc_path = cfg.moc_dir / "domains" / f"Domain_{moc_name}.md"

    # Group by source
    by_source: dict[str, list[dict]] = defaultdict(list)
    for c in domain_concepts:
        src_val = c.get("source") or c.get("sources") or "unknown"
        srcs = flatten_source_list(src_val)
        for src in srcs:
            by_source[src].append(c)

    mermaid_graph = _generate_mermaid_flowchart(domain_concepts)

    lines = [
        f"# 🏷️ Domain: {display}\n\n",
        f"> [!abstract] **📌 Tổng Quan Lĩnh Vực**\n",
        f"> - 🧠 **Quy mô:** **{len(domain_concepts)}** khái niệm (Concepts)\n",
        f"> - 📖 **Phân bổ:** **{len(by_source)}** nguồn tri thức (Sources)\n\n",
    ]

    if mermaid_graph:
        lines.append(mermaid_graph)

    lines.extend([
        "---\n\n",
    ])

    for src, src_concepts in sorted(by_source.items()):
        norm_src = normalize_stem(src)
        if known_sources and norm_src in known_sources:
            lines.append(f"### From [[{src}]]\n\n")
        elif not known_sources and src not in ("web_imputed", "query_synthesis", "unknown", "LLM OS Pipeline v7.4", ""):
            lines.append(f"### From [[{src}]]\n\n")
        else:
            lines.append(f"### From {src}\n\n")

        for c in sorted(src_concepts, key=lambda x: x.get("title", "")):
            lines.append(_format_concept_line(c))
        lines.append("\n")

    return moc_path, "".join(lines)


# --- Source MOCs ---

def _build_source_mocs(concepts: list[dict], sources: list[dict]) -> list[Path]:
    """Build MOC_*.md for each source book with Mermaid concept map diagrams."""
    source_map: dict[str, list[dict]] = defaultdict(list)
    active_paths = []

    for c in concepts:
        src_val = c.get("source") or c.get("sources") or ""
        if src_val:
            srcs = flatten_source_list(src_val)
            for src in srcs:
                source_map[src].append(c)
                norm = normalize_stem(src)
                if norm != src:
                    source_map[norm].append(c)

    for src in sources:
        src_stem = src["_stem"]
        keys_to_check = {src_stem, normalize_stem(src_stem)}
        for a in _get_source_aliases(src):
            keys_to_check.add(a)
            keys_to_check.add(normalize_stem(a))

        seen_concepts: set[str] = set()
        linked_concepts: list[dict] = []
        for key in keys_to_check:
            for c in source_map.get(key, []):
                c_stem = c.get("_stem")
                if c_stem and c_stem not in seen_concepts:
                    seen_concepts.add(c_stem)
                    linked_concepts.append(c)

        if not linked_concepts:
            continue

        moc_path, content = _render_source_moc_content(src, linked_concepts)
        active_paths.append(moc_path.resolve())
        _safe_write_text(moc_path, content)

    return active_paths


# --- Domain MOCs ---

def _build_domain_mocs(concepts: list[dict], sources: list[dict] | None = None) -> list[Path]:
    """Build Domain_*.md for domains with enough concepts, formatting as visual dashboards."""
    domain_map: dict[str, list[dict]] = defaultdict(list)
    active_paths = []

    known_sources: set[str] = set()
    if sources:
        for s in sources:
            known_sources.add(normalize_stem(s.get("_stem", "")))
            for a in _get_source_aliases(s):
                known_sources.add(normalize_stem(a))

    for c in concepts:
        for tag in c.get("tags", []):
            if isinstance(tag, str) and tag.startswith("domain/"):
                raw_domain = _normalize_domain_tag(tag.split("/", 1)[1])
                domain = DOMAIN_ALIASES.get(raw_domain, raw_domain)
                domain_map[domain].append(c)

    for domain, domain_concepts in domain_map.items():
        if len(domain_concepts) < DOMAIN_MOC_THRESHOLD:
            continue

        moc_path, content = _render_domain_moc_content(domain, domain_concepts, known_sources=known_sources)
        active_paths.append(moc_path.resolve())
        _safe_write_text(moc_path, content)

    return active_paths


# --- Master Index ---

def _build_master_index(concepts: list[dict], sources: list[dict]) -> None:
    """Build the Master Index (index.md) with a premium, organized visual dashboard."""
    total_concepts = len(concepts)
    total_sources = len(sources)

    # Find MOC files (searching recursively across sub-folders)
    source_mocs = sorted(cfg.moc_dir.rglob("MOC_*.md"))
    domain_mocs = sorted(cfg.moc_dir.rglob("Domain_*.md"))

    # Recently added (last 30)
    def _get_sort_key(c):
        d = c.get("date_created")
        d_str = d.isoformat() if isinstance(d, date) else (str(d) if d else "1970-01-01")
        mtime = c.get("_mtime")
        if mtime is None:
            path = c.get("_path")
            mtime = path.stat().st_mtime if path and path.exists() else 0
        return (d_str, mtime)

    recent = sorted(concepts, key=_get_sort_key, reverse=True)[:30]

    # Classify Source MOCs
    moc_to_source = {}
    for src in sources:
        display_name = _get_source_moc_display_name(src)
        moc_name = _normalize_moc_name(display_name)
        moc_stem = f"MOC_{moc_name}"
        moc_to_source[moc_stem] = src

    books_mocs = []
    media_mocs = []
    articles_mocs = []

    for moc in source_mocs:
        stem = moc.stem
        src = moc_to_source.get(stem)
        name = stem.replace("MOC_", "").replace("_", " ")

        # Clean display name (strip date prefix and trailing "Source")
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
        elif (
            source_type in ("audio", "video")
            or any(
                k in title_lower or k in stem_lower
                for k in ["youtube", "podcast", "video", "interview", "talk", "talks", "ss4_", "wired", "wired_interview"]
            )
        ):
            media_mocs.append((stem, name))
        else:
            articles_mocs.append((stem, name))

    # Classify Domain MOCs into Grand Domains
    domain_groups = {k: [] for k in GRAND_DOMAINS}
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

    lines = [
        "# 📚 VvC Second Brain — Master Index\n\n",
        "> [!abstract] **📊 Chỉ Số Thứ Tự Tri Thức (Knowledge Intelligence)**\n",
        f"> - 🧠 **{total_concepts}** khái niệm cốt lõi (Concepts)\n",
        f"> - 📖 **{total_sources}** nguồn tri thức (Sources)\n",
        f"> - 🗺️ **{len(source_mocs)}** Bản đồ Nguồn (Source MOCs)\n",
        f"> - 🏷️ **{len(domain_mocs)}** Bản đồ Lĩnh vực (Domain MOCs)\n\n",
        f"*Last updated: {date.today().isoformat()}*\n\n",
        "---\n\n",
        "> [!quote]+ 🌟 Kiệt Tác Chuyên Luận (Flagship Playbooks)\n",
        "> - 📘 **Bản Điều Phối Kiến Trúc 12 Chương**: [[ai_eos_playbook_master|AI-EOS Playbook Master — Cẩm Nang Vận Hành Doanh Nghiệp AI-Native]]\n",
        "> - 📑 **Toàn Văn Bản Thảo Hợp Nhất (Full Manuscript)**: [[ai_eos_playbook_full_manuscript|Toàn Văn Bản Thảo AI-EOS Playbook]]\n",
        "> - 🏛️ **Khung Pháp Lý & Tiêu Chuẩn 2026**: [[tong_quan_khung_phap_ly_xay_dung_2026|Tổng Quan Khung Pháp Lý Quản Lý Chất Lượng & Số Hóa Xây Dựng 2026]]\n\n",
        "---\n\n",
        "## 📖 Source Topics (Bản Đồ Nguồn)\n\n",
    ]

    # Render Books MOC
    lines.append(f"> [!book]+ 📚 1. Sách & Ấn Bản Hệ Thống (Books & Literature) [{len(books_mocs)}]\n")
    lines.append("> Các bản đồ tri thức tổng hợp từ sách giấy, EPUB, PDF có tính hệ thống cao.\n>\n")
    if books_mocs:
        for stem, name in books_mocs:
            lines.append(f"> - [[{stem}|{name}]]\n")
    else:
        lines.append("> - *(Chưa có)*\n")
    lines.append("\n")

    # Render Media MOC
    lines.append(f"> [!video]- 🎥 2. Bài Giảng, Video & Podcasts (Media & Audio) [{len(media_mocs)}]\n")
    lines.append("> Tri thức đúc kết từ các tập podcast, bài nói chuyện, video YouTube chất lượng cao.\n>\n")
    if media_mocs:
        for stem, name in media_mocs:
            lines.append(f"> - [[{stem}|{name}]]\n")
    else:
        lines.append("> - *(Chưa có)*\n")
    lines.append("\n")

    # Render Articles MOC
    lines.append(f"> [!note]+ 📰 3. Bài Báo, Nghiên Cứu & Web Clips (Articles & Web) [{len(articles_mocs)}]\n")
    lines.append("> Các bài viết chuyên sâu từ internet, tài liệu văn bản ngắn hoặc stubs tổng hợp.\n>\n")
    if articles_mocs:
        for stem, name in articles_mocs:
            lines.append(f"> - [[{stem}|{name}]]\n")
    else:
        lines.append("> - *(Chưa có)*\n")
    lines.append("\n")

    # Render Domain MOCs
    lines.append("## 🏷️ Domain Topics (Bản Đồ Lĩnh Vực)\n\n")
    for category, info in GRAND_DOMAINS.items():
        mocs = domain_groups[category]
        if not mocs:
            continue
        lines.append(f"> [!info]+ {info['title']} [{len(mocs)}]\n")
        for stem, name in sorted(mocs, key=lambda x: x[1]):
            lines.append(f"> - [[{stem}|{name}]]\n")
        lines.append("\n")

    if domain_groups["other"]:
        lines.append(f"> [!quote]- 📁 Lĩnh Vực Khác (Other Domains) [{len(domain_groups['other'])}]\n")
        for stem, name in sorted(domain_groups["other"], key=lambda x: x[1]):
            lines.append(f"> - [[{stem}|{name}]]\n")
        lines.append("\n")

    # Render Top 30 Concepts
    lines.append("## 🆕 Concept Gần Đây Nhất\n\n")
    lines.append("> [!note]- 🆕 Top 30 Concept Mới Cập Nhật\n")
    for c in recent:
        title = c.get("title", c["_stem"])
        created = c.get("date_created", "")
        lines.append(f"> - [{created}] [[{c['_stem']}|{title}]]\n")
    lines.append("\n")

    # Dynamic Dataview Dashboard
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

    _safe_write_text(cfg.index_file, "".join(lines))
    _logger.info("Master Index rebuilt")


def rebuild_incremental(concept: dict | Path) -> None:
    """Incrementally rebuild only the MOCs affected by a single concept.

    1. Updates cache for the modified/new concept note.
    2. Identifies affected source stem and updates its Source MOC.
    3. Identifies affected domain tags and updates their Domain MOCs.
    4. Updates Master Index (index.md) recent concepts and stats.

    Runtime: < 0.05s.
    """
    from core.vault import update_concept_cache

    concept_data: dict[str, Any] | None = None
    if isinstance(concept, Path):
        concept_data = update_concept_cache(concept)
    elif isinstance(concept, dict):
        concept_data = concept
        p = concept.get("_path")
        if p and isinstance(p, Path) and p.exists():
            update_concept_cache(p, concept_data)

    if not concept_data:
        return

    all_concepts = scan_all_concepts()
    all_sources = scan_all_sources()

    # 1. Rebuild affected Source MOC(s)
    src_val = concept_data.get("source", "")
    if src_val:
        src_stems = flatten_source_list(src_val)
        for src_stem in src_stems:
            matched_source = next((s for s in all_sources if s.get("_stem") == src_stem), None)
            if matched_source:
                linked = [c for c in all_concepts if src_stem in flatten_source_list(c.get("source") or c.get("sources") or "")]
                if linked:
                    moc_path, content = _render_source_moc_content(matched_source, linked)
                    _safe_write_text(moc_path, content)

    # 2. Rebuild affected Domain MOC(s)
    known_sources = {normalize_stem(s.get("_stem", "")) for s in all_sources}
    for s in all_sources:
        for a in _get_source_aliases(s):
            known_sources.add(normalize_stem(a))

    tags = concept_data.get("tags", [])
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("domain/"):
            raw_domain = _normalize_domain_tag(tag.split("/", 1)[1])
            domain = DOMAIN_ALIASES.get(raw_domain, raw_domain)
            domain_concepts = [
                c for c in all_concepts
                if any(
                    DOMAIN_ALIASES.get(_normalize_domain_tag(t.split("/", 1)[1]), _normalize_domain_tag(t.split("/", 1)[1])) == domain
                    for t in c.get("tags", [])
                    if isinstance(t, str) and t.startswith("domain/")
                )
            ]
            if len(domain_concepts) >= DOMAIN_MOC_THRESHOLD:
                moc_path, content = _render_domain_moc_content(domain, domain_concepts, known_sources=known_sources)
                _safe_write_text(moc_path, content)

    # 3. Update Master Index
    _build_master_index(all_concepts, all_sources)


def rebuild_all(concepts: list[dict] | None = None, sources: list[dict] | None = None) -> None:
    """Rebuild all MOCs and the Master Index, unlinking stale MOCs."""
    lock_file = cfg.state_dir / "wiki_maintain.lock"
    try:
        with CrossProcessFileLock(lock_file, timeout=60.0):
            if concepts is None:
                concepts = scan_all_concepts()
            if sources is None:
                sources = scan_all_sources()

            # Track active paths to preserve
            active_paths = set()

            active_source_paths = _build_source_mocs(concepts, sources)
            active_paths.update(active_source_paths)

            active_domain_paths = _build_domain_mocs(concepts, sources)
            active_paths.update(active_domain_paths)

            # Master index is always active
            active_paths.add(cfg.index_file.resolve())
            # Command file is always preserved
            if cfg.command_file:
                active_paths.add(Path(cfg.command_file).resolve())

            # Pre-existing documents or active user files to preserve
            preserved_names = {"Weekly_Synthesis.md"}

            # Self-healing stale file cleanup (scans recursively across moc_dir and sub-folders)
            for f in list(cfg.moc_dir.rglob("*.md")):
                if f.name in preserved_names:
                    continue

                f_resolved = f.resolve()
                if f_resolved not in active_paths:
                    # Only delete files starting with MOC_ or Domain_ to be absolutely safe
                    if f.name.startswith("MOC_") or f.name.startswith("Domain_"):
                        try:
                            f.unlink()
                            _logger.info(f"Cleaned up stale MOC file: {f.name}")
                        except OSError as e:
                            _logger.warning(f"Failed to delete stale MOC file {f.name}: {e}")

            _build_master_index(concepts, sources)

            _logger.info(f"Wiki maintained: {len(concepts)} concepts, {len(sources)} sources")
            log("lint", f"Rebuilt MOCs: {len(concepts)} concepts")
    except TimeoutError:
        _logger.warning("Another process is maintaining wiki; skipping concurrent rebuild")


# Canonical alias
maintain_wiki = rebuild_all


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    parser = argparse.ArgumentParser(description="VvC Second Brain — Wiki Maintainer")
    parser.add_argument("--check-only", action="store_true", help="Dry-run vault health check without modifying MOCs")
    parser.add_argument("--fix-code-pills", action="store_true", help="Automatically heal code-pill wikilinks")
    args = parser.parse_args()

    if args.check_only:
        from services.wiki_health import scan_wikilink_code_pills
        concepts = scan_all_concepts()
        sources = scan_all_sources()
        code_pills = scan_wikilink_code_pills(fix=args.fix_code_pills)
        print(f"Vault Verification: {len(concepts)} concepts, {len(sources)} sources.")
        if code_pills:
            print(f"WARNING: Found {len(code_pills)} files with code-pill wikilinks (total matches: {sum(c['count'] for c in code_pills)}):")
            for item in code_pills:
                print(f"  - {item['file']}: {item['count']} pills")
        else:
            print("Clean Wikilink Invariant check: PASS (0 code-pill wikilinks found).")
        print("Vault health check complete.")
    else:
        rebuild_all()
        print("Wiki maintenance complete.")
