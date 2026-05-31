"""VvC Second Brain — Vault Document Utilities.

Provides high-performance, centralized functions for scanning and loading 
concepts, sources, and other vault documents.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.config import cfg
from core.frontmatter import parse_frontmatter

_logger = logging.getLogger("vvc.vault")


def scan_all_concepts() -> list[dict]:
    """Scan all academic concept notes in Permanent/concepts.
    
    Skips non-markdown, empty, and Excalidraw plugin files (*.excalidraw.md).
    
    Returns:
        A list of parsed frontmatter dictionaries, each containing '_path' and '_stem'.
    """
    concepts = []
    if not cfg.concepts_dir.exists():
        _logger.warning(f"Concepts directory does not exist: {cfg.concepts_dir}")
        return concepts

    for f in cfg.concepts_dir.iterdir():
        if f.suffix != ".md" or f.name.endswith(".excalidraw.md"):
            continue
        try:
            with open(f, encoding="utf-8", errors="ignore") as file:
                content = file.read(4096)
            frontmatter = parse_frontmatter(content)
            if frontmatter:
                frontmatter["_path"] = f
                frontmatter["_stem"] = f.stem
                concepts.append(frontmatter)
        except OSError as e:
            _logger.warning(f"Failed to read concept file {f.name}: {e}")
            continue
            
    return concepts


def scan_all_sources() -> list[dict]:
    """Scan all source notes in Permanent/sources recursively.
    
    Scans both the top-level sources folder and subfolders like 'transcripts/'.
    
    Returns:
        A list of parsed frontmatter dictionaries, each containing '_path' and '_stem'.
    """
    sources = []
    if not cfg.sources_dir.exists():
        _logger.warning(f"Sources directory does not exist: {cfg.sources_dir}")
        return sources

    for f in cfg.sources_dir.rglob("*.md"):
        try:
            with open(f, encoding="utf-8", errors="ignore") as file:
                content = file.read(4096)
            frontmatter = parse_frontmatter(content)
            if frontmatter:
                frontmatter["_path"] = f
                frontmatter["_stem"] = f.stem
                sources.append(frontmatter)
        except OSError as e:
            _logger.warning(f"Failed to read source file {f.name}: {e}")
            continue
            
    return sources
