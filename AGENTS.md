# 🧠 VvC Second Brain — Agent Constitution (v8.12.5)

> This file is the "operating manual" for any AI agent working with this Obsidian vault.
> It defines the structure, rules, and behavior for the LLM OS autonomous ingestion pipeline.

> [!IMPORTANT] Context File Hierarchy — Read This First
> This vault uses **3 layered context files**. Each file has a distinct role:
>
> | File | Role | Authority |
> |:---|:---|:---|
> | `AGENTS.md` (**THIS FILE**) | **Constitution** — full authoritative rules, schemas, and behavior | Highest |
> | `GEMINI.md` (vault root) | **Project Context** — quick reference for interactive sessions, pointers to this file | Medium |
> | `scripts/GEMINI.md` | **Pipeline Override** — loaded automatically when working in `scripts/` dir, activates Pipeline Mode | Scoped |
>
> **Rule**: When in doubt, `AGENTS.md` wins. `GEMINI.md` is a summary — never redefine rules there. `scripts/GEMINI.md` only overrides *behavior*, never *schema*.

> [!WARNING] Sync Manifest — Mandatory Co-Update Checklist
> When updating **any architectural rule** in this Constitution (Concept Note format, YAML schema, pipeline stages, LLM routing, etc.), the agent **MUST** also propagate changes to ALL dependent files listed below. Failure to do so causes **documentation drift** — downstream agents will operate on stale rules.
>
> | File | What to sync | Type |
> |:---|:---|:---|
> | `GEMINI.md` (vault root) | Version number in title only (lean pointer) | Project Context |
> | `CHANGELOG.md` | New version entry (2-3 lines) | Version History |
> | `scripts/GEMINI.md` | Architecture Reference version header | Pipeline Override |
> | `scripts/README.md` | Version header + changelog line | Developer Docs |
> | `templates/concept.md` | Obsidian template body structure | User Template |
> | `scripts/pipeline/synthesize.py` | LLM prompt `<rules>` + `<output_template>` | Book Pipeline Code |
> | `scripts/services/brain_dump.py` | LLM prompt `<rules>` + `<output_template>` in `_REDUCE_PROMPT` | Brain Dump Code |
> | `scripts/pipeline/process_markdown.py` | `_MARKDOWN_PROMPT` concept format template | Markdown Pipeline Code |
> | `scripts/services/legal_sync_worker.py` | `_LEGAL_PROMPT` concept format template | Legal Sync Code |
>
> **Verification**: After propagation, run `pytest scripts/tests/` to ensure no regressions.

---

## 1. Project Overview

This vault is a **personal knowledge base** ("Second Brain") that follows the **LLM Compiler Pattern** (Andrej Karpathy, 2026). The system acts as a "Zero-Touch" LLM OS. Books and handwriting images are ingested, processed, Auto-Corrected via Ground Truth RAG, and synthesized into a structured, interlinked Zettelkasten.

**Philosophy**: You (the agent) are the **librarian and compiler**. The human is the **source provider**. Your job is to keep this wiki coherent, well-linked, and up-to-date.

---

## 1.1 Operating Modes

This vault supports **two distinct operating modes**. Identify your mode and follow the corresponding rules:

### 🟢 Interactive Mode (Default)

When a human is working with you via Gemini CLI, Antigravity, or any interactive session:
- Act as a **knowledgeable pair programmer and librarian**.
- Explain your reasoning, ask clarifying questions when needed.
- Use all available tools (file read/write, shell, search) as appropriate.
- Follow the full Constitution (sections 2–6 below).

### 🔵 Pipeline Mode (Automated Daemon)

When your prompt begins with `[PIPELINE]` or you are invoked by the daemon scripts in `scripts/`:
- You are a **text processing engine**, not an assistant.
- Output **ONLY** the requested content. No explanations, no questions, no preambles.
- **NEVER** ask for clarification — process whatever input you receive.
- **NEVER** wrap output in code fences unless explicitly requested.
- **NEVER** use tools unless the prompt explicitly instructs you to.
- Respond in the language specified by the prompt. Default: **Vietnamese**.
- Preserve all structural markers (`[HIGHLIGHTED]`, `[CONTEXT]`, YAML `---`, etc.).

> **How to detect Pipeline Mode:** The `scripts/GEMINI.md` context file is loaded
> automatically via JIT when operating within the `scripts/` directory.

---

## 2. Directory Structure

