# 🧠 VvC Second Brain — Agent Constitution (v8.15.10)

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
> | `scripts/core/prompts/pipeline.py` | LLM prompt `<rules>` + `<output_template>` | Book Pipeline Code |
> | `scripts/core/prompts/services.py` | LLM prompt `<rules>` + `<output_template>` in `BRAIN_DUMP_REDUCE` | Brain Dump Code |
> | `scripts/pipeline/process_markdown.py` | `_MARKDOWN_PROMPT` concept format template | Markdown Pipeline Code |
> | `scripts/services/legal_sync_worker.py` | `_LEGAL_PROMPT` concept format template | Legal Sync Code |
>
> **Verification**: After propagation, run `pytest scripts/tests/` to ensure no regressions.

---

## 1. Project Overview

This vault is a **personal knowledge base** ("Second Brain") that follows the **LLM Compiler Pattern** (Andrej Karpathy, 2026). The system acts as a "Zero-Touch" LLM OS. Books and handwriting images are ingested, processed, Auto-Corrected via Ground Truth RAG, and synthesized into a structured, interlinked Zettelkasten.

**Philosophy**: You (the agent) are the **librarian and compiler**. The human is the **source provider**. Your job is to keep this wiki coherent, well-linked, and up-to-date.

### 1.1 Operating Modes

- **🟢 Interactive Mode (Default)**: Khi tương tác với con người, hành động như một librarian & pair programmer am hiểu. Giải thích suy luận, đặt câu hỏi làm rõ khi cần, sử dụng công cụ phù hợp.
- **🔵 Pipeline Mode (Automated Daemon)**: Kích hoạt khi prompt bắt đầu bằng `[PIPELINE]` hoặc trong `scripts/`. Agent đóng vai trò là một pure text processing engine: Output CHỈ nội dung được yêu cầu, KHÔNG giải thích, KHÔNG hỏi, KHÔNG bọc code fences trừ khi được yêu cầu, ngôn ngữ mặc định: **Tiếng Việt**.

---

## 2. Directory Structure & File Access Rules

```text
D:\VvC_Notes\                       ← Vault Root (Obsidian)
├── AGENTS.md                       ← THIS FILE — do NOT modify unless explicitly asked
├── 00 - Maps of Content/           ← 🗺️ Hub pages, Master Index (`index.md`), and AI Cockpit
│   ├── sources/                    ←    📚 Source MOCs (1 file per book/source)
│   └── domains/                    ←    🏷️ Domain MOCs (grouped by topic)
├── 03 - Resources/                 
│   ├── books/                      ← 📥 Human drops new books (EPUB/PDF) here (Read-only)
│   └── attachments/                ← 🖼️ Output folder for Excalidraw & Mermaid diagrams
├── 04 - Permanent/                 ← 🧠 Compiled knowledge layer
│   ├── concepts/                   ←    Atomic concept notes (1 idea = 1 file)
│   ├── sources/                    ←    Source summaries (1 book = 1 file)
│   └── topics/                     ←    📝 AI-generated long-form essays & analyses
├── 05 - Fleeting/                  ← 📸 Active ingestion workspace (human drops photos here)
├── 99 - Archive/                   ← 🗄️ Processed photos are archived here (Read-only)
├── scripts/                        ← ⚙️ Python automation daemons (Backend infrastructure)
└── templates/                      ← 📝 Obsidian note templates
```

### Rules
- **NEVER** modify files in `03 - Resources/` or `99 - Archive/`. Only read them.
- **NEVER** modify `AGENTS.md` unless explicitly asked by the user.
- **ONLY** write/update files in `04 - Permanent/`, `00 - Maps of Content/`, và `05 - Fleeting/`.

---

## 3. Canonical Schemas

### 3.1 YAML Frontmatter Schema (Required for `04 - Permanent/`)

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

### 3.2 `_toc.json` Schema (Canonical v8.0)

Mỗi thư mục sách trong `05 - Fleeting/<Book_Name>/` bắt buộc có `_toc.json` làm SSOT ánh xạ trang ảnh tiếng Việt sang corpus bản gốc tiếng Anh:

