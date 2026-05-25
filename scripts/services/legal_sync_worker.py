"""VvC Second Brain — Legal Sync Worker (v7.0).

Simulates CCBA's legal document tracker by pulling legal updates
and saving them as concept notes in the permanent vault.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from core.config import cfg
from core.log import log
from core.llm import call_llm
from services.diagram_base import spawn_worker

_logger = logging.getLogger("vvc.legal_sync")

_LEGAL_PROMPT = """You are a Legal Assistant tracking Vietnamese Construction Law.
Based on the following `legal_registry.yaml` from CCBA's tracking system, identify the most recently updated, drafted, or pending document (check the "monitoring" or "decrees" section).
Generate a Concept Note summarizing this update.

REGISTRY DATA:
{registry_data}

<rules>
1. Tuân thủ CHÍNH XÁC cấu trúc trong <output_template>. KHÔNG thêm heading khác.
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`.
3. Quy tắc ngôn ngữ:
   - **Evidence Hook**: BẮT BUỘC bằng tiếng Việt.
   - **Citation Line**: Ngay dưới Evidence Hook, ghi rõ nguồn pháp lý chính thức.
   - **`## Core Idea`**: Phân tích thuần tiếng Việt.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: Ghi `(không có)` vì nguồn pháp lý Việt Nam.
</rules>

<output_template>
---
title: "Nghị định/Thông tư mới về [Chủ đề]"
aliases: ["Update Pháp lý Xây dựng"]
tags:
  - knowledge
  - domain/legal
  - type/concept
type: concept
date_created: {date}
date_modified: {date}
source: "Web Crawler"
source_page: ""
source_chapter: ""
ground_truth_page: ""
ground_truth_chapter: ""
source_type: text
summary: "Tóm tắt 2-3 câu về nghị định."
people: []
companies: []
status: seed
confidence: high
---

> "Tóm tắt 2-3 câu ngắn gọn dịch sát nghĩa từ nội dung pháp lý — Evidence Hook."
> — **Cơ quan ban hành**, trích dẫn trong *Tên Văn bản Pháp lý* (Số hiệu, Năm)

## Core Idea

[Phân tích chi tiết các điểm mới và tác động tới ngành tư vấn xây dựng. Trình bày rõ ràng theo bullet points.]

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

(không có)

---

## References

- Nguồn: Web Crawler ({date})
</output_template>
"""

def trigger_legal_sync() -> None:
    """Trigger background legal sync."""
    spawn_worker(
        target=_generate_legal_sync,
        args=(),
        name="legal-sync",
    )

def _generate_legal_sync() -> None:
    """Worker function: fetch and save legal updates."""
    _logger.info("Generating Legal Update Concept")
    log("lifecycle", "Legal Sync started")

    try:
        registry_path = Path(r"D:\GitHubProjects\ccba-agent-platform\.agent\.agent\skills\legal-document-tracker\registry\legal_registry.yaml")
        registry_data = "No registry data found."
        if registry_path.exists():
            registry_data = registry_path.read_text(encoding="utf-8")
            
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = _LEGAL_PROMPT.format(date=today, registry_data=registry_data)
        
        note_content = call_llm(
            prompt,
            task="synthesis",
        )
        
        if not note_content:
            log("error", "Legal Sync generation failed")
            return
            
        note_content = note_content.strip()
        if note_content.startswith("```markdown"):
            note_content = note_content[11:]
            if note_content.endswith("```"):
                note_content = note_content[:-3]
        note_content = note_content.strip()
        
        # Save to 04 - Permanent/concepts
        filename = f"legal_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        output_dir = cfg.vault_root / "04 - Permanent" / "concepts"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / filename
        output_path.write_text(note_content, encoding="utf-8")
            
        _logger.info(f"Legal Update saved: {filename}")
        log("lifecycle", f"Legal Sync completed: {filename}")
        
    except Exception as e:
        _logger.error(f"Legal Sync failed: {e}")
        log("error", f"Legal Sync failed: {e}")

if __name__ == "__main__":
    # Allow running as a standalone cronjob
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    _generate_legal_sync()
