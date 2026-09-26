"""VvC Second Brain — RAG Context Builder.

Searches vault and formats context for LLMs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from core.config import cfg
from core.frontmatter import parse_frontmatter, extract_body

from .hybrid_search import search as _rag_search

_logger = logging.getLogger("vvc.rag.context_builder")


def _extract_query_wikilink_stems(query: str) -> list[str]:
    """Extract unique cleaned stems from [[stem]] or [[stem|alias]] in query."""
    raw_stems = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", query)
    seen: set[str] = set()
    unique: list[str] = []
    for raw in raw_stems:
        s = raw.strip()
        if "#" in s:
            s = s.split("#")[0].strip()
        if s.endswith(".md"):
            s = s[:-3].strip()
        s = Path(s).name.strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            unique.append(s)
    return unique


def _find_stem_file(stem: str, search_dirs: list[Path]) -> Path | None:
    """Find existing file for stem in search directories in priority order."""
    for d in search_dirs:
        candidate = d / f"{stem}.md"
        if candidate.is_file():
            return candidate
        candidate_lower = d / f"{stem.lower()}.md"
        if candidate_lower.is_file():
            return candidate_lower
    return None


def _load_explicit_doc(target_path: Path, stem: str) -> dict | None:
    """Read target markdown file and extract structured document metadata."""
    try:
        raw_text = target_path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning(f"Failed to read explicit reference {target_path}: {e}")
        return None
    fm = parse_frontmatter(raw_text)
    return {
        "source_file": target_path.name,
        "title": fm.get("title") or stem,
        "summary": fm.get("summary", ""),
        "tags": fm.get("tags", []),
        "body": extract_body(raw_text).strip()[:3500].strip(),
        "priority": "explicit_user_reference",
        "path": target_path,
    }


def resolve_explicit_references(query: str, max_docs: int = 2) -> list[dict]:
    """Extract explicit wikilinks [[stem]] from query and resolve them in priority order.

    Priority order:
        1. 04 - Permanent/topics/{stem}.md
        2. 04 - Permanent/sources/{stem}.md
        3. 04 - Permanent/concepts/{stem}.md
        4. 00 - Maps of Content/{stem}.md
        5. 00 - Maps of Content/sources/{stem}.md
        6. 00 - Maps of Content/domains/{stem}.md
    """
    unique_stems = _extract_query_wikilink_stems(query)
    if not unique_stems:
        return []

    vault_root = cfg.vault_root
    search_dirs = [
        vault_root / "04 - Permanent" / "topics",
        vault_root / "04 - Permanent" / "sources",
        vault_root / "04 - Permanent" / "concepts",
        vault_root / "00 - Maps of Content",
        vault_root / "00 - Maps of Content" / "sources",
        vault_root / "00 - Maps of Content" / "domains",
    ]

    resolved_docs: list[dict] = []
    for stem in unique_stems:
        target_path = _find_stem_file(stem, search_dirs)
        if target_path is None:
            continue

        doc = _load_explicit_doc(target_path, stem)
        if doc:
            resolved_docs.append(doc)
            if len(resolved_docs) >= max_docs:
                break

    return resolved_docs


def _format_doc_xml(
    doc_id: int, file_name: str, title: str, summary: str, tags: Any, body: str, priority: str = ""
) -> str:
    """Format single document into canonical XML tags for RAG context."""
    pfx = f' priority="{priority}"' if priority else ""
    lines = [f'<document id="{doc_id}" file="{file_name}" title="{title}"{pfx}>\n']
    if summary:
        lines.append(f"TÓM TẮT: {summary}\n")
    if tags:
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        lines.append(f"TAGS: {tags_str}\n")
    lines.append(f"NỘI DUNG:\n{body.strip()}\n</document>")
    return "".join(lines)


def _append_explicit_docs(
    explicit_docs: list[dict],
    context_parts: list[str],
    rag_refs: dict[int, tuple[str, str]],
    seen_files: set[str],
    seen_stems: set[str],
) -> None:
    """Format and append explicit user references to context."""
    for doc in explicit_docs:
        doc_id = len(context_parts) + 1
        rag_refs[doc_id] = (doc["source_file"], doc["title"])
        seen_files.add(doc["source_file"].lower())
        seen_stems.add(doc["path"].stem.lower())
        context_parts.append(
            _format_doc_xml(
                doc_id,
                doc["source_file"],
                doc["title"],
                doc["summary"],
                doc["tags"],
                doc["body"],
                priority="explicit_user_reference",
            )
        )


def _append_search_results(
    results: list[Any],
    context_parts: list[str],
    rag_refs: dict[int, tuple[str, str]],
    seen_files: set[str],
    seen_stems: set[str],
) -> None:
    """Format and append hybrid search results to context."""
    for r in results:
        src_file = r.source_file
        src_stem = Path(src_file).stem
        if src_file.lower() in seen_files or src_stem.lower() in seen_stems:
            continue

        fm = parse_frontmatter(r.text)
        title = fm.get("title", src_file)
        doc_id = len(context_parts) + 1
        rag_refs[doc_id] = (src_file, title)
        seen_files.add(src_file.lower())
        seen_stems.add(src_stem.lower())
        context_parts.append(
            _format_doc_xml(
                doc_id,
                src_file,
                title,
                fm.get("summary", ""),
                fm.get("tags", []),
                extract_body(r.text),
            )
        )


def build_rag_context(query: str) -> tuple[str, dict[int, tuple[str, str]]]:
    """Search vault for relevant context using RAG and explicit references.

    Extracts up to 2 explicit wikilinks [[stem]] at the top of context,
    cleans query for hybrid search, and deduplicates.

    Returns:
        (formatted_context_string, dictionary_of_refs).
    """
    context_parts: list[str] = []
    rag_refs: dict[int, tuple[str, str]] = {}
    seen_files: set[str] = set()
    seen_stems: set[str] = set()

    try:
        explicit_docs = resolve_explicit_references(query, max_docs=2)
    except Exception as e:
        _logger.warning(f"Explicit reference resolution failed: {e}")
        explicit_docs = []
    _append_explicit_docs(explicit_docs, context_parts, rag_refs, seen_files, seen_stems)

    if _rag_search is not None:
        try:
            clean_query = re.sub(
                r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]",
                lambda m: m.group(2) if m.group(2) else m.group(1),
                query,
            ).strip()
            results = _rag_search(clean_query, top_k=25)
            if results:
                _append_search_results(results, context_parts, rag_refs, seen_files, seen_stems)
        except Exception as e:
            _logger.warning(f"RAG search failed: {e}")

    if not context_parts:
        return "", {}

    return "\n---\n".join(context_parts), rag_refs


__all__ = [
    "build_rag_context",
    "resolve_explicit_references",
]
