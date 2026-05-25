"""VvC Second Brain — Brain Dump Handler (v7.0).

Processes Brain_Dump.md: extracts ideas, fetches URLs, creates concept notes.

Usage:
    from services.brain_dump import handle_brain_dump
    handle_brain_dump()  # Called by daemon.py polling loop
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from pipeline.post_process import save_concept

from services.url_fetcher import fetch_url, fetch_url_title
from services.text_chunker import orthographic_preprocess
from core.frontmatter import normalize_stem
from pipeline.synthesize import fix_section_ordering

try:
    from wiki_maintain import rebuild_all as _rebuild_all
except ImportError:
    _rebuild_all = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.dump")

# --- URL Extraction ---

_URL_PATTERN = re.compile(r"https?://[^\s\]\)>]+")


# --- Brain Dump Detection ---

_DUMP_MARKER = "---"
_PROCESSED_MARKER = "<!-- processed -->"


def _extract_inbox_sections(content: str) -> tuple[str, str, str]:
    """Extracts inbox content and splits the file.
    Returns (before_inbox, inbox_content, after_inbox)
    """
    match = re.search(r"(##\s*Inbox[ \t]*\n)(.*?)(?=\n##\s*|\Z)", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return "", "", ""
    
    before = content[:match.start(2)]
    inbox = match.group(2).strip()
    after = content[match.end(2):]
    return before, inbox, after


def _find_pending_dump(content: str) -> str | None:
    """Find unprocessed brain dump content from ## Inbox."""
    _, inbox, _ = _extract_inbox_sections(content)
    if inbox and len(inbox) >= 10:
        return inbox

    # Fallback to legacy marker if ## Inbox is not found
    if _PROCESSED_MARKER in content:
        parts = content.rsplit(_PROCESSED_MARKER, 1)
        remaining = parts[1].strip() if len(parts) > 1 else ""
        if len(remaining) >= 20:
            return remaining

    return None


# --- Idempotency State (Anti-Resurrection) ---

_STATE_FILE = Path(__file__).parent.parent / ".dump_state.json"

def _is_recently_processed(content_hash: str) -> bool:
    """Check if we recently processed this exact text hash to prevent sync loops."""
    try:
        if _STATE_FILE.exists():
            state = json.loads(_STATE_FILE.read_text())
        else:
            state = {"processed_hashes": []}
    except Exception:
        state = {"processed_hashes": []}
        
    if content_hash in state.get("processed_hashes", []):
        return True
        
    # Add to state and keep last 20
    state["processed_hashes"] = state.get("processed_hashes", [])
    state["processed_hashes"].append(content_hash)
    state["processed_hashes"] = state["processed_hashes"][-20:]
    try:
        _STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass
    return False

def _clear_inbox_only(dump_text: str) -> None:
    """Clear the processed dump_text from Inbox without generating new concepts (Self-Healing mode)."""
    try:
        current_content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return
    before, inbox, after = _extract_inbox_sections(current_content)
    if before and inbox:
        new_inbox = inbox.replace(dump_text, "").strip()
        if new_inbox:
            new_inbox = "\n" + new_inbox + "\n"
        else:
            new_inbox = "\n\n"
            
        if not after.startswith("\n"):
            after = "\n" + after
        new_content = before + new_inbox + after
        try:
            cfg.dump_file.write_text(new_content, encoding="utf-8")
        except OSError:
            pass



# --- Map-Reduce Prompts ---

_MAP_PROMPT = """Bạn là chuyên gia phân tích (Semantic Arbitrator). Đọc nội dung dưới đây và trích xuất ra một danh sách các "Ý TƯỞNG CỐT LÕI" (Atomic Concepts) độc lập.

BRAIN DUMP:
---
{dump_text}
---

NỘI DUNG TỪ URLs (nếu có):
---
{url_content}
---

YÊU CẦU:
1. Mỗi ý tưởng phải thực sự độc lập, mang một giá trị kiến thức cụ thể.
2. BẮT BUỘC: Bạn phải dịch và đặt tiêu đề (title) của khái niệm bằng tiếng Việt ngắn gọn, súc tích và chuẩn học thuật (ngay cả khi nguồn gốc là tiếng Anh).
3. Trả về đúng định dạng JSON array:
```json
[
  {{"title": "Tiêu đề khái niệm bằng tiếng Việt chuẩn có dấu (ví dụ: Quản trị tự thân số)", "summary": "Tóm tắt 1-2 câu về ý tưởng này bằng tiếng Việt"}}
]
```
Chỉ trả về chuỗi JSON hợp lệ, không giải thích gì thêm. Tùy thuộc vào độ nén thông tin của văn bản, hãy trích xuất TẤT CẢ các ý tưởng thực sự mang tính cốt lõi và đắt giá (BẮT BUỘC: chỉ trích xuất từ tối thiểu {min_concepts} đến tối đa {max_concepts} ý tưởng). TUYỆT ĐỐI KHÔNG trích xuất để đủ số lượng, hãy mạnh tay loại bỏ các ý tưởng vụn vặt hoặc hiển nhiên.
"""

