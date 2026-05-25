"""VvC Second Brain — Post-Processing Stage (v8.6).

Save concept note, archive image, trigger MOC rebuild.
Supports 3-Tier Merge Control + SUBSUME deduplication.
"""

from __future__ import annotations

import logging
import re
import json
import shutil
from datetime import date, datetime
from pathlib import Path

from core.config import cfg
from core.frontmatter import parse_frontmatter, normalize_stem, extract_body, build_frontmatter
from core.llm import call_llm
from core.log import log

_logger = logging.getLogger("vvc.postproc")

# Sentinel returned by _arbitrate_and_merge when existing note fully subsumes new content
_SUBSUME_SENTINEL = Path("__SUBSUMED__")

# --- Quality Gate ---

# Template placeholder strings injected by synthesize.py prompts
_TEMPLATE_MARKERS: tuple[str, ...] = (
    "2-4 câu của bạn ở đây",
    "PHẢI nằm bên trong Core Idea",
    "câu phân tích của bạn",
    "your analysis here",
    "[phân tích của bạn]",
    "[HÃY VIẾT TÓM TẮT DÀI 2-3 CÂU CỦA BẠN VÀO ĐÂY]",
    "[VIẾT TÓM TẮT 2-3 CÂU VÀO ĐÂY]",
)

# Slug suffixes that indicate a title was cut at a meaningless boundary
_TRUNCATED_SUFFIXES: frozenset[str] = frozenset({
    "mh", "lit", "lh", "nh", "th", "ch", "gh", "kh", "ph", "bh",
})


def _validate_quality(content: str, stem: str) -> list[str]:
    """Run pre-save quality checks on a concept note.

    Args:
        content: Full note content (frontmatter + body).
        stem: Proposed filename stem (without extension).

    Returns:
        List of failure reasons (empty = pass).
    """
    failures: list[str] = []

    # 1. Template placeholders not filled
    for marker in _TEMPLATE_MARKERS:
        if marker in content:
            failures.append(f"template placeholder found: '{marker[:40]}'")
            break

    # 2. Core Idea section missing
    if "## Core Idea" not in content:
        failures.append("missing '## Core Idea' section")

    # 3. Blockquote is just a copy of the title (no real insight)
    title_m  = re.search(r"^title:\s*[^\n]+", content, re.MULTILINE)
    core_m   = re.search(r"## Core Idea\n+> (.+)", content)
    if title_m and core_m:
        clean = lambda s: re.sub(r"[^\w ]", "", s.lower())[:40]
        if clean(title_m.group(0))[:30] == clean(core_m.group(1))[:30]:
            failures.append("Core Idea blockquote is a copy of the title — no real analysis")

    # 4. Body too short (< 300 chars after frontmatter)
    fm_end = content.find("\n---\n", 3)
    body = content[fm_end + 4:].strip() if fm_end > 0 else content.strip()
    if len(body) < 300:
        failures.append(f"body too short ({len(body)} chars, minimum 300)")

    # 5. Slug ends with a truncation artifact
    last_seg = stem.rsplit("_", 1)[-1]
    if last_seg in _TRUNCATED_SUFFIXES:
        failures.append(f"filename stem ends with truncation artifact: '_{last_seg}'")

    return failures