```text
D:\VvC_Notes\                       ← Vault Root (Obsidian)
├── AGENTS.md                       ← THIS FILE — do NOT modify unless explicitly asked
├── 00 - Maps of Content/           ← 🗺️ Hub pages and Master Index (`index.md`)
├── 03 - Resources/                 
│   ├── books/                      ← 📥 Human drops new books (EPUB/PDF) here
│   └── attachments/                ← 🖼️ Output folder for Excalidraw & Mermaid diagrams
├── 04 - Permanent/                 ← 🧠 Compiled knowledge layer
│   ├── concepts/                   ←    Atomic concept notes (1 idea = 1 file)
│   ├── sources/                    ←    Source summaries (1 book = 1 file)
│   └── topics/                     ←    📝 AI-generated long-form essays & analyses
├── 05 - Fleeting/                  ← 📸 Active ingestion workspace (human drops photos here)
├── 99 - Archive/                   ← 🗄️ Processed photos are archived here
├── scripts/                        ← ⚙️ Python automation daemons
└── templates/                      ← 📝 Obsidian note templates
```

### Rules
- **NEVER** modify files in `03 - Resources/` or `99 - Archive/`. Only read them.
- **NEVER** modify `AGENTS.md` unless explicitly asked by the user.
- **ONLY** write/update files in `04 - Permanent/`, `00 - Maps of Content/`, and `05 - Fleeting/`.

---

## 3. YAML Frontmatter Schema (Required)

Every file in `04 - Permanent/` MUST have this frontmatter:

```yaml
---
title: "Tên khái niệm / bài viết"
aliases:
  - "tên gọi khác"
tags:
  - knowledge
  - domain/<lĩnh_vực>
  - type/<loại>              # e.g., type/concept, type/source, type/topic
type: concept | source | topic
date_created: YYYY-MM-DD
date_modified: YYYY-MM-DD
source: "tên_file_nguồn.md"        # Source note reference (wiki-linkable)
source_page: ""                    # Page number from Vietnamese photo source
source_chapter: ""                 # Chapter wiki-link [[chapter]] from Vietnamese source
ground_truth_page: ""              # Page number from English ground truth source
ground_truth_chapter: ""           # Chapter wiki-link [[chapter]] from English source
source_type: pdf | epub | image | text | compiled
summary: "Insight cốt lõi 1-2 câu — KHÔNG lặp lại blockquote đầu trang"
people: []                         # Extracted human entities
companies: []                      # Extracted organization entities
status: seed | growing | evergreen
related: []                        # 5-10 wiki-links [[snake_case_concept]]
confidence: high | medium | low
---
```

---

## 3.1 `_toc.json` Schema (Canonical v8.0)

Every book workspace in `05 - Fleeting/<Book_Name>/` contains a `_toc.json` file that maps the Vietnamese photo source to the English ground truth corpus. This is the **single source of truth** for chapter resolution during the ingestion pipeline.

```jsonc
{
  "book_title_vi": "Tiêu đề tiếng Việt",              // REQUIRED — used by _sync_source_note()
  "book_title_original": "Original title (EN/other)",   // RECOMMENDED — human readability
  "author": "Tác giả",                                   // OPTIONAL
  "translator": "Dịch giả",                              // OPTIONAL (null nếu sách gốc)
  "publisher": "NXB",                                    // OPTIONAL
  "chapters": [                                           // REQUIRED
    {
      "chapter_num": 1,              // REQUIRED — int, sequential index (NOT book chapter number)
      "title_vi": "Tiêu đề VN",     // REQUIRED — used by _sync_source_note()
      "title_original": "EN title",  // RECOMMENDED — for BM25 search & readability
      "description_vi": null,        // OPTIONAL — null nếu không có
      "epub_file": "04_Ch1.md",     // REQUIRED — filename in *_MD corpus (must end with .md)
      "page_start": 19,             // OPTIONAL — trang ấn bản VN (int or null)
      "page_end": 34                // OPTIONAL — auto-calculated if missing
    }
  ]
}
```

### Rules
- `chapter_num` is a **sequential index** (1, 2, 3...), NOT the book's actual chapter number. The real chapter number is embedded in `title_original` or `title_vi`.
- `epub_file` MUST always include the `.md` extension.
- `page_start`/`page_end` are always `int` or `null`. Never strings.
- For English-only books (no Vietnamese translation), copy `title_original` into `title_vi` so `_sync_source_note()` always has display data.
- **Producers**: `epub_convert.py`, `pdf_convert.py`, `ocr.py` (Vision API), `heal_existing_tocs.py`.
- **Consumers**: `ground_truth.py` (`resolve_chapter()`), `ocr.py` (`_sync_source_note()`).

