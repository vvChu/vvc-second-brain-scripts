# 🤝 Báo cáo Bàn giao Context Công nghệ (v8.15.10) — VvC Second Brain

> Tệp tin này được thiết lập tại `.\.md\agent_handoff.md` theo đúng quy trình bàn giao Macro (Phiên) được thống nhất giữa Người dùng và AI Agent.
> Mục tiêu là giúp AI Agent tiếp theo nạp bối cảnh và tiếp quản dự án JIT (Just-In-Time) 100% thành công mà không cần hỏi lại người dùng.

---

## 1. Bản đồ Trạng thái Hệ thống (System State Map)

* **Phiên bản hiện tại:** `v8.15.10 — Antigravity Multi-Tier Autonomous Engine`
* **Trạng thái Git:** Sạch sẽ. Commit mới nhất: `d854483` — `fix(daemon): exclude current pid during restart on linux` (ahead of origin by 2 commits: `136ab32`, `d854483`).
* **Tổng số Concepts trong Vault:** **2,677 tệp** (234 Transcripts, 237 Source MOCs, 35 Domain MOCs, **1,964 Vector Store Nodes**).
* **Trạng thái CSDL Sơ đồ (`figure_inventory.json`):** **100% Sẵn sàng** (106 hình vẽ, đầy đủ Caption + Alt-text cho RAG).
* **Kết quả Kiểm thử:** **7/7 unit tests youtube passed**, toàn bộ test suite ổn định.
* **Hạ tầng 24/7 (systemd / watchdog trên Server Spark Ubuntu Linux aarch64):**
  - `daemon.py` (PID 3380831) — active (Watchdog xử lý Command.md, Brain_Dump.md, Fleeting OCR).
  - `ffmpeg` binary: Đã symlink từ static `imageio_ffmpeg` binary vào `~/.local/bin/ffmpeg` (executable, aarch64).
  - `whisper-local` (Cổng 8008 trên GPU Grace Blackwell GB10): Sẵn sàng cho Zero-Cost Local Transcription.

---

## 2. Các thay đổi trong phiên v8.15.10 (22/09/2026)

| Loại | Thay đổi | Chi tiết |
| :--- | :--- | :--- |
| **Fix/Security** | `scripts/services/youtube/transcript.py` | Lọc bỏ `live_chat` và `live_chat_replay` khỏi danh sách subtitles. Thêm kiểm tra `is_live: True` ngắt sớm chống tải livestream vô tận. Bổ sung regex guard quét thẻ HTML/JS DOM rác (`<div`, `yt-formatted-string`) tự động hủy fetch trước khi đưa vào pipeline. Unit tests `test_youtube_transcript.py` passed 7/7. |
| **Fix/Daemon** | `scripts/daemon.py` | Vá lệnh `pkill` trên Linux trong hàm `restart_existing_daemons()` bằng cách thêm cờ loại trừ PID hiện tại (`$! != my_pid`), ngăn ngừa daemon tự kết liễu khi gọi `--restart`. |
| **Infra/FFmpeg** | `~/.local/bin/ffmpeg` | Tìm thấy binary aarch64 tĩnh sẵn có trong package `imageio_ffmpeg` và tạo symlink vào `~/.local/bin/ffmpeg` (nằm trong PATH của user `vvc`, không cần `sudo`), kích hoạt đầy đủ tính năng audio conversion và frame extraction. |
| **Synthesis** | `05 - Fleeting/Brain_Dump.md` | **(1)** Khắc phục và hấp thụ thành công bài giảng Jim Rohn (*"Nghệ Thuật Giao Tiếp"* - `q8jUr6HBn68`): tạo 8 Atomic Concepts, 1 Source Note, 1 Source MOC. **(2)** Hấp thụ thành công toàn văn sách nói *"Tư Duy Ngược"* (Nguyễn Anh Dũng, 3h04m, 172k ký tự phụ đề - `lUv9io4Eu60`): tạo 14 Atomic Concepts chuẩn v8.3, 1 Source Note (616 dòng). Nâng Vector Store index từ 1,942 lên 1,964 nodes. |
| **Visual Ingestion** | `scripts/services/youtube/visual_extractor.py` | Kiểm thử thực địa cơ chế phòng thủ 2 tầng: **(1) Podcast / Sách nói**: Thuật toán pHash gom 108 frames thành 3 frames duy nhất, AI Visual Judge thẩm định ảnh nền podcast và tự động từ chối (`KEY_FRAMES: []`), không làm rác kho assets. **(2) Video bài giảng kinh doanh (*Alex Hormozi - RGT7nNrvSek*)**: Thuật toán pHash nhận diện 31/34 frames độc lập, AI Judge chấp thuận 3 keyframes, `ffmpeg` trích xuất offline seek 3 ảnh HD WebP 1280x720 sắc nét lưu vào `04 - Permanent/sources/assets/video_frames/` và tự động dọn dẹp video tạm 181 MB. |

