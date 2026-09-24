"""VvC Second Brain — Command Coordinator & Orchestrator.

Manages query processing, RAG context retrieval, LLM dispatch, topic auto-saving,
resilient disk I/O, and background worker triggering.
"""

from __future__ import annotations

import concurrent.futures
import html
import logging
from pathlib import Path
import re
import time

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.prompts.services import COMMAND_RESPONSE as _RESPONSE_PROMPT

from services.worker_dispatcher import trigger_workers
from services.command.inbox import auto_archive_command, MAX_COMMAND_LEN
from services.rag import build_rag_context

import services.command as _pkg
from services.command.styles import WRITING_STYLES, parse_style
from core.markdown_sanitizer import clean_wikilink_quotes
from services.command.citations import reindex_citations
from services.command.inbox import (
    ensure_format,
    find_pending_query,
    apply_command_patch,
)
from services.command.topic_saver import auto_save_topic
from services.command.hero_image import process_hero_image

try:
    from services.legal_sync_worker import trigger_legal_sync
except ImportError:
    trigger_legal_sync = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.command")


def _get_active_cfg():
    """Retrieve active config dynamically to respect test monkeypatching."""
    return getattr(_pkg, "cfg", cfg)


def _get_active_call_llm():
    """Retrieve active call_llm dynamically to respect test monkeypatching."""
    return getattr(_pkg, "call_llm", call_llm)


def _safe_write_command_file(target_file: Path, content: str, max_retries: int = 3) -> bool:
    """Write text to target_file with retry on transient OSError (e.g. Windows file locking).

    Args:
        target_file: Path of the file to write.
        content: String content to write.
        max_retries: Maximum write attempts before giving up.

    Returns:
        True if write succeeded, False otherwise.
    """
    for attempt in range(max_retries):
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
            return True
        except OSError as e:
            if attempt < max_retries - 1:
                time.sleep(0.15)
            else:
                _logger.error(f"Failed to write to {target_file} after {max_retries} attempts: {e}")
                return False
    return False


def generate_response(
    query: str,
    style_name: str,
    rag_context: str,
    is_fast: bool = False,
    explicit_model: str = "",
) -> str:
    """Generate LLM response for a user query.

    Args:
        query: Query string.
        style_name: Writing style name.
        rag_context: Vault context string.
        is_fast: If True, overrides model routing to use task="synthesis" for speed.
        explicit_model: Optional explicit model override (e.g. claude-opus-4-6-thinking).

    Returns:
        LLM response text.
    """
    style = WRITING_STYLES.get(style_name, WRITING_STYLES["professional"])
    prompt = _RESPONSE_PROMPT.format(
        style_instruction=style["system"],
        rag_context=rag_context or "(Không tìm thấy context liên quan trong vault)",
        query=query,
    )

    if is_fast or style_name in ("tim-urban", "eli5", "storyteller", "bullet", "socratic", "fast", "hero-image"):
        task = "synthesis"
    else:
        task = "reasoning"

    active_call_llm = _get_active_call_llm()
    if explicit_model:
        return active_call_llm(prompt, model=explicit_model, task=task)
    return active_call_llm(prompt, task=task)


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


def extract_and_fetch_urls(clean_query: str) -> tuple[str, list[str]]:
    """Detect HTTP/HTTPS URLs in query, fetch content via url_fetcher, and format as XML context.

    Args:
        clean_query: The cleaned user query text.

    Returns:
        Tuple of (formatted_xml_context, list_of_fetched_urls).
    """
    urls = re.findall(r"https?://[^\s)\]]+", clean_query)
    if not urls:
        return "", []

    seen = set()
    unique_urls = []
    for u in urls:
        clean_u = u.rstrip(".,;:\"'>")
        if clean_u.endswith(")") and clean_u.count("(") < clean_u.count(")"):
            clean_u = clean_u.rstrip(")")
        if clean_u and clean_u not in seen:
            seen.add(clean_u)
            unique_urls.append(clean_u)

    unique_urls = unique_urls[:5]

    xml_blocks = []
    fetched_urls = []
    for url in unique_urls:
        try:
            from services.url_fetcher import fetch_url
            import inspect
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
                    text = future.result(timeout=10.0)
                except concurrent.futures.TimeoutError:
                    _logger.warning(f"JIT URL fetch timed out (>10s) for {url}")
                    continue

            if not text or not text.strip():
                continue

            title = ""
            heading_match = re.search(r"^#\s+(.+)$", text.strip(), re.MULTILINE)
            if heading_match:
                title = heading_match.group(1).strip()
            if not title:
                try:
                    from services.url_fetcher import fetch_url_title
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as t_executor:
                        t_future = t_executor.submit(fetch_url_title, url)
                        try:
                            title = t_future.result(timeout=3.0) or ""
                        except (concurrent.futures.TimeoutError, Exception):
                            title = ""
                except Exception:
                    title = ""
            if not title:
                title = url

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
            xml_blocks.append(
                f'<external_web_source url="{safe_url}" title="{safe_title}">\n{processed_text}\n</external_web_source>'
            )
            fetched_urls.append(url)
        except Exception as e:
            _logger.warning(f"Failed to fetch JIT URL {url}: {e}")
            continue

    return "\n\n".join(xml_blocks), fetched_urls


