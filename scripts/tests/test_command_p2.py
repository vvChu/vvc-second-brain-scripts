"""Unit and integration tests for Command Module Sprint P2 upgrades.

Covers:
1. JIT URL Ingestion (URL detection, fetching, XML formatting, and RAG context integration).
2. UI Fallback Callout in Command.md when LLM generation fails (all tiers exhausted).
3. Diagram Fallback Placeholders for Mermaid, Excalidraw, and D2 workers.
4. Rich Metadata in Topic Note frontmatter (summary, related, status, tags).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import re
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts directory is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import cfg
from core.frontmatter import parse_frontmatter
from services.command.coordinator import (
    extract_and_fetch_urls,
    generate_response,
    handle_command,
    process_command,
)
from services.command.inbox import INPUT_MARKER, HISTORY_MARKER, extract_sections
from services.command.topic_saver import (
    build_topic_content,
    auto_save_topic,
    TOPIC_AUTO_SAVE_THRESHOLD,
)
from services.diagram_base import save_fallback_diagram
from services.mermaid_worker import _generate_mermaid
from services.excalidraw_worker import _generate_excalidraw
from services.d2_worker import _generate_d2


# ── 1. JIT URL Ingestion Tests ────────────────────────────────────────────────


def test_extract_and_fetch_urls_basic(monkeypatch):
    """Should extract URLs, call fetch_url, and format into XML external context."""
    def mock_fetch_url(url: str, visual: bool = False) -> str:
        if "example.com/ai" in url:
            return "# Trí Tuệ Nhân Tạo Hiện Đại\n\nNội dung bài viết chi tiết về AI."
        return ""

    monkeypatch.setattr("services.url_fetcher.fetch_url", mock_fetch_url)

    query = "Hãy phân tích bài viết tại https://example.com/ai và so sánh."
    xml_context, urls = extract_and_fetch_urls(query)

    assert urls == ["https://example.com/ai"]
    assert '<external_web_source url="https://example.com/ai" title="Trí Tuệ Nhân Tạo Hiện Đại">' in xml_context
    assert "Nội dung bài viết chi tiết về AI." in xml_context
    assert "</external_web_source>" in xml_context


def test_extract_and_fetch_urls_stripping_and_deduplication(monkeypatch):
    """Should clean trailing punctuation, deduplicate URLs, and handle multiple links."""
    fetched = []

    def mock_fetch_url(url: str, visual: bool = False) -> str:
        fetched.append(url)
        return f"Content for {url}"

    monkeypatch.setattr("services.url_fetcher.fetch_url", mock_fetch_url)

    query = (
        "Đọc bài https://link1.org/doc, sau đó đọc https://link1.org/doc (lặp lại) "
        "và cuối cùng là https://link2.org/item."
    )
    xml_context, urls = extract_and_fetch_urls(query)

    assert urls == ["https://link1.org/doc", "https://link2.org/item"]
    assert len(fetched) == 2
    assert "https://link1.org/doc" in xml_context
    assert "https://link2.org/item" in xml_context


def test_extract_and_fetch_urls_truncation_to_4000_chars(monkeypatch):
    """Extracted URL text should be capped at 4,000 characters."""
    very_long_article = "Bản tin công nghệ dài. " * 500  # > 10,000 chars

    monkeypatch.setattr("services.url_fetcher.fetch_url", lambda u, visual=False: very_long_article)

    query = "Tóm tắt https://news.example.com/long-read"
    xml_context, urls = extract_and_fetch_urls(query)

    assert len(urls) == 1
    # Check inner text length within XML tag
    match = re.search(r"<external_web_source[^>]*>\n(.*?)\n</external_web_source>", xml_context, re.DOTALL)
    assert match is not None
    extracted_text = match.group(1)
    assert len(extracted_text) <= 4000


def test_extract_and_fetch_urls_network_failure_resilience(monkeypatch):
    """Network errors in URL fetching should be logged and not crash processing."""
    def mock_failing_fetch(url: str, visual: bool = False) -> str:
        raise ConnectionError("Server unreachable")

    monkeypatch.setattr("services.url_fetcher.fetch_url", mock_failing_fetch)

    query = "Xem https://dead-link.com/error"
    xml_context, urls = extract_and_fetch_urls(query)

    assert xml_context == ""
    assert urls == []


def test_jit_url_integration_in_handle_command(tmp_path, monkeypatch):
    """handle_command should prepend extracted external URL context to rag_context."""
    vault_root = tmp_path / "vault"
    cmd_file = vault_root / "00 - Maps of Content" / "Command.md"
    cmd_file.parent.mkdir(parents=True, exist_ok=True)

    cmd_content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: Tóm tắt bài viết https://tech.io/deep-dive ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(cmd_content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, vault_root=vault_root, command_file=cmd_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)

    # Mock URL fetcher
    monkeypatch.setattr(
        "services.url_fetcher.fetch_url",
        lambda u, visual=False: "Nội dung bài viết chuyên sâu về kỹ thuật phần mềm.",
    )

    # Capture rag_context passed to generate_response
    captured_context = []

    def mock_generate_response(query, style_name, rag_context, is_fast=False):
        captured_context.append(rag_context)
        return "Tóm tắt hoàn tất cho bạn."

    monkeypatch.setattr("services.command.coordinator.generate_response", mock_generate_response)

    count = handle_command(command_file=cmd_file)
    assert count == 1
    assert len(captured_context) == 1
    assert '<external_web_source url="https://tech.io/deep-dive"' in captured_context[0]
    assert "Nội dung bài viết chuyên sâu" in captured_context[0]


# ── 2. UI Fallback Callout on LLM Failure Tests ──────────────────────────────


def test_ui_fallback_callout_on_llm_failure(tmp_path, monkeypatch):
    """When all LLM tiers fail (returning empty), handle_command should write an error callout to Command.md."""
    vault_root = tmp_path / "vault"
    cmd_file = vault_root / "00 - Maps of Content" / "Command.md"
    cmd_file.parent.mkdir(parents=True, exist_ok=True)

    cmd_content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: Câu hỏi quan trọng cần giải đáp ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(cmd_content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, vault_root=vault_root, command_file=cmd_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)

    # Simulate LLM complete failure
    monkeypatch.setattr("services.command.coordinator.generate_response", lambda *args, **kwargs: "")

    processed = handle_command(command_file=cmd_file)

    # Should count as processed (cleared from input with error response)
    assert processed == 1

    result_text = cmd_file.read_text(encoding="utf-8")
    before, inbox, after = extract_sections(result_text)

    # Query must be cleared from inbox
    assert "@AI: Câu hỏi quan trọng cần giải đáp ---" not in inbox
    assert "@AI:  ---" in inbox

    # Error callout must be in output
    assert "> [!danger] ⚠️ Lỗi kết nối mô hình LLM" in after
    assert "Không thể nhận phản hồi từ Gateway hoặc CLI" in after


def test_ui_fallback_callout_hero_image_failure(tmp_path, monkeypatch):
    """When /hero-image processing fails to generate any response, write fallback callout."""
    vault_root = tmp_path / "vault"
    cmd_file = vault_root / "00 - Maps of Content" / "Command.md"
    cmd_file.parent.mkdir(parents=True, exist_ok=True)

    cmd_content = (
        f"{INPUT_MARKER}\n\n"
        "@AI: /hero Sơ đồ không thể sinh ---\n\n"
        f"{HISTORY_MARKER}\n"
    )
    cmd_file.write_text(cmd_content, encoding="utf-8")

    mock_cfg = dataclasses.replace(cfg, vault_root=vault_root, command_file=cmd_file)
    monkeypatch.setattr("services.command.cfg", mock_cfg)
    monkeypatch.setattr("services.command.coordinator.cfg", mock_cfg)

    monkeypatch.setattr("services.command.coordinator.process_hero_image", lambda *a, **kw: (None, None, None))

    processed = handle_command(command_file=cmd_file)
    assert processed == 1

    result_text = cmd_file.read_text(encoding="utf-8")
    assert "> [!danger] ⚠️ Lỗi kết nối mô hình LLM" in result_text


# ── 3. Diagram Fallback Placeholders Tests ────────────────────────────────────


def test_save_fallback_diagram_mermaid(tmp_path, monkeypatch):
    """save_fallback_diagram for Mermaid should create a valid flowchart with red warning card."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    save_fallback_diagram("luong_xu_ly.mermaid.md", "Lỗi cú pháp Mermaid", "mermaid")

    out_file = attach_dir / "luong_xu_ly.mermaid.md"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert content.startswith("```mermaid\nflowchart TD\n")
    assert "⚠️ Không thể khởi tạo sơ đồ: Luong Xu Ly" in content
    assert "Lỗi cú pháp Mermaid" in content
    assert "style err fill:#fee2e2,stroke:#ef4444" in content