```jsonc
{
  "book_title_vi": "Tiêu đề tiếng Việt",              // REQUIRED
  "book_title_original": "Original title (EN/other)",   // RECOMMENDED
  "author": "Tác giả",                                   // OPTIONAL
  "chapters": [
    {
      "chapter_num": 1,              // REQUIRED — int, sequential index (1, 2, 3...)
      "title_vi": "Tiêu đề VN",     // REQUIRED
      "title_original": "EN title",  // RECOMMENDED
      "epub_file": "04_Ch1.md",     // REQUIRED — filename in *_MD corpus (must end with .md)
      "page_start": 19,             // OPTIONAL — trang ấn bản VN (int or null)
      "page_end": 34                // OPTIONAL — auto-calculated if missing
    }
  ]
}
```

---

## 4. Note Types & Architectural Invariants

### 4.1 Concept Notes (`04 - Permanent/concepts/`)
- **Nguyên tử hóa (Atomic)**: 1 concept = 1 file. Đặt tên: `snake_case_concept_name.md`.
- **Cấu trúc Thân bài Chuẩn mực (Canonical v8.3 Body Order)**:
  1. **Evidence Hook**: `> "Trích dẫn nguyên văn tiếng Việt"` (blockquote độc lập, không tiêu đề H1/H2). BẮT BUỘC tiếng Việt (dịch sát nghĩa nếu nguồn là tiếng Anh).
  2. **Citation Line**: `> — **Tên Tác Giả**, trích dẫn trong *Tên Sách* (Nguồn phụ, [[file_nguồn_thô|Tên Nguồn, Năm]])` (liền ngay dưới Hook).
  3. **`## Core Idea`**: Phân tích thuần tiếng Việt. KHÔNG lồng quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook.
  4. **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: BẮT BUỘC bằng **tiếng Anh nguyên bản** từ nguồn thô để kiểm chứng học thuật. Nếu nguồn thuần Việt ghi `(không có)`.
  5. **`---`**: Dấu phân cách ngang.
  6. **`## References`**: Tối đa 2-3 wiki-links `[[source_note]]`.

### 4.2 Other Note Types
- **Source Summaries (`04 - Permanent/sources/`)**: Tên `YYYY-MM-DD_Book_Title_Author.md`. Bắt buộc có `aliases` để trích xuất tên MOC.
- **Maps of Content (`00 - Maps of Content/sources/MOC_*.md`)**: Tự động sinh cho nguồn có $\ge 1$ concept note. Empty MOCs tự động bị dọn dẹp.
- **Domain MOCs (`00 - Maps of Content/domains/Domain_*.md`)**: Tự động gom nhóm khi có $\ge 15$ concepts cùng domain.
- **Master Index (`00 - Maps of Content/index.md`)**: Bảng điều khiển thống kê toàn bộ Vault.
- **Topic Articles (`04 - Permanent/topics/`)**: Bài luận dài, phân tích kiến trúc (>500 từ) tự động lưu tại đây. Bắt buộc gắn relative link tới tài liệu nội bộ đã tải về (`[📄 Bản PDF cục bộ](../../.md/extracted_docs/papers/<file>.pdf)`) bên cạnh URL/DOI trực tuyến.

### 4.3 Human-AI Alignment & Graph Health Invariants
- **Aesthetic Alignment (v8.10.0)**: Siêu dữ liệu máy móc, marker ảnh thô phải bọc trong Callout ẩn (`> [!info]- 🖼️ Tiêu đề`). Ảnh minh họa nhúng bằng cú pháp wiki-link `![[filename.webp]]` ngay dưới ngữ cảnh phân tích tương ứng.
- **Alias-First Resolution (v8.12.6)**: Khi xử lý broken links do lệch slug, thêm biến thể gọi vào `aliases` của DUY NHẤT note đích. Tuyệt đối không sửa hàng loạt hàng chục concept notes nguồn.
- **Zero-Graph Contamination**: Báo cáo meta, diagnostic reports (như `Weekly_Synthesis.md`, lint logs) tuyệt đối KHÔNG chứa live wikilinks trỏ vào broken links hay orphan notes. Bọc tên slug lỗi trong backticks `` `slug` ``.
- **Linter Scope**: Linter nạp đầy đủ 6 bề mặt (concepts, sources, topics, chapters, fleeting, MOCs); phân biệt rõ `broken_body_links` (cần sửa ngay) và `prospective_related_seeds` (trong YAML related).