---

## 4. Note Types & Guidelines

### 4.1 Concept Notes (`04 - Permanent/concepts/`)
- **One concept per file** (atomic notes).
- Filename: `snake_case_concept_name.md` (e.g., `transformer_architecture.md`).
- **YAML Frontmatter**: Must include the `source` reference. Must proactively populate `aliases`, `tags` (domain specific), and `related` (for Obsidian Graph integration).
- **Body Structure**: Must strictly follow the minimalist template without any extra headers (No `Implications`, `Connections`, or extra `# H1`). Exact order:
  1. **Evidence Hook** — `> "Trích dẫn nguyên văn tiếng Việt"` (blockquote đứng độc lập, không nằm trong section nào). **BẮT BUỘC bằng tiếng Việt** — nếu nguồn thô là tiếng Anh, phải dịch sát nghĩa sang tiếng Việt.
  2. **Citation Line** — `> — **Tên Tác Giả**, trích dẫn trong sách/bài viết *Tên Sách* (Nguồn phụ, [[file_nguồn_thô|Tên Nguồn, Năm]])` (nằm liền ngay dưới Evidence Hook, cùng khối blockquote). Ghi rõ chủ thể phát biểu chính thức và nguồn gián tiếp kèm wiki-link trỏ về file nguồn thô.
  3. **`## Core Idea`** — Phân tích thuần tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp nội dung Evidence Hook.
  4. **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`** — **BẮT BUỘC bằng tiếng Anh nguyên bản** lấy từ nguồn thô làm căn cứ học thuật. Nằm ngay sau Core Idea để người đọc kiểm chứng liên tục. Nếu nguồn hoàn toàn bằng tiếng Việt, ghi `(không có)`.
  5. **`---`** — Dấu phân tách ngang (visual separator: nội dung tri thức / hạ tầng tra cứu)
  6. **`## References`** — CHỈ chứa tối đa 2-3 wiki-link `[[source_note]]`. KHÔNG lặp lại thông tin trang/chương (đã có trong YAML frontmatter).

### 4.2 Source Summaries (`04 - Permanent/sources/`)
- One file per ingested book.
- Filename: `YYYY-MM-DD_Book_Title_Author.md`.
- Contains: metadata about the source and full summary.
- **Important**: Must contain an `aliases` array (e.g., `aliases: ["Book Title"]`) so the wiki maintainer can extract a clean MOC name.

### 4.3 Maps of Content (`00 - Maps of Content/MOC_*.md`)
- Auto-generated overview pages that link together all concepts belonging to a specific source.
- Filename dynamically generated based on the Source Note's alias (Title Cased).
- **Zero-Concept Filtering**: MOC pages are only generated for sources that have at least 1 linked concept. Stale empty MOCs are automatically purged by the self-healing routine.

### 4.4 Domain MOCs (`00 - Maps of Content/Domain_*.md`)
- Auto-generated cross-source topic maps that group concepts by `domain/` tag.
- Created automatically when ≥8 concepts share the same domain tag.
- Structure: stats header → concepts grouped by source book.

### 4.5 Master Index (`00 - Maps of Content/index.md`)
- Auto-generated dashboard with statistics, Source MOCs, Domain MOCs, and recently added concepts.
- Updated every time a new note is compiled.

### 4.6 Topic Articles (`04 - Permanent/topics/`)
- **AI-generated long-form essays**, architecture reviews, research reports, and thematic analyses.
- Filename: `snake_case_topic_name.md` (e.g., `ai_friendly_codebase.md`, `vvc_architecture_review.md`).
- **Auto-save rule**: Whenever the agent produces a substantive article, report, or essay (>500 words) during an interactive session, it **MUST** also save a copy to `04 - Permanent/topics/` in addition to the conversation artifacts directory. This ensures all generated knowledge persists in the vault.
- Unlike concept notes, topic articles are **free-form** — they do not require the Evidence Hook → Core Idea → Ground Truth body structure. However, YAML frontmatter with `type: topic` is recommended.
- Topic articles may reference concept notes via wiki-links `[[concept_name]]`.

