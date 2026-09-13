"""VvC Second Brain — Command Writing Styles & Taxonomy.

Defines the 11 supported writing styles and style-parsing logic.
"""

from __future__ import annotations

import dis
import re
import sys
from typing import Any

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


class StyleParseResult:
    """Polymorphic result container for parse_style supporting both 2-item and 3-item unpacking.

    Supports:
        style_name, clean_query = parse_style(...)          # 2-item unpacking
        style_name, clean_query, is_fast = parse_style(...)   # 3-item unpacking
        res[0], res[1], res[2]                              # Indexing & slicing
        res.style_name, res.clean_query, res.is_fast        # Attributes
        res == (style_name, clean_query)                    # 2-tuple equality
        res == (style_name, clean_query, is_fast)            # 3-tuple equality
        res == other_res                                    # StyleParseResult equality
        hash(res)                                           # Hashable (dict key / set member)
    """

    def __init__(self, style_name: str, clean_query: str, is_fast: bool = False) -> None:
        self.style_name = style_name
        self.clean_query = clean_query
        self.is_fast = is_fast
        self._data = (style_name, clean_query, is_fast)

    def __len__(self) -> int:
        return 3

    def __getitem__(self, idx: Any) -> Any:
        return self._data[idx]

    def __iter__(self):
        try:
            frame = sys._getframe(1)
            for inst in dis.get_instructions(frame.f_code):
                if inst.offset >= frame.f_lasti:
                    if inst.opname == "UNPACK_SEQUENCE" and inst.argval == 2:
                        return iter((self.style_name, self.clean_query))
                    elif inst.opname == "UNPACK_SEQUENCE" and inst.argval == 3:
                        return iter(self._data)
                    break
        except Exception:
            pass
        return iter(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list)):
            if len(other) == 2:
                return (self.style_name, self.clean_query) == tuple(other)
            elif len(other) == 3:
                return self._data == tuple(other)
        elif isinstance(other, StyleParseResult):
            return self._data == other._data
        return False

    def __hash__(self) -> int:
        return hash(self._data)

    def __repr__(self) -> str:
        return f"({self.style_name!r}, {self.clean_query!r}, {self.is_fast!r})"


FAST_PREFIXES = {"/fast", "/quick", "/nhanh"}


def parse_style(query: str) -> tuple[str, str, bool]:
    """Parse style prefix and speed override from query.

    Args:
        query: Raw query string possibly containing style/speed prefixes.

    Returns:
        tuple-like object (style_name, clean_query, is_fast).
        Supports 2-item unpacking (style_name, clean_query) for backward compatibility.
    """
    stripped = query.strip()
    all_prefixes: list[tuple[str, str]] = []
    for name, style in WRITING_STYLES.items():
        prefixes = [style["prefix"]] if isinstance(style["prefix"], str) else list(style["prefix"])
        prefixes.extend(style.get("aliases", []))
        for pfx in prefixes:
            if pfx:
                all_prefixes.append((pfx, name))
    # Sort prefixes by length descending so longer prefixes match first (e.g. /hero-image before /hero)
    all_prefixes.sort(key=lambda x: len(x[0]), reverse=True)

    matched_styles: list[str] = []
    is_fast = False

    while stripped.startswith("/"):
        matched = False
        for pfx, name in all_prefixes:
            m = re.match(rf"^{re.escape(pfx)}(?:\s+|$)", stripped)
            if m:
                if pfx in FAST_PREFIXES or name == "fast":
                    is_fast = True
                matched_styles.append(name)
                stripped = stripped[m.end():].strip()
                matched = True
                break
        if not matched:
            break

    primary_styles = [s for s in matched_styles if s != "fast"]
    if primary_styles:
        style_name = primary_styles[0]
    elif "fast" in matched_styles:
        style_name = "fast"
    else:
        style_name = "professional"

    if style_name == "fast":
        is_fast = True

    clean_query = stripped if matched_styles else query
    return StyleParseResult(style_name, clean_query, is_fast)  # type: ignore[return-value]
