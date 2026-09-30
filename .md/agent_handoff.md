# 🤝 Báo cáo Bàn giao Context Công nghệ (v8.16.0) — VvC Second Brain

> Tệp tin này được thiết lập tại `.\.md\agent_handoff.md` theo đúng quy trình bàn giao Macro (Phiên) được thống nhất giữa Người dùng và AI Agent.
> Mục tiêu là giúp AI Agent tiếp theo nạp bối cảnh và tiếp quản dự án JIT (Just-In-Time) 100% thành công mà không cần hỏi lại người dùng.

---

## 1. Bản đồ Trạng thái Hệ thống (System State Map)

* **Phiên bản hiện tại:** `v8.16.0 — Architectural Hardening: Multi-Device Fencing, Core Idea Semantic Embedding, Ingestion Queue & Origin Tagging`
* **Nhánh Git:** `main` (commit `ccf5ada`), đồng bộ 100% với `origin/main`, `working tree clean`.
* **Tổng số Concepts trong Vault:** **2,908 notes** (`origin` tagging: `book: 2319`, `ocr: 445`, `web: 100`, `command: 44`), toàn bộ Clean Wikilink Invariant 100% PASS, 0 code-pills.
* **Kết quả Kiểm thử:**
  - `scripts/.venv/bin/pytest scripts/tests`: **617/617 unit tests PASSED (112.5s)**, 0 failures, 0 regressions.
  - `test_architectural_budgets.py`: **2/2 unit tests PASSED**. Toàn bộ tệp sản xuất $\le 350$ dòng, toàn bộ hàm AST $\le 50$ dòng (**0 legacy ratchets toàn diện — 100% tuân thủ**).
  - `test_codebase_cleanliness.py`: **3/3 unit tests PASSED**, 0 vi phạm Machine-State Leakage, 100% Clean.
  - `test_agent_constitution.py`: **13/13 unit tests PASSED**, 0 documentation drift trên toàn bộ 10 context files.
* **Hạ tầng 24/7 (systemd services trên Server Spark Ubuntu Linux aarch64, 100.83.192.30):**
  - `vvc-gdrive-mount.service` — active (Rclone VFS mount cache 10GB/72h, `--poll-interval 15s`).
  - `vvc-daemon.service` — active (Watchdog xử lý Command.md, Brain_Dump.md, Fleeting OCR, Inbox queue, nhịp tim `.spark_heartbeat_epoch.json` — PID live).
  - `vvc-book-ingest.service` — active (Watcher tự động biên dịch sách mới).
  - `vvc-sleep.timer` — active (Weekly Sleep Consolidation 02:00 AM Chủ Nhật).
* **Bất biến Vận hành Sống còn (Active-Passive Single-Active Runner):**
  - Server Linux Spark là **Primary Host duy nhất** chạy daemon 24/7.
  - Máy trạm Windows chỉ là Client (Obsidian UI). Tuyệt đối cấm chạy daemon đồng thời cả hai máy để chống thảm họa Google Drive Split-Brain. Khi cần chạy runner cục bộ trên Windows, bắt buộc phải dùng `scripts/start_windows_runner.cmd` để dừng service trên Spark và kiểm tra nhịp tim an toàn.

---

## 2. Các thay đổi trong phiên v8.16.0 (30/09/2026)

