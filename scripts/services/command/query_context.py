"""VvC Second Brain — Command Query Context Engineering.

Assembles multi-source context for user queries in Command.md:
- JIT live external URL extraction and resilient fetching (with timeout protection).
- Multi-turn conversation history continuity detection and extraction.
- Vault RAG hybrid retrieval fusion.
"""

from __future__ import annotations

import concurrent.futures
import html
import inspect
import logging
import re

from services.rag import build_rag_context

_logger = logging.getLogger("vvc.command.query_context")


# --- JIT URL Extraction & Fetching ---


def _extract_clean_urls(clean_query: str, max_urls: int = 5) -> list[str]:
    """Extract and deduplicate up to max_urls clean HTTP/HTTPS URLs from query.

    Args:
        clean_query: User query string.
        max_urls: Maximum number of unique URLs to return.

    Returns:
        List of cleaned, unique URL strings.
    """
    urls = re.findall(r"https?://[^\s)\]]+", clean_query)
    if not urls:
        return []

    seen: set[str] = set()
    unique_urls: list[str] = []
    for u in urls:
        clean_u = u.rstrip(".,;:\"'>")
        if clean_u.endswith(")") and clean_u.count("(") < clean_u.count(")"):
            clean_u = clean_u.rstrip(")")
        if clean_u and clean_u not in seen:
            seen.add(clean_u)
            unique_urls.append(clean_u)

    return unique_urls[:max_urls]


def _fetch_url_with_timeout(url: str, timeout: float = 10.0) -> str:
    """Fetch URL text safely within a specified timeout limit.

    Args:
        url: Web URL to fetch.
        timeout: Maximum seconds to wait before timing out.

    Returns:
        Fetched text content, or empty string on failure or timeout.
    """
    from services.url_fetcher import fetch_url

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        try:
            sig = inspect.signature(fetch_url)
            accepts_transcribe = "transcribe" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except Exception:
            accepts_transcribe = False

        if accepts_transcribe:
            future = executor.submit(fetch_url, url, transcribe=False)
        else:
            future = executor.submit(fetch_url, url)

        try:
            return future.result(timeout=timeout) or ""
        except concurrent.futures.TimeoutError:
            _logger.warning(f"JIT URL fetch timed out (>{timeout}s) for {url}")
            return ""


