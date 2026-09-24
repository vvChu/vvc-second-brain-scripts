# 🧠 VvC Second Brain — Mental Model & Kiến Trúc Tổng Thể (v8.15.13)

> **Tài liệu tham chiếu kỹ thuật (Technical Pointer & Living Architecture Reference)**  
> **Tuân thủ quy chuẩn**: Global Rule §1 (Knowledge Projects Central KB) & ADR-0057 / ADR-0058  
> **Master Canonical Topic Note**: [[kien_truc_va_mental_model_vvc_second_brain|04 - Permanent/topics/kien_truc_va_mental_model_vvc_second_brain.md]]  
> **Sơ đồ Excalidraw 16:9**: [[vvc_second_brain_architecture.excalidraw.md|03 - Resources/attachments/vvc_second_brain_architecture.excalidraw.md]]  

---

## 1. Bản Tóm Tắt Kỹ Thuật (Executive Abstract)

Kho tri thức cá nhân **VvC Second Brain** vận hành theo mô hình **LLM Compiler Pattern** (Andrej Karpathy, 2026) đóng vai trò là một Hệ Điều Hành Tri Thức Tự Trị ("Zero-Touch" LLM OS):
- **Phân định vai trò**: Con người là *Source Provider* (chụp ảnh highlight sách, nghe podcast, xem YouTube, ghi nhanh vào `Brain_Dump.md`), AI Agent và hệ thống daemons nền là *Compiler & Librarian*.
- **3 Đột phá so với Karpathy gốc**:
  1. *Verifiable Ground Truth RAG*: Khử ảo giác bằng Chapter-Scoped BM25 đối chiếu trực tiếp bản gốc tiếng Anh, cưỡng chế cặp đối xứng **Evidence Hook (VN)** + **Ground Truth Verbatim (EN)** trên từng Concept Note.
  2. *Noise Gating & Chống Hồi Sinh*: Lọc nhận thức `_is_meaningful_dump`, lưu trạng thái con trỏ byte `.dump_state.json`, và ngăn trùng lặp URL qua `.processed_urls.json`.
  3. *Closed-Loop Compounding Feedback*: Các câu trả lời sâu sắc trong `Command.md` ($\ge 2500$ ký tự) tự động chuyển hóa thành Topic Note trong `04 - Permanent/topics/`, lập tức quay lại làm giàu ngữ cảnh RAG cho các câu hỏi tương lai.
- **Bất biến Vận hành Sống còn (Active-Passive Single-Active Runner)**: Máy chủ Linux **Server Spark** (`spark-CCBA aarch64`) là Primary Host chạy 24/7. Máy tính Windows chỉ đóng vai trò Client (Obsidian UI). Khi chạy runner cục bộ trên Windows, bắt buộc phải tắt daemon trên Spark qua `stop_windows_runner.cmd` để tránh hiện tượng chia cắt não (Split-Brain) gây xung đột tệp qua Google Drive.
- **Hạ tầng Lưu trữ Rclone FUSE**: Sử dụng `vvc-gdrive-mount.service` với Rclone FUSE VFS Full Cache (cache 10GB, dir-cache 72h), loại bỏ hoàn toàn GVFS cũ.

---

## 2. Bản Đồ Mã Nguồn 8 Trụ Cột Kiến Trúc (Architecture Seams Map)

