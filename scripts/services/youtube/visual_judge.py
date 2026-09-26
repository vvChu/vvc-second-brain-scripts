"""VvC Second Brain — YouTube Visual Judge & Response Parser.

Handles LLM-as-Judge prompt construction, Vision Gateway API communication,
KEY_FRAMES JSON parsing with explicit status flags, and semantic alt-text generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

from core.config import cfg
from core.llm import resolve_model
from core.llm.utils import http_session, encode_image

_logger = logging.getLogger("vvc.youtube.judge")


class KeyFramesParseResult(tuple):
    """3-tuple subclass preserving (cleaned_summary, key_frame_indices, key_frame_alts)
    while exposing explicit parsing status flags."""
    is_explicit_empty: bool = False
    parse_success: bool = False
    header_present: bool = False

    def __new__(
        cls,
        cleaned_summary: str,
        key_frame_indices: list[int],
        key_frame_alts: dict[int, str],
        *,
        is_explicit_empty: bool = False,
        parse_success: bool = False,
        header_present: bool = False,
    ):
        obj = super().__new__(cls, (cleaned_summary, key_frame_indices, key_frame_alts))
        obj.is_explicit_empty = is_explicit_empty
        obj.parse_success = parse_success
        obj.header_present = header_present
        return obj


def _extract_json_array(json_part: str) -> list | None:
    """Extract a JSON list from a text block using greedy followed by non-greedy search."""
    greedy_match = re.search(r"\[[\s\S]*\]", json_part)
    if greedy_match:
        try:
            parsed = json.loads(greedy_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    lazy_match = re.search(r"\[[\s\S]*?\]", json_part)
    if lazy_match:
        try:
            parsed = json.loads(lazy_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return None


def _parse_frame_item(
    item: Any,
    seen_indices: set[int],
    key_frame_indices: list[int],
    key_frame_alts: dict[int, str],
) -> None:
    """Parse a single item from KEY_FRAMES array into indices and alt dict."""
    if isinstance(item, dict):
        idx = item.get("index")
        alt = str(item.get("alt", "")).strip()
        if idx is not None:
            try:
                idx_int = int(idx)
                if idx_int not in seen_indices:
                    seen_indices.add(idx_int)
                    key_frame_indices.append(idx_int)
                if alt and idx_int not in key_frame_alts:
                    key_frame_alts[idx_int] = alt
            except (ValueError, TypeError):
                pass
    elif isinstance(item, (int, str)):
        try:
            idx_int = int(item)
            if idx_int not in seen_indices:
                seen_indices.add(idx_int)
                key_frame_indices.append(idx_int)
        except (ValueError, TypeError):
            pass


def _parse_key_frames_response(summary: str) -> KeyFramesParseResult:
    """Parse KEY_FRAMES from LLM-as-Judge output supporting v12.0 dict list and int list."""
    key_frame_indices: list[int] = []
    key_frame_alts: dict[int, str] = {}
    cleaned_summary = summary

    matches = list(re.finditer(r"(?:\*\*|__)?KEY_FRAMES(?:\*\*|__)?\s*:(?:\*\*|__)?", summary, flags=re.IGNORECASE))
    if not matches:
        return KeyFramesParseResult(
            cleaned_summary, key_frame_indices, key_frame_alts,
            is_explicit_empty=False, parse_success=False, header_present=False
        )

    match = matches[-1]
    cleaned_summary = summary[:match.start()].strip()
    json_part = summary[match.end():].strip()
    json_part = re.sub(r"^```(?:json)?\s*", "", json_part, flags=re.IGNORECASE)
    json_part = re.sub(r"\s*```$", "", json_part)

    raw_list = _extract_json_array(json_part)
    if not isinstance(raw_list, list):
        _logger.warning("Không thể parse JSON KEY_FRAMES từ response.")
        return KeyFramesParseResult(
            cleaned_summary, key_frame_indices, key_frame_alts,
            is_explicit_empty=False, parse_success=False, header_present=True
        )

    if len(raw_list) == 0:
        return KeyFramesParseResult(
            cleaned_summary, key_frame_indices, key_frame_alts,
            is_explicit_empty=True, parse_success=True, header_present=True
        )

    seen: set[int] = set()
    for item in raw_list:
        _parse_frame_item(item, seen, key_frame_indices, key_frame_alts)

    return KeyFramesParseResult(
        cleaned_summary, key_frame_indices, key_frame_alts,
        is_explicit_empty=False, parse_success=True, header_present=True
    )


def _resolve_key_frames_with_fallback(
    summary: str,
    total_frames: int,
) -> tuple[str, list[int], dict[int, str]]:
    """Phân giải KEY_FRAMES từ phản hồi của model, phân biệt rõ quyết định từ chối và lỗi format / parse thất bại."""
    parse_result = _parse_key_frames_response(summary)
    cleaned_summary, key_frame_indices, key_frame_alts = parse_result

    if parse_result.is_explicit_empty:
        _logger.info("Model từ chối chọn frame có chủ ý (KEY_FRAMES: []). Tôn trọng quyết định, không trích xuất frame.")
        return cleaned_summary, [], {}

    if key_frame_indices:
        return cleaned_summary, key_frame_indices, key_frame_alts

    if total_frames > 0:
        if not parse_result.header_present:
            _logger.warning("Không tìm thấy chuỗi KEY_FRAMES: trong mô tả của model (lỗi format). Áp dụng fallback tự động...")
        else:
            _logger.warning("Phát hiện chuỗi KEY_FRAMES: nhưng không parse được frame hợp lệ (parse thất bại). Áp dụng fallback...")

        key_frame_indices = [0, total_frames // 2, total_frames - 1] if total_frames >= 3 else list(range(total_frames))

    return cleaned_summary, key_frame_indices, key_frame_alts


def _generate_semantic_alt_texts(visual_summary: str, saved_frames: list[str]) -> dict[str, str]:
    """Gọi LLM cực nhanh để ánh xạ và tạo alt-text giàu ngữ nghĩa cho từng frame ảnh dựa trên Visual Summary."""
    if not saved_frames:
        return {}

    prompt = (
        "Bạn là chuyên gia phân tích đa phương thức. Dưới đây là bản tóm tắt nội dung trực quan (Visual Summary) của một video học thuật, "
        "và danh sách các tệp tin ảnh slide đã được trích xuất (có chứa mốc thời gian ts<seconds> trong tên file).\n\n"
        "NHIỆM VỤ CỦA BẠN:\n"
        "Hãy dựa vào bản tóm tắt dưới đây và mốc thời gian của từng file ảnh để viết một mô tả ngắn gọn (alt text) bằng tiếng Việt khoảng 10-20 từ cho mỗi ảnh. "
        "Mô tả phải tập trung vào nội dung học thuật trực quan xuất hiện trong slide đó (ví dụ: 'Sơ đồ kiến trúc Deep Module', 'Bảng thuật ngữ chuyên ngành', 'Đồ thị phân tích hiệu suất').\n\n"
        f"VISUAL SUMMARY:\n---\n{visual_summary}\n---\n\n"
        f"DANH SÁCH FILE ẢNH:\n{saved_frames}\n\n"
        "BẮT BUỘC TRẢ VỀ định dạng JSON object dạng:\n"
        "{\n"
        "  \"tên_file_1.webp\": \"mô tả slide 1 bằng tiếng Việt\",\n"
        "  \"tên_file_2.webp\": \"mô tả slide 2 bằng tiếng Việt\"\n"
        "}\n"
        "Chỉ trả về chuỗi JSON hợp lệ, không giải thích gì thêm, không bọc trong code block markdown."
    )

    try:
        from core.llm import call_llm
        res = call_llm(prompt, task="correction")
        if res:
            match = re.search(r"\{.*\}", res, re.DOTALL)
            res_str = match.group(0) if match else res
            return json.loads(res_str)
    except Exception as e:
        _logger.warning(f"Không thể tạo semantic alt-text JIT: {e}")
    return {}


def _build_judge_prompt(transcript_text: str | None = None) -> str:
    """Build the system and task prompt for Context-Aware Visual Judge."""
    prompt_text = (
        "Bạn là một LLM-as-Judge chuyên nghiệp, chịu trách nhiệm phân tích các khung hình của một video bài giảng/học thuật để lọc ra các khung hình có giá trị tri thức trực quan cao nhất.\n\n"
        "NHIỆM VỤ CỦA BẠN:\n"
        "1. Phân tích sự tiến triển trực quan qua các khung hình được cung cấp (đã được đánh chỉ số 0, 1, 2... theo thứ tự thời gian).\n"
        "2. Đọc và đối chiếu chặt chẽ với phần AUDIO TRANSCRIPT CONTEXT bên dưới để hiểu nội dung học thuật được thảo luận tại thời điểm tương ứng.\n"
        "3. Viết một bản tóm tắt nội dung trực quan (Visual Slide Summary) bằng TIẾNG VIỆT chi tiết, khoa học, tóm lược đầy đủ các sơ đồ, công thức, mã nguồn hoặc tiêu đề slide xuất hiện trong ảnh. Không được viết ad-hoc kiểu 'ở khung hình 1', hãy diễn giải mượt mà như một báo cáo học thuật chuyên sâu.\n"
        "4. BẮT BUỘC lọc KEY_FRAMES theo nguyên tắc khắt khe bên dưới để tránh đưa ảnh rác vào Zettelkasten.\n\n"
        "⚠️ QUY TẮC CẤM (REJECTION RULES) - BẮT BUỘC TUÂN THỦ:\n"
        "- CẤM TUYỆT ĐỐI chọn các khung hình 'Talking Head' (chân dung diễn giả đứng nói trước máy quay, cận cảnh khuôn mặt) mà không có slide chữ, biểu đồ, mã nguồn hay sơ đồ hiển thị đi kèm. Cho dù lời thoại (transcript) tại giây đó có hay đến mấy, nếu hình ảnh chỉ là mặt người nói -> KHÔNG ĐƯỢC CHỌN.\n"
        "- LƯU Ý ĐẶC BIỆT: Các khung hình ghép (split-screen, picture-in-picture, hoặc slide lớn có ghép mặt nhỏ diễn giả ở góc) vẫn ĐƯỢC CHẤP NHẬN và vô cùng giá trị. Chỉ từ chối khi khung hình CHỈ có duy nhất khuôn mặt người nói phóng to mà không có bất kỳ thông tin slide học thuật nào.\n"
        "- CẤM chọn các khung hình chứa nút kêu gọi 'SUBSCRIBE' (Đăng ký kênh), nút Like, intro, outro, logo chuyển cảnh, hoặc hình ảnh phong cảnh chung chung không mang tính học thuật cô đọng trực quan.\n"
        "- CHỈ CHẤP NHẬN các khung hình là phương tiện truyền tải thông tin trực quan độc lập và rõ ràng: slide bài giảng đọc được chữ, sơ đồ kiến trúc hệ thống, sơ đồ tư duy (mindmap), bảng so sánh số liệu, mã nguồn (code snippet) thực tế, hoặc công thức toán học.\n\n"
        "Ở DÒNG CUỐI CÙNG của câu trả lời, xuất ra chính xác định dạng JSON:\n"
        "KEY_FRAMES: [{\"index\": <index>, \"alt\": \"<mô tả ngắn 10-20 từ về slide/sơ đồ bằng tiếng Việt>\"}, ...]\n"
        "trong đó chọn ra các chỉ số index (0-indexed của ảnh đầu vào) kèm mô tả alt-text tương ứng. Nếu không có khung hình nào chứa sơ đồ/slide trực quan giá trị học thuật thực sự, hãy xuất ra: KEY_FRAMES: []\n\n"
    )
    if transcript_text:
        prompt_text += f"=== [AUDIO TRANSCRIPT CONTEXT] ===\n{transcript_text}\n==================================\n\n"
    return prompt_text


def _call_vision_judge_api(
    extracted_frames: list[Path],
    prompt_text: str,
    session: Any = None,
) -> str:
    """Call Vision Gateway API with multi-frame images and transcript context."""
    active_session = session if session is not None else http_session
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]

    for f_path in extracted_frames:
        b64_data = encode_image(f_path, max_pixels=768, quality=70)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"}
        })

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.gateway_api_key}",
    }
    target_model = resolve_model(cfg.gateway_proxy_model or "gemini-3.8-flash-low", task="vision")
    payload = {
        "model": target_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 8192,
    }

    _logger.info(f"Đang gửi {len(extracted_frames)} frames lên Gateway API ({payload['model']}) (Context-Aware)...")
    resp = active_session.post(
        f"{cfg.gateway_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()

    result_json = resp.json()
    summary = result_json["choices"][0]["message"]["content"]
    summary = re.sub(
        r"(?i)Refining\s+the\s+Vietnamese\s+text\s+for\s+50%\s+reduced\s+verbosity\*\*:\s*Keep\s+it\s+extremely\s+punchy\s+and\s+direct\.\s*",
        "",
        summary,
    )
    return summary.strip()
