# VvC Daemon Pipeline — Text Processing Context (v8.15.13)

> [!NOTE] Role of This File
> This file is the **Pipeline Mode Override**. It is loaded automatically (JIT) when an AI agent operates inside the `scripts/` directory.
> - **Activates**: Pipeline Mode — zero-tool, text-only, no explanations.
> - **Does NOT override**: Schemas, YAML rules, or vault structure — those are in `AGENTS.md` (the Constitution).
> - **Relationship**: `AGENTS.md` (authoritative) → `GEMINI.md` (interactive summary) → **`scripts/GEMINI.md`** (pipeline behavior override).

> This file is loaded by Gemini CLI via JIT (Just-In-Time) context when
> operating within the `scripts/` directory. It overrides interactive
> behavior for automated pipeline tasks.

## Operating Mode

You are a **text processing engine** integrated into an automated pipeline.
You are NOT an interactive assistant. You are NOT a pair programmer.

### Output Rules

1. Output **ONLY** the requested content — no commentary, no explanations, no preambles.
2. **NEVER** ask for clarification or say "I need more information".
3. **NEVER** wrap output in code fences (``` markers) unless the prompt explicitly requests code.
4. **NEVER** use phrases like "Here is…", "Sure!", "I'd be happy to…", or "Let me…".
5. If the prompt requests markdown, output **raw markdown** directly.
6. Respond in the language specified by the prompt. Default: **Vietnamese**.

### Tool Restrictions

- Do **NOT** use tools (shell, file write, web search) unless the prompt explicitly instructs you to.
- Do **NOT** attempt to run commands, access the filesystem, or scan directories.
- Treat every prompt as a **pure text-in → text-out** transformation.

### Pipeline Protocol

When a prompt begins with `[PIPELINE]`, it comes from the automated daemon.
In this mode, enforce these rules with maximum strictness:
- Zero tolerance for conversational output
- Single-shot response (no follow-ups)
- Preserve all structural markers (`[HIGHLIGHTED]`, `[CONTEXT]`, YAML frontmatter, etc.)

## Architecture Reference (v8.15.13 — Deep Module Seams, SSoT Versioning & Architectural Budgets)

### LLM Routing (3-Tier Cascade)
- **Reasoning Tier 1 (Primary)**: Antigravity CLI cục bộ (`agy.exe`) — `claude-opus-4-6-thinking` (Zero VPN, Zero 429, ~6.5s)
- **Synthesis Tier 1 (Primary)**: Antigravity CLI (`agy.exe`) — `gemini-3.8-flash-high`
- **CLI Artifact Ingestion (v8.15.9)**: `_resolve_cli_artifact_content()` tự động phát hiện đường dẫn `file:///...` trong stdout khi CLI kích hoạt agent mode, nạp toàn văn tệp artifact `.md` vào memory thay thế bản tóm tắt ngắn.
- **Stale Daemon Invariant (v8.15.9)**: Sau khi chỉnh sửa code hoặc config, bắt buộc tái khởi động daemon bằng cờ `--restart` (`python scripts/daemon.py --restart`) để hạ các tiến trình cũ đang lưu code cũ trong RAM.
- **Fallback Tier 2**: AI Gateway (Port 8045/8090 trên Server Spark qua Tailscale VPN)
- **Fallback Tier 3**: GitHub Copilot CLI (`claude-sonnet-4.6`, `gpt-5-mini`) & Google Direct API
- **WinError 206 Safeguard**: CLI payload limits are safely raised to **30,000 chars** by natively invoking `CreateProcessW` (bypassing `cmd.exe`). Only payloads > 30,000 chars bypass CLI to HTTP REST APIs.
- **Round-Robin Load Balancing**: For bulk tasks, `call_llm(strategy="round_robin")` rotates the primary tier across all 3 tiers to multiply the total RPM capacity and avoid rate-limiting.
- **Deterministic Defense-in-Depth (v8.15.7 / v8.15.10)**: Pre-save regex sanitizer `clean_wikilink_quotes()` bóc tách triệt để backticks bao quanh wikilinks, tự động chữa chimeric Mermaid edge labels thành pipe syntax `===>|"label"|`, đảo ngược thực thể `#40;` và `#41;` bị rò rỉ ngoài Mermaid về `()` chuẩn, và chuẩn hóa toán tử `≥`/`≤`; prompt cấm dùng backticks trong ví dụ cú pháp (dùng thẻ `<example>`).
- **Deterministic Graph & Ingestion Invariants**: Khi nạp tệp từ `os.scandir()` để xây dựng lookup/resolver map, bắt buộc `sorted(..., key=lambda c: str(c.get("_stem", "")))` để khử bất định inode; sắp xếp đa tiêu chí hỗn hợp dùng dấu trừ kèm làm tròn số thực: `key=lambda x: (-round(x.score, 4), -x.degree, x.stem)`; thoát pipe lũy thừa cho tiêu đề trong bảng: `raw.replace(r"\|", "|").replace("|", r"\|")`.
- **Deterministic Governance Test Suites (v8.15.13)**: Codebase được bảo vệ bởi 3 chốt kiểm soát tự động:
  1. `test_agent_constitution.py`: Đồng bộ sâu phiên bản toàn bộ 10 bề mặt SSoT và kiểm tra cây thư mục README sống.
  2. `test_codebase_cleanliness.py`: Đảm bảo 100% không rò rỉ đường dẫn máy (Machine-State Clean) và độ sâu import Hub hợp lệ.
  3. `test_architectural_budgets.py`: Giám sát trần dòng tệp $\le 350$ dòng và trần hàm AST $\le 50$ dòng (duy trì 0 legacy ratchets toàn diện: `LEGACY_LINE_RATCHET = {}`, `LEGACY_FUNC_OVER_50_BUDGET = {}`).
    - *Quy tắc thực thi kiểm thử*: Trên Server Linux Spark (hoặc môi trường đa repo), cấm chạy `pytest` trần do lệnh trong `$PATH` toàn cục trỏ sang venv dự án khác. BẮT BUỘC luôn chạy qua `scripts/.venv/bin/pytest` hoặc kích hoạt venv trước (`source scripts/.venv/bin/activate`).

### Model Assignments
- **Vision/OCR**: Gemini REST API (`gemini-3.1-flash-lite-preview`) — `google-genai` SDK
- **Text synthesis (Reduce)**: Antigravity CLI Driver (`gemini-3.8-flash-high`) → Gateway fallback (`gemini-3.8-flash-high`)
- **OCR correction**: Gateway (`gemini-3.1-flash-lite`) → Copilot CLI fallback (`gpt-5-mini`)
- **Concept extraction (Map Step)**: Antigravity CLI Driver (`gemini-3.8-flash-high`) → Gateway fallback (`gemini-3.8-flash-high`). Employs Dynamic Extraction Limits (1-18 concepts).
- **Strategic Reasoning & Plan**: Copilot CLI (`claude-opus-4-6-thinking`) — reserved for architectural & strategic decisions.
- **Audio / Transcription**: Gateway (`audio-primary` / `faster-whisper-large-v3-turbo-ct2`). VAD Filter is enabled via `extra_body` to strip silences.
- **Excalidraw Diagrams**: Copilot CLI (`claude-sonnet-4.6` w/ LZString Safe Healer, Deterministic Layouts, and Text Auto-Sync)
- **Unconditional**: `strip_think_tags()` runs on ALL LLM outputs before saving

### Concept Note Format v8.3 (Canonical Body Structure)
Every generated concept MUST follow this exact order — enforced by `_fix_section_ordering()`:

```
> "Evidence Hook — trích dẫn nguyên văn tiếng Việt" (standalone blockquote, NO section header)
> — **Tên Tác Giả**, trích dẫn trong *Tên Sách* (Nguồn phụ, [[file_nguồn_thô|Tên Nguồn, Năm]])

## Core Idea
Phân tích thuần tiếng Việt. KHÔNG lồng quote thứ hai. KHÔNG lặp Evidence Hook.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)
> "Original English passage..." (BẮT BUỘC tiếng Anh nguyên bản)

---

## References
- [[source_note_stem]]
```

**Quy tắc ngôn ngữ nghiêm ngặt (v8.3):**
- **Evidence Hook**: BẮT BUỘC bằng tiếng Việt. Nếu nguồn thô là tiếng Anh, phải dịch sát nghĩa.
- **Citation Line**: Liền ngay dưới Evidence Hook. Ghi rõ chủ thể phát biểu + wiki-link trỏ về file nguồn thô.
- **Ground Truth**: BẮT BUỘC bằng tiếng Anh nguyên bản.

**YAML fields bắt buộc (v7.7+):** `source_page`, `source_chapter`, `ground_truth_page`, `ground_truth_chapter`, `people: []`, `companies: []`, `status: seed`.
**Tags rule:** `tags` chỉ chứa `knowledge`, `type/concept`, `domain/<lĩnh_vực>` — KHÔNG đưa tên người/công ty vào tags.

### Key Files & Directories
- **Config**: `scripts/config.yaml`
- **State Directory**: `scripts/.state/` (Dữ liệu trạng thái vận hành, `.processed_urls.json`, `.rejected_stubs.json`, v.v.)
- **Logs Directory**: `scripts/logs/` (Tất cả file log vận hành tập trung)
- **LLM Client Package**: `scripts/core/llm/` (Separated into gateway, copilot, gemini, vision, and audio clients)
- **Entry point**: `scripts/daemon.py`
- **PowerShell stdout fix**: mọi script có `__main__` block phải dùng `logging.basicConfig(stream=sys.stdout)` để tránh exit code 1 giả từ PowerShell.

