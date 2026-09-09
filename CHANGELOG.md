# 📜 VvC Second Brain — Changelog

Lịch sử thay đổi kiến trúc pipeline. Xem `AGENTS.md` cho quy tắc hiện hành.

---

## v8.12.4 — YouTube Visual Extractor v12.0: Dynamic Storyboard & 1-Pass Multimodal Judge
Nâng cấp toàn diện cơ chế trích xuất hình ảnh video YouTube (`visual_extractor.py`) lên v12.0:
- **Dynamic Storyboard Selection**: Tự động tính toán diện tích tile ($W \times H$) lớn nhất thay cho chuỗi formats tĩnh, luôn ưu tiên `sb0` (320x180 px = 57.600 px²/tile, gấp 16 lần `sb2` 80x45 px).
- **Invariant Slicing & Timestamp Math**: Dùng kích thước cố định `tile_w`, `tile_h` loại bỏ biến dạng cắt méo ở fragment cuối và đồng bộ chuẩn xác timestamp (`actual_ts = global_tile_idx * tile_duration`), triệt tiêu độ lệch pha 120s.
- **Robust Progressive & DASH Selector**: Nâng cấp selector `'bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/best[height<=720]/b/18/bestvideo/best'` hỗ trợ hoàn hảo progressive streams (format 18) lẫn DASH 720p.
- **1-Pass Multimodal LLM-as-Judge & Self-Healing**: Nhận diện keyframes và sinh trực tiếp JSON alt-text ngay trong phiên nhìn ảnh. Bổ sung công cụ `heal_video_frames.py` quét và tự động chữa lành các frame suy thoái toàn vault.

## v8.12.3 — YouTube 403 CDN Defense & Constitution LLM Routing Sync
Đồng bộ hóa kiến trúc định tuyến mô hình và tăng cường năng lực bóc tách video YouTube:
- **YouTube 403 CDN Signature Fix**: Nâng cấp cận dưới `yt-dlp>=2026.8.19` trong `requirements.txt`. Khắc phục triệt để lỗi `HTTP 403 Forbidden` do cơ chế n-sig mới của YouTube, giải phóng hoàn toàn luồng tải HD 720p và ngăn pipeline suy thoái về thumbnail thô 320x180.
- **Constitution Routing Sync**: Đồng bộ bảng Model Routing trong `AGENTS.md` (§8), `scripts/GEMINI.md`, và `scripts/README.md` theo cấu hình thực tế `gemini-3.8-flash-high` cho cả Map (trích xuất) và Reduce (tổng hợp note).
- **Cognitive Allocation Enforcement**: Phân định chính xác vai trò Claude Opus 4.6 Thinking cho Strategic Arbitration / Architecture Planning và Gemini 3.8 Flash High cho Autonomous Compiler loops.

## v8.12.2 — Antigravity CLI Integration & Full Pipeline Map-Reduce Acceleration
Nâng cấp toàn diện cơ chế gọi LLM và đồng bộ hóa pipeline Map-Reduce với Antigravity CLI (agy.exe):
- **Native Antigravity JSON Bridge**: Nâng cấp `call_gemini_cli` thành native client giao tiếp với `agy.exe` qua `--output-format json` và `--disable-slash-commands`. Tự động bóc tách sạch 100% thinking tokens, triệt tiêu rủi ro rò rỉ `<think>` vào Concept Notes, đồng thời thu thập chi tiết telemetry hiệu năng.
- **Pipeline Map-Reduce Acceleration**: Đồng bộ hóa toàn bộ chu trình Map (trích xuất ý tưởng nguyên tử) và Reduce (tổng hợp Concept Note) trên `gemini-3.8-flash-high`. Tận dụng tối đa Context Caching (8.155 tokens) giúp tăng tốc độ trích xuất Map từ 96s xuống ~7.9s và hoàn tất Note trong ~3-5s.
- **Cognitive Labor Division**: Phân định rõ ràng vai trò các tầng model: Gemini 3.8 Flash High cho băng chuyền tự động tốc độ cao (Map & Reduce), và bảo toàn Claude Opus 4.6 Thinking cho các tác vụ tương tác chiến lược cấp cao (Command.md, Macro-Synthesis topics/, Semantic Merger Arbitrator).

