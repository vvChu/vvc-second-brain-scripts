# 📜 VvC Second Brain — Changelog

Lịch sử thay đổi kiến trúc pipeline. Xem `AGENTS.md` cho quy tắc hiện hành.

## v8.15.13 — Deep Module Seams: Weekly Synthesis Extraction, RAG & Wiki Health Deep Packages
Tối ưu hóa cấu trúc mô-đun sâu (Deep Modules) và làm sạch ranh giới tương tác (Clean Seams) theo chuẩn `ccba-codebase-design`:
- **Phân Rã Dịch Vụ Wiki Health Thành Package Chuyên Biệt (`services.wiki_health`)**: Phân rã tệp `scripts/services/wiki_health.py` (1.050 dòng) thành Deep Module Package `services/wiki_health/` gồm 6 submodules chuyên trách: `linter.py` (VaultLinter), `link_healer.py` (LinkHealer kèm chuẩn hóa đường dẫn `config.yaml`), `stub_lifecycle.py` (quản lý lifecycle stubs), `domain_enricher.py` (làm giàu domain YAML), `code_pill_cleaner.py` (làm sạch code-pill wikilinks), `title_standardizer.py` (chuẩn hóa tiêu đề note); toàn bộ submodule đều tuân thủ nghiêm ngặt ngân sách dòng (≤ 289 dòng so với trần 350 dòng); re-export đầy đủ 20 symbols qua Central Facade `__init__.py` bảo toàn 100% hợp đồng giao diện cho tất cả các callers.
- **Tách Báo Cáo Weekly Synthesis (`services.weekly_synthesis`)**: Tách hàm `generate_weekly_synthesis` (260 dòng) từ `services/wiki_health.py` sang module chuyên biệt `services/weekly_synthesis.py`, áp dụng kỹ thuật lazy import triệt tiêu 100% circular dependencies, giữ shim re-export tại `wiki_health` và cập nhật các callers nội bộ (`close_session.py`, `sleep.py`).
- **Đóng Gói Phân Hệ RAG Thành Package (`services.rag`)**: Hợp nhất và đóng gói `rag_search.py` và `rag_builder.py` thành package `services/rag/` (`hybrid_search.py`, `context_builder.py`, `__init__.py`) với Deep Seam trung tâm; rút gọn 2 module cũ thành shims tương thích ngược 100%; chuyển các caller live (`coordinator.py`, `hero_image.py`) sang import trực tiếp từ `services.rag`.
- **Chuẩn Hóa Seams Command & Deprecation Warning**: Chuẩn hóa import trong `command/__init__.py`, loại bỏ dead imports, bổ sung `DeprecationWarning` chính quy cho legacy shim `services/chat_history.py`, dọn dẹp import tests sang `services.command.inbox`.
- **SSoT Versioning & Manifest Sync**: Thiết lập `scripts/core/__version__.py` làm nguồn chân lý duy nhất cho phiên bản; loại bỏ chuỗi hardcode trong log daemons; tự động bảo vệ qua `test_deep_manifest_version_synchronization` trên 10 bề mặt SSoT.
- **Zero-Slack Architectural Ratchets & Graduation**: Thiết lập chốt chặn phân tích tĩnh trần tệp $\le 350$ dòng (28 tệp legacy) và trần hàm AST $\le 50$ dòng (82 tệp legacy) không khoảng đệm; tinh gọn `services/command/hero_image.py` về 345 dòng ($\le 350$ dòng) và khử 100% hàm > 50 dòng (từ 3 hàm về 0), chính thức tốt nghiệp khỏi danh sách legacy ratchets (`test_architectural_budgets.py`); kiên cố hóa regex linter Spoke Cleanliness chống rò rỉ đường dẫn máy (`test_codebase_cleanliness.py`).
- **Động Cơ Tìm Kiếm Cầu Nối Tri Thức Liên Miền (BridgeCandidateFinder & Core Taxonomy — Issue #4)**: Trích xuất từ điển taxonomy (`GRAND_DOMAINS`, `DOMAIN_ALIASES`, `normalize_domain_tag`, `resolve_grand_domains`) sang `scripts/core/taxonomy.py`, re-export tại `wiki_maintain.py` giải phóng 66 dòng code và chống circular import; triển khai `BridgeCandidateFinder` trong `services.wiki_health` phân giải đồ thị 2.754 concepts (xử lý 2.762 liên kết trực tiếp và 255 liên kết qua alias), tính toán điểm Simpson Diversity kết hợp log-degree, lọc Hub Pruning (2 ≤ d ≤ 25); tích hợp vào `VaultLinter` (`LintReport["bridge_candidates"]`) và kết xuất bảng Markdown công thái học tại `Weekly_Synthesis.md` (`_render_bridge_candidates`); bổ sung test suite `test_bridge_finder.py` bảo đảm hiệu năng < 0.15s trên toàn bộ đồ thị thực tế.
- **Nâng Cấp Bộ Test Suite**: Bổ sung unit tests toàn diện (`test_wiki_health_package.py`, `test_weekly_synthesis.py`, `test_rag_package.py`, `test_codebase_cleanliness.py`, `test_architectural_budgets.py`, `test_bridge_finder.py`), nâng tổng số test lên 581 items với 10 unit tests độc lập cho `test_bridge_finder.py`.
- **Đúc Kết Quy Tắc Quản Trị Vận Hành (Operational Governance Invariants)**: Thể chế hóa vùng đệm tệp tạm thời `.md/scratch/` giải quyết xung đột với `.gitignore`; thiết lập nguyên tắc siết bánh cóc đồng thời (Concurrent Zero-Slack Ratchet Tightening); xác lập nguyên tắc phân rã mô-đun chạm trần (Cap-Reached Module Decomposition); và chuẩn hóa chỉ dẫn môi trường chạy kiểm thử cách ly trên Server Spark Linux (`scripts/.venv/bin/pytest`).


## v8.15.12 — Deep Module Seams: Core Markdown Sanitizer, Orthography Disambiguation & Diagram Base Hygiene
Chuẩn hóa kiến trúc phân tầng một chiều, tách ranh giới module sâu (Deep Seams) và loại bỏ hoàn toàn hiện tượng phụ thuộc ngược giữa các tầng (`core/markdown_sanitizer.py`, `services/orthography.py`, `services/diagram_base.py`, `services/moc_mermaid.py`, `pipeline/post_process.py`, `services/mermaid_worker.py`):
- **Deep Seam `core.markdown_sanitizer`**: Tách toàn bộ 4 hàm biến đổi chuỗi thuần túy (`heal_mermaid_edge_syntax`, `heal_html_entity_leakage`, `heal_artifact_embed_syntax`, `clean_wikilink_quotes`) khỏi `services/command/citations.py` về tầng nền tảng `core/`. Giải phóng hoàn toàn `pipeline/post_process.py` khỏi phụ thuộc ngược vào `services/command`, giảm thời gian nạp module lạnh từ 125ms xuống ~6ms (>20x faster).
- **Phân Định Ranh Giới Ngữ Âm / Chính Tả (`services.orthography`)**: Tách biệt rõ ranh giới giữa Map-Reduce tài liệu lớn (>200.000 ký tự) tại `core/text_chunker.py` và tiền xử lý ngữ âm, chính tả ASR transcript cùng Smart Bypass tại `services/orthography.py`. Duy trì `services/text_chunker.py` như một shim tương thích ngược 100%.
- **Hợp Nhất Nền Tảng Sơ Đồ (`services.diagram_base`)**: Di dời `wrap_label` và `sanitize_mermaid` về đúng vị trí trung tâm tại `services/diagram_base.py`, loại bỏ hoàn toàn import ngược từ `diagram_base` vào `moc_mermaid`. Giữ re-export trong `services/moc_mermaid.py` kèm public API contract `__all__`.
- **Hoàn Thiện Kiểm Thử & Loại Bỏ Dead Imports**: Bổ sung unit tests độc lập cho cả 3 seam (`test_markdown_sanitizer.py`, `test_orthography.py`, `test_diagram_base.py`), nâng tổng số test lên 550/550 passed (100%), và dọn dẹp unused import `sanitize_mermaid` trong `mermaid_worker.py`.

## v8.15.11 — 4-Tier Native ASR Caption Hierarchy, Ground Truth Fallback & Multi-Evidence Hooks
Thể chế hóa các nâng cấp kiến trúc và sửa lỗi từ phiên Double-Pass Adversarial Evaluation (`AGENTS.md` §4.1, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/services/youtube/transcript.py`, `scripts/pipeline/self_correct.py`, `scripts/tools/deduplicate_sources.py`, `scripts/core/prompts/pipeline.py`, `scripts/core/prompts/services.py`):
- **4-Tier Native ASR Caption Selection Hierarchy**: Phân biệt chuẩn xác giữa track phụ đề Native ASR nguyên bản (URL không chứa tham số `tlang=`) và phụ đề dịch máy YouTube (`tlang=...`), ưu tiên: Manual vi/en $\rightarrow$ Native ASR vi/en $\rightarrow$ Auto-translated fallback $\rightarrow$ Whisper AI (`language=None` tự động nhận diện tiếng nói đa ngữ); bảo tồn 100% Ground Truth nguyên văn tiếng Anh của diễn giả.
- **Ground Truth Fallback Instruction & Self-Correction Bypass**: Chuẩn hóa điều khoản fallback tường minh trong prompt LLM: nếu nguồn nạp thuần Việt hoặc video không có transcript tiếng Anh verbatim, ghi rõ `(không có — nguồn nạp là tài liệu tiếng Việt)`; đồng thời nâng cấp `scripts/pipeline/self_correct.py` lập tức bỏ qua xác thực blockquote khi Ground Truth mang giá trị fallback, triệt tiêu ảo giác LLM.
- **Multi-Evidence Hooks for Stage 5 Merged Notes**: Chính thức ghi nhận trong Hiến pháp quy tắc đa bằng chứng: ghi chú sau hợp nhất ngữ nghĩa (Stage 5 Semantic Merger) được phép duy trì 2-3 Evidence Hooks kèm Citation Line ở phần mở đầu; tự động kích hoạt Consolidated Pruning khi đạt ngưỡng $\ge 4$ hooks.
- **Automated Source Deduplication & Link Healing**: Mở rộng `scripts/tools/deduplicate_sources.py` hỗ trợ cả trường `sources:` mảng YAML và tự động chuyển hướng, chữa lành 10 concept notes cùng registry của video `zcLPGC-tvgk` (Uncle Bob), thu hồi MOC mồ côi.
- **Living Architecture Reference & Workspace Context Standardization**: Thể chế hóa tài liệu kiến trúc sống 8 Trụ cột và 3 Đột phá tại `.md/vault_mental_model_and_architecture.md`, chuẩn hóa SSoT `.md/workspace_context.yaml`, bổ sung §1.1 vào `AGENTS.md`, đồng bộ Quick Rules trong `GEMINI.md`, cấu hình un-ignore `.md/*.md` và `.md/*.yaml` trong `.gitignore`, đồng thời mở rộng quy chuẩn cho Claude (`CLAUDE.md`), Cursor (`.cursor/rules/vault-architecture.mdc`), và GitHub Copilot (`.github/copilot-instructions.md`).


## v8.15.10 — Mermaid Edge Label & Strict HTML Entity Context Isolation Invariants
Thể chế hóa các bài học kiến trúc thực chiến từ phiên `/ccba-grilling /learn` sau đợt khắc phục sự cố biên dịch Chương 3 (`AGENTS.md` §4.4, §5, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/services/command/citations.py`, `scripts/services/mermaid_worker.py`, `.agents/rules/diagramming_hygiene.md`, `.agents/skills/ccba-markdown-document-processing/SKILL.md`):
- **Mermaid Edge Label Invariant**: Cấm tuyệt đối chèn nhãn text vào giữa thân mũi tên (`===="text"====>`, `-."text".->`, `<===="text"====>`); bắt buộc dùng cú pháp pipe chuẩn `===>|"label"|`, `-.->|"label"|`, `<===>|"label"|` hoặc `-- "label" -->`; chuẩn hóa toán tử so sánh (`>=` $\rightarrow$ `≥`, `<=` $\rightarrow$ `≤`) để loại bỏ xung đột token với arrow head.
- **Strict HTML Entity Context Isolation Invariant**: Các thực thể HTML `#40;` và `#41;` CHỈ được phép tồn tại bên trong khối ````mermaid` để chống lỗi parse node shape. Cấm rò rỉ `#40;`/`#41;` ra ngoài các bảng biểu Markdown hoặc thân bài; bảng Markdown bắt buộc dùng ngoặc đơn tròn chuẩn `()`.
- **Dual-Anchor Hybrid Auto-Correction & Warning Log**: Triển khai cơ chế tự động làm sạch và chữa lỗi tại hai mỏ neo: `scripts/services/command/citations.py` (`heal_mermaid_edge_syntax`, `heal_html_entity_leakage` tích hợp vào `clean_wikilink_quotes` bảo vệ sơ đồ/bảng biểu inline) và `scripts/services/mermaid_worker.py` (chữa các tệp `.mermaid.md` độc lập), kèm ghi log cảnh báo tự động `[Mermaid Sanitizer]` và `[Entity Sanitizer]`.

## v8.15.9 — Stale Daemon Invariant, CLI Autonomous Artifact Ingestion & The 4 Mermaid Ergonomic Design Patterns
Thể chế hóa các bài học kiến trúc thực chiến từ phiên `/grill-me /learn` sau đợt chấp bút Chương 4 và nâng cấp sơ đồ Mermaid (`AGENTS.md` §4.4, §5, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/daemon.py`, `scripts/core/llm/gemini_client.py`, `.agents/rules/diagramming_hygiene.md`, `.agents/skills/ccba-markdown-document-processing/SKILL.md`):
- **Stale Daemon Invariant & `--restart` Flag**: Thể chế hóa quy tắc cấm vận hành trên daemon cũ lưu mã nguồn cũ trong RAM; bổ sung cờ `--restart` vào `scripts/daemon.py` tự động quét và hạ các tiến trình python/pythonw chạy nền trước khi tái nạp code mới.
- **CLI Autonomous Artifact Ingestion**: Nâng cấp `scripts/core/llm/gemini_client.py` với `_resolve_cli_artifact_content` tự động phát hiện đường dẫn URI `file:///...` trỏ vào thư mục brain của `agy.exe` khi Claude Opus kích hoạt Agent mode, đọc toàn văn nội dung tệp artifact `.md` thay thế thông báo tóm tắt ngắn từ stdout trước khi chuyển tiếp cho downstream.
- **Bộ Tứ Mẫu Thiết Kế Mermaid Công Thái Học (The 4 Mermaid Ergonomic Design Patterns)**: Chuẩn hóa 4 mẫu thiết kế cấu trúc trong `.agents/rules/diagramming_hygiene.md` §3.6: (1) Macro Hub-and-Pods Layout với `~~~` khóa chặt trục ngang; (2) Semantic Decision Tree với Badges pastel ngữ nghĩa (`REUSE`, `EXTEND`, `CREATE NEW`); (3) Multi-Tier Governance Funnel trực quan hóa 3 tầng lọc ADR-0057; (4) Cross-Domain Subgraphs phân vùng lãnh thổ SpokeZone vs HubZone với luồng phản hồi bất đối xứng trọng số $\Delta W \ge 2$.

## v8.15.8 — Local Antigravity CLI Opus Tier 1 Routing & Multi-Tier Reasoning Cascade
Nâng cấp Antigravity CLI cục bộ (`agy.exe`) lên làm Tier 1 Primary cho mô hình Claude Opus 4.6 Thinking và các tác vụ suy luận sâu (`scripts/core/llm/__init__.py`, `scripts/core/llm/gemini_client.py`, `scripts/config.yaml`, `scripts/core/config.py`):
- **Local Antigravity CLI Opus Tier 1**: Định tuyến ưu tiên số 1 các yêu cầu `/opus`, `/academic`, `/phan-bien` và `task="reasoning"` về `agy.exe` với `claude-opus-4-6-thinking`, loại bỏ hoàn toàn hiện tượng 429 upstream và giáng cấp ngầm (silent downgrade) từ Port 8045/8090.
- **Tự Động Nâng Ngưỡng Timeout Phản Hồi Reasoning**: Tự động nâng timeout lên `reasoning_timeout` (600s, kèm `--print-timeout 600s`) cho các dòng mô hình Thinking nhằm bảo đảm chuỗi suy luận sâu không bị ngắt quãng.
- **Chuỗi Dự Phòng Đa Tầng Bền Vững (Multi-Tier Fallback Cascade)**: Khi CLI cục bộ gặp sự cố hoặc offline, hệ thống tự động fallback mượt mà sang Gateway Port 8045 $\rightarrow$ GitHub Copilot CLI (`claude-sonnet-4.6`) $\rightarrow$ Google AI Studio API.

## v8.15.7 — Clean Wikilink & Zero-Code-Pill Invariant, SLM Prompt Anti-Literalism & Deterministic Sanitization Gate
Thể chế hóa các bài học kinh nghiệm từ phiên `/grill-me /learn` nhằm giải quyết triệt để lỗi Code-Pill Wikilinks, lệch số trích dẫn trong bảng và hiện tượng sao chép máy móc (Token Literalism) của mô hình tầng dưới (`AGENTS.md` §4.4, §5, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/wiki_maintain.py`, `.agents/skills/ccba-markdown-document-processing/SKILL.md`, `.agents/skills/ccba-llm-pipeline-patterns/SKILL.md`):
- **Clean Wikilink & Zero-Code-Pill Invariant**: Cấm tuyệt đối bọc backtick quanh wikilink trên mọi bề mặt Markdown (thân bài, bảng biểu, callout, danh mục trích dẫn) để bảo toàn tính tương tác và không làm gãy đồ thị Graph View trong Obsidian; trong bảng biểu bắt buộc escape pipe `[[slug\|alias]]` nhưng giữ nguyên liên kết trần; đồng bộ 100% số thứ tự trích dẫn trong bảng với danh mục tham chiếu cuối bài.
- **SLM Prompt Anti-Literalism Standard**: Cấm dùng backticks bọc ví dụ mẫu trong prompt nếu output không chứa backtick (dùng thẻ XML `<example>` thay thế) nhằm ngăn chặn mô hình nhẹ (Gemini Flash, Haiku) sao chép máy móc ký tự vào output; đặt điều khoản cấm tường minh trong phần `<rules>` của prompt.
- **Deterministic Backend Sanitization Gate**: Triển khai cơ chế phòng thủ 2 đầu: Bắt buộc bộ lọc tất định tại pre-save (`citations.py`, `post_process.py`) để bóc tách backticks khỏi wikilinks; đồng thời bổ sung hàm quét "code-pill wikilinks" vào `scripts/wiki_maintain.py` để phát hiện và cảnh báo tự động trong toàn bộ Vault.

## v8.15.6 — Executive Typography 16:9, Arrow-Label Clearance & Mermaid Flat Two-Node Invariants
Thể chế hóa các bài học kinh nghiệm từ phiên `/grill-me /learn` nhằm giải quyết dứt điểm Nghịch lý Co giãn Canvas, lỗi đè chữ tiêu đề Subgraph Mermaid và rào chắn không gian mũi tên (`AGENTS.md` §4.9, §4.12, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/core/prompts/services.py`, `.agents/skills/ccba-markdown-document-processing/SKILL.md`):
- **Executive Typography 16:9 & Architecture Specification Matrix Invariant**: Triệt tiêu Nghịch lý Co giãn Canvas (Canvas-to-Document Scaling Paradox) khi nhúng sơ đồ Excalidraw vào cột đọc hẹp Obsidian: khóa chiều rộng canvas $1.000\text{px} \le W \le 1.150\text{px}$ để duy trì hệ số co giãn khi nhúng $\ge 65\%-70\%$; áp dụng cỡ chữ sàn hiển thị $\ge 8.5\text{px}-11.5\text{px}$ (canvas font $\ge 12\text{px}-20\text{px}$); tuân thủ nguyên tắc Executive Poster kết hợp Bảng Đặc Tả Ma Trận Markdown đặt ngay dưới sơ đồ.
- **Quy Tắc Phân Tách Mũi Tên & Nhãn Kết Nối (Arrow-Label Clearance Invariant)**: Bắt buộc tách rời trục tọa độ Y giữa nhãn text và mũi tên với khoảng đệm an toàn $\ge 15\text{px}$ để chống đường kẻ đâm xuyên qua chữ; khoảng cách ngang giữa 2 khối có mũi tên liên kết kèm nhãn phải đạt tối thiểu $\ge 80\text{px}-90\text{px}$.
- **Quy Tắc Phẳng Hóa Cặp Đối Trọng & Cấm Lồng Hộp (Flat Two-Node & Subgraph Title Invariant)**: Cấm tuyệt đối việc tạo `subgraph` chỉ để chứa duy nhất 1 node con trong các mô hình đối trọng song phương (phẳng hóa thành 2 node độc lập); cấm sử dụng thẻ `<br/>` trong nhãn tiêu đề của `subgraph` để loại trừ lỗi cắt cụt chữ (clipping) do engine Dagre; cưỡng chế $100\%$ căn lề trái bullet points bằng `<div align='left'>`.

## v8.15.5 — Clean Callout Headers, Target Language Syntax Alignment & Minimal Code Banners
Chuẩn hóa Bộ Ba Ràng Buộc Trình Bày Callout & Cấu Hình nhằm loại bỏ dứt điểm lỗi Double Icon và vỡ baseline trên Obsidian (`AGENTS.md` §4.12, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/core/prompts/services.py`, `.agents/skills/ccba-markdown-document-processing/SKILL.md`):
- **Quy Tắc Tiêu Đề Callout Thuần Khiết (Clean Callout Header Invariant)**: Cấm chèn emoji (⚙️, 📋...) vào đầu tiêu đề Callout để triệt tiêu lỗi Double Icon Glitch do Obsidian tự động tiêm SVG icon; cấm bọc backticks quanh tên tệp/định danh trong tiêu đề Callout (dùng plain text) để bảo toàn baseline phẳng và nút chevron gấp mở.
- **Quy Tắc Đồng Bộ Ngữ Nghĩa Cú Pháp Ngôn Ngữ Mục Tiêu (Target Language Syntax Alignment Invariant)**: Đồng bộ hóa chính xác cú pháp comment giữa văn bản giải thích và khối code mẫu (`#` cho YAML/Python, `//` cho JSONC/JS/TS, `<!-- -->` cho HTML/Markdown), chống crash parser khi copy-paste.
- **Quy Tắc Tối Giản Dải Phân Cách Code Block (Minimal Banner Invariant)**: Thay thế các dòng phân cách dài `# ================================` bằng tiêu đề phân vùng ngắn gọn `# --- GLOBAL SECTION ---` để khử rác thị giác và tiết kiệm không gian trên Light Theme.

## v8.15.4 — Mermaid Engineering Invariants & Two-Track Document Ergonomics
Thiết lập bộ quy chuẩn bất biến kỹ thuật giải quyết triệt để các lỗi hiển thị Dagre, màu sắc và công thái học đọc tài liệu (`AGENTS.md` §4.12, `GEMINI.md`, `scripts/GEMINI.md`, `scripts/README.md`, `scripts/core/prompts/services.py`, `.agents/skills/ccba-markdown-document-processing/SKILL.md`):
- **Quy Tắc Ngưỡng Vàng Lai (Hybrid Golden Threshold)**: Bắt buộc tách Excalidraw 16:9 khi sơ đồ là Kiến trúc Hệ thống / Ma trận đa tầng ($\ge 3$ layers), hoặc tổng số nodes $\ge 9$, hoặc có liên kết chéo giữa $\ge 3$ subgraphs. Mermaid inline chỉ dành cho luồng tuyến tính, tương tác song phương (2 cụm), hoặc chu trình nhỏ ($\le 8$ nodes).
- **Bộ Tứ Ràng Buộc Kỹ Thuật Mermaid (The 4 Mermaid Invariants)**: Bắt buộc áp dụng đồng bộ: (1) Bất đối xứng trọng số cạnh ($\Delta W = W_{down} - W_{up} \ge 2$) khóa cứng cấp bậc Dagre; (2) Directive `%%{init}%%` Grayscale Base Theme khử màu vàng mù tạt `#ffffde`; (3) `<div align='left'>` căn lề trái bullet points; (4) Cạnh vô hình `~~~` cưỡng chế thứ tự đọc LTR.
- **Công Thái Học Tài Liệu Phân Loại 2 Nhánh (Two-Track Document Ergonomics)**: Khối code $> 15$ dòng bắt buộc bọc trong Obsidian Callout: Cấu hình mẫu/Schema dùng Callout Mở sẵn `> [!abstract]+ ⚙️`; Log thô/Metadata dùng Callout Đóng sẵn `> [!info]- 📋`; cấm để code block trần $> 15$ dòng làm đứt mạch đọc.

## v8.15.3 — Zero-ASCII Art Invariant & Responsive Diagram Enforcement
Thiết lập quy chuẩn bất biến cấm sơ đồ văn bản và cưỡng chế tính co giãn responsive cho toàn bộ tài liệu tri thức (`AGENTS.md` §4.11, `GEMINI.md`, `scripts/core/prompts/services.py`):
- **Cấm Tuyệt Đối Sơ Đồ Ký Tự Text (Zero-ASCII/Unicode Box Invariant)**: Nghiêm cấm vẽ sơ đồ kiến trúc, ma trận phân nhánh, flowcharts bằng ký tự ASCII (`+---+`, `|`, `->`) hoặc Unicode Box-Drawing (`┌─┐`, `└─┘`) bên trong code block trần để triệt tiêu vĩnh viễn lỗi Soft Line Wrapping làm rách viền khung và sụp đổ trục mũi tên trên Obsidian Reading View và mobile.
- **Cưỡng Chế Native Language Fencing Cho Tệp Cấu Hình/Mã Nguồn**: Mọi tệp cấu hình và dữ liệu (như `workspace_context.yaml`, `config.json`) bắt buộc dùng code fence ngôn ngữ chuẩn (` ```yaml `, ` ```json `), phân tách phân vùng bằng chú thích comment (`# ---`), tuyệt đối không bọc trong khung vẽ Unicode/ASCII giả lập.
- **Chuẩn Hóa Mermaid-First & Semantic Styling**: Bắt buộc chuyển đổi sơ đồ luồng, phân tầng, phân nhánh sang **Mermaid Flowchart** (`flowchart TD` / `flowchart LR`) kết hợp bộ style Academic Grayscale (`principal`, `standard`, `subbox`, `alert`, `safe`).

## v8.15.2 — Markdown Table Invariants & Reading View Aesthetics
Chuẩn hóa các quy tắc bất biến khi tạo và hiển thị bảng Markdown trong Obsidian (Chromium Table Engine):
- **Bắt Buộc Thoát Ký Tự Pipe trong Wikilinks (`AGENTS.md` §4.10, `GEMINI.md`)**: Bắt buộc escape `[[slug\|alias]]` trong ô bảng Markdown để chống gãy parser bảng, ngăn chặn hiện tượng mất thẻ đóng `]]` và rách mép hiển thị do chuỗi slug dài không có khoảng trắng.
- **Khóa Mũi Tên Điều Hướng Chống Rớt Dòng Mồ Côi**: Bắt buộc dùng `&nbsp;` liền kề ký tự mũi tên/bullet (`↳&nbsp;Text`) sau thẻ ngắt dòng `<br>`, loại trừ việc mũi tên bị rơi xuống đứng một mình trên một dòng riêng.
- **Cân Bằng Độ Rộng Đáy & Phân Tầng 2 Nhịp**: Bổ sung nhãn phụ `*(...)*` để neo baseline width Cột 1 (~18-22%) và cấu trúc ô so sánh 2 nhịp (In đậm từ khóa + cơ chế $\le 40$ ký tự/dòng), triệt tiêu hoàn toàn horizontal scrollbar trên Obsidian reading view.

## v8.15.1 — Dual-Rendering Excalidraw Auto-Expand Container & Wheel Layout Invariants
Chuẩn hóa và đồng bộ hóa các bất biến bố cục sơ đồ trực quan (Excalidraw + Wheel Layout) vào Hiến pháp và mã nguồn:
- **Tự Động Nới Rộng Chiều Cao Container Excalidraw (`services/excalidraw_worker.py`, `core/prompts/services.py`)**: Tự động kiểm tra và nâng chiều cao container shape theo công thức $H_{container} \ge H_{text} + 30\text{px}$, ngăn tràn chữ ra ngoài khung; bổ sung cảnh báo diện tích thực tế của hình thoi/elip và ràng buộc prompt súc tích 1 dòng ($\le 35$ ký tự), node metadata width $\ge 200\text{px}$.
- **Phân Tách 3 Tầng & Neo Vị Trí Wheel Layout (`core/layouts/wheel_layout.py`)**: Bóc tách rành mạch `header_ids` (neo cố định tại $Y=30\text{px}$), `aux_shape_ids` (loại trừ phantom nodes khỏi vành đai), và `connected_shape_ids` (phân bố đều trên vành đai tuần hoàn $Y \ge 120\text{px}$).

## v8.15.0 — Large Document Map-Reduce Chunker, Port 8045 Claude Opus/Sonnet & Conditional Multi-turn (Sprint P3)
Hoàn thành toàn diện gói nâng cấp LLM OS v8.15.0 (Sprint P3) theo Bản đồ Wayfinder (`.md/wayfinder/llm_os_upgrade_sprint_p3/map.md`):
- **Tích Hợp Antigravity Tools Proxy Port 8045 (`core/llm/gateway_client.py`, `config.yaml`, `core/config.py`)**: Kết nối trực tiếp Port 8045 trên Server Spark (`100.83.192.30:8045`) qua giao thức OpenAI `/v1/chat/completions` (zero new dependencies). Mở khóa suy luận chuyên sâu từ **Claude Opus 4.6 Thinking** (`claude-opus-4-6-thinking`) và **Claude Sonnet 4.6** (`claude-sonnet-4-6`).
- **Tier 1 Self-Healing & Cooldown Circuit Breaker (`core/llm/gateway_client.py`)**: Khi Port 8045 gặp lỗi 503 (pool cooldown) hoặc 429, tự động kích hoạt soft cooldown 30s và giáng cấp tức thì sang `gemini-3.8-flash-high` trên Port 8090 mà không làm sập pipeline. Chèn Callout `> [!info]` thông báo giáng cấp thân thiện đầu bài viết qua `consume_gateway_downgraded()`.
- **Hỗ Trợ Slash Commands Ép Model (`services/command/styles.py`)**: Nhận diện tiền tố ép model `/opus` (Claude Opus 4.6 Thinking), `/sonnet` (Claude Sonnet 4.6), `/pro` (Gemini 3.1 Pro), `/fast` hoặc `/flash` (Gemini 3.8 Flash High). Mở rộng `StyleParseResult` hỗ trợ unpacking linh hoạt 2, 3 và 4 phần tử (`style_name, clean_query, is_fast, explicit_model`).
- **Engine Adaptive Text Chunking & Map-Reduce (`core/text_chunker.py`)**:
  - `split_into_chunks()`: Phân tách tài liệu lớn theo ranh giới Heading (`#`, `##`, `###`) hoặc ngắt dòng đoạn văn (`\n\n`), duy trì overlap 1,000 ký tự.
  - `map_reduce_summarize()`: Xử lý dứt điểm tài liệu khổng lồ (>200,000 ký tự), chấm dứt hiện tượng Silent Drop. Pha Map dùng `gemini-3.8-flash-high` tóm tắt siêu tốc từng chunk, Pha Reduce dùng model đích (Opus 4.6 hoặc model yêu cầu) tổng hợp thành ngữ cảnh mạch lạc. Tích hợp cho cả JIT URL Ingestion (`coordinator.py`) và Fleeting Brain Dump (`concept_synthesis.py`).
- **Bộ Nhớ Ngắn Hạn Multi-turn Có Điều Kiện (`services/command/coordinator.py`, `core/prompts/services.py`)**:
  - `detect_continuity_signal()`: Nhận diện các câu hỏi đào sâu ("ở trên", "vừa rồi", "phần 2", "giải thích thêm", "so sánh với cái trước"...).
  - `extract_last_exchange()`: Trích xuất chính xác 1 lượt hỏi-đáp gần nhất ($\le 4,000$ ký tự) từ `Command.md` và nhúng vào thẻ `<previous_conversation_context>`.
- **Toàn Bộ Bộ Kiểm Thử**: Bổ sung `test_gateway_routing_p3.py`, `test_core_text_chunker.py`, `test_command_multiturn.py`, nâng tổng số test lên **481/481 passed tests** (100% pass, 0 regressions).

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
