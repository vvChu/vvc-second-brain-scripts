"""VvC Second Brain — Brain Dump Orchestrator.

Main entry point for processing Brain_Dump.md content.
Handles idempotency, noise gating, URL deduplication routing, and flow control.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from services.text_chunker import orthographic_preprocess
from services.brain_dump.inbox_io import (
    _find_pending_dump, _extract_inbox_sections,
    _commit_inbox_changes, _clear_inbox_only,
)
from services.brain_dump.url_registry import (
    _URL_PATTERN, _normalize_url, _check_override,
    _load_url_registry, _save_url_registry, _process_urls,
)
from services.brain_dump.concept_synthesis import (
    _save_transcript, _synthesize_and_save_concepts,
)

_logger = logging.getLogger("vvc.dump")


# --- Idempotency State (Anti-Resurrection) ---

_STATE_FILE = cfg.state_dir / ".dump_state.json"

def _is_recently_processed(content_hash: str) -> bool:
    """Check if we recently processed this exact text hash to prevent sync loops."""
    try:
        if _STATE_FILE.exists():
            state = json.loads(_STATE_FILE.read_text())
            return content_hash in state.get("processed_hashes", [])
    except Exception:
        pass
    return False


def _register_processed_hash(content_hash: str) -> None:
    """Register a successfully processed text hash to prevent sync loops."""
    if not content_hash:
        return
    try:
        if _STATE_FILE.exists():
            state = json.loads(_STATE_FILE.read_text())
        else:
            state = {"processed_hashes": []}
    except Exception:
        state = {"processed_hashes": []}
        
    state["processed_hashes"] = state.get("processed_hashes", [])
    if content_hash not in state["processed_hashes"]:
        state["processed_hashes"].append(content_hash)
        state["processed_hashes"] = state["processed_hashes"][-20:]
        try:
            _STATE_FILE.write_text(json.dumps(state))
        except OSError:
            pass


def _is_meaningful_dump(text: str) -> bool:
    """Evaluate if the text is meaningful enough to generate a concept."""
    # Clean text by removing URLs for evaluation
    clean_text = _URL_PATTERN.sub("", text).strip()
    
    if not clean_text:
        return False
        
    if len(clean_text) > 2000:
        return True # Long texts are generally meaningful
        
    prompt = (
        f"Bạn là người gác cổng tri thức (Semantic Arbitrator). Hãy đánh giá xem đoạn văn bản "
        f"dưới đây có chứa ít nhất một ý tưởng, quan điểm, khái niệm, hoặc thông tin CÓ Ý NGHĨA "
        f"nào xứng đáng để lưu trữ vào hệ thống quản lý tri thức Zettelkasten hay không?\n"
        f"TUYỆT ĐỐI TỪ CHỐI (Trả lời NO) nếu:\n"
        f"- Chỉ là một câu chào hỏi, lời nói bâng quơ, hoặc câu mệnh lệnh ngắn (ví dụ: 'hãy xử lý youtube', 'test thử', 'alo').\n"
        f"- Văn bản quá ngắn, tối nghĩa, hoặc là rác do lỗi copy/paste.\n"
        f"Trả lời CHÍNH XÁC: 'YES' hoặc 'NO'.\n\n"
        f"VĂN BẢN:\n---\n{clean_text}\n---"
    )
    result = call_llm(prompt, task="correction")
    return bool(result and result.strip().upper().startswith("YES"))

def handle_brain_dump() -> None:
    """Process pending content in Brain_Dump.md."""
    if not cfg.dump_file.exists():
        return
    try:
        content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return

    dump_text = _find_pending_dump(content)
    if not dump_text:
        return

    content_hash = hashlib.md5(dump_text.encode('utf-8')).hexdigest()
    if _is_recently_processed(content_hash):
        _logger.warning("Resurrection bug detected. Re-clearing inbox.")
        log("dump", "Resurrection bug self-healed.")
        _clear_inbox_only(dump_text)
        return

    _logger.info(f"Processing Brain Dump ({len(dump_text)} chars)")
    log("dump", f"Brain Dump detected ({len(dump_text)} chars)")

    # Phân tích và chặn trùng lặp JIT từng dòng chứa URL
    lines = dump_text.splitlines()
    registry = _load_url_registry()
    
    remaining_lines = []
    auto_feedback_links = []
    urls_to_scrape = []
    url_normalization_map = {}
    visual_urls = set()
    
    inbox_updated_directly = False
    
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            remaining_lines.append(line)
            continue
            
        found_urls = _URL_PATTERN.findall(stripped_line)
        if not found_urls:
            remaining_lines.append(line)
            continue
            
        # Có URL trên dòng này!
        has_override = _check_override(stripped_line)
        url = found_urls[0]
        norm_url = _normalize_url(url)
        url_normalization_map[url] = norm_url
        
        # Tự động kích hoạt visual cho mọi URL YouTube (hoặc nếu dòng chứa /visual)
        is_youtube = "youtube.com" in url or "youtu.be" in url
        if is_youtube or "/visual" in stripped_line.lower():
            visual_urls.add(url)
            # Dọn dẹp từ khóa điều khiển /visual khỏi dòng ghi chép nếu có
            line = re.sub(r"/visual\s*", "", line, flags=re.IGNORECASE)
            stripped_line = re.sub(r"/visual\s*", "", stripped_line, flags=re.IGNORECASE).strip()
            
        # Nếu URL đã xử lý và KHÔNG có từ khóa override
        if norm_url in registry and not has_override:
            entry = registry[norm_url]
            source_note = entry.get("source_note", "")
            concepts = entry.get("concepts", [])
            
            feedback_lines = []
            if source_note:
                feedback_lines.append(f"- [[{source_note}|Ghi chép gốc (Đã xử lý trước đó)]]")
            else:
                feedback_lines.append(f"- URL gốc: [{url}]({url}) (Đã xử lý trước đó)")
                
            for c in concepts:
                c_stem = c.get("stem", "")
                c_title = c.get("title", "")
                if c_stem and c_title:
                    feedback_lines.append(f"  - [[{c_stem}|{c_title}]] (Đã tồn tại)")
                    
            auto_feedback_links.extend(feedback_lines)
            
            # Kiểm tra xem dòng đó có chứa văn bản viết tay có nghĩa không
            temp_line = stripped_line.replace(url, "")
            for kw in ["xử lý lại", "tải lại", "nạp lại", "chạy lại", "cập nhật",
                        "reprocess", "/force", "force", "override"]:
                temp_line = temp_line.replace(kw, "")
            temp_line_clean = re.sub(r"[#\*\-\s\(\)\[\]]+", "", temp_line)
            
            if len(temp_line_clean) < 3:
                # Dòng chỉ chứa URL hoặc từ khóa điều khiển -> Xóa hẳn
                inbox_updated_directly = True
                _logger.info(f"[Deduplication] Chặn URL trùng: {url}. Đã tạo Auto-Feedback.")
            else:
                # Dòng chứa ghi chép viết tay quan trọng -> Giữ lại phần chữ, thay thế URL bằng ghi chú
                line_without_url = stripped_line.replace(url, f"*(URL đã xử lý: {url})*")
                remaining_lines.append(line_without_url)
                inbox_updated_directly = True
                _logger.info(f"[Deduplication] URL {url} trùng nhưng dòng có ghi chép viết tay. Giữ lại chữ.")
        else:
            # URL mới hoặc có override
            remaining_lines.append(line)
            urls_to_scrape.append(url)
            
    # Tái tạo dump_text cho phần còn lại
    new_dump_text = "\n".join(remaining_lines)
    
    # Nếu tất cả các URL đều bị chặn trùng lặp và không còn nội dung nào mới cần xử lý
    if inbox_updated_directly and not urls_to_scrape and not new_dump_text.strip():
        if auto_feedback_links:
            # Xóa inbox và append các feedback link vào Processed
            _commit_inbox_changes(dump_text, "", auto_feedback_links)
            _register_processed_hash(content_hash)
            log("dump", "Deduplication: All URLs were duplicates. Auto-feedback links appended.")
            _logger.info("Deduplication: All URLs were duplicates. Auto-feedback links appended.")
        else:
            _clear_inbox_only(dump_text)
            _register_processed_hash(content_hash)
        return

    url_content = _process_urls(new_dump_text, urls_to_scrape, visual_urls)

    # Semantic Arbitrator: Reject noise if no valid URL content was extracted
    if not url_content and not _is_meaningful_dump(new_dump_text):
        _logger.warning("Brain Dump rejected: Semantic Arbitrator deemed text not meaningful.")
        log("dump", "Rejected: Text not meaningful.")
        # Cần ghi lại file nếu có auto_feedback_links trước đó!
        if auto_feedback_links:
            _commit_inbox_changes(dump_text, "", auto_feedback_links)
            _register_processed_hash(content_hash)
        else:
            _clear_inbox_only(dump_text)
            _register_processed_hash(content_hash)
        return

    # Orthographic correction - use separate variable to preserve original dump_text
    processed_text = new_dump_text
    source_ref = "brain_dump"
    
    # Extract URL if present (chỉ lấy URL thực sự được cào)
    original_url = ""
    if urls_to_scrape:
        original_url = urls_to_scrape[0]

    # --- Preserve image metadata through orthographic correction ---
    # Image metadata section ([IMG:...] markers) is appended by url_fetcher
    # but would be destroyed by LLM correction. Strip it, correct text, re-append.
    _IMG_SECTION_MARKER = "\n\n## 🖼️ Hình ảnh bài viết"
    _VIDEO_VISUAL_MARKER = "\n\n## 🎞️"
    _VIDEO_IMG_SECTION_MARKER = "\n\n## 🎬"
    image_metadata_section = ""
    
    if url_content:
        if _IMG_SECTION_MARKER in url_content:
            split_idx = url_content.index(_IMG_SECTION_MARKER)
            image_metadata_section = url_content[split_idx:]
            url_content = url_content[:split_idx]
        elif _VIDEO_VISUAL_MARKER in url_content:
            split_idx = url_content.index(_VIDEO_VISUAL_MARKER)
            image_metadata_section = url_content[split_idx:]
            url_content = url_content[:split_idx]
        elif _VIDEO_IMG_SECTION_MARKER in url_content:
            split_idx = url_content.index(_VIDEO_IMG_SECTION_MARKER)
            image_metadata_section = url_content[split_idx:]
            url_content = url_content[:split_idx]

    if url_content:
        url_content = orthographic_preprocess(url_content)
        # Re-append image metadata (preserved verbatim, never corrected)
        if image_metadata_section:
            url_content = f"{url_content}{image_metadata_section}"
        saved_ref = _save_transcript(url_content, original_url)
        if saved_ref:
            source_ref = saved_ref
    else:
        processed_text = orthographic_preprocess(new_dump_text)
        saved_ref = _save_transcript(processed_text, original_url)
        if saved_ref:
            source_ref = saved_ref

    saved_stems = _synthesize_and_save_concepts(processed_text, url_content, source_ref)

    if saved_stems or auto_feedback_links:
        # Gom toàn bộ links (cả concept mới sinh và concept cũ từ auto_feedback_links)
        all_links = []
        if saved_stems:
            all_links.extend(f"- [[{stem}|{title}]]" for stem, title in saved_stems)
        if auto_feedback_links:
            all_links.extend(auto_feedback_links)
            
        _commit_inbox_changes(dump_text, "", all_links)
        _register_processed_hash(content_hash)
        
        # Cập nhật registry cho các URL đã được xử lý thành công trong lượt này
        if saved_stems:
            registry = _load_url_registry()
            for url in urls_to_scrape:
                norm_url = url_normalization_map.get(url)
                if norm_url:
                    registry[norm_url] = {
                        "source_note": source_ref,
                        "concepts": [{"stem": stem, "title": title} for stem, title in saved_stems],
                        "processed_at": datetime.now().isoformat()
                    }
            _save_url_registry(registry)
            
        log("dump", f"Completed: {len(saved_stems)} concepts created")
        _logger.info(f"Brain Dump: {len(saved_stems)} concepts created")
