"""VvC Second Brain — RAG Context Builder.

Searches vault and formats context for LLMs.
"""

import logging
import re
from core.frontmatter import parse_frontmatter

try:
    from services.rag_search import search as _rag_search
except ImportError:
    _rag_search = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.rag_builder")

def build_rag_context(query: str) -> tuple[str, dict[int, tuple[str, str]]]:
    """Search vault for relevant context using RAG.
    Returns (formatted_context_string, dictionary_of_refs).
    """
    if _rag_search is None:
        return "", {}
    try:
        results = _rag_search(query, top_k=25)
        if not results:
            return "", {}
        context_parts = []
        rag_refs = {}
        for r in results:
            fm = parse_frontmatter(r.text)
            title = fm.get("title", r.source_file)
            summary = fm.get("summary", "")
            
            # Clean body: remove YAML block
            body = re.sub(r"^---\n.*?\n---\n", "", r.text, flags=re.DOTALL)
            
            doc_id = len(context_parts) + 1
            rag_refs[doc_id] = (r.source_file, title)
            
            # Format clean context with XML tags for better LLM "Lost in the middle" recall
            clean_ctx = f'<document id="{doc_id}" file="{r.source_file}" title="{title}">\n'
            if summary:
                clean_ctx += f"TÓM TẮT: {summary}\n"
            
            tags = fm.get("tags", [])
            if tags:
                if isinstance(tags, list):
                    tags_str = ", ".join(tags)
                else:
                    tags_str = str(tags)
                clean_ctx += f"TAGS: {tags_str}\n"
                
            clean_ctx += f"NỘI DUNG:\n{body.strip()}\n</document>"
            context_parts.append(clean_ctx)
        return "\n---\n".join(context_parts), rag_refs
    except Exception as e:
        _logger.warning(f"RAG search failed: {e}")
        return "", {}
