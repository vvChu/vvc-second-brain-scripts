# 🤝 Báo cáo Bàn giao Context Công nghệ (v8.15.11) — VvC Second Brain

> Tệp tin này được thiết lập tại `.\.md\agent_handoff.md` theo đúng quy trình bàn giao Macro (Phiên) được thống nhất giữa Người dùng và AI Agent.
> Mục tiêu là giúp AI Agent tiếp theo nạp bối cảnh và tiếp quản dự án JIT (Just-In-Time) 100% thành công mà không cần hỏi lại người dùng.

---

## 1. Bản đồ Trạng thái Hệ thống (System State Map)

* **Phiên bản hiện tại:** `v8.15.11 — Living Architecture Reference, 8 Pillars, 3 Breakthroughs & 5-Layer Defense-in-Depth`
* **Nhánh Git:** `docs/vault-mental-model-architecture` (commits `171cde9`, `45cf4ac`).
* **Tổng số Concepts trong Vault:** **2,711 concepts**, **252 sources** (Toàn bộ Clean Wikilink Invariant 100% PASS, 0 code-pills).
* **Kết quả Kiểm thử:**
  - `test_agent_constitution.py`: **10/10 unit tests PASSED (0.06s)**.
  - Toàn bộ kho kiểm thử Vault: **537/537 passed (40.61s - 56.09s)**, 0 failures, 0 regressions.
  - Spoke Cleanliness & Import Depth: **12/15 scripts budget**, 152 tệp quét 0 vi phạm import depth.
* **Hạ tầng 24/7 (systemd services trên Server Spark Ubuntu Linux aarch64, 100.83.192.30):**
  - `vvc-gdrive-mount.service` — active (Rclone VFS mount cache 10GB/72h).
  - `vvc-daemon.service` — active (Watchdog xử lý Command.md, Brain_Dump.md, Fleeting OCR).
  - `vvc-book-ingest.service` — active (Watcher tự động biên dịch sách mới).
* **Bất biến Vận hành Sống còn (Active-Passive Single-Active Runner):**
  - Server Linux Spark là **Primary Host duy nhất** chạy daemon 24/7.
  - Máy trạm Windows chỉ là Client (Obsidian UI). Tuyệt đối cấm chạy daemon đồng thời cả hai máy để chống thảm họa Google Drive Split-Brain.

---

## 2. Các thay đổi trong phiên v8.15.11 (23/09/2026)

| Hạng mục | Tệp tin tác động | Chi tiết kỹ thuật |
| :--- | :--- | :--- |
| **Master Canonical Topic Note** | `04 - Permanent/topics/kien_truc_va_mental_model_vvc_second_brain.md` | Biên soạn chuyên luận toàn diện: 8 Trụ Cột (P1–P8), mô hình Karpathy 2026, 3 đột phá thực nghiệm độc bản (Verifiable Ground Truth RAG, Noise Gating & Anti-Resurrection, Closed-Loop Compounding), và tiến hóa 6 bước từ v8.9 lên v8.15.11. Khử triệt để 5 code-pills tại L249–255 bằng fenced code block. |
| **Sơ đồ Excalidraw 16:9** | `03 - Resources/attachments/vvc_second_brain_architecture.excalidraw.md` | Thiết kế sơ đồ kiến trúc chuẩn công thái học 16:9 ($1.080\text{px} \times 607.5\text{px}$ design envelope, bounding box $1.020\text{px} \times 619\text{px}$, tỷ lệ scale khi nhúng $\ge 65\%-70\%$). 34 elements (12 rectangles, 22 texts), bảng màu Executive Modern Theme (Slate/Teal/Indigo/Blue), 4 cấp font Executive Typography (18px, 13px, 12px, 11px). Đi kèm Bảng Đặc Tả Ma Trận Kiến Trúc Markdown bên dưới. |
| **Technical Reference Pointer** | `.md/vault_mental_model_and_architecture.md` | Tóm lược kỹ thuật xúc tích đặt tại `.md/` theo chuẩn Global Rule §1 giúp AI Agents nắm bắt ngay kiến trúc khi bắt đầu phiên. |
| **Ngũ Tầng Phòng Thủ (Layer 0–4)** | `.gitignore`, `.md/workspace_context.yaml`, `AGENTS.md`, `GEMINI.md`, `scripts/GEMINI.md`, `CHANGELOG.md`, `CLAUDE.md`, `.cursor/rules/`, `.github/`, `scripts/tests/` | Thiết lập hệ thống phòng thủ khép kín cưỡng chế nạp mental model cho mọi AI Agents: (L0) un-ignore đệ quy `.md/**/`; (L1) SSoT context với `pipeline_mode_bypass` và `subagent_mode_bypass`; (L2) Hiến pháp §1.1 và mở rộng Sync Manifest 12 tệp; (L3) Cross-IDE configs với Cursor quoted `globs: "*"`; (L4) 10 unit tests CI/CD. |
| **Đúc Kết Bài Học (/learn)** | `AGENTS.md` (L200), `GEMINI.md` (L59), `scripts/tests/test_agent_constitution.py` | Bổ sung quy chuẩn: Mọi ví dụ cú pháp hoặc placeholder cho liên kết (`[[...]]` hoặc `![[...]]`) BẮT BUỘC đặt trong fenced code block chuẩn (ngôn ngữ `text` hoặc `markdown`), cấm inline backticks để triệt tiêu lỗi code-pill và ngăn regex sanitizer bóc tách làm gãy đồ thị Obsidian. |

