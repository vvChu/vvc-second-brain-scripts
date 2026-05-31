"""VvC Second Brain — Post-Processing Stage (v8.7).

Save concept note, archive image (WebP compressed), trigger MOC rebuild.
Semantic Knowledge Merger logic extracted to pipeline/semantic_merger.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import date
from pathlib import Path

from core.config import cfg
from core.frontmatter import parse_frontmatter, normalize_stem
from core.log import log
from pipeline.semantic_merger import (
    SUBSUME_SENTINEL,
    find_semantic_overlap,
    arbitrate_and_merge,
    execute_cross_linking,
    log_subsume,
)

_logger = logging.getLogger("vvc.postproc")


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


def _is_decorative_image(name: str, path: Path) -> bool:
    """Check if an image is decorative based on filename keywords or small file size."""
    name_lower = name.lower()
    if any(k in name_lower for k in ["cover", "logo", "credit", "title_page"]):
        return True
    try:
        if path.exists() and path.stat().st_size < 5120:  # 5 KB
            return True
    except Exception:
        pass
    return False


def _find_md_dir(book_name: str) -> Path | None:
    """Find the extracted markdown corpus directory for the given book name."""
    books_dir = cfg.resources_books_dir
    if not books_dir.exists():
        return None
    try:
        return next(
            (d for d in books_dir.iterdir()
             if d.is_dir() and d.name.endswith("_MD") and book_name.lower() in d.name.lower()),
            None,
        )
    except OSError:
        return None


def _align_jit_images(content: str, book_name: str) -> str:
    """Scan original book corpus MD files to find and align crisp publisher diagrams."""
    if not book_name:
        return content

    # 1. Parse frontmatter
    fm = parse_frontmatter(content)
    gt_ch = fm.get("ground_truth_chapter")
    if not gt_ch:
        return content

    # Extract clean chapter stem from wiki-link
    chapter_stem = str(gt_ch).replace("[[", "").replace("]]", "").strip()
    if not chapter_stem:
        return content

    # OCR page and ground truth page for metadata resolution
    page = str(fm.get("source_page", "")).strip()
    if not page:
        page = str(fm.get("ground_truth_page", "")).strip()

    # 2. Find book MD corpus folder
    md_dir = _find_md_dir(book_name)

    if not md_dir or not md_dir.exists():
        _logger.debug(f"[JIT Image] MD directory not found for book: {book_name}")
        return content

    # 3. Locate chapter file
    chapter_file = md_dir / f"{chapter_stem}.md"
    if not chapter_file.exists():
        _logger.debug(f"[JIT Image] Chapter file '{chapter_stem}.md' not found in {md_dir}")
        return content

    try:
        chapter_text = chapter_file.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning(f"[JIT Image] Failed to read chapter file: {e}")
        return content

    # 4. Extract Ground Truth paragraphs from note content
    gt_section_match = re.search(
        r"## (?:📖|Ground Truth)[^\n]*\n+(.*?)(?:\n\n---|\n\n##|\Z)",
        content,
        re.DOTALL
    )
    if not gt_section_match:
        _logger.debug("[JIT Image] No Ground Truth section found in note content")
        return content

    gt_block = gt_section_match.group(1)
    paragraphs: list[str] = []
    current_para: list[str] = []
    
    for line in gt_block.splitlines():
        line = line.strip()
        if line.startswith(">"):
            clean_line = line.lstrip(">").strip()
            if clean_line:
                current_para.append(clean_line)
            else:
                if current_para:
                    paragraphs.append(" ".join(current_para))
                    current_para = []
        else:
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
    if current_para:
        paragraphs.append(" ".join(current_para))

    # 5. Search for paragraphs in the chapter file
    found_images: list[str] = []
    image_regex = re.compile(
        r'!\[\[([^\]]+\.(?:jpg|jpeg|png|webp))\]\]|!\[.*?\]\(([^\)]+\.(?:jpg|jpeg|png|webp))\)',
        re.IGNORECASE
    )

    for para in paragraphs:
        para_clean = re.sub(r"\s+", " ", para).strip()
        if not para_clean or len(para_clean) < 15:
            continue

        # Find position of this paragraph in chapter_text
        pos = chapter_text.find(para)
        if pos == -1:
            # Try search by prefix to be robust
            prefix = para_clean[:80].strip()
            pos = chapter_text.find(prefix)
            if pos == -1 and len(para_clean) > 150:
                middle = para_clean[len(para_clean)//2 : len(para_clean)//2 + 80].strip()
                pos = chapter_text.find(middle)

        if pos != -1:
            # Scan ±800 chars around the matched position
            start_win = max(0, pos - 800)
            end_win = min(len(chapter_text), pos + len(para) + 800)
            window = chapter_text[start_win:end_win]

            for m in image_regex.finditer(window):
                img_name = m.group(1) or m.group(2)
                if img_name:
                    img_name = img_name.strip()
                    if img_name not in found_images:
                        found_images.append(img_name)

    if not found_images:
        _logger.debug("[JIT Image] No book images found close to Ground Truth in chapter")
        return content

    # 6. Process, copy, and compress original images
    aligned_images: list[str] = []
    book_slug = normalize_stem(book_name)[:30].rstrip("_")
    short_ch = _shorten_chapter(chapter_stem)

    for img_name in found_images:
        original_img_path = md_dir / img_name
        if not original_img_path.exists():
            _logger.debug(f"[JIT Image] Original image file {img_name} not found in {md_dir}")
            continue

        # Filter decorative/tiny images
        if _is_decorative_image(img_name, original_img_path):
            _logger.debug(f"[JIT Image] Filtered decorative image: {img_name}")
            continue

        # Determine target name using Adaptive Naming Strategy
        orig_stem = normalize_stem(original_img_path.stem)
        book_words = [w for w in book_slug.split("_") if len(w) > 3]
        has_book_prefix = any(w in orig_stem for w in book_words)

        if has_book_prefix:
            dest_name = f"{orig_stem}.webp"
        else:
            parts = [book_slug]
            if short_ch:
                parts.append(short_ch)
            if page:
                parts.append(f"p{page}")
            parts.append(orig_stem)
            dest_name = f"{'_'.join(parts)}.webp"

        assets_dir = cfg.assets_dir / book_slug
        dest_path = assets_dir / dest_name

        # Compress to WebP or copy
        if not dest_path.exists():
            try:
                from PIL import Image as PILImage
                img = PILImage.open(original_img_path)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)
                assets_dir.mkdir(parents=True, exist_ok=True)
                img.save(dest_path, "WEBP", quality=80)
                _logger.info(f"[JIT Image] Compressed and saved original image: {original_img_path.name} -> {dest_path.name}")
            except Exception as e:
                _logger.warning(f"[JIT Image] WebP compression failed for {original_img_path.name}: {e}. Falling back to copy.")
                dest_path_raw = dest_path.with_suffix(original_img_path.suffix)
                try:
                    assets_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy(str(original_img_path), str(dest_path_raw))
                    _logger.info(f"[JIT Image] Copied original image (fallback): {original_img_path.name} -> {dest_path_raw.name}")
                    dest_name = dest_path_raw.name
                except Exception as copy_err:
                    _logger.warning(f"[JIT Image] Copy failed completely: {copy_err}")
                    continue

        aligned_images.append(dest_name)

    if not aligned_images:
        return content

    # 7. Embed aligned images right before ## 📖 Ground Truth section
    gt_heading_match = re.search(r"## (?:📖|Ground Truth)", content)
    if gt_heading_match:
        idx = gt_heading_match.start()
        embed_lines = []
        for dest_name in aligned_images:
            embed_syntax = f"![[{dest_name}]]"
            if embed_syntax not in content:
                embed_lines.append(f"\n{embed_syntax}\n")
        if embed_lines:
            embed_block = "".join(embed_lines)
            content = content[:idx].rstrip() + "\n" + embed_block + "\n" + content[idx:]
            _logger.info(f"[JIT Image] Successfully aligned {len(aligned_images)} original image(s) to concept note")

    return content


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

    # JIT Image Alignment
    if book_name:
        content = _align_jit_images(content, book_name)

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
    overlap = find_semantic_overlap(content)
    if overlap:
        existing_stem, score = overlap
        # Arbitrate and try to merge
        merged_path = arbitrate_and_merge(content, existing_stem)
        
        # SUBSUME: existing note fully covers new content — skip saving entirely
        if merged_path == SUBSUME_SENTINEL:
            _logger.info(f"[Merger] SUBSUMED by '{existing_stem}'. Skipping save, archiving image only.")
            if image_path and image_path.exists():
                _archive_image(image_path, book_name)
            log_subsume(title, existing_stem, score, image_path)
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
            
            # Hot-insert/update the merged file embedding in the index
            try:
                final_merged_content = merged_path.read_text(encoding="utf-8")
                _hot_insert_embedding(merged_path, final_merged_content)
            except Exception as hot_err:
                _logger.warning(f"Failed to hot-insert merged embedding: {hot_err}")
                
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
        
        # Hot-insert embedding to keep index in sync
        _hot_insert_embedding(concept_path, content)
        
        # If we had a semantic overlap candidate but kept them separate, perform cross-linking now
        if overlap:
            existing_stem, _ = overlap
            existing_path = cfg.concepts_dir / f"{existing_stem}.md"
            if existing_path.exists():
                execute_cross_linking(concept_path, existing_path)
                
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


def _get_source_hash(image_path: Path) -> str | None:
    """Compute MD5 hash of source image bytes for dedup."""
    try:
        return hashlib.md5(image_path.read_bytes()).hexdigest()
    except Exception:
        return None


def _load_manifest(archive_dir: Path) -> dict:
    """Load per-book archive manifest mapping source_hash -> archived filename."""
    manifest_path = archive_dir / ".archive_manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(archive_dir: Path, manifest: dict) -> None:
    """Persist archive manifest to disk."""
    manifest_path = archive_dir / ".archive_manifest.json"
    try:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        _logger.warning(f"Failed to save archive manifest: {e}")


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

    # Dedup check: if identical content already archived, return existing filename
    source_hash = _get_source_hash(image_path)
    if source_hash:
        manifest = _load_manifest(archive_dir)
        if source_hash in manifest:
            existing_name = manifest[source_hash]
            _logger.info(f"Dedup: {image_path.name} identical to existing '{existing_name}'. Skipping archive.")
            return existing_name

    today = date.today().strftime("%Y%m%d")

    if concept_slug:
        # Concept-Centric Naming v2.0
        short_ch = _shorten_chapter(chapter)
        c_part = f"_{short_ch}" if short_ch else ""
        p_part = f"_p{page}" if page else ""
        
        # Base structured name
        base_name = f"{concept_slug}{c_part}{p_part}"
        archive_name = f"{base_name}.webp"
        dest = archive_dir / archive_name
        
        # Collision prevention: append suffix if file exists
        suffix = 2
        while dest.exists():
            archive_name = f"{base_name}_{suffix}.webp"
            dest = archive_dir / archive_name
            suffix += 1
    else:
        # Fallback to old structured format
        c_part = f"_{normalize_stem(chapter)[:20]}" if chapter else ""
        p_part = f"_p{page}" if page else ""
        b_part = f"{safe_book_name}" if safe_book_name else "unknown_book"
        
        archive_name = f"{b_part}{c_part}{p_part}_{image_path.stem}_{today}.webp"
        dest = archive_dir / archive_name
        
        # Collision prevention
        suffix = 2
        base_name = dest.stem
        while dest.exists():
            archive_name = f"{base_name}_{suffix}.webp"
            dest = archive_dir / archive_name
            suffix += 1

    try:
        from PIL import Image as PILImage
        img = PILImage.open(image_path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)
        img.save(dest, "WEBP", quality=80)
        _logger.info(f"Archived (WebP): {image_path.name} → {dest.name}")
    except Exception as e:
        _logger.warning(f"WebP compression failed, falling back to raw copy: {e}")
        dest = dest.with_suffix(image_path.suffix)
        archive_name = dest.name
        try:
            shutil.copy(str(image_path), str(dest))
            _logger.info(f"Archived (raw copy fallback): {image_path.name} → {dest.name}")
        except OSError as copy_err:
            _logger.warning(f"Archive failed completely: {copy_err}")

    # Update manifest so future identical images are deduped
    if source_hash:
        manifest = _load_manifest(archive_dir)
        manifest[source_hash] = archive_name
        _save_manifest(archive_dir, manifest)

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


def _hot_insert_embedding(concept_path: Path, content: str) -> None:
    """Hot-insert/update a concept's embedding vector in _embedding_index.npz.

    Args:
        concept_path: Path to the saved concept note.
        content: Full text of the concept note.
    """
    import numpy as np
    import hashlib
    from pipeline.semantic_merger import get_embedding_via_gateway

    stem = concept_path.stem
    _logger.info(f"Hot-inserting embedding for concept: {stem}")

    # 1. Fetch query embedding
    query_emb = get_embedding_via_gateway(content)
    if query_emb is None:
        _logger.warning(f"Could not fetch embedding for hot-insert of '{stem}'")
        return

    # 2. Paths
    index_path = cfg.state_dir / "_embedding_index.npz"
    bak_path = index_path.with_suffix(".npz.bak")

    # 3. Load existing arrays
    existing_embeddings = []
    existing_texts = []
    existing_sources = []

    loaded_path = None
    if index_path.exists():
        loaded_path = index_path
    elif bak_path.exists():
        loaded_path = bak_path

    if loaded_path:
        try:
            data = np.load(loaded_path, allow_pickle=True)
            if "embeddings" in data and "texts" in data and "sources" in data:
                existing_embeddings = data["embeddings"].tolist()
                existing_texts = data["texts"].tolist()
                existing_sources = data["sources"].tolist()
        except Exception as e:
            _logger.warning(f"Failed to load existing index for hot-insert: {e}")

    # 4. Prepare new item metadata
    content_hash = f"hash:{hashlib.md5(content.encode('utf-8')).hexdigest()}"

    # 5. Insert or Update
    try:
        if stem in existing_sources:
            idx = existing_sources.index(stem)
            existing_embeddings[idx] = query_emb
            existing_texts[idx] = content_hash
            _logger.info(f"Updated existing entry in index for '{stem}'")
        else:
            existing_embeddings.append(query_emb)
            existing_texts.append(content_hash)
            existing_sources.append(stem)
            _logger.info(f"Appended new entry to index for '{stem}'")

        # 6. Save back to npz with backup restoration guard
        np.savez_compressed(
            index_path,
            embeddings=np.array(existing_embeddings, dtype=np.float32),
            texts=np.array(existing_texts, dtype=object),
            sources=np.array(existing_sources, dtype=object),
        )

        # Sync backup
        try:
            import shutil
            shutil.copy2(index_path, bak_path)
        except Exception as bak_err:
            _logger.warning(f"Failed to sync backup index during hot-insert: {bak_err}")

        _logger.info(f"Hot-insert successful: Index size is now {len(existing_sources)}")

    except Exception as save_err:
        _logger.error(f"Failed to save hot-inserted embedding index: {save_err}")

