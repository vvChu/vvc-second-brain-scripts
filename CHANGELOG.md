# 📜 VvC Second Brain — Changelog

Lịch sử thay đổi kiến trúc pipeline. Xem `AGENTS.md` cho quy tắc hiện hành.

---

## v8.14.0 — Command Module & Worker Ecosystem Optimization (P0 + P1 Package)
Nâng cấp toàn diện hiệu năng và chất lượng tạo nội dung của Module Command theo chuẩn Double-Pass Adversarial Review:
- **Kiểm Soát Artifacts Trong Prompt (`core/prompts/services.py`)**: Ràng buộc chặt chẽ điều kiện chèn sơ đồ trực quan và tài liệu DOCX/CSV/XLSX, triệt tiêu 100% bão tác vụ rác ngoài ý muốn. Phân định rõ ngữ nghĩa 3 loại sơ đồ (Excalidraw cho concept/matrix, Mermaid cho flowchart/sequence, D2 cho system topology).
- **Explicit Wikilink Prioritization & Safe Topic Resolver (`services/rag_builder.py`)**: Bóc tách `[[stem]]` từ câu hỏi, ưu tiên nạp `topics/` -> `sources/` -> `concepts/` -> `MOC/` lên đầu ngữ cảnh RAG (`priority="explicit_user_reference"`), dùng `extract_body()` xử lý Windows CRLF và giữ nguyên `scan_all_concepts()`.
- **Dual-Scope Diagram Context 12k Chars (`services/diagram_base.py`)**: Chấm dứt hiện tượng sơ đồ "đói ngữ cảnh" bằng cách phân tầng `[TARGET SECTION]` trọng tâm kết hợp `[FULL ARTICLE CONTEXT]` toàn bài (lên tới 12,000 ký tự).
- **Tối Ưu Tốc Độ Background Workers (`services/mermaid_worker.py`, `services/vision_qc_worker.py`)**: Chuyển `mermaid_worker` và `vision_qc_worker` sang `task="synthesis"`, rút ngắn thời gian sinh từ ~80s xuống ~3-5s.
- **Phân Tuyến Mô Hình Đa Tầng & Ghi Đè `/fast` (`services/command/styles.py`, `coordinator.py`)**: Xây dựng `StyleParseResult` đa hình tương thích ngược, phân bổ `reasoning` (~105s) cho nhóm học thuật/phản biện và `synthesis` (~35s) cho nhóm sáng tạo, cho phép ghi đè tốc độ tức thì với `/fast`.
- **Test Suite**: Bổ sung bộ kiểm thử `test_command_upgrades.py` (16 test cases), đạt **120/120 tests passed** (100% pass, 0 regressions).

