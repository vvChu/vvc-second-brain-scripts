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

    _logger.info(f"Processing {len(chunks)} chunk(s) for formatting and correction.")
    
    formatted_chunks = []
    for i, chunk in enumerate(chunks, 1):
        _logger.info(f"Processing chunk {i}/{len(chunks)}...")
        prompt = (
            f"Văn bản dưới đây có thể chứa lỗi chính tả đồng âm (do nhận diện giọng nói Youtube/OCR, ví dụ: Chi/Tri, S/X, D/Gi/R). "
            f"Hãy:\n"
            f"1. Hiệu đính toàn bộ các lỗi chính tả đồng âm (đặc biệt các thuật ngữ chuyên ngành).\n"
            f"2. Trình bày lại văn bản thành định dạng Markdown đẹp mắt, mạch lạc (chia đoạn, dùng bullet points nếu cần, in đậm ý chính).\n"
            f"3. TUYỆT ĐỐI CHỈ TRẢ VỀ NỘI DUNG VĂN BẢN ĐÃ ĐỊNH DẠNG. KHÔNG CHÀO HỎI, KHÔNG GIẢI THÍCH, KHÔNG BÌNH LUẬN THÊM BẤT CỨ ĐIỀU GÌ NHƯ 'Đây là văn bản...'.\n"
            f"4. TUYỆT ĐỐI KHÔNG tóm tắt hay cắt xén nội dung, phải giữ nguyên toàn bộ lượng thông tin.\n\n"
            f"VĂN BẢN GỐC:\n---\n{chunk}\n---"
        )
        result = call_llm(
            prompt, 
            task="correction", 
            validator=lambda x: len(x) > len(chunk) * 0.4
        )
        if result:
            formatted_chunks.append(result.strip())
        else:
            _logger.warning(f"Chunk {i} formatting failed all tiers. Using original.")
            formatted_chunks.append(chunk.strip())
            
    return "\n\n---\n\n".join(formatted_chunks)
