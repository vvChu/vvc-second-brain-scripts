"""VvC Second Brain — Vault Document Utilities.

Provides high-performance, centralized functions for scanning and loading 
concepts, sources, and other vault documents with persistent mtime caching.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from core.config import cfg
from core.frontmatter import parse_frontmatter

_logger = logging.getLogger("vvc.vault")

_CACHE_VERSION = 1
_CONCEPTS_CACHE_FILE = cfg.state_dir / "_vault_concepts_cache.json"
_SOURCES_CACHE_FILE = cfg.state_dir / "_vault_sources_cache.json"


def _load_cache(cache_path: Path) -> dict[str, Any]:
    """Load JSON cache safely. Returns entries dict."""
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version") == _CACHE_VERSION:
            return data.get("entries", {})
    except Exception as e:
        _logger.warning(f"Failed to load cache from {cache_path.name}: {e}")
    return {}


def _save_cache(cache_path: Path, entries: dict[str, Any]) -> None:
    """Save JSON cache atomically via a temporary file."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".json.tmp")
        payload = {"version": _CACHE_VERSION, "entries": entries}
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)
    except Exception as e:
        _logger.warning(f"Failed to save cache to {cache_path.name}: {e}")


def _parse_concept_disk_entry(entry_path: str, stem: str, stat: os.stat_result) -> tuple[dict, dict] | None:
    """Read full concept file from disk and return (concept_data, cache_entry)."""
    try:
        content = Path(entry_path).read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        _logger.warning(f"Failed to read concept file {entry_path}: {e}")
        return None

    fm = parse_frontmatter(content)
    if not fm:
        return None

    raw_links = re.findall(r"\[\[([^\]|#\n]+)", content)
    fm["_stem"] = stem
    fm["_links"] = [l.strip() for l in raw_links if l.strip()]

    cache_data = {k: v for k, v in fm.items() if k != "_path"}
    cache_entry = {"mtime": stat.st_mtime, "size": stat.st_size, "data": cache_data}

    fm["_path"] = Path(entry_path)
    fm["_mtime"] = stat.st_mtime
    return fm, cache_entry


def scan_all_concepts() -> list[dict]:
    """Scan all academic concept notes in Permanent/concepts with mtime caching."""
    concepts: list[dict] = []
    if not cfg.concepts_dir.exists():
        _logger.warning(f"Concepts directory does not exist: {cfg.concepts_dir}")
        return concepts

    cache = _load_cache(_CONCEPTS_CACHE_FILE)
    new_cache: dict[str, Any] = {}
    dirty = False

    try:
        with os.scandir(cfg.concepts_dir) as it:
            for entry in it:
                if not entry.is_file() or not entry.name.endswith(".md") or entry.name.endswith(".excalidraw.md"):
                    continue
                stem = entry.name[:-3]
                try:
                    stat = entry.stat()
                except OSError:
                    continue

                cached = cache.get(stem)
                if cached and cached.get("mtime") == stat.st_mtime and cached.get("size") == stat.st_size:
                    data = dict(cached["data"])
                    data["_path"], data["_stem"], data["_mtime"] = Path(entry.path), stem, stat.st_mtime
                    concepts.append(data)
                    new_cache[stem] = cached
                    continue

                res = _parse_concept_disk_entry(entry.path, stem, stat)
                if res:
                    fm, cache_entry = res
                    new_cache[stem] = cache_entry
                    concepts.append(fm)
                    dirty = True
    except OSError as e:
        _logger.warning(f"Failed to scan concepts directory: {e}")

    if dirty or len(new_cache) != len(cache):
        _save_cache(_CONCEPTS_CACHE_FILE, new_cache)
    return concepts


def _parse_source_disk_entry(f: Path, stat: os.stat_result) -> tuple[dict, dict] | None:
    """Read full source file from disk and return (source_data, cache_entry)."""
    try:
        content = f.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        _logger.warning(f"Failed to read source file {f.name}: {e}")
        return None

    fm = parse_frontmatter(content)
    if not isinstance(fm, dict):
        fm = {}
    fm["_stem"] = f.stem
    cache_data = {k: v for k, v in fm.items() if k != "_path"}
    cache_entry = {"mtime": stat.st_mtime, "size": stat.st_size, "data": cache_data}
    fm["_path"] = f
    return fm, cache_entry


def scan_all_sources() -> list[dict]:
    """Scan all source notes in Permanent/sources recursively with mtime caching."""
    sources: list[dict] = []
    if not cfg.sources_dir.exists():
        _logger.warning(f"Sources directory does not exist: {cfg.sources_dir}")
        return sources

    cache = _load_cache(_SOURCES_CACHE_FILE)
    new_cache: dict[str, Any] = {}
    dirty = False

    for f in cfg.sources_dir.rglob("*.md"):
        try:
            rel_key = f.relative_to(cfg.sources_dir).as_posix()
            stat = f.stat()
        except OSError:
            continue

        cached = cache.get(rel_key)
        if cached and cached.get("mtime") == stat.st_mtime and cached.get("size") == stat.st_size:
            data = dict(cached["data"])
            data["_path"], data["_stem"] = f, f.stem
            sources.append(data)
            new_cache[rel_key] = cached
            continue

        res = _parse_source_disk_entry(f, stat)
        if res:
            fm, cache_entry = res
            new_cache[rel_key] = cache_entry
            sources.append(fm)
            dirty = True

    if dirty or len(new_cache) != len(cache):
        _save_cache(_SOURCES_CACHE_FILE, new_cache)
    return sources


def update_concept_cache(
    file_path: Path,
    frontmatter: dict | None = None,
    links: list[str] | None = None,
) -> dict | None:
    """Update or insert a single concept in the persistent cache."""
    if not file_path.exists():
        return None

    try:
        stat = file_path.stat()
        stem = file_path.stem

        if frontmatter is None or links is None:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            frontmatter = frontmatter or parse_frontmatter(content)
            if links is None:
                raw_links = re.findall(r"\[\[([^\]|#\n]+)", content)
                links = [l.strip() for l in raw_links if l.strip()]

        if not frontmatter:
            return None

        concept = dict(frontmatter)
        concept["_stem"], concept["_links"] = stem, links or []

        cache = _load_cache(_CONCEPTS_CACHE_FILE)
        cache[stem] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "data": {k: v for k, v in concept.items() if k != "_path"},
        }
        _save_cache(_CONCEPTS_CACHE_FILE, cache)

        concept["_path"] = file_path
        return concept
    except Exception as e:
        _logger.warning(f"Failed to update concept cache for {file_path.name}: {e}")
        return None


def invalidate_concept_cache(file_path_or_stem: Path | str) -> None:
    """Invalidate a concept from cache if deleted."""
    stem = file_path_or_stem.stem if isinstance(file_path_or_stem, Path) else file_path_or_stem
    if stem.endswith(".md"):
        stem = stem[:-3]
    cache = _load_cache(_CONCEPTS_CACHE_FILE)
    if stem in cache:
        del cache[stem]
        _save_cache(_CONCEPTS_CACHE_FILE, cache)