def save_concept(
    content: str,
    *,
    image_path: Path | None = None,
    book_name: str = "",
) -> Path | None:
    """Save concept note to 04-Permanent/concepts/ and archive the source image.

    Args:
        content: Full concept note content (frontmatter + body).
        image_path: Source image to archive (optional).
        book_name: Book name for archive subfolder.

    Returns:
        Path to saved concept file, or None on failure.
    """
    if not content or len(content) < 100:
        _logger.error("Content too short to save")
        return None

    # Extract title for filename
    title = _extract_title(content)
    if not title or title == "untitled":
        _logger.error("Cannot determine title from content")
        return None

    # Generate filename
    filename = _title_to_filename(title)
    stem = Path(filename).stem

    # --- Quality Gate ---
    failures = _validate_quality(content, stem)
    if failures:
        reason = "; ".join(failures)
        _logger.warning(f"Quality gate REJECTED concept '{stem}': {reason}")
        log("quality", f"Rejected: {stem} — {reason}")
        return None

    concept_path = cfg.concepts_dir / filename

    # 1. Semantic Overlap Check for High Quality Concepts (Exclude Stubs)
    overlap = _find_semantic_overlap(content)
    if overlap:
        existing_stem, score = overlap
        # Arbitrate and try to merge
        merged_path = _arbitrate_and_merge(content, existing_stem)
        
        # SUBSUME: existing note fully covers new content — skip saving entirely
        if merged_path == _SUBSUME_SENTINEL:
            _logger.info(f"[Merger] SUBSUMED by '{existing_stem}'. Skipping save, archiving image only.")
            if image_path and image_path.exists():
                _archive_image(image_path, book_name)
            _log_subsume(title, existing_stem, score, image_path)
            log("subsume", f"Subsumed by: {existing_stem}.md (score={score:.3f})", source=str(image_path.name) if image_path else "")
            return None
        
        if merged_path:
            # Successfully merged! Save the source image if any
            if image_path and image_path.exists():
                fm = parse_frontmatter(content)
                page = str(fm.get("source_page", "")).strip()
                chapter = str(fm.get("source_chapter", "")).strip()
                if not chapter:
                    chapter = str(fm.get("ground_truth_chapter", "")).strip()
                
                # Archive image with existing_stem to link it properly
                new_image_name = _archive_image(image_path, book_name, page, chapter, concept_slug=existing_stem)
                
                # Append image callout to merged file
                try:
                    merged_content = merged_path.read_text(encoding="utf-8")
                    merged_content = f"{merged_content.rstrip()}\n\n> [!info]- 📷 Nguồn gốc\n> Ảnh chụp trang sách bổ sung (click để mở)\n> ![[{new_image_name}]]\n"
                    merged_path.write_text(merged_content, encoding="utf-8")
                except Exception as img_err:
                    _logger.warning(f"Failed to append image to merged file: {img_err}")
                    
            return merged_path

    # Avoid overwriting existing concepts, unless the existing file is an empty STUB
    is_stub = False
    if concept_path.exists():
        try:
            # Check if the existing concept is just an auto-generated stub
            existing_content = concept_path.read_text(encoding="utf-8")
            existing_fm = parse_frontmatter(existing_content)
            # If it's a stub or low confidence, we can safely overwrite (hydrate) it!
            if existing_fm.get("confidence") == "low" or existing_fm.get("source_type") == "stub":
                is_stub = True
                _logger.info(f"Existing file '{concept_path.name}' is a STUB. Hydrating it with new tri thức...")
        except Exception as e:
            _logger.warning(f"Failed to inspect existing file '{concept_path.name}': {e}")

    if concept_path.exists() and not is_stub:
        existing_stem = concept_path.stem
        suffix = 2
        while concept_path.exists():
            concept_path = cfg.concepts_dir / f"{existing_stem}_{suffix}.md"
            suffix += 1

    # Extract metadata for intelligent image renaming
    fm = parse_frontmatter(content)
    page = str(fm.get("source_page", "")).strip()
    chapter = str(fm.get("source_chapter", "")).strip()
    if not chapter:
        chapter = str(fm.get("ground_truth_chapter", "")).strip()

    # Archive source image and generate new structured name
    if image_path and image_path.exists():
        new_image_name = _archive_image(image_path, book_name, page, chapter, concept_slug=stem)
        # Automatically append the image block to the bottom of the concept note
        content = f"{content.rstrip()}\n\n> [!info]- 📷 Nguồn gốc\n> Ảnh chụp trang sách gốc (click để mở)\n> ![[{new_image_name}]]\n"

    # Save
    try:
        concept_path.parent.mkdir(parents=True, exist_ok=True)
        concept_path.write_text(content, encoding="utf-8")
        _logger.info(f"Saved: {concept_path.name}")
        log("ingest", f"Created concept: {concept_path.name}", source=str(image_path.name) if image_path else "")
        
        # If we had a semantic overlap candidate but kept them separate, perform cross-linking now
        if overlap:
            existing_stem, _ = overlap
            existing_path = cfg.concepts_dir / f"{existing_stem}.md"
            if existing_path.exists():
                _execute_cross_linking(concept_path, existing_path)
                
    except OSError as e:
        _logger.error(f"Failed to save concept: {e}")
        return None

    return concept_path