def test_save_fallback_diagram_excalidraw(tmp_path, monkeypatch):
    """save_fallback_diagram for Excalidraw should create valid excalidraw file with 8-char nanoids and valid JSON."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    save_fallback_diagram("kien_truc.excalidraw.md", "Lỗi JSON syntax", "excalidraw")

    out_file = attach_dir / "kien_truc.excalidraw.md"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")

    assert "excalidraw-plugin: parsed" in content
    assert "# Excalidraw Data" in content
    assert "## Text Elements" in content
    assert "^texterr1" in content

    # Check JSON validity
    json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    assert json_match is not None
    data = json.loads(json_match.group(1))
    assert data["type"] == "excalidraw"
    assert len(data["elements"]) == 2
    assert data["elements"][0]["id"] == "carderr1"
    assert data["elements"][1]["id"] == "texterr1"
    assert len(data["elements"][0]["id"]) == 8
    assert len(data["elements"][1]["id"]) == 8


def test_save_fallback_diagram_d2(tmp_path, monkeypatch):
    """save_fallback_diagram for D2 should save both valid standalone SVG and companion .d2 file."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    save_fallback_diagram("he_thong.d2.svg", "Lỗi biên dịch Kroki", "d2")

    svg_file = attach_dir / "he_thong.d2.svg"
    d2_file = attach_dir / "he_thong.d2"

    assert svg_file.exists()
    assert d2_file.exists()

    svg_content = svg_file.read_text(encoding="utf-8")
    assert svg_content.startswith("<svg")
    assert "fill=\"#fee2e2\"" in svg_content
    assert "Lỗi biên dịch Kroki" in svg_content

    d2_content = d2_file.read_text(encoding="utf-8")
    assert 'error: "⚠️ Không thể khởi tạo sơ đồ: He Thong' in d2_content
    assert 'fill: "#fee2e2"' in d2_content