### 4.7 Triết lý Thiết kế: Human-AI Alignment in Document Aesthetics (v8.10.0)
Để tối ưu hóa trải nghiệm đọc của con người đồng thời bảo toàn năng lực phân tích tối đa cho AI Agent khi thực hiện các tác vụ RAG và tổng hợp tri thức, toàn bộ các tệp tài liệu trong Vault phải tuân thủ nghiêm ngặt nguyên tắc **Căn chỉnh Thẩm mỹ Song phương**:
- **Đối với Con người (Thẩm mỹ & Trực quan)**:
  - Tất cả các siêu dữ liệu trung gian, thẻ đánh dấu kỹ thuật thô của hệ thống (như danh sách các marker hình ảnh `[IMG:...]` hoặc các log phụ trợ) **bắt buộc phải được đóng gói gọn gàng bên trong Callout ẩn của Obsidian** dạng đóng mở (`> [!info]- 🖼️ Tiêu đề\n> - [IMG:...]`).
  - Hình ảnh minh họa phải được nhúng trực tiếp bằng cú pháp wiki-link tiêu chuẩn `![[filename.webp]]` ngay dưới các đoạn văn bản chứa ngữ cảnh phân tích tương ứng của bài viết (không dồn ảnh thô kệch xuống cuối trang).
- **Đối với AI (Bảo toàn Ngữ cảnh & RAG)**:
  - Tuyệt đối không xóa hoặc lược bỏ siêu dữ liệu bối cảnh (như tên tệp ảnh và `alt-text` mô tả chi tiết nội dung thị giác). Khối Callout ẩn mặc định co lại đối với con người nhưng text thô bên trong vẫn được LLM đọc trọn vẹn khi parse tệp markdown, giúp AI Agent dễ dàng nắm bắt "bản đồ tri thức" và tự động phân phối, liên kết hình vẽ vào các Concept Notes mới một cách chính xác trong pha Map-Reduce tiếp theo.

---

## 5. Autonomous Ingestion Pipeline (LLM OS v7.0 — Lean Compiler)

The vault operates via Python background daemons. Entry point: `scripts/daemon.py`.

```text
scripts/
├── daemon.py                  ← Main watchdog: queue + temporal batching + worker loop
├── book_ingest.py             ← Book watcher: EPUB/PDF → workspace setup
├── sleep.py                   ← Weekly consolidation (lint, heal, MOC rebuild)
├── wiki_maintain.py           ← Source MOC + Domain MOC + Master Index (w/ Zero-Concept filter)
├── epub_convert.py            ← EPUB → Markdown converter
├── web_clip.py                ← CLI tool: URL → Fleeting Markdown
├── config.yaml                ← Centralized configuration
│
├── .state/                    ← Operational state & journal data (Zero Cloud Contamination)
├── logs/                      ← Operational log files (daemon.log, sleep_daemon.log, etc.)
│
├── core/                      ← Shared infrastructure
│   ├── config.py              ← VaultConfig dataclass (singleton)
│   ├── types.py               ← Central type definitions & strict type checking
│   ├── daemon_utils.py        ← Watchdog helper & file stability guards
│   ├── media.py               ← Media utility seam (FFmpeg/FFprobe locator & transcode SSOT)
│   ├── prompts/               ← Prompts Registry (modularized text templates)
│   ├── llm/                   ← 3-tier LLM Modular Package (Gateway, Copilot, Gemini, Vision, Audio)
│   ├── layouts/               ← 7 deterministic layout engines (Sugiyama, Radial, Cycle, Matrix, etc.)
│   ├── layout_router.py       ← Topology auto-detection → engine dispatch
│   ├── frontmatter.py         ← YAML frontmatter parse/build/normalize_stem
│   └── log.py                 ← Append-only logger → log.md (weekly rotation)
│
├── pipeline/                  ← Ingestion stages (7 files)
│   ├── image_processor.py     ← 5-stage pipeline orchestrator (single + Map-Reduce batch)
│   ├── ocr.py                 ← Vision API: auto-orient → OCR → highlight parsing
│   ├── ground_truth.py        ← BM25 chapter-scoped matching + OCR correction
│   ├── synthesize.py          ← LLM concept note generation (Format v7.7 Cognitive Flow)
│   ├── self_correct.py        ← Independent blockquote accuracy verification
│   ├── post_process.py        ← Save concept (unicodedata strict snake_case), archive image
│   └── semantic_merger.py     ← Semantic Knowledge Merger (3-Tier Merge Control, cross-linking)
│
├── services/                  ← Interactive services & Micro-modules (~20 files)
│   ├── command.py             ← Command.md Facade (8 writing styles)
│   ├── brain_dump/            ← Brain Dump Decomposition Package (coordinator & workers)
│   ├── youtube/               ← YouTube Decomposition Package (transcripts & fallbacks)
│   ├── podcast.py             ← Podcast Ingestion Engine (Apple/Spotify/Web audio + Whisper)
│   ├── article_images.py      ← Web article image downloader & WebP compressor
│   ├── worker_dispatcher.py   ← ArtifactEngine: Strategy & Adapter Registry for all artifacts
│   ├── chat_history.py        ← Command.md Auto-Archive logic
│   ├── rag_builder.py         ← RAG Context XML formatter
│   ├── url_fetcher.py         ← Trafilatura & BeautifulSoup web scraping (no truncation limits)
│   ├── text_chunker.py        ← Semantic chunking (25K/chunk) & AI orthographic correction
│   ├── rag_search.py          ← Hybrid RAG (BM25 + Embedding + RRF fusion)
│   ├── wiki_health.py         ← Consolidated: lint + heal + domain enrichment
│   ├── moc_mermaid.py         ← MOC Mermaid diagram generators (Source + Domain, w/ chapter grouping)
│   ├── diagram_base.py        ← Shared diagram infrastructure
│   ├── excalidraw_worker.py   ← Excalidraw JSON via Copilot CLI (claude-sonnet) (w/ Text Auto-Sync)
│   ├── mermaid_worker.py      ← Mermaid diagram generation
│   └── legal_sync_worker.py   ← Autonomous Legal Document Concept generation
│
└── tests/                     ← 266 unit tests (pytest) — coverage ≥ 50%
```