## v8.13.3 — Multimodal Diagram Pipeline Standardization & Wayfinder Hardening
Hoàn thành toàn diện 10 Frontier Tickets theo Bản đồ Định hướng Wayfinder (`.md/wayfinder/multimodal_diagrams/map.md`):
- **D2 Kroki Recovery & Portable Seam Locator (`services/d2_worker.py`, `core/prompts/services.py`, `.gitignore`)**: Bổ sung `User-Agent` tùy biến vượt Cloudflare WAF của Kroki (HTTP 403), vệ sinh cấm engine thương mại `tala` trên Kroki, escape an toàn cú pháp JSON prompt. Bổ sung hàm `find_d2_bin()` định vị binary cục bộ theo 4 tầng (`shutil.which`, `tools/bin/d2.exe`, WinGet packages, Programs/d2) cho phép dùng local D2 (mở khóa Tala v0.9.0+) mà không ép `elk`.
- **Responsive Mobile Diagrams (`core/prompts/services.py`, `services/mermaid_worker.py`, `.obsidian/snippets/mermaid-fit.css`)**: Ràng buộc hướng mặc định `flowchart TD` (Top-Down) và `direction: down` (chiều rộng $\le 500$px). Bổ sung CSS `.is-phone` cho phép cuộn ngang cảm ứng mượt mà cho cả Mermaid lẫn D2 SVG nhúng mà không bị co nhỏ chữ. Tự động chuẩn hóa `flowchart LR` có $>3$ liên kết thành `flowchart TD` (bảo vệ comment và nhãn chuỗi).
- **Tự Động Chữa Lành Thẻ Nhúng (`services/command/citations.py`, `coordinator.py`)**: Hàm `heal_artifact_embed_syntax()` chuẩn hóa toàn diện cú pháp thẻ nhúng Excalidraw (`_excalidraw_md` $\rightarrow$ `.excalidraw.md`), triệt tiêu link gãy khi lưu Topic Notes.
- **NanoID 8 Ký Tự Chuẩn Obsidian Excalidraw (`services/excalidraw_worker.py`, `core/prompts/services.py`)**: Hàm `_ensure_nanoid_8` khử xung đột bằng `seen_ids`, đồng bộ mũi tên `startBinding/endBinding`, cập nhật prompt mẫu chuẩn 8 ký tự.
- **Neo Giữ Tiêu Đề Khung Container (`services/diagram_base.py`, `services/excalidraw_worker.py`, `core/layout_router.py`)**: Cơ chế `containerHeaderOf` neo tiêu đề ở đỉnh khung, đồng bộ dịch chuyển khi canvas di dời, bổ sung Container Guard bỏ qua Sugiyama flattening trên các spatial clusters.
- **Universal Bounding Box Normalization (`services/diagram_base.py`, `services/excalidraw_worker.py`)**: Hàm `normalize_canvas_bounding_box()` dịch chuyển toàn bộ shapes, text, và toạ độ uốn của mũi tên về vùng an toàn ($x \ge 80, y \ge 60$).
- **Bảo Tồn Lớp Ngữ Nghĩa & Mã Hóa HTML Mermaid (`services/mermaid_worker.py`)**: Giữ nguyên các class `alert`, `law`, `accent`; mã hóa ký tự đặc biệt bằng HTML entities tiêu chuẩn (`#40;`, `#41;`, `#124;`) thay vì unicode lạ; phân tầng độ sáng cho nested subgraphs.
- **Đồng Bộ Cấu Hình Hero Image SSOT (`config.yaml`, `core/config.py`, `services/command/styles.py`)**: Khai báo `gateway_image_model: "gemini-3.1-flash-image"` trong config SSOT, bổ sung Negative Constraints chống tranh hoạt hình/3D nhựa.
- **Chữa Lành Ghi Chú Excalidraw Cũ (`attachments/`)**: Giải mã và chuẩn hóa ID 8 ký tự cùng toạ độ dương cho 2 sơ đồ đang nhúng thực tế (`mo_hinh_to_chuc_ai_yeung` và `ai_native_enterprise_os`).
- **Test Suite**: Mở rộng lên **415/415 passed tests** (100% pass, 0 regressions).

## v8.13.2 — Command Deep Module Consolidation & Multi-Query Drainage Loop (ccba-codebase-design)
Tái cấu trúc làm sâu module `services.command` theo 3 khuyến nghị từ đợt khảo sát kiến trúc:
- **Hấp thụ `chat_history.py` vào `services/command/inbox.py`**: Khôi phục tính Locality tuyệt đối cho định dạng và vòng đời của `Command.md`. Chuyển `services/chat_history.py` thành thin backward-compatibility shim.
- **Multi-Query Drainage Loop trong `handle_command()`**: Triệt tiêu hoàn toàn lỗi Starvation bất đồng bộ tại Seam Poller (`daemon.py`). Hỗ trợ vét cạn toàn bộ truy vấn trong Inbox trong một chu trình worker với safety cap `max_queries=10`.
- **Chuẩn hóa Dependency Seam cho `hero_image.py`**: Khắc phục hiện tượng bypass cấu hình toàn cục trong `generate_hero_image`, nhận diện `active_cfg` tường minh và giảm thiểu monkeypatching phân mảnh trong test suite.
- **Test Suite**: Mở rộng lên **393/393 passed tests** (thêm 4 unit tests mới, 0 regressions).