## v8.12.1 — Sequential Hook Overlap Prevention in Batch Processing
Nâng cấp và cải tiến toàn diện quy trình xử lý batch để loại bỏ hiện tượng trùng lặp trích dẫn giữa các trang liền kề:
- **Sequential Hook Exclusion**: Khởi tạo danh sách loại trừ `exclude_hooks` động trong scope của một batch. Trích xuất blockquote (Evidence Hook) từ các Concept Note được tạo thành công, làm sạch qua hàm helper `_clean_blockquote_quote()`, và append vào danh sách loại trừ tuần tự.
- **Dynamic CRITICAL DIRECTIVE Injection**: Tự động sinh chỉ thị loại trừ nghiêm ngặt `[CRITICAL DIRECTIVE: Để tránh trùng lặp trích dẫn...]` và ghép nối trực tiếp vào tham số `highlighted` cho các lượt gọi synthesis tiếp theo, định hướng LLM chọn các trích dẫn độc lập khác trong trang.
- **Test Hardening & Performance Optimization**: Bổ sung bộ kiểm thử `scripts/tests/test_hook_exclusion.py` bao phủ hoàn chỉnh hàm helper làm sạch và luồng dữ liệu loại trừ trong batch. Áp dụng mock JIT và cô lập Index Rebuilding giúp tối ưu tốc độ chạy test từ **32.84 giây xuống còn 0.42 giây** (nhanh hơn 80 lần) mà vẫn đảm bảo 100% độc lập, không kết nối mạng.

## v8.12.0 — JIT Image Alignment & Adaptive Naming
Nâng cấp và cải tiến toàn diện quy trình căn chỉnh ảnh và bối cảnh hóa:
- **JIT Image Alignment (Bước 1)**: Tự động phát hiện và trích xuất ảnh sơ đồ/hình vẽ gốc sắc nét từ Nhà xuất bản trong thư mục `_MD/` dựa trên vị trí khớp của dải Ground Truth (trong phạm vi ±800 ký tự). Nhúng liên kết ảnh `![[image.webp]]` trực tiếp vào cuối `## Core Idea` (trước phần Ground Truth) để tối ưu hóa trải nghiệm đọc thẩm mỹ song phương.
- **Cơ chế Adaptive Naming (Đặt tên Thích ứng Thông minh)**: Tự động phân tích tên ảnh thô để đặt tên file đính kèm một cách khoa học: giữ nguyên tên gốc chuyên nghiệp của NXB nếu đã chứa từ khóa sách; bổ sung đầy đủ ngữ cảnh `[book]_[chapter]_[page]_[original_name]` đối với các ảnh có tên thô sơ (như `00003.png`), đảm bảo định danh duy nhất trên toàn vault và tự thuyết minh bối cảnh rõ ràng.
- **Tối ưu hóa & Quản lý Tài nguyên**: Tự động nén WebP (kích thước tối đa 1536px, chất lượng 80) đối với tất cả ảnh gốc trích xuất từ sách, lưu trữ ngăn nắp trong thư mục assets riêng của từng cuốn sách (`04 - Permanent/sources/assets/[book_name]/`), loại bỏ trùng lặp nội dung JIT.
- **Test Hardening**: Bổ sung bộ kiểm thử chuyên biệt `tests/test_jit_images.py` phủ 100% các kịch bản định danh thích ứng, bỏ qua ảnh decorative, và chèn vị trí nhúng chuẩn.