### 1. Setup & Ingestion (`book_ingest.py` & `epub_convert.py`)
- Watches `03 - Resources/books/`.
- Converts EPUB to chunked markdown corpus for BM25 matching.
- Creates Source Notes and workspaces in `05 - Fleeting/`.

### 2. 5-Stage Pipeline (`daemon.py` v7.5)
- Watches `05 - Fleeting/` for images and `Command.md` / `Brain_Dump.md` for queries.
- **File Stability Guard**: Before enqueuing, `_is_file_stable()` verifies the image file size is stable (1.5s gap), preventing processing of partially-synced files from cloud junction.
- **Temporal Batching Engine**: Images dropped in the same workspace within a 10-second cooldown window are grouped into a single batch task → synthesized as one Concept Note (prevents multi-page fragmentation).
- **Stage 1 — OCR** (`pipeline/ocr.py`): Vision API → highlight parsing → page detection. When a TOC image is processed, **Reverse Metadata Sync** automatically updates the matching Source Note with the Vietnamese title and chapter table from `_toc.json`.
- **Stage 2 — Ground Truth** (`pipeline/ground_truth.py`): BM25 chapter-scoped search → OCR auto-correction.
- **Stage 3 — Synthesis** (`pipeline/synthesize.py`): LLM generates atomic Concept Note (Format v7.7 — Evidence Hook → Core Idea → Ground Truth → `---` → References).
- **Stage 4 — Self-Correction** (`pipeline/self_correct.py`): Independent blockquote verification.
- **Stage 5 — Post-Process** (`pipeline/post_process.py`): Save to concepts/, archive image (public `archive_image()` for batch archiving of extra pages), trigger MOC.
- **Stage 6 — Semantic Knowledge Merger** (`pipeline/semantic_merger.py` v8.9.9): Runs automatically before saving. Calculates Cosine similarity with existing concepts via AI Gateway `/embeddings`. If similarity $\ge 0.88$, passes through a **3-Tier Merge Control** before deciding:
  - **Tier 1 — Hook Count Gate**: If existing note has ≥4 Evidence Hooks (blockquotes `> "`), activate **Consolidated Pruning** (Tỉa cành củng cố) rather than forcing separate. The merger instructs the LLM to selectively prune and consolidate redundant or similar quotes, maintaining a strict maximum limit of 4 (preferably 3) high-value Vietnamese hooks.
  - **Tier 2 — Dynamic Size Limit**:
    - For notes under Consolidated Pruning (≥4 hooks): calculates `core_size` by stripping all blockquotes. Merges are allowed if `core_size` ≤ 6,000 bytes (protecting analysis limits) AND overall `file_size` ≤ 10,000 bytes. If either limit is exceeded, forces `SEPARATE` + cross-link.
    - For normal notes (<4 hooks): forces `SEPARATE` if `file_size` > 7,700 bytes (derived from vault-wide statistics).
  - **Tier 3 — LLM Arbitrator**: Consults LLM with 3-way decision: `MERGE`, `SEPARATE`, or `SUBSUME`. Bias toward `SEPARATE`. If `MERGE`, triggers **Academic Merge Synthesis** (combining and pruning Evidence Hooks bilingual v8.9.9, and deep rewriting of `## Core Idea`). If `SEPARATE`, saves the new file and automatically establishes two-way cross-links on the Obsidian Graph. If `SUBSUME`, the new concept is **dropped entirely** — source image is archived, event is logged to `.state/.subsume_journal.jsonl` for weekly review in `Weekly_Synthesis.md`.

