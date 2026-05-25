"""VvC Second Brain — Markdown Processing Stage (v7.1).

Processes long-form raw text (e.g., YouTube Transcripts, Web Clips) 
from 05 - Fleeting/ and synthesizes them into atomic Zettelkasten concepts.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import date
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from pipeline.post_process import save_concept

_logger = logging.getLogger("vvc.md_process")

_MARKDOWN_PROMPT = """Bạn là trợ lý biên soạn tri thức. Phân tích nội dung văn bản (transcript/bài viết) dưới đây và bóc tách thành các Concept Notes độc lập.

NỘI DUNG:
---
{content}
---

NHIỆM VỤ:
1. Đọc toàn bộ nội dung và xác định các KHÁI NIỆM (Concepts), MÔ HÌNH TƯ DUY (Mental Models), hoặc Ý TƯỞNG (Ideas) cốt lõi và có giá trị nhất.
2. Lọc bỏ thông tin thừa, hội thoại lan man hoặc ví dụ rườm rà.
3. Với MỖI khái niệm lớn, hãy tạo 1 Concept Note hoàn chỉnh (YAML frontmatter + body). 
4. Bắt buộc phân tách các concept notes bằng dòng chữ chính xác: ===CONCEPT_SEPARATOR===

<rules>
1. Bạn TUYỆT ĐỐI PHẢI tuân thủ chính xác cấu trúc trong <output_template>. KHÔNG THÊM BẤT KỲ HEADING NÀO KHÁC (không `# Tên khái niệm`, không `## Implications`, không `## Connections`).
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`. Việc bỏ sót sẽ làm hỏng hệ thống.
3. Quy tắc ngôn ngữ NGHIÊM NGẶT:
   - **Evidence Hook** (blockquote đầu tiên): BẮT BUỘC bằng TIẾNG VIỆT. Nếu nguồn thô là tiếng Anh, phải dịch sát nghĩa sang tiếng Việt.
   - **Citation Line**: Ngay dưới Evidence Hook, cùng khối blockquote. Ghi rõ tên tác giả, tên tác phẩm, nguồn thô.
   - **`## Core Idea`**: PHÂN TÍCH THUẦN hoàn toàn bằng tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook. Tập trung diễn giải cơ chế, hệ quả.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: BẮT BUỘC bằng TIẾNG ANH nguyên bản. Nếu nguồn hoàn toàn bằng tiếng Việt, ghi `(không có)`.
4. Mỗi concept = 1 ý tưởng atomic, đứng độc lập.
5. related: tự động suy luận 5-10 links liên quan nhất.
6. Nếu bài viết chỉ có 1 ý chính → tạo 1 concept. Nếu có nhiều ý → tạo nhiều concept (ví dụ 3-5 concepts cho video 1 tiếng).
</rules>

<output_template>
---
title: "Tên khái niệm"
aliases: []
tags:
  - knowledge
  - type/concept
  - domain/<lĩnh_vực>
type: concept
date_created: {today}
date_modified: {today}
source: "{source_name}"
source_type: text
summary: "Tóm tắt 2-3 câu"
people: []
companies: []
status: seed
related: []
confidence: medium
---

> "Trích dẫn nguyên văn BẮT BUỘC bằng tiếng Việt — Evidence Hook."
> — **Tên Tác Giả**, trích dẫn trong *Tên Tác Phẩm* ([[source_note_stem|Nguồn, Năm]])

## Core Idea

Phân tích chuyên sâu (200-400 từ) diễn giải ý tưởng này — hoàn toàn bằng tiếng Việt.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> "Original English passage from source..." (BẮT BUỘC tiếng Anh nguyên bản)

---

## References

- [[source_note_stem]]
</output_template>
"""

def process_markdown_file(file_path: Path) -> bool:
    """Read a raw markdown file, synthesize concepts, and archive the file."""
    _logger.info(f"Processing Markdown: {file_path.name}")
    log("ingest", f"Markdown Processing started: {file_path.name}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.error(f"Failed to read file {file_path}: {e}")
        return False

    if len(content.strip()) < 50:
        _logger.warning("File too short, skipping.")
        return False

    today = date.today().isoformat()
    source_name = file_path.stem.replace("_", " ").title()

    prompt = _MARKDOWN_PROMPT.format(
        content=content,
        source_name=source_name,
        source_ref=file_path.stem,
        today=today,
    )

    # Note: For large contexts, this might use gemini-3.1-pro-high if configured
    result = call_llm(prompt, task="synthesis")
    
    if not result:
        log("error", "Markdown synthesis failed", source=file_path.name)
        _logger.error("Synthesis failed for markdown file")
        return False

    # Debug: Save raw LLM output
    try:
        (Path(cfg.vault_root) / "scratch" / "raw_markdown_synth.md").write_text(result, encoding="utf-8")
    except Exception:
        pass

    concepts = result.split("===CONCEPT_SEPARATOR===")
    saved_count = 0

    for concept in concepts:
        concept = concept.strip()
        if len(concept) < 100:
            continue

        # Strip markdown fences
        concept = re.sub(r"^```(?:markdown|md)?\s*\n", "", concept)
        concept = re.sub(r"\n```\s*$", "", concept)

        if not concept.startswith("---"):
            continue

        saved_path = save_concept(concept)
        if saved_path:
            saved_count += 1

    log("synth", f"Created {saved_count} concepts from {file_path.name}")
    _logger.info(f"Created {saved_count} concepts from {file_path.name}")

    if saved_count > 0:
        _archive_file(file_path)
        # Trigger MOC rebuild
        try:
            from wiki_maintain import rebuild_all
            rebuild_all()
        except ImportError:
            pass
        return True

    return False

def _archive_file(file_path: Path) -> None:
    """Move processed file to 99 - Archive/web_clips/"""
    archive_dir = cfg.archive_dir / "web_clips"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / file_path.name
    
    try:
        if dest.exists():
            dest.unlink()
        shutil.move(str(file_path), str(dest))
        _logger.info(f"Archived {file_path.name} to {archive_dir}")
    except OSError as e:
        _logger.error(f"Failed to archive {file_path}: {e}")