_REDUCE_PROMPT = """Bạn là trợ lý biên soạn tri thức Zettelkasten.
Dựa vào nội dung NGUỒN dưới đây, hãy tạo 1 Concept Note duy nhất cho ý tưởng: "{concept_title}" ({concept_summary}).

<source_material>
{dump_text}
{url_content}
</source_material>

<rules>
1. Bạn TUYỆT ĐỐI PHẢI tuân thủ chính xác cấu trúc trong <output_template>. KHÔNG THÊM BẤT KỲ HEADING NÀO KHÁC (không `# Tên khái niệm`, không `## Implications`, không `## Connections`).
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`. Việc bỏ sót sẽ làm hỏng hệ thống.
3. Trong phần YAML frontmatter:
   - Trực tiếp trích xuất thực thể con người liên quan và điền vào trường `people: []` (ví dụ: `people: ["Jensen Huang", "Geoffrey Hinton"]`).
   - Trực tiếp trích xuất thực thể công ty/tổ chức liên quan và điền vào trường `companies: []` (ví dụ: `companies: ["Nvidia", "Google"]`).
   - Tuyệt đối KHÔNG đưa tên người hoặc tên công ty vào tags (không gán `domain/nvidia` hay `domain/jensen_huang`).
   - Trường `tags` chỉ được chứa lĩnh vực tri thức lớn (ví dụ: `domain/ai`, `domain/management`, `domain/strategy`, `domain/psychology`, `domain/finance`, v.v.) cùng với hai tags mặc định là `knowledge` và `type/concept`.
   - Trường `status` luôn mặc định là `seed` cho các concept mới sinh tự động.
   - Trường `source_page`, `source_chapter`, `ground_truth_page`, `ground_truth_chapter` để trống (vì đây là nguồn ghi chép / text).
4. Triệt tiêu trùng lặp ngữ nghĩa & Chuẩn hóa song ngữ (CRITICAL):
   - Trường `summary` trong YAML: tuyên bố siêu súc tích một câu phản ánh INSIGHT cốt lõi. PHẢI khác nội dung blockquote Evidence Hook bên dưới.
   - **Evidence Hook** (blockquote ngay dưới frontmatter): Trích dẫn/ý tưởng cốt lõi đắt giá nhất lấy trực tiếp từ NGUỒN, dịch sát nghĩa sang tiếng Việt. Dưới blockquote này, bạn PHẢI tự động thêm một dòng trích dẫn khoa học dạng:
     `> — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])`
   - **`## Core Idea`**: PHÂN TÍCH THUẦN hoàn toàn bằng tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook. Tập trung diễn giải cơ chế, hệ quả.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: PHẢI hiển thị bằng **tiếng Anh nguyên bản** (nếu nguồn gốc là tiếng Anh) để làm căn cứ học thuật đối chiếu. Nếu nguồn hoàn toàn bằng tiếng Việt, hãy ghi rõ "(không có)".
5. Viết nội dung phân tích hoàn toàn bằng tiếng Việt (trừ các thuật ngữ tiếng Anh chuyên môn chưa có từ tương đương).
</rules>

<output_template>
```markdown
---
title: "{concept_title}"
aliases:
  - "tên gọi khác 1"
tags:
  - knowledge
  - type/concept
  - domain/<lĩnh_vực_chuyên_môn_lớn>
type: concept
date_created: {today}
date_modified: {today}
source: "{source_ref}"
source_page: ""
source_chapter: ""
ground_truth_page: ""
ground_truth_chapter: ""
source_type: text
summary: "{concept_summary}"
people: []
companies: []
status: seed
related: []
confidence: high
---

> "Trích dẫn lại nguyên văn phần quan trọng nhất lấy từ NGUỒN làm bằng chứng, dịch sang tiếng Việt — Evidence Hook."
> — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])

## Core Idea

Đoạn phân tích chuyên sâu (200-400 từ) bằng tiếng Việt giải thích cặn kẽ tại sao khái niệm này quan trọng, nó hoạt động như thế nào và có ý nghĩa gì. Tránh lặp lại câu trích dẫn Evidence Hook ở trên. Bạn có thể sử dụng các tiêu đề cấp 3 (###) nếu cần chia nhỏ bài phân tích.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> "Original English quote or paragraph representing the academic ground truth for this concept."

---

## References

- [[{source_ref}]]
```
</output_template>
"""