## v8.13.1 — Dual-Rendering Diagram Standards & Layout Pipeline Hardening
Nâng cấp toàn diện kiến trúc sinh sơ đồ và chuẩn hóa hiển thị đa tầng (Excalidraw + Mermaid) theo AGENTS.md §4.9:
- **Shared Layout Seams & Robust Geometry (`services/diagram_base.py`, `core/layouts/`)**:
  - `sync_bound_text_translation`: Đồng bộ dịch chuyển text hai chiều (`boundElements` và `containerId == sid`), lọc bỏ các ID rỗng/None.
  - `compute_safe_arrow_endpoints`: Tính toán giao điểm đường biên chuẩn xác (`get_shape_boundary_point`), áp dụng khoảng cách an toàn `dot > 12.0` với adaptive padding `min(5.0, (dot - 2.0) / 2.0)` triệt tiêu đảo ngược mũi tên và arrowhead blobs trên cả 7 layout engines (`wheel`, `cycle`, `radial`, `tree`, `value_chain`, `concentric`, `matrix`).
  - Xây dựng layout mới `wheel_layout.py` (Wheel / Star-Cycle), tích hợp tự động phát hiện `is_wheel` trong `layout_router.py`.
  - Khắc phục `value_chain_layout.py` tự biến node cuối thành hình thoi ("Margin") và bổ sung tọa độ lưới 2x2 cho `matrix_layout.py`.
- **Obsidian Excalidraw 2.x Wrapper & Context Matching (`services/excalidraw_worker.py`, `services/diagram_base.py`)**:
  - Cập nhật wrapper tiêu chuẩn `# Excalidraw Data \n ## Text Elements \n %% ## Drawing %%`, chấm dứt hiện tượng nhân đôi header và rò rỉ thẻ neo `^txt_...`.
  - Nâng cấp `find_diagram_context` hỗ trợ regex wiki-links có pipe kích thước (`![[name.excalidraw.md|100%]]`) và fallback tính điểm trùng khớp từ khóa heading.
- **Mermaid Academic Theme Hygiene (`services/mermaid_worker.py`)**:
  - Bảo vệ cú pháp biểu đồ phi-flowchart (`pie`, `timeline`, `mindmap`, `sequenceDiagram`, `stateDiagram`) khỏi việc tiêm `classDef` gây lỗi render.
  - Bóc tách Subgraph bằng regex và định kiểu qua `style <sg_id>` thay vì `class`. Tích hợp `wrap_label` và `sanitize_mermaid` trên 10 loại hình khối.
- **Thư viện mẫu & Kỹ năng (`diagram_templates.yaml`, `ccba-excalidraw-diagram`)**:
  - Thêm template `wheel` cho Mermaid và Excalidraw; chuyển sơ đồ *EOS Model Wheel* sang `wheel`; sửa template `matrix`.
- **D2 Vector Diagram Worker (`services/d2_worker.py`, `services/worker_dispatcher.py`)**:
  - Hỗ trợ biên dịch D2 sang SVG vector qua local CLI hoặc Kroki HTTP fallback (zero-dependency), tự động lưu cả file `.svg` lẫn file `.d2` trong `attachments/`.
- **Hero Image Command (`services/command/hero_image.py`, `services/command/styles.py`)**:
  - Tích hợp lệnh `/hero-image`, `/hero`, `/banner` tổng hợp prompt điện ảnh 16:9 từ ngữ cảnh bài viết và tự động nhúng `![[hero.jpg|100%]]` ngay dưới H1 (bảo vệ frontmatter Windows CRLF/LF).
- **Test Suite**: Mở rộng bộ kiểm thử lên **389/389 tests passed** (100% pass, 0 regressions).