def test_mermaid_worker_fallback_on_failure(tmp_path, monkeypatch):
    """_generate_mermaid should save fallback diagram when LLM returns empty or invalid syntax."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.mermaid_worker.cfg", mock_cfg)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    # 1. LLM failure
    monkeypatch.setattr("services.mermaid_worker.call_llm", lambda *a, **kw: "")
    _generate_mermaid("test_fail.mermaid.md", "Context text")

    fail_file = attach_dir / "test_fail.mermaid.md"
    assert fail_file.exists()
    assert "⚠️ Không thể khởi tạo sơ đồ" in fail_file.read_text(encoding="utf-8")

    # 2. Syntax validation failure
    monkeypatch.setattr("services.mermaid_worker.call_llm", lambda *a, **kw: "Not valid mermaid code at all")
    _generate_mermaid("test_invalid.mermaid.md", "Context text")

    invalid_file = attach_dir / "test_invalid.mermaid.md"
    assert invalid_file.exists()
    assert "⚠️ Không thể khởi tạo sơ đồ" in invalid_file.read_text(encoding="utf-8")


def test_excalidraw_worker_fallback_on_failure(tmp_path, monkeypatch):
    """_generate_excalidraw should save fallback diagram when LLM returns invalid JSON."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.excalidraw_worker.cfg", mock_cfg)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    monkeypatch.setattr("services.excalidraw_worker.call_llm", lambda *a, **kw: "```json\n{broken json\n```")
    _generate_excalidraw("broken.excalidraw.md", "Context text")

    broken_file = attach_dir / "broken.excalidraw.md"
    assert broken_file.exists()
    content = broken_file.read_text(encoding="utf-8")
    assert "^texterr1" in content
    assert "Lỗi cú pháp JSON Excalidraw" in content


