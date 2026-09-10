"""VvC Second Brain — Concept Synthesis (Map-Reduce).

Handles Map-Reduce concept extraction, transcript saving, image weaving,
and concept reference enrichment.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.frontmatter import normalize_stem
from pipeline.post_process import save_concept
from pipeline.synthesize import fix_section_ordering
from services.url_fetcher import fetch_url_title
from services.brain_dump.url_registry import _URL_PATTERN, _extract_related_links

_logger = logging.getLogger("vvc.dump")

from core.prompts.services import BRAIN_DUMP_MAP as _MAP_PROMPT  # noqa: E402
from core.prompts.services import BRAIN_DUMP_REDUCE as _REDUCE_PROMPT  # noqa: E402



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


def _weave_images_into_transcript(transcript_text: str, img_markers_text: str) -> str:
    """Weaves high-res frames into their exact chronological transcript positions.
    
    Inserts premium context-aware Obsidian callout blocks and anchors.
    """
    if not img_markers_text:
        return transcript_text
        
    # 1. Trích xuất tất cả các ảnh [IMG:filename|alt=...]
    img_matches = re.findall(r"\[IMG:([^\]|]+)(?:\|alt=([^\]]*))?]", img_markers_text)
    if not img_matches:
        return transcript_text
        
    # Phân tích và nhóm ảnh theo timestamp
    images = []
    for filename, alt in img_matches:
        filename = filename.strip()
        alt = alt.strip() if alt else "Video frame - diagram/slide"
        # Tìm ts<seconds> trong tên file
        ts_match = re.search(r"_ts(\d+)", filename)
        if ts_match:
            seconds = int(ts_match.group(1))
            images.append({
                "filename": filename,
                "alt": alt,
                "seconds": seconds
            })
            
    if not images:
        return transcript_text
        
    # Sắp xếp ảnh theo thứ tự thời gian tăng dần
    images.sort(key=lambda x: x["seconds"])
    
    # 2. Tìm tất cả các phân đoạn thời gian [MM:SS] hoặc khoảng thời gian [MM:SS - MM:SS] trong transcript
    segment_pattern = re.compile(r"\[(\d+):(\d+)(?:\s*-\s*\d+:\d+)?]")
    segments = []
    
    for match in segment_pattern.finditer(transcript_text):
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        total_seconds = minutes * 60 + seconds
        segments.append({
            "start_char": match.start(),
            "end_char": match.end(),
            "seconds": total_seconds,
            "time_str": f"[{minutes:02d}:{seconds:02d}]"
        })
        
    if not segments:
        # Fallback: Nếu không có mốc thời gian, tạo catalog ở cuối
        gallery = "\n\n## 🖼️ Danh sách Slide HD\n"
        for img in images:
            c_type, emoji, title_suffix = _determine_callout_style(img["alt"])
            gallery += f"\n### {emoji} {title_suffix} tại {img['seconds']}s ^ts{img['seconds']}\n![[{img['filename']}]]\n"
        return transcript_text + gallery
        
    # 3. Dệt ảnh vào transcript
    # Duyệt ngược từ dưới lên trên để không làm lệch chỉ số start_char / end_char
    images.sort(key=lambda x: x["seconds"], reverse=True)
    
    modified_text = transcript_text
    
    for img in images:
        target_sec = img["seconds"]
        # Tìm phân đoạn có seconds <= target_sec và sát nhất
        best_seg = None
        for seg in segments:
            if seg["seconds"] <= target_sec:
                if best_seg is None or seg["seconds"] > best_seg["seconds"]:
                    best_seg = seg
                    
        if best_seg is None:
            best_seg = segments[0]
            
        m = int(target_sec // 60)
        s = int(target_sec % 60)
        
        # Determine premium styling based on context
        c_type, emoji, title_suffix = _determine_callout_style(img["alt"])
        
        insert_text = (
            f"\n\n> [!{c_type}]- {emoji} {title_suffix} tại {m:02d}:{s:02d} ^ts{target_sec}\n"
            f"> ![[{img['filename']}]]\n\n"
        )
        
        # Tìm vị trí xuống dòng gần nhất phía trước start_char của phân đoạn được chọn
        pos = best_seg["start_char"]
        newline_pos = modified_text.rfind("\n", 0, pos)
        if newline_pos != -1:
            insert_pos = newline_pos + 1
        else:
            insert_pos = 0
            
        # Nếu giữa insert_pos và pos chứa một tiêu đề markdown (#+), dời insert_pos xuống ngay sau tiêu đề đó
        sub_segment = modified_text[insert_pos:pos]
        header_match = re.search(r"^(#+\s+[^\n]+)", sub_segment, re.MULTILINE)
        if header_match:
            insert_pos = insert_pos + header_match.end()
            if insert_pos < len(modified_text) and modified_text[insert_pos] == "\n":
                insert_pos += 1
            
        modified_text = modified_text[:insert_pos] + insert_text + modified_text[insert_pos:]
        
    # 4. Xóa bỏ hoàn toàn các tag mốc thời gian [MM:SS] hoặc khoảng thời gian [MM:SS - MM:SS] thô để văn bản tự nhiên tuyệt đối!
    modified_text = re.sub(r"\s*\[\d+:\d+(?:\s*-\s*\d+:\d+)?]", "", modified_text)
    
    return modified_text


def _save_transcript(text: str, original_url: str = "") -> str:
    """Save processed transcript to 04 - Permanent/sources/transcripts. Returns file stem."""
    if not text or len(text.strip()) < 50:
        return ""
        
    # --- Dệt hình ảnh slide HD vào transcript ---
    img_marker = "## 🎬 Hình ảnh trực quan từ video"
    img_section = ""
    transcript_text = text
    
    if img_marker in text:
        parts = text.split(img_marker, 1)
        transcript_text = parts[0].strip()
        img_section = img_marker + parts[1]
        
    if img_section:
        transcript_text = _weave_images_into_transcript(transcript_text, img_section)
        transcript_text = f"{transcript_text}\n\n{img_section}"
        
    text = transcript_text
        
    transcripts_dir = cfg.sources_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp_date = date.today().isoformat()
    title = ""
    # Extract title from markdown heading in first line if present (prevents Mojibake re-fetch)
    if text.strip().startswith("# "):
        first_line = text.strip().split("\n", 1)[0]
        extracted_title = first_line.lstrip("# ").strip()
        if extracted_title:
            title = extracted_title

    if not title and original_url:
        title = fetch_url_title(original_url)
        
    slug = ""
    if title:
        slug = normalize_stem(title)
        if len(slug) > 40:
            slug = slug[:40].rsplit("_", 1)[0]
        filename = f"{timestamp_date}_{slug}.md"
        display_title = title
    elif original_url:
        # Fallback: derive slug from URL domain + path
        from urllib.parse import urlparse
        parsed = urlparse(original_url)
        host = (parsed.hostname or "").replace("www.", "")
        path_parts = parsed.path.strip("/").split("/")
        path_slug = normalize_stem(path_parts[-1]) if path_parts and path_parts[-1] else ""
        if path_slug and len(path_slug) > 5:
            slug = path_slug[:40].rsplit("_", 1)[0] if len(path_slug) > 40 else path_slug
        else:
            slug = normalize_stem(host.split(".")[0])
        filename = f"{timestamp_date}_{slug}.md"
        display_title = f"Brain Dump Source — {host}"
    else:
        timestamp_time = datetime.now().strftime("%H%M%S")
        filename = f"{timestamp_date}_{timestamp_time}_BrainDump_Source.md"
        display_title = f"Brain Dump Source {timestamp_date} {timestamp_time}"
        
    filepath = transcripts_dir / filename
    
    # --- Dedup: reuse existing transcript with same slug (different date) ---
    if slug:
        existing = list(transcripts_dir.glob(f"*_{slug}.md"))
        existing = [f for f in existing if f.name != filename]
        if existing:
            filepath = existing[0]  # Reuse oldest file path
            filename = filepath.name
            _logger.info(f"Overwriting existing transcript: {filename}")
    
    # Preserve original date_created if overwriting
    date_created = date.today().isoformat()
    if filepath.exists():
        try:
            from core.frontmatter import parse_frontmatter
            old_fm, _ = parse_frontmatter(filepath.read_text(encoding="utf-8"))
            date_created = old_fm.get("date_created", date_created)
        except Exception:
            pass
    
    fm = (
        f"---\n"
        f"title: \"{display_title}\"\n"
        f"aliases:\n  - \"{filename[:-3]}_Source\"\n"
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
    
    if original_url:
        import datetime as dt
        from services.podcast import is_podcast_url

        is_youtube = "youtube.com" in original_url or "youtu.be" in original_url
        is_podcast = is_podcast_url(original_url)

        # Option B: Source Note Enrichment — extract related links (articles only, skip YouTube and Podcasts)
        related_links_md = ""
        if not is_youtube and not is_podcast:
            related = _extract_related_links(original_url)
            if related:
                links_block = "\n".join(f"- [{u}]({u})" for u in related)
                related_links_md = f"\n\n## 🔗 Related Links\n\n{links_block}\n"

        body = (
            f"> [!info] 🌐 Nguồn thu thập (Brain Dump)\n"
            f"> **Link gốc:** [{original_url}]({original_url})\n"
            f"> **Thời gian:** {dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
            f"## 📝 Nội dung thô (Transcript / Text Extracted)\n\n{text}{related_links_md}\n"
        )
    else:
        body = f"# Raw Sources for Brain Dump\n\n{text}\n"
    
    try:
        filepath.write_text(fm + body, encoding="utf-8")
        _logger.info(f"Saved source text to {filepath.name}")
        return filepath.stem
    except OSError as e:
        _logger.warning(f"Failed to save transcript {filename}: {e}")
        return ""

def _enrich_concept_references(concept_text: str, source_ref: str) -> str:
    """Enriches the ## References section with precise chronological anchor-links.
    
    Finds all embedded frame images, parses their timestamps, and appends deep-links.
    """
    if not source_ref or source_ref == "brain_dump":
        return concept_text
        
    # 1. Tìm tất cả các ảnh dạng ![[yt_..._ts(\d+).webp]]
    img_matches = re.findall(r"!\[\[yt_[^\]]+_ts(\d+)\.webp\]\]", concept_text)
    if not img_matches:
        return concept_text
        
    # Loại bỏ trùng lặp và sắp xếp timestamp tăng dần
    timestamps = sorted(list(set(int(ts) for ts in img_matches)))
    
    # 2. Xây dựng danh sách liên kết neo
    links = []
    for ts in timestamps:
        m = int(ts // 60)
        s = int(ts % 60)
        links.append(f"  - [[{source_ref}#^ts{ts}|Xem slide và ngữ cảnh chi tiết tại [{m:02d}:{s:02d}] trong ghi chép gốc]]")
        
    if not links:
        return concept_text
        
    # 3. Tìm và làm giàu mục ## References
    # Định dạng tham chiếu gốc thường là: - [[source_ref]] hoặc - [[source_ref|alias]]
    target_pattern = rf"-\s*\[\[{re.escape(source_ref)}(?:\|[^\]]*)?]]"
    match = re.search(target_pattern, concept_text)
    
    if match:
        original_ref = match.group(0)
        enriched_ref = original_ref + "\n" + "\n".join(links)
        concept_text = concept_text.replace(original_ref, enriched_ref, 1)
        
    return concept_text


def _backlink_source_to_concepts(
    source_ref: str, saved_stems: list[tuple[str, str]]
) -> None:
    """Inserts backlinks from Source Note ^ts callouts to referencing Concept Notes.

    Creates the reverse direction of the Dual-Layer cross-link:
    Source Note → Concept Note (complements _enrich_concept_references).
    Idempotent: skips backlinks that already exist in the Source Note.
    """
    if not source_ref or source_ref == "brain_dump" or not saved_stems:
        return

    # Locate Source Note in transcripts/
    source_file = cfg.sources_dir / "transcripts" / f"{source_ref}.md"
    if not source_file.exists():
        return

    # Build timestamp → concepts mapping by reading saved concept files
    ts_to_concepts: dict[int, list[tuple[str, str]]] = {}

    for stem, title in saved_stems:
        concept_file = cfg.concepts_dir / f"{stem}.md"
        if not concept_file.exists():
            continue
        try:
            text = concept_file.read_text(encoding="utf-8")
        except OSError:
            continue

        for m in re.finditer(r"yt_[^\]]+_ts(\d+)\.webp", text):
            ts = int(m.group(1))
            if (stem, title) not in ts_to_concepts.get(ts, []):
                ts_to_concepts.setdefault(ts, []).append((stem, title))

    if not ts_to_concepts:
        return

    try:
        source_text = source_file.read_text(encoding="utf-8")
    except OSError:
        return

    # Process line-by-line, inserting backlinks after ^ts callout blocks
    lines = source_text.split("\n")
    new_lines: list[str] = []
    i = 0
    modified = False

    while i < len(lines):
        new_lines.append(lines[i])

        # Check if line contains a ^ts anchor
        ts_anchor = re.search(r"\^ts(\d+)", lines[i])
        if ts_anchor:
            ts = int(ts_anchor.group(1))
            concepts = ts_to_concepts.get(ts)
            if concepts:
                # Consume remaining callout lines (starting with >)
                while i + 1 < len(lines) and lines[i + 1].startswith(">"):
                    i += 1
                    new_lines.append(lines[i])

                # Insert backlinks inside the callout block
                for stem, title in concepts:
                    backlink = f"> 📎 [[{stem}|{title}]]"
                    # Idempotency: skip if already present in original text
                    if backlink not in source_text:
                        new_lines.append(backlink)
                        modified = True
        i += 1

    if modified:
        try:
            source_file.write_text("\n".join(new_lines), encoding="utf-8")
            _logger.info(
                f"Two-way cross-linked {len(ts_to_concepts)} anchors "
                f"in Source Note: {source_ref}"
            )
        except OSError as e:
            _logger.warning(f"Failed to backlink Source Note: {e}")


def _synthesize_and_save_concepts(dump_text: str, url_content: str, source_ref: str) -> list[tuple[str, str]]:
    today = date.today().isoformat()
    
    # Calculate proportional dynamic concept extraction limits based on raw input length
    total_len = len(dump_text) + len(url_content)
    if total_len < 5000:
        min_c, max_c = 1, 3
    elif total_len < 20000:
        min_c, max_c = 3, 7
    elif total_len < 50000:
        min_c, max_c = 5, 12
    else:
        min_c, max_c = 8, 18
        
    _logger.info(f"[Map-Reduce] Calculated dynamic limit based on raw text volume ({total_len} chars): min={min_c}, max={max_c} concepts.")
    
    # --- MAP STEP (Extraction) ---
    map_prompt = _MAP_PROMPT.format(
        dump_text=dump_text,
        url_content=url_content or "(không có URL content)",
        min_concepts=min_c,
        max_concepts=max_c,
    )
    
    _logger.info("Executing Map step: Extracting atomic concepts via Synthesis tier (Gemini 3.8 Flash High)...")
    map_result = call_llm(map_prompt, task="synthesis")
    if not map_result:
        log("error", "Brain Dump MAP step failed")
        return []
        
    try:
        # Extract JSON from the output (handling markdown code blocks if any)
        json_match = re.search(r'\[\s*\{.*\}\s*\]', map_result, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = map_result
            
        concepts_list = json.loads(json_str)
        if not isinstance(concepts_list, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        _logger.error(f"Failed to parse MAP step JSON: {e}")
        log("error", "Brain Dump MAP step failed to parse JSON")
        return []
        
    _logger.info(f"Map step found {len(concepts_list)} concepts. Starting Reduce step...")
    
    # Extract original URL if present
    original_url = ""
    urls = _URL_PATTERN.findall(dump_text)
    if urls:
        original_url = urls[0]

    # --- REDUCE STEP (Synthesis) ---
    saved_stems = []
    for idx, concept_meta in enumerate(concepts_list):
        c_title = concept_meta.get("title", f"Concept {idx+1}")
        c_summary = concept_meta.get("summary", "")
        
        _logger.info(f"Reducing concept {idx+1}/{len(concepts_list)}: {c_title}")
        
        reduce_prompt = _REDUCE_PROMPT.format(
            dump_text=dump_text,
            url_content=url_content or "(không có URL content)",
            concept_title=c_title,
            concept_summary=c_summary,
            today=today,
            source_ref=source_ref
        )
        
        concept_body = call_llm(reduce_prompt, task="synthesis")
        if not concept_body or len(concept_body) < 100:
            _logger.warning(f"Failed to generate concept: {c_title}")
            continue
            
        # Robustly extract from the first YAML marker (support CRLF and LF)
        match = re.search(r"(---\r?\n.*)", concept_body, re.DOTALL)
        if not match:
            _logger.warning(f"Failed to find YAML frontmatter for: {c_title}")
            continue
            
        concept_clean = match.group(1)
        concept_clean = re.sub(r"\n```\s*$", "", concept_clean)
        
        # Apply strict section ordering
        concept_clean = fix_section_ordering(concept_clean)
        
        # Tự động làm giàu các tham chiếu neo block từ ảnh được nhúng JIT
        concept_clean = _enrich_concept_references(concept_clean, source_ref)
        
        # Add Premium Source Callout at the bottom of the concept
        if original_url:
            import datetime as dt
            time_str = dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            source_callout = (
                f"\n\n> [!info]- 🌐 Nguồn thu thập\n"
                f"> Ghi chép được thu thập từ internet (click để mở)\n"
                f"> - **Đường dẫn gốc:** [{original_url}]({original_url})\n"
                f"> - **Thời gian thu thập:** {time_str}\n"
                f"> - **Tệp nguồn thô:** [[{source_ref}]]\n"
            )
            concept_clean = f"{concept_clean.rstrip()}{source_callout}"
            
        saved_path = save_concept(concept_clean)
        if saved_path:
            saved_stems.append((saved_path.stem, c_title))

    # Two-way cross-link: Source Note → Concept Note
    if saved_stems:
        _backlink_source_to_concepts(source_ref, saved_stems)

    return saved_stems
