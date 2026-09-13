"""Tests for Command Module & Workers Upgrades (P0 + P1 package).

Covers:
1. Explicit wikilink resolution and prioritized hybrid RAG context building.
2. Dual-scope diagram context (target section + full article up to 12,000 chars).
3. Style parsing with multi-prefix speed overrides (/fast, /quick, /nhanh).
4. Cognitive task routing (reasoning vs synthesis) in coordinator.
5. Synthesis task routing in mermaid and vision QC workers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts directory is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import cfg
from services.command.styles import parse_style, StyleParseResult
from services.command.coordinator import generate_response, process_command, handle_command
from services.diagram_base import find_diagram_context
from services.rag_builder import resolve_explicit_references, build_rag_context


# ── 1. Explicit Wikilink Resolution ──────────────────────────────────────────


def test_resolve_explicit_references_priority_and_parsing():
    """Should resolve explicit wikilinks according to directory priority: topics > sources > concepts > MOC."""
    vault_root = cfg.vault_root
    topics_dir = vault_root / "04 - Permanent" / "topics"
    sources_dir = vault_root / "04 - Permanent" / "sources"
    concepts_dir = vault_root / "04 - Permanent" / "concepts"
    moc_dir = vault_root / "00 - Maps of Content"

    for d in (topics_dir, sources_dir, concepts_dir, moc_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Same stem in topics and concepts -> topics wins
    (topics_dir / "kien_truc.md").write_text(
        "---\ntitle: \"Kiến Trúc Topic\"\nsummary: \"Tóm tắt topic\"\ntags: [arch, system]\n---\n\nNội dung topic chi tiết.",
        encoding="utf-8",
    )
    (concepts_dir / "kien_truc.md").write_text(
        "---\ntitle: \"Kiến Trúc Concept\"\n---\n\nNội dung concept.",
        encoding="utf-8",
    )

    # 2. File in MOC
    (moc_dir / "moc_system.md").write_text(
        "---\ntitle: \"MOC System\"\n---\n\nMOC index body.",
        encoding="utf-8",
    )

    query = "Hãy phân tích [[kien_truc|Kiến trúc tổng thể]] và đối chiếu với [[moc_system.md]]"
    docs = resolve_explicit_references(query, max_docs=2)

    assert len(docs) == 2
    # First doc should be from topics
    assert docs[0]["source_file"] == "kien_truc.md"
    assert docs[0]["title"] == "Kiến Trúc Topic"
    assert docs[0]["summary"] == "Tóm tắt topic"
    assert docs[0]["tags"] == ["arch", "system"]
    assert "Nội dung topic chi tiết." in docs[0]["body"]
    assert docs[0]["priority"] == "explicit_user_reference"

    # Second doc should be from MOC
    assert docs[1]["source_file"] == "moc_system.md"
    assert docs[1]["title"] == "MOC System"
    assert "MOC index body." in docs[1]["body"]


def test_resolve_explicit_references_cap_and_truncation():
    """Should limit resolved explicit documents to max_docs and truncate long bodies to 3,500 chars."""
    vault_root = cfg.vault_root
    topics_dir = vault_root / "04 - Permanent" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)

    long_body = "A" * 6000
    (topics_dir / "long_doc.md").write_text(f"---\ntitle: \"Long\"\n---\n\n{long_body}", encoding="utf-8")
    (topics_dir / "doc2.md").write_text("Content 2", encoding="utf-8")
    (topics_dir / "doc3.md").write_text("Content 3", encoding="utf-8")

    query = "Xem [[long_doc]], [[doc2]] và [[doc3]]"
    docs = resolve_explicit_references(query, max_docs=2)

    assert len(docs) == 2
    assert docs[0]["source_file"] == "long_doc.md"
    assert len(docs[0]["body"]) == 3500


def test_build_rag_context_prioritized_hybrid_and_deduplication(monkeypatch):
    """build_rag_context should place explicit docs at top and deduplicate them from hybrid search."""
    vault_root = cfg.vault_root
    topics_dir = vault_root / "04 - Permanent" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)

    (topics_dir / "ref_doc.md").write_text(
        "---\ntitle: \"Ref Doc\"\nsummary: \"Explicit summary\"\n---\n\nExplicit body text.",
        encoding="utf-8",
    )

    from services.rag_search import SearchResult

    searched_queries = []

    def mock_search(query_str: str, top_k: int = 25):
        searched_queries.append(query_str)
        return [
            # Same file returned by search (duplicate)
            SearchResult(
                text="---\ntitle: \"Ref Doc\"\n---\n\nExplicit body text.",
                source_file="ref_doc.md",
                score=0.9,
                method="hybrid",
            ),
            # New file
            SearchResult(
                text="---\ntitle: \"Other Note\"\n---\n\nOther body text.",
                source_file="other_note.md",
                score=0.8,
                method="hybrid",
            ),
        ]

    monkeypatch.setattr("services.rag_builder._rag_search", mock_search)

    query = "Đọc [[ref_doc|Tài liệu tham khảo]] và giải thích hệ thống"
    ctx, refs = build_rag_context(query)

    # 1. Clean query passed to hybrid search
    assert len(searched_queries) == 1
    assert "[[ref_doc|Tài liệu tham khảo]]" not in searched_queries[0]
    assert "Tài liệu tham khảo" in searched_queries[0]

    # 2. Context starts with explicit doc
    assert 'priority="explicit_user_reference"' in ctx
    assert '<document id="1" file="ref_doc.md"' in ctx

    # 3. Deduplication: ref_doc.md is NOT added a second time
    assert ctx.count('file="ref_doc.md"') == 1
    assert '<document id="2" file="other_note.md"' in ctx
    assert len(refs) == 2


# ── 2. Dual-Scope Diagram Context ────────────────────────────────────────────


def test_dual_scope_diagram_context_structure():
    """find_diagram_context should generate dual-scope context with target section and full response context."""
    source_text = (
        "# Báo Cáo Hệ Thống\n\n"
        "## 1. Giới Thiệu Tổng Quan\n"
        "Nội dung giới thiệu tổng quan hệ thống.\n\n"
        "## 2. Thiết Kế Kiến Trúc Chi Tiết\n"
        "Phân tích kiến trúc vi dịch vụ và cơ chế đồng bộ:\n"
        "![[kien_truc_he_thong.mermaid.md|100%]]\n"
        "Chi tiết luồng xử lý giữa các thành phần.\n\n"
        "## 3. Đánh Giá & Kết Luận\n"
        "Đánh giá hiệu năng và kết luận cuối cùng."
    )

    ctx = find_diagram_context("kien_truc_he_thong.mermaid.md", source_text)

    # Must contain both scope markers
    assert "=== [TARGET SECTION (Trọng tâm sơ đồ)] ===" in ctx
    assert "=== [FULL ARTICLE CONTEXT (Toàn bộ bài viết tham chiếu)] ===" in ctx

    target_part, full_part = ctx.split("=== [FULL ARTICLE CONTEXT (Toàn bộ bài viết tham chiếu)] ===")

    # Target part must contain section 2 and its embed
    assert "## 2. Thiết Kế Kiến Trúc Chi Tiết" in target_part
    assert "![[kien_truc_he_thong.mermaid.md|100%]]" in target_part
    assert "## 3. Đánh Giá & Kết Luận" not in target_part
    assert "## 1. Giới Thiệu Tổng Quan" not in target_part

    # Full part must contain the entire document
    assert "## 1. Giới Thiệu Tổng Quan" in full_part
    assert "## 2. Thiết Kế Kiến Trúc Chi Tiết" in full_part
    assert "## 3. Đánh Giá & Kết Luận" in full_part


def test_dual_scope_diagram_context_length_cap():
    """find_diagram_context full article context should be capped at 12,000 characters."""
    padding = "Dòng phân tích mở rộng nội dung bài viết. " * 300  # ~13,000 chars
    source_text = (
        "## Phần Mở Đầu\n"
        "![[so_do_tong_hop.excalidraw.md|100%]]\n"
        "Nội dung trọng tâm.\n\n"
        "## Phần Mở Rộng\n"
        f"{padding}"
    )
    assert len(source_text) > 12000

    ctx = find_diagram_context("so_do_tong_hop.excalidraw.md", source_text)
    _, full_part = ctx.split("=== [FULL ARTICLE CONTEXT (Toàn bộ bài viết tham chiếu)] ===")
    assert len(full_part.strip()) <= 12000


def test_dual_scope_diagram_context_fallback_and_plain():
    """find_diagram_context should preserve fallback matching by heading keywords and plain text handling."""
    # 1. Fallback to heading when placeholder is absent
    text_no_placeholder = (
        "## Bối Cảnh\nText bối cảnh.\n\n"
        "## Luồng Dữ Liệu Tự Động\nChi tiết luồng tự động.\n\n"
        "## Kết Thúc\nHết."
    )
    ctx_fallback = find_diagram_context("luong_du_lieu_tu_dong.mermaid.md", text_no_placeholder)
    assert "## Luồng Dữ Liệu Tự Động" in ctx_fallback

    # 2. Plain text without any headings (preserves ±500 char window)
    plain_text = "Dữ liệu trước. " * 50 + "![[plain_diagram.excalidraw.md]]" + " Dữ liệu sau. " * 50
    ctx_plain = find_diagram_context("plain_diagram.excalidraw.md", plain_text)
    assert "![[plain_diagram.excalidraw.md]]" in ctx_plain
    assert len(ctx_plain) < len(plain_text)


# ── 3. Style Parsing & Speed Overrides ───────────────────────────────────────


def test_parse_style_speed_overrides():
    """parse_style should detect /fast, /quick, /nhanh overrides and return StyleParseResult."""
    # 1. Standalone speed prefixes
    s1, q1, f1 = parse_style("/fast Tóm tắt nhanh")
    assert s1 == "fast" and q1 == "Tóm tắt nhanh" and f1 is True

    s2, q2, f2 = parse_style("/quick Trả lời một câu")
    assert s2 == "fast" and q2 == "Trả lời một câu" and f2 is True

    s3, q3, f3 = parse_style("/nhanh Đi thẳng vào vấn đề")
    assert s3 == "fast" and q3 == "Đi thẳng vào vấn đề" and f3 is True

    # 2. Multi-prefix combinations: primary style + speed override
    s4, q4, f4 = parse_style("/academic /fast Phân tích kinh tế vĩ mô")
    assert s4 == "academic" and q4 == "Phân tích kinh tế vĩ mô" and f4 is True

    s5, q5, f5 = parse_style("/quick /academic Phân tích kinh tế vĩ mô")
    assert s5 == "academic" and q5 == "Phân tích kinh tế vĩ mô" and f5 is True

    s6, q6, f6 = parse_style("/tim-urban /nhanh Tại sao chúng ta trì hoãn")
    assert s6 == "tim-urban" and q6 == "Tại sao chúng ta trì hoãn" and f6 is True

    # 3. Standard style without speed override
    s7, q7, f7 = parse_style("/academic Luận điểm nghiên cứu")
    assert s7 == "academic" and q7 == "Luận điểm nghiên cứu" and f7 is False

    s8, q8, f8 = parse_style("/debate Hai góc nhìn đối lập")
    assert s8 == "debate" and q8 == "Hai góc nhìn đối lập" and f8 is False

    # 4. Default query
    s9, q9, f9 = parse_style("Câu hỏi thông thường không có tiền tố")
    assert s9 == "professional" and q9 == "Câu hỏi thông thường không có tiền tố" and f9 is False

    # 5. Word boundary preservation
    s10, q10, f10 = parse_style("/fasten the screws tightly")
    assert s10 == "professional" and q10 == "/fasten the screws tightly" and f10 is False


def test_parse_style_backward_compatibility():
    """parse_style return value should support 2-item unpacking and tuple equality."""
    # 2-item unpacking
    style, clean = parse_style("/tim-urban Giải thích AI")
    assert style == "tim-urban"
    assert clean == "Giải thích AI"

    # 2-item tuple equality (used by existing tests)
    assert parse_style("/hero-image [[kien_truc]]") == ("hero-image", "[[kien_truc]]")
    assert ("hero-image", "[[kien_truc]]") == parse_style("/hero-image [[kien_truc]]")

    # 3-item tuple equality
    assert parse_style("/hero-image [[kien_truc]]") == ("hero-image", "[[kien_truc]]", False)

    # Attribute access
    res = parse_style("/debate /fast Tranh luận")
    assert res.style_name == "debate"
    assert res.clean_query == "Tranh luận"
    assert res.is_fast is True


# ── 4. Coordinator Cognitive Task Routing ────────────────────────────────────


def test_coordinator_task_routing(monkeypatch):
    """generate_response should route deep reasoning styles to reasoning and creative/fast styles to synthesis."""
    recorded_tasks = []

    def mock_call_llm(prompt: str, task: str = "reasoning", **kwargs):
        recorded_tasks.append(task)
        return "Mocked response text."

    monkeypatch.setattr("services.command.coordinator._get_active_call_llm", lambda: mock_call_llm)

    # 1. Deep reasoning group (without speed override) -> task="reasoning"
    for deep_style in ("academic", "debate", "sparring", "professional"):
        recorded_tasks.clear()
        generate_response("Query", deep_style, "Context", is_fast=False)
        assert recorded_tasks == ["reasoning"], f"Style {deep_style} should use task='reasoning'"

    # 2. Deep reasoning group WITH speed override (is_fast=True) -> task="synthesis"
    for deep_style in ("academic", "debate", "sparring", "professional"):
        recorded_tasks.clear()
        generate_response("Query", deep_style, "Context", is_fast=True)
        assert recorded_tasks == ["synthesis"], f"Style {deep_style} with is_fast=True should use task='synthesis'"

    # 3. Creative / explanatory group -> task="synthesis"
    for creative_style in ("tim-urban", "eli5", "storyteller", "bullet", "socratic", "fast", "hero-image"):
        recorded_tasks.clear()
        generate_response("Query", creative_style, "Context", is_fast=False)
        assert recorded_tasks == ["synthesis"], f"Style {creative_style} should use task='synthesis'"


def test_process_command_alias():
    """process_command should be an alias of handle_command."""
    assert process_command is handle_command


# ── 5. Workers Task Routing ──────────────────────────────────────────────────


def test_mermaid_worker_task_synthesis(monkeypatch):
    """_generate_mermaid should call LLM with task='synthesis'."""
    from services.mermaid_worker import _generate_mermaid

    called_task = None

    def mock_call_llm(prompt: str, task: str = "reasoning", **kwargs):
        nonlocal called_task
        called_task = task
        return "flowchart TD\n  A --> B"

    monkeypatch.setattr("services.mermaid_worker.call_llm", mock_call_llm)
    monkeypatch.setattr("services.mermaid_worker.save_diagram_file", lambda *args, **kwargs: None)

    _generate_mermaid("test_diagram.mermaid.md", "## Section\n![[test_diagram.mermaid.md]]\nContext")
    assert called_task == "synthesis"


def test_vision_qc_worker_task_synthesis(monkeypatch):
    """_generate_qc should call LLM with task='synthesis'."""
    from services.vision_qc_worker import _generate_qc

    called_task = None

    def mock_call_llm(prompt: str, task: str = "reasoning", **kwargs):
        nonlocal called_task
        called_task = task
        return (
            "<qc_table>\n"
            "| STT | Hạng mục | Tiêu chuẩn | Kết quả |\n"
            "|---|---|---|---|\n"
            "| 1 | Bê tông móng | TCVN 5574 | Đạt |\n"
            "</qc_table>"
        )

    monkeypatch.setattr("services.vision_qc_worker.call_llm", mock_call_llm)

    _generate_qc("audit_matrix.csv", "Bối cảnh kiểm tra bê tông.", "Kiểm tra chất lượng móng")
    assert called_task == "synthesis"


# ── 6. Robustness & Edge-Case Regressions ─────────────────────────────────────


def test_resolve_explicit_references_crlf_and_headings_and_subpaths():
    """Should cleanly strip Windows CRLF frontmatter, handle #headings, and resolve subpaths."""
    vault_root = cfg.vault_root
    concepts_dir = vault_root / "04 - Permanent" / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    # Windows CRLF file content
    crlf_content = "---\r\ntitle: \"Hệ Thống Phân Tán\"\r\nsummary: \"Tóm tắt CRLF\"\r\n---\r\n\r\nNội dung thân bài không chứa frontmatter."
    (concepts_dir / "he_thong_phan_tan.md").write_bytes(crlf_content.encode("utf-8"))

    # Test query with heading, alias, and subpath
    query = (
        "Đọc [[he_thong_phan_tan#Core Idea|Hệ thống]] "
        "và so sánh với [[04 - Permanent/concepts/he_thong_phan_tan.md#Bản Gốc]]"
    )
    docs = resolve_explicit_references(query, max_docs=2)

    assert len(docs) == 1  # Deduplicated to 1 unique doc
    assert docs[0]["source_file"] == "he_thong_phan_tan.md"
    assert docs[0]["title"] == "Hệ Thống Phân Tán"
    # Verify YAML was stripped completely even with CRLF
    assert "---" not in docs[0]["body"]
    assert "title:" not in docs[0]["body"]
    assert docs[0]["body"] == "Nội dung thân bài không chứa frontmatter."


