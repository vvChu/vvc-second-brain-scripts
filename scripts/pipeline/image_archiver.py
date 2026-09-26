"""VvC Second Brain — Image Archiving Subsystem (v8.15.13).

Handles WebP compression, collision suffixing, dedup hashing via per-book manifests,
and Concept-Centric Naming v2.0 for archived images in 99-Archive/.
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
from core.frontmatter import normalize_stem

_logger = logging.getLogger("vvc.image_archiver")


def _shorten_chapter(chapter_ref: str) -> str:
    """Extract a clean, short chapter identifier (e.g. 'ch7' from '[[Chương 7: Đối phó]]')."""
    clean = chapter_ref.replace("[[", "").replace("]]", "").strip()
    if not clean:
        return ""
    if "/" in clean:
        clean = clean.split("/")[-1]
    norm = normalize_stem(clean)
    match = re.search(r"(?:chuong|chapter|ch)_*(\d+)", norm, re.IGNORECASE)
    if match:
        return f"ch{match.group(1)}"
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


def _resolve_archive_dest(
    archive_dir: Path,
    image_path: Path,
    safe_book_name: str,
    page: str,
    chapter: str,
    concept_slug: str,
) -> Path:
    """Calculate target destination path in archive with collision suffixing."""
    if concept_slug:
        short_ch = _shorten_chapter(chapter)
        c_part = f"_{short_ch}" if short_ch else ""
        p_part = f"_p{page}" if page else ""
        base = f"{concept_slug}{c_part}{p_part}"
    else:
        c_part = f"_{normalize_stem(chapter)[:20]}" if chapter else ""
        p_part = f"_p{page}" if page else ""
        b_part = safe_book_name or "unknown_book"
        today = date.today().strftime("%Y%m%d")
        base = f"{b_part}{c_part}{p_part}_{image_path.stem}_{today}"

    dest = archive_dir / f"{base}.webp"
    suffix = 2
    while dest.exists():
        dest = archive_dir / f"{base}_{suffix}.webp"
        suffix += 1
    return dest


def _compress_and_save_image(image_path: Path, dest: Path) -> Path:
    """Compress image to WebP with raw copy fallback on failure."""
    try:
        from PIL import Image as PILImage
        img = PILImage.open(image_path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)
        img.save(dest, "WEBP", quality=80)
        _logger.info(f"Archived (WebP): {image_path.name} → {dest.name}")
        return dest
    except Exception as e:
        _logger.warning(f"WebP compression failed, falling back to raw copy: {e}")
        fallback_dest = dest.with_suffix(image_path.suffix)
        try:
            shutil.copy(str(image_path), str(fallback_dest))
            _logger.info(f"Archived (raw copy fallback): {image_path.name} → {fallback_dest.name}")
        except OSError as copy_err:
            _logger.warning(f"Archive failed completely: {copy_err}")
        return fallback_dest


def _archive_image(
    image_path: Path,
    book_name: str = "",
    page: str = "",
    chapter: str = "",
    *,
    concept_slug: str = "",
) -> str:
    """Move processed image to 99-Archive/ and rename it structurally based on metadata."""
    archive_dir = cfg.archive_dir
    safe_book_name = re.sub(r"[^\w\s-]", "", book_name).strip().replace(" ", "_")
    if safe_book_name:
        archive_dir = archive_dir / safe_book_name
    archive_dir.mkdir(parents=True, exist_ok=True)

    source_hash = _get_source_hash(image_path)
    if source_hash:
        manifest = _load_manifest(archive_dir)
        if source_hash in manifest:
            existing = manifest[source_hash]
            _logger.info(f"Dedup: {image_path.name} identical to existing '{existing}'. Skipping archive.")
            return existing

    dest = _resolve_archive_dest(archive_dir, image_path, safe_book_name, page, chapter, concept_slug)
    actual_dest = _compress_and_save_image(image_path, dest)
    archive_name = actual_dest.name

    if source_hash:
        manifest = _load_manifest(archive_dir)
        manifest[source_hash] = archive_name
        _save_manifest(archive_dir, manifest)

    return archive_name


def archive_image(image_path: Path, book_name: str = "") -> str:
    """Public wrapper around _archive_image for external callers."""
    return _archive_image(image_path, book_name=book_name)