## v8.13.0 — Command Service Deep Module Package Refactoring (ccba-codebase-design)
Tái cấu trúc toàn diện tệp monolith `services/command.py` (469 dòng) thành Deep Module Package `services/command/` theo chuẩn `ccba-codebase-design`:
- **Deep Module Architecture (`services/command/`)**:
  - `__init__.py`: Public Seam tối giản (`__all__ = ["handle_command", "WRITING_STYLES", "reindex_citations"]`) che giấu toàn bộ chi tiết xử lý nội bộ, kết hợp Dynamic Shims bảo toàn tương thích ngược 100%.
  - `coordinator.py`: Điều phối luồng xử lý, LLM dispatch, Dynamic Module Aliasing cho test monkeypatching (`_get_active_cfg()`), và resilient I/O retry (3 lần, 150ms backoff) chống file locking trên Windows.
  - `inbox.py`: Đóng gói toàn bộ logic biến đổi chuỗi thuần túy (Zero I/O, Zero state) gồm bóc tách span an toàn, in-place patching bảo toàn draft notes người dùng, và định dạng Markdown callout.
  - `styles.py`: Taxonomy thuần túy định nghĩa 10 phong cách viết và bộ phân giải tiền tố lệnh `/style`.
  - `citations.py`: Xử lý thuần túy đánh lại chỉ số trích dẫn `[14] -> [1]` và làm sạch dấu nháy kép/đơn trong wikilinks.
  - `topic_saver.py`: Tách biệt logic sinh cấu trúc Topic Note (RAM) và ghi tệp đĩa nguyên tử khi phản hồi $\ge 2,500$ ký tự.
- **Adversarial Hardening & Bug Fixes**:
  - Khắc phục lỗi regex tham lam nuốt chửng draft notes khi câu hỏi có nhiều dòng chứa `---`.
  - Triệt tiêu false positive query triggering bằng cách kiểm tra neo đầu dòng và tính chẵn lẻ của Markdown code fences.
- **Test Suite**: Bổ sung 6 unit tests mới vào `test_command_flow.py`, mở rộng toàn bộ test suite lên **337/337 tests passed** (100% pass, 0 regressions).

## v8.12.7 — Interactive Command Center Hardening & JIT Dynamic Model Resolver
Nâng cấp toàn diện giao diện dòng lệnh tương tác và tự động hóa phân giải mô hình ngôn ngữ:
- **Interactive Command Center Hardening (`services/command.py`, `services/chat_history.py`, `daemon.py`)**:
  - Triệt tiêu lỗi vòng lặp đốt token khi `Command.md` bắt đầu bằng `## 📥 Input`.
  - In-Place Surgical Patching: Chỉ thay thế khối query `@AI: {query} ---` đã xử lý thành `@AI:  ---`, bảo toàn 100% ghi chú nháp trong Inbox.
  - Asynchronous Daemon Polling: Tách worker thread riêng biệt (`command-worker`) có khóa `_command_lock`, giải phóng main loop khỏi việc bị block 90s khi LLM suy luận.
  - Bổ sung Fast Mode (`/fast`, `/quick`, `/nhanh`) định tuyến sang `task="synthesis"` phản hồi tức thì (~15s) thay vì deep reasoning (~90s).
  - Tự động lưu trữ Topic Note: Các phản hồi dài $\ge 2,500$ ký tự tự động xuất thành tệp `04 - Permanent/topics/{slug}.md` kèm liên kết điều hướng theo đúng AGENTS.md §4.6.
- **JIT Dynamic Model Resolver (`core/llm/model_resolver.py`)**:
  - Chuẩn hóa toàn bộ cấu hình hệ thống lên Gemini 3.8 Flash (`gemini-3.8-flash-high` cho synthesis và `gemini-3.8-flash-low` cho vision/fast).
  - Tích hợp hàm `resolve_model()` tự động phát hiện version Gemini mới nhất từ Gateway hoặc Google API (phân tích số học `3.8 > 3.7 > 3.5`), hỗ trợ alias `latest`, `auto`, `gemini-latest`.
  - Tích hợp bộ đệm 24h (`.state/.models_cache.json`) và hằng số tĩnh an toàn `STATIC_LATEST_GEMINI_FLASH = "gemini-3.8-flash-high"`.
- **Test Suite**: Mở rộng bộ kiểm thử lên **331/331 tests passed** (100% pass, 0 regressions).

