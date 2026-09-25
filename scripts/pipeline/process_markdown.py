"""VvC Second Brain — Markdown Processing Stage (v7.1).

Processes long-form raw text (e.g., YouTube Transcripts, Web Clips) 
from 05 - Fleeting/ and synthesizes them into atomic Zettelkasten concepts.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import date
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.vector_store import VectorStore
from pipeline.post_process import save_concept

_logger = logging.getLogger("vvc.md_process")

from core.prompts.pipeline import MARKDOWN_SYNTHESIS as _MARKDOWN_PROMPT  # noqa: E402

def process_markdown_file(file_path: Path) -> bool:
    """Read a raw markdown file, synthesize concepts, and archive the file."""
    _logger.info(f"Processing Markdown: {file_path.name}")
    log("ingest", f"Markdown Processing started: {file_path.name}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.error(f"Failed to read file {file_path}: {e}")
        return False

    if len(content.strip()) < 50:
        _logger.warning("File too short, skipping.")
        return False

    today = date.today().isoformat()
    source_name = file_path.stem.replace("_", " ").title()

    prompt = _MARKDOWN_PROMPT.format(
        content=content,
        source_name=source_name,
        source_ref=file_path.stem,
        today=today,
    )

    # Note: For large contexts, this might use gemini-3.1-pro-high if configured
    result = call_llm(prompt, task="synthesis")
    
    if not result:
        log("error", "Markdown synthesis failed", source=file_path.name)
        _logger.error("Synthesis failed for markdown file")
        return False

    # Debug: Save raw LLM output
    try:
        (Path(__file__).parent.parent / "scratch" / "raw_markdown_synth.md").write_text(result, encoding="utf-8")
    except Exception:
        pass

    concepts = result.split("===CONCEPT_SEPARATOR===")
    saved_count = 0
    saved_paths: list[Path] = []

    with VectorStore.get_instance().batch():
        for concept in concepts:
            concept = concept.strip()
            if len(concept) < 100:
                continue

            # Strip markdown fences
            concept = re.sub(r"^```(?:markdown|md)?\s*\n", "", concept)
            concept = re.sub(r"\n```\s*$", "", concept)

            if not concept.startswith("---"):
                continue

            saved_path = save_concept(concept)
            if saved_path:
                saved_count += 1
                saved_paths.append(saved_path)

    log("synth", f"Created {saved_count} concepts from {file_path.name}")
    _logger.info(f"Created {saved_count} concepts from {file_path.name}")

    if saved_count > 0:
        _archive_file(file_path)
        # Trigger MOC rebuild incrementally
        try:
            from wiki_maintain import rebuild_incremental
            for sp in saved_paths:
                rebuild_incremental(sp)
        except ImportError:
            pass
        return True

    return False

def _archive_file(file_path: Path) -> None:
    """Move processed file to 99 - Archive/web_clips/"""
    archive_dir = cfg.archive_dir / "web_clips"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / file_path.name
    
    try:
        if dest.exists():
            dest.unlink()
        shutil.move(str(file_path), str(dest))
        _logger.info(f"Archived {file_path.name} to {archive_dir}")
    except OSError as e:
        _logger.error(f"Failed to archive {file_path}: {e}")