def check_file_back(response: str, query: str) -> None:
    """If response contains insights about existing concepts, enrich them.

    Args:
        response: Generated response.
        query: Original user query.
    """
    links = re.findall(r"\[\[([^\]|]+)", response)
    if not links:
        return
    _logger.debug(f"File-back candidates: {links[:5]}")


def write_response(
    content: str,
    query: str,
    response: str,
    style_name: str,
    style: dict,
    target_file: Path | None = None,
) -> bool:
    """Write the formatted response block back to the command file.

    Args:
        content: Current fallback content.
        query: Original user query.
        response: Generated response text.
        style_name: Style name.
        style: Style dictionary.
        target_file: Optional target file path (defaults to active cfg.command_file).

    Returns:
        True if written successfully, False otherwise.
    """
    cmd_file = target_file if target_file is not None else _get_active_cfg().command_file

    target_content = content
    if cmd_file.exists():
        try:
            target_content = cmd_file.read_text(encoding="utf-8")
        except OSError:
            target_content = content

    emoji = style.get("emoji", "🤖")
    new_content, success = apply_command_patch(
        current_content=target_content,
        fallback_content=content,
        query=query,
        response=response,
        style_name=style_name,
        emoji=emoji,
    )
    if not success:
        return False

    if _safe_write_command_file(cmd_file, new_content):
        _logger.info(f"Response written ({len(response)} chars)")
        log("query", f"Response delivered: {len(response)} chars", source="Command.md")
        return True
    return False