def test_d2_worker_fallback_on_failure(tmp_path, monkeypatch):
    """_generate_d2 should save fallback diagram when LLM or compilation fails."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.d2_worker.cfg", mock_cfg)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    # Simulate compilation failure
    monkeypatch.setattr("services.d2_worker.call_llm", lambda *a, **kw: "```d2\na -> b\n```")
    monkeypatch.setattr("services.d2_worker.compile_d2_to_svg", lambda *a, **kw: None)

    _generate_d2("flow_fail.d2.svg", "Context text")

    svg_file = attach_dir / "flow_fail.d2.svg"
    d2_file = attach_dir / "flow_fail.d2"
    assert svg_file.exists()
    assert d2_file.exists()
    assert "⚠️ Sơ đồ D2" in svg_file.read_text(encoding="utf-8")


# ── 4. Rich Metadata in Topic Note Tests ─────────────────────────────────────


def test_topic_saver_rich_metadata():
    """build_topic_content should extract summary, related wikilinks, and status: seed."""
    response_body = (
        "# Kiến Trúc Phần Mềm Hiện Đại\n\n"
        "Kiến trúc phần mềm hiện đại đòi hỏi tính module hóa cao và phân tách rõ ràng. "
        "Mô hình Clean Architecture giúp doanh nghiệp dễ dàng mở rộng và bảo trì trong dài hạn.\n\n"
        "Trong thiết kế này, chúng ta cần kết hợp [[domain_driven_design|DDD]] cùng với [[event_sourcing]]. "
        "Ngoài ra, các thành phần giao tiếp qua [[message_broker]] và [[api_gateway]].\n\n"
        "Hệ thống cũng tham chiếu tới hình ảnh ![[kien_truc_clean.png]] và sơ đồ ![[diagram.mermaid.md]]. "
        "Tài liệu tự tham chiếu [[kien_truc_phan_mem_hien_dai]] sẽ được lọc bỏ.\n\n"
        + ("Phần thân văn bản phân tích chuyên sâu thêm rất nhiều chi tiết để vượt ngưỡng ký tự. " * 35)
    )

    assert len(response_body) >= TOPIC_AUTO_SAVE_THRESHOLD

    result = build_topic_content("Phân tích kiến trúc", response_body)
    assert result is not None
    title, slug, full_content = result

    assert title == "Kiến Trúc Phần Mềm Hiện Đại"
    assert slug == "kien_truc_phan_mem_hien_dai"

    fm = parse_frontmatter(full_content)
    assert fm["title"] == "Kiến Trúc Phần Mềm Hiện Đại"
    assert fm["type"] == "topic"
    assert fm["status"] == "seed"
    assert "knowledge" in fm["tags"]
    assert "type/topic" in fm["tags"]

    # Summary checks: 1-2 opening sentences
    assert "Kiến trúc phần mềm hiện đại đòi hỏi tính module hóa cao" in fm["summary"]
    assert len(fm["summary"]) <= 250

    # Related wikilinks checks
    related = fm["related"]
    assert isinstance(related, list)
    assert "[[domain_driven_design]]" in related
    assert "[[event_sourcing]]" in related
    assert "[[message_broker]]" in related
    assert "[[api_gateway]]" in related

    # Self-link and media must be filtered out
    assert "[[kien_truc_phan_mem_hien_dai]]" not in related
    assert "[[kien_truc_clean.png]]" not in related
    assert "[[diagram.mermaid.md]]" not in related


def test_topic_saver_cap_related_links():
    """build_topic_content should cap related links at 8 items."""
    many_links = " ".join(f"[[link_{i}]]" for i in range(20))
    body = (
        "# Thử Nghiệm Nhiều Liên Kết\n\n"
        "Đoạn văn mở đầu thử nghiệm giới hạn số lượng liên kết liên quan.\n\n"
        f"{many_links}\n\n"
        + ("Nội dung văn bản mở rộng rất dài... " * 100)
    )

    result = build_topic_content("Test links", body)
    assert result is not None
    _, _, full_content = result
    fm = parse_frontmatter(full_content)

    assert len(fm["related"]) == 8


def test_extract_and_fetch_urls_autolink_brackets(monkeypatch):
    """CommonMark autolinks like <https://example.com/item> should strip trailing > correctly."""
    fetched = []

    def mock_fetch(url: str, visual: bool = False) -> str:
        fetched.append(url)
        return "# Bài viết mẫu\n\nNội dung bài viết."

    monkeypatch.setattr("services.url_fetcher.fetch_url", mock_fetch)

    query = "Hãy đọc <https://example.com/autolink> và tóm tắt."
    xml_context, urls = extract_and_fetch_urls(query)

    assert urls == ["https://example.com/autolink"]
    assert fetched == ["https://example.com/autolink"]
    assert '<external_web_source url="https://example.com/autolink"' in xml_context


