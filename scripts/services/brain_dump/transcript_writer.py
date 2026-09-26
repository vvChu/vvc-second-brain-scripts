"""VvC Second Brain — Brain Dump Transcript Writer & Cross-Linking Engine.

Handles:
- Context-aware Obsidian callout styling for video/slide frames
- Chronological weaving of high-res image markers into transcript text
- Saving processed transcripts to 04 - Permanent/sources/transcripts
- Two-way anchor cross-linking between Source Notes and Concept Notes
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

from core.frontmatter import normalize_stem

_logger = logging.getLogger("vvc.dump.transcript")


def _determine_callout_style(alt_text: str) -> tuple[str, str, str]:
    """Determines premium callout type, emoji, and display title based on alt-text.

    Returns:
        (callout_type, emoji, title_suffix)
    """
    alt = alt_text.lower()

    # 1. Code / Setup / CLI / Installation
    if any(kw in alt for kw in ["code", "python", "hàm", "function", "class", "lập trình", "viết mã", "setup", "cấu hình", "config", "command", "install"]):
        return "example", "💻", "Mã nguồn / Thiết lập"

    # 2. Tables / Comparison / Matrices
    if any(kw in alt for kw in ["bảng", "table", "so sánh", "matrix", "dữ liệu", "data"]):
        return "info", "📋", "Bảng biểu / Đối chiếu"

    # 3. Diagrams / Architecture / Charts / Workflows
    if any(kw in alt for kw in ["sơ đồ", "diagram", "kiến trúc", "architecture", "biểu đồ", "chart", "map", "workflow", "luồng", "mô hình", "model"]):
        return "abstract", "📊", "Sơ đồ / Kiến trúc"

    # 4. Quotes / Key Highlights / Quotes
    if any(kw in alt for kw in ["quote", "trích dẫn", "phát biểu", "định nghĩa", "definition"]):
        return "quote", "💬", "Trích dẫn / Định nghĩa"

    # 5. Fallback - Generic slide/frame
    return "abstract", "🖼️", "Slide trực quan"


def _extract_transcript_images(img_markers_text: str) -> list[dict]:
    """Extract and parse image markers with timestamp seconds."""
    img_matches = re.findall(r"\[IMG:([^\]|]+)(?:\|alt=([^\]]*))?]", img_markers_text)
    if not img_matches:
        return []

    images = []
    for filename, alt in img_matches:
        filename = filename.strip()
        alt = alt.strip() if alt else "Video frame - diagram/slide"
        ts_match = re.search(r"_ts(\d+)", filename)
        if ts_match:
            images.append({
                "filename": filename,
                "alt": alt,
                "seconds": int(ts_match.group(1))
            })
    return images


def _extract_transcript_segments(transcript_text: str) -> list[dict]:
    """Find all timestamp segments [MM:SS] in transcript."""
    segment_pattern = re.compile(r"\[(\d+):(\d+)(?:\s*-\s*\d+:\d+)?]")
    segments = []
    for match in segment_pattern.finditer(transcript_text):
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        segments.append({
            "start_char": match.start(),
            "end_char": match.end(),
            "seconds": minutes * 60 + seconds,
            "time_str": f"[{minutes:02d}:{seconds:02d}]"
        })
    return segments


def _build_fallback_image_gallery(images: list[dict]) -> str:
    """Build an image catalog section at the bottom when no timestamps exist."""
    gallery = "\n\n## 🖼️ Danh sách Slide HD\n"
    for img in images:
        _, emoji, title_suffix = _determine_callout_style(img["alt"])
        gallery += f"\n### {emoji} {title_suffix} tại {img['seconds']}s ^ts{img['seconds']}\n![[{img['filename']}]]\n"
    return gallery


def _insert_single_image(text: str, img: dict, segments: list[dict]) -> str:
    """Insert a single image callout near the closest matching timestamp segment."""
    target_sec = img["seconds"]
    best_seg = None
    for seg in segments:
        if seg["seconds"] <= target_sec:
            if best_seg is None or seg["seconds"] > best_seg["seconds"]:
                best_seg = seg
    if best_seg is None:
        best_seg = segments[0]

    m = int(target_sec // 60)
    s = int(target_sec % 60)
    c_type, emoji, title_suffix = _determine_callout_style(img["alt"])
    insert_text = (
        f"\n\n> [!{c_type}]- {emoji} {title_suffix} tại {m:02d}:{s:02d} ^ts{target_sec}\n"
        f"> ![[{img['filename']}]]\n\n"
    )

    pos = best_seg["start_char"]
    newline_pos = text.rfind("\n", 0, pos)
    insert_pos = (newline_pos + 1) if newline_pos != -1 else 0

    sub_segment = text[insert_pos:pos]
    header_match = re.search(r"^(#+\s+[^\n]+)", sub_segment, re.MULTILINE)
    if header_match:
        insert_pos = insert_pos + header_match.end()
        if insert_pos < len(text) and text[insert_pos] == "\n":
            insert_pos += 1

    return text[:insert_pos] + insert_text + text[insert_pos:]


def _weave_images_into_transcript(transcript_text: str, img_markers_text: str) -> str:
    """Weaves high-res frames into their exact chronological transcript positions."""
    if not img_markers_text:
        return transcript_text

    images = _extract_transcript_images(img_markers_text)
    if not images:
        return transcript_text

    images.sort(key=lambda x: x["seconds"])
    segments = _extract_transcript_segments(transcript_text)
    if not segments:
        return transcript_text + _build_fallback_image_gallery(images)

    # Sort descending so insertions near the end don't shift earlier character offsets
    images.sort(key=lambda x: x["seconds"], reverse=True)
    modified_text = transcript_text
    for img in images:
        modified_text = _insert_single_image(modified_text, img, segments)

    return re.sub(r"\s*\[\d+:\d+(?:\s*-\s*\d+:\d+)?]", "", modified_text)


def _resolve_transcript_metadata(text: str, original_url: str) -> tuple[str, str, str]:
    """Derive display title, slug, and filename for transcript."""
    import services.brain_dump.concept_synthesis as cs

    timestamp_date = date.today().isoformat()
    title = ""
    if text.strip().startswith("# "):
        first_line = text.strip().split("\n", 1)[0]
        title = first_line.lstrip("# ").strip()

    if not title and original_url:
        title = cs.fetch_url_title(original_url)

    if title:
        slug = normalize_stem(title)
        if len(slug) > 40:
            slug = slug[:40].rsplit("_", 1)[0]
        return title, slug, f"{timestamp_date}_{slug}.md"

    if original_url:
        from urllib.parse import urlparse
        parsed = urlparse(original_url)
        host = (parsed.hostname or "").replace("www.", "")
        path_parts = parsed.path.strip("/").split("/")
        path_slug = normalize_stem(path_parts[-1]) if path_parts and path_parts[-1] else ""
        if path_slug and len(path_slug) > 5:
            slug = path_slug[:40].rsplit("_", 1)[0] if len(path_slug) > 40 else path_slug
        else:
            slug = normalize_stem(host.split(".")[0])
        return f"Brain Dump Source — {host}", slug, f"{timestamp_date}_{slug}.md"

    timestamp_time = datetime.now().strftime("%H%M%S")
    return f"Brain Dump Source {timestamp_date} {timestamp_time}", "", f"{timestamp_date}_{timestamp_time}_BrainDump_Source.md"


def _resolve_existing_transcript_path(transcripts_dir: Path, slug: str, filename: str) -> tuple[Path, str, str]:
    """Find existing transcript to overwrite or return new target path."""
    filepath = transcripts_dir / filename
    if slug:
        existing = [f for f in transcripts_dir.glob(f"*_{slug}.md") if f.name != filename]
        if existing:
            filepath = existing[0]
            filename = filepath.name
            _logger.info(f"Overwriting existing transcript: {filename}")

    date_created = date.today().isoformat()
    if filepath.exists():
        try:
            from core.frontmatter import parse_frontmatter
            old_fm = parse_frontmatter(filepath.read_text(encoding="utf-8"))
            date_created = old_fm.get("date_created", date_created)
        except Exception:
            pass
    return filepath, filename, date_created


def _build_transcript_frontmatter(safe_title: str, filename: str, date_created: str) -> str:
    """Build YAML frontmatter string for a transcript source note."""
    return (
        f"---\n"
        f'title: "{safe_title}"\n'
        f'aliases:\n  - "{safe_title}"\n  - "{filename[:-3]}_Source"\n'
        f"tags:\n  - knowledge\n  - type/source\n"
        f"type: source\n"
        f"date_created: {date_created}\n"
        f"date_modified: {date.today().isoformat()}\n"
        f"source: \"brain_dump\"\n"
        f"source_type: text\n"
        f"summary: \"Raw transcript extracted via Brain Dump Watchdog.\"\n"
        f"related: []\n"
        f"confidence: high\n"
        f"---\n\n"
    )


def _build_transcript_body(text: str, original_url: str) -> str:
    """Build body section with optional metadata callout and related links."""
    import services.brain_dump.concept_synthesis as cs

    if not original_url:
        return f"# Raw Sources for Brain Dump\n\n{text}\n"

    import datetime as dt
    from services.podcast import is_podcast_url

    is_youtube = "youtube.com" in original_url or "youtu.be" in original_url
    is_podcast = is_podcast_url(original_url)

    related_links_md = ""
    if not is_youtube and not is_podcast:
        related = cs._extract_related_links(original_url)
        if related:
            links_block = "\n".join(f"- [{u}]({u})" for u in related)
            related_links_md = f"\n\n## 🔗 Related Links\n\n{links_block}\n"

    time_str = dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    return (
        f"> [!info] 🌐 Nguồn thu thập (Brain Dump)\n"
        f"> **Link gốc:** [{original_url}]({original_url})\n"
        f"> **Thời gian:** {time_str}\n\n"
        f"## 📝 Nội dung thô (Transcript / Text Extracted)\n\n{text}{related_links_md}\n"
    )


def _build_transcript_content(
    display_title: str,
    filename: str,
    date_created: str,
    text: str,
    original_url: str,
) -> str:
    """Build full frontmatter and body for a transcript markdown file."""
    safe_title = display_title.replace('"', '\\"')
    fm = _build_transcript_frontmatter(safe_title, filename, date_created)
    body = _build_transcript_body(text, original_url)
    return fm + body


def _save_transcript(text: str, original_url: str = "") -> str:
    """Save processed transcript to 04 - Permanent/sources/transcripts. Returns file stem."""
    import services.brain_dump.concept_synthesis as cs

    if not text or len(text.strip()) < 50:
        return ""

    img_marker = "## 🎬 Hình ảnh trực quan từ video"
    if img_marker in text:
        parts = text.split(img_marker, 1)
        transcript_text = parts[0].strip()
        img_section = img_marker + parts[1]
        text = f"{_weave_images_into_transcript(transcript_text, img_section)}\n\n{img_section}"

    transcripts_dir = cs.cfg.sources_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    display_title, slug, filename = _resolve_transcript_metadata(text, original_url)
    filepath, filename, date_created = _resolve_existing_transcript_path(transcripts_dir, slug, filename)
    content = _build_transcript_content(display_title, filename, date_created, text, original_url)

    try:
        filepath.write_text(content, encoding="utf-8")
        _logger.info(f"Saved source text to {filepath.name}")
        return filepath.stem
    except OSError as e:
        _logger.warning(f"Failed to save transcript {filename}: {e}")
        return ""

