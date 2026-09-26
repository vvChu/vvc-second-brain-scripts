"""VvC Second Brain — Command Coordinator & Orchestrator.

Manages query processing, RAG context retrieval, LLM dispatch, topic auto-saving,
resilient disk I/O, and background worker triggering.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
import time

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.prompts.services import COMMAND_RESPONSE as _RESPONSE_PROMPT
from core.markdown_sanitizer import clean_wikilink_quotes

from services.worker_dispatcher import trigger_workers
from services.command.styles import WRITING_STYLES, parse_style
from services.command.citations import reindex_citations
from services.command.inbox import (
    ensure_format,
    find_pending_query,
    apply_command_patch,
    auto_archive_command,
    MAX_COMMAND_LEN,
)
from services.command.topic_saver import auto_save_topic
from services.command.hero_image import process_hero_image
from services.command.query_context import (
    extract_and_fetch_urls,
    detect_continuity_signal,
    extract_last_exchange,
    build_query_context,
)
import services.command as _pkg

try:
    from services.legal_sync_worker import trigger_legal_sync
except ImportError:
    trigger_legal_sync = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.command")

_ERR_LLM_CALLOUT = (
    "> [!danger] ⚠️ Lỗi kết nối mô hình LLM\n"
    "> Không thể nhận phản hồi từ Gateway hoặc CLI. Vui lòng kiểm tra lại dịch vụ và thử lại sau."
)

__all__ = [
    "handle_command",
    "process_command",
    "generate_response",
    "write_response",
    "check_file_back",
    "extract_and_fetch_urls",
    "detect_continuity_signal",
    "extract_last_exchange",
]


def _get_active_cfg():
    """Retrieve active config dynamically to respect test monkeypatching."""
    return getattr(_pkg, "cfg", cfg)


def _get_active_call_llm():
    """Retrieve active call_llm dynamically to respect test monkeypatching."""
    return getattr(_pkg, "call_llm", call_llm)


def _safe_write_command_file(target_file: Path, content: str, max_retries: int = 3) -> bool:
    """Write text to target_file with retry on transient OSError."""
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
    """Generate LLM response for a user query."""
    style = WRITING_STYLES.get(style_name, WRITING_STYLES["professional"])
    prompt = _RESPONSE_PROMPT.format(
        style_instruction=style["system"],
        rag_context=rag_context or "(Không tìm thấy context liên quan trong vault)",
        query=query,
    )
    fast_styles = ("tim-urban", "eli5", "storyteller", "bullet", "socratic", "fast", "hero-image")
    task = "synthesis" if (is_fast or style_name in fast_styles) else "reasoning"

    active_call_llm = _get_active_call_llm()
    if explicit_model:
        return active_call_llm(prompt, model=explicit_model, task=task)
    return active_call_llm(prompt, task=task)


def check_file_back(response: str, query: str) -> None:
    """If response contains insights about existing concepts, enrich them."""
    links = re.findall(r"\[\[([^\]|]+)", response)
    if links:
        _logger.debug(f"File-back candidates: {links[:5]}")


def write_response(
    content: str,
    query: str,
    response: str,
    style_name: str,
    style: dict,
    target_file: Path | None = None,
) -> bool:
    """Write the formatted response block back to the command file."""
    cmd_file = target_file if target_file is not None else _get_active_cfg().command_file
    target_content = content
    if cmd_file.exists():
        try:
            target_content = cmd_file.read_text(encoding="utf-8")
        except OSError:
            pass

    new_content, success = apply_command_patch(
        current_content=target_content,
        fallback_content=content,
        query=query,
        response=response,
        style_name=style_name,
        emoji=style.get("emoji", "🤖"),
    )
    if not success:
        return False

    if _safe_write_command_file(cmd_file, new_content):
        _logger.info(f"Response written ({len(response)} chars)")
        log("query", f"Response delivered: {len(response)} chars", source="Command.md")
        return True
    return False


def _dispatch_and_write(
    content: str, query: str, clean_query: str, response: str, style_name: str, style: dict, cmd_file: Path
) -> bool:
    """Write response to file and trigger background worker dispatchers."""
    if write_response(content, query, response, style_name, style, target_file=cmd_file):
        trigger_workers(response, clean_query)
        check_file_back(response, clean_query)
        return True
    return False


def _handle_special_commands(query: str, content: str, cmd_file: Path) -> tuple[bool, bool] | None:
    """Intercept special slash commands like /legal_sync."""
    if not query.strip().startswith("/legal_sync"):
        return None
    if trigger_legal_sync:
        trigger_legal_sync()
        msg = "> Đang tiến hành đồng bộ dữ liệu Pháp luật Xây dựng trên Cloud. Vui lòng kiểm tra mục **Permanent/concepts** sau vài phút."
    else:
        msg = "> Không tìm thấy legal_sync_worker."
    written = write_response(content, query, msg, "professional", WRITING_STYLES["professional"], target_file=cmd_file)
    return (written, written)


def _apply_response_enhancements(
    response: str,
    clean_query: str,
    style_name: str,
    rag_refs: dict,
    active_cfg,
) -> str:
    """Enrich response with downgrade notices, clean links, citations, and topic auto-save."""
    try:
        from core.llm.gateway_client import consume_gateway_downgraded

        if consume_gateway_downgraded():
            response = (
                "> [!info] ℹ️ Claude Opus 4.6 đang trong thời gian hồi phục tài khoản (cooldown), "
                "hệ thống đã tự động phản hồi bằng Gemini 3.8 Flash High để bạn không phải chờ đợi.\n\n"
            ) + response
    except Exception:
        pass

    response = clean_wikilink_quotes(response)
    if rag_refs:
        response = reindex_citations(response, rag_refs)

    topic_file = auto_save_topic(clean_query, response, style_name, base_dir=active_cfg.vault_root)
    if topic_file:
        response += f"\n\n---\n\n📑 **Đã lưu trữ thành Topic Note:** [[{topic_file.stem}]]\n"
    return response


def _handle_hero_image_branch(
    query: str,
    clean_query: str,
    style_name: str,
    style: dict,
    content: str,
    cmd_file: Path,
    active_cfg,
) -> tuple[bool, bool]:
    """Handle generation and delivery for hero-image style requests."""
    response, _, _ = process_hero_image(
        clean_query,
        active_cfg=active_cfg,
        call_llm_fn=_get_active_call_llm(),
    )
    if not response:
        log("error", "Hero-image response generation failed")
        written = write_response(content, query, _ERR_LLM_CALLOUT, style_name, style, target_file=cmd_file)
        return (written, False)
    written = _dispatch_and_write(content, query, clean_query, response, style_name, style, cmd_file)
    return (written, written)


def _execute_single_query(
    query: str,
    content: str,
    cmd_file: Path,
    active_cfg,
) -> tuple[bool, bool]:
    """Execute a single extracted command query end-to-end.

    Returns:
        Tuple of (handled_successfully_or_error_written, should_continue_loop).
    """
    special_res = _handle_special_commands(query, content, cmd_file)
    if special_res is not None:
        return special_res

    parsed_style = parse_style(query)
    style_name, clean_query = parsed_style.style_name, parsed_style.clean_query
    style = WRITING_STYLES[style_name]

    if style_name == "hero-image":
        return _handle_hero_image_branch(query, clean_query, style_name, style, content, cmd_file, active_cfg)

    rag_context, rag_refs = build_query_context(clean_query, content)
    gen_kwargs = {"is_fast": parsed_style.is_fast}
    explicit_model = getattr(parsed_style, "explicit_model", "")
    if explicit_model:
        gen_kwargs["explicit_model"] = explicit_model

    response = generate_response(clean_query, style_name, rag_context, **gen_kwargs)
    if not response:
        log("error", "Command response generation failed")
        written = write_response(content, query, _ERR_LLM_CALLOUT, style_name, style, target_file=cmd_file)
        return (written, False)

    final_response = _apply_response_enhancements(response, clean_query, style_name, rag_refs, active_cfg)
    written = _dispatch_and_write(content, query, clean_query, final_response, style_name, style, cmd_file)
    return (written, written)


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
            _safe_write_command_file(cmd_file, content)
            _logger.info("Migrated Command.md to Inbox format")

        if len(content) > MAX_COMMAND_LEN:
            new_content = auto_archive_command(content, vault_root=active_cfg.vault_root)
            if new_content != content:
                content = new_content
                _safe_write_command_file(cmd_file, content)

        query = find_pending_query(content)
        if not query:
            break

        _logger.info(f"Processing query ({processed_count + 1}): {query[:80]}...")
        log("query", f"Command query: {query[:100]}")

        handled, cont = _execute_single_query(query, content, cmd_file, active_cfg)
        if handled:
            processed_count += 1
        if not cont:
            break

    return processed_count


# Alias for backward-compatibility / alternative calling convention
process_command = handle_command
