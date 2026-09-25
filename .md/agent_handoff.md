# 🤝 Báo cáo Bàn giao Context Công nghệ (v8.15.13) — VvC Second Brain

> Tệp tin này được thiết lập tại `.\.md\agent_handoff.md` theo đúng quy trình bàn giao Macro (Phiên) được thống nhất giữa Người dùng và AI Agent.
> Mục tiêu là giúp AI Agent tiếp theo nạp bối cảnh và tiếp quản dự án JIT (Just-In-Time) 100% thành công mà không cần hỏi lại người dùng.

---

## 1. Bản đồ Trạng thái Hệ thống (System State Map)

* **Phiên bản hiện tại:** `v8.15.13 — Monotonic Architectural Budgets, Zero-Slack Ratchets, Context-Managed Batch Flush & Deep Module Seams`
* **Nhánh Git:** `main` (commit `dbf68c4`), đồng bộ 100% với `origin/main`, `working tree clean`.
* **Tổng số Concepts trong Vault:** **2,782 concepts**, **264 sources** (Toàn bộ Clean Wikilink Invariant 100% PASS, 0 code-pills).
* **Kết quả Kiểm thử:**
  - `scripts/.venv/bin/pytest scripts/tests`: **595/595 unit tests PASSED (92.44s)**, 0 failures, 0 regressions.
  - `test_architectural_budgets.py`: **2/2 unit tests PASSED**. Toàn bộ 29 tệp legacy line ratchet và 83 tệp legacy func budget đạt độ khít **Zero-Slack 100%**.
  - `test_codebase_cleanliness.py`: **3/3 unit tests PASSED**, 0 vi phạm Machine-State Leakage, 12/15 scripts budget.
  - `test_agent_constitution.py`: **12/12 unit tests PASSED**, 0 documentation drift.
* **Hạ tầng 24/7 (systemd services trên Server Spark Ubuntu Linux aarch64, 100.83.192.30):**
  - `vvc-gdrive-mount.service` — active (Rclone VFS mount cache 10GB/72h).
  - `vvc-daemon.service` — active (Watchdog xử lý Command.md, Brain_Dump.md, Fleeting OCR — chạy code tối ưu PR #5).
  - `vvc-book-ingest.service` — active (Watcher tự động biên dịch sách mới).
  - `vvc-sleep.timer` — active (Weekly Sleep Consolidation 02:00 AM Chủ Nhật).
* **Bất biến Vận hành Sống còn (Active-Passive Single-Active Runner):**
  - Server Linux Spark là **Primary Host duy nhất** chạy daemon 24/7.
  - Máy trạm Windows chỉ là Client (Obsidian UI). Tuyệt đối cấm chạy daemon đồng thời cả hai máy để chống thảm họa Google Drive Split-Brain.

---

## 2. Các thay đổi trong phiên v8.15.13 (25/09/2026)

| Hạng mục | Tệp tin tác động | Chi tiết kỹ thuật |
| :--- | :--- | :--- |
| **Context-Managed Batch Flush** | [`scripts/core/vector_store.py`](file:///home/vvc/VvC_Notes/scripts/core/vector_store.py)<br/>[`scripts/pipeline/image_processor.py`](file:///home/vvc/VvC_Notes/scripts/pipeline/image_processor.py)<br/>[`scripts/services/brain_dump/concept_synthesis.py`](file:///home/vvc/VvC_Notes/scripts/services/brain_dump/concept_synthesis.py) | **PR #5 (`f56983c`)**: Triển khai `with vector_store.batch():` gộp nhiều thao tác `hot_insert` thành một lần `flush` ghi đĩa nguyên tử duy nhất. Giảm độ phức tạp I/O đĩa từ $O(N)$ xuống $O(1)$, triệt tiêu hiện tượng write amplification khi nạp sách hàng loạt. |
| **Ratchet Tightening Vector Store** | [`scripts/tests/test_architectural_budgets.py`](file:///home/vvc/VvC_Notes/scripts/tests/test_architectural_budgets.py) | **Issue #9 / PR #10 (`174b0c7`, `f499150`)**: Khóa chặt thành quả tối ưu của `core/vector_store.py`. Cập nhật `LEGACY_LINE_RATCHET` từ 552 xuống **547 dòng** (-5 dòng), và `LEGACY_FUNC_OVER_50_BUDGET` từ 3 xuống **1 hàm** (`sync_all`: 135 dòng). |
| **Zero-Slack Ratchet Completion** | [`scripts/tests/test_architectural_budgets.py`](file:///home/vvc/VvC_Notes/scripts/tests/test_architectural_budgets.py) | **Commit `dbf68c4`**: Khắc phục 2 dòng slack còn dư từ PR #5. Siết chặt `pipeline/image_processor.py` từ 518 xuống **517 dòng**, và `services/brain_dump/concept_synthesis.py` từ 549 xuống **548 dòng**. Toàn bộ 29/29 tệp legacy line ratchet và 83/83 tệp func budget đạt 100% Zero-Slack theo Hiến pháp `AGENTS.md`. |
| **Vệ sinh Session Artifacts** | [`.md/scratch/`](file:///home/vvc/VvC_Notes/.md/scratch) | Di chuyển toàn bộ tệp tạm (`implementation_plan.md`, `task.md`, `walkthrough.md`) vào thư mục đệm `.md/scratch/` (được `.gitignore` L100 bỏ qua). Khôi phục `working tree clean` 100%. |

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
6. **Ô Nhiễm `$PATH` Khi Chạy Kiểm Thử Trên Server Spark**:
   - Lệnh `pytest` trong `$PATH` toàn cục (`/home/vvc/.local/bin/pytest`) là wrapper script trỏ sang môi trường của dự án `ccba-legal-knowledge`. Nếu chạy `pytest` trần sẽ gây lỗi 64 bài test do thiếu package đồ họa/media.
   - **Quy tắc bắt buộc**: Luôn gọi trực tiếp qua `scripts/.venv/bin/pytest` hoặc kích hoạt virtualenv trước (`source scripts/.venv/bin/activate`). Môi trường `scripts/.venv` có đầy đủ 100% dependencies và vượt qua 595/595 bài test.
7. **Headroom Fragility và Bẫy Kiến Trúc trong `core/vector_store.py`**:
   - Tệp hiện có 4 hàm cận biên trần 50 dòng AST (`flush`: 48, `hot_insert`: 46, `_read_index_data`: 44, `search`: 43) và chạm trần tổng 547 dòng (slack = 0).
   - **Quy tắc bất biến**: Tuyệt đối CẤM refactor inline tạo helper methods nội bộ trong tệp này vì sẽ làm vỡ trần 547 dòng. Khi cần mở rộng logic vector store, giải pháp duy nhất hợp thức là **bóc tách thành deep package** `scripts/core/vector_store/` (chứa `store.py`, `batch.py`, `sync.py`, `io.py`).
8. **Vùng Đệm Session Artifacts `.md/scratch/`**:
   - Quy tắc `.gitignore` (`!.md/**/*.md`) vô tình un-ignore mọi tệp markdown tạo trực tiếp dưới `.md/`. Để giữ `working tree clean`, mọi tệp kế hoạch, task list, và walkthrough tạm thời của AI Agents bắt buộc phải tạo bên trong `.md/scratch/`.

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
>    ```