---

## 3. Bài học cốt lõi & Phòng ngừa (Lessons Learned)

1. **YouTube Scaffolding Captions & Livestream Pitfall**:
   - `yt-dlp` liệt kê `live_chat` trong danh sách `subtitles`. Nếu không lọc bỏ, pipeline sẽ tải về hàng nghìn dòng mã HTML/JSON giao diện web của YouTube và nhầm tưởng là lời thoại, gây lãng phí hàng chục nghìn tokens LLM và tạo ghi chú rác.
   - Livestream đang diễn ra (`is_live: True`) không có VOD captions tĩnh; nếu fallback sang audio download sẽ bị treo vô tận vì luồng livestream không có điểm kết thúc. Phải kiểm tra và ngắt sớm ngay từ đầu.
2. **Context-Aware Visual Judge & pHash Invariant**:
   - Không được lưu toàn bộ frames của video vào Vault. Phải qua 2 chốt chặn: Tầng 1 (Toán học pHash) loại bỏ các ảnh giống nhau; Tầng 2 (Nhận thức AI Vision) đánh giá mục đích sử dụng hình ảnh. Nếu chỉ là ảnh phong cảnh podcast/talking head, AI chủ động từ chối (`KEY_FRAMES: []`) để bảo vệ độ tinh gọn của đồ thị tri thức.
3. **Static Binary Symlink Pattern on Linux**:
   - Khi môi trường máy chủ Linux không có quyền `sudo`, việc kiểm tra các thư viện Python cài sẵn (như `imageio_ffmpeg`, `torch`, `triton`) thường phát hiện các binary hoặc shared libraries độc lập đã biên dịch sẵn cho kiến trúc mục tiêu (aarch64). Tạo symlink vào `~/.local/bin` là giải pháp nhanh, sạch và không can thiệp hệ thống.

---

## 4. Chỉ dẫn JIT nạp Context cho AI kế nhiệm (Memo for next Agent)

> [!IMPORTANT]
> **Hãy thực hiện các bước sau để tiếp quản dự án lập tức:**
> 1. Đọc kỹ hiến pháp toàn cục tại [AGENTS.md](file:///home/vvc/VvC_Notes/AGENTS.md) và [GEMINI.md](file:///home/vvc/VvC_Notes/GEMINI.md) để nắm cấu trúc 3 tầng, YAML schema, quy tắc Zettelkasten và công thái học đồ họa v8.15.10.
> 2. Kiểm tra trạng thái tiến trình nền daemon trên Linux:
>    ```bash
>    ps aux | grep daemon.py
>    ```
> 3. Kiểm thử unit test suite cho module YouTube:
>    ```bash
>    /home/vvc/VvC_Notes/scripts/.venv/bin/pytest scripts/tests/test_youtube_transcript.py
>    ```
> 4. **Stale Daemon Invariant**: Nếu có chỉnh sửa code trong `scripts/` hoặc `scripts/config.yaml`, BẮT BUỘC phải khởi động lại daemon:
>    ```bash
>    scripts/.venv/bin/python scripts/daemon.py --restart
>    ```
> 5. **Git Synchronization**: Nhánh local `main` hiện đang có 2 commit sửa lỗi sẵn sàng (`136ab32`, `d854483`). Chạy `git push origin main` khi người dùng yêu cầu đồng bộ lên GitHub remote.