## v8.11.0 — Gateway JIT Environment Loading & Context Metadata Protection
Nâng cấp kiến trúc bảo mật cấu hình và phòng ngự dữ liệu hệ thống:
- **JIT Environment Loading (H4)**: Loại bỏ hoàn toàn API key hardcode trong `config.yaml`. Triển khai cơ chế nạp biến môi trường JIT cục bộ thủ công bằng Python thuần (KISS) từ file `.env` tại thư mục `scripts/` và thư mục gốc của Vault, bảo mật tuyệt đối qua `.gitignore`.
- **Context Metadata Protection (H5)**: Nâng cấp hàm `enrich_book_context()` trong `pipeline/map_reduce.py` để tách và ghép nối phòng ngự dải YAML metadata header gốc của file `_context.txt`, loại bỏ hoàn toàn rủi ro bị LLM ghi đè hoặc làm hỏng các đường dẫn hệ thống vĩ mô.
- **Obsidian Graph Healing & Clean (C1, C3, L7, L10)**: Sửa lỗi lệch pha `epub_file` cho 7 chương của Reinventing the Organization (C1); Xóa bỏ hoàn toàn workspace ma `BigBIM_Source` (C3); Giải phóng 22.6MB đĩa từ tệp backup rác `.npz.bak` (L7); Tích hợp giải thuật **Token-based Fuzzy Matching [L10]** trong `_sync_source_note()` để xử lý hoàn hảo các tên workspace bị cắt ngắn đuôi khi đồng bộ mục lục.
- **Test Hardening**: Bổ sung 3 test cases mới nâng tổng số test suite lên 171 tests. 171/171 tests passed 100% hoàn hảo và an toàn.

## v8.10.0 — Operational Separation & Ubiquitous Language (AI-Friendly Codebase)
Nâng cấp và cải tiến toàn diện codebase dự án đạt chuẩn AI-Friendly/Agent-Ready:
- **Operational Separation (Tách biệt vận hành)**: Chuyển toàn bộ các tệp log vận hành (`*.log`) về thư mục tập trung `scripts/logs/` và toàn bộ các tệp trạng thái vận hành (`.dump_state.json`, `.processed_urls.json`, `.rejected_stubs.json`, `.subsume_journal.jsonl`, `_embedding_index.npz`) về thư mục bảo mật `scripts/.state/`. Cấu hình tự động khởi tạo thư mục qua VaultConfig và cập nhật `.gitignore` loại bỏ tuyệt đối ô nhiễm dữ liệu lên cloud/git.
- **Architecture Decomposition (Phân rã kiến trúc)**: Monolithic `services/brain_dump.py` và `services/youtube_transcript.py` được phân rã thành các gói module chuyên biệt (`services/brain_dump/`, `services/youtube/`) kết hợp với quản lý Registry Prompts tập trung tại `core/prompts/` giúp tăng tính tái sử dụng và type safety.
- **Type Safety & Ubiquitous Language (Đồng bộ ngôn ngữ nhất quán)**: Áp dụng Strict Type Hints trên toàn bộ codebase với file định nghĩa tập trung `core/types.py`. Đồng bộ hóa thuật ngữ: đổi `gt` thành `ground_truth`, `fm` thành `frontmatter`, `workspace_path` thành `workspace_dir` để khớp hoàn hảo trên mọi module.
- **Test Hardening (Củng cố kiểm thử)**: Nâng tổng số lượng unit tests lên 167 tests, nâng độ phủ coverage toàn bộ hệ thống lên $\ge 50\%$ (phần core chính đạt 70-100% coverage), 167/167 tests passed 100% hoàn hảo và an toàn tuyệt đối.

## v8.9.10 — Next.js Custom Image Extraction & Native SVG Support
Nâng cấp cơ chế Smart Filter trong `services/article_images.py`. Tự động phát hiện và trích xuất các hình vẽ/sơ đồ giá trị cao từ các component React/Next.js tùy chỉnh như `<ThemeImage>` (phổ biến trên các blog công nghệ hiện đại) bằng Regex hiệu năng cao. Hỗ trợ lưu trữ định dạng ảnh vector `.svg` bản gốc sắc nét bằng cách ghi trực tiếp byte thô, bỏ qua Pillow và bộ lọc dung lượng tối thiểu đối với tệp SVG. Tất cả 30/30 tests passed.

## v8.9.9 — Consolidated Pruning & Smart Core Size
Nâng cấp cơ chế 3-Tier Merge Control trong `pipeline/semantic_merger.py`. Thay thế cơ chế chặn cứng khi ghi chú cũ có $\ge 4$ hooks bằng chế độ **Consolidated Pruning** (Tỉa cành củng cố) kết hợp với tính toán kích thước thông minh. Lọc bỏ trích dẫn thô để tính dung lượng lõi (`core_size`). Cho phép hợp nhất nếu `core_size` $\le 6,000$ bytes và `file_size` $\le 10,000$ bytes, giúp tránh phân mảnh khái niệm trong khi vẫn ngăn ngừa God Notes. 17/17 tests passed.