| Trụ Cột | Trách Nhiệm Kỹ Thuật | Tệp Mã Nguồn / Cấu Hình Chính | Khớp Nối (Deep Seams) |
| :--- | :--- | :--- | :--- |
| **P1. Vận Hành & Single Runner** | Điều phối tiến trình, chống Split-Brain, quản lý queue và locks. | [`scripts/daemon.py`](file:///home/vvc/VvC_Notes/scripts/daemon.py)<br/>[`scripts/core/file_lock.py`](file:///home/vvc/VvC_Notes/scripts/core/file_lock.py)<br/>[`scripts/start_windows_runner.cmd`](file:///home/vvc/VvC_Notes/scripts/start_windows_runner.cmd) | `CrossProcessFileLock`<br/>`restart_existing_daemons()` |
| **P2. Phân Tầng Lưu Trữ** | Rclone VFS mount, cách ly state/logs cục bộ khỏi cloud. | [`~/.config/systemd/user/vvc-gdrive-mount.service`](file:///home/vvc/.config/systemd/user/vvc-gdrive-mount.service)<br/>[`scripts/config.yaml`](file:///home/vvc/VvC_Notes/scripts/config.yaml) | `scripts/.state/`<br/>`scripts/logs/` |
| **P3. Hạt Nhân Tri Thức** | Chuẩn Concept Note Canonical v8.3, Đa Bằng Chứng, Consolidated Pruning. | [`scripts/core/frontmatter.py`](file:///home/vvc/VvC_Notes/scripts/core/frontmatter.py)<br/>[`scripts/core/prompts/pipeline.py`](file:///home/vvc/VvC_Notes/scripts/core/prompts/pipeline.py) | `build_frontmatter()`<br/>`parse_frontmatter()` |
| **P4. Đường Ống Biên Dịch** | Chuỗi 5 giai đoạn: OCR $\rightarrow$ Chapter BM25 $\rightarrow$ Synthesis $\rightarrow$ Self-Correction $\rightarrow$ Merger. | [`scripts/pipeline/image_processor.py`](file:///home/vvc/VvC_Notes/scripts/pipeline/image_processor.py)<br/>[`scripts/pipeline/ground_truth.py`](file:///home/vvc/VvC_Notes/scripts/pipeline/ground_truth.py) | `process_book_image()`<br/>`match_ground_truth()` |
| **P5. Thu Nạp Đa Kênh** | YouTube 4-tier Native ASR & Storyboard pHash, Podcast Faster-Whisper, Command JIT. | [`scripts/services/youtube/`](file:///home/vvc/VvC_Notes/scripts/services/youtube/)<br/>[`scripts/services/podcast.py`](file:///home/vvc/VvC_Notes/scripts/services/podcast.py)<br/>[`scripts/services/command/`](file:///home/vvc/VvC_Notes/scripts/services/command/) | `fetch_transcript_hierarchy()`<br/>`extract_video_frames()` |
| **P6. Lưới AI Thích Ứng** | Lưới định tuyến 4 tầng, Circuit Breaker 503, WinError 206 stdin streaming, CLI artifact ingestion. | [`scripts/core/llm/__init__.py`](file:///home/vvc/VvC_Notes/scripts/core/llm/__init__.py)<br/>[`scripts/core/llm/gemini_client.py`](file:///home/vvc/VvC_Notes/scripts/core/llm/gemini_client.py) | `call_llm()`<br/>`consume_gateway_downgraded()` |
| **P7. Điều Phối Artifacts** | Lazy ArtifactEngine (6 async workers), Ngưỡng Vàng Lai 16:9, Mermaid 4 Patterns. | [`scripts/services/worker_dispatcher.py`](file:///home/vvc/VvC_Notes/scripts/services/worker_dispatcher.py)<br/>[`scripts/services/diagram_base.py`](file:///home/vvc/VvC_Notes/scripts/services/diagram_base.py) | `dispatch_artifacts()`<br/>`spawn_worker()` |
| **P8. Chu Trình Tự Hồi Phục** | Hợp nhất Cosine $\ge 0.88$ (SUBSUME/MERGE), Mtime 2 cấp độ, Weekly Sleep Consolidation. | [`scripts/pipeline/semantic_merger.py`](file:///home/vvc/VvC_Notes/scripts/pipeline/semantic_merger.py)<br/>[`scripts/sleep.py`](file:///home/vvc/VvC_Notes/scripts/sleep.py) | `merge_concept()`<br/>`run_sleep_consolidation()` |

---

## 3. Hạ Tầng & Dịch Vụ Nền 24/7 (Server Spark Linux aarch64)

### 3.1. Cấu hình Systemd User Units
Trên Server Spark (`100.83.192.30`), 4 dịch vụ nền tự trị quản lý toàn bộ vòng đời của Vault:

```bash
# Trạng thái dịch vụ nền
systemctl --user status vvc-gdrive-mount.service   # Rclone FUSE mount Google Drive
systemctl --user status vvc-daemon.service         # Main Watchdog & Command Coordinator
systemctl --user status vvc-book-ingest.service    # Watcher sách mới (EPUB/PDF)
systemctl --user status vvc-sleep.timer           # Weekly Consolidation Timer (02:00 AM Sun)
```

### 3.2. Cấu hình AI Gateway & Local CLI
- **Antigravity CLI Driver cục bộ (`agy`)**: Tier 1 Priority cho `claude-opus-4-6-thinking` (suy luận sâu) và `gemini-3.8-flash-high` (tổng hợp concept).
- **AI Gateway trên Server Spark**:
  - `http://100.83.192.30:8045/v1`: Antigravity OpenAI Proxy (Claude Opus / Sonnet Thinking).
  - `http://100.83.192.30:8090/v1`: LiteLLM Gateway (22 models, Whisper V3 Turbo, Text Embedding 3072-dim).
- **Local Whisper Server**: Cổng 8008 trên GPU Grace Blackwell GB10 phục vụ ASR siêu tốc không phụ thuộc đám mây.

---

## 4. Chỉ Dẫn Dành Cho AI Agent Tiếp Quản (JIT Onboarding Memo)

1. **Đọc Toàn Văn Luận Án Kiến Trúc**:
   - Truy cập ngay [[kien_truc_va_mental_model_vvc_second_brain|04 - Permanent/topics/kien_truc_va_mental_model_vvc_second_brain.md]] để nắm trọn vẹn 8 Trụ cột, lý luận First Principles, và các ví dụ thực tế.
2. **Tuân Thủ Bất Biến Stale Daemon**:
   - Khi chỉnh sửa bất kỳ tệp nào trong `scripts/` hoặc `scripts/config.yaml`, BẮT BUỘC phải hạ daemon cũ trước khi kiểm thử:
     ```bash
     scripts/.venv/bin/python scripts/daemon.py --restart
     ```
3. **Tuân Thủ Quy Chuẩn Công Thái Học Thị Giác (v8.15.10)**:
   - Sơ đồ $\ge 3$ tầng hoặc $\ge 9$ nodes $\rightarrow$ Dùng Excalidraw 16:9 (`![[...excalidraw.md|100%]]`) kèm bảng đặc tả ma trận Markdown.
   - Sơ đồ nhỏ $\le 8$ nodes $\rightarrow$ Dùng Mermaid Academic Grayscale với pipe syntax `===>|"label"|`, toán tử Unicode `≥`/`≤`, và cô lập thực thể thoát ngoặc đơn HTML strictly bên trong Mermaid.
   - Tuyệt đối CẤM định dạng code-pill wikilink (cấm bọc backticks quanh wikilinks) trên mọi bề mặt Markdown.

---

## 5. Lệnh Kiểm Thử Toàn Trình (Verification Gate Suite)

```bash
# 1. Kiểm tra ngân sách mã nguồn Spoke Cleanliness (Đạt chuẩn 12/15 scripts)
python3 scripts/check_spoke_cleanliness.py

# 2. Kiểm thử Frontmatter, Prompts và Model Resolver
/home/vvc/VvC_Notes/scripts/.venv/bin/pytest scripts/tests/test_frontmatter.py scripts/tests/test_prompts.py scripts/tests/test_model_resolver.py -q

# 3. Kiểm thử Command Flow, Multi-turn, Dispatcher và Semantic Merger
/home/vvc/VvC_Notes/scripts/.venv/bin/pytest scripts/tests/test_command_flow.py scripts/tests/test_command_multiturn.py scripts/tests/test_dispatcher.py scripts/tests/test_semantic_merger.py -q
```
