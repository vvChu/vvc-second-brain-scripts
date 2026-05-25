"""VvC Second Brain — Wiki Maintainer (v7.0).

Builds and maintains MOC pages, Domain MOCs, and the Master Index.

Usage:
    python wiki_maintain.py          # Manual full rebuild
    from wiki_maintain import rebuild_all
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from core.config import cfg
from core.frontmatter import normalize_stem
from core.log import log
from core.vault import scan_all_concepts, scan_all_sources

_logger = logging.getLogger("vvc.maintain")

DOMAIN_MOC_THRESHOLD = 8  # Min concepts to create a Domain MOC

GRAND_DOMAINS = {
    "tech": {
        "title": "💻 Công Nghệ & Hệ Thống (Technology & Systems)",
        "keywords": ["ai", "computing", "deep_learning", "digital_transformation", "engineering", "software", "technology"]
    },
    "cognition": {
        "title": "🧠 Nhận Thức & Phát Triển (Cognition & Growth)",
        "keywords": ["cognitive", "learning", "neuroscience", "psychology", "philosophy", "phat_trien", "personal", "education"]
    },
    "business": {
        "title": "💰 Kinh Doanh & Tài Chính (Business & Economics)",
        "keywords": ["business", "economics", "entrepreneurship", "finance"]
    },
    "management": {
        "title": "👥 Quản Trị & Tổ Chức (Management & Leadership)",
        "keywords": ["management", "culture", "hr", "human_resources", "innovation", "leadership", "organization", "strategy", "productivity"]
    }
}



def _normalize_moc_name(name: str) -> str:
    """Normalize a display name into a clean, accent-free Title_Cased MOC name."""
    import unicodedata
    # Replace đ/Đ manually since NFKD does not decompose them
    name = name.replace("đ", "d").replace("Đ", "D")
    # Decompose unicode to separate base characters and accents, then strip accents
    normalized = unicodedata.normalize('NFKD', name)
    name = normalized.encode('ascii', 'ignore').decode('ascii')
    # Replace non-alphanumeric with underscores
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    # Capitalize each word for proper Title_Casing
    return "_".join(w.capitalize() for w in name.split("_") if w)


def rebuild_all(concepts: list[dict] | None = None, sources: list[dict] | None = None) -> None:
    """Rebuild all MOCs and the Master Index, unlinking stale MOCs."""
    if concepts is None:
        concepts = scan_all_concepts()
    if sources is None:
        sources = scan_all_sources()

    # Track active paths to preserve
    active_paths = set()

    active_source_paths = _build_source_mocs(concepts, sources)
    active_paths.update(active_source_paths)

    active_domain_paths = _build_domain_mocs(concepts)
    active_paths.update(active_domain_paths)

    # Master index is always active
    active_paths.add(cfg.index_file.resolve())
    # Command file is always preserved
    if cfg.command_file:
        active_paths.add(Path(cfg.command_file).resolve())

    # Pre-existing documents or active user files to preserve
    preserved_names = {"Weekly_Synthesis.md", "Chien_Luoc_NVIDIA_Jensen_Huang.md", "Chien_Luoc_NVIDIA_Jensen_Huang.docx"}

    # Self-healing stale file cleanup
    for f in cfg.moc_dir.iterdir():
        if f.suffix not in (".md", ".docx") or f.name in preserved_names:
            continue
        
        f_resolved = f.resolve()
        if f_resolved not in active_paths:
            # Only delete files starting with MOC_ or Domain_ to be absolutely safe!
            if f.name.startswith("MOC_") or f.name.startswith("Domain_"):
                try:
                    f.unlink()
                    _logger.info(f"Cleaned up stale MOC file: {f.name}")
                except OSError as e:
                    _logger.warning(f"Failed to delete stale MOC file {f.name}: {e}")

    _build_master_index(concepts, sources)

    _logger.info(f"Wiki maintained: {len(concepts)} concepts, {len(sources)} sources")
    log("lint", f"Rebuilt MOCs: {len(concepts)} concepts")


def _generate_mermaid_flowchart(concepts_in_group: list[dict]) -> str:
    """Generate a clean, professional Mermaid flowchart TD representing connections between concepts."""
    # Find active stems in this group
    stems = {c["_stem"] for c in concepts_in_group}
    
    edges = []
    seen_edges = set()
    
    for c in concepts_in_group:
        stem = c["_stem"]
        
        # 1. Parse related links
        related = c.get("related", [])
        if isinstance(related, list):
            for rel in related:
                if isinstance(rel, list):
                    rel = rel[0] if rel else None
                if not isinstance(rel, str):
                    continue
                # Strip obsidian wiki brackets if present in the related string
                rel_cleaned = rel.replace("[[", "").replace("]]", "").strip()
                rel_norm = normalize_stem(rel_cleaned)
                if rel_norm in stems and rel_norm != stem:
                    edge = (stem, rel_norm)
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        edges.append(edge)
                        
        # 2. Parse links inside the body if they point to concepts in the same group
        links = c.get("_links", [])
        if isinstance(links, list):
            for link in links:
                normalized_link = normalize_stem(link)
                if normalized_link in stems and normalized_link != stem:
                    edge = (stem, normalized_link)
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        edges.append(edge)

    # If there are no connections, don't generate the diagram
    if not edges:
        return ""
        
    # Limit edges to 20 to prevent visual chaos
    if len(edges) > 20:
        edges = edges[:20]
        
    # Build diagram lines
    lines = [
        "\n> [!visual]- 🗺️ Sơ đồ Kết Nối Ý Niệm (Concept Map)\n",
        "> ```mermaid\n",
        "> flowchart TD\n",
        ">     %% Grayscale Academic Theme Style\n",
        ">     classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;\n"
    ]
    
    # Render nodes and edges
    unique_stems = set()
    for src, tgt in edges:
        unique_stems.add(src)
        unique_stems.add(tgt)
        
    # Render node label maps
    for stem in sorted(unique_stems):
        # Find display title in group
        matching = [c for c in concepts_in_group if c["_stem"] == stem]
        title = matching[0].get("title", stem) if matching else stem
        display_title = title[:35] + "..." if len(title) > 38 else title
        display_title = display_title.replace('"', "'").replace("(", "[").replace(")", "]")
        lines.append(f">     {stem}[\"{display_title}\"]\n")
        
    # Render edges
    for src, tgt in sorted(edges):
        lines.append(f">     {src} --> {tgt}\n")
        
    lines.append("> ```\n\n")
    return "".join(lines)


# --- Source MOCs ---

def _build_source_mocs(concepts: list[dict], sources: list[dict]) -> list[Path]:
    """Build MOC_*.md for each source book with a premium visual abstract."""
    source_map: dict[str, list[dict]] = defaultdict(list)
    active_paths = []

    for c in concepts:
        src_val = c.get("source", "")
        if src_val:
            srcs = []
            if isinstance(src_val, str):
                srcs.append(src_val)
            elif isinstance(src_val, list):
                def flatten(lst):
                    for item in lst:
                        if isinstance(item, list):
                            yield from flatten(item)
                        elif isinstance(item, str):
                            yield item
                srcs.extend(flatten(src_val))
            
            for src in srcs:
                if src.endswith(".md"):
                    src = src[:-3]
                source_map[src].append(c)

    for src in sources:
        src_stem = src["_stem"]
        linked_concepts = source_map.get(src_stem, [])
        if not linked_concepts:
            continue

        aliases = src.get("aliases", [])
        display_name = aliases[0] if aliases else src.get("title", src_stem)

        # Title Case for MOC filename with Unicode normalization
        moc_name = _normalize_moc_name(display_name)
        moc_path = cfg.moc_dir / f"MOC_{moc_name}.md"
        active_paths.append(moc_path.resolve())

        mermaid_graph = _generate_mermaid_flowchart(linked_concepts)

        lines = [
            f"# 🗺️ {display_name}\n\n",
            f"> [!abstract] **📌 Thông Tin Bản Đồ Nguồn**\n",
            f"> - 📖 **Nguồn gốc:** [[{src_stem}]]\n",
            f"> - 🧠 **Quy mô:** **{len(linked_concepts)}** khái niệm cốt lõi (Concepts)\n\n",
        ]
        
        if mermaid_graph:
            lines.append(mermaid_graph)
            
        lines.extend([
            "---\n\n",
            "## Concepts\n\n",
        ])

        for c in sorted(linked_concepts, key=lambda x: x.get("title", "")):
            title = c.get("title", c["_stem"])
            summary = c.get("summary", "")
            
            # Tính toán các Visual Indicators
            status = str(c.get("status", "seed")).lower()
            status_icon = "🌱" if status == "seed" else ("🌿" if status == "growing" else "🌳")
            
            confidence = str(c.get("confidence", "high")).lower()
            conf_indicator = " 🔍" if confidence in ("low", "medium") else ""
            
            lines.append(f"- {status_icon} [[{c['_stem']}|{title}]]{conf_indicator}{' — ' + summary if summary else ''}\n")

        try:
            moc_path.write_text("".join(lines), encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Failed to write MOC: {e}")

    return active_paths


# --- Domain MOCs ---

def _build_domain_mocs(concepts: list[dict]) -> list[Path]:
    """Build Domain_*.md for domains with enough concepts, formatting as visual dashboards."""
    domain_map: dict[str, list[dict]] = defaultdict(list)
    active_paths = []

    for c in concepts:
        for tag in c.get("tags", []):
            if tag.startswith("domain/"):
                # Normalize domain: standard lowercase, hyphen and slash to underscore
                domain = tag.split("/", 1)[1].replace("-", "_").replace("/", "_").lower()
                domain_map[domain].append(c)

    for domain, domain_concepts in domain_map.items():
        if len(domain_concepts) < DOMAIN_MOC_THRESHOLD:
            continue

        display = domain.replace("_", " ").title()
        moc_name = _normalize_moc_name(display)
        moc_path = cfg.moc_dir / f"Domain_{moc_name}.md"
        active_paths.append(moc_path.resolve())

        # Group by source
        by_source: dict[str, list[dict]] = defaultdict(list)
        for c in domain_concepts:
            src_val = c.get("source", "unknown")
            srcs = []
            if isinstance(src_val, str):
                srcs.append(src_val)
            elif isinstance(src_val, list):
                def flatten(lst):
                    for item in lst:
                        if isinstance(item, list):
                            yield from flatten(item)
                        elif isinstance(item, str):
                            yield item
                srcs.extend(flatten(src_val))
            
            for src in srcs:
                if src.endswith(".md"):
                    src = src[:-3]
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
            lines.append(f"### From [[{src}]]\n\n")
            for c in sorted(src_concepts, key=lambda x: x.get("title", "")):
                # Tính toán các Visual Indicators
                status = str(c.get("status", "seed")).lower()
                status_icon = "🌱" if status == "seed" else ("🌿" if status == "growing" else "🌳")
                
                confidence = str(c.get("confidence", "high")).lower()
                conf_indicator = " 🔍" if confidence in ("low", "medium") else ""
                
                lines.append(f"- {status_icon} [[{c['_stem']}|{c.get('title', c['_stem'])}]] {conf_indicator}\n")
            lines.append("\n")

        try:
            moc_path.write_text("".join(lines), encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Failed to write Domain MOC: {e}")

    return active_paths


# --- Master Index ---

def _build_master_index(concepts: list[dict], sources: list[dict]) -> None:
    """Build the Master Index (index.md) with a premium, organized visual dashboard."""
    # Count stats
    total_concepts = len(concepts)
    total_sources = len(sources)

    # Find MOC files
    source_mocs = sorted(cfg.moc_dir.glob("MOC_*.md"))
    domain_mocs = sorted(cfg.moc_dir.glob("Domain_*.md"))

    # Recently added (last 30)
    def _get_sort_key(c):
        d = c.get("date_created")
        d_str = d.isoformat() if isinstance(d, date) else (str(d) if d else "1970-01-01")
        path = c.get("_path")
        mtime = path.stat().st_mtime if path and path.exists() else 0
        return (d_str, mtime)

    recent = sorted(concepts, key=_get_sort_key, reverse=True)[:30]

    # Phân loại các Source MOCs
    moc_to_source = {}
    for src in sources:
        src_stem = src.get("_stem", "")
        aliases = src.get("aliases", [])
        display_name = aliases[0] if aliases else src.get("title", src_stem)
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
        
        # Làm sạch tên hiển thị (bỏ ngày tháng và chữ "Source" ở cuối nếu có)
        name = re.sub(r"^\d{4}\s\d{2}\s\d{2}\s(?:\d{6}\s)?", "", name)
        name = re.sub(r"\sSource$", "", name)
        
        if not src:
            articles_mocs.append((stem, name))
            continue
            
        source_type = str(src.get("source_type", "")).lower()
        title_lower = str(src.get("title", "")).lower()
        stem_lower = str(src.get("_stem", "")).lower()
        
        if source_type in ('pdf', 'epub', 'azw3', 'mobi', 'chm', 'epub3', 'azw'):
            books_mocs.append((stem, name))
        elif (source_type in ('audio', 'video') or 
              any(k in title_lower or k in stem_lower for k in ['youtube', 'podcast', 'video', 'interview', 'talk', 'talks', 'ss4_', 'wired', 'wired_interview'])):
            media_mocs.append((stem, name))
        else:
            articles_mocs.append((stem, name))

    # Phân loại Domain MOCs theo các Đại lộ tri thức
    domain_groups = {k: [] for k in GRAND_DOMAINS}
    domain_groups["other"] = []

    for moc in domain_mocs:
        name = moc.stem.replace("Domain_", "").replace("_", " ")
        domain_key = moc.stem.replace("Domain_", "").lower()
        
        matched = False
        for category, info in GRAND_DOMAINS.items():
            if any(kw in domain_key for kw in info["keywords"]):
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
        "## 📖 Source Topics (Bản Đồ Nguồn)\n\n",
    ]

    # Render Books MOC (Callout mặc định mở vì độ hệ thống cao)
    lines.append(f"> [!book]+ 📚 1. Sách & Ấn Bản Hệ Thống (Books & Literature) [{len(books_mocs)}]\n")
    lines.append("> Các bản đồ tri thức tổng hợp từ sách giấy, EPUB, PDF có tính hệ thống cao.\n>\n")
    if books_mocs:
        for stem, name in books_mocs:
            lines.append(f"> - [[{stem}|{name}]]\n")
    else:
        lines.append("> - *(Chưa có)*\n")
    lines.append("\n")

    # Render Media MOC (Callout mặc định đóng để tránh visual clutter)
    lines.append(f"> [!video]- 🎥 2. Bài Giảng, Video & Podcasts (Media & Audio) [{len(media_mocs)}]\n")
    lines.append("> Tri thức đúc kết từ các tập podcast, bài nói chuyện, video YouTube chất lượng cao.\n>\n")
    if media_mocs:
        for stem, name in media_mocs:
            lines.append(f"> - [[{stem}|{name}]]\n")
    else:
        lines.append("> - *(Chưa có)*\n")
    lines.append("\n")

    # Render Articles MOC (Callout mặc định mở vì số lượng ít và cần đọc nhanh)
    lines.append(f"> [!note]+ 📰 3. Bài Báo, Nghiên Cứu & Web Clips (Articles & Web) [{len(articles_mocs)}]\n")
    lines.append("> Các bài viết chuyên sâu từ internet, tài liệu văn bản ngắn hoặc stubs tổng hợp.\n>\n")
    if articles_mocs:
        for stem, name in articles_mocs:
            lines.append(f"> - [[{stem}|{name}]]\n")
    else:
        lines.append("> - *(Chưa có)*\n")
    lines.append("\n")

    # Render Domain MOCs chia theo 4 Đại lộ tri thức lớn
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

    # Render Top 30 Concept Gần Đây Nhất (gập gọn mặc định đóng)
    lines.append("## 🆕 Concept Gần Đây Nhất\n\n")
    lines.append("> [!note]- 🆕 Top 30 Concept Mới Cập Nhật\n")
    for c in recent:
        title = c.get("title", c["_stem"])
        created = c.get("date_created", "")
        lines.append(f"> - [{created}] [[{c['_stem']}|{title}]]\n")
    lines.append("\n")

    # Append the Dynamic Dataview Dashboard for premium interactive management (all collapsed to improve page load speed)
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
        "> ```\n"
    ])

    try:
        cfg.index_file.write_text("".join(lines), encoding="utf-8")
        _logger.info("Master Index rebuilt")
    except OSError as e:
        _logger.error(f"Failed to write index: {e}")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    rebuild_all()
    print("Wiki maintenance complete.")

