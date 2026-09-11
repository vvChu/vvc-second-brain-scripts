"""VvC Second Brain — Command.md Interactive Handler (v7.0).

Monitors Command.md for @AI: queries, processes them with RAG + LLM,
writes responses back. Supports 9 writing styles via /prefix.

Usage:
    from services.command import handle_command
    handle_command()  # Called by daemon.py polling loop
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log

from services.worker_dispatcher import trigger_workers
from services.chat_history import auto_archive_command, extract_sections, INPUT_MARKER, HISTORY_MARKER, MAX_COMMAND_LEN
from services.rag_builder import build_rag_context

try:
    from services.legal_sync_worker import trigger_legal_sync
except ImportError:
    trigger_legal_sync = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.command")

# --- Writing Styles ---

WRITING_STYLES: dict[str, dict] = {
    "professional": {
        "prefix": "",
        "emoji": "🏢",
        "system": "Viết bằng phong cách khoa học, chuyên nghiệp, có cấu trúc rõ ràng. Dùng heading, bullet points, và evidence-based reasoning.",
    },
    "tim-urban": {
        "prefix": "/tim-urban",
        "emoji": "🐒",
        "system": "Viết phong cách Tim Urban (Wait But Why): hài hước, dùng analogies sáng tạo, snarky footnotes, giải thích phức tạp bằng ngôn ngữ đời thường.",
    },
    "academic": {
        "prefix": "/academic",
        "emoji": "🎓",
        "system": "Viết phong cách học thuật formal: evidence-based, citations, structured argumentation, neutral tone.",
    },
    "bullet": {
        "prefix": "/bullet",
        "emoji": "📝",
        "system": "Viết ngắn gọn tối đa: chỉ bullet points, scannable, zero filler words. Mỗi point ≤ 2 dòng.",
    },
    "socratic": {
        "prefix": "/socratic",
        "emoji": "🤔",
        "system": "Dẫn dắt suy nghĩ bằng câu hỏi Socratic. Không đưa câu trả lời trực tiếp, thay vào đó đặt câu hỏi để người đọc tự rút ra kết luận.",
    },
    "storyteller": {
        "prefix": "/storyteller",
        "emoji": "📖",
        "system": "Viết phong cách kể chuyện: narrative, anecdotes, ví dụ thực tế, tạo cảm xúc và engagement.",
    },
    "eli5": {
        "prefix": "/eli5",
        "emoji": "👶",
        "system": "Explain Like I'm 5: zero jargon, analogies đơn giản, ngôn ngữ hằng ngày. Bất kỳ ai cũng hiểu được.",
    },
    "debate": {
        "prefix": "/debate",
        "emoji": "⚖️",
        "system": "Multi-perspective debate: trình bày ≥2 quan điểm đối lập, steelmanning mỗi bên, rồi tổng hợp.",
    },
    "sparring": {
        "prefix": "/phan-bien",
        "aliases": ["/sparring", "/phản-biện"],
        "emoji": "🥊",
        "system": (
            "Bỏ qua xu nịnh hoàn toàn. Đóng vai đối tác đấu tập (sparring partner) và nhà phê bình khắt khe, không khoan nhượng.\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. Phê bình trước (Critique-first): Liệt kê ít nhất 3 lỗ hổng logic, giả định sai hoặc rủi ro tiềm ẩn TRƯỚC KHI đưa ra bất kỳ nhận xét tích cực nào.\n"
            "2. Dựa trên bằng chứng (Evidence-based): Mọi phê bình phải trích dẫn cụ thể từ văn bản, dữ liệu hoặc phát biểu trong ngữ cảnh được cung cấp. Tuyệt đối không nhận xét chung chung.\n"
            "3. Quét điểm mù (Blind-spot query): Chỉ ra ít nhất 1 điểm mù tư duy người dùng có thể đang bảo vệ vô thức và 1 giả định cốt lõi có nguy cơ trở nên lỗi thời (irrelevance risk).\n"
            "4. Tính xây dựng: Mỗi điểm phê bình phải đi kèm câu hỏi gợi mở hoặc phương án kiểm chứng thực tế, không tiêu cực vô căn cứ."
        ),
    },
}


def _parse_style(query: str) -> tuple[str, str]:
    """Parse style prefix from query. Returns (style_name, clean_query)."""
    for name, style in WRITING_STYLES.items():
        prefixes = [style["prefix"]] if isinstance(style["prefix"], str) else list(style["prefix"])
        prefixes.extend(style.get("aliases", []))
        for pfx in prefixes:
            if pfx and query.strip().startswith(pfx):
                clean = query.strip()[len(pfx):].strip()
                return name, clean
    return "professional", query


# --- Format Extraction ---

def _ensure_format(content: str) -> str:
    """Ensure the file has the Inbox / History structure."""
    if INPUT_MARKER in content and HISTORY_MARKER in content:
        return content
    header = "# 🤖 Command Center\nGõ câu lệnh vào phần Input dưới đây.\n\n"
    input_sec = f"{INPUT_MARKER}\n\n@AI:  ---\n\n"
    history_sec = f"{HISTORY_MARKER}\n\n"
    return header + input_sec + history_sec + content.strip()


# --- Query Detection ---

_QUERY_PATTERN = re.compile(
    r"@AI:\s*(.*?)\s*---",
    re.DOTALL | re.IGNORECASE,
)

def _find_pending_query(content: str) -> str | None:
    """Find unprocessed query in the Inbox."""
    _, inbox, _ = extract_sections(content)
    if not inbox: 
        return None
        
    match = _QUERY_PATTERN.search(inbox)
    if not match: 
        return None
        
    query = match.group(1).strip()
    if not query: 
        return None
        
    return query


# --- Response Generation ---

from core.prompts.services import COMMAND_RESPONSE as _RESPONSE_PROMPT  # noqa: E402


def _generate_response(query: str, style_name: str, rag_context: str) -> str:
    """Generate LLM response for a user query."""
    style = WRITING_STYLES[style_name]

    prompt = _RESPONSE_PROMPT.format(
        style_instruction=style["system"],
        rag_context=rag_context or "(Không tìm thấy context liên quan trong vault)",
        query=query,
    )

    return call_llm(prompt, task="reasoning")


# --- File-Back Loop ---

def _check_file_back(response: str, query: str) -> None:
    """If response contains insights about existing concepts, enrich them."""
    # Extract wiki-links mentioned in response
    links = re.findall(r"\[\[([^\]|]+)", response)
    if not links:
        return

    # For now, just log — full file-back implementation in Phase 4
    _logger.debug(f"File-back candidates: {links[:5]}")


# --- Main Handler ---

def _write_response(content: str, query: str, response: str, style_name: str, style: dict) -> bool:
    """Write the formatted response block back to the command file."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    response_block = (
        f"@AI: {query} ---\n"
        f"> [!done]+ {style['emoji']} Trả lời ({now}) — *{style_name}*\n"
        + "\n".join(f"> {line}" for line in response.split("\n"))
        + "\n\n"
    )
    
    before, inbox, after = extract_sections(content)
    if not before:
        return False
        
    new_inbox = "\n\n@AI:  ---\n\n"
    new_after = response_block + after.lstrip()
    
    new_content = before + INPUT_MARKER + "\n" + new_inbox + HISTORY_MARKER + "\n\n" + new_after
    
    try:
        cfg.command_file.write_text(new_content, encoding="utf-8")
        _logger.info(f"Response written ({len(response)} chars)")
        log("query", f"Response delivered: {len(response)} chars", source="Command.md")
        return True
    except OSError as e:
        _logger.error(f"Failed to write response: {e}")
        return False

