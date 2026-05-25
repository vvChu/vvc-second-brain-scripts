# 🧠 VvC Second Brain — Project Context

> [!NOTE] Role of This File
> This is the **Project Context** file for interactive AI sessions (Gemini CLI, Antigravity, etc.).
> - **Source of truth**: `AGENTS.md` (vault root) — always defer there for full schema, rules, and behavior.
> - **This file**: Quick reference + changelog + architecture pointers. Do NOT redefine rules here.
> - **Overridden by**: `scripts/GEMINI.md` when working inside the `scripts/` directory (Pipeline Mode).

This workspace is a **personal knowledge management system** ("Second Brain") built on Obsidian and powered by an autonomous ingestion pipeline following the **LLM Compiler Pattern** (Andrej Karpathy, 2026).

## 🚀 Project Overview

The system acts as a "Zero-Touch" LLM OS. It automatically ingests, processes, and synthesizes raw sources (books, handwritten notes, images) into a structured, interlinked Zettelkasten.

- **Philosophy**: AI agents act as the **librarians and compilers**, while the human is the **source provider**.
- **Core Pattern**: Raw text/images/urls → OCR/Extraction/Correction → Hybrid RAG Ground Truth Alignment → Atomic Concept Synthesis & Metadata Injection.
- **v8.6 3-Tier Merge Control & God Note Prevention (v8.6)**: Thay thế Hard Limit tĩnh 10KB bằng hệ thống kiểm soát hợp nhất đa tầng dựa trên phân tích thống kê vault-wide 1,450 concepts. **Tier 1 — Hook Count Gate**: Chặn merge khi note hiện có đã tích lũy ≥4 Evidence Hooks (giải quyết nguyên nhân gốc: quote stacking vô hạn). **Tier 2 — Dynamic Size Limit**: Ngưỡng P95 × 1.3 (~7.7KB) thay vì 10KB tĩnh, chặn sớm hơn 23% và bắt thêm 11 notes vùng xám 8-10KB. **Tier 3 — LLM Arbitrator**: Giữ nguyên bias SEPARATE (62.1% SEPARATE trong lịch sử). Nâng Cosine threshold từ 0.85 lên 0.88. Tầng 1-2 chạy O(1) tiết kiệm API calls cho notes đã phì đại. Bổ sung script `consolidate_god_notes.py` để xử lý retroactive 9 God Notes >10KB hiện có trong vault.
- **v8.5 Sleep Consolidation Optimizations, AI Gateway Embeddings & Semantic Knowledge Merger (v8.5)**: Cấu trúc lại toàn bộ tiến trình củng cố hàng tuần `sleep.py` sang mô hình Quét Một Lần (Scan-Once Architecture), tiết kiệm ~42 giây IO. Tích hợp trực tiếp `DomainEnricher` để tự động hóa gán nhãn lĩnh vực thông qua AI Gateway. Triệt tiêu double-lint bằng cách truyền trực tiếp `report` từ `lint_vault()` sang `heal_broken_links()`. Refactor hoàn toàn `update_embeddings.py` chuyển sang sử dụng mô hình nhúng `gemini-embed` qua AI Gateway (LiteLLM Server Spark), giải quyết triệt để lỗi rate limit 429 và tăng tốc độ đồng bộ hóa vector store gấp 7.5 lần nhờ tối ưu throttle delay từ 1.5s xuống 0.2s. Tích hợp **Semantic Knowledge Merger** (tính toán Cosine similarity threshold 0.85 chủ động, LLM Semantic Arbitrator, tự động liên kết chéo hai chiều (cross-linking) khi giữ tách rời, và **Academic Merge Synthesis** xếp chồng Evidence Hooks/Citation Lines song ngữ v8.3, viết lại `## Core Idea` tích lũy đa nguồn). Tích hợp **Proportional Dynamic Limit** tự động co giãn giới hạn trích xuất động trong Brain Dump Map-Reduce dựa trên độ dài văn bản thô (ký tự) từ `1-3` (dưới 5k) lên tới `8-18` concepts (trên 50k).
- **v8.4 Ingestion Pipeline & UTF-8 Stdout Hardening (v8.4)**: Tinh chỉnh daemon nới lỏng Watchdog prefix hỗ trợ ảnh mục lục thô đơn lẻ (`_toc.jpg`, `_cover.jpg`). Đồng bộ hóa so khớp chương robust với kiểu dữ liệu `null`/`None` cho `page_start`/`page_end` trong `_toc.json` tránh lỗi `TypeError`. Chuẩn hóa 188 Concept Notes có tiêu đề thô thành Việt hóa chuẩn học thuật qua AI Gateway hàng loạt. Bổ sung quy định Windows Stdout UTF-8 (`sys.stdout.reconfigure(encoding='utf-8')`) cho các script in dữ liệu Unicode.
- **v8.3 Bilingual Standard & Secondary Citation (Concept Note Format v8.3)**: Chuẩn hóa quy tắc ngôn ngữ song ngữ nghiêm ngặt: Evidence Hook **BẮT BUỘC tiếng Việt** (dịch sát nghĩa nếu nguồn thô là tiếng Anh), Ground Truth **BẮT BUỘC tiếng Anh nguyên bản**. Bổ sung **Citation Line** (dòng trích dẫn học thuật gián tiếp kèm wiki-link Obsidian trỏ về file nguồn thô) ngay dưới Evidence Hook để ghi rõ chủ thể phát biểu chính thức. Cập nhật đồng bộ: `AGENTS.md` Section 4.1, `templates/concept.md`, `synthesize.py` prompt + output template, `brain_dump.py` prompt + output template.
- **v8.0 Canonical `_toc.json` Schema**: Chuẩn hóa cấu trúc `_toc.json` dầy đủ 7/7 sách. Hợp nhất xung đột naming (`book_title_en` → `book_title_original`), loại bỏ orphan fields (`title_en`, `epub_page_start/end`), enforce `.md` extension cho `epub_file`, và chuẩn hóa type (`page_start`/`page_end` luôn là `int | null`). Cập nhật 4 producers (`epub_convert.py`, `pdf_convert.py`, `ocr.py`, `heal_existing_tocs.py`) + test fixtures. Xem `AGENTS.md` Section 3.1 cho full canonical schema.
- **v7.7 Concept Note Format (Cognitive Flow Optimized)**: Chuẩn hóa cấu trúc body concept note thành 6 bước canonical dứt khoát: Evidence Hook (blockquote tiếng Việt đứng độc lập) → Citation Line (trích dẫn học thuật gián tiếp) → `## Core Idea` (phân tích thuần, không lồng quote) → `## 📖 Ground Truth` (căn cứ tiếng Anh) → `---` (visual separator) → `## References` (chỉ 1-2 wiki-link). Triệt tiêu trùng lặp thông tin nguồn (trước đây xuất hiện 3-4 lần). Cập nhật `synthesize.py` prompt + `_fix_section_ordering()` + `templates/concept.md`.
- **v7.6 Dual-Source Frontmatter**: YAML frontmatter hỗ trợ song song tham chiếu sách tiếng Việt (`source_page`, `source_chapter`) và Ground Truth tiếng Anh (`ground_truth_page`, `ground_truth_chapter`). Bổ sung thêm `people: []`, `companies: []`, `status: seed|growing|evergreen` cho Dataview queries và Metadata Menu.
- **v7.5 Architecture Hardening (3 Systemic Fixes)**: 
  1. **Reverse Metadata Sync**: `ocr.py` now triggers `_sync_source_note()` after `_toc.json` is created — automatically updates the Source Note's YAML title and injects a `## 📚 Mục lục` chapter table.
  2. **File Stability Guard**: `daemon.py` replaces `time.sleep(1)` with `_is_file_stable()` — size-comparison guard (1.5s) prevents processing partially-synced cloud junction files.
  3. **Temporal Batching Engine**: `daemon.py` buffers images per workspace; `_flush_batches()` thread flushes after 10s idle — N images → 1 batch OCR → 1 Concept Note (no multi-page fragmentation).
