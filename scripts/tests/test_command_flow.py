"""Unit tests for Command.md processing flow (v8.12.6+).

Verifies:
1. Boundary check with empty before (file starting directly with ## 📥 Input).
2. Inbox in-place surgical patching preserving user draft notes.
3. Query containing internal horizontal rules (---) and YAML blocks.
4. Fast mode routing (/fast, /quick, /nhanh -> task="synthesis").
5. Topic auto-save threshold (>= 2500 chars -> 04 - Permanent/topics/).
6. Citation reindexing ([14] -> [1]) and reference list generation.
7. Section extraction returning (None, None, None) on missing markers.
8. Auto-archive hardening matching root-level @AI: only.
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest

from core.config import cfg
from services.chat_history import (
    extract_sections,
    auto_archive_command,
    INPUT_MARKER,
    HISTORY_MARKER,
    QUERY_PATTERN,
)
from services.command import (
    _find_pending_query,
    _find_pending_query_span,
    _parse_style,
    _generate_response,
    _write_response,
    _auto_save_topic,
    reindex_citations,
    WRITING_STYLES,
    TOPIC_AUTO_SAVE_THRESHOLD,
)


def test_boundary_check_empty_before(tmp_path, monkeypatch):
    """Writing response must succeed even when before is empty string (no header)."""
    import dataclasses
    command_file = tmp_path / "Command.md"
    content = f"{INPUT_MARKER}\n\n@AI: What is transformer? ---\n\n{HISTORY_MARKER}\n\n"
    command_file.write_text(content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, command_file=command_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    success = _write_response(
        content,
        "What is transformer?",
        "A deep learning architecture based on self-attention.",
        "professional",
        WRITING_STYLES["professional"],
    )

    assert success is True
    result = command_file.read_text(encoding="utf-8")
    assert "@AI:  ---" in result
    assert "A deep learning architecture based on self-attention." in result
    assert HISTORY_MARKER in result


def test_inbox_surgical_patch_preserves_notes(tmp_path, monkeypatch):
    """User draft notes before and after @AI: query must be preserved when query is cleared."""
    import dataclasses
    command_file = tmp_path / "Command.md"
    content = (
        "# 🤖 Command Center\n\n"
        f"{INPUT_MARKER}\n\n"
        "Draft note 1: Kiểm tra quy chuẩn 06.\n\n"
        "@AI: Tóm tắt bài báo này ---\n\n"
        "Draft note 2: Họp lúc 15h30.\n\n"
        f"{HISTORY_MARKER}\n\n"
        "@AI: Old question ---\n"
        "> [!done]+ 🏢 Trả lời\n"
        "> Old answer\n"
    )
    command_file.write_text(content, encoding="utf-8")
    mock_cfg = dataclasses.replace(cfg, command_file=command_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    success = _write_response(
        content,
        "Tóm tắt bài báo này",
        "Bài báo nói về tự động hóa trong xây dựng.",
        "professional",
        WRITING_STYLES["professional"],
    )

    assert success is True
    new_content = command_file.read_text(encoding="utf-8")
    before, inbox, after = extract_sections(new_content)

    assert inbox is not None
    assert "Draft note 1: Kiểm tra quy chuẩn 06." in inbox
    assert "Draft note 2: Họp lúc 15h30." in inbox
    assert "@AI:  ---" in inbox
    assert "@AI: Tóm tắt bài báo này ---" not in inbox

    # The query and response should be recorded in history (after)
    assert "@AI: Tóm tắt bài báo này ---" in after
    assert "Bài báo nói về tự động hóa trong xây dựng." in after


def test_query_containing_horizontal_rules():
    """Queries containing horizontal rules (---) or YAML blocks must not be truncated."""
    # Case 1: Markdown horizontal rules inside query
    content_hr = (
        f"{INPUT_MARKER}\n\n"
        "@AI:\n"
        "So sánh hai phương pháp sau:\n"
        "---\n"
        "Phương pháp A: Sugiyama Layered Layout\n"
        "---\n"
        "Phương pháp B: Force-Directed Layout\n"
        "---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    query_hr = _find_pending_query(content_hr)
    assert query_hr is not None
    assert "Phương pháp A: Sugiyama Layered Layout" in query_hr
    assert "Phương pháp B: Force-Directed Layout" in query_hr

    # Case 2: YAML frontmatter block inside query
    content_yaml = (
        f"{INPUT_MARKER}\n\n"
        "@AI:\n"
        "---\n"
        "title: Architecture Review\n"
        "status: active\n"
        "---\n"
        "Giải thích các trường YAML trên giúp tôi.\n"
        "---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    query_yaml = _find_pending_query(content_yaml)
    assert query_yaml is not None
    assert "title: Architecture Review" in query_yaml
    assert "Giải thích các trường YAML trên" in query_yaml


def test_fast_mode_routing(monkeypatch):
    """Fast mode prefix (/fast, /quick, /nhanh) should route to task='synthesis'."""
    # Prefix parsing
    style, clean = _parse_style("/fast Tóm tắt nhanh quy định này")
    assert style == "fast"
    assert clean == "Tóm tắt nhanh quy định này"

    style, clean = _parse_style("/quick Give me a 1-sentence answer")
    assert style == "fast"
    assert clean == "Give me a 1-sentence answer"

    style, clean = _parse_style("/nhanh Giải thích thuật toán")
    assert style == "fast"
    assert clean == "Giải thích thuật toán"

    # LLM routing verification
    tasks_called: list[str] = []

    def mock_call_llm(prompt: str, task: str = "default") -> str:
        tasks_called.append(task)
        return "Mock response"

    monkeypatch.setattr("services.command.call_llm", mock_call_llm)

    # Calling with fast style should use 'synthesis'
    _generate_response("Query", "fast", "")
    assert tasks_called == ["synthesis"]

    # Calling with professional style should use 'reasoning'
    _generate_response("Query", "professional", "")
    assert tasks_called == ["synthesis", "reasoning"]


def test_topic_auto_save_threshold(tmp_path, monkeypatch):
    """Responses >= 2500 chars should be auto-saved as Topic articles."""
    import dataclasses
    mock_cfg = dataclasses.replace(cfg, vault_root=tmp_path)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    # 1. Short response (< 2500 chars) -> None
    short_resp = "Ngắn gọn: hệ thống hoạt động bình thường." * 10
    assert len(short_resp) < TOPIC_AUTO_SAVE_THRESHOLD
    saved_short = _auto_save_topic("Kiểm tra hệ thống", short_resp, "professional")
    assert saved_short is None

    # 2. Long response (>= 2500 chars) -> Path
    long_body = "Phân tích chi tiết về kiến trúc hệ thống và luồng dữ liệu. " * 60
    long_resp = f"# Kiến Trúc Toàn Cục LLM OS\n\n{long_body}"
    assert len(long_resp) >= TOPIC_AUTO_SAVE_THRESHOLD

    saved_long = _auto_save_topic("Kiến Trúc Toàn Cục LLM OS", long_resp, "professional")
    assert saved_long is not None
    assert saved_long.exists()
    assert saved_long.parent == tmp_path / "04 - Permanent" / "topics"
    assert saved_long.name == "kien_truc_toan_cuc_llm_os.md"

    content = saved_long.read_text(encoding="utf-8")
    assert "type: topic" in content
    assert "source: Command.md" in content
    assert "tags:" in content
    assert "type/topic" in content
    assert "# Kiến Trúc Toàn Cục LLM OS" in content


def test_citation_reindexing():
    """Citations [14], [5] should be reindexed to [1], [2] in appearance order."""
    response = (
        "Theo báo cáo [[source_1|14]], hệ thống hoạt động ổn định. "
        "Ngoài ra tài liệu [5] cũng nhấn mạnh điều này cùng với [14]."
    )
    rag_refs = {
        14: ("bao_cao_nghiem_thu.md", "Báo Cáo Nghiệm Thu 2026"),
        5: ("tieu_chuan_thiet_ke.md", "Tiêu Chuẩn Thiết Kế TC-01"),
        99: ("unused.md", "Unused Reference"),
    }

    reindexed = reindex_citations(response, rag_refs)

    # 14 appeared first -> becomes 1
    # 5 appeared second -> becomes 2
    assert "[[source_1|1]]" in reindexed
    assert "[2]" in reindexed
    assert "[14]" not in reindexed
    assert "[5]" not in reindexed

    # Check reference list block
    assert "## Tài liệu tham chiếu" in reindexed
    assert "1. [[bao_cao_nghiem_thu.md|Báo Cáo Nghiệm Thu 2026]]" in reindexed
    assert "2. [[tieu_chuan_thiet_ke.md|Tiêu Chuẩn Thiết Kế TC-01]]" in reindexed
    assert "unused.md" not in reindexed


def test_extract_sections_marker_missing():
    """extract_sections should return (None, None, None) if markers are missing."""
    before, inbox, after = extract_sections("Some arbitrary content without markers")
    assert before is None
    assert inbox is None
    assert after is None


def test_auto_archive_root_level_only():
    """QUERY_PATTERN should only match root-level @AI: lines, ignoring blockquotes."""
    content = (
        "@AI: Root query 1 ---\n"
        "> [!done]+ 🏢 Trả lời\n"
        "> > @AI: nested quote inside callout ---\n"
        "> Some response body\n"
        "@AI: Root query 2 ---\n"
        "> [!done]+ 🏢 Trả lời\n"
        "> Another response body\n"
    )
    matches = list(QUERY_PATTERN.finditer(content))
    # Should only match the 2 root-level queries, not the nested quote
    assert len(matches) == 2
    assert matches[0].group(1).strip() == "Root query 1"
    assert matches[1].group(1).strip() == "Root query 2"


def test_daemon_poll_command_async(tmp_path, monkeypatch):
    """_poll_command() must be non-blocking, spawn a worker thread, and update mtime post-run."""
    import time
    import threading
    import dataclasses
    import daemon

    command_file = tmp_path / "Command.md"
    command_file.write_text(f"{INPUT_MARKER}\n\n@AI: Hello ---\n\n{HISTORY_MARKER}\n", encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, command_file=command_file)
    monkeypatch.setattr("daemon.cfg", mock_cfg)

    # Reset poller state
    daemon._poller_state.command_mtime = 0.0
    daemon._command_in_progress = False

    executed = threading.Event()

    def mock_handle_command():
        # Verify _command_in_progress is True while worker runs
        assert daemon._command_in_progress is True
        executed.set()

    monkeypatch.setattr("services.command.handle_command", mock_handle_command)

    # Call _poll_command()
    daemon._poll_command()

    # Wait for background thread to execute
    assert executed.wait(timeout=2.0) is True

    # Give thread a moment to finish its finally block
    time.sleep(0.1)

    assert daemon._command_in_progress is False
    assert daemon._poller_state.command_mtime == command_file.stat().st_mtime


def test_inbox_with_empty_answered_placeholder_first(tmp_path, monkeypatch):
    """Empty placeholder @AI:  --- must be skipped, correctly identifying pending query below it."""
    import dataclasses
    command_file = tmp_path / "Command.md"
    content = (
        f"{INPUT_MARKER}\n\n"
        "@AI:  ---\n\n"
        "Draft note: xem lại tài liệu\n\n"
        "@AI: Giải thích cơ chế attention ---\n\n"
        f"{HISTORY_MARKER}\n\n"
    )
    command_file.write_text(content, encoding="utf-8")
    mock_cfg = dataclasses.replace(cfg, command_file=command_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    query = _find_pending_query(content)
    assert query == "Giải thích cơ chế attention"

    success = _write_response(
        content,
        "Giải thích cơ chế attention",
        "Cơ chế attention giúp mô hình tập trung vào phần quan trọng.",
        "professional",
        WRITING_STYLES["professional"],
    )
    assert success is True
    result = command_file.read_text(encoding="utf-8")
    _, inbox, _ = extract_sections(result)
    assert "Draft note: xem lại tài liệu" in inbox
    assert "Giải thích cơ chế attention" not in inbox


def test_inbox_draft_notes_containing_horizontal_rules(tmp_path, monkeypatch):
    """Draft notes containing markdown horizontal rules (---) must not be wiped out."""
    import dataclasses
    command_file = tmp_path / "Command.md"
    content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: Explain Python ---\n\n"
        "User draft notes:\n"
        "---\n"
        "Section 1: Syntax\n"
        "---\n"
        "Section 2: Concurrency\n"
        "---\n\n"
        f"{HISTORY_MARKER}\n\n"
    )
    command_file.write_text(content, encoding="utf-8")
    mock_cfg = dataclasses.replace(cfg, command_file=command_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    query = _find_pending_query(content)
    assert query == "Explain Python"

    success = _write_response(
        content,
        "Explain Python",
        "Python is a high-level interpreted programming language.",
        "professional",
        WRITING_STYLES["professional"],
    )
    assert success is True
    result = command_file.read_text(encoding="utf-8")
    _, inbox, _ = extract_sections(result)
    assert "User draft notes:" in inbox
    assert "Section 1: Syntax" in inbox
    assert "Section 2: Concurrency" in inbox
    assert "@AI:  ---" in inbox


def test_extract_sections_no_trailing_newline_at_eof():
    """extract_sections should succeed even when HISTORY_MARKER has no trailing newline at EOF."""
    content = f"{INPUT_MARKER}\n@AI: test ---\n{HISTORY_MARKER}"
    before, inbox, after = extract_sections(content)
    assert before is not None
    assert inbox is not None
    assert after is not None
    assert "@AI: test ---" in inbox


def test_fast_mode_prefix_word_boundary():
    """Commands like /fasten or /quickstart should not falsely match fast style."""
    style1, clean1 = _parse_style("/fasten the screws")
    assert style1 == "professional"
    assert clean1 == "/fasten the screws"

    style2, clean2 = _parse_style("/quickstart guide")
    assert style2 == "professional"
    assert clean2 == "/quickstart guide"


def test_topic_reference_callout_formatting(tmp_path, monkeypatch):
    """Topic note reference should render cleanly inside callout without double blockquote > >."""
    import dataclasses
    command_file = tmp_path / "Command.md"
    content = f"{INPUT_MARKER}\n\n@AI: Kiến Trúc Toàn Cục ---\n\n{HISTORY_MARKER}\n\n"
    command_file.write_text(content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, command_file=command_file, vault_root=tmp_path)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    # Build a response >= 2500 chars
    long_response = "# Kiến Trúc Toàn Cục\n\n" + ("Nội dung bài viết phân tích chi tiết sâu sắc. " * 60)
    topic_file = _auto_save_topic("Kiến Trúc Toàn Cục", long_response, "professional")
    assert topic_file is not None

    appended_response = long_response + f"\n\n---\n\n📑 **Đã lưu trữ thành Topic Note:** [[{topic_file.stem}]]\n"
    _write_response(content, "Kiến Trúc Toàn Cục", appended_response, "professional", WRITING_STYLES["professional"])

    result = command_file.read_text(encoding="utf-8")
    assert "> > 📑 **Đã lưu trữ thành Topic Note:**" not in result
    assert "> 📑 **Đã lưu trữ thành Topic Note:**" in result


def test_pure_inbox_patch_preserves_surrounding_text():
    """apply_command_patch should surgically remove the query while keeping drafts intact."""
    from services.command.inbox import apply_command_patch

    initial = (
        "# 🤖 Command Center\n\n"
        f"{INPUT_MARKER}\n\n"
        "Draft Note Alpha: Cần chuẩn bị hồ sơ hoàn công.\n\n"
        "@AI: /fast Tóm tắt nghị định 15 ---\n\n"
        "Draft Note Beta: Họp lúc 14h00 chiều nay.\n\n"
        f"{HISTORY_MARKER}\n\n"
        "@AI: Câu hỏi trước ---\n"
        "> [!done]+ 🏢 Trả lời (2026-09-01 10:00) — *professional*\n"
        "> Câu trả lời cũ\n"
    )

    new_content, success = apply_command_patch(
        current_content=initial,
        fallback_content=initial,
        query="/fast Tóm tắt nghị định 15",
        response="Nghị định 15 quy định về quản lý dự án đầu tư xây dựng.",
        style_name="fast",
        emoji="⚡",
        now_str="2026-09-12 12:00",
    )

    assert success is True
    before, inbox, after = extract_sections(new_content)
    assert inbox is not None
    assert "Draft Note Alpha: Cần chuẩn bị hồ sơ hoàn công." in inbox
    assert "Draft Note Beta: Họp lúc 14h00 chiều nay." in inbox
    assert "@AI:  ---" in inbox
    assert "@AI: /fast Tóm tắt nghị định 15 ---" not in inbox

    assert after is not None
    assert "@AI: /fast Tóm tắt nghị định 15 ---" in after
    assert "> [!done]+ ⚡ Trả lời (2026-09-12 12:00) — *fast*" in after
    assert "> Nghị định 15 quy định về quản lý dự án đầu tư xây dựng." in after
    assert "Draft Note Alpha" not in after


def test_pure_find_pending_query_span_nested_rules():
    """find_pending_query_span should correctly parse nested horizontal rules and YAML blocks."""
    from services.command.inbox import find_pending_query_span

    inbox = (
        "Some preceding text\n\n"
        "@AI:\n"
        "---\n"
        "title: YAML In Query\n"
        "category: testing\n"
        "---\n"
        "So sánh hai phương án sau:\n"
        "---\n"
        "Phương án 1: Microservices\n"
        "---\n"
        "Phương án 2: Deep Module Monolith\n"
        "---\n\n"
        "Trailing notes below query\n"
    )

    query, start, end = find_pending_query_span(inbox)
    assert query is not None
    assert "title: YAML In Query" in query
    assert "Phương án 1: Microservices" in query
    assert "Phương án 2: Deep Module Monolith" in query
    assert start == inbox.find("@AI:")
    assert end > start
    assert inbox[start:end].endswith("---")


def test_pure_build_topic_content_schema():
    """build_topic_content should generate correct YAML frontmatter and slug without I/O."""
    from services.command.topic_saver import build_topic_content, TOPIC_AUTO_SAVE_THRESHOLD

    # Response below threshold returns None
    short_resp = "Short response" * 50
    assert len(short_resp) < TOPIC_AUTO_SAVE_THRESHOLD
    assert build_topic_content("Câu hỏi ngắn", short_resp) is None

    # Response above threshold returns (title, slug, full_content)
    body = "Nội dung phân tích chuyên sâu về kiến trúc phần mềm hướng miền. " * 50
    long_resp = f"# Thiết Kế Deep Module\n\n{body}"
    assert len(long_resp) >= TOPIC_AUTO_SAVE_THRESHOLD

    result = build_topic_content("Thiết Kế Deep Module", long_resp)
    assert result is not None
    title, slug, full_content = result

    assert title == "Thiết Kế Deep Module"
    assert slug == "thiet_ke_deep_module"
    assert full_content.startswith("---\n")
    assert "title: Thiết Kế Deep Module" in full_content
    assert "type: topic" in full_content
    assert "source: Command.md" in full_content
    assert "# Thiết Kế Deep Module" in full_content


def test_inbox_multiline_query_preserves_subsequent_horizontal_rules():
    """Multi-line query must not swallow user draft notes containing horizontal rules."""
    from services.command.inbox import find_pending_query_span, patch_inbox

    inbox = (
        "Preceding draft note.\n\n"
        "@AI:\n"
        "/fast Tóm tắt nghị định 15\n"
        "---\n\n"
        "Draft Note Beta: Họp lúc 14h00 chiều nay.\n"
        "---\n"
        "Agenda họp:\n"
        "1. Tiến độ\n"
        "2. Chi phí\n"
        "---\n"
    )

    query, start, end = find_pending_query_span(inbox)
    assert query == "/fast Tóm tắt nghị định 15"
    assert "Draft Note Beta" not in query

    patched = patch_inbox(inbox, query)
    assert "@AI:  ---" in patched
    assert "Draft Note Beta: Họp lúc 14h00 chiều nay." in patched
    assert "Agenda họp:" in patched
    assert "1. Tiến độ" in patched
    assert "2. Chi phí" in patched


def test_inbox_ignores_quoted_and_code_fenced_queries():
    """find_pending_query_span must ignore @AI: inside blockquotes and code blocks."""
    from services.command.inbox import find_pending_query_span

    inbox = (
        "> @AI: Quoted query from previous note ---\n"
        "> [!info] Callout block\n"
        "> > @AI: Nested callout query ---\n\n"
        "```python\n"
        "# @AI: Example command in code fence ---\n"
        "```\n\n"
        "@AI: Genuine pending query ---\n"
    )

    query, start, end = find_pending_query_span(inbox)
    assert query == "Genuine pending query"


def test_clean_wikilink_quotes_embeds_and_notes():
    """clean_wikilink_quotes should sanitize accidental quotes from both embeds and notes."""
    from services.command.citations import clean_wikilink_quotes

    assert clean_wikilink_quotes('![["diagram.png"]]') == "![[diagram.png]]"
    assert clean_wikilink_quotes('![["diagram.png"|400]]') == "![[diagram.png|400]]"
    assert clean_wikilink_quotes('![[\'chart.svg\']]') == "![[chart.svg]]"
    assert clean_wikilink_quotes('[["concept_note.md"]]') == "[[concept_note.md]]"
    assert clean_wikilink_quotes('[[note_without_quotes]]') == "[[note_without_quotes]]"
    assert clean_wikilink_quotes('`[[concept_note|[1]]]`') == "[[concept_note|[1]]]"
    assert clean_wikilink_quotes('`[[slug]]`') == "[[slug]]"
    assert clean_wikilink_quotes('`![[image.png]]`') == "![[image.png]]"


# ── Hero Image Command Flow Tests (v8.13.0) ───────────────────────────────────

def test_parse_style_hero_image_triggers():
    """Verify /hero-image, /hero, and /banner all route to hero-image style."""
    from services.command.styles import parse_style

    assert parse_style("/hero-image [[kien_truc_he_thong]]") == ("hero-image", "[[kien_truc_he_thong]]")
    assert parse_style("/hero [[kien_truc_he_thong]]") == ("hero-image", "[[kien_truc_he_thong]]")
    assert parse_style("/banner [[kien_truc_he_thong]]") == ("hero-image", "[[kien_truc_he_thong]]")
    assert parse_style("/hero-image") == ("hero-image", "")
    assert parse_style("/hero") == ("hero-image", "")


def test_find_topic_note(tmp_path):
    """find_topic_note should resolve wikilinks, exact filenames, and normalized stems."""
    from services.command.hero_image import find_topic_note

    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "deep_module_design.md").write_text("# Deep Module\n", encoding="utf-8")

    # Wikilink match
    slug, path = find_topic_note("[[deep_module_design]]", topics_dir)
    assert slug == "deep_module_design"
    assert path == topics_dir / "deep_module_design.md"

    # Wikilink with display alias
    slug, path = find_topic_note("[[deep_module_design|Thiết Kế]]", topics_dir)
    assert slug == "deep_module_design"
    assert path == topics_dir / "deep_module_design.md"

    # Missing note returns slug and None
    slug, path = find_topic_note("[[non_existent_topic]]", topics_dir)
    assert slug == "non_existent_topic"
    assert path is None

    # Multi-wikilink: should skip non-topic and resolve existing topic note
    multi_query = "Xem [[concept_khac]] để viết tiếp cho topic [[deep_module_design]]"
    slug, path = find_topic_note(multi_query, topics_dir)
    assert slug == "deep_module_design"
    assert path == topics_dir / "deep_module_design.md"

    # Alias / Title resolution in topic note frontmatter
    alias_topic = topics_dir / "kien_truc_phan_tan.md"
    alias_topic.write_text(
        "---\ntitle: Distributed Architecture\naliases:\n  - He Thong Phan Tan\n---\n\n# Distributed Architecture",
        encoding="utf-8",
    )
    slug, path = find_topic_note("He Thong Phan Tan", topics_dir)
    assert slug == "kien_truc_phan_tan"
    assert path == alias_topic


def test_embed_hero_image_in_topic_beneath_h1():
    """embed_hero_image_in_topic should place embed tag directly beneath H1 heading."""
    from services.command.hero_image import embed_hero_image_in_topic

    original = (
        "---\n"
        "title: Kiến Trúc Phần Mềm\n"
        "---\n\n"
        "# Kiến Trúc Phần Mềm\n\n"
        "Nội dung phân tích mở đầu.\n"
    )
    expected = (
        "---\n"
        "title: Kiến Trúc Phần Mềm\n"
        "---\n\n"
        "# Kiến Trúc Phần Mềm\n\n"
        "![[kien_truc_phan_mem_hero.jpg|100%]]\n\n"
        "Nội dung phân tích mở đầu.\n"
    )
    result = embed_hero_image_in_topic(original, "kien_truc_phan_mem_hero.jpg")
    assert result == expected


def test_embed_hero_image_in_topic_idempotent():
    """embed_hero_image_in_topic should not duplicate embed if already present."""
    from services.command.hero_image import embed_hero_image_in_topic

    content_with_hero = (
        "# AI Agents\n\n"
        "![[ai_agents_hero.jpg|100%]]\n\n"
        "Giới thiệu về AI Agents.\n"
    )
    assert embed_hero_image_in_topic(content_with_hero, "ai_agents_hero.jpg") == content_with_hero


def test_embed_hero_image_in_topic_fallback_frontmatter():
    """embed_hero_image_in_topic falls back to placing after frontmatter if no H1."""
    from services.command.hero_image import embed_hero_image_in_topic

    no_h1 = (
        "---\n"
        "title: Untitled\n"
        "---\n\n"
        "Chỉ có nội dung không có H1.\n"
    )
    result = embed_hero_image_in_topic(no_h1, "untitled_hero.jpg")
    assert "![[untitled_hero.jpg|100%]]" in result
    assert result.startswith("---\ntitle: Untitled\n---\n\n![[untitled_hero.jpg|100%]]")


def test_embed_hero_image_in_topic_crlf_safety():
    """embed_hero_image_in_topic must preserve frontmatter without corruption on Windows CRLF."""
    from services.command.hero_image import embed_hero_image_in_topic

    # Case 1: CRLF with H1
    crlf_h1 = "---\r\ntitle: CRLF Note\r\n---\r\n\r\n# CRLF Heading\r\n\r\nBody text."
    res1 = embed_hero_image_in_topic(crlf_h1, "crlf_hero.jpg")
    assert res1.startswith("---\r\ntitle: CRLF Note\r\n---\r\n\r\n# CRLF Heading\n\n![[crlf_hero.jpg|100%]]\n\nBody text.")

    # Case 2: CRLF without H1 (must NOT prepend before frontmatter!)
    crlf_no_h1 = "---\r\ntitle: CRLF No H1\r\n---\r\n\r\nBody without heading."
    res2 = embed_hero_image_in_topic(crlf_no_h1, "crlf_no_h1_hero.jpg")
    assert not res2.startswith("![[crlf_no_h1_hero.jpg")
    assert res2.startswith("---\r\ntitle: CRLF No H1\r\n---\n\n![[crlf_no_h1_hero.jpg|100%]]\n\nBody without heading.")


def test_extract_image_prompt():
    """extract_image_prompt should extract prompt block from various LLM response formats."""
    from services.command.hero_image import extract_image_prompt

    resp1 = (
        "Phân tích ý niệm thị giác:\n"
        "Một không gian kiến trúc tối giản.\n\n"
        "### Final Image Prompt\n"
        "A cinematic 16:9 render of a towering monolithic crystal structure with volumetric light shafts, octan render, 8k.\n\n"
        "---\n"
        "Hy vọng gợi ý này hữu ích."
    )
    assert "A cinematic 16:9 render" in extract_image_prompt(resp1)

    resp2 = (
        "Prompt: An architectural blueprint floating in a dark ethereal void with cyan glowing vector lines, 16:9 aspect ratio.\n"
    )
    assert "An architectural blueprint" in extract_image_prompt(resp2)

    # Prompt inside code fence
    resp3 = (
        "Phân tích:\n\n"
        "### Final Image Prompt\n"
        "```\n"
        "A high-contrast cinematic 16:9 photograph of an intricate geometric labyrinth in misty morning light.\n"
        "```\n"
    )
    p3 = extract_image_prompt(resp3)
    assert "A high-contrast cinematic 16:9 photograph" in p3
    assert "```" not in p3


def test_handle_command_hero_image_flow(tmp_path, monkeypatch):
    """End-to-end: handle_command with /hero-image extracts topic, generates image, embeds in topic, and writes response."""
    import dataclasses
    from core.config import cfg
    from services.command.coordinator import handle_command
    from services.command.hero_image import set_custom_image_generator

    # Setup directories
    vault_root = tmp_path / "vault"
    cmd_file = vault_root / "00 - Maps of Content" / "Command.md"
    cmd_file.parent.mkdir(parents=True, exist_ok=True)
    topics_dir = vault_root / "04 - Permanent" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    attach_dir = vault_root / "03 - Resources" / "attachments"
    attach_dir.mkdir(parents=True, exist_ok=True)

    # Create topic note
    topic_file = topics_dir / "kien_truc_deep_module.md"
    topic_file.write_text(
        "---\ntitle: Kiến Trúc Deep Module\n---\n\n# Kiến Trúc Deep Module\n\nNội dung bài viết về Deep Module.",
        encoding="utf-8",
    )

    # Create Command.md inbox query
    cmd_content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: /hero-image [[kien_truc_deep_module]] ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(cmd_content, encoding="utf-8")

    # Mock config
    mock_cfg = dataclasses.replace(
        cfg,
        vault_root=vault_root,
        command_file=cmd_file,
        attachments_dir=attach_dir,
    )
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)
    monkeypatch.setattr("services.command.hero_image.cfg", mock_cfg)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    # Mock LLM
    def mock_llm(prompt, task="general"):
        return (
            "Phân tích thị giác: Tượng trưng cho module sâu.\n\n"
            "### Final Image Prompt\n"
            "A cinematic 16:9 photographic visualization of an iceberg in dark ocean, moody dramatic lighting, 8k.\n"
        )

    monkeypatch.setattr("services.command.call_llm", mock_llm)
    monkeypatch.setattr("services.command.coordinator.call_llm", mock_llm)
    monkeypatch.setattr("services.command.hero_image.call_llm", mock_llm)

    # Mock image generator to create file and return True
    def dummy_generator(prompt, output_path):
        output_path.write_bytes(b"dummy_image_data")
        return True

    set_custom_image_generator(dummy_generator)

    try:
        handle_command(command_file=cmd_file)

        # 1. Image was generated and saved to attachments
        expected_img = attach_dir / "kien_truc_deep_module_hero.jpg"
        assert expected_img.exists()
        assert expected_img.read_bytes() == b"dummy_image_data"

        # 2. Topic note was updated with embed tag beneath H1
        updated_topic = topic_file.read_text(encoding="utf-8")
        assert "# Kiến Trúc Deep Module\n\n![[kien_truc_deep_module_hero.jpg|100%]]" in updated_topic

        # 3. Command.md was updated with response and preview embed
        updated_cmd = cmd_file.read_text(encoding="utf-8")
        assert "@AI:  ---" in updated_cmd
        assert "![[kien_truc_deep_module_hero.jpg|100%]]" in updated_cmd
        assert "Phân tích thị giác" in updated_cmd
    finally:
        set_custom_image_generator(None)


def test_handle_command_hero_image_offline_fallback(tmp_path, monkeypatch):
    """handle_command with /hero-image when image generator is unavailable still delivers prompt without crashing."""
    import dataclasses
    from core.config import cfg
    from services.command.coordinator import handle_command
    from services.command.hero_image import set_custom_image_generator

    vault_root = tmp_path / "vault"
    cmd_file = vault_root / "00 - Maps of Content" / "Command.md"
    cmd_file.parent.mkdir(parents=True, exist_ok=True)
    attach_dir = vault_root / "03 - Resources" / "attachments"
    attach_dir.mkdir(parents=True, exist_ok=True)

    cmd_content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: /hero Concept Không Có Topic Sẵn ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(cmd_content, encoding="utf-8")

    mock_cfg = dataclasses.replace(
        cfg,
        vault_root=vault_root,
        command_file=cmd_file,
        attachments_dir=attach_dir,
    )
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)
    monkeypatch.setattr("services.command.hero_image.cfg", mock_cfg)
    monkeypatch.setattr("services.command.cfg", mock_cfg)

    def mock_llm(prompt, task="general"):
        return (
            "Ý niệm thị giác: Bố cục trừu tượng.\n\n"
            "### Final Image Prompt\n"
            "A wide 16:9 architectural rendering with glowing isometric grid.\n"
        )

    monkeypatch.setattr("services.command.call_llm", mock_llm)
    monkeypatch.setattr("services.command.coordinator.call_llm", mock_llm)
    monkeypatch.setattr("services.command.hero_image.call_llm", mock_llm)
    monkeypatch.setattr("services.command.hero_image.build_rag_context", lambda q: ("", {}))

    # Force generator to return False (offline/no endpoint)
    set_custom_image_generator(lambda p, o: False)

    try:
        handle_command(command_file=cmd_file)

        updated_cmd = cmd_file.read_text(encoding="utf-8")
        assert "@AI:  ---" in updated_cmd
        assert "Hero Banner Placeholder" in updated_cmd
        assert "A wide 16:9 architectural rendering" in updated_cmd
    finally:
        set_custom_image_generator(None)


# ── Refactoring Deepening Tests (v8.13.2) ──────────────────────────────────────

def test_chat_history_backward_compatibility_shim():
    """Verify chat_history shim re-exports exact objects from services.command.inbox."""
    import services.chat_history as ch
    import services.command.inbox as inbox

    assert ch.MAX_COMMAND_LEN == inbox.MAX_COMMAND_LEN
    assert ch.INPUT_MARKER == inbox.INPUT_MARKER
    assert ch.HISTORY_MARKER == inbox.HISTORY_MARKER
    assert ch.QUERY_PATTERN == inbox.QUERY_PATTERN
    assert ch.extract_sections is inbox.extract_sections
    assert ch.auto_archive_command is inbox.auto_archive_command


def test_handle_command_multi_query_drainage_loop(tmp_path, monkeypatch):
    """handle_command must process all pending queries in a single invocation (drainage loop)."""
    import dataclasses
    from core.config import cfg
    from services.command import handle_command, INPUT_MARKER, HISTORY_MARKER

    cmd_file = tmp_path / "Command.md"
    content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: Query One ---\n\n"
        "Draft note: ghi chú quan trọng ở giữa.\n\n"
        "@AI: /fast Query Two ---\n\n"
        "@AI: Query Three ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, command_file=cmd_file, vault_root=tmp_path)
    monkeypatch.setattr("services.command.cfg", mock_cfg)
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)

    # Track queries received by LLM
    llm_queries = []

    def mock_call_llm(prompt: str, task: str = "default") -> str:
        for q in ["Query One", "Query Two", "Query Three"]:
            if q in prompt:
                llm_queries.append(q)
                return f"Answer for {q}"
        return "Generic answer"

    monkeypatch.setattr("services.command.call_llm", mock_call_llm)
    monkeypatch.setattr("services.command.coordinator.call_llm", mock_call_llm)

    # Run handle_command: should drain all 3 queries
    processed = handle_command(command_file=cmd_file)

    assert processed == 3
    assert len(llm_queries) == 3
    assert "Query One" in llm_queries
    assert "Query Two" in llm_queries
    assert "Query Three" in llm_queries

    final_text = cmd_file.read_text(encoding="utf-8")
    from services.command.inbox import extract_sections
    before, inbox, after = extract_sections(final_text)

    # All 3 queries should have been cleared from Inbox
    assert "@AI: Query One ---" not in inbox
    assert "@AI: /fast Query Two ---" not in inbox
    assert "@AI: Query Three ---" not in inbox

    # User draft note must be preserved intact in inbox
    assert "Draft note: ghi chú quan trọng ở giữa." in inbox

    # All 3 answers and query logs must be recorded in History (after)
    assert "@AI: Query One ---" in after
    assert "@AI: /fast Query Two ---" in after
    assert "@AI: Query Three ---" in after
    assert "Answer for Query One" in after
    assert "Answer for Query Two" in after
    assert "Answer for Query Three" in after


def test_handle_command_max_queries_cap(tmp_path, monkeypatch):
    """handle_command should respect max_queries safety cap to prevent infinite loops."""
    import dataclasses
    from core.config import cfg
    from services.command import handle_command, INPUT_MARKER, HISTORY_MARKER

    cmd_file = tmp_path / "Command.md"
    content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: Q1 ---\n\n"
        "@AI: Q2 ---\n\n"
        "@AI: Q3 ---\n\n"
        "@AI: Q4 ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, command_file=cmd_file, vault_root=tmp_path)
    monkeypatch.setattr("services.command.cfg", mock_cfg)
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)
    monkeypatch.setattr("services.command.call_llm", lambda p, task="default": "Answer")
    monkeypatch.setattr("services.command.coordinator.call_llm", lambda p, task="default": "Answer")

    # Set safety cap to 2
    processed = handle_command(command_file=cmd_file, max_queries=2)
    assert processed == 2


def test_hero_image_generator_respects_active_cfg(tmp_path, monkeypatch):
    """generate_hero_image must use active_cfg instead of bypassing it."""
    import dataclasses
    from core.config import cfg
    from services.command.hero_image import generate_hero_image

    output_path = tmp_path / "test_hero.jpg"

    # Config with no gateway endpoint
    mock_cfg_no_gw = dataclasses.replace(cfg, gateway_url=None, gateway_api_key=None)
    res = generate_hero_image("prompt", output_path, active_cfg=mock_cfg_no_gw)
    assert res is False


def test_heal_artifact_embed_syntax():
    """heal_artifact_embed_syntax must fix snake_cased diagram extensions in wikilinks."""
    from services.command.citations import heal_artifact_embed_syntax, clean_wikilink_quotes

    sample = (
        "Check this: ![[architecture_excalidraw_md|100%]]\n"
        "And this: ![[flow_mermaid_md]]\n"
        "And vector: ![[system_d2_svg|800]]\n"
    )
    healed = heal_artifact_embed_syntax(sample)
    assert "![[architecture.excalidraw.md|100%]]" in healed
    assert "![[flow.mermaid.md]]" in healed
    assert "![[system.d2.svg|800]]" in healed

    # clean_wikilink_quotes should also call heal_artifact_embed_syntax
    quoted = 'See ![["overview_excalidraw_md|100%"]]'
    cleaned = clean_wikilink_quotes(quoted)
    assert "![[overview.excalidraw.md|100%]]" in cleaned


def test_heal_mermaid_edge_syntax():
    """heal_mermaid_edge_syntax must convert hallucinated edge syntax to valid pipe labels and normalize operators."""
    from services.command.citations import heal_mermaid_edge_syntax

    # 1. Thick forward edge: ===="label"====> -> ===>|"label"|
    sample_thick = 'HUB ===="Tái cấu trúc SOP"====> SPOKES'
    assert heal_mermaid_edge_syntax(sample_thick) == 'HUB ===>|"Tái cấu trúc SOP"| SPOKES'

    # 2. Dotted edge: -."label".-> or -."label"-.-> -> -.->|"label"|
    sample_dotted = 'SPOKES -."Phản hồi"-.-> HUB'
    assert heal_mermaid_edge_syntax(sample_dotted) == 'SPOKES -.->|"Phản hồi"| HUB'
    sample_dotted_short = 'SPOKES -."Phản hồi".-> HUB'
    assert heal_mermaid_edge_syntax(sample_dotted_short) == 'SPOKES -.->|"Phản hồi"| HUB'

    # 3. Bidirectional thick edge: <===="label"====> -> <===>|"label"|
    sample_bidi = 'NODE_A <===="Đồng bộ 2 chiều"====> NODE_B'
    assert heal_mermaid_edge_syntax(sample_bidi) == 'NODE_A <===>|"Đồng bộ 2 chiều"| NODE_B'

    # 4. Operator normalization: >= -> ≥, <= -> ≤
    sample_ops = 'ROUTER ===="Độ phức tạp >= 8 và chi phí <= 10"====> T1'
    assert heal_mermaid_edge_syntax(sample_ops) == 'ROUTER ===>|"Độ phức tạp ≥ 8 và chi phí ≤ 10"| T1'


def test_heal_html_entity_leakage():
    """heal_html_entity_leakage must preserve #40; / #41; inside Mermaid while reverting outside."""
    from services.command.citations import heal_html_entity_leakage, clean_wikilink_quotes

    sample = (
        "| Cột 1 | Cột 2 #40;Ghi chú#41; |\n"
        "|---|---|\n"
        "| Dữ liệu #40;VN#41; | Giá trị |\n"
        "\n"
        "```mermaid\n"
        "graph TD\n"
        "    NODE[\"<div align='left'>• Điểm 1 #40;A#41;</div>\"]\n"
        "    A ====\"Nhãn >= 5\"====> B\n"
        "```\n"
        "\n"
        "Đoạn văn ngoài bảng #40;chú thích#41;.\n"
    )

    healed = heal_html_entity_leakage(sample)
    # Outside mermaid: entities reverted
    assert "| Cột 1 | Cột 2 (Ghi chú) |" in healed
    assert "| Dữ liệu (VN) | Giá trị |" in healed
    assert "Đoạn văn ngoài bảng (chú thích)." in healed
    assert "#40;" not in healed.split("```mermaid")[0]
    assert "#40;" not in healed.split("```\n\n")[1]

    # Inside mermaid: #40; preserved, edge healed, operator normalized
    mermaid_block = healed.split("```mermaid")[1].split("```")[0]
    assert "#40;A#41;" in mermaid_block
    assert '===>|"Nhãn ≥ 5"|' in mermaid_block

    # clean_wikilink_quotes calls heal_html_entity_leakage
    cleaned = clean_wikilink_quotes(sample)
    assert "| Cột 1 | Cột 2 (Ghi chú) |" in cleaned