### 4.4 Document Ergonomics & Visual Invariants (v8.15.10)
Toàn bộ tài liệu tri thức trong Vault bắt buộc tuân thủ 10 bộ quy chuẩn công thái học:
1. **Hybrid Golden Threshold**: Sơ đồ $\ge 3$ layers, hoặc $\ge 9$ nodes, hoặc kết nối chéo phức tạp $\ge 3$ subgraphs $\rightarrow$ BẮT BUỘC tạo Excalidraw 16:9 (`![[...excalidraw.md|100%]]`). Mermaid inline chỉ dùng cho luồng tuyến tính, tương tác song phương, hoặc chu trình $\le 8$ nodes.
2. **Excalidraw 16:9 Standards**: Khóa canvas width $1.000\text{px} \le W \le 1.150\text{px}$ (đảm bảo scale khi nhúng $\ge 65\%-70\%$), cỡ chữ sàn hiển thị $\ge 8.5\text{px}-11.5\text{px}$ (Executive Typography 16:9), bắt buộc tạo **Bảng Đặc Tả Ma Trận Kiến Trúc Markdown** ngay dưới sơ đồ; Auto-Expand Container ($H \ge H_{text} + 30\text{px}$); Wheel layout multi-tier anchor ($Y_{header}=30\text{px}, Y_{wheel}\ge 120\text{px}$); Arrow-Label Clearance ($\Delta Y \ge 15\text{px}$, khoảng cách ngang $\ge 80-90\text{px}$).
3. **Mermaid 5 Invariants**: (1) Bất đối xứng trọng số cạnh ($\Delta W = W_{down} - W_{up} \ge 2$) khóa cứng Hub ở đỉnh; (2) Directive `%%{init}%%` Grayscale Base Theme khử màu vàng mù tạt `#ffffde`; (3) `<div align='left'>` căn lề trái bullet points và thoát HTML entity (`#40;`, `#41;`); (4) Cạnh vô hình `~~~` cưỡng chế thứ tự đọc LTR; (5) Flat Two-Node Invariant cấm subgraph lồng 1 node và cấm `<br/>` trong tiêu đề subgraph.
4. **The 4 Mermaid Ergonomic Design Patterns (v8.15.9)**: Chuẩn hóa 4 mẫu thiết kế cấu trúc: (1) Macro Hub-and-Pods Layout với `HUB ===> POD` và `POD1 ~~~ POD2 ~~~ POD3` khóa chặt trục ngang; (2) Semantic Decision Tree với Badges pastel ngữ nghĩa (Xanh lá `REUSE`, Xanh dương `EXTEND`, Vàng hổ phách `CREATE NEW`); (3) Multi-Tier Governance Funnel trực quan hóa 3 tầng lọc ADR-0057 & GPI; (4) Cross-Domain Subgraphs phân vùng lãnh thổ SpokeZone vs HubZone với luồng đóng góp xuôi `==>` và phản hồi ngược `-.->` phân cấp trọng số.
5. **Markdown Table Invariants (v8.15.2)**: Bắt buộc escape pipe trong wikilinks (`[[slug\|alias]]`), non-breaking arrow (`↳&nbsp;Text`), subtitle baseline width stabilization `*(...)*`, và phân tầng 2 nhịp ($\le 40$ ký tự/dòng).
6. **Zero-ASCII Art Invariant (v8.15.3)**: Cấm tuyệt đối vẽ sơ đồ bằng ký tự ASCII/Unicode box art; dùng native language fences (```yaml, ```json) với comment dividers (`# ---`).
7. **Two-Track Callout Ergonomics (v8.15.5)**: Khối code $> 15$ dòng bọc trong Callout (`> [!abstract]+` cho code/schema, `> [!info]-` cho logs/metadata); Clean Callout Header (cấm emoji và backticks trong tiêu đề callout); Target Language Syntax Alignment (`#`, `//`, `<!-- -->`, `--`); Minimal Banner (`# --- SECTION ---`).
8. **Clean Wikilink & Zero-Code-Pill Invariant (v8.15.7)**: Cấm tuyệt đối bọc backticks quanh wikilinks trên mọi bề mặt Markdown (thân bài, bảng biểu, callouts, footnotes, danh mục tham chiếu). Backtick biến liên kết tương tác thành code pill xám và làm gãy đồ thị Graph View trong Obsidian. Trong bảng Markdown, bắt buộc escape pipe (`[[slug\|alias]]`) nhưng giữ nguyên liên kết trần; số thứ tự trích dẫn trong bảng phải đồng bộ 1-1 với danh mục tham chiếu cuối bài.
9. **Mermaid Edge Label Invariant (v8.15.10)**: Cấm tuyệt đối chèn nhãn text vào giữa thân mũi tên (`===="text"====>`, `-."text".->`, `<===="text"====>`); bắt buộc dùng cú pháp pipe chuẩn `===>|"label"|`, `-.->|"label"|`, `<===>|"label"|` hoặc `-- "label" -->`. Khi nhãn chứa toán tử so sánh, bắt buộc dùng ký tự Unicode (`≥`, `≤`) thay vì ký tự toán tử ASCII thô (`>=`, `<=`) để triệt tiêu xung đột token phân tích cú pháp.
10. **Strict HTML Entity Context Isolation Invariant (v8.15.10)**: Các thực thể HTML thoát ký tự như `#40;` và `#41;` CHỈ được phép tồn tại bên trong khối ````mermaid` (nơi chúng ngăn chặn lỗi parser node shape). CẤM TUYỆT ĐỐI để rò rỉ `#40;`/`#41;` ra ngoài các bảng biểu Markdown hoặc văn bản thông thường (nơi Obsidian không giải mã và hiển thị thô); bảng Markdown bắt buộc sử dụng dấu ngoặc đơn tròn thông thường `()`.