def handle_command(command_file: Path | None = None, max_queries: int = 10) -> int:
    """Process pending queries in Command.md until inbox is clear.

    Args:
        command_file: Optional path override for Command.md.
        max_queries: Safety cap on consecutive queries to prevent infinite loop.

    Returns:
        Total count of queries successfully processed.
    """
    active_cfg = _get_active_cfg()
    cmd_file = command_file if command_file is not None else active_cfg.command_file
    if not cmd_file.exists():
        return 0

    processed_count = 0
    while processed_count < max_queries:
        try:
            original_content = cmd_file.read_text(encoding="utf-8")
        except OSError:
            break

        content = ensure_format(original_content)
        if content != original_content:
            try:
                _safe_write_command_file(cmd_file, content)
                _logger.info("Migrated Command.md to Inbox format")
            except OSError:
                pass

        # Auto-archive if file is too large
        if len(content) > MAX_COMMAND_LEN:
            new_content = auto_archive_command(content, vault_root=active_cfg.vault_root)
            if new_content != content:
                content = new_content
                try:
                    _safe_write_command_file(cmd_file, content)
                except OSError:
                    pass

        query = find_pending_query(content)
        if not query:
            break

        _logger.info(f"Processing query ({processed_count + 1}): {query[:80]}...")
        log("query", f"Command query: {query[:100]}")

        # Intercept /legal_sync command
        if query.strip().startswith("/legal_sync"):
            if trigger_legal_sync:
                trigger_legal_sync()
                write_response(
                    content,
                    query,
                    "> Đang tiến hành đồng bộ dữ liệu Pháp luật Xây dựng trên Cloud. Vui lòng kiểm tra mục **Permanent/concepts** sau vài phút.",
                    "professional",
                    WRITING_STYLES["professional"],
                    target_file=cmd_file,
                )
            else:
                write_response(
                    content,
                    query,
                    "> Không tìm thấy legal_sync_worker.",
                    "professional",
                    WRITING_STYLES["professional"],
                    target_file=cmd_file,
                )
            processed_count += 1
            continue

        parsed_style = parse_style(query)
        style_name = parsed_style.style_name
        clean_query = parsed_style.clean_query
        is_fast = parsed_style.is_fast
        explicit_model = getattr(parsed_style, "explicit_model", "")
        style = WRITING_STYLES[style_name]

        if style_name == "hero-image":
            response, topic_path, image_path = process_hero_image(
                clean_query,
                active_cfg=active_cfg,
                call_llm_fn=_get_active_call_llm(),
            )
            if not response:
                log("error", "Hero-image response generation failed")
                error_callout = (
                    "> [!danger] ⚠️ Lỗi kết nối mô hình LLM\n"
                    "> Không thể nhận phản hồi từ Gateway hoặc CLI. Vui lòng kiểm tra lại dịch vụ và thử lại sau."
                )
                if write_response(content, query, error_callout, style_name, style, target_file=cmd_file):
                    processed_count += 1
                break
            if write_response(content, query, response, style_name, style, target_file=cmd_file):
                trigger_workers(response, clean_query)
                check_file_back(response, clean_query)
                processed_count += 1
            else:
                break
            continue

        rag_context, rag_refs = build_rag_context(clean_query)

        # Multi-turn Context: if query references previous turn, inject last exchange
        if detect_continuity_signal(clean_query):
            last_exchange = extract_last_exchange(content)
            if last_exchange:
                prev_ctx = (
                    f'<previous_conversation_context>\n'
                    f'<user_previous_query>{html.escape(last_exchange["query"])}</user_previous_query>\n'
                    f'<assistant_previous_response>\n{last_exchange["response"]}\n</assistant_previous_response>\n'
                    f'</previous_conversation_context>'
                )
                rag_context = f"{prev_ctx}\n\n{rag_context}" if rag_context else prev_ctx
                _logger.info(f"Injected multi-turn conversation context for query: {clean_query[:50]}...")

        # JIT URL Ingestion: fetch content from external URLs in query
        ext_context, fetched_urls = extract_and_fetch_urls(clean_query)
        if ext_context:
            rag_context = f"{ext_context}\n\n{rag_context}" if rag_context else ext_context

        gen_kwargs = {"is_fast": is_fast}
        if explicit_model:
            gen_kwargs["explicit_model"] = explicit_model
        response = generate_response(
            clean_query,
            style_name,
            rag_context,
            **gen_kwargs,
        )
        if not response:
            log("error", "Command response generation failed")
            error_callout = (
                "> [!danger] ⚠️ Lỗi kết nối mô hình LLM\n"
                "> Không thể nhận phản hồi từ Gateway hoặc CLI. Vui lòng kiểm tra lại dịch vụ và thử lại sau."
            )
            if write_response(content, query, error_callout, style_name, style, target_file=cmd_file):
                processed_count += 1
            break

        # Check if gateway gracefully downgraded from Opus to Gemini due to 503 cooldown
        try:
            from core.llm.gateway_client import consume_gateway_downgraded
            if consume_gateway_downgraded():
                downgrade_callout = (
                    "> [!info] ℹ️ Claude Opus 4.6 đang trong thời gian hồi phục tài khoản (cooldown), "
                    "hệ thống đã tự động phản hồi bằng Gemini 3.8 Flash High để bạn không phải chờ đợi.\n\n"
                )
                response = downgrade_callout + response
        except Exception:
            pass

        # Clean up accidental quotes inside wikilinks generated by LLM: ![["filename.md"]] -> ![[filename.md]]
        response = clean_wikilink_quotes(response)

        # Programmatically append reference list based on used IDs
        if rag_refs:
            response = reindex_citations(response, rag_refs)

        # Auto-save topic if response meets threshold (>= 2500 chars)
        topic_file = auto_save_topic(clean_query, response, style_name, base_dir=active_cfg.vault_root)
        if topic_file:
            response += f"\n\n---\n\n📑 **Đã lưu trữ thành Topic Note:** [[{topic_file.stem}]]\n"

        if write_response(content, query, response, style_name, style, target_file=cmd_file):
            trigger_workers(response, clean_query)
            check_file_back(response, clean_query)
            processed_count += 1
        else:
            break

    return processed_count


# Alias for backward-compatibility / alternative calling convention
process_command = handle_command

