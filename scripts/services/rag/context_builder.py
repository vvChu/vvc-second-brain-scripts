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


def resolve_explicit_references(query: str, max_docs: int = 2) -> list[dict]:
    """Extract explicit wikilinks [[stem]] from query and resolve them in priority order.

    Priority order:
        1. 04 - Permanent/topics/{stem}.md
        2. 04 - Permanent/sources/{stem}.md
        3. 04 - Permanent/concepts/{stem}.md
        4. 00 - Maps of Content/{stem}.md
        5. 00 - Maps of Content/sources/{stem}.md
        6. 00 - Maps of Content/domains/{stem}.md

    Args:
        query: Raw user query possibly containing [[stem]] or [[stem|alias]].
        max_docs: Maximum number of explicit documents to resolve (default: 2).

    Returns:
        List of dicts representing resolved documents (up to max_docs).
    """
    raw_stems = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", query)
    if not raw_stems:
        return []

    seen = set()
    unique_stems: list[str] = []
    for raw in raw_stems:
        s = raw.strip()
        if "#" in s:
            s = s.split("#")[0].strip()
        if s.endswith(".md"):
            s = s[:-3].strip()
        s = Path(s).name.strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            unique_stems.append(s)

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
        target_path: Path | None = None
        for d in search_dirs:
            candidate = d / f"{stem}.md"
            if candidate.is_file():
                target_path = candidate
                break
            candidate_lower = d / f"{stem.lower()}.md"
            if candidate_lower.is_file():
                target_path = candidate_lower
                break

        if target_path is None:
            continue

        try:
            raw_text = target_path.read_text(encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Failed to read explicit reference {target_path}: {e}")
            continue

        fm = parse_frontmatter(raw_text)
        title = fm.get("title") or stem
        summary = fm.get("summary", "")
        tags = fm.get("tags", [])

        body = extract_body(raw_text).strip()
        body_truncated = body[:3500].strip()

        resolved_docs.append({
            "source_file": target_path.name,
            "title": title,
            "summary": summary,
            "tags": tags,
            "body": body_truncated,
            "priority": "explicit_user_reference",
            "path": target_path,
        })

        if len(resolved_docs) >= max_docs:
            break

    return resolved_docs


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

    # 1. Resolve explicit references first (prioritized)
    try:
        explicit_docs = resolve_explicit_references(query, max_docs=2)
    except Exception as e:
        _logger.warning(f"Explicit reference resolution failed: {e}")
        explicit_docs = []

    for doc in explicit_docs:
        doc_id = len(context_parts) + 1
        rag_refs[doc_id] = (doc["source_file"], doc["title"])
        seen_files.add(doc["source_file"].lower())
        seen_stems.add(doc["path"].stem.lower())

        clean_ctx = f'<document id="{doc_id}" file="{doc["source_file"]}" title="{doc["title"]}" priority="explicit_user_reference">\n'
        if doc["summary"]:
            clean_ctx += f"TÓM TẮT: {doc['summary']}\n"

        tags = doc["tags"]
        if tags:
            tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
            clean_ctx += f"TAGS: {tags_str}\n"

        clean_ctx += f"NỘI DUNG:\n{doc['body']}\n</document>"
        context_parts.append(clean_ctx)

    # 2. Hybrid RAG Search
    if _rag_search is not None:
        try:
            # Clean wikilink markup from query for natural language / BM25 search
            clean_query = re.sub(
                r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]",
                lambda m: m.group(2) if m.group(2) else m.group(1),
                query,
            ).strip()

            results = _rag_search(clean_query, top_k=25)
            if results:
                for r in results:
                    src_file = r.source_file
                    src_stem = Path(src_file).stem
                    if src_file.lower() in seen_files or src_stem.lower() in seen_stems:
                        continue

                    fm = parse_frontmatter(r.text)
                    title = fm.get("title", src_file)
                    summary = fm.get("summary", "")

                    body = extract_body(r.text)

                    doc_id = len(context_parts) + 1
                    rag_refs[doc_id] = (src_file, title)
                    seen_files.add(src_file.lower())
                    seen_stems.add(src_stem.lower())

                    clean_ctx = f'<document id="{doc_id}" file="{src_file}" title="{title}">\n'
                    if summary:
                        clean_ctx += f"TÓM TẮT: {summary}\n"

                    tags = fm.get("tags", [])
                    if tags:
                        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
                        clean_ctx += f"TAGS: {tags_str}\n"

                    clean_ctx += f"NỘI DUNG:\n{body.strip()}\n</document>"
                    context_parts.append(clean_ctx)
        except Exception as e:
            _logger.warning(f"RAG search failed: {e}")

    if not context_parts:
        return "", {}

    return "\n---\n".join(context_parts), rag_refs


__all__ = [
    "build_rag_context",
    "resolve_explicit_references",
]
