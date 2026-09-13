"""Unit tests for Command Multi-turn Context and Model Overrides."""

from __future__ import annotations

import pytest
from services.command.coordinator import detect_continuity_signal, extract_last_exchange
from services.command.styles import parse_style, StyleParseResult


def test_detect_continuity_signal():
    """Verify detection of context continuation signals."""
    # Positive signals
    assert detect_continuity_signal("Giải thích rõ hơn phần 2 ở trên") is True
    assert detect_continuity_signal("So sánh với cái trước xem khác biệt là gì") is True
    assert detect_continuity_signal("Làm rõ luận điểm 3 vừa rồi") is True
    assert detect_continuity_signal("Hãy tiếp tục viết phần tiếp theo") is True
    assert detect_continuity_signal("Please elaborate on the previous point") is True
    assert detect_continuity_signal("Can you clarify the above diagram?") is True
    assert detect_continuity_signal("Nói rõ hơn về ý thứ 1") is True

    # Negative signals (standalone queries)
    assert detect_continuity_signal("Kiến trúc microservices là gì?") is False
    assert detect_continuity_signal("Viết bài tổng quan về Clean Architecture") is False
    assert detect_continuity_signal("Tóm tắt cuốn sách Thinking Fast and Slow") is False


def test_extract_last_exchange_empty_or_missing_history():
    """Return None when interaction history section is absent or incomplete."""
    content_no_history = "# Command\n\n## 📥 Input\n@AI: Hello\n"
    assert extract_last_exchange(content_no_history) is None

    content_empty_history = "# Command\n\n## 🕰️ Lịch sử tương tác\n\n(Chưa có lịch sử)\n"
    assert extract_last_exchange(content_empty_history) is None


def test_extract_last_exchange_success():
    """Extract previous query and response from interaction history."""
    sample_content = """# Command

## 📥 Input
@AI: Giải thích rõ hơn phần 2 ở trên

## 🕰️ Lịch sử tương tác

> [!example] 📝 Lịch sử thực thi (2026-09-13 10:00:00)
> **Yêu cầu:**
> @AI: Phân tích kiến trúc Microservices và Modular Monolith
> ---
> **Phản hồi:**
> > [!done]+ 🤖 Phản hồi của AI (professional)
> > Đây là câu trả lời chi tiết về Microservices:
> > 
> > 1. Khái niệm cơ bản.
> > 2. Ưu và nhược điểm.
> > 3. Kết luận kiến trúc.
"""
    result = extract_last_exchange(sample_content)
    assert result is not None
    assert "Phân tích kiến trúc Microservices" in result["query"]
    assert "Đây là câu trả lời chi tiết về Microservices" in result["response"]
    assert "2. Ưu và nhược điểm." in result["response"]


def test_extract_last_exchange_truncation():
    """Truncate previous response if it exceeds max_chars."""
    long_response_lines = "\n> ".join([f"Dòng phân tích thứ {i} về hệ thống." for i in range(200)])
    sample_content = f"""# Command

## 🕰️ Lịch sử tương tác

> [!example] 📝 Lịch sử thực thi
> **Yêu cầu:**
> @AI: Truy vấn trước đó
> ---
> **Phản hồi:**
> > [!done]+ 🤖 Phản hồi của AI
> {long_response_lines}
"""
    result = extract_last_exchange(sample_content, max_chars=500)
    assert result is not None
    assert len(result["response"]) <= 600
    assert "...(cắt ngắn để bảo toàn ngân sách ngữ cảnh)..." in result["response"]


def test_parse_style_model_overrides():
    """Verify parsing of /opus, /sonnet, /pro, /flash and combination with styles."""
    # /opus alone
    res = parse_style("/opus Hãy phân tích hệ thống")
    assert res.explicit_model == "claude-opus-4-6-thinking"
    assert res.style_name == "professional"
    assert res.clean_query == "Hãy phân tích hệ thống"

    # /sonnet + /academic
    res2 = parse_style("/sonnet /academic Đánh giá phương pháp luận")
    assert res2.explicit_model == "claude-sonnet-4-6"
    assert res2.style_name == "academic"
    assert res2.clean_query == "Đánh giá phương pháp luận"

    # /pro + /bullet
    res3 = parse_style("/pro /bullet Liệt kê 5 nguyên tắc")
    assert res3.explicit_model == "gemini-3.1-pro"
    assert res3.style_name == "bullet"
    assert res3.clean_query == "Liệt kê 5 nguyên tắc"

    # /fast + /opus
    res4 = parse_style("/fast /opus Tóm tắt nhanh")
    assert res4.explicit_model == "claude-opus-4-6-thinking"
    assert res4.is_fast is True
    assert res4.clean_query == "Tóm tắt nhanh"


def test_parse_style_unpacking_compatibility():
    """Ensure backward compatibility with 2-item, 3-item, and 4-item unpacking."""
    query = "/opus /academic Phân tích"

    # 2-item unpacking
    style, clean = parse_style(query)
    assert style == "academic"
    assert clean == "Phân tích"

    # 3-item unpacking
    style, clean, is_fast = parse_style(query)
    assert style == "academic"
    assert clean == "Phân tích"
    assert is_fast is False

    # 4-item unpacking
    style, clean, is_fast, model = parse_style(query)
    assert style == "academic"
    assert clean == "Phân tích"
    assert is_fast is False
    assert model == "claude-opus-4-6-thinking"