def _extract_title(content: str) -> str:
    """Extract title from frontmatter or H1."""
    fm = parse_frontmatter(content)
    if fm.get("title"):
        return fm["title"]
    h1 = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return h1.group(1).strip() if h1 else "untitled"


def _title_to_filename(title: str) -> str:
    """Convert Vietnamese title to snake_case filename.

    Args:
        title: Unicode title string.

    Returns:
        Filename like 'chien_luoc_nvidia.md'.
    """
    slug = normalize_stem(title)

    # Truncate to reasonable length
    if len(slug) > 80:
        slug = slug[:80].rsplit("_", 1)[0]

    return f"{slug}.md"


def _shorten_chapter(chapter_ref: str) -> str:
    """Extract a clean, short chapter identifier (e.g. 'ch7' from '[[Chương 7: Đối phó]]')."""
    clean = chapter_ref.replace("[[", "").replace("]]", "").strip()
    if not clean:
        return ""
    
    # Extract basename if it contains a path
    if "/" in clean:
        clean = clean.split("/")[-1]
    
    # Normalize first to remove Vietnamese diacritics
    norm = normalize_stem(clean)
    
    # Try to match 'chuong_X', 'chapter_X', or 'ch_X' / 'chX'
    match = re.search(r"(?:chuong|chapter|ch)_*(\d+)", norm, re.IGNORECASE)
    if match:
        return f"ch{match.group(1)}"
    
    # Fallback to normalized stem limited to 15 chars
    return norm[:15]


def _archive_image(
    image_path: Path,
    book_name: str = "",
    page: str = "",
    chapter: str = "",
    *,
    concept_slug: str = "",
) -> str:
    """Move processed image to 99-Archive/ and rename it structurally based on metadata.

    Supports Concept-Centric Naming v2.0 if concept_slug is provided:
    [concept_slug]_[short_chapter]_p[page].jpg
    
    Returns:
        The new filename of the archived image.
    """
    archive_dir = cfg.archive_dir
    safe_book_name = re.sub(r"[^\w\s-]", "", book_name).strip().replace(" ", "_")
    
    if safe_book_name:
        archive_dir = archive_dir / safe_book_name
    archive_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().strftime("%Y%m%d")

    if concept_slug:
        # Concept-Centric Naming v2.0
        short_ch = _shorten_chapter(chapter)
        c_part = f"_{short_ch}" if short_ch else ""
        p_part = f"_p{page}" if page else ""
        
        # Base structured name
        base_name = f"{concept_slug}{c_part}{p_part}"
        archive_name = f"{base_name}{image_path.suffix}"
        dest = archive_dir / archive_name
        
        # Collision prevention: append suffix if file exists
        suffix = 2
        while dest.exists():
            archive_name = f"{base_name}_{suffix}{image_path.suffix}"
            dest = archive_dir / archive_name
            suffix += 1
    else:
        # Fallback to old structured format
        c_part = f"_{normalize_stem(chapter)[:20]}" if chapter else ""
        p_part = f"_p{page}" if page else ""
        b_part = f"{safe_book_name}" if safe_book_name else "unknown_book"
        
        archive_name = f"{b_part}{c_part}{p_part}_{image_path.stem}_{today}{image_path.suffix}"
        dest = archive_dir / archive_name
        
        # Collision prevention
        suffix = 2
        base_name = dest.stem
        while dest.exists():
            archive_name = f"{base_name}_{suffix}{image_path.suffix}"
            dest = archive_dir / archive_name
            suffix += 1

    try:
        shutil.copy(str(image_path), str(dest))
        _logger.info(f"Archived (copied): {image_path.name} → {dest.name}")
    except OSError as e:
        _logger.warning(f"Archive failed: {e}")
        
    return archive_name


