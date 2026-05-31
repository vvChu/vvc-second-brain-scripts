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


# --- URL Deduplication Registry (v8.9) ---

_URL_REGISTRY_FILE = Path(__file__).parent.parent / ".processed_urls.json"
_OVERRIDE_KEYWORDS = [
    "xử lý lại", "tải lại", "nạp lại", "chạy lại", "cập nhật",
    "reprocess", "/force", "force", "override"
]

def _load_url_registry() -> dict:
    """Tải registry lưu trữ lịch sử xử lý URL."""
    try:
        if _URL_REGISTRY_FILE.exists():
            return json.loads(_URL_REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning(f"Không thể đọc registry URL: {e}")
    return {}

def _save_url_registry(registry: dict) -> None:
    """Ghi registry lưu trữ lịch sử xử lý URL."""
    try:
        _URL_REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _logger.warning(f"Không thể ghi registry URL: {e}")

def _normalize_url(url: str) -> str:
    """Chuẩn hóa URL để đối chiếu trùng lặp chính xác nhất."""
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        
        # Đặc cách Youtube: giữ lại query v để phân biệt video
        query = ""
        if "youtube.com" in host or "youtu.be" in host:
            qs = parse_qs(parsed.query)
            if 'v' in qs:
                query = f"?v={qs['v'][0]}"
                
        return f"{host}{path}{query}"
    except Exception:
        return url.strip().lower()

def _check_override(line: str) -> bool:
    """Kiểm tra xem dòng chứa URL có từ khóa ghi đè hay không."""
    line_lower = line.lower()
    return any(kw in line_lower for kw in _OVERRIDE_KEYWORDS)


def _commit_inbox_changes(dump_text_to_replace: str, new_inbox_content: str, links_to_append: list[str]) -> None:
    """Ghi tất cả thay đổi đối với Brain_Dump.md trong một giao dịch duy nhất (Single-Write Commit)."""
    try:
        current_content = cfg.dump_file.read_text(encoding="utf-8")
    except OSError:
        return
        
    before, inbox, after = _extract_inbox_sections(current_content)
    if before and inbox:
        # Nâng cấp v8.9: So khớp line-by-line linh hoạt chống lệch khoảng trắng và CRLF (\r\n) trên Windows
        replace_lines = {line.strip() for line in dump_text_to_replace.splitlines() if line.strip()}
        inbox_lines = inbox.splitlines()
        
        remaining_lines = []
        for line in inbox_lines:
            if line.strip() in replace_lines:
                continue
            remaining_lines.append(line)
            
        if new_inbox_content.strip():
            remaining_lines.append(new_inbox_content.strip())
            
        new_inbox = "\n".join(remaining_lines).strip()
        if new_inbox:
            new_inbox = "\n" + new_inbox + "\n"
        else:
            new_inbox = "\n\n"
            
        links_str = "\n".join(links_to_append)
        if not after.startswith("\n"):
            after = "\n" + after
        if "## Processed" in after:
            if not after.endswith("\n"):
                after += "\n"
            after = re.sub(r"(##\s*Processed\s*\n)", f"\\1{links_str}\n", after, count=1, flags=re.IGNORECASE)
        else:
            after += f"\n## Processed\n{links_str}\n"
            
        new_content = before + new_inbox + after
        try:
            cfg.dump_file.write_text(new_content, encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Không thể ghi Brain_Dump.md: {e}")
            
    if _rebuild_all is not None:
        try:
            _rebuild_all()
        except Exception:
            pass

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
6. Nếu phần <source_material> chứa mục `## 🖼️ Hình ảnh bài viết (Đã tải cục bộ)` hoặc `## 🎬 Hình ảnh trực quan từ video (Đã tải cục bộ)` với danh sách `[IMG:filename|alt=description]`:
   - Xem xét alt text hoặc tên file để xác định ảnh nào **thực sự liên quan** đến concept "{concept_title}" đang viết.
   - Nhúng ảnh liên quan vào **`## Core Idea`** bằng cú pháp Obsidian `![[filename]]` tại vị trí phù hợp trong bài phân tích.
   - CHỈ nhúng **tối đa 3 ảnh** cho mỗi concept. Chỉ chọn ảnh thực sự minh họa cho nội dung Core Idea.
   - KHÔNG nhúng ảnh vào Evidence Hook, Ground Truth, hay References section.
   - Nếu không có ảnh nào liên quan đến concept này, KHÔNG nhúng ảnh nào cả.
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


def _process_urls(dump_text: str, urls_to_scrape: list[str] | None = None, visual_urls: set[str] | None = None) -> str:
    urls = _URL_PATTERN.findall(dump_text)
    if not urls:
        return ""
    fetched = []
    # Lọc các URL nếu được yêu cầu
    target_urls = [u for u in urls if urls_to_scrape is None or u in urls_to_scrape]
    for url in target_urls[:5]:
        is_visual = visual_urls is not None and url in visual_urls
        text = fetch_url(url, visual=is_visual)
        if text:
            fetched.append(f"[{url}]\n{text}")
    return "\n\n".join(fetched)


def _weave_images_into_transcript(transcript_text: str, img_markers_text: str) -> str:
    """Weaves high-res frames into their exact chronological transcript positions.
    
    Inserts Obsidian image tags and block anchors right above the matching transcript segment.
    """
    if not img_markers_text:
        return transcript_text
        
    # 1. Trích xuất tất cả các ảnh [IMG:filename|alt=...]
    img_matches = re.findall(r"\[IMG:([^\]|]+)(?:\|alt=([^\]]*))?\]", img_markers_text)
    if not img_matches:
        return transcript_text
        
    # Phân tích và nhóm ảnh theo timestamp
    images = []
    for filename, alt in img_matches:
        filename = filename.strip()
        alt = alt.strip() if alt else "Video frame - diagram/slide"
        # Tìm ts<seconds> trong tên file
        ts_match = re.search(r"_ts(\d+)", filename)
        if ts_match:
            seconds = int(ts_match.group(1))
            images.append({
                "filename": filename,
                "alt": alt,
                "seconds": seconds
            })
            
    if not images:
        return transcript_text
        
    # Sắp xếp ảnh theo thứ tự thời gian tăng dần
    images.sort(key=lambda x: x["seconds"])
    
    # 2. Tìm tất cả các phân đoạn thời gian [MM:SS] hoặc khoảng thời gian [MM:SS - MM:SS] trong transcript
    segment_pattern = re.compile(r"\[(\d+):(\d+)(?:\s*-\s*\d+:\d+)?\]")
    segments = []
    
    for match in segment_pattern.finditer(transcript_text):
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        total_seconds = minutes * 60 + seconds
        segments.append({
            "start_char": match.start(),
            "end_char": match.end(),
            "seconds": total_seconds,
            "time_str": f"[{minutes:02d}:{seconds:02d}]"
        })
        
    if not segments:
        # Fallback: Nếu không có mốc thời gian, tạo catalog ở cuối
        gallery = "\n\n## 🖼️ Danh sách Slide HD\n"
        for img in images:
            gallery += f"\n### Slide tại {img['seconds']}s ^ts{img['seconds']}\n![[{img['filename']}]]\n"
        return transcript_text + gallery
        
    # 3. Dệt ảnh vào transcript
    # Duyệt ngược từ dưới lên trên để không làm lệch chỉ số start_char / end_char
    images.sort(key=lambda x: x["seconds"], reverse=True)
    
    modified_text = transcript_text
    
    for img in images:
        target_sec = img["seconds"]
        # Tìm phân đoạn có seconds <= target_sec và sát nhất
        best_seg = None
        for seg in segments:
            if seg["seconds"] <= target_sec:
                if best_seg is None or seg["seconds"] > best_seg["seconds"]:
                    best_seg = seg
                    
        if best_seg is None:
            best_seg = segments[0]
            
        m = int(target_sec // 60)
        s = int(target_sec % 60)
        insert_text = (
            f"\n\n> [!abstract]- 🖼️ Slide tại {m:02d}:{s:02d} ^ts{target_sec}\n"
            f"> ![[{img['filename']}]]\n\n"
        )
        
        # Tìm vị trí xuống dòng gần nhất phía trước start_char của phân đoạn được chọn
        pos = best_seg["start_char"]
        newline_pos = modified_text.rfind("\n", 0, pos)
        if newline_pos != -1:
            insert_pos = newline_pos + 1
        else:
            insert_pos = 0
            
        # Nếu giữa insert_pos và pos chứa một tiêu đề markdown (#+), dời insert_pos xuống ngay sau tiêu đề đó
        sub_segment = modified_text[insert_pos:pos]
        header_match = re.search(r"^(#+\s+[^\n]+)", sub_segment, re.MULTILINE)
        if header_match:
            insert_pos = insert_pos + header_match.end()
            if insert_pos < len(modified_text) and modified_text[insert_pos] == "\n":
                insert_pos += 1
            
        modified_text = modified_text[:insert_pos] + insert_text + modified_text[insert_pos:]
        
    # 4. Xóa bỏ hoàn toàn các tag mốc thời gian [MM:SS] hoặc khoảng thời gian [MM:SS - MM:SS] thô để văn bản tự nhiên tuyệt đối!
    modified_text = re.sub(r"\s*\[\d+:\d+(?:\s*-\s*\d+:\d+)?\]", "", modified_text)
    
    return modified_text


# --- Noise patterns for link filtering ---
_NOISE_LINK_PATTERNS = [
    r"intent/tweet", r"intent/compose", r"intent/follow",  # Social share intents
    r"bsky\.app/intent", r"linkedin\.com/share",           # More social share
    r"\.(png|jpg|jpeg|gif|webp|svg|ico|css|js|woff|pdf)$",  # Assets
    r"^mailto:", r"^tel:", r"javascript:",                   # Non-HTTP
    r"#",                                                    # Fragment-only anchors
]
_NOISE_LINK_RE = re.compile("|".join(_NOISE_LINK_PATTERNS), re.IGNORECASE)

# Content domains worth reading (articles, docs, blogs, repos with READMEs)
_CONTENT_DOMAIN_PATTERNS = re.compile(
    r"(github\.com/[^/]+/[^/]+$"             # GitHub repo root only (not file paths)
    r"|youtube\.com/watch|youtu\.be/"         # YouTube videos
    r"|substack\.com|medium\.com"             # Blog platforms
    r"|dev\.to|hashnode|hbl\.io"              # Dev blogs
    r"|npmjs\.com|pypi\.org"                  # Package registries
    r"|docs\.|documentation\."
    r")",
    re.IGNORECASE
)


def _extract_related_links(original_url: str) -> list[str]:
    """Extract and filter meaningful out-links from an article page.

    Returns a deduplicated list of up to 10 clean, readable URLs
    excluding noise (social share intents, assets, fragment anchors).
    Only called for non-YouTube article URLs.

    Args:
        original_url: The URL of the article already fetched.

    Returns:
        List of filtered URLs (strings), at most 10 items.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse, urljoin
    except ImportError:
        return []

    try:
        resp = requests.get(
            original_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        _logger.warning(f"[SourceEnrich] Failed to fetch HTML for link extraction: {e}")
        return []

    source_host = urlparse(original_url).hostname or ""
    seen: set[str] = set()
    result: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        # Resolve relative URLs
        href = urljoin(original_url, href)

        # Skip noise patterns
        if _NOISE_LINK_RE.search(href):
            continue
        if not href.startswith("http"):
            continue

        # Deduplicate
        norm = href.rstrip("/")
        if norm in seen or norm == original_url.rstrip("/"):
            continue
        seen.add(norm)

        parsed = urlparse(href)
        link_host = parsed.hostname or ""
        path = parsed.path

        # Skip GitHub sub-paths (tree/blob/commit...) — only keep repo roots
        if "github.com" in link_host:
            parts = [p for p in path.strip("/").split("/") if p]
            # Keep only repo root (owner/repo) — skip tree/blob/etc.
            if len(parts) >= 3:
                continue

        # Accept: same domain OR content domains
        same_domain = source_host and link_host.endswith(source_host.lstrip("www."))
        is_content = bool(_CONTENT_DOMAIN_PATTERNS.search(href))

        if same_domain or is_content:
            result.append(href)
            if len(result) >= 10:
                break

    _logger.info(f"[SourceEnrich] Extracted {len(result)} related link(s) from {original_url}")
    return result


def _save_transcript(text: str, original_url: str = "") -> str:
    """Save processed transcript to 04 - Permanent/sources/transcripts. Returns file stem."""
    if not text or len(text.strip()) < 50:
        return ""
        
    # --- Dệt hình ảnh slide HD vào transcript ---
    img_marker = "## 🎬 Hình ảnh trực quan từ video"
    img_section = ""
    transcript_text = text
    
    if img_marker in text:
        parts = text.split(img_marker, 1)
        transcript_text = parts[0].strip()
        img_section = img_marker + parts[1]
        
    if img_section:
        transcript_text = _weave_images_into_transcript(transcript_text, img_section)
        transcript_text = f"{transcript_text}\n\n{img_section}"
        
    text = transcript_text
        
    transcripts_dir = cfg.sources_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp_date = date.today().isoformat()
    title = ""
    if original_url:
        title = fetch_url_title(original_url)
        
    slug = ""
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
    
    # --- Dedup: reuse existing transcript with same slug (different date) ---
    if slug:
        existing = list(transcripts_dir.glob(f"*_{slug}.md"))
        existing = [f for f in existing if f.name != filename]
        if existing:
            filepath = existing[0]  # Reuse oldest file path
            filename = filepath.name
            _logger.info(f"Overwriting existing transcript: {filename}")
    
    # Preserve original date_created if overwriting
    date_created = date.today().isoformat()
    if filepath.exists():
        try:
            from core.frontmatter import parse_frontmatter
            old_fm, _ = parse_frontmatter(filepath.read_text(encoding="utf-8"))
            date_created = old_fm.get("date_created", date_created)
        except Exception:
            pass
    
    fm = (
        f"---\n"
        f"title: \"{display_title}\"\n"
        f"aliases:\n  - \"{filename[:-3]}_Source\"\n"
        f"tags:\n  - knowledge\n  - type/source\n"
        f"type: source\n"
        f"date_created: {date_created}\n"
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
        is_youtube = "youtube.com" in original_url or "youtu.be" in original_url

        # Option B: Source Note Enrichment — extract related links (articles only)
        related_links_md = ""
        if not is_youtube:
            related = _extract_related_links(original_url)
            if related:
                links_block = "\n".join(f"- [{u}]({u})" for u in related)
                related_links_md = f"\n\n## 🔗 Related Links\n\n{links_block}\n"

        body = (
            f"> [!info] 🌐 Nguồn thu thập (Brain Dump)\n"
            f"> **Link gốc:** [{original_url}]({original_url})\n"
            f"> **Thời gian:** {dt.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
            f"## 📝 Nội dung thô (Transcript / Text Extracted)\n\n{text}{related_links_md}\n"
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

def _enrich_concept_references(concept_text: str, source_ref: str) -> str:
    """Enriches the ## References section with precise chronological anchor-links.
    
    Finds all embedded frame images, parses their timestamps, and appends deep-links.
    """
    if not source_ref or source_ref == "brain_dump":
        return concept_text
        
    # 1. Tìm tất cả các ảnh dạng ![[yt_..._ts(\d+).webp]]
    img_matches = re.findall(r"!\[\[yt_[^\]]+_ts(\d+)\.webp\]\]", concept_text)
    if not img_matches:
        return concept_text
        
    # Loại bỏ trùng lặp và sắp xếp timestamp tăng dần
    timestamps = sorted(list(set(int(ts) for ts in img_matches)))
    
    # 2. Xây dựng danh sách liên kết neo
    links = []
    for ts in timestamps:
        m = int(ts // 60)
        s = int(ts % 60)
        links.append(f"  - [[{source_ref}#^ts{ts}|Xem slide và ngữ cảnh chi tiết tại [{m:02d}:{s:02d}] trong ghi chép gốc]]")
        
    if not links:
        return concept_text
        
    # 3. Tìm và làm giàu mục ## References
    # Định dạng tham chiếu gốc thường là: - [[source_ref]] hoặc - [[source_ref|alias]]
    target_pattern = rf"-\s*\[\[{re.escape(source_ref)}(?:\|[^\]]*)?\]\]"
    match = re.search(target_pattern, concept_text)
    
    if match:
        original_ref = match.group(0)
        enriched_ref = original_ref + "\n" + "\n".join(links)
        concept_text = concept_text.replace(original_ref, enriched_ref, 1)
        
    return concept_text


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
        
        # Tự động làm giàu các tham chiếu neo block từ ảnh được nhúng JIT
        concept_clean = _enrich_concept_references(concept_clean, source_ref)
        
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
            for kw in _OVERRIDE_KEYWORDS:
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