def handle_command() -> None:
    """Process pending queries in Command.md."""
    if not cfg.command_file.exists():
        return
    try:
        original_content = cfg.command_file.read_text(encoding="utf-8")
    except OSError:
        return
        
    content = _ensure_format(original_content)
    if content != original_content:
        try:
            cfg.command_file.write_text(content, encoding="utf-8")
            _logger.info("Migrated Command.md to Inbox format")
        except OSError:
            pass

    # Auto-archive if file is too large
    if len(content) > MAX_COMMAND_LEN:
        new_content = auto_archive_command(content)
        if new_content != content:
            content = new_content
            try:
                cfg.command_file.write_text(content, encoding="utf-8")
            except OSError:
                pass

    query = _find_pending_query(content)
    if not query:
        return

    _logger.info(f"Processing query: {query[:80]}...")
    log("query", f"Command query: {query[:100]}")

    # Intercept /legal_sync command
    if query.strip().startswith("/legal_sync"):
        if trigger_legal_sync:
            trigger_legal_sync()
            _write_response(content, query, "> Đang tiến hành đồng bộ dữ liệu Pháp luật Xây dựng trên Cloud. Vui lòng kiểm tra mục **Permanent/concepts** sau vài phút.", "professional", WRITING_STYLES["professional"])
        else:
            _write_response(content, query, "> Không tìm thấy legal_sync_worker.", "professional", WRITING_STYLES["professional"])
        return

    style_name, clean_query = _parse_style(query)
    style = WRITING_STYLES[style_name]
    rag_context, rag_refs = build_rag_context(clean_query)
    
    response = _generate_response(clean_query, style_name, rag_context)
    if not response:
        log("error", "Command response generation failed")
        return

    # Clean up accidental quotes inside wikilinks generated by LLM: ![["filename.md"]] -> ![[filename.md]]
    response = re.sub(r'!\[\["(.*?)"(\|.*?)?\]\]', r'![[\1\2]]', response)
    response = re.sub(r"!\[\['(.*?)'(\|.*?)?\]\]", r'![[\1\2]]', response)

    # Programmatically append reference list based on used IDs
    used_ids = []
    # Match standard [1] or wikilink aliases like [[file|1]] or [[file|[1]]]
    for match in re.finditer(r"\[(\d+)\]|\|\[?(\d+)\]?\]\]", response):
        val = match.group(1) or match.group(2)
        if val:
            try:
                parsed_id = int(val)
                if parsed_id not in used_ids:
                    used_ids.append(parsed_id)
            except ValueError:
                pass
            
    if used_ids and rag_refs:
        # Filter used_ids to only those present in rag_refs (preserving appearance order)
        valid_ids = [i for i in used_ids if i in rag_refs]
        
        if valid_ids:
            id_map = {old_id: new_id for new_id, old_id in enumerate(valid_ids, 1)}
            
            def _replace_id(match):
                if match.group(1):
                    old_id = int(match.group(1))
                    if old_id in id_map:
                        return f"[{id_map[old_id]}]"
                elif match.group(2):
                    old_id = int(match.group(2))
                    if old_id in id_map:
                        original = match.group(0)
                        if f"[{old_id}]" in original:
                            return original.replace(f"[{old_id}]", f"[{id_map[old_id]}]")
                        else:
                            return original.replace(str(old_id), str(id_map[old_id]))
                return match.group(0)
                
            response = re.sub(r"\[(\d+)\]|\|\[?(\d+)\]?\]\]", _replace_id, response)
            
            ref_block = "\n\n---\n\n## Tài liệu tham chiếu\n"
            for old_id in valid_ids:
                fname, ftitle = rag_refs[old_id]
                new_id = id_map[old_id]
                ref_block += f"{new_id}. [[{fname}|{ftitle}]]\n"
            
            if "]. [[" in ref_block or ". [[" in ref_block:
                response += ref_block

    if _write_response(content, query, response, style_name, style):
        trigger_workers(response, clean_query)
        _check_file_back(response, clean_query)