| Hạng mục | Tệp tin tác động | Chi tiết kỹ thuật |
| :--- | :--- | :--- |
| **Hàng rào Nhịp tim Đa máy (Cross-Machine Fencing)** | [`scripts/core/cross_machine_fencing.py`](file:///home/vvc/VvC_Notes/scripts/core/cross_machine_fencing.py)<br/>[`scripts/daemon.py`](file:///home/vvc/VvC_Notes/scripts/daemon.py)<br/>[`scripts/start_windows_runner.cmd`](file:///home/vvc/VvC_Notes/scripts/start_windows_runner.cmd) | **PR #23 (`ccf5ada`)**: Thiết lập cơ chế chống Split-Brain thông qua tệp `.spark_heartbeat_epoch.json` (TTL 120s). Linux daemon duy trì nhịp tim định kỳ trong vòng lặp; Windows runner kiểm tra heartbeat và từ chối chạy song song nếu daemon Linux đang sống. |
| **Hàng đợi Inbox & Bộ thu hoạch Xung đột** | [`scripts/services/brain_dump/inbox_io.py`](file:///home/vvc/VvC_Notes/scripts/services/brain_dump/inbox_io.py)<br/>[`scripts/services/brain_dump/orchestrator.py`](file:///home/vvc/VvC_Notes/scripts/services/brain_dump/orchestrator.py) | Hỗ trợ hàng đợi thu nạp đa tệp `05 - Fleeting/inbox/*.md`. Tự động phát hiện và thu hoạch các tệp xung đột Google Drive (`Brain_Dump (*).md` hoặc `*conflict*`), trích xuất toàn bộ nội dung chưa xử lý và lưu trữ có tổ chức vào `99 - Archive/inbox/`. |
| **Phân loại Provenance & RAG Penalty** | [`scripts/core/frontmatter.py`](file:///home/vvc/VvC_Notes/scripts/core/frontmatter.py)<br/>[`scripts/services/rag/context_builder.py`](file:///home/vvc/VvC_Notes/scripts/services/rag/context_builder.py)<br/>[`scripts/migrations/migrate_origin_tag.py`](file:///home/vvc/VvC_Notes/scripts/migrations/migrate_origin_tag.py) | Bổ sung trường bắt buộc `origin: book \| ocr \| web \| command` vào YAML schema. Di trú toàn diện 2.908 notes trong Vault. Áp dụng hệ số phạt $0.85\times$ điểm RAG cho các nguồn `web` và `command` khi rerank để bảo vệ tính hàn lâm của tri thức từ sách gốc. |
| **Trích xuất Ngữ nghĩa BGE-M3 Sâu** | [`scripts/core/frontmatter.py`](file:///home/vvc/VvC_Notes/scripts/core/frontmatter.py)<br/>[`scripts/core/vector_io.py`](file:///home/vvc/VvC_Notes/scripts/core/vector_io.py) | Hàm `extract_concept_semantic_text` bóc tách chuyên biệt phần `## Core Idea`, tiêu đề và summary, loại bỏ hoàn toàn blockquotes tiếng Anh Ground Truth và frontmatter trước khi vector hóa bằng mô hình local BGE-M3 (1024-d). |
| **Sàn Điểm Ground Truth & Sleep Thích Ứng** | [`scripts/pipeline/ground_truth.py`](file:///home/vvc/VvC_Notes/scripts/pipeline/ground_truth.py)<br/>[`scripts/sleep.py`](file:///home/vvc/VvC_Notes/scripts/sleep.py) | Siết chặt sàn BM25 Score $\ge 0.65$ cho các trích dẫn Ground Truth nhằm loại bỏ matches mơ hồ; điều chỉnh giới hạn sleep consolidation động dựa trên quy mô concept notes hiện có trong Vault. |

---

## 3. Bài học cốt lõi & Phòng ngừa (Lessons Learned)

1. **Bẫy Masking Thư Mục Con Trong Gitignore**:
   - Khi un-ignore tệp trong một thư mục bị ignore, dùng `.dir/*` sẽ khiến Git dừng duyệt sâu ngay khi gặp thư mục con. Bắt buộc dùng cú pháp đệ quy 4 dòng (`.dir/**`, `!.dir/**/`, `!.dir/**/*.md`, `!.dir/**/*.yaml`).
2. **Cú pháp YAML Wildcard trong Cursor Rules (Fatal Alias Dereference)**:
   - Trong YAML 1.2, ký tự `*` đầu scalar là toán tử dereference alias. Để `globs: *` trần sẽ gây `yaml.scanner.ScannerError` làm sập trình nạp rule của Cursor. Bắt buộc bọc ngoặc kép: `globs: "*"`.
3. **Chống "Sham Unit Tests" Cho Cấu Hình (ADR-0058)**:
   - Unit test kiểm tra tệp cấu hình không được dùng string containment checks hời hợt (`assert "key:" in text`) vì sẽ tạo ra False Green. Bắt buộc phải parse dữ liệu bằng parser thật (`yaml.safe_load`, `json.loads`) và kiểm tra đường dẫn tồn tại thực tế trên đĩa.
4. **Fenced Code Block Cho Ví Dụ Cú Pháp Wikilink**:
   - Khi viết ví dụ minh họa về cú pháp wikilink (`[[...]]`) hoặc embed tag (`![[...]]`), cấm tuyệt đối dùng inline backticks. Phải đặt trong fenced code block để linter và regex sanitizer không nhận diện nhầm là liên kết hỏng.
5. **Ranh Giới Kiến Trúc Phân Tầng Lưu Trữ (Git vs Google Drive Mount)**:
   - Các thư mục tri thức `04 - Permanent/`, `03 - Resources/`, `00 - Maps of Content/` là symlinks trỏ sang Google Drive qua Rclone FUSE mount và được `.gitignore` loại trừ vĩnh viễn. Git commit chỉ lưu trữ mã nguồn hạ tầng, SSoT context và quy chuẩn Hiến pháp.
6. **Ô Nhiễm `$PATH` Khi Chạy Kiểm Thử Trên Server Spark**:
   - Lệnh `pytest` trong `$PATH` toàn cục (`/home/vvc/.local/bin/pytest`) là wrapper script trỏ sang môi trường của dự án `ccba-legal-knowledge`. Nếu chạy `pytest` trần sẽ gây lỗi 64 bài test do thiếu package đồ họa/media.
   - **Quy tắc bắt buộc**: Luôn gọi trực tiếp qua `scripts/.venv/bin/pytest` hoặc kích hoạt virtualenv trước (`source scripts/.venv/bin/activate`). Môi trường `scripts/.venv` có đầy đủ 100% dependencies và vượt qua 617/617 bài test.
7. **Bảo toàn Ngân sách Kiến trúc (Zero-Slack Ratchet Budgets)**:
   - Toàn bộ 100% legacy ratchets đã được loại bỏ (`LEGACY_LINE_RATCHET = {}`, `LEGACY_FUNC_OVER_50_BUDGET = {}`).
   - Mọi tệp sản xuất mới hoặc refactor bắt buộc tuân thủ trần cứng $\le 350$ dòng và hàm AST $\le 50$ dòng; cấm tuyệt đối mở thêm ratchet để lách kiểm thử.
8. **Vùng Đệm Session Artifacts `.md/scratch/`**:
   - Quy tắc `.gitignore` (`!.md/**/*.md`) vô tình un-ignore mọi tệp markdown tạo trực tiếp dưới `.md/`. Để giữ `working tree clean`, mọi tệp kế hoạch, task list, và walkthrough tạm thời của AI Agents bắt buộc phải tạo bên trong `.md/scratch/`.
9. **Cơ chế Hàng rào Nhịp tim Epoch Đa Máy (Heartbeat Epoch Fencing)**:
   - Khi vận hành kiến trúc Active-Passive trên cùng thư mục Google Drive đồng bộ, giải pháp đơn giản và tin cậy nhất là tệp epoch heartbeat (`.spark_heartbeat_epoch.json`) ghi nhận timestamp UNIX thời gian thực kèm TTL (120s). Phía client kiểm tra sự tồn tại và tính tươi mới của nhịp tim để từ chối khởi động cục bộ, triệt tiêu nguy cơ Split-Brain.
10. **Tách biệt Ngữ nghĩa Thuần (Core Semantic Text) Khi Nhúng Vector**:
    - Nhúng toàn bộ tệp concept note chứa cả blockquotes tiếng Anh Ground Truth và YAML frontmatter làm loãng vector đại diện. Trích xuất chuyên biệt khối `## Core Idea`, tiêu đề và summary giúp vector embedding BGE-M3 phản ánh chính xác 100% nội dung phân tích cốt lõi, nâng cao độ chính xác khi truy vấn RAG.
11. **Thu Hoạch Tệp Xung Đột Đồng Bộ Đám Mây (Cloud Sync Conflict Harvester)**:
    - Thay vì cố gắng ngăn chặn xung đột đồng bộ ở tầng mạng (vốn không khả thi do độ trễ Google Drive và các thiết bị di động ngắt quãng), giải pháp tối ưu là xây dựng Harvester tự động nhận diện các tệp xung đột `Brain_Dump (*).md` hoặc `*conflict*`, nạp nội dung dở dang vào pipeline và chuyển tệp cũ sang kho lưu trữ có dấu thời gian.
12. **Chiến Lược Phạt Trọng Số Provenance Trong RAG (Provenance Bias Penalty)**:
    - Khi tích hợp tri thức đa nguồn, không nên loại bỏ hoàn toàn các ghi chú nhanh hoặc truy vấn command, mà phân tầng bằng trường `origin` và áp dụng hệ số phạt nhẹ ($0.85\times$) khi rerank. Điều này đảm bảo các khái niệm được kiểm chứng từ sách gốc luôn được ưu tiên hàng đầu, trong khi vẫn giữ được tính kết nối của đồ thị tri thức.

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
> 4. Kiểm tra sức khỏe Hiến pháp, ngân sách kiến trúc và tài liệu qua pytest:
>    ```bash
>    scripts/.venv/bin/pytest scripts/tests/test_agent_constitution.py scripts/tests/test_architectural_budgets.py -v
>    scripts/.venv/bin/python scripts/wiki_maintain.py --check-only
>    ```
> 5. **Stale Daemon Invariant**: Nếu có chỉnh sửa code trong `scripts/` hoặc `scripts/config.yaml`, BẮT BUỘC phải khởi động lại daemon:
>    ```bash
>    scripts/.venv/bin/python scripts/daemon.py --restart
>    systemctl --user restart vvc-daemon.service
>    ```