### 3. Interactive Services
- **Command.md** (`services/command.py`): 8 writing styles via `/prefix`, RAG-enhanced responses, forces `|100%` on embedded diagrams.
- **Brain Dump** (`services/brain_dump.py`): Extracts pending ideas from native `## Inbox` markdown header, appends output to `## Processed`. Upgraded to **Map-Reduce Architecture (v7.4.2)** for processing long inputs and URLs:
  - **No Truncation Limits (v8.9.1)**: `url_fetcher.py` returns full extracted text without any character truncation. Articles and YouTube transcripts are passed through at their natural length. Long text is handled downstream by `text_chunker.py` (semantic chunking at 25K chars/chunk) and LLM clients (CLI tiers auto-skip at 30K chars, HTTP tiers have no limit). Gateway primary model (1M token context) and Copilot/Gemini fallbacks (128K+ token context) accommodate any realistic web article.
  - **Image Pipeline (v8.9.10)**: Article images are automatically extracted using `services/article_images.py` via `url_fetcher.py`. Extractor parses both standard `<img>` tags and Next.js/React custom `<ThemeImage>` components (prioritizing the `dark` mode URL) using Regex. Filter excludes noise (logos, icons, navigation, sidebar). Standard images are compressed concurrently to WebP (max 1536px, Q=80), while vector SVG (`.svg`) files are downloaded natively as raw bytes to bypass Pillow and size constraints, preserving crispness inside Obsidian. All are saved to `04 - Permanent/sources/assets/<domain>/` and registered as `[IMG:filename|alt=...]` markers in metadata callouts.
  - **Map Step**: Uses `task="reasoning"` to extract Atomic Concepts into a JSON array via Semantic Arbitrator. Employs a **Proportional Dynamic Limit (v8.5)** calculated dynamically based on raw text volume (from `1-3` concepts for small inputs <5k characters, up to `8-18` concepts for inputs >50k characters) to prevent information loss on large transcripts while strictly filtering out noise.
  - **Reduce Step**: Uses `task="synthesis"` with 4096 tokens limit to build strictly-formatted Concept Notes (avoids token exhaustion). Instructed by Rule 6 to embed `![[filename]]` in the `## Core Idea` section (maximum 3 images per concept).
- **Hybrid RAG** (`services/rag_search.py`): BM25 + Gemini Embeddings + RRF fusion.

### 4. Wiki Health (`services/wiki_health.py`) — OOP Architecture (v7.4)
- **3 classes**: `VaultLinter` (single-pass lint), `LinkHealer` (broken link repair), `DomainEnricher` (tag enrichment).
- **Facade pattern**: Public functions `lint_vault()`, `heal_broken_links()`, `enrich_domains()` maintain backward compatibility.
- **Semantic Arbitrator**: LLM gatekeeper in `_is_valid_concept()` — only creates stubs for high-value academic concepts. Explicitly accepts short boolean bypasses (`YES`/`NO`) to prevent false-rejections.
- **Strict Abort & Auto-Unlink**: Broken links rejected by Arbitrator are cached in `.rejected_stubs.json` and permanently unlinked (brackets stripped) from source files to prevent Infinite Retry Loops.
- **API Protection**: Enforces 20 RPM via 3.0s throttling, 30s backoff for failures, and a 3-consecutive-error Circuit Breaker.
- Runs weekly via `sleep.py` (Task Scheduler).