## v8.9.8 — Topic Articles (`04 - Permanent/topics/`)
Thêm §4.6 Topic Articles vào Constitution. AI-generated long-form essays, architecture reviews, và research reports được lưu tự động vào `04 - Permanent/topics/` (snake_case, `type: topic`). Auto-save rule: bài viết >500 words PHẢI có bản lưu trong vault. Cập nhật directory tree và GEMINI.md.

## v8.9.7 — Callout Image Metadata & Aesthetics Upgrade
Nâng cấp kiến trúc thể hiện siêu dữ liệu trong tài liệu (Human-AI Alignment in Document Aesthetics). Sửa đổi hàm `format_image_metadata` trong `services/article_images.py` để tự động đóng gói danh sách các marker hình ảnh kỹ thuật `[IMG:...]` thô bên trong một Obsidian Callout dạng đóng/mở (`> [!info]- 🖼️ ...`). Thiết kế này bảo toàn 100% ngữ cảnh tri thức và bối cảnh (alt-text) ảnh tập trung cho RAG AI Agent phân tích khi trích xuất khái niệm, đồng thời che giấu siêu dữ liệu thô để tối ưu hóa tối đa trải nghiệm thị giác của con người khi xem ghi chép trên Obsidian. 119/120 tests passed.

## v8.9.6 — Article Image Extraction (Local WebP)
Tự động trích xuất hình ảnh có giá trị tri thức từ bài báo web (articles) khi xử lý URL trong `Brain_Dump.md`. Module mới `services/article_images.py` sử dụng Smart Filter (BeautifulSoup) loại bỏ noise images (logo, icon, tracker, navigation, sidebar) và tải đồng thời (ThreadPool, 5 workers) tối đa 20 ảnh/bài, nén WebP (Q=80, max 1536px), lưu tại `04 - Permanent/sources/assets/<domain>/`. LLM tự động nhúng `![[image.webp]]` vào `## Core Idea` trong Concept Notes. Zero-touch activation cho articles (không cần `/visual`). 113/113 tests passed.

## v8.9.5 — Video Visual Extraction
Tích hợp tính năng trích xuất nội dung trực quan (Video Visual Extraction) từ YouTube. Hỗ trợ cú pháp điều khiển `/visual` trong `Brain_Dump.md` để tự động tải video chất lượng thấp, trích xuất hình ảnh (1 frame/10 giây, giới hạn tối đa 30 frames phân bố đều) qua FFmpeg, và sử dụng LiteLLM Gateway Multimodal API để tạo mô tả trực quan (slide, sơ đồ, bảng biểu). Hợp nhất âm thanh (transcription) và hình ảnh (visual progression) thành tệp nguồn Zettelkasten chất lượng cao mà không phá vỡ JIT Deduplication. 104/104 tests passed.

## v8.9.3 — Source File Deduplication & Link Healer
Triển khai công cụ `deduplicate_sources.py` tự động quét, sao lưu phòng thủ, và chuyển hướng an toàn 100% liên kết chéo của 24 Concept Notes trỏ tới các nguồn trùng lặp trên đĩa về 3 Nguồn chính Canonical. Tự động hợp nhất Registry và rebuild đồ thị Obsidian Graph sạch sẽ hoàn toàn qua Wiki Maintenance JIT. 103/103 tests passed.

## v8.9.2 — Historic URL Registry Hydration
Triển khai công cụ `hydrate_url_registry.py` lập chỉ mục ngược (Inverted Index Map) tối ưu I/O siêu tốc (~3.9s), tự động quét và nạp thành công 75 URL lịch sử và hàng trăm Concept Notes vào `.processed_urls.json` giúp Vault đạt trạng thái miễn dịch trùng lặp tri thức 100% với cơ chế JIT Auto-Feedback 12ms.

