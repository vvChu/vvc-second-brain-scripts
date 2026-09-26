"""VvC Second Brain — Post-Processing Stage (v8.7).

Save concept note, archive image (WebP compressed), trigger MOC rebuild.
Semantic Knowledge Merger logic extracted to pipeline/semantic_merger.py.
Image archiving logic extracted to pipeline/image_archiver.py.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.config import cfg
from core.file_lock import CrossProcessFileLock  # noqa: F401
from core.frontmatter import parse_frontmatter, normalize_stem
from core.log import log
from core.vector_store import VectorStore
from pipeline.book_assets import (
    find_book_md_dir,
    is_decorative_image,
    align_book_diagrams,
)
from pipeline.semantic_merger import (
    SUBSUME_SENTINEL,
    find_semantic_overlap,
    arbitrate_and_merge,
    execute_cross_linking,
    log_subsume,
)
from core.markdown_sanitizer import clean_wikilink_quotes
from pipeline.image_archiver import (
    _archive_image,
    archive_image,
    _shorten_chapter,
)

# Backward-compatible aliases for internal callers & tests
_find_md_dir = find_book_md_dir
_is_decorative_image = is_decorative_image
_align_jit_images = align_book_diagrams

_logger = logging.getLogger("vvc.postproc")

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


def _check_core_idea_copy(content: str) -> str | None:
    """Check if Core Idea blockquote is merely a copy of the title."""
    title_m = re.search(r"^title:\s*[^\n]+", content, re.MULTILINE)
    core_m = re.search(r"## Core Idea\n+> (.+)", content)
    if title_m and core_m:
        clean = lambda s: re.sub(r"[^\w ]", "", s.lower())[:40]
        if clean(title_m.group(0))[:30] == clean(core_m.group(1))[:30]:
            return "Core Idea blockquote is a copy of the title — no real analysis"
    return None


def _check_summary_hook_overlap(content: str) -> str | None:
    """Check if YAML summary duplicates or overlaps heavily with Evidence Hook."""
    summary_m = re.search(r"^summary:\s*['\"]?(.+?)['\"]?\s*$", content, re.MULTILINE)
    hook_m = re.search(r"^>\s*\"([^\"]+)\"", content, re.MULTILINE)
    if not (summary_m and hook_m):
        return None

    clean = lambda s: re.sub(r"[^\w ]", "", s.lower()).strip()
    sum_clean, hook_clean = clean(summary_m.group(1)), clean(hook_m.group(1))
    if not (sum_clean and hook_clean):
        return None

    if sum_clean in hook_clean or hook_clean in sum_clean:
        return "YAML summary duplicates or overlaps with the Evidence Hook blockquote"

    sum_words, hook_words = set(sum_clean.split()), set(hook_clean.split())
    if sum_words and hook_words:
        if (len(sum_words & hook_words) / max(1, len(sum_words))) > 0.85:
            return "YAML summary duplicates or overlaps with the Evidence Hook blockquote"
    return None


def _validate_quality(content: str, stem: str) -> list[str]:
    """Run pre-save quality checks on a concept note.

    Args:
        content: Full note content (frontmatter + body).
        stem: Proposed filename stem (without extension).

    Returns:
        List of failure reasons (empty = pass).
    """
    failures: list[str] = []

    for marker in _TEMPLATE_MARKERS:
        if marker in content:
            failures.append(f"template placeholder found: '{marker[:40]}'")
            break

    if "## Core Idea" not in content:
        failures.append("missing '## Core Idea' section")

    if copy_err := _check_core_idea_copy(content):
        failures.append(copy_err)

    fm_end = content.find("\n---\n", 3)
    body = content[fm_end + 4:].strip() if fm_end > 0 else content.strip()
    if len(body) < 300:
        failures.append(f"body too short ({len(body)} chars, minimum 300)")

    last_seg = stem.rsplit("_", 1)[-1]
    if last_seg in _TRUNCATED_SUFFIXES:
        failures.append(f"filename stem ends with truncation artifact: '_{last_seg}'")

    if overlap_err := _check_summary_hook_overlap(content):
        failures.append(overlap_err)

    return failures


def _handle_overlap_and_merge(
    content: str,
    overlap: tuple[str, float],
    image_path: Path | None,
    book_name: str,
    title: str,
) -> tuple[bool, Path | None]:
    """Handle semantic overlap arbitration, subsumption or merging.

    Returns:
        (handled, result_path): handled is True if subsumed or merged.
    """
    existing_stem, score = overlap
    merged_path = arbitrate_and_merge(content, existing_stem)
    if merged_path == SUBSUME_SENTINEL:
        _logger.info(f"[Merger] SUBSUMED by '{existing_stem}'. Skipping save, archiving image only.")
        if image_path and image_path.exists():
            _archive_image(image_path, book_name)
        log_subsume(title, existing_stem, score, image_path)
        log("subsume", f"Subsumed by: {existing_stem}.md (score={score:.3f})", source=str(image_path.name) if image_path else "")
        return True, None

    if not merged_path:
        return False, None

    if image_path and image_path.exists():
        fm = parse_frontmatter(content)
        page = str(fm.get("source_page", "")).strip()
        ch = str(fm.get("source_chapter", "")).strip() or str(fm.get("ground_truth_chapter", "")).strip()
        new_img = _archive_image(image_path, book_name, page, ch, concept_slug=existing_stem)
        try:
            cur = merged_path.read_text(encoding="utf-8").rstrip()
            merged_path.write_text(f"{cur}\n\n> [!info]- 📷 Nguồn gốc\n> Ảnh chụp trang sách bổ sung (click để mở)\n> ![[{new_img}]]\n", encoding="utf-8")
        except Exception as img_err:
            _logger.warning(f"Failed to append image to merged file: {img_err}")

    try:
        _hot_insert_embedding(merged_path, merged_path.read_text(encoding="utf-8"))
    except Exception as hot_err:
        _logger.warning(f"Failed to hot-insert merged embedding: {hot_err}")

    return True, merged_path


def _resolve_concept_path(filename: str) -> Path:
    """Determine final file path, allowing overwrite if existing file is a STUB."""
    concept_path = cfg.concepts_dir / filename
    if not concept_path.exists():
        return concept_path

    try:
        existing_fm = parse_frontmatter(concept_path.read_text(encoding="utf-8"))
        if existing_fm.get("confidence") == "low" or existing_fm.get("source_type") == "stub":
            _logger.info(f"Existing file '{concept_path.name}' is a STUB. Hydrating it with new tri thức...")
            return concept_path
    except Exception as e:
        _logger.warning(f"Failed to inspect existing file '{concept_path.name}': {e}")

    existing_stem, suffix = concept_path.stem, 2
    while concept_path.exists():
        concept_path = cfg.concepts_dir / f"{existing_stem}_{suffix}.md"
        suffix += 1
    return concept_path


def _write_concept_and_link(
    concept_path: Path,
    content: str,
    image_name: str | None,
    overlap: tuple[str, float] | None,
) -> Path | None:
    """Write concept file to disk, hot-insert embedding, and perform cross-linking."""
    try:
        concept_path.parent.mkdir(parents=True, exist_ok=True)
        concept_path.write_text(content, encoding="utf-8")
        _logger.info(f"Saved: {concept_path.name}")
        log("ingest", f"Created concept: {concept_path.name}", source=image_name or "")
        _hot_insert_embedding(concept_path, content)

        if overlap:
            existing_path = cfg.concepts_dir / f"{overlap[0]}.md"
            if existing_path.exists():
                execute_cross_linking(concept_path, existing_path)
        return concept_path
    except OSError as e:
        _logger.error(f"Failed to save concept: {e}")
        return None


def _attach_source_image(
    content: str,
    image_path: Path | None,
    book_name: str,
    stem: str,
) -> str:
    """Archive source image and append origin callout to concept content."""
    if not (image_path and image_path.exists()):
        return content
    fm = parse_frontmatter(content)
    page = str(fm.get("source_page", "")).strip()
    chapter = str(fm.get("source_chapter", "")).strip() or str(fm.get("ground_truth_chapter", "")).strip()
    new_img = _archive_image(image_path, book_name, page, chapter, concept_slug=stem)
    return f"{content.rstrip()}\n\n> [!info]- 📷 Nguồn gốc\n> Ảnh chụp trang sách gốc (click để mở)\n> ![[{new_img}]]\n"


def save_concept(
    content: str,
    *,
    image_path: Path | None = None,
    book_name: str = "",
) -> Path | None:
    """Save concept note to 04-Permanent/concepts/ and archive the source image."""
    if not content or len(content) < 100:
        _logger.error("Content too short to save")
        return None

    content = clean_wikilink_quotes(content)
    if book_name:
        content = _align_jit_images(content, book_name)

    title = _extract_title(content)
    if not title or title == "untitled":
        _logger.error("Cannot determine title from content")
        return None

    filename = _title_to_filename(title)
    stem = Path(filename).stem

    failures = _validate_quality(content, stem)
    if failures:
        reason = "; ".join(failures)
        _logger.warning(f"Quality gate REJECTED concept '{stem}': {reason}")
        log("quality", f"Rejected: {stem} — {reason}")
        return None

    overlap = find_semantic_overlap(content)
    if overlap:
        handled, merged_res = _handle_overlap_and_merge(content, overlap, image_path, book_name, title)
        if handled:
            return merged_res

    concept_path = _resolve_concept_path(filename)
    content = _attach_source_image(content, image_path, book_name, stem)
    image_name = str(image_path.name) if image_path else None
    return _write_concept_and_link(concept_path, content, image_name, overlap)


def _extract_title(content: str) -> str:
    """Extract title from frontmatter or H1."""
    fm = parse_frontmatter(content)
    if fm.get("title"):
        return fm["title"]
    h1 = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return h1.group(1).strip() if h1 else "untitled"


def _title_to_filename(title: str) -> str:
    """Convert Vietnamese title to snake_case filename."""
    slug = normalize_stem(title)
    if len(slug) > 80:
        slug = slug[:80].rsplit("_", 1)[0]
    return f"{slug}.md"


def _hot_insert_embedding(concept_path: Path, content: str) -> None:
    """Hot-insert/update vector embedding of a concept note into VectorStore."""
    VectorStore.get_instance().hot_insert(concept_path.stem, content)