def test_style_parse_result_self_equality_hash_and_slicing():
    """StyleParseResult should support self-equality, hashability, and slicing."""
    r1 = parse_style("/fast Tóm tắt")
    r2 = parse_style("/fast Tóm tắt")
    r3 = parse_style("/academic Tóm tắt")

    # 1. Self-equality between two StyleParseResult instances
    assert r1 == r2
    assert r1 != r3

    # 2. Hashability and set/dict membership
    assert hash(r1) == hash(r2)
    s = {r1}
    assert r2 in s
    assert r3 not in s

    # 3. Slicing support
    assert r1[0:2] == ("fast", "Tóm tắt")
    assert r1[:] == ("fast", "Tóm tắt", True)
    assert r1[-1] is True


def test_find_diagram_context_d2_variants_and_keyword_stripping():
    """find_diagram_context should support .d2 and .d2.svg and strip them in fallback keyword matching."""
    # 1. Explicit placeholder matching with .d2.svg and .d2
    source_text = (
        "# Hạ Tầng Kỹ Thuật\n\n"
        "## Kiến Trúc Gateway Microservices\n"
        "![[microservices_gateway.d2.svg|100%]]\n"
        "Chi tiết topology mạng.\n\n"
        "## Phần Kết\nHết."
    )
    ctx_svg = find_diagram_context("microservices_gateway.d2.svg", source_text)
    assert "=== [TARGET SECTION (Trọng tâm sơ đồ)] ===" in ctx_svg
    assert "![[microservices_gateway.d2.svg|100%]]" in ctx_svg

    ctx_d2 = find_diagram_context("microservices_gateway.d2", source_text)
    assert "=== [TARGET SECTION (Trọng tâm sơ đồ)] ===" in ctx_d2
    assert "![[microservices_gateway.d2.svg|100%]]" in ctx_d2

    # 2. Fallback heading keyword matching should strip .d2.svg cleanly
    source_no_embed = (
        "# Hệ Thống\n\n"
        "## Tổng Quan\nGiới thiệu.\n\n"
        "## Thiết Kế Mạng Lưới Phân Tán\nNội dung mạng lưới phân tán.\n\n"
        "## Tổng Kết\nHết."
    )
    ctx_fallback = find_diagram_context("mang_luoi_phan_tan.d2.svg", source_no_embed)
    assert "## Thiết Kế Mạng Lưới Phân Tán" in ctx_fallback


def test_coordinator_unknown_style_fallback(monkeypatch):
    """generate_response should gracefully fall back to professional when unknown style is passed."""
    called_prompt = None

    def mock_call_llm(prompt: str, task: str = "reasoning", **kwargs):
        nonlocal called_prompt
        called_prompt = prompt
        return "Fallback response"

    monkeypatch.setattr("services.command.coordinator._get_active_call_llm", lambda: mock_call_llm)

    resp = generate_response("Câu hỏi", "non_existent_style_xyz", "Ngữ cảnh")
    assert resp == "Fallback response"
    assert "Viết bằng phong cách khoa học, chuyên nghiệp" in called_prompt

