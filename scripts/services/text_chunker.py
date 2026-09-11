"""VvC Second Brain — Text Chunker & Orthographic Corrector.

Handles semantic chunking and LLM-based orthographic corrections.
"""

import logging
import re

from core.llm import call_llm
from core.prompts.services import (
    ORTHOGRAPHIC_CORRECTION_PLAIN,
    ORTHOGRAPHIC_CORRECTION_TIMESTAMPED,
)

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
            prompt = ORTHOGRAPHIC_CORRECTION_TIMESTAMPED.format(chunk=chunk)
        else:
            prompt = ORTHOGRAPHIC_CORRECTION_PLAIN.format(chunk=chunk)
            
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