### 5. Diagram Generation (v7.2.1 Typesetting Engine & Text Sync)
- **Excalidraw** (`services/excalidraw_worker.py`): Copilot CLI (claude-sonnet) for spatial reasoning.
  - **Topology Router** (`scripts/core/layout_router.py`): Central brain that analyzes graph topology or layout metadata tags to auto-select engines.
  - **Deterministic Layout Engines**: Sugiyama (Hierarchy), Radial (Hub-Spoke), Cycle (Loops), Matrix (2x2/Scatter), Concentric (Concentric circles), Value Chain (Michael Porter horizontal flow), and Tree (Top-Down or Left-to-Right tree charts).
  - **Academic Book Theme**: 100% grayscale aesthetics, centralized color palette in `config.yaml`, and automatic Python text-wrapping for nodes.
  - **Text Element Auto-Sync**: Automatically extracts text elements bound to shapes and populates them into the `# Text Elements` markdown section with block IDs (`^id_txt`) to completely eliminate Obsidian text lumping bugs.
- **Mermaid** (`services/mermaid_worker.py`): LLM-generated, native Obsidian rendering (Synchronized to Grayscale Academic Theme).

---

## 6. Maintenance & Linting
- **Wiki Lint**: 6 automated health checks run during Sleep Consolidation (weekly via Task Scheduler).
- Always check for the string `Error connecting` in LLM outputs to prevent timeout errors from poisoning the Zettelkasten.
- When restarting daemons, always kill previous Ghost Processes to prevent race conditions. Note: Windows `.venv` uses a Shim Launcher architecture. It is normal to see 4 `pythonw.exe` processes (2 Shim Launchers + 2 Global Python Workers) for 2 running daemons. They are not Ghost Processes.
- Web-imputed stubs (`confidence: low`) should be reviewed and upgraded by the user.
- **Vault Sync**: Handled transparently by Google Drive Desktop via Windows Directory Junctions. The `D:\VvC_Notes` vault folders (e.g. `04 - Permanent`) are `mklink /J` junctions pointing directly to `G:\My Drive\VvC_Vault\...`. Python environments (`.venv`, `scripts`) remain isolated locally to prevent cloud contamination.
- **Code Standards**: All scripts use top-level `try/except` imports (no local imports in hot paths). Shutdown signals use `threading.Event` (not global bool). State tracking uses `@dataclass`.
- **PowerShell stdout fix**: Scripts with `__main__` block phải dùng `logging.basicConfig(stream=sys.stdout)`. Python mặc định ghi log vào `stderr` — PowerShell sẽ tự động return exit code 1 khi có bất kỳ output nào trên stderr, dù không có lỗi thực sự. Đồng thời, nếu script in ký tự Unicode (tiếng Việt có dấu) ra terminal Windows, bắt buộc gọi `sys.stdout.reconfigure(encoding='utf-8')` ở đầu để ngăn lỗi `UnicodeEncodeError` (charmap).
---

## 7. Research & Proposal Discipline — Double-Pass Adversarial Review

Trước khi đề xuất bất kỳ thay đổi kỹ thuật nào đối với pipeline, codebase, hoặc kiến trúc vault, Agent **PHẢI** thực hiện **2 vòng kiểm chứng** tuần tự. Không được trình bày đề xuất nếu chưa hoàn thành cả 2 vòng.

> [!IMPORTANT]
> Quy tắc này ra đời từ bài học thực tế trong phiên v8.7: 4/6 đề xuất tối ưu ban đầu đều SAI — bao gồm cả đề xuất tính năng đã tồn tại sẵn trong codebase (`encode_image()` đã resize ảnh), ước lượng hiệu suất lạc quan gấp 20 lần, và giả định phá hủy tính năng highlight detection.

### Vòng 1 — Code-First Research (Đọc code trước khi đề xuất)
- **KHÔNG BAO GIỜ** đề xuất tính năng "mới" mà chưa `grep`/search codebase để xác nhận nó chưa tồn tại.
- Đọc **implementation thực tế** của các hàm liên quan — không suy đoán hành vi từ tên hàm hay docstring.
- Kiểm tra data flow thực tế end-to-end: input format → transform logic → output format.
- Nếu đề xuất liên quan đến hiệu suất: **đo lường thực tế** hoặc phân tích log — KHÔNG đưa ra con số ước lượng lý thuyết như kết luận.

### Vòng 2 — Self-Adversarial Review (Tự phản biện trước khi trình bày)
- Sau khi hình thành đề xuất, **tự hỏi**: "Đề xuất này có thể SAI ở đâu? Những giả định nào chưa được kiểm chứng?"
- Xác định và kiểm tra **ít nhất 3 giả định cốt lõi** bằng dữ liệu thực (code, logs, file system).
- Nếu đề xuất ảnh hưởng đến pipeline hiện có: kiểm tra xem nó có vi phạm các design constraints đã ghi nhận trong `AGENTS.md` hoặc `GEMINI.md` không.
- Phân loại rõ ràng mỗi đề xuất: **"đã tồn tại"** vs **"cần triển khai mới"** vs **"cần thay đổi code hiện có"**.