def _resolve_url_title(url: str, text: str) -> str:
    """Resolve article title from markdown heading or fetch_url_title fallback.

    Args:
        url: URL of the target page.
        text: Extracted page text.

    Returns:
        Resolved title string, or original url if unresolved.
    """
    heading_match = re.search(r"^#\s+(.+)$", text.strip(), re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    try:
        from services.url_fetcher import fetch_url_title

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as t_executor:
            t_future = t_executor.submit(fetch_url_title, url)
            try:
                title = t_future.result(timeout=3.0) or ""
                if title:
                    return title
            except (concurrent.futures.TimeoutError, Exception):
                pass
    except Exception:
        pass

    return url


def _format_url_xml_block(url: str, title: str, text: str) -> str:
    """Format single URL content into safe XML context block with truncation.

    Args:
        url: Source URL.
        title: Extracted page title.
        text: Raw page text.

    Returns:
        XML formatted context block.
    """
    stripped_text = text.strip()
    if len(stripped_text) > 200_000:
        try:
            from core.text_chunker import map_reduce_summarize

            processed_text = map_reduce_summarize(stripped_text, max_chars=200_000)
        except Exception as e:
            _logger.warning(f"Map-Reduce summarization failed for {url}: {e}")
            processed_text = stripped_text[:4000]
    else:
        processed_text = stripped_text[:4000]

    safe_title = html.escape(title, quote=True)
    safe_url = html.escape(url, quote=True)
    return (
        f'<external_web_source url="{safe_url}" title="{safe_title}">\n'
        f"{processed_text}\n"
        f"</external_web_source>"
    )


def extract_and_fetch_urls(clean_query: str) -> tuple[str, list[str]]:
    """Detect HTTP/HTTPS URLs in query, fetch content via url_fetcher, and format as XML context.

    Args:
        clean_query: The cleaned user query text.

    Returns:
        Tuple of (formatted_xml_context, list_of_fetched_urls).
    """
    unique_urls = _extract_clean_urls(clean_query, max_urls=5)
    if not unique_urls:
        return "", []

    xml_blocks: list[str] = []
    fetched_urls: list[str] = []

    for url in unique_urls:
        try:
            text = _fetch_url_with_timeout(url, timeout=10.0)
            if not text or not text.strip():
                continue

            title = _resolve_url_title(url, text)
            xml_blocks.append(_format_url_xml_block(url, title, text))
            fetched_urls.append(url)
        except Exception as e:
            _logger.warning(f"Failed to fetch JIT URL {url}: {e}")
            continue

    return "\n\n".join(xml_blocks), fetched_urls


# --- Multi-turn Conversation & History ---


def detect_continuity_signal(query: str) -> bool:
    """Check if query references previous conversation turns."""
    pattern = (
        r"(ở trên|vừa rồi|trước đó|vừa nêu|bảng trên|phần \d+|mục \d+|ý thứ \d+|luận điểm \d+|"
        r"nói rõ hơn|giải thích thêm|làm rõ|chi tiết hơn|tiếp tục|tiếp theo|bổ sung|so sánh với cái trước|"
        r"above|previous|earlier|clarify|elaborate|continue|furthermore)"
    )
    return bool(re.search(pattern, query, re.IGNORECASE))


def extract_last_exchange(command_content: str, max_chars: int = 4000) -> dict[str, str] | None:
    """Extract the most recent Q&A exchange prior to the pending query in Command.md.

    Returns:
        Dict with 'query' and 'response', or None if no prior exchange.
    """
    if "## 🕰️ Lịch sử tương tác" not in command_content:
        return None
    history_part = command_content.split("## 🕰️ Lịch sử tương tác", 1)[1]
    m_query = re.search(r"@AI:\s*(.*?)\s*---", history_part, re.DOTALL)
    if not m_query:
        return None
    prev_query = m_query.group(1).strip()

    after_query = history_part[m_query.end():]
    m_resp = re.search(r">\s*\[!done\]\+?\s*[^\n]*\n((?:>[^\n]*\n?)+)", after_query)
    if not m_resp:
        return None
    raw_lines = m_resp.group(1).splitlines()
    clean_lines = [re.sub(r"^>\s?", "", line) for line in raw_lines]
    prev_resp = "\n".join(clean_lines).strip()
    if len(prev_resp) > max_chars:
        prev_resp = prev_resp[:max_chars] + "\n...(cắt ngắn để bảo toàn ngân sách ngữ cảnh)..."
    return {"query": prev_query, "response": prev_resp}


def build_multi_turn_context(clean_query: str, content: str) -> str:
    """Construct multi-turn conversation context XML if query contains continuity signals."""
    if not detect_continuity_signal(clean_query):
        return ""

    last_exchange = extract_last_exchange(content)
    if not last_exchange:
        return ""

    _logger.info(f"Injected multi-turn conversation context for query: {clean_query[:50]}...")
    return (
        f"<previous_conversation_context>\n"
        f'<user_previous_query>{html.escape(last_exchange["query"])}</user_previous_query>\n'
        f'<assistant_previous_response>\n{last_exchange["response"]}\n</assistant_previous_response>\n'
        f"</previous_conversation_context>"
    )


def build_query_context(clean_query: str, content: str) -> tuple[str, dict]:
    """Assemble vault RAG context, multi-turn history, and live JIT URL context.

    Args:
        clean_query: User query string stripped of style prefix.
        content: Current full content of Command.md for multi-turn history extraction.

    Returns:
        Tuple of (combined_rag_context_str, rag_references_dict).
    """
    rag_context, rag_refs = build_rag_context(clean_query)

    prev_ctx = build_multi_turn_context(clean_query, content)
    if prev_ctx:
        rag_context = f"{prev_ctx}\n\n{rag_context}" if rag_context else prev_ctx

    ext_context, _ = extract_and_fetch_urls(clean_query)
    if ext_context:
        rag_context = f"{ext_context}\n\n{rag_context}" if rag_context else ext_context

    return rag_context, rag_refs