def test_extract_and_fetch_urls_timeout_protection(monkeypatch):
    """When fetch_url hangs longer than 10s, it should safely time out without crashing."""
    import time

    def mock_slow_fetch(url: str, visual: bool = False) -> str:
        # Simulate a hanging network request
        time.sleep(15.0)
        return "Nội dung trễ"

    # For testing speed, monkeypatch the timeout within the module to 0.1s
    monkeypatch.setattr("services.url_fetcher.fetch_url", mock_slow_fetch)

    # Patch ThreadPoolExecutor.submit result timeout inside coordinator
    import concurrent.futures
    orig_submit = concurrent.futures.ThreadPoolExecutor.submit

    def mock_submit(self, fn, *args, **kwargs):
        future = orig_submit(self, fn, *args, **kwargs)
        orig_result = future.result
        future.result = lambda timeout=None: orig_result(timeout=0.05)
        return future

    monkeypatch.setattr(concurrent.futures.ThreadPoolExecutor, "submit", mock_submit)

    query = "Đọc https://hanging-website.org/slow"
    xml_context, urls = extract_and_fetch_urls(query)

    assert xml_context == ""
    assert urls == []


def test_extract_and_fetch_urls_xml_escaping(monkeypatch):
    """When article title contains double quotes, XML attributes must be properly escaped."""
    def mock_fetch(url: str, visual: bool = False) -> str:
        return '# Báo cáo "AI Đột Phá & Xu Hướng 2026"\n\nNội dung báo cáo chi tiết.'

    monkeypatch.setattr("services.url_fetcher.fetch_url", mock_fetch)

    query = "Xem https://example.com/report"
    xml_context, urls = extract_and_fetch_urls(query)

    assert len(urls) == 1
    assert 'title="Báo cáo &quot;AI Đột Phá &amp; Xu Hướng 2026&quot;"' in xml_context
    assert '<external_web_source url="https://example.com/report"' in xml_context


def test_d2_fallback_diagram_xml_escaping(tmp_path, monkeypatch):
    """D2 fallback SVG must properly escape XML entities (&, <, >) to produce valid XML."""
    import xml.etree.ElementTree as ET

    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    save_fallback_diagram(
        "sys_error.d2.svg",
        "Lỗi kết nối <Gateway 502> & server timeout",
        "d2",
    )

    svg_file = attach_dir / "sys_error.d2.svg"
    assert svg_file.exists()
    svg_content = svg_file.read_text(encoding="utf-8")

    # SVG must be 100% valid XML parseable by ElementTree
    root = ET.fromstring(svg_content)
    assert root.tag.endswith("svg")
    assert "&lt;Gateway 502&gt; &amp; server timeout" in svg_content


def test_mermaid_fallback_diagram_quotes_and_sanitization(tmp_path, monkeypatch):
    """Mermaid fallback must sanitize quotes and special characters in diagram name and error."""
    attach_dir = tmp_path / "attachments"
    mock_cfg = dataclasses.replace(cfg, attachments_dir=attach_dir)
    monkeypatch.setattr("services.diagram_base.cfg", mock_cfg)

    save_fallback_diagram(
        'so_do_"luong_du_lieu".mermaid.md',
        'Lỗi cú pháp "node" không hợp lệ & timeout <500>',
        "mermaid",
    )

    out_file = attach_dir / 'so_do__luong_du_lieu_.mermaid.md'
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "```mermaid\nflowchart TD\n" in content
    # Inner quotes and angle brackets in node label should be sanitized to prevent syntax error
    assert '⚠️ Không thể khởi tạo sơ đồ:' in content
    assert '&lt;500&gt;' in content
    assert "style err fill:#fee2e2" in content


