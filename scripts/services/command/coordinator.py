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

from services.worker_dispatcher import trigger_workers
from services.chat_history import auto_archive_command, MAX_COMMAND_LEN
from services.rag_builder import build_rag_context

import services.command as _pkg
from services.command.styles import WRITING_STYLES, parse_style
from services.command.citations import reindex_citations, clean_wikilink_quotes
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


def generate_response(query: str, style_name: str, rag_context: str) -> str:
    """Generate LLM response for a user query.

    Args:
        query: Query string.
        style_name: Writing style name.
        rag_context: Vault context string.

    Returns:
        LLM response text.
    """
    style = WRITING_STYLES[style_name]
    prompt = _RESPONSE_PROMPT.format(
        style_instruction=style["system"],
        rag_context=rag_context or "(Không tìm thấy context liên quan trong vault)",
        query=query,
    )

    task = "synthesis" if style_name in ("fast", "hero-image") else "reasoning"
    active_call_llm = _get_active_call_llm()
    return active_call_llm(prompt, task=task)


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


def handle_command(command_file: Path | None = None) -> None:
    """Process pending queries in Command.md.

    Args:
        command_file: Optional path override for Command.md.
    """
    active_cfg = _get_active_cfg()
    cmd_file = command_file if command_file is not None else active_cfg.command_file
    if not cmd_file.exists():
        return
    try:
        original_content = cmd_file.read_text(encoding="utf-8")
    except OSError:
        return

    content = ensure_format(original_content)
    if content != original_content:
        try:
            _safe_write_command_file(cmd_file, content)
            _logger.info("Migrated Command.md to Inbox format")
        except OSError:
            pass

    # Auto-archive if file is too large
    if len(content) > MAX_COMMAND_LEN:
        new_content = auto_archive_command(content)
        if new_content != content:
            content = new_content
            try:
                _safe_write_command_file(cmd_file, content)
            except OSError:
                pass

    query = find_pending_query(content)
    if not query:
        return

    _logger.info(f"Processing query: {query[:80]}...")
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
        return

    style_name, clean_query = parse_style(query)
    style = WRITING_STYLES[style_name]

    if style_name == "hero-image":
        response, topic_path, image_path = process_hero_image(
            clean_query,
            active_cfg=active_cfg,
            call_llm_fn=_get_active_call_llm(),
        )
        if not response:
            log("error", "Hero-image response generation failed")
            return
        if write_response(content, query, response, style_name, style, target_file=cmd_file):
            trigger_workers(response, clean_query)
            check_file_back(response, clean_query)
        return

    rag_context, rag_refs = build_rag_context(clean_query)

    response = generate_response(clean_query, style_name, rag_context)
    if not response:
        log("error", "Command response generation failed")
        return

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