def archive_image(image_path: Path, book_name: str = "") -> str:
    """Public wrapper around _archive_image for external callers (e.g. batch processor).

    Archives an image without concept-level metadata (page/chapter unknown at call site).

    Args:
        image_path: Image to archive.
        book_name: Book identifier for archive subfolder.

    Returns:
        The new filename of the archived image.
    """
    return _archive_image(image_path, book_name=book_name)


def _get_embedding_via_gateway(text: str) -> list[float] | None:
    """Fetch L2-normalized embedding vector from AI Gateway."""
    if not cfg.gateway_url or not cfg.gateway_api_key:
        return None
    try:
        import requests
        import numpy as np
        url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gemini-embed",
            "input": [text[:2000]],
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        values = resp.json()["data"][0]["embedding"]
        emb = np.array(values, dtype=np.float32)
        norm = np.linalg.norm(emb)
        normalized = emb / norm if norm > 0 else emb
        return normalized.tolist()
    except Exception as e:
        _logger.warning(f"Failed to fetch embedding via Gateway in postproc: {e}")
        return None


def _find_semantic_overlap(new_text: str) -> tuple[str, float] | None:
    """Find if a concept has extremely high semantic similarity with an existing one.
    
    Returns:
        Tuple of (existing_stem, similarity_score) or None.
    """
    import numpy as np
    index_path = Path(__file__).parent.parent / "_embedding_index.npz"
    bak_path = index_path.with_suffix(".npz.bak")
    
    loaded_path = None
    if index_path.exists():
        loaded_path = index_path
    elif bak_path.exists():
        loaded_path = bak_path
        
    if not loaded_path:
        return None
        
    try:
        data = np.load(loaded_path, allow_pickle=True)
        if "embeddings" not in data or "sources" not in data:
            return None
            
        embeddings = data["embeddings"]
        sources = data["sources"].tolist()
        
        # Fetch query embedding
        query_emb = _get_embedding_via_gateway(new_text)
        if query_emb is None:
            return None
            
        # Fast dot product on pre-normalized vectors
        similarities = np.dot(embeddings, np.array(query_emb, dtype=np.float32))
        
        # Find best match
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        
        if best_score >= 0.88:
            return sources[best_idx], best_score
    except Exception as e:
        _logger.warning(f"Failed to scan semantic overlap: {e}")
        
    return None