---

## 3. Bài học cốt lõi & Phòng ngừa (Lessons Learned)

1. **Bẫy Masking Thư Mục Con Trong Gitignore**:
   - Khi un-ignore tệp trong một thư mục bị ignore, dùng `.dir/*` sẽ khiến Git dừng duyệt sâu ngay khi gặp thư mục con. Bắt buộc dùng cú pháp đệ quy 4 dòng:
     ```gitignore
     .dir/**
     !.dir/**/
     !.dir/**/*.md
     !.dir/**/*.yaml
     ```
2. **Cú pháp YAML Wildcard trong Cursor Rules (Fatal Alias Dereference)**:
   - Trong YAML 1.2, ký tự `*` đầu scalar là toán tử dereference alias. Để `globs: *` trần sẽ gây `yaml.scanner.ScannerError` làm sập trình nạp rule của Cursor. Bắt buộc bọc ngoặc kép: `globs: "*"`.
3. **Chống "Sham Unit Tests" Cho Cấu Hình (ADR-0058)**:
   - Unit test kiểm tra tệp cấu hình không được dùng string containment checks hời hợt (`assert "key:" in text`) vì sẽ tạo ra False Green. Bắt buộc phải parse dữ liệu bằng parser thật (`yaml.safe_load`, `json.loads`) và kiểm tra đường dẫn tồn tại thực tế trên đĩa.
4. **Fenced Code Block Cho Ví Dụ Cú Pháp Wikilink**:
   - Khi viết ví dụ minh họa về cú pháp wikilink (`[[...]]`) hoặc embed tag (`![[...]]`), cấm tuyệt đối dùng inline backticks. Phải đặt trong fenced code block để linter và regex sanitizer không nhận diện nhầm là liên kết hỏng.
5. **Ranh Giới Kiến Trúc Phân Tầng Lưu Trữ (Git vs Google Drive Mount)**:
   - Các thư mục tri thức `04 - Permanent/`, `03 - Resources/`, `00 - Maps of Content/` là symlinks trỏ sang Google Drive qua Rclone FUSE mount và được `.gitignore` loại trừ vĩnh viễn. Git commit chỉ lưu trữ mã nguồn hạ tầng, SSoT context và quy chuẩn Hiến pháp.

---

## 4. Chỉ dẫn JIT nạp Context cho AI kế nhiệm (Memo for next Agent)

> [!IMPORTANT]
> **Hãy thực hiện các bước sau để tiếp quản dự án lập tức:**
> 1. Đọc tệp cấu hình SSoT trung tâm tại [`.md/workspace_context.yaml`](file:///home/vvc/VvC_Notes/.md/workspace_context.yaml) và bản tóm lược kiến trúc [`.md/vault_mental_model_and_architecture.md`](file:///home/vvc/VvC_Notes/.md/vault_mental_model_and_architecture.md).
> 2. Đọc Hiến pháp toàn cục tại [`AGENTS.md`](file:///home/vvc/VvC_Notes/AGENTS.md) (§1.1 Living Architecture Reference và §4.4 Document Ergonomics & Visual Invariants) cùng [`GEMINI.md`](file:///home/vvc/VvC_Notes/GEMINI.md).
> 3. Kiểm tra trạng thái tiến trình nền daemon trên Linux:
>    ```bash
>    systemctl --user status vvc-daemon.service vvc-book-ingest.service
>    ```
> 4. Kiểm tra sức khỏe Hiến pháp và tài liệu qua pytest:
>    ```bash
>    scripts/.venv/bin/pytest scripts/tests/test_agent_constitution.py -v
>    scripts/.venv/bin/python scripts/wiki_maintain.py --check-only
>    ```
> 5. **Stale Daemon Invariant**: Nếu có chỉnh sửa code trong `scripts/` hoặc `scripts/config.yaml`, BẮT BUỘC phải khởi động lại daemon:
>    ```bash
>    scripts/.venv/bin/python scripts/daemon.py --restart
>    ```