## v8.12.6 — Maps of Content Hierarchical Restructure & Domain Quality Gate
Tái cấu trúc kiến trúc thông tin và thẩm mỹ thị giác cho thư mục `00 - Maps of Content/`:
- **Sub-folder Hierarchy (`sources/` & `domains/`)**: Di dời 174 Source MOCs vào `00 - Maps of Content/sources/` và 27 Domain MOCs vào `00 - Maps of Content/domains/`. Giữ thư mục gốc `00` tinh gọn tuyệt đối với đúng 3 tệp điều hành (`index.md`, `Command.md`, `Weekly_Synthesis.md`).
- **Domain MOC Quality Gate (`DOMAIN_MOC_THRESHOLD = 15`)**: Nâng ngưỡng tạo Domain MOC từ 8 lên 15 concepts, giảm từ 52 domain vụn vặt xuống còn 27 Đại Lĩnh Vực chất lượng cao, phân loại 100% vào 4 Grand Domains (0 domain rơi vào nhóm "Other").
- **Recursive Stale Cleanup & Linter Alignment**: Nâng cấp `wiki_maintain.py` (`rglob`), `wiki_health.py` và `close_session.py` hỗ trợ đệ quy sub-folders, tự động dọn dẹp các tệp MOC cũ/rác và đảm bảo 0 broken links ảo. Di dời tài liệu NVIDIA về `topics/` và `attachments/`.
- **Test Suite**: Đồng bộ 100% test suite với 301/301 tests passed trong ~53s.

## v8.12.5 — Podcast Ingestion Pipeline & Codebase Architecture Deepening
Tái cấu trúc kiến trúc mã nguồn theo chuẩn `ccba-codebase-design` và tích hợp engine bóc tách Podcast tự hành:
- **Podcast Ingestion Engine (`services/podcast.py`)**: Tự động nhận diện nguồn Apple Podcasts, Spotify và link audio trực tiếp; phân giải JSON-LD metadata, tải và transcode âm thanh về chuẩn 16kHz mono 32kbps MP3 và chuyển tiếp sang Faster-Whisper trên Server Spark với tự động phát hiện ngôn ngữ và mốc thời gian `[MM:SS]`.
- **Media Utility Seam (`core/media.py`)**: Thiết lập Seam SSOT hạ tầng nhị phân ngoại vi duy nhất cho hệ thống (`find_ffmpeg_bin`, `find_ffprobe_bin`, `transcode_audio_to_mp3`), tự động tìm kiếm qua WinGet và dọn dẹp file tạm khi gặp sự cố, loại bỏ hoàn toàn mã nguồn trùng lặp giữa YouTube và Podcast.
- **Eliminate Legacy Shims**: Áp dụng triệt để *Deletion Test*, xóa sạch 2 tệp shim nông (`services/youtube_transcript.py` và `services/moc_diagram.py`), repoint 100% callers trực tiếp về `services.youtube` và `services.moc_mermaid`.
- **Vector Store & File Lock Seams (`core/file_lock.py`, `core/vector_store.py`)**: Tách tiện ích khóa tiến trình hệ điều hành `CrossProcessFileLock` (msvcrt / fcntl) và đóng gói vòng đời chỉ mục vector trong `VectorStore` với khóa file và ghi tệp tạm nguyên tử (`os.replace`).
- **Publisher Diagram SSOT (`pipeline/book_assets.py`)**: Tập trung hóa toàn bộ logic trích xuất sơ đồ sách, nhận diện ảnh trang trí và danh mục JIT diagrams, loại bỏ code trùng lặp trên 4 tệp pipeline.
- **Incremental MOC Rebuild & Caching (`wiki_maintain.py`, `core/vault.py`)**: Áp dụng mtime/size cache và LibYAML `CSafeLoader`, xây dựng `rebuild_incremental(concept)` rút ngắn thời gian cập nhật MOC từ 1.8s-3.2s xuống <0.05s-0.5s.
- **Graph Health & Zero False-Alarm Linter (`services/wiki_health.py`)**: Triệt tiêu 1,421 broken links và 107 missing frontmatter notes nhờ lọc media attachments, nạp đầy đủ 6 bề mặt tra cứu, áp dụng nguyên tắc *Alias-First Resolution*, và mở rộng bộ test lên 300/300 passed tests (100%).

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
