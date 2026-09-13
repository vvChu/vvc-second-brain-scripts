"""VvC Second Brain — Command Writing Styles & Taxonomy.

Defines the 11 supported writing styles and style-parsing logic.
"""

from __future__ import annotations

import re

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
    "fast": {
        "prefix": "/fast",
        "aliases": ["/quick", "/nhanh"],
        "emoji": "⚡",
        "system": "Viết ngắn gọn, trực diện, trả lời nhanh câu hỏi mà không cần diễn giải rườm rà. Tập trung vào câu trả lời cốt lõi ngay lập tức.",
    },
    "hero-image": {
        "prefix": "/hero-image",
        "aliases": ["/hero", "/banner"],
        "emoji": "🎨",
        "system": (
            "Bạn là Giám đốc Nghệ thuật và Chuyên gia Thiết kế Thị giác (Art Director & Visual Metaphor Specialist).\n"
            "Nhiệm vụ: Phân tích sâu chủ đề/khái niệm được yêu cầu, sau đó tổng hợp một đoạn mô tả ẩn dụ thị giác điện ảnh (cinematic visual metaphor) tỉ lệ 16:9 chất lượng cao bằng tiếng Anh chuyên sâu để làm prompt sinh ảnh (Hero Banner).\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. Cấu trúc bài viết gồm 2 phần: Phân tích ý niệm thị giác (Visual Concept Analysis) bằng tiếng Việt và Prompt sinh ảnh hoàn chỉnh (Final Image Prompt) bằng tiếng Anh.\n"
            "2. Prompt tiếng Anh phải tuân thủ chuẩn nhiếp ảnh/điện ảnh: Lighting (chiếu sáng), Color Palette (bảng màu), Composition (bố cục 16:9), Medium (3D architectural render, cinematic photography, high-concept visualization), Mood/Atmosphere (bầu không khí huyền ảo, học thuật, sâu sắc).\n"
            "3. BẮT BUỘC có mục rõ ràng: '### Final Image Prompt' hoặc 'Prompt: ' chứa đoạn prompt tiếng Anh nguyên vẹn để hệ thống tự động trích xuất.\n"
            "4. KHÔNG sử dụng chữ (text, typography, labels) hoặc logo vụn vặt trong hình ảnh. Tập trung hoàn toàn vào biểu tượng ẩn dụ và sự tương phản mạnh mẽ của các yếu tố không gian, cấu trúc và ánh sáng.\n"
            "5. RÀO CẢN PHỦ ĐỊNH (Negative Constraints): Tuyệt đối KHÔNG sử dụng phong cách tranh hoạt hình (cartoon), anime, đồ chơi nhựa 3D (plastic toy, glossy CGI render), chibi, hoặc hình vẽ minh họa trẻ con ngô nghê. Phong cách bắt buộc phải đạt độ nghiêm túc học thuật, điện ảnh (cinematic film still, editorial photography, moody architectural installation, dark minimal aesthetic)."
        ),
    },
}


def parse_style(query: str) -> tuple[str, str]:
    """Parse style prefix from query.

    Args:
        query: Raw query string possibly containing a style prefix.

    Returns:
        tuple of (style_name, clean_query). Defaults to ('professional', query).
    """
    stripped = query.strip()
    for name, style in WRITING_STYLES.items():
        prefixes = [style["prefix"]] if isinstance(style["prefix"], str) else list(style["prefix"])
        prefixes.extend(style.get("aliases", []))
        for pfx in prefixes:
            if not pfx:
                continue
            m = re.match(rf"^{re.escape(pfx)}(?:\s+|$)", stripped)
            if m:
                clean = stripped[m.end():].strip()
                return name, clean
    return "professional", query
