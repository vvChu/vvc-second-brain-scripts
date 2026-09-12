"""VvC Second Brain — Command Inbox String Transformations.

Pure functional string processing for Command.md inbox, queries, callouts, and surgical patching.
Zero File I/O.
"""

from __future__ import annotations

from datetime import datetime
import re

from services.chat_history import (
    INPUT_MARKER,
    HISTORY_MARKER,
    extract_sections,
)


def ensure_format(content: str) -> str:
    """Ensure the content has the Inbox / History structure.

    Args:
        content: Raw markdown text of Command.md.

    Returns:
        Structured content with INPUT_MARKER and HISTORY_MARKER.
    """
    if INPUT_MARKER in content and HISTORY_MARKER in content:
        return content
    header = "# 🤖 Command Center\nGõ câu lệnh vào phần Input dưới đây.\n\n"
    input_sec = f"{INPUT_MARKER}\n\n@AI:  ---\n\n"
    history_sec = f"{HISTORY_MARKER}\n\n"
    return header + input_sec + history_sec + content.strip()


def _is_yaml_frontmatter(text: str) -> bool:
    """Check if text begins with a YAML frontmatter block (--- key: val ... ---)."""
    return bool(re.match(r"^\s*---\r?\n[a-zA-Z0-9_-]+\s*:.*?\r?\n---\s*(\r?\n|$)", text, re.DOTALL))


def find_pending_query_span(inbox: str, target_query: str | None = None) -> tuple[str | None, int, int]:
    """Find unprocessed @AI: query and its [start, end) span in inbox.

    Handles internal horizontal rules (---) and YAML blocks (--- ... ---).
    Skips empty/answered queries (e.g. @AI:  ---) and supports targeting a specific query.
    Ignores false positives inside blockquotes (> @AI:) or code fences.

    Args:
        inbox: Content of the Inbox section.
        target_query: Optional query string to match specifically.

    Returns:
        Tuple of (clean_query, start_idx, end_idx) or (None, -1, -1).
    """
    if not inbox:
        return None, -1, -1

    for ai_match in re.finditer(r"^[ \t]*(@AI:)", inbox, re.MULTILINE | re.IGNORECASE):
        # Ignore matches inside code fences
        prefix_before = inbox[:ai_match.start(1)]
        if prefix_before.count("```") % 2 != 0:
            continue

        start_idx = ai_match.start(1)
        after_ai = inbox[ai_match.end(1):]

        # Delimit search to next root-level @AI: if any
        next_ai = re.search(r"^[ \t]*@AI:", after_ai, re.MULTILINE | re.IGNORECASE)
        search_limit = next_ai.start() if next_ai else len(after_ai)
        search_text = after_ai[:search_limit]

        # Check if closing --- is on the same line as @AI:
        # e.g., "@AI: What is transformer? ---"
        first_nl = search_text.find("\n")
        same_line = search_text[:first_nl] if first_nl != -1 else search_text
        same_line_dash = re.search(r"---", same_line)
        if same_line_dash:
            cand = same_line[:same_line_dash.start()].strip()
            if cand:
                if target_query is None or cand.strip() == target_query.strip():
                    end_idx = ai_match.end(1) + same_line_dash.end()
                    return cand, start_idx, end_idx
            else:
                # Empty query placeholder like "@AI:  ---" -> skip to next @AI:
                continue

        # Check multiline empty placeholder: @AI:\n--- (not starting a YAML block)
        m_empty = re.match(r"^\s*---\s*(\r?\n|$)", search_text)
        if m_empty and not _is_yaml_frontmatter(search_text):
            continue

        dash_matches = list(re.finditer(r"---", search_text))
        if not dash_matches:
            continue

        # Filter candidate closing dashes
        valid_candidates: list[tuple[re.Match, str]] = []
        for m in dash_matches:
            cand = search_text[:m.start()].strip()
            if not cand:
                continue
            # Check unclosed code fences
            if cand.count("```") % 2 != 0:
                continue
            # Check unclosed YAML frontmatter
            if cand.startswith("---") and cand.count("---") < 2:
                continue
            valid_candidates.append((m, cand))

        if not valid_candidates:
            continue

        # If matching a specific target query, find exact candidate
        if target_query is not None:
            for m, cand in valid_candidates:
                if cand.strip() == target_query.strip():
                    end_idx = ai_match.end(1) + m.end()
                    return cand, start_idx, end_idx

        # For discovering query: find candidate followed by end of text or blank line
        selected_match, selected_query = valid_candidates[-1]
        for m, cand in valid_candidates:
            rem = search_text[m.end():]
            if not rem.strip() or re.match(r"^\r?\n\s*\r?\n", rem):
                selected_match, selected_query = m, cand
                break

        end_idx = ai_match.end(1) + selected_match.end()
        if target_query is None or selected_query.strip() == target_query.strip():
            return selected_query, start_idx, end_idx

    return None, -1, -1


