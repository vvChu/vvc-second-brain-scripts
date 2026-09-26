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
from services.orthography import orthographic_preprocess
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

def _build_duplicate_feedback(entry: dict, url: str) -> list[str]:
    """Generate formatted feedback links for a duplicate URL entry."""
    src = entry.get("source_note", "")
    fb = [f"- [[{src}|Ghi chép gốc (Đã xử lý trước đó)]]"] if src else [f"- URL gốc: [{url}]({url}) (Đã xử lý trước đó)"]
    for c in entry.get("concepts", []):
        c_stem, c_title = c.get("stem", ""), c.get("title", "")
        if c_stem and c_title:
            fb.append(f"  - [[{c_stem}|{c_title}]] (Đã tồn tại)")
    return fb


def _strip_duplicate_url_from_line(stripped: str, url: str) -> str | None:
    """Return preserved handwritten notes if any, or None if line was purely URL/controls."""
    temp = stripped.replace(url, "")
    for kw in ["xử lý lại", "tải lại", "nạp lại", "chạy lại", "cập nhật", "reprocess", "/force", "force", "override"]:
        temp = temp.replace(kw, "")
    clean = re.sub(r"[#\*\-\s\(\)\[\]]+", "", temp)
    if len(clean) >= 3:
        _logger.info(f"[Deduplication] URL {url} trùng nhưng dòng có ghi chép viết tay. Giữ lại chữ.")
        return stripped.replace(url, f"*(URL đã xử lý: {url})*")
    _logger.info(f"[Deduplication] Chặn URL trùng: {url}. Đã tạo Auto-Feedback.")
    return None


def _deduplicate_dump_urls(
    dump_text: str,
) -> tuple[str, list[str], list[str], set[str], dict[str, str], bool]:
    """Inspect URLs in dump lines, deduplicate against registry, and generate auto-feedback."""
    registry = _load_url_registry()
    remaining_lines: list[str] = []
    auto_feedback: list[str] = []
    urls_to_scrape: list[str] = []
    visual_urls: set[str] = set()
    url_normalization_map: dict[str, str] = {}
    inbox_updated_directly = False

    for line in dump_text.splitlines():
        stripped = line.strip()
        found_urls = _URL_PATTERN.findall(stripped) if stripped else []
        if not found_urls:
            remaining_lines.append(line)
            continue

        url = found_urls[0]
        norm = _normalize_url(url)
        url_normalization_map[url] = norm
        if "youtube.com" in url or "youtu.be" in url or "/visual" in stripped.lower():
            visual_urls.add(url)
            line = re.sub(r"/visual\s*", "", line, flags=re.IGNORECASE)
            stripped = re.sub(r"/visual\s*", "", stripped, flags=re.IGNORECASE).strip()

        if norm in registry and not _check_override(stripped):
            inbox_updated_directly = True
            auto_feedback.extend(_build_duplicate_feedback(registry[norm], url))
            line_rem = _strip_duplicate_url_from_line(stripped, url)
            if line_rem:
                remaining_lines.append(line_rem)
        else:
            remaining_lines.append(line)
            urls_to_scrape.append(url)

    return "\n".join(remaining_lines), auto_feedback, urls_to_scrape, visual_urls, url_normalization_map, inbox_updated_directly


def _isolate_image_metadata(url_content: str) -> tuple[str, str]:
    """Split and isolate image/visual metadata markers from URL content."""
    for marker in ("\n\n## 🖼️ Hình ảnh bài viết", "\n\n## 🎞️", "\n\n## 🎬"):
        if marker in url_content:
            idx = url_content.index(marker)
            return url_content[:idx], url_content[idx:]
    return url_content, ""


def _preprocess_and_save_transcripts(
    new_dump_text: str, url_content: str, urls_to_scrape: list[str]
) -> tuple[str, str, str]:
    """Apply orthographic preprocessing and save transcript source note."""
    orig_url = urls_to_scrape[0] if urls_to_scrape else ""
    source_ref = "brain_dump"
    if url_content:
        clean_url_content, img_meta = _isolate_image_metadata(url_content)
        url_content = f"{orthographic_preprocess(clean_url_content)}{img_meta}"
        saved = _save_transcript(url_content, orig_url)
        if saved:
            source_ref = saved
        return new_dump_text, url_content, source_ref

    processed = orthographic_preprocess(new_dump_text)
    saved = _save_transcript(processed, orig_url)
    if saved:
        source_ref = saved
    return processed, "", source_ref


