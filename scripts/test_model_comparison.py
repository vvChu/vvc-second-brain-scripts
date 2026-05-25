"""VvC Second Brain — LLM Model Comparison Test (v1.0).

This script compares the writing capabilities of three premium models:
1. gemini-3.5-flash-low
2. gemini-3.1-pro-high
3. claude-opus-4-6-thinking

It executes a deep academic prompt on "Reinventing a construction consulting organization 
into a market-oriented ecosystem organization" against the AI Gateway for all three models, 
and appends the comparative results directly to Command.md.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

# Setup paths to ensure internal modules are importable
_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import cfg
from core.llm.gateway_client import call_gateway

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [model_test] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
_logger = logging.getLogger("vvc.model_test")


def to_blockquote(text: str) -> str:
    """Formats raw text into an Obsidian-compatible blockquote."""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def run_model_comparison() -> None:
    """Executes the comparative test across the three LLM models and updates Command.md."""
    _logger.info("=" * 60)
    _logger.info("Starting LLM Model Comparison Test...")
    _logger.info("=" * 60)

    prompt = (
        "Hãy viết một bài khảo cứu chuyên sâu (khoảng 800 - 1000 từ) về đề tài: "
        "\"Tái tạo một tổ chức tư vấn về lĩnh vực xây dựng thành một tổ chức theo định hướng hệ sinh thái định hướng thị trường (Market-Oriented Ecosystem Organization)\".\n\n"
        "Yêu cầu chuyên môn:\n"
        "1. Phân tích First Principles về sự hạn chế của mô hình tư vấn xây dựng truyền thống (phòng ban cứng nhắc, thâm dụng lao động, quản lý tập trung phân tầng) dẫn đến sự chậm trễ, xung đột lợi ích giữa các khâu (Thiết kế - Pháp lý - Giám sát) và kém thích ứng.\n"
        "2. Đề xuất mô hình chuyển đổi dựa trên lý thuyết Tổ chức Hệ sinh thái Định hướng Thị trường: Phá vỡ cấu trúc cũ thành các Micro-teams/Micro-enterprises tự chủ hoạt động, liên kết trực tiếp với nhu cầu thị trường, tự quyết định tài chính và dịch vụ.\n"
        "3. Nêu bật cách ứng dụng Công nghệ AI và lực lượng lao động số (AI Agents tự trị) để khuếch đại năng lực của các Micro-teams, tự động hóa các khâu phân tích quy chuẩn xây dựng phức tạp (QCVN 06/202X, QCVN 10) để đạt năng suất vượt trội.\n"
        "4. Đề cập đến phương thức chuyển đổi định giá sản phẩm dịch vụ tư vấn từ Billable Hours sang định giá dựa trên giá trị và kết quả thực tế (Outcome-based Pricing).\n"
        "5. Trình bày mạch lạc, cấu trúc rõ ràng, sử dụng ngôn ngữ khoa học, chuyên nghiệp, lập luận First Principles vững chắc."
    )

    # 1. Call gemini-3.5-flash-low
    _logger.info("Calling gemini-3.5-flash-low on Gateway...")
    ans_flash = call_gateway(prompt, model="gemini-3.5-flash-low", timeout=300)
    if not ans_flash:
        _logger.warning("Failed to get response from gemini-3.5-flash-low. Using fallback placeholder.")
        ans_flash = "(Lỗi cuộc gọi API đến gemini-3.5-flash-low)"

    # 2. Call gemini-3.1-pro-high
    _logger.info("Calling gemini-3.1-pro-high on Gateway...")
    ans_pro = call_gateway(prompt, model="gemini-3.1-pro-high", timeout=300)
    if not ans_pro:
        _logger.warning("Failed to get response from gemini-3.1-pro-high. Using fallback placeholder.")
        ans_pro = "(Lỗi cuộc gọi API đến gemini-3.1-pro-high)"

    # 3. Call claude-opus-4-6-thinking
    _logger.info("Calling claude-opus-4-6-thinking on Gateway...")
    ans_opus = call_gateway(prompt, model="claude-opus-4-6-thinking", timeout=600)
    if not ans_opus:
        _logger.warning("Failed to get response from claude-opus-4-6-thinking. Using fallback placeholder.")
        ans_opus = "(Lỗi cuộc gọi API đến claude-opus-4-6-thinking)"

    # Generate Markdown Comparison Block
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    comp_header = (
        f"@AI: /academic Hãy so sánh năng lực viết bài giữa 3 model: gemini-3.5-flash-low, gemini-3.1-pro-high, và claude-opus-4-6-thinking "
        f"về chủ đề \"Tái tạo tổ chức tư vấn xây dựng thành hệ sinh thái định hướng thị trường\". ---\n"
        f"> [!done]+ 🎓 Kết quả thử nghiệm so sánh 3 Model lớn tại AI Gateway ({today_str})\n"
        f"> Dưới đây là bài viết được sinh ra bởi 3 model khác nhau cùng dựa trên một prompt thiết kế chuyên sâu về chủ đề tái tạo tổ chức tư vấn xây dựng thành hệ sinh thái định hướng thị trường để so sánh chất lượng.\n"
        f">\n"
    )

    comp_flash = (
        f"> ## 🏢 MODEL 1: gemini-3.5-flash-low\n"
        f">\n"
        f"{to_blockquote(ans_flash)}\n"
        f">\n"
        f"> ---\n"
        f">\n"
    )

    comp_pro = (
        f"> ## 🏢 MODEL 2: gemini-3.1-pro-high\n"
        f">\n"
        f"{to_blockquote(ans_pro)}\n"
        f">\n"
        f"> ---\n"
        f">\n"
    )

    comp_opus = (
        f"> ## 🏢 MODEL 3: claude-opus-4-6-thinking\n"
        f">\n"
        f"{to_blockquote(ans_opus)}\n"
    )

    full_comparison_block = comp_header + comp_flash + comp_pro + comp_opus + "\n\n"

    # Write to Command.md
    command_file = Path(cfg.command_file)
    if not command_file.exists():
        _logger.error(f"Command.md does not exist at {command_file}")
        return

    try:
        content = command_file.read_text(encoding="utf-8")
        marker = "## 🕰️ Lịch sử tương tác"
        
        if marker in content:
            # Insert the comparison block right after the marker
            parts = content.split(marker, 1)
            # Ensure proper spacing around the inserted block
            new_content = parts[0] + marker + "\n\n" + full_comparison_block + parts[1].lstrip()
            command_file.write_text(new_content, encoding="utf-8")
            _logger.info("Command.md successfully updated with the model comparison test results.")
        else:
            # Fallback: append to the end of the file
            _logger.warning("Could not find interaction history marker. Appending comparison to the end of Command.md.")
            new_content = content + "\n\n" + full_comparison_block
            command_file.write_text(new_content, encoding="utf-8")
    except Exception as e:
        _logger.error(f"Failed to write comparison to Command.md: {e}")

    _logger.info("Model comparison test complete!")


if __name__ == "__main__":
    run_model_comparison()
