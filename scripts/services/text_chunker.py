"""VvC Second Brain — Text Chunker & Orthographic Corrector.

Handles semantic chunking and LLM-based orthographic corrections.
"""

import logging
import re

from core.llm import call_llm

_logger = logging.getLogger("vvc.text_chunker")

def orthographic_preprocess(text: str) -> str:
    """Adaptive orthographic correction and markdown formatting with semantic chunking."""
    if not text or len(text) < 50:
        return text

    # Semantic Chunking
    max_chunk_size = 25000
    chunks = []
    
    if len(text) <= max_chunk_size:
        chunks = [text]
    else:
        _logger.info(f"Text is {len(text)} chars. Chunking into {max_chunk_size}-char segments.")
        # Split by sentence boundaries
        raw_sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = []
        for s in raw_sentences:
            s = s.strip()
            if not s:
                continue
            if len(s) <= max_chunk_size:
                sentences.append(s)
            else:
                # Fallback: split huge sentences by space (e.g. YouTube transcripts without punctuation)
                words = s.split()
                temp_s = []
                temp_len = 0
                for w in words:
                    if temp_len + len(w) > max_chunk_size and temp_s:
                        sentences.append(" ".join(temp_s))
                        temp_s = [w]
                        temp_len = len(w) + 1
                    else:
                        temp_s.append(w)
                        temp_len += len(w) + 1
                if temp_s:
                    sentences.append(" ".join(temp_s))

        current_chunk = []
        current_len = 0
        
        for sentence in sentences:
            sentence_len = len(sentence)
            
            if current_len + sentence_len > max_chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_len = sentence_len + 1
            else:
                current_chunk.append(sentence)
                current_len += sentence_len + 1 # +1 for space
                
        if current_chunk:
            chunks.append(" ".join(current_chunk))

    # Detect if raw text contains any timestamps [MM:SS]
    has_timestamps = bool(re.search(r"\[\d+:\d+\]", text))
    
    _logger.info(f"Processing {len(chunks)} chunk(s) for formatting and correction. Timestamps detected: {has_timestamps}")
    
    formatted_chunks = []
    for i, chunk in enumerate(chunks, 1):
        _logger.info(f"Processing chunk {i}/{len(chunks)}...")
        
        if has_timestamps:
            prompt = (
                f"Bạn là chuyên gia chưng cất tri thức (Knowledge Distillation) xuất sắc.\n"
                f"Hãy biên soạn và dịch nội dung transcript thô từ video dưới đây sang tiếng Việt chuẩn học thuật, mượt mà và cực kỳ dễ tiếp thu.\n\n"
                f"NHIỆM VỤ BIÊN SOẠN:\n"
                f"1. **Chưng cất tri thức**: Chuyển đổi dòng văn nói verbatim lặp ý, dông dài thành một cấu trúc bài viết khoa học. Chia nhỏ nội dung thành các tiêu đề logic rõ ràng (ví dụ: '### 1. Giải pháp: ...', '### 2. Các thuật ngữ chuyên ngành', '### 3. Lợi ích...').\n"
                f"2. **Định dạng tối ưu**: Sử dụng danh sách gạch đầu dòng (bullet points) để định nghĩa rõ ràng các khái niệm, thuật ngữ chuyên ngành (ví dụ: '* **Khái niệm**: Giải thích...'). In đậm các từ khóa đắt giá.\n"
                f"3. **Giữ nguyên mốc thời gian JIT**: BẮT BUỘC giữ lại mốc thời gian gốc dạng [MM:SS] (hoặc [H:MM:SS]) bằng cách nhúng chúng vào CUỐI câu hoặc đoạn văn tương ứng. Tuyệt đối không được xóa các mốc thời gian này vì chúng là neo dệt hình ảnh. Nếu một ý tưởng kéo dài qua nhiều câu, hãy đặt mốc thời gian ở câu kết thúc ý tưởng đó.\n"
                f"4. **Hiệu đính chính tả**: Sửa các lỗi chính tả đồng âm (Chi/Tri, S/X, D/Gi/R) hoặc thuật ngữ dịch sai.\n"
                f"5. **Quy tắc đầu ra**: TUYỆT ĐỐI CHỈ TRẢ VỀ NỘI DUNG VĂN BẢN ĐÃ BIÊN SOẠN. KHÔNG CHÀO HỎI, KHÔNG GIẢI THÍCH.\n\n"
                f"VĂN BẢN TRANSCRIPT GỐC:\n---\n{chunk}\n---"
            )
        else:
            prompt = (
                f"Bạn là chuyên gia chưng cất tri thức (Knowledge Distillation) xuất sắc.\n"
                f"Hãy biên soạn và định dạng nội dung văn bản dưới đây sang tiếng Việt chuẩn học thuật, mượt mà và cực kỳ dễ tiếp thu.\n\n"
                f"NHIỆM VỤ BIÊN SOẠN:\n"
                f"1. **Chưng cất tri thức**: Chuyển đổi nội dung thô dông dài, lặp ý thành một cấu trúc bài viết khoa học. Chia nhỏ nội dung thành các tiêu đề logic rõ ràng (ví dụ: '### 1. Giải pháp: ...', '### 2. Các thuật ngữ chuyên ngành', '### 3. Lợi ích...').\n"
                f"2. **Định dạng tối ưu**: Sử dụng danh sách gạch đầu dòng (bullet points) để định nghĩa rõ ràng các khái niệm, thuật ngữ chuyên ngành (ví dụ: '* **Khái niệm**: Giải thích...'). In đậm các từ khóa đắt giá.\n"
                f"3. **Hiệu đính chính tả**: Sửa các lỗi chính tả đồng âm (Chi/Tri, S/X, D/Gi/R) hoặc thuật ngữ dịch sai.\n"
                f"4. **Quy tắc đầu ra**: TUYỆT ĐỐI CHỈ TRẢ VỀ NỘI DUNG VĂN BẢN ĐÃ BIÊN SOẠN. KHÔNG CHÀO HỎI, KHÔNG GIẢI THÍCH.\n\n"
                f"VĂN BẢN GỐC:\n---\n{chunk}\n---"
            )
            
        result = call_llm(
            prompt, 
            task="correction", 
            validator=lambda x: len(x) > 300
        )
        if result:
            formatted_chunks.append(result.strip())
        else:
            _logger.warning(f"Chunk {i} formatting failed all tiers. Using original.")
            formatted_chunks.append(chunk.strip())
            
    return "\n\n---\n\n".join(formatted_chunks)