> [!TIP] Progressive Disclosure — Tra Cứu Trực Quan Nâng Cao
> Khi cần vẽ sơ đồ Excalidraw/Mermaid phức tạp, căn chỉnh layout hình học hoặc cấu hình D2/Kroki, Agent tra cứu cẩm nang kỹ thuật đầy đủ tại:
> 📖 [`.agents/rules/diagramming_hygiene.md`](file:///d:/VvC_Notes/.agents/rules/diagramming_hygiene.md) và [Master Skill `ccba-markdown-document-processing`](file:///d:/VvC_Notes/.agents/skills/ccba-markdown-document-processing/SKILL.md).

---

## 5. Autonomous Pipeline & AI Infrastructure (Backend Reference)

Vault vận hành thông qua các Python background daemons theo mô hình **LLM Compiler Pattern**:
- **Entry Points**: `scripts/daemon.py` (Watchdog xử lý ảnh và truy vấn), `book_ingest.py` (Watcher sách mới), `sleep.py` (Consolidation hàng tuần), `wiki_maintain.py` (Tái tạo MOCs).
- **5-Stage Pipeline**: Stage 1 OCR (Vision API) $\rightarrow$ Stage 2 Ground Truth (BM25 chapter-scoped search) $\rightarrow$ Stage 3 Synthesis (LLM Concept Note) $\rightarrow$ Stage 4 Self-Correction (Blockquote verification) $\rightarrow$ Stage 5 Post-Process & Semantic Knowledge Merger (3-Tier Merge Control, Cosine $\ge 0.88$, Consolidated Pruning).
- **AI Infrastructure (3-Tier Routing & Local Antigravity CLI Opus Tier 1)**:
  - **Tier 1 (Primary)**: Antigravity CLI Driver cục bộ (`agy.exe` — `claude-opus-4-6-thinking` cho suy luận sâu, `gemini-3.8-flash-high` cho tổng hợp concept note; Zero VPN, Zero 429).
  - **Tier 2 (Fallback)**: AI Gateway (ccba-ai SDK, LiteLLM trên Server Spark qua Tailscale VPN: `claude-opus-4-6-thinking` trên Port 8045 / `gemini-3.8-flash-high` trên Port 8090).
  - **Tier 3 (Fallback)**: GitHub Copilot CLI (`claude-sonnet-4.6`, `gpt-5-mini`) & Direct REST API (`gemini-3.1-flash-lite-preview`).
  - **WinError 206 Safeguard**: CLI payload limits an toàn đến 30,000 ký tự qua `CreateProcessW` và stream qua `stdin` (`--input-format stream-json`).
- **Stale Daemon Invariant (v8.15.9)**: Python nạp mã nguồn vào RAM khi khởi động; khi nâng cấp mã nguồn trong `scripts/` hoặc `config.yaml`, các tiến trình daemon chạy ngầm (`daemon.py`, `book_ingest.py`) vẫn giữ code cũ trong bộ nhớ, gây xung đột và xử lý sai lệch. Agent BẮT BUỘC phải hạ daemon cũ (dùng `python scripts/daemon.py --restart` hoặc PowerShell) trước khi kiểm thử hoặc chạy tác vụ downstream.
- **CLI Autonomous Artifact Ingestion Invariant (v8.15.9)**: Khi gọi `agy.exe` (Antigravity CLI Tier 1) với chuyên luận dài, LLM Opus có thể tự kích hoạt Agent mode tạo tệp artifact `.md` trên đĩa và chỉ xuất đường dẫn URI `file:///...` ra `stdout`. Lớp client (`gemini_client.py`) bắt buộc phải tự động phát hiện URI, nạp toàn văn artifact thay thế cho tệp tóm tắt trước khi bàn giao cho downstream (`topic_saver.py`, `coordinator.py`).
- **Deterministic Defense-in-Depth & SLM Prompt Anti-Literalism (v8.15.7 / v8.15.10)**: Tuyệt đối không dùng backticks bao quanh ví dụ cú pháp trong prompt LLM nếu output không được phép chứa backticks (dùng thẻ XML `<example>` thay thế) nhằm ngăn chặn hiện tượng sao chép máy móc từng ký tự (token literalism) của các mô hình nhẹ (SLMs/Flash); bắt buộc có điều khoản cấm tường minh trong `<rules>`; và mọi pipeline sinh text phải có lớp lọc tất định (deterministic regex sanitization: `clean_wikilink_quotes` bóc tách code-pill wikilinks, tự động chữa chimeric Mermaid edges thành pipe syntax `===>|"label"|`, đảo ngược thực thể `#40;` và `#41;` bị rò rỉ ngoài Mermaid thành `()`, và chuẩn hóa toán tử `≥`/`≤`) ở tầng Python runtime trước khi ghi đĩa.

> [!TIP] Progressive Disclosure — Tra Cứu Mã Nguồn & Vận Hành Pipeline
> Khi làm việc, phát triển hoặc sửa lỗi trong thư mục `scripts/`, Agent chuyển sang **Pipeline Mode** và tra cứu tài liệu chuyên sâu tại:
> ⚙️ [`scripts/README.md`](file:///d:/VvC_Notes/scripts/README.md) (Kiến trúc micro-services, danh mục script) và [`scripts/GEMINI.md`](file:///d:/VvC_Notes/scripts/GEMINI.md) (Quy tắc override vận hành pipeline).

---

## 6. Governance & Skills Standards

- **Research & Proposal Discipline**: Mọi đề xuất kỹ thuật hoặc thay đổi kiến trúc bắt buộc tuân thủ quy trình **Double-Pass Adversarial Review** (Vòng 1 Code-First Research $\rightarrow$ Vòng 2 Self-Adversarial Review) theo quy định tại **Global Memory & Context (§8)**.
- **Skills Governance**: Mọi kỹ năng Agent độc lập thuộc namespace `ccba-*` phải tuân thủ Khung Quyết Định Hai Giai Đoạn (ADR-0057), đạt điểm $GPI \ge 12.0$ và vượt qua `python scripts/validate_skills.py --file <path> --enforce-gpi`.
- **Platform Hub Invariant**: Khi task liên quan đến CCBA, Agent đọc `platform-loader/SKILL.md` và kiểm tra catalog trước khi tạo công cụ mới (Reuse-First Gate).
