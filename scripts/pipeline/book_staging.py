"""VvC Second Brain — Book Ingestion Staging & Corpus Conversion.

Manages workspace creation, source note initialization, EPUB/PDF
corpus extraction, and TOC/macro-context synchronization.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import date
from pathlib import Path

from core.config import cfg
from core.frontmatter import build_frontmatter

try:
    from epub_convert import convert_epub as _convert_epub_fn
except ImportError:
    _convert_epub_fn = None  # type: ignore[assignment]

try:
    from pdf_convert import convert_pdf as _convert_pdf_fn
except ImportError:
    _convert_pdf_fn = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.book.staging")

__all__ = [
    "_normalize_book_name",
    "_create_workspace",
    "_create_source_note",
    "_convert_epub",
    "_convert_book_corpus",
    "_sync_toc_and_macro_context",
]


def _normalize_book_name(filename: str) -> str:
    """Convert book filename to workspace name."""
    return re.sub(r"[^a-zA-Z0-9À-ỹ]+", "_", Path(filename).stem).strip("_")


def _create_workspace(book_name: str, book_path: Path) -> Path:
    """Create a workspace folder in 05-Fleeting/ for photo drops."""
    workspace = cfg.fleeting_dir / book_name
    workspace.mkdir(parents=True, exist_ok=True)
    context_file = workspace / "_context.txt"
    if not context_file.exists():
        meta = (
            f"book_title: {book_path.stem}\nbook_file: {book_path.name}\n"
            f"date_added: {date.today().isoformat()}\nstatus: active\n"
            f"corpus_rel_path: 03 - Resources/books/{book_name}_MD\n"
            f"archive_rel_path: 99 - Archive/{book_name}\n"
        )
        context_file.write_text(meta, encoding="utf-8")
    return workspace


def _create_source_note(book_name: str, book_path: Path) -> Path:
    """Create a source summary note in 04-Permanent/sources/."""
    today = date.today().isoformat()
    source_path = cfg.sources_dir / f"{today}_{book_name.lower()}.md"
    if source_path.exists():
        return source_path
    title = book_path.stem.replace("_", " ").replace("-", " ")
    fm = build_frontmatter({
        "title": title, "author": "", "aliases": [title], "tags": ["knowledge", "type/source"],
        "type": "source", "date_created": today, "date_modified": today, "source": book_path.name,
        "source_type": book_path.suffix.lstrip("."), "summary": f"Source note for: {title}",
        "related": [], "confidence": "high",
    })
    body = (
        f"\n# {title}\n\n> Source summary pending ingestion.\n\n"
        f"## Metadata\n\n- File: `{book_path.name}`\n- Format: {book_path.suffix.upper()}\n- Added: {today}\n"
    )
    try:
        source_path.write_text(fm + body, encoding="utf-8")
        _logger.info(f"Source note created: {source_path.name}")
    except OSError as e:
        _logger.error(f"Failed to create source note: {e}")
    return source_path


def _convert_epub(book_path: Path, book_name: str) -> bool:
    """Convert EPUB to chunked markdown corpus."""
    out_dir = cfg.resources_books_dir / f"{book_name}_MD"
    if out_dir.exists() and any(out_dir.glob("*.md")):
        _logger.info(f"MD corpus already exists: {out_dir.name}")
        return True
    if _convert_epub_fn is not None:
        return _convert_epub_fn(book_path, out_dir)
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book, idx = epub.read_epub(str(book_path)), 0
        out_dir.mkdir(parents=True, exist_ok=True)
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            text = BeautifulSoup(item.get_content(), "html.parser").get_text(separator="\n", strip=True)
            if len(text) >= 100:
                name = f"{idx:02d}_{item.get_name().replace('/', '_').replace('.xhtml', '')}.md"
                (out_dir / name).write_text(text, encoding="utf-8")
                idx += 1
        _logger.info(f"EPUB extracted: {idx} chapters -> {out_dir.name}")
        return idx > 0
    except Exception as e:
        _logger.error(f"EPUB conversion failed: {e}")
        return False


def _convert_book_corpus(book_path: Path, book_name: str, workspace: Path) -> bool:
    """Convert book (EPUB or PDF) into chunked markdown corpus."""
    suffix = book_path.suffix.lower()
    if suffix == ".epub":
        return _convert_epub(book_path, book_name)
    if suffix == ".pdf":
        if _convert_pdf_fn:
            try:
                return _convert_pdf_fn(book_path, workspace_dir=workspace)
            except Exception as e:
                _logger.error(f"Failed to run convert_pdf: {e}")
        else:
            _logger.warning("pdf_convert module not available")
    return False


def _sync_toc_and_macro_context(book_name: str, workspace: Path) -> None:
    """Sync TOC template and generate book macro context."""
    toc_orig = cfg.resources_books_dir / f"{book_name}_MD" / "_toc_original.json"
    ws_toc = workspace / "_toc.json"
    if toc_orig.exists() and not ws_toc.exists():
        try:
            shutil.copy(str(toc_orig), str(ws_toc))
            _logger.info(f"Copied original TOC template: {workspace.name}/_toc.json")
        except OSError as e:
            _logger.error(f"Failed to copy original TOC template: {e}")
    try:
        from pipeline.map_reduce import get_or_create_book_context
        get_or_create_book_context(workspace)
        _logger.info(f"Generated <BOOK_CONTEXT> for {book_name}")
    except Exception as e:
        _logger.warning(f"Failed to generate <BOOK_CONTEXT> for {book_name}: {e}")