def _process_urls(dump_text: str) -> str:
    urls = _URL_PATTERN.findall(dump_text)
    if not urls:
        return ""
    fetched = []
    for url in urls[:5]:
        text = fetch_url(url)
        if text:
            fetched.append(f"[{url}]\n{text}")
    return "\n\n".join(fetched)


def _save_transcript(text: str, original_url: str = "") -> str:
    """Save processed transcript to 04 - Permanent/sources/transcripts. Returns file stem."""
    if not text or len(text.strip()) < 50:
        return ""
        
    transcripts_dir = cfg.sources_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp_date = date.today().isoformat()
    title = ""
    if original_url:
        title = fetch_url_title(original_url)
        
    if title:
        slug = normalize_stem(title)
        if len(slug) > 40:
            slug = slug[:40].rsplit("_", 1)[0]
        filename = f"{timestamp_date}_{slug}.md"
        display_title = title
    elif original_url:
        # Fallback: derive slug from URL domain + path
        from urllib.parse import urlparse
        parsed = urlparse(original_url)
        host = (parsed.hostname or "").replace("www.", "")
        path_parts = parsed.path.strip("/").split("/")
        path_slug = normalize_stem(path_parts[-1]) if path_parts and path_parts[-1] else ""
        if path_slug and len(path_slug) > 5:
            slug = path_slug[:40].rsplit("_", 1)[0] if len(path_slug) > 40 else path_slug
        else:
            slug = normalize_stem(host.split(".")[0])
        filename = f"{timestamp_date}_{slug}.md"
        display_title = f"Brain Dump Source — {host}"
    else:
        timestamp_time = datetime.now().strftime("%H%M%S")
        filename = f"{timestamp_date}_{timestamp_time}_BrainDump_Source.md"
        display_title = f"Brain Dump Source {timestamp_date} {timestamp_time}"
        
    filepath = transcripts_dir / filename
    
    fm = (
        f"---\n"
        f"title: \"{display_title}\"\n"
        f"aliases:\n  - \"{filename[:-3]}_Source\"\n"
        f"tags:\n  - knowledge\n  - type/source\n"
        f"type: source\n"
        f"date_created: {date.today().isoformat()}\n"
        f"date_modified: {date.today().isoformat()}\n"
        f"source: \"brain_dump\"\n"
        f"source_type: text\n"
        f"summary: \"Raw transcript extracted via Brain Dump Watchdog.\"\n"
        f"related: []\n"
        f"confidence: high\n"
        f"---\n\n"
    )
    
    if original_url:
        import datetime as dt
        body = (
            f"> [!info] 🌐 Nguồn thu thập (Brain Dump)\n"
            f"> **Link gốc:** [{original_url}]({original_url})\n"
            f"> **Thời gian:** {dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
            f"## 📝 Nội dung thô (Transcript / Text Extracted)\n\n{text}\n"
        )
    else:
        body = f"# Raw Sources for Brain Dump\n\n{text}\n"
    
    try:
        filepath.write_text(fm + body, encoding="utf-8")
        _logger.info(f"Saved source text to {filepath.name}")
        return filepath.stem
    except OSError as e:
        _logger.warning(f"Failed to save transcript {filename}: {e}")
        return ""