- **v7.4.2 Brain Dump Map-Reduce**: Upgraded `brain_dump.py` to a 2-step Map-Reduce process (Extraction via `reasoning` task -> Synthesis via `synthesis` task) to eliminate token exhaustion and ensure 100% strict formatting of `## Core Idea` for long audio/video ingestions. It employs a **Dynamic Limit (3-12 concepts)** based on text density rather than a hard limit to preserve information.
- **v7.4 Modular Architecture**: Refactored God Objects (`brain_dump.py`, `command.py`, `core/llm.py`) into specialized micro-modules (`url_fetcher`, `text_chunker`, `llm/gateway_client.py`, etc.) adhering to Single Responsibility Principle.
- **v7.2.1 Diagram Typesetting Engine & Clean MOC Architecture**: 
  - **Academic Layouts & Grayscale Theme**: Replaced organic layout hallucinations with 4 deterministic engines (Sugiyama, Radial, Cycle, Matrix), managed by a Topology Router and an enforced 100% Academic Grayscale Theme.
  - **Excalidraw Text Auto-Sync**: Resolved "text lumping" bugs by dynamically extracting and populating text elements with block IDs (`^id_txt`) into the markdown `# Text Elements` section for both system workers and manual scripts.
  - **Zero-Concept MOC Filtering**: Upgraded `wiki_maintain.py` to skip generation of MOC pages for sources with 0 linked concepts, allowing the self-healing routine to automatically purge clutter and keep the Maps of Content pristine.