def test_topic_saver_summary_skips_hero_images_and_dividers():
    """Summary extraction must skip image embeds, horizontal rules, and fences under H1."""
    body = (
        "# Tiêu Đề Bài Viết Về Trí Tuệ Nhân Tạo\n\n"
        "![[ai_hero_cover.webp]]\n\n"
        "---\n\n"
        "| Chỉ số | Giá trị |\n"
        "| --- | --- |\n"
        "| Tốc độ | Nhanh |\n\n"
        "Trí tuệ nhân tạo đang thay đổi sâu rộng phương thức làm việc hiện đại. "
        "Các hệ thống tự động hóa giúp giải phóng con người khỏi những công việc lặp đi lặp lại.\n\n"
        + ("Văn bản phân tích chuyên sâu thêm rất nhiều chi tiết dài hơn 2500 ký tự... " * 50)
    )

    result = build_topic_content("AI topic", body)
    assert result is not None
    _, _, full_content = result
    fm = parse_frontmatter(full_content)

    assert "![[" not in fm["summary"]
    assert "---" not in fm["summary"]
    assert "|" not in fm["summary"]
    assert fm["summary"].startswith("Trí tuệ nhân tạo đang thay đổi sâu rộng")


def test_topic_saver_self_link_filtering_with_diacritics_and_titlecase():
    """Self-references in Title Case, with diacritics or different casing must be filtered out."""
    body = (
        "# Kiến Trúc Phần Mềm Hiện Đại\n\n"
        "Đoạn văn mở đầu phân tích về thiết kế hệ thống phần mềm.\n\n"
        "Trong bài viết [[Kiến Trúc Phần Mềm Hiện Đại]], chúng ta xem xét [[Clean Architecture]] "
        "và các liên kết khác như [[Event Driven]]. "
        "Cũng như self-link dạng slug [[kien_truc_phan_mem_hien_dai]].\n\n"
        + ("Nội dung mở rộng dài hơn rất nhiều để vượt ngưỡng lưu trữ tự động... " * 45)
    )

    result = build_topic_content("Kiến trúc", body)
    assert result is not None
    _, slug, full_content = result
    assert slug == "kien_truc_phan_mem_hien_dai"

    fm = parse_frontmatter(full_content)
    related = fm["related"]

    # Both Title Case and slug self-references must be filtered out
    assert "[[Kiến Trúc Phần Mềm Hiện Đại]]" not in related
    assert "[[kien_truc_phan_mem_hien_dai]]" not in related

    # Other links must be kept
    assert "[[Clean Architecture]]" in related
    assert "[[Event Driven]]" in related


def test_topic_saver_ignores_code_block_links_and_embeds():
    """Wikilinks inside fenced code blocks and ![[image.png]] embeds must not be in related."""
    body = (
        "# Phân Tích Mã Nguồn\n\n"
        "Đoạn văn mở đầu phân tích mã nguồn và cấu trúc liên kết.\n\n"
        "Tham khảo khái niệm [[atomic_notes]] và [[zettelkasten_method]].\n\n"
        "Hình ảnh minh họa ![[architecture_diagram.png]] được nhúng trong bài.\n\n"
        "```python\n"
        "# Ví dụ mã nguồn không phải là liên kết tri thức:\n"
        "dummy_link = '[[fake_code_concept]]'\n"
        "```\n\n"
        + ("Văn bản bài viết chi tiết kéo dài để vượt ngưỡng 2500 ký tự... " * 40)
    )

    result = build_topic_content("Mã nguồn", body)
    assert result is not None
    _, _, full_content = result
    fm = parse_frontmatter(full_content)
    related = fm["related"]

    assert "[[atomic_notes]]" in related
    assert "[[zettelkasten_method]]" in related
    assert "[[fake_code_concept]]" not in related
    assert "[[architecture_diagram.png]]" not in related