### Quy tắc trình bày kết quả
- Mọi con số (tốc độ, dung lượng, thời gian) PHẢI kèm **nguồn**: `[đo thực tế]`, `[phân tích log]`, hoặc `[ước lượng lý thuyết — chưa kiểm chứng]`.
- Khi so sánh giải pháp: đánh giá theo ma trận **Giá trị × Độ phức tạp × Rủi ro × KISS** thay vì chỉ liệt kê ưu điểm.
- Nếu phát hiện đề xuất ban đầu sai trong quá trình kiểm chứng → **thẳng thắn ghi nhận và loại bỏ**, không cố biện minh.

---

## 8. AI Infrastructure — 3-Tier Routing (v8.12.3)

```
Tier 1 (Primary):  Antigravity CLI Driver (gemini-3.8-flash-high) / AI Gateway (ccba-ai SDK)  ← 22 models via LiteLLM
Tier 2 (Fallback): Gateway / Copilot CLI
Tier 3 (Direct):   Gemini REST API
```

| Task | Routing | Model |
|---|---|---|
| OCR / Vision | Gemini REST API / Gateway | `gemini-3.1-flash-lite-preview` |
| Text synthesis (Reduce) | Antigravity CLI → Gateway fallback | `gemini-3.8-flash-high` (Think ~3k-4.5k tokens, ~17-23s) |
| OCR correction | Gateway → Copilot CLI fallback | `gemini-3.1-flash-lite` |
| Concept Extraction (Map Step) | Antigravity CLI → Gateway fallback | `gemini-3.8-flash-high` (Cached ~8k tokens, ~13s) |
| Strategic Reasoning & Plan | Copilot CLI (CLI Tier) | `claude-opus-4-6-thinking` (Reserved for high-stakes decisions) |
| Audio / Transcription | AI Gateway | `audio-primary` (`faster-whisper-large-v3-turbo-ct2`) |
| Excalidraw diagrams | Copilot CLI | `claude-sonnet-4.6` (w/ LZString Safe Healer) |

- **Config**: `scripts/config.yaml`
- **Client Package**: `scripts/core/llm/` (Separated into `gateway_client`, `copilot_client`, `gemini_client`, `vision_client`, `audio_client`)
- **Round-Robin Load Balancing**: For bulk operations (e.g. `LinkHealer`), `call_llm(strategy="round_robin")` rotates the primary tier across all backends to evenly distribute load, effectively multiplying the overall system RPM limit by 4x.
- **Tier-Specific Routing**: Models are dynamically resolved by tier (Gateway proxy vs Copilot models) avoiding global overrides. Copilot correction model defaults to `""` to prevent Quota Exceeded errors.
- **WinError 206 Safeguard**: CLI payload limits are safely raised to **30,000 characters** by natively invoking `CreateProcessW` (bypassing `cmd.exe` wrappers like `gemini.cmd` via `node.exe`). Payloads exceeding this limit bypass CLI directly to HTTP REST APIs.
- **VAD Filter**: Audio transcription (Whisper) automatically injects `"vad_filter": true` via `extra_body` to remove silences.
- **Unconditional think-tag stripping**: `strip_think_tags()` runs on ALL LLM outputs before saving

---

## 9. Agent Skills

### Issue Tracker
Các lỗi (bugs) và yêu cầu tính năng (Specs) của dự án này được theo dõi trên GitHub Issues. Sử dụng công cụ `gh` CLI cho mọi thao tác. Xem `.md/knowledge/agents/issue_tracker.md`.

### Domain Docs
Dự án sử dụng cấu trúc Single-context. Tra cứu `CONTEXT.md` và `docs/adr/` tại thư mục gốc. Xem `.md/knowledge/agents/domain.md`.

### Skills Governance
Tuân thủ Khung Quyết Định Hai Giai Đoạn (ADR-0057 & RES-2026-ARCH-001 v1.2) với kiến trúc 3 tầng (Tier 1: Package Function, Tier 2A: Progressive Reference, Tier 2B: Standalone Kernel Skill, Tier 3: Composite Orchestrator). Mọi kỹ năng độc lập bắt buộc đạt $GPI \ge 12.0$ và vượt qua `python scripts/validate_skills.py --file <path> --enforce-gpi`.