def find_pending_query(content: str) -> str | None:
    """Find unprocessed query in the Inbox section of content.

    Args:
        content: Full text of Command.md.

    Returns:
        Unprocessed query string or None.
    """
    _, inbox, _ = extract_sections(content)
    if not inbox:
        return None

    query, _, _ = find_pending_query_span(inbox)
    return query


def format_response_callout(
    query: str,
    response: str,
    style_name: str,
    emoji: str,
    now_str: str | None = None,
) -> str:
    """Format Obsidian callout block for the response history.

    Args:
        query: Original user query.
        response: Synthesized answer.
        style_name: Name of the writing style.
        emoji: Emoji representation for the style.
        now_str: Optional timestamp string (defaults to current time).

    Returns:
        Formatted markdown block ending with double newline.
    """
    now = now_str if now_str is not None else datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"@AI: {query} ---\n"
        f"> [!done]+ {emoji} Trả lời ({now}) — *{style_name}*\n"
        + "\n".join(f"> {line}" for line in response.split("\n"))
        + "\n\n"
    )


def patch_inbox(inbox: str, query: str) -> str:
    """Surgically replace the pending query with empty placeholder '@AI:  ---'.

    Preserves all surrounding user draft notes and non-targeted content.

    Args:
        inbox: Content of the Inbox section.
        query: Query string to be cleared.

    Returns:
        Updated inbox string.
    """
    _, q_start, q_end = find_pending_query_span(inbox, target_query=query)
    if q_start != -1 and q_end != -1:
        return inbox[:q_start] + "@AI:  ---" + inbox[q_end:]

    escaped_query = re.escape(query)
    pattern = re.compile(rf"@AI:\s*{escaped_query}\s*---", re.IGNORECASE | re.DOTALL)
    if pattern.search(inbox):
        return pattern.sub("@AI:  ---", inbox, count=1)

    if "@AI:" not in inbox:
        return inbox + "\n\n@AI:  ---\n"
    return inbox


def apply_command_patch(
    current_content: str,
    fallback_content: str,
    query: str,
    response: str,
    style_name: str,
    emoji: str,
    now_str: str | None = None,
) -> tuple[str, bool]:
    """Apply surgical patch to command file content.

    Tries current_content first; falls back to fallback_content if sections missing.

    Args:
        current_content: Content freshly read from disk.
        fallback_content: In-memory fallback content.
        query: Original user query.
        response: Generated response.
        style_name: Writing style name.
        emoji: Writing style emoji.
        now_str: Optional timestamp string.

    Returns:
        Tuple of (new_full_content, success). If failed, returns ("", False).
    """
    before, inbox, after = extract_sections(current_content)
    if before is None or inbox is None or after is None:
        if current_content != fallback_content:
            before, inbox, after = extract_sections(fallback_content)
        if before is None or inbox is None or after is None:
            return "", False

    new_inbox = patch_inbox(inbox, query)
    response_block = format_response_callout(query, response, style_name, emoji, now_str=now_str)
    new_after = response_block + after.lstrip()
    new_content = before + INPUT_MARKER + "\n\n" + new_inbox.strip() + "\n\n" + HISTORY_MARKER + "\n\n" + new_after
    return new_content, True
