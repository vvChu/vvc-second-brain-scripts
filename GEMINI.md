# 🧠 VvC Second Brain — Project Context (v8.15.13)

> [!NOTE] Context File Hierarchy
> | File | Role | Authority |
> |:---|:---|:---|
> | `AGENTS.md` | **Constitution** — full rules, schemas, behavior | Highest |
> | `GEMINI.md` | **This file** — quick reference & entry point | Medium |
> | `scripts/GEMINI.md` | **Pipeline Override** — daemon text-processing mode | Scoped |
> | `CHANGELOG.md` | **Version history** — changelog only | Reference |
>
> **Rule**: `AGENTS.md` is the source of truth. Do NOT redefine rules here.

## Overview

Personal knowledge management system ("Second Brain") built on Obsidian. Autonomous ingestion pipeline following the **LLM Compiler Pattern** (Karpathy, 2026).

- **Philosophy**: AI agents = **librarians & compilers**. Human = **source provider**.
- **Core Pattern**: Raw images/books/URLs → OCR → Ground Truth RAG → Atomic Concept Synthesis → Zettelkasten.
- **Current version**: v8.15.13 — See `CHANGELOG.md` for full history.

## Directory Structure

| Path | Purpose |
|---|---|
| `00 - Maps of Content/` | 🗺️ MOC pages & Master Index |
| `03 - Resources/books/` | 📥 Input: new books (EPUB/PDF) |
| `04 - Permanent/` | 🧠 Compiled knowledge (concepts, sources & topics) |
| `05 - Fleeting/` | 📸 Active ingestion workspace |
| `99 - Archive/` | 🗄️ Processed raw materials (WebP compressed) |
| `scripts/` | ⚙️ Python automation pipeline |

## Key Commands

| Task | Command |
|---|---|
| **Main Pipeline** | `pythonw scripts/daemon.py` |
| **Restart Daemon** | `python scripts/daemon.py --restart` |
| **Book Watcher** | `pythonw scripts/book_ingest.py` |
| **Web Clipper** | `python scripts/web_clip.py "https://url"` |
| **Wiki Maintenance** | `python scripts/wiki_maintain.py` |
| **Weekly Consolidation** | `python scripts/sleep.py` |
| **EPUB Converter** | `python scripts/epub_convert.py <epub_path>` |

*Use `.venv\Scripts\activate` first. Use `pythonw` for headless daemons. `run_watcher.vbs` auto-launches via Task Scheduler.*

## Quick Rules (Details in AGENTS.md)