def _arbitrate_and_merge(new_content: str, existing_stem: str) -> Path | None:
    """Arbitrates if we should merge or separate two highly similar concepts.
    
    If MERGE: Synthesizes merged note, overwrites existing file.
    If SEPARATE: Cross-links both notes.
    """
    import json
    existing_path = cfg.concepts_dir / f"{existing_stem}.md"
    if not existing_path.exists():
        return None
        
    try:
        existing_content = existing_path.read_text(encoding="utf-8")
        
        # Don't arbitrate if the existing file is an empty stub (hydration will handle this directly)
        existing_fm = parse_frontmatter(existing_content)
        if existing_fm.get("confidence") == "low" or existing_fm.get("source_type") == "stub":
            return None
            
        # Tier 1: Hook Count Gate — block merge if too many evidence hooks accumulated
        # Root cause of God Notes is unbounded quote stacking; 4 hooks = healthy upper bound
        hook_count = len(re.findall(r'^> "', existing_content, re.MULTILINE))
        if hook_count >= 4:
            _logger.info(f"[Merger] Hook Count Gate: '{existing_stem}' has {hook_count} evidence hooks (max 4). Force KEEP SEPARATE.")
            return None

        # Tier 2: Dynamic Size Limit — P95 × 1.3 (~7.7KB), derived from vault-wide analysis
        file_size = existing_path.stat().st_size
        if file_size > 7700:
            _logger.info(f"[Merger] Dynamic Size Limit: '{existing_stem}' ({file_size} bytes) exceeds limit (7,700 bytes). Force KEEP SEPARATE.")
            return None
            
        _logger.info(f"[Merger] Overlap detected between new concept and '{existing_stem}'. Consulting Arbitrator...")
        
        # 1. Arbitrate Prompt (3-way: MERGE / SEPARATE / SUBSUME)
        arbitrate_prompt = (
            f"Bạn là Nhà biên soạn Zettelkasten tối cao. Hai ghi chú tri thức chất lượng cao này có độ tương đồng ngữ nghĩa rất cao.\n\n"
            f"GHI CHÚ HIỆN CÓ ĐÃ LƯU:\n"
            f"```markdown\n{existing_content}\n```\n\n"
            f"GHI CHÚ MỚI CHUẨN BỊ LƯU:\n"
            f"```markdown\n{new_content}\n```\n\n"
            f"YÊU CẦU ĐÁNH GIÁ:\n"
            f"Hãy phân tích và quyết định xem chúng ta nên:\n"
            f"- Trả về 'MERGE' nếu: Chúng thảo luận chung một khái niệm học thuật cốt lõi duy nhất VÀ ghi chú mới bổ sung thông tin/trích dẫn/góc nhìn mà ghi chú cũ CHƯA CÓ.\n"
            f"- Trả về 'SEPARATE' nếu: Dù trùng lặp từ khóa, chúng bàn về hai khía cạnh, bối cảnh hoặc trường hợp hoàn toàn độc lập.\n"
            f"- Trả về 'SUBSUME' nếu: Ghi chú hiện có đã BAO HÀM TOÀN BỘ nội dung, ý tưởng và trích dẫn của ghi chú mới. Ghi chú mới KHÔNG bổ sung bất kỳ giá trị mới nào — tạo ra sẽ chỉ gây dư thừa.\n\n"
            f"QUY TẮC THIÊN VỊ QUAN TRỌNG:\n"
            f"- Ưu tiên chọn 'SEPARATE' nếu hai ghi chú chỉ trùng lặp từ khóa bề nổi nhưng khác bối cảnh thực tế.\n"
            f"- CHỈ chọn 'MERGE' khi chúng thực sự bàn về CÙNG MỘT KHÁI NIỆM HỌC THUẬT và ghi chú mới CÓ bổ sung giá trị.\n"
            f"- Chọn 'SUBSUME' khi ghi chú mới là TẬP CON hoàn toàn của ghi chú cũ — không có thông tin mới.\n\n"
            f"Trả lời CHÍNH XÁC duy nhất một từ: 'MERGE', 'SEPARATE', hoặc 'SUBSUME'."
        )
        
        decision = call_llm(arbitrate_prompt, task="synthesis", allowed_shorts=("MERGE", "SEPARATE", "SUBSUME"))
        if not decision:
            decision = "SEPARATE"
            
        decision = decision.strip().upper()
        
        if "SUBSUME" in decision:
            _logger.info(f"[Merger] Arbitrator DECIDED: SUBSUME — existing '{existing_stem}.md' fully covers new content. Dropping.")
            return _SUBSUME_SENTINEL
        
        if "MERGE" in decision:
            _logger.info(f"[Merger] Arbitrator DECIDED to MERGE into '{existing_stem}.md'. Synthesizing...")
            
            # 2. Synthesize Merge Prompt
            merge_prompt = (
                f"Bạn là Chuyên gia biên tập Zettelkasten v8.3. Hãy hợp nhất hai ghi chú tri thức này thành một ghi chú học thuật duy nhất có giá trị tích lũy cao.\n\n"
                f"GHI CHÚ 1:\n"
                f"```markdown\n{existing_content}\n```\n\n"
                f"GHI CHÚ 2:\n"
                f"```markdown\n{new_content}\n```\n\n"
                f"QUY TẮC HỢP NHẤT BẮT BUỘC:\n"
                f"1. FRONTMATTER YAML: Phải gộp tất cả các tags, sources (thành mảng), related links. Đặt trạng thái `status: evergreen`, `confidence: high`.\n"
                f"2. EVIDENCE HOOKS (Consolidation): Hãy kiểm tra và xếp chồng các Evidence Hooks lên đầu note (standalone blockquotes độc lập ở đầu tệp tin, ghi rõ Citation Line học thuật có wiki-link). TUYÊN BỐ QUAN TRỌNG: Nếu hai trích dẫn có ý nghĩa tương đương hoặc lặp ý, hãy cô đọng lại và chỉ giữ lại tối đa 3 trích dẫn tiếng Việt sắc bén nhất đại diện cho các nguồn/trang khác nhau. Tránh xếp chồng quá nhiều blockquotes gây loãng giá trị ghi chú.\n"
                f"3. CORE IDEA: Viết lại phần Core Idea phân tích tổng hợp chiều sâu, chỉ ra điểm giao thoa tri thức, phản biện hoặc bổ trợ giữa hai góc nhìn. Tuyệt đối không lặp lại trích dẫn.\n"
                f"4. GROUND TRUTH: Gom tất cả các đoạn văn tiếng Anh nguyên bản từ phần Ground Truth của cả hai ghi chú cũ.\n"
                f"5. REFERENCES: Gom tất cả các liên kết nguồn thô.\n\n"
                f"Trả về ĐÚNG tệp tin Markdown hoàn chỉnh bắt đầu từ '---' đến hết."
            )
            
            merged_body = call_llm(merge_prompt, task="synthesis")
            if merged_body and len(merged_body) > 200:
                # Robustly extract from the first YAML marker
                match = re.search(r"(---\n.*)", merged_body, re.DOTALL)
                if match:
                    merged_clean = match.group(1)
                    merged_clean = re.sub(r"\n```\s*$", "", merged_clean)
                    
                    from pipeline.synthesize import fix_section_ordering
                    merged_clean = fix_section_ordering(merged_clean)
                    
                    existing_path.write_text(merged_clean, encoding="utf-8")
                    _logger.info(f"[Merger] Synthesized merge saved successfully to '{existing_path.name}'.")
                    log("merge", f"Merged new concept into: {existing_path.name}")
                    return existing_path
                    
            _logger.warning("[Merger] Merge synthesis failed. Falling back to SEPARATE.")
            
        # 3. SEPARATE strategy (Cross-Linking)
        _logger.info(f"[Merger] Arbitrator DECIDED to KEEP SEPARATE.")
        return None
    except Exception as e:
        _logger.warning(f"[Merger] Exception during arbitration: {e}")
        return None


