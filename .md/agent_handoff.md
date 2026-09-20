# 🤝 Báo cáo Bàn giao Context Công nghệ (v8.15.10) — VvC Second Brain

> Tệp tin này được thiết lập tại `.\.md\agent_handoff.md` theo đúng quy trình bàn giao Macro (Phiên) được thống nhất giữa Người dùng và AI Agent.
> Mục tiêu là giúp AI Agent tiếp theo nạp bối cảnh và tiếp quản dự án JIT (Just-In-Time) 100% thành công mà không cần hỏi lại người dùng.

---

## 1. Bản đồ Trạng thái Hệ thống (System State Map)

* **Phiên bản hiện tại:** `v8.15.10 — Antigravity Multi-Tier Autonomous Engine`
* **Trạng thái Git:** Sạch sẽ. Commit mới nhất: `1c1e78b` — `feat(infra): add windows runner control scripts and sync log.md in setup_spark`
* **Tổng số Concepts trong Vault:** **2,635 tệp** (236 Sources, 232 Source MOCs, 34 Domain MOCs).
* **Trạng thái CSDL Sơ đồ (`figure_inventory.json`):** **100% Sẵn sàng** (106 hình vẽ, đầy đủ Caption + Alt-text cho RAG).
* **Kết quả Kiểm thử:** **522/522 tests passed thành công 100%** (0 regressions).
* **Hạ tầng 24/7 (systemd trên Server Spark Ubuntu Linux aarch64):**
  - `vvc-daemon.service` (PID 69830) — active (Watchdog xử lý Command.md, Brain_Dump.md, Fleeting OCR).
  - `vvc-book-ingest.service` (PID 3582641) — active (Watcher sách mới EPUB/PDF trong `03 - Resources/books`).
  - `vvc-gdrive-mount.service` (PID 3566553) — active (Rclone VFS mount 2 chiều với Google Drive).

---

## 2. Các thay đổi trong phiên v8.15.10 (21/09/2026)

| Loại | Thay đổi | Chi tiết |
| :--- | :--- | :--- |
| **Fix/Refactor** | `scripts/config.yaml` & `gemini_client.py` | Chuyển `text_correction_model` sang `gemini-3.8-flash-low` (~1.8s - 2.8s/call). Thêm filter `-lite` vào `is_antigravity_cli_supported()` bảo vệ CLI Tier 1. Bổ sung test case `test_cli_artifact_ingestion.py` (12/12 passed). |
| **Infra** | `run_agent_windows.bat`, `stop_agent_windows.bat` | Bổ sung runner control scripts cho Windows worker và cập nhật nhật ký cấu hình trong `setup_spark/log.md`. Commit `1c1e78b`. |
| **Synthesis** | `00 - Maps of Content/Command.md` | Xử lý thành công đề tài *"Thuật Toán Tối Ưu Hóa 5 Bước Của Elon Musk x Harness Engineering"* bằng **Claude Opus 4.6 Thinking** (121k in / 10k out, 207s). Tạo topic note `thuat_toan_toi_uu_hoa_nam_buoc_va_ky_nghe_kien_truc_phan_mem_ai_native_mot_khung_phan_tich_lien_nganh.md` (19,433 ký tự, 13 concepts linked). |
| **Playbook** | `ai_eos_playbook_master.md` | Tích hợp bài luận mới thành Phụ lục Kỹ thuật 10A (*Technical Appendix 10A*), liên kết chéo Chương 10, cập nhật backlog `y_tuong_bai_viet_tiem_nang.md`. Biên dịch lại toàn bộ `ai_eos_playbook_full_manuscript.md` (41,160 từ, 238,003 ký tự). |
| **Consolidation** | `scripts/close_session.py` & Graph Healing | Chạy đóng phiên: tự động vá 2 stubs, cập nhật `Weekly_Synthesis.md` (2026-09-21). Bổ sung alias `agi` / `AGI` cho `dinh_nghia_va_moc_thoi_gian_dat_agi.md` theo chuẩn **Alias-First Resolution (AGENTS.md §4.3)** để vá dứt điểm broken body link `agi\`. |

---

## 3. Bài học cốt lõi & Phòng ngừa (Lessons Learned)

1. **Antigravity CLI Model Constraints**:
   - `agy` CLI chỉ nhận các model có reasoning effort suffix (`gemini-3.8-flash-{low,medium,high}`, `gemini-3.1-pro-...`, `claude-opus-4-6-thinking`).
   - Các model Google AI Studio dạng `-lite` (`gemini-3.1-flash-lite-preview`) không được Antigravity CLI hỗ trợ và trả về exit code 1. Phải luôn có lớp lọc `is_antigravity_cli_supported()` để tự động fallback sang LiteLLM Gateway hoặc Copilot CLI.
2. **Hiệu năng của Gemini 3.8 Flash Low**:
   - Cấu hình `gemini-3.8-flash-low` cho các tác vụ sửa chính tả, định dạng bảng, vá stubs giảm thời gian xử lý từ >10s xuống còn <3s mà vẫn giữ độ chính xác tuyệt đối.
3. **Autonomous Artifact Ingestion**:
   - Khi chạy Claude Opus với prompt dài chuyên luận, `agy.exe` tạo tệp artifact trên đĩa thay vì in trực tiếp ra stdout. Lớp client `gemini_client.py:_resolve_cli_artifact_content` đã tự động phát hiện URI `file:///...` và nạp toàn văn thành công mà không làm gián đoạn pipeline.

---

## 4. Chỉ dẫn JIT nạp Context cho AI kế nhiệm (Memo for next Agent)

> [!IMPORTANT]
> **Hãy thực hiện các bước sau để tiếp quản dự án lập tức:**
> 1. Đọc kỹ hiến pháp toàn cục tại [AGENTS.md](file:///home/vvc/VvC_Notes/AGENTS.md) và [GEMINI.md](file:///home/vvc/VvC_Notes/GEMINI.md) để nắm cấu trúc 3 tầng, YAML schema, quy tắc Zettelkasten và công thái học đồ họa v8.15.10.
> 2. Kiểm tra trạng thái 3 tiến trình nền systemd trên Linux:
>    ```bash
>    systemctl --user status vvc-daemon.service vvc-book-ingest.service vvc-gdrive-mount.service
>    ```
> 3. Kiểm thử toàn diện test suite:
>    ```bash
>    /home/vvc/VvC_Notes/scripts/.venv/bin/pytest scripts/tests/
>    ```
> 4. **Stale Daemon Invariant**: Nếu có chỉnh sửa code trong `scripts/` hoặc `scripts/config.yaml`, BẮT BUỘC phải khởi động lại daemon trước khi test thực địa:
>    ```bash
>    systemctl --user restart vvc-daemon.service
>    ```