- **File Access**: Read-only `03 - Resources/`, `99 - Archive/`, `AGENTS.md`. Write to `04 - Permanent/`, `00 - Maps of Content/`, `05 - Fleeting/`.
- **Naming**: Concepts = `snake_case.md`. Sources = `YYYY-MM-DD_Title_Author.md`. MOCs = `MOC_Title.md`.
- **YAML Schema**: See `AGENTS.md` §3. Required fields include `source_page/chapter`, `ground_truth_page/chapter`, `people`, `companies`, `status`.
- **Concept Note Format** (v8.3): Evidence Hook (VN) → Citation Line → `## Core Idea` → `## 📖 Ground Truth` (EN) → `---` → `## References`.
- **Quality Gate**: 5 pre-save checks in `post_process.py`. Failed notes are rejected, never saved.
- **Research Discipline**: Double-Pass Adversarial Review required before proposing changes. See `AGENTS.md` §7.
- **Topic Backlog**: When asked to write new articles or brainstorm topics, always refer to the existing backlog of potential ideas at [[y_tuong_bai_viet_tiem_nang|Danh Mục Các Bài Viết Tiềm Năng]].
- **Dual-Rendering Diagrams** (v8.15.6): See `AGENTS.md` §4.9. Standard Excalidraw 2.x wrapper, Auto-Expand Container ($H \ge H_{text} + 30\text{px}$), Wheel layout multi-tier disambiguation & anchor, Academic Grayscale styling, Executive Typography 16:9 ($W \le 1.150\text{px}$, font floor $\ge 8.5\text{px}-11.5\text{px}$) kèm Bảng Đặc Tả Markdown bên dưới, và Arrow-Label Clearance ($\Delta Y \ge 15\text{px}$, gap $\ge 80\text{px}-90\text{px}$).
- **Markdown Tables** (v8.15.2): See `AGENTS.md` §4.10. Mandatory pipe escaping in table wikilinks (`[[slug\|alias]]`), non-breaking arrow binding (`↳&nbsp;Text`), baseline subtitle anchors `*(...)*`, and 2-tier visual hierarchy ($\le 40$ chars/line).
- **Zero-ASCII Art Invariant** (v8.15.3): See `AGENTS.md` §4.11. Cấm tuyệt đối vẽ sơ đồ ASCII/Unicode box art trong markdown; bắt buộc dùng Mermaid/Excalidraw và native language code fences (yaml, json) cho config/code.
- **Mermaid Engineering & 4 Design Patterns** (v8.15.9): See `AGENTS.md` §4.4. Hybrid golden threshold, 5 Mermaid invariants (bất đối xứng trọng số $\Delta W \ge 2$, grayscale base theme, căn lề trái text, cạnh vô hình LTR, Flat Two-Node Invariant cấm subgraph lồng 1 node và cấm `<br/>` trong tiêu đề subgraph), cùng Bộ Tứ Mẫu Thiết Kế Mermaid (Macro Hub-and-Pods với `~~~`, Semantic Decision Tree với Badges, Multi-Tier Funnel, và Cross-Domain Subgraphs).
- **Clean Wikilinks & Deterministic Defense** (v8.15.7 / v8.15.11): See `AGENTS.md` §4.4 & §5. Cấm tuyệt đối bọc backticks quanh wikilinks/embeds (ví dụ cú pháp bắt buộc dùng fenced code block); thoát pipe `[[slug\|alias]]` trong bảng nhưng giữ link trần; đồng bộ 100% số trích dẫn trong bảng với danh mục cuối bài; Zero-Fencing Examples trong prompt SLM; và tiền xử lý regex tất định (`clean_wikilink_quotes`) trước khi ghi đĩa.
- **Stale Daemon & CLI Artifact Ingestion** (v8.15.9): See `AGENTS.md` §5. Cờ `--restart` bắt buộc khi nạp code mới; `_resolve_cli_artifact_content` tự động nuốt toàn văn artifact thay thế summary từ CLI stdout.
- **Mermaid Edge Labels & HTML Entity Context Isolation** (v8.15.10): See `AGENTS.md` §4.4 & §4.10. Cấm chèn nhãn text vào giữa thân mũi tên (dùng `===>|"label"|`, `-.->|"label"|`, `<===>|"label"|`); chuẩn hóa toán tử `≥`/`≤`; thực thể HTML `#40;` và `#41;` CHỈ dùng bên trong khối ````mermaid`; bảng biểu Markdown bắt buộc dùng dấu ngoặc đơn tròn chuẩn `()`.
- **Living Architecture & Mental Model** (v8.15.13): See `AGENTS.md` §1.1. Khảo sát 8 Trụ cột kiến trúc, 3 Đột phá Karpathy và Bất biến Active-Passive Single-Active Runner tại [`.md/vault_mental_model_and_architecture.md`](file:///home/vvc/VvC_Notes/.md/vault_mental_model_and_architecture.md), [[kien_truc_va_mental_model_vvc_second_brain|04 - Permanent/topics/kien_truc_va_mental_model_vvc_second_brain.md]] và SSoT [`.md/workspace_context.yaml`](file:///home/vvc/VvC_Notes/.md/workspace_context.yaml).
- **Architectural Budgets & Zero-Slack Ratchets** (v8.15.13): See `AGENTS.md` §5. SSoT versioning qua `core.__version__`; trần tệp sản xuất mới $\le 350$ dòng (13 legacy ratchets); trần hàm AST $\le 50$ dòng (67 legacy ratchets); đồng bộ cây thư mục README sống và 0 rò rỉ đường dẫn máy (`test_architectural_budgets.py`, `test_codebase_cleanliness.py`).
- **Session Artifact Buffer Isolation** (v8.15.13): See `AGENTS.md` §4.3. Mọi tệp tạm thời của phiên làm việc AI (plans, tasks, walkthroughs) bắt buộc lưu trong `.md/scratch/` để bảo toàn `git status clean`.
- **Test Runner & Ratchet Governance** (v8.15.13): See `AGENTS.md` §5 & `scripts/README.md`. Trên Server Spark luôn chạy kiểm thử qua `scripts/.venv/bin/pytest` để tránh xung đột wrapper `$PATH`; tối ưu giảm dòng tệp legacy bắt buộc siết ratchet đồng thời trong cùng commit.