## v8.9 — URL Deduplication & Re-processing Guard
Tích hợp JIT URL Deduplication Registry cục bộ (`.processed_urls.json`) giúp chặn trùng lặp URL JIT và sinh Auto-Feedback chỉ dẫn tới các note cũ mà không gọi LLM/cào web lại. Hỗ trợ hệ thống từ khóa ghi đè (`xử lý lại`, `/force`...) để chủ động cào lại và hợp nhất an toàn thông qua Semantic Knowledge Merger (v8.6). Triển khai Single-Write Commit giảm tối đa xung đột đồng bộ file `Brain_Dump.md`. 16/16 test services passed.

## v8.8 — Vault Mount Resilience
Tích hợp JIT Google Drive mount readiness guard cho `book_ingest.py` trên startup. Khi hệ thống khởi động và Google Drive chưa mount kịp, daemon sẽ tự động chờ tối đa 150 giây thay vì bị crash ngay lập tức do lỗi `FileNotFoundError`.

## v8.7 — WebP Archive Compression
`_archive_image()` trong `post_process.py` chuyển từ `shutil.copy()` sang nén Pillow WebP (RGB, 1536px max, quality=80). Giảm dung lượng `99 - Archive/` từ **2.19GB xuống ~107MB** (~95%). Fallback tự động về raw copy nếu Pillow gặp lỗi. 54/54 tests passed.

## v8.6 — 3-Tier Merge Control & SUBSUME
Thay thế Hard Limit tĩnh 10KB bằng hệ thống kiểm soát hợp nhất đa tầng: **Tier 1** Hook Count Gate (≥4 hooks → SEPARATE), **Tier 2** Dynamic Size Limit (P95×1.3 ~7.7KB), **Tier 3** LLM Arbitrator (MERGE/SEPARATE/SUBSUME). SUBSUME logs to `.subsume_journal.jsonl`.

## v8.5 — Sleep Consolidation, Semantic Merger & Dynamic Limits
Scan-Once Sleep Architecture. AI Gateway Embeddings (7.5x speed). Semantic Knowledge Merger (Cosine 0.88 + Arbitrator + cross-linking). Proportional Dynamic Limit (Brain Dump: 1-3 → 8-18 concepts based on input size).

## v8.4 — Ingestion Pipeline & UTF-8 Stdout Hardening
Nới lỏng Watchdog prefix hỗ trợ `_toc.jpg`, `_cover.jpg`. Robust `null`/`None` handling cho `_toc.json`. Chuẩn hóa 188 Concept Notes. Windows Stdout UTF-8 fix.

## v8.3 — Bilingual Standard & Secondary Citation
Evidence Hook **BẮT BUỘC tiếng Việt**. Citation Line kèm wiki-link. Ground Truth **BẮT BUỘC tiếng Anh nguyên bản**.

## v8.0 — Canonical `_toc.json` Schema
Hợp nhất naming (`book_title_en` → `book_title_original`), enforce `.md` extension, chuẩn hóa `page_start`/`page_end` luôn `int | null`.

## v7.7 — Concept Note Format (Cognitive Flow)
Body order: Evidence Hook → Citation Line → `## Core Idea` → `## 📖 Ground Truth` → `---` → `## References`.

## v7.6 — Dual-Source Frontmatter
Thêm `source_page/chapter`, `ground_truth_page/chapter`, `people`, `companies`, `status`.

## v7.5 — Architecture Hardening (3 Systemic Fixes)
Reverse Metadata Sync, File Stability Guard (1.5s), Temporal Batching Engine (10s cooldown).

## v7.4.2 — Brain Dump Map-Reduce
2-step Map-Reduce: Extraction (reasoning) → Synthesis (synthesis). Dynamic Limit 3-12 concepts.

## v7.4 — Modular Architecture
Refactored God Objects into micro-modules. Single Responsibility Principle. Modular LLM Package.

## v7.2.1 — Diagram Typesetting Engine & Clean MOC
4 deterministic layout engines (Sugiyama, Radial, Cycle, Matrix). Academic Grayscale Theme. Text Auto-Sync. Zero-Concept MOC Filtering.