def _synthesize_and_save_concepts(dump_text: str, url_content: str, source_ref: str) -> list[tuple[str, str]]:
    today = date.today().isoformat()
    
    # Calculate proportional dynamic concept extraction limits based on raw input length
    total_len = len(dump_text) + len(url_content)
    if total_len < 5000:
        min_c, max_c = 1, 3
    elif total_len < 20000:
        min_c, max_c = 3, 7
    elif total_len < 50000:
        min_c, max_c = 5, 12
    else:
        min_c, max_c = 8, 18
        
    _logger.info(f"[Map-Reduce] Calculated dynamic limit based on raw text volume ({total_len} chars): min={min_c}, max={max_c} concepts.")
    
    # --- MAP STEP (Extraction) ---
    map_prompt = _MAP_PROMPT.format(
        dump_text=dump_text,
        url_content=url_content or "(không có URL content)",
        min_concepts=min_c,
        max_concepts=max_c,
    )
    
    _logger.info("Executing Map step: Extracting atomic concepts via Reasoning tier...")
    map_result = call_llm(map_prompt, task="reasoning")
    if not map_result:
        log("error", "Brain Dump MAP step failed")
        return []
        
    try:
        # Extract JSON from the output (handling markdown code blocks if any)
        json_match = re.search(r'\[\s*\{.*\}\s*\]', map_result, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = map_result
            
        concepts_list = json.loads(json_str)
        if not isinstance(concepts_list, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        _logger.error(f"Failed to parse MAP step JSON: {e}")
        log("error", "Brain Dump MAP step failed to parse JSON")
        return []
        
    _logger.info(f"Map step found {len(concepts_list)} concepts. Starting Reduce step...")
    
    # Extract original URL if present
    original_url = ""
    urls = _URL_PATTERN.findall(dump_text)
    if urls:
        original_url = urls[0]

    # --- REDUCE STEP (Synthesis) ---
    saved_stems = []
    for idx, concept_meta in enumerate(concepts_list):
        c_title = concept_meta.get("title", f"Concept {idx+1}")
        c_summary = concept_meta.get("summary", "")
        
        _logger.info(f"Reducing concept {idx+1}/{len(concepts_list)}: {c_title}")
        
        reduce_prompt = _REDUCE_PROMPT.format(
            dump_text=dump_text,
            url_content=url_content or "(không có URL content)",
            concept_title=c_title,
            concept_summary=c_summary,
            today=today,
            source_ref=source_ref
        )
        
        concept_body = call_llm(reduce_prompt, task="synthesis")
        if not concept_body or len(concept_body) < 100:
            _logger.warning(f"Failed to generate concept: {c_title}")
            continue
            
        # Robustly extract from the first YAML marker
        match = re.search(r"(---\n.*)", concept_body, re.DOTALL)
        if not match:
            _logger.warning(f"Failed to find YAML frontmatter for: {c_title}")
            continue
            
        concept_clean = match.group(1)
        concept_clean = re.sub(r"\n```\s*$", "", concept_clean)
        
        # Apply strict section ordering
        concept_clean = fix_section_ordering(concept_clean)
        
        # Add Premium Source Callout at the bottom of the concept
        if original_url:
            import datetime as dt
            time_str = dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            source_callout = (
                f"\n\n> [!info]- 🌐 Nguồn thu thập\n"
                f"> Ghi chép được thu thập từ internet (click để mở)\n"
                f"> - **Đường dẫn gốc:** [{original_url}]({original_url})\n"
                f"> - **Thời gian thu thập:** {time_str}\n"
                f"> - **Tệp nguồn thô:** [[{source_ref}]]\n"
            )
            concept_clean = f"{concept_clean.rstrip()}{source_callout}"
            
        saved_path = save_concept(concept_clean)
        if saved_path:
            saved_stems.append((saved_path.stem, c_title))
            
    return saved_stems

def _mark_dump_processed(dump_text: str, saved_concepts: list[tuple[str, str]]) -> None:
    try:
        current_content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return
        
    before, inbox, after = _extract_inbox_sections(current_content)
    if before and inbox:
        # Avoid race condition: only remove the text we actually processed
        new_inbox = inbox.replace(dump_text, "").strip()
        if new_inbox:
            new_inbox = "\n" + new_inbox + "\n"
        else:
            new_inbox = "\n\n"
            
        links_str = "\n".join(f"- [[{stem}|{title}]]" for stem, title in saved_concepts)
        if not after.startswith("\n"):
            after = "\n" + after
        if "## Processed" in after:
            if not after.endswith("\n"):
                after += "\n"
            after = re.sub(r"(##\s*Processed\s*\n)", f"\\1{links_str}\n", after, count=1, flags=re.IGNORECASE)
        else:
            after += f"\n## Processed\n{links_str}\n"
        new_content = before + new_inbox + after
        cfg.dump_file.write_text(new_content, encoding="utf-8")
    else:
        new_content = current_content + f"\n\n{_PROCESSED_MARKER}\n"
        cfg.dump_file.write_text(new_content, encoding="utf-8")

    if _rebuild_all is not None:
        try:
            _rebuild_all()
        except Exception:
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

    url_content = _process_urls(dump_text)

    # Semantic Arbitrator: Reject noise if no valid URL content was extracted
    if not url_content and not _is_meaningful_dump(dump_text):
        _logger.warning("Brain Dump rejected: Semantic Arbitrator deemed text not meaningful.")
        log("dump", "Rejected: Text not meaningful.")
        _clear_inbox_only(dump_text)
        return

    # Orthographic correction - use separate variable to preserve original dump_text
    processed_text = dump_text
    source_ref = "brain_dump"
    
    # Extract URL if present
    original_url = ""
    urls = _URL_PATTERN.findall(dump_text)
    if urls:
        original_url = urls[0]
        
    if url_content:
        url_content = orthographic_preprocess(url_content)
        saved_ref = _save_transcript(url_content, original_url)
        if saved_ref:
            source_ref = saved_ref
    else:
        processed_text = orthographic_preprocess(dump_text)
        saved_ref = _save_transcript(processed_text, original_url)
        if saved_ref:
            source_ref = saved_ref

    saved_stems = _synthesize_and_save_concepts(processed_text, url_content, source_ref)

    if saved_stems:
        _mark_dump_processed(dump_text, saved_stems)
        log("dump", f"Completed: {len(saved_stems)} concepts created")
        _logger.info(f"Brain Dump: {len(saved_stems)} concepts created")