def _execute_cross_linking(path_a: Path, path_b: Path) -> None:
    """Create bidirectional links between A and B in their related YAML array and References."""
    for current_path, target_path in [(path_a, path_b), (path_b, path_a)]:
        if not current_path.exists() or not target_path.exists():
            continue
        try:
            content = current_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            body = extract_body(content)
            
            related = fm.get("related", [])
            target_stem = target_path.stem
            target_link = f"[[{target_stem}]]"
            
            # 1. Update related list
            if target_stem not in related:
                related.append(target_stem)
                fm["related"] = related
                
            # 2. Update References in body
            if target_link not in body:
                if "## References" in body:
                    body = body.replace("## References", f"## References\n- {target_link}")
                else:
                    body = f"{body.rstrip()}\n\n## References\n- {target_link}\n"
                    
            current_path.write_text(build_frontmatter(fm) + body, encoding="utf-8")
            _logger.info(f"[Merger] Cross-linked [[{target_stem}]] in {current_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to cross-link {current_path.name} to {target_path.name}: {e}")


def _log_subsume(
    new_title: str,
    existing_stem: str,
    score: float,
    image_path: Path | None,
) -> None:
    """Append a SUBSUME event to the weekly-reviewable journal.

    The journal file (.subsume_journal.jsonl) lives in the vault root and is
    read by sleep.py during weekly consolidation to produce a human-readable
    summary for review.

    Args:
        new_title: Title of the new concept that was subsumed.
        existing_stem: Stem of the existing concept that absorbed it.
        score: Cosine similarity score.
        image_path: Source image that triggered the concept.
    """
    journal_path = cfg.vault_root / ".subsume_journal.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "new_title": new_title,
        "existing_concept": f"{existing_stem}.md",
        "similarity_score": round(score, 4),
        "source_image": str(image_path.name) if image_path else None,
    }
    try:
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        _logger.warning(f"Failed to write subsume journal: {e}")