## 🛠️ Tech Stack & Architecture

- **Frontend**: [Obsidian](https://obsidian.md/) (for human interaction and visualization).
- **Backend**: Python-based autonomous daemons (`scripts/daemon.py`).
- **AI Infrastructure**: 3-Tier LLM routing (see below).
- **Automation**: `watchdog` based pipeline for real-time ingestion.

### 3-Tier LLM Architecture (v7.4 Modular)

```
Tier 1 (Primary):  AI Gateway (ccba-ai SDK)  ← 22 models via LiteLLM
Tier 2 (Fallback): Copilot CLI               ← claude-sonnet-4.6 (default)
Tier 3 (Direct):   Gemini REST API            ← gemini-3-flash-preview
```

### Context File Hierarchy

```
~/.gemini/GEMINI.md           ← Global defaults (all projects)
D:\VvC_Notes\GEMINI.md        ← THIS FILE — project-level context
D:\VvC_Notes\AGENTS.md        ← Agent Constitution (dual-mode rules)
D:\VvC_Notes\scripts\GEMINI.md ← JIT context: daemon text-processing mode
```

## 📁 Directory Structure

| Path | Purpose |
|---|---|
| `00 - Maps of Content/` | 🗺️ Navigation hub, indexes, and MOC pages. |
| `03 - Resources/books/` | 📥 Input folder for new books (EPUB/PDF). |
| `03 - Resources/attachments/` | 🖼️ Output folder for Excalidraw & Mermaid diagrams. |
| `04 - Permanent/` | 🧠 The compiled knowledge layer (Concepts & Sources). |
| `05 - Fleeting/` | 📸 Active workspace for image + text ingestion. |
| `99 - Archive/` | 🗄️ Processed raw materials. |
| `scripts/` | ⚙️ Python automation pipeline and core logic. |
| `templates/` | 📝 Obsidian templates for different note types. |

## ⚙️ Key Commands

To run the autonomous pipeline, use the following commands from the project root:

| Task | Command |
|---|---|
| **Main Ingestion Pipeline** | `pythonw scripts/daemon.py` |
| **Google Drive Sync (PC ↔ Phone)** | `Transparent via Windows Directory Junctions` |
| **Book Ingestion Watcher** | `pythonw scripts/book_ingest.py` |
| **Web Clipper (CLI)** | `python scripts/web_clip.py "https://url"` |
| **Wiki Maintenance (Manual)**| `python scripts/wiki_maintain.py` |
| **Weekly Synthesis & Heal** | `python scripts/sleep.py` |
| **EPUB Converter** | `python scripts/epub_convert.py <epub_path>` |

*Note: Use `.venv\Scripts\activate` before running scripts. Use `pythonw` for headless daemon execution. `run_watcher.vbs` launches daemon.py + book_ingest.py automatically via Task Scheduler. PC-to-Mobile sync is now handled transparently by Google Drive Desktop via `mklink /J` directory junctions (isolating the `.venv` and `scripts` locally).*

### Command.md Writing Styles

Use `/prefix` to select a writing style. Default is `professional` (scientific, structured).

| Style | Syntax | Description |
|---|---|---|
| **professional** | `@AI: query ---` | Khoa học, chuyên nghiệp, business-ready |
| tim-urban | `@AI: /tim-urban query ---` | Hài hước, analogies, snarky |
| academic | `@AI: /academic query ---` | Formal, evidence-based |
| bullet | `@AI: /bullet query ---` | Ngắn gọn, scannable |
| socratic | `@AI: /socratic query ---` | Dẫn dắt suy nghĩ |
| storyteller | `@AI: /storyteller query ---` | Narrative, kể chuyện |
| eli5 | `@AI: /eli5 query ---` | Explain Like I'm 5 |
| debate | `@AI: /debate query ---` | Multi-perspective |

## 🤖 Agent Conventions & Rules

**Crucial: All AI agents MUST adhere to `AGENTS.md` (The Constitution).**

### Dual Operating Modes

1. **🟢 Interactive Mode** — Human is present. Full assistant behavior, tool use, explanations.
2. **🔵 Pipeline Mode** — Daemon automation. Text-processing-only, zero-tool, single-shot.

See `AGENTS.md` Section 1.1 for full mode definitions.

### File Access Rules
- **READ-ONLY**: `03 - Resources/`, `99 - Archive/`, `AGENTS.md`.
- **WRITE/UPDATE**: `04 - Permanent/`, `00 - Maps of Content/`, `05 - Fleeting/`.

### Note Schema (YAML Frontmatter v7.7)
> 📖 **Full schema defined in `AGENTS.md` Section 3** — this is the authoritative source.

New fields added in v7.6–7.7 (not in older notes):
- `source_page`, `source_chapter` — tham chiếu sách tiếng Việt
- `ground_truth_page`, `ground_truth_chapter` — tham chiếu sách gốc tiếng Anh
- `people: []`, `companies: []` — thực thể (Dataview/Metadata Menu)
- `status: seed | growing | evergreen` — trạng thái tri thức

**Tags rule**: chỉ `knowledge`, `type/concept`, `domain/*` — KHÔNG thêm tên người/công ty vào tags.

### TOC Schema (`_toc.json` v8.0)
> 📖 **Full schema defined in `AGENTS.md` Section 3.1** — canonical reference.

Key rules:
- `chapter_num` = sequential index (NOT book chapter number)
- `epub_file` MUST end with `.md`
- `page_start`/`page_end` = `int | null` (never strings)
- English-only books: copy `title_original` → `title_vi`

### Naming Conventions
- **Concept Notes**: `snake_case_name.md` (e.g., `transformer_architecture.md`).
- **Source Notes**: `YYYY-MM-DD_Book_Title_Author.md`.
- **Source MOCs**: `MOC_Title_Cased.md`.
- **Domain MOCs**: `Domain_Title_Cased.md` (auto-created when ≥8 concepts share a `domain/` tag).

### Code Quality (Scripts)
- Use **Type Hints** for all Python parameters and returns.
- Prefer **composition over inheritance**.
- Public functions must have **Google-style docstrings**.
- Use `scripts/core/llm.py` for all LLM calls (`call_llm()` + `call_vision()`).
- **Shutdown signals**: use `threading.Event` (not global bool) in all daemon `main()` loops.
- **Hot-path imports**: all heavy imports (rank_bm25, watchdog, service modules) at top-level with `try/except` fallback — never inside loops.
- **State tracking**: use `@dataclass` (e.g., `_PollerState` in `daemon.py`).
- **PowerShell stdout fix**: khi script có thể chạy tay từ terminal, `logging.basicConfig()` PHẢI có `stream=sys.stdout`. Nếu thiếu, Python ghi log vào stderr và PowerShell tự động return exit code 1 dù không có lỗi thực sự. Đồng thời, nếu script in ký tự Unicode (tiếng Việt có dấu) ra terminal Windows, bắt buộc gọi `sys.stdout.reconfigure(encoding='utf-8')` ở đầu để ngăn lỗi `UnicodeEncodeError` (charmap).

### Quality Gate (`pipeline/post_process.py`)
Before any concept note is saved, `_validate_quality()` enforces 5 checks:
1. No template placeholders (e.g., `"2-4 câu của bạn ở đây"`)
2. `## Core Idea` section present
3. Core Idea blockquote ≠ copy of title
4. Body ≥ 300 chars after frontmatter
5. Filename stem doesn't end with truncation artifact (`_mh`, `_lit`…)

Failed concepts are **rejected** and logged to `log.md` — never saved to vault.

## 🔗 Configuration

- **Central config**: `scripts/config.yaml`
- **LLM Client Package**: `scripts/core/llm/` (Separated into `gateway_client`, `copilot_client`, `gemini_client`, `vision_client`, `audio_client`)
- **Frontmatter**: `scripts/core/frontmatter.py` (parse/build/normalize_stem)
- **Model Routing (v7.4 Tier-Specific)**: Models are resolved independently per tier to prevent 400 Bad Request / code 1 errors across incompatible backends.
  - OCR/Vision: `gemini-3-flash-preview` (Gemini REST API)
  - Text/Synthesis: `gemini-3.1-pro-high` (Gateway) → `claude-sonnet-4.6` (Copilot CLI fallback)
  - OCR Correction: `gemini-3.1-flash-lite` (Gateway) → `gpt-5-mini` (Copilot CLI fallback)
  - Map Step (Reasoning): `claude-opus-4-6-thinking` (Gateway) → `claude-sonnet-4.6` (Copilot CLI fallback)
  - Audio/Transcription: `audio-primary` (`faster-whisper-large-v3-turbo-ct2`) via Gateway. VAD Filter is enabled via `extra_body` to strip silences.
  - Excalidraw Diagrams: `claude-sonnet-4.6` (Copilot CLI — spatial reasoning, w/ LZString Safe Healer)
- **Round-Robin Load Balancing**: For bulk operations (like `LinkHealer`), requests are automatically rotated across Tiers 1-3 to prevent Rate Limiting, effectively providing 4x the RPM capacity.
- **Strict Abort & Auto-Unlink**: Garbage concepts rejected by the Semantic Arbitrator are cached in `.rejected_stubs.json` and permanently unlinked from source files.
- **CLI Syntax & Safety**:
  - Gemini CLI: `gemini -m <model> -p "<prompt>"` (non-interactive/headless)
  - Copilot CLI: `copilot --model <model> -p "<prompt>"` (non-interactive)
  - **WinError 206 Protection**: By invoking `CreateProcessW` directly via `node.exe` and `copilot.exe`, payloads up to **30,000 chars** safely execute natively. Only payloads > 30,000 chars bypass CLI to HTTP REST APIs, maximizing CLI throughput.