def _update_processed_registry(
    urls_to_scrape: list[str],
    url_norm_map: dict[str, str],
    source_ref: str,
    saved_stems: list[tuple[str, str]],
) -> None:
    """Record newly scraped URLs into URL registry."""
    if not urls_to_scrape:
        return
    registry = _load_url_registry()
    for u in urls_to_scrape:
        norm = url_norm_map.get(u)
        if norm:
            registry[norm] = {
                "source_note": source_ref,
                "concepts": [{"stem": stem, "title": title} for stem, title in saved_stems],
                "processed_at": datetime.now().isoformat(),
            }
    _save_url_registry(registry)


def _finalize_brain_dump(
    dump_text: str,
    content_hash: str,
    saved_stems: list[tuple[str, str]],
    auto_feedback: list[str],
    source_ref: str,
    urls_to_scrape: list[str],
    url_norm_map: dict[str, str],
) -> None:
    """Commit inbox changes, register hash, update registry and rebuild MOCs."""
    all_links = [f"- [[{s}|{t}]]" for s, t in saved_stems]
    all_links.extend(auto_feedback)
    if not all_links:
        if source_ref and source_ref != "brain_dump":
            all_links.append(f"- [[{source_ref}|Ghi chép gốc (Nội dung đã được hấp thụ vào kho tri thức)]]")
        else:
            all_links.append("- *(Nội dung đã được đối soát và hấp thụ vào các khái niệm hiện có)*")

    _commit_inbox_changes(dump_text, "", all_links)
    _register_processed_hash(content_hash)
    _update_processed_registry(urls_to_scrape, url_norm_map, source_ref, saved_stems)

    if saved_stems:
        try:
            from wiki_maintain import rebuild_incremental
            for stem, _ in saved_stems:
                c_file = cfg.concepts_dir / f"{stem}.md"
                if c_file.exists():
                    rebuild_incremental(c_file)
        except Exception as e:
            _logger.warning(f"Brain dump incremental MOC rebuild failed: {e}")


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

    content_hash = hashlib.md5(dump_text.encode("utf-8")).hexdigest()
    if _is_recently_processed(content_hash):
        _logger.warning("Resurrection bug detected. Re-clearing inbox.")
        log("dump", "Resurrection bug self-healed.")
        _clear_inbox_only(dump_text)
        return

    _logger.info(f"Processing Brain Dump ({len(dump_text)} chars)")
    log("dump", f"Brain Dump detected ({len(dump_text)} chars)")

    new_dump, auto_fb, urls_scrape, visual_urls, url_map, directly_updated = _deduplicate_dump_urls(dump_text)
    if directly_updated and not urls_scrape and not new_dump.strip():
        if auto_fb:
            _commit_inbox_changes(dump_text, "", auto_fb)
            log("dump", "Deduplication: All URLs were duplicates. Auto-feedback links appended.")
        else:
            _clear_inbox_only(dump_text)
        _register_processed_hash(content_hash)
        return

    url_content = _process_urls(new_dump, urls_scrape, visual_urls)
    if not url_content and not _is_meaningful_dump(new_dump):
        _logger.warning("Brain Dump rejected: Semantic Arbitrator deemed text not meaningful.")
        log("dump", "Rejected: Text not meaningful.")
        if auto_fb:
            _commit_inbox_changes(dump_text, "", auto_fb)
        else:
            _clear_inbox_only(dump_text)
        _register_processed_hash(content_hash)
        return

    proc_text, proc_url, source_ref = _preprocess_and_save_transcripts(new_dump, url_content, urls_scrape)
    saved_stems = _synthesize_and_save_concepts(proc_text, proc_url, source_ref)
    _finalize_brain_dump(dump_text, content_hash, saved_stems, auto_fb, source_ref, urls_scrape, url_map)
    log("dump", f"Completed: {len(saved_stems)} concepts created (transcript: {source_ref})")
    _logger.info(f"Brain Dump: {len(saved_stems)} concepts created (transcript: {source_ref})")

