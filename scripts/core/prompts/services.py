"""VvC Second Brain — Services Prompt Registry.

Centralized prompt templates for interactive services and workers.
Prompts with placeholders use str.format(); static prompts are used as-is.

Modules that consume these prompts:
    - core/text_chunker.py
    - services/brain_dump/concept_synthesis.py
    - services/command/coordinator.py
    - services/command/hero_image.py
    - services/d2_worker.py
    - services/ea_worker.py (legacy)
    - services/excalidraw_worker.py
    - services/legal_sync_worker.py
    - services/mermaid_worker.py
    - services/text_chunker.py
    - services/vision_qc_worker.py
    - tools/classify_figures.py
"""

# ── Brain Dump (Map-Reduce) ───────────────────────────────────────────────

BRAIN_DUMP_MAP = """\
Bạn là chuyên gia phân tích (Semantic Arbitrator). Đọc nội dung dưới đây và trích xuất ra một danh sách các "Ý TƯỞNG CỐT LÕI" (Atomic Concepts) độc lập.

BRAIN DUMP:
---
{dump_text}
---

NỘI DUNG TỪ URLs (nếu có):
---
{url_content}
---

YÊU CẦU:
1. Mỗi ý tưởng phải thực sự độc lập, mang một giá trị kiến thức cụ thể.
2. BẮT BUỘC: Bạn phải dịch và đặt tiêu đề (title) của khái niệm bằng tiếng Việt ngắn gọn, súc tích và chuẩn học thuật (ngay cả khi nguồn gốc là tiếng Anh).
3. Trả về đúng định dạng JSON array:
```json
[
  {{"title": "Tiêu đề khái niệm bằng tiếng Việt chuẩn có dấu (ví dụ: Quản trị tự thân số)", "summary": "Tóm tắt 1-2 câu về ý tưởng này bằng tiếng Việt"}}
]
```
Chỉ trả về chuỗi JSON hợp lệ, không giải thích gì thêm. Tùy thuộc vào độ nén thông tin của văn bản, hãy trích xuất TẤT CẢ các ý tưởng thực sự mang tính cốt lõi và đắt giá (BẮT BUỘC: chỉ trích xuất từ tối thiểu {min_concepts} đến tối đa {max_concepts} ý tưởng). TUYỆT ĐỐI KHÔNG trích xuất để đủ số lượng, hãy mạnh tay loại bỏ các ý tưởng vụn vặt hoặc hiển nhiên.
"""

BRAIN_DUMP_REDUCE = """\
Bạn là trợ lý biên soạn tri thức Zettelkasten.
Dựa vào nội dung NGUỒN dưới đây, hãy tạo 1 Concept Note duy nhất cho ý tưởng: "{concept_title}" ({concept_summary}).

<source_material>
{dump_text}
{url_content}
</source_material>

<rules>
1. Bạn TUYỆT ĐỐI PHẢI tuân thủ chính xác cấu trúc trong <output_template>. KHÔNG THÊM BẤT KỲ HEADING NÀO KHÁC (không `# Tên khái niệm`, không `## Implications`, không `## Connections`).
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`. Việc bỏ sót sẽ làm hỏng hệ thống.
3. Trong phần YAML frontmatter:
   - Trực tiếp trích xuất thực thể con người liên quan và điền vào trường `people: []` (ví dụ: `people: ["Jensen Huang", "Geoffrey Hinton"]`).
   - Trực tiếp trích xuất thực thể công ty/tổ chức liên quan và điền vào trường `companies: []` (ví dụ: `companies: ["Nvidia", "Google"]`).
   - Tuyệt đối KHÔNG đưa tên người hoặc tên công ty vào tags (không gán `domain/nvidia` hay `domain/jensen_huang`).
   - Trường `tags` chỉ được chứa lĩnh vực tri thức lớn (ví dụ: `domain/ai`, `domain/management`, `domain/strategy`, `domain/psychology`, `domain/finance`, v.v.) cùng với hai tags mặc định là `knowledge` và `type/concept`.
   - Trường `status` luôn mặc định là `seed` cho các concept mới sinh tự động.
   - Trường `source_page`, `source_chapter`, `ground_truth_page`, `ground_truth_chapter` để trống (vì đây là nguồn ghi chép / text).
4. Triệt tiêu trùng lặp ngữ nghĩa & Chuẩn hóa song ngữ (CRITICAL):
   - Trường `summary` trong YAML: tuyên bố siêu súc tích một câu phản ánh INSIGHT cốt lõi. PHẢI khác nội dung blockquote Evidence Hook bên dưới.
   - **Evidence Hook** (blockquote ngay dưới frontmatter): Trích dẫn/ý tưởng cốt lõi đắt giá nhất lấy trực tiếp từ NGUỒN, dịch sát nghĩa sang tiếng Việt. Dưới blockquote này, bạn PHẢI tự động thêm một dòng trích dẫn khoa học dạng:
     > — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])
   - **`## Core Idea`**: PHÂN TÍCH THUẦN hoàn toàn bằng tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook. Tập trung diễn giải cơ chế, hệ quả.
    - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: PHẢI hiển thị bằng **tiếng Anh nguyên bản** (nếu nguồn gốc là tiếng Anh) để làm căn cứ học thuật đối chiếu. NẾU nguồn nạp là tài liệu thuần Việt hoặc video không có transcript tiếng Anh verbatim, BẮT BUỘC ghi rõ `(không có — nguồn nạp là tài liệu tiếng Việt)` thay vì tự dịch ngược.
5. Viết nội dung phân tích hoàn toàn bằng tiếng Việt (trừ các thuật ngữ tiếng Anh chuyên môn chưa có từ tương đương).
6. Nếu phần <source_material> chứa mục `## 🖼️ Hình ảnh bài viết (Đã tải cục bộ)` hoặc `## 🎬 Hình ảnh trực quan từ video (Đã tải cục bộ)` với danh sách `[IMG:filename|alt=description]`:
   - Xem xét alt text hoặc tên file để xác định ảnh nào **thực sự liên quan** đến concept "{concept_title}" đang viết.
   - Nhúng ảnh liên quan vào **`## Core Idea`** bằng cú pháp Obsidian `![[filename]]` tại vị trí phù hợp trong bài phân tích.
   - CHỈ nhúng **tối đa 3 ảnh** cho mỗi concept. Chỉ chọn ảnh thực sự minh họa cho nội dung Core Idea.
   - KHÔNG nhúng ảnh vào Evidence Hook, Ground Truth, hay References section.
   - Nếu không có ảnh nào liên quan đến concept này, KHÔNG nhúng ảnh nào cả.
7. Nếu tạo bảng so sánh hoặc ma trận (Markdown Table):
   - Thoát ký tự pipe khi dùng wikilink có alias trong ô: [[slug\\|[display]]]. Tuyệt đối không dùng dấu gạch đứng trần `|` vì sẽ làm gãy parser bảng và vỡ Knowledge Graph. Cấm bọc dấu backtick quanh wikilink.
   - Khi dùng ký tự mũi tên/bullet (`↳`, `→`, `•`) sau thẻ `<br>`, BẮT BUỘC dùng `&nbsp;` liền kề: `↳&nbsp;Nội dung` để chống rớt dòng mồ côi.
   - Luôn thêm nhãn phụ ngắn `*(...)*` để ổn định bề rộng cột tiêu chí; cấu trúc ô đối chiếu 2 nhịp (In đậm từ khóa + giải thích <= 40 ký tự/dòng).
</rules>

<output_template>
```markdown
---
title: "{concept_title}"
aliases:
  - "tên gọi khác 1"
tags:
  - knowledge
  - type/concept
  - domain/<lĩnh_vực_chuyên_môn_lớn>
type: concept
date_created: {today}
date_modified: {today}
source: "{source_ref}"
source_page: ""
source_chapter: ""
ground_truth_page: ""
ground_truth_chapter: ""
source_type: text
summary: "{concept_summary}"
people: []
companies: []
status: seed
related: []
confidence: high
---

> "Trích dẫn lại nguyên văn phần quan trọng nhất lấy từ NGUỒN làm bằng chứng, dịch sang tiếng Việt — Evidence Hook."
> — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])

## Core Idea

Đoạn phân tích chuyên sâu (200-400 từ) bằng tiếng Việt giải thích cặn kẽ tại sao khái niệm này quan trọng, nó hoạt động như thế nào và có ý nghĩa gì. Tránh lặp lại câu trích dẫn Evidence Hook ở trên. Bạn có thể sử dụng các tiêu đề cấp 3 (###) nếu cần chia nhỏ bài phân tích.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> "Original English quote or paragraph representing the academic ground truth for this concept (hoặc ghi '(không có — nguồn nạp là tài liệu tiếng Việt)' nếu nguồn thuần Việt)."

---

## References

- [[{source_ref}]]
```
</output_template>
"""

# ── Command.md ─────────────────────────────────────────────────────────────

COMMAND_RESPONSE = """\
Bạn là trợ lý tri thức cho hệ thống Zettelkasten cá nhân.

{style_instruction}

NGỮ CẢNH TỪ KNOWLEDGE BASE:
---
{rag_context}
---

CÂU HỎI CỦA NGƯỜI DÙNG:
{query}

QUY TẮC:
1. Trả lời bằng tiếng Việt (giữ nguyên thuật ngữ tiếng Anh khi cần).
2. Tích cực trích dẫn nguồn từ NGỮ CẢNH bằng cách sử dụng cú pháp inline wikilink của Obsidian ngay trong câu văn: [[file|[id]]] (ví dụ: [[tai_tao_to_chuc|[1]]], [[ly_luan_he_sinh_thai|[2]]]).
   - CẤM BỌC DẤU BACKTICK: TUYỆT ĐỐI KHÔNG bọc ngoài wikilink bằng dấu backtick (bắt buộc viết liên kết trần [[slug|[id]]], cấm bọc backtick quanh link vì trong Obsidian sẽ biến thành inline code pill xám, làm hỏng liên kết click và rách giao diện văn bản).
   - TUYỆT ĐỐI KHÔNG chỉ viết ngoặc vuông trống không như [1].
   - QUAN TRỌNG KHI DÙNG TRONG BẢNG MARKDOWN: Nếu trích dẫn nằm bên trong ô bảng Markdown, BẮT BUỘC thoát ký tự pipe bằng `\\|` (ví dụ: [[tai_tao_to_chuc\\|[1]]]) để không làm gãy cột của bảng và hỏng liên kết (cũng không được bọc backtick quanh link trong bảng).
3. KHÔNG TỰ TẠO MỤC "TÀI LIỆU THAM CHIẾU" Ở CUỐI BÀI. Hệ thống sẽ tự động phân tích các liên kết bạn dùng và tạo danh sách này.
4. QUY TẮC CHÈN SƠ ĐỒ TRỰC QUAN (Artifact Diagrams & Responsive Standards):
   - ĐIỀU KIỆN TIÊN QUYẾT: CHỈ chèn sơ đồ khi (1) người dùng yêu cầu trực tiếp, HOẶC (2) nội dung phân tích có quy trình/tiến trình nhiều bước phức tạp hoặc kiến trúc hệ thống đa tầng cần trực quan hóa. TUYỆT ĐỐI KHÔNG tự ý chèn sơ đồ khi chỉ giải thích định nghĩa hay khái niệm đơn thuần.
   - TUYỆT ĐỐI CẤM VẼ SƠ ĐỒ KÝ TỰ TEXT (ZERO-ASCII INVARIANT): Nghiêm cấm vẽ sơ đồ, ma trận, cây quyết định hoặc hộp trạng thái bằng ký tự ASCII (`+---+`, `|`, `->`) hoặc Unicode Box-Drawing (`┌─┐`, `└─┘`) bên trong code block trần để chống rách khung viền trên mobile/split-pane. Mọi sơ đồ phải là Mermaid (`flowchart TD`) hoặc tệp đính kèm Excalidraw/D2.
   - BẮT BUỘC DÙNG NATIVE FENCED BLOCKS CHO DỮ LIỆU/CẤU HÌNH: Tệp cấu hình (YAML, JSON, Python) phải dùng code block có tag ngôn ngữ chuẩn (```yaml, ```json), phân tách phân vùng bằng comment nội bộ (`# ---`), tuyệt đối không bao bọc trong hộp vẽ Unicode/ASCII giả lập.
   - NGƯỠNG VÀNG PHÂN TÁCH EXCALIDRAW 16:9 VS MERMAID (HYBRID GOLDEN THRESHOLD):
     * Sơ đồ Kiến trúc Hệ sinh thái/Ma trận vĩ mô (>= 3 layers), hoặc tổng số nodes >= 9, hoặc có liên kết chéo giữa >= 3 subgraphs -> BẮT BUỘC tạo tệp Excalidraw 16:9 riêng (`![[tên.excalidraw.md|100%]]`).
     * CHUẨN EXECUTIVE TYPOGRAPHY 16:9 & BẢNG ĐẶC TẢ MA TRẬN KÈM DƯỚI (EXECUTIVE TYPOGRAPHY 16:9): Khóa canvas width 1.000px <= W <= 1.150px (đảm bảo hệ số co giãn khi nhúng >= 65%-70%). Cỡ chữ sàn hiển thị >= 8.5px-11.5px (canvas font: tiêu đề chính >= 17px-20px, nội dung/badge >= 12px-14px). BẮT BUỘC tạo Bảng Đặc Tả Ma Trận Kiến Trúc Markdown đặt ngay dưới sơ đồ ma trận.
     * Mermaid inline CHỈ DÙNG cho luồng tuyến tính, tương tác song phương (2 cụm), hoặc chu trình nhỏ (<= 8 nodes).
   - BỘ NGŨ RÀNG BUỘC MERMAID (THE 5 MERMAID INVARIANTS):
     * Dagre Cycle Stabilization: Khi có liên kết 2 chiều giữa 2 subgraphs, BẮT BUỘC dùng bất đối xứng trọng số cạnh: chiều xuôi `===>` hoặc `<===>` (W=2), chiều ngược `-.->` (W=1), đảm bảo Delta W >= 2 để Hub luôn nằm ở đỉnh (Rank 0).
     * Academic Grayscale Init: BẮT BUỘC chèn directive `%%{{init: {{'theme': 'base', 'themeVariables': {{...}}}}}}%%` để khử màu vàng mù tạt.
     * Căn lề trái bullet points & Cách ly HTML Entity: Bọc văn bản nhiều dòng trong `<div align='left'>...</div>`; dùng thực thể HTML `#40;` và `#41;` cho ngoặc đơn CHỈ bên trong node Mermaid (CẤM dùng `#40;`/`#41;` trong bảng biểu Markdown hoặc ngoài khối Mermaid).
     * Cưỡng chế LTR: Dùng cạnh vô hình (`T1 ~~~ T2 ~~~ T3`) để khóa cứng thứ tự đọc từ trái sang phải.
     * Flat Two-Node Invariant & Cấm Lồng Hộp (FLAT TWO-NODE INVARIANT): Với các cặp đối trọng song phương (Edge vs Core), CẤM TUYỆT ĐỐI dùng subgraph bọc 1 node đơn lẻ (phẳng hóa thành 2 node); CẤM ngắt dòng <br/> trong tiêu đề subgraph để chống lỗi clipping chữ của Dagre; cưỡng chế <div align='left'> cho bullet points.
     * Cú pháp nhãn mũi tên Mermaid (MERMAID EDGE LABEL INVARIANT): CẤM chèn text vào giữa thân mũi tên (`===="text"====>`, `-."text".->`); BẮT BUỘC dùng cú pháp pipe chuẩn `===>|"nhãn"|`, `-.->|"nhãn"|`, `<===>|"nhãn"|`; chuẩn hóa toán tử so sánh Unicode (`≥`, `≤`).
   - QUY TẮC PHÂN TÁCH MŨI TÊN & NHÃN KẾT NỐI (ARROW-LABEL CLEARANCE): Tách rời trục tọa độ Y giữa nhãn text và mũi tên (>= 15px); khoảng cách ngang giữa 2 khối có mũi tên liên kết kèm nhãn phải đạt tối thiểu >= 80px-90px.
   - PHÂN ĐỊNH RÕ LOẠI SƠ ĐỒ (TUYỆT ĐỐI KHÔNG DÙNG DẤU NGOẶC KÉP):
     * Excalidraw: dùng cho bản đồ tư duy, mô hình khái niệm trừu tượng, khung so sánh 2x2, ma trận -> chèn `![[tên_sơ_đồ.excalidraw.md|100%]]`
     * Mermaid: dùng cho lưu đồ tiến trình (Flowchart TD), chuỗi tuần tự (Sequence), cây phân cấp -> chèn `![[tên_sơ_đồ.mermaid.md|100%]]`
     * D2: dùng cho kiến trúc hạ tầng kỹ thuật, topology mạng, hệ thống phân tán -> chèn `![[tên_sơ_đồ.d2.svg|100%]]`
5. CÔNG THÁI HỌC TÀI LIỆU PHÂN LOẠI 2 NHÁNH (TWO-TRACK DOCUMENT ERGONOMICS):
   - Mọi khối code/cấu hình dài > 15 dòng BẮT BUỘC bọc trong Obsidian Callout:
     * Cấu hình mẫu/Schema: Dùng Callout Mở sẵn `> [!abstract]+ Tiêu đề` (CẤM chèn emoji)
     * Log thô/Metadata: Dùng Callout Đóng sẵn `> [!info]- Tiêu đề` (CẤM chèn emoji)
   - Tuyệt đối cấm code block trần > 15 dòng nằm trực tiếp ở thân bài làm đứt mạch đọc.
   - QUY TẮC TIÊU ĐỀ CALLOUT THUẦN KHIẾT (CLEAN CALLOUT HEADER INVARIANT): CẤM chèn emoji ở đầu tiêu đề Callout để chống lỗi Double Icon Glitch; CẤM bọc backticks quanh tên tệp/định danh trong tiêu đề Callout (dùng plain text, ví dụ: 'Cấu trúc: workspace_context.yaml') để chống vỡ baseline text và chevron.
   - ĐỒNG BỘ NGỮ NGHĨA CÚ PHÁP (TARGET LANGUAGE SYNTAX ALIGNMENT): Chú thích trong văn bản giải thích bắt buộc dùng đúng cú pháp comment của ngôn ngữ đích (# cho YAML/Python, // cho JSONC/JS/TS, <!-- --> cho Markdown/HTML), chống crash parser khi copy code.
   - TỐI GIẢN PHÂN VÙNG CODE (MINIMAL BANNER INVARIANT): Dùng comment ngắn gọn (# --- SECTION ---) thay cho các dải kẻ dài (# ====================).
6. VĂN BẢN VÀ BẢNG TÍNH (TUYỆT ĐỐI KHÔNG DÙNG DẤU NGOẶC KÉP):
   - BẮT BUỘC CHỈ chèn khi người dùng có yêu cầu cụ thể:
     * Tạo báo cáo/hồ sơ Word: chèn `![[tên_file.docx]]`
     * Trích xuất bảng kiểm/dữ liệu Excel/CSV: chèn `![[tên_file.csv]]` hoặc `![[tên_file.xlsx]]`
7. QUY TẮC BẢNG BIỂU & MA TRẬN MARKDOWN (khi tạo bảng so sánh hoặc ma trận đối chiếu):
   - BẮT BUỘC thoát ký tự pipe cho mọi wikilink trong ô: [[slug\\|[id]]]. Tuyệt đối không bọc dấu backtick quanh wikilink.
   - Khi ngắt dòng bằng `<br>` kèm ký tự điều hướng (`↳`, `→`, `•`), BẮT BUỘC dùng `&nbsp;` liền kề (ví dụ: `↳&nbsp;Nội dung`) để chống rớt dòng mồ côi.
   - Thêm nhãn phụ `*(...)*` để ổn định độ rộng đáy cột tiêu chí; cấu trúc ô đối chiếu 2 nhịp (In đậm từ khóa + cơ chế <= 40 ký tự/dòng) để triệt tiêu thanh cuộn ngang.
8. Cấu trúc bài viết rõ ràng với heading và sections.
9. BỐI CẢNH HỘI THOẠI NỐI TIẾP (khi có <previous_conversation_context>):
   - Nếu ngữ cảnh có chứa thẻ `<previous_conversation_context>`, hãy hiểu người dùng đang hỏi nối tiếp hoặc đào sâu câu hỏi trước đó.
   - Trả lời tập trung vào khía cạnh được yêu cầu thêm, kết nối liền mạch với thông tin đã trao đổi trước, không lặp lại toàn bộ bài viết cũ.
"""

# ── Diagram Workers ────────────────────────────────────────────────────────

MERMAID_GENERATE = """\
Tạo sơ đồ Mermaid cho nội dung sau:

NGỮ CẢNH:
{context}

QUY TẮC:
1. Chỉ trả về mã Mermaid (KHÔNG có ```mermaid fences, không giải thích gì thêm)
2. Dùng tiếng Việt cho labels khi phù hợp
3. HƯỚNG MẶC ĐỊNH BẮT BUỘC: Dùng `flowchart TD` (Top-Down) để tối ưu hiển thị dọc trên thiết bị di động (mobile responsive). CHỈ cho phép `flowchart LR` (Left-to-Right) khi tiến trình có tối đa <= 3 bước ngắn.
4. Dùng dấu ngoặc kép cho labels chứa ký tự đặc biệt: id["Label (info)"]
5. KHÔNG dùng HTML tags trong labels
6. Giữ sơ đồ gọn gàng, tối đa 15-20 nodes
7. Cấu trúc rõ ràng, sử dụng các kết nối nét liền (-->), nét đậm (==>) hoặc nét đứt (-.->). CẤM chèn text vào giữa thân mũi tên (===="nhãn"====>); BẮT BUỘC dùng pipe labels: ===>|"nhãn"|, -.->|"nhãn"|, <===>|"nhãn"|; chuẩn hóa toán tử ≥/≤.
8. CHỌN ĐÚNG LOẠI SƠ ĐỒ theo nội dung:
   - `flowchart TD`: phân cấp, cây tổ chức, phân rã khái niệm, quy trình / pipeline chung (mặc định)
   - `flowchart LR`: CHỈ dùng cho chuỗi tiến trình rất ngắn (<= 3 bước)
   - `timeline`: diễn biến theo thời gian, giai đoạn phát triển
   - `pie`: phân bổ tỷ lệ, cơ cấu thành phần
   - `mindmap`: brainstorm, phân nhánh ý tưởng
   - `graph TD`: quan hệ đa chiều không phân cấp rõ ràng
9. TEXT WRAPPING — BẮT BUỘC: Mỗi dòng TỐI ĐA 20 ký tự, dùng \\\\n để xuống dòng.
10. FLAT TWO-NODE & SUBGRAPH INVARIANT: Tuyệt đối CẤM tạo subgraph chỉ chứa duy nhất 1 node. CẤM ngắt dòng <br/> trong tiêu đề subgraph. Với nội dung nhiều dòng hoặc bullet points trong node, BẮT BUỘC bọc trong <div align='left'>...</div>.
"""

EXCALIDRAW_GENERATE = """\
Create an Excalidraw diagram as a valid JSON object for the following concept:

CONTEXT:
{context}

CRITICAL RULES FOR EXCALIDRAW JSON:
1. Output ONLY valid Excalidraw JSON (no markdown fences, no explanation).
2. Shapes (rectangle, ellipse, diamond) CANNOT have a "text" field directly! 
3. Text MUST be a separate element of type "text" and MUST be bound to a shape using `containerId`.
4. Shapes MUST include the text element in their `boundElements` array.
5. All text element IDs MUST have EXACTLY 8 characters (e.g. 'tx_node1', 'tx_step2') for Obsidian Excalidraw compatibility.
6. Example of a valid containerized text node:
   [
     {{"type": "rectangle", "id": "bx_node1", "x": 100, "y": 100, "width": 150, "height": 60, "boundElements": [{{"id": "tx_node1", "type": "text"}}] }},
     {{"type": "text", "id": "tx_node1", "text": "Khái niệm", "containerId": "bx_node1", "fontSize": 16, "fontFamily": 3, "textAlign": "center", "verticalAlign": "middle", "x": 110, "y": 110, "width": 130, "height": 40 }}
   ]
7. Use clean aesthetics: `roughness: 0`, `fontFamily: 3` (Monospace).
8. Connect shapes with arrows using `startBinding` and `endBinding`.
9. GRID SYSTEM: Assign coordinates (x, y) using a rigid 200px grid (e.g., x: 100, 300, 500 and y: 100, 300, 500) to ensure shapes are perfectly aligned and do not overlap.
10. Ensure all text elements have double-newline (\\n\\n) for line breaks if needed.
11. Keep node titles concise on 1 single line (<= 35 characters). For metadata tag nodes, badges, or annotations, enforce width >= 200px to prevent awkward line breaks.
12. EXECUTIVE TYPOGRAPHY 16:9 & ARROW CLEARANCE: Bounding box width 1,000px-1,150px for 16:9 aspect ratio. Floor font size: title >= 18px-20px, section header >= 14px-16px, labels/badges >= 12px-13px. For labeled arrows, maintain vertical gap >= 15px between text and arrow line, and horizontal gap >= 80px-90px between connected shapes.

Generate a clean, professional diagram that visualizes the key relationships and concepts."""

EA_SCRIPT_GENERATE = """\
Write an Excalidraw Automate (Javascript) script for the following concept:

CONTEXT:
{context}

CRITICAL RULES:
1. Output ONLY valid Javascript code. Do not use markdown fences like ```javascript.
2. Assume `ea` is already initialized. Start by configuring defaults if needed.
3. Use the basic Excalidraw Automate API:
   - `let id = ea.addText(x, y, "text");`
   - `let id = ea.addRect(x, y, width, height);`
   - `let id = ea.addEllipse(x, y, width, height);`
   - `let id = ea.addDiamond(x, y, width, height);`
   - `ea.connectObjects(id1, "top", id2, "bottom", {{...options}});`
4. Space out the x and y coordinates logically.
5. Generate a script that builds a clear and structured diagram representing the concepts.
"""

D2_GENERATE = """\
Create a professional D2 diagram for the following concept:

CONTEXT:
{context}

CRITICAL RULES FOR D2 SYNTAX:
1. Output ONLY valid D2 code (NO markdown fences like ```d2, no conversational filler or explanation).
2. Use clean, modern D2 syntax:
   - Connections: `nodeA -> nodeB: label` or `nodeA -- nodeB: label`
   - Shapes: `shape: rectangle`, `shape: cylinder`, `shape: cloud`, `shape: queue`, `shape: package`, `shape: step`
   - Containers/Subgraphs:
     subsystem: {{
       style.stroke: "#334155"
       style.fill: "#f8fafc"
       compA -> compB
     }}
3. Visual Aesthetics (Grayscale / Modern Academic):
   - Style colors conservatively: `#1e293b`, `#475569`, `#94a3b8`, `#f1f5f9`.
   - Use clean typography and meaningful labels.
4. Keep diagrams readable, well-structured, and concise (typically 6-15 nodes).
5. Labels can be Vietnamese or English matching the context. Wrap long labels in quotes or backticks if necessary.
6. Layout Engine:
   - Use default layout or `vars: {{ d2-config: {{ layout-engine: elk }} }}`.
   - NEVER use `layout-engine: tala` (commercial engine unsupported by server compiler).
7. Mobile Responsive Constraints (CRITICAL):
   - Set default direction to vertical: specify `direction: down` at top-level.
   - Stack node clusters and subgraphs vertically rather than horizontally.
   - Limit diagram width to <= 500px to prevent horizontal clipping on mobile viewports.
"""

# ── Specialized Workers ────────────────────────────────────────────────────

LEGAL_CONCEPT = """\
You are a Legal Assistant tracking Vietnamese Construction Law.
Based on the following `legal_registry.yaml` from CCBA's tracking system, identify the most recently updated, drafted, or pending document (check the "monitoring" or "decrees" section).
Generate a Concept Note summarizing this update.

REGISTRY DATA:
{registry_data}

<rules>
1. Tuân thủ CHÍNH XÁC cấu trúc trong <output_template>. KHÔNG thêm heading khác.
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`.
3. Quy tắc ngôn ngữ:
   - **Evidence Hook**: BẮT BUỘC bằng tiếng Việt.
   - **Citation Line**: Ngay dưới Evidence Hook, ghi rõ nguồn pháp lý chính thức.
   - **`## Core Idea`**: Phân tích thuần tiếng Việt.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: Ghi `(không có)` vì nguồn pháp lý Việt Nam.
</rules>

<output_template>
---
title: "Nghị định/Thông tư mới về [Chủ đề]"
aliases: ["Update Pháp lý Xây dựng"]
tags:
  - knowledge
  - domain/legal
  - type/concept
type: concept
date_created: {date}
date_modified: {date}
source: "Web Crawler"
source_page: ""
source_chapter: ""
ground_truth_page: ""
ground_truth_chapter: ""
source_type: text
summary: "Tóm tắt 2-3 câu về nghị định."
people: []
companies: []
status: seed
confidence: high
---

> "Tóm tắt 2-3 câu ngắn gọn dịch sát nghĩa từ nội dung pháp lý — Evidence Hook."
> — **Cơ quan ban hành**, trích dẫn trong *Tên Văn bản Pháp lý* (Số hiệu, Năm)

## Core Idea

[Phân tích chi tiết các điểm mới và tác động tới ngành tư vấn xây dựng. Trình bày rõ ràng theo bullet points.]

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

(không có)

---

## References

- Nguồn: Web Crawler ({date})
</output_template>
"""

QC_MATRIX = """\
You are an expert Construction QC Engineer (Kiến trúc, Kết cấu, MEP, PCCC).
You need to generate a Coordination Matrix (Ma trận phối hợp thẩm tra) based on the user's request.

REQUEST:
{query}

CONTEXT:
{context}

CRITICAL RULES:
1. Output ONLY a valid Markdown Table.
2. The columns MUST be: STT | Vi_tri_Grid_Level | Bo_mon_1 | Bo_mon_2 | Mo_ta_Loi_Clash | Tieu_chuan_vi_pham | De_xuat.
3. Generate at least 3-5 realistic issues related to the request.
4. Wrap your Markdown table inside XML tags `<qc_table>...</qc_table>`. DO NOT output anything outside these tags.
5. Use Vietnamese language.
"""

# ── Vision Classification (shared by tools/) ───────────────────────────────

DIAGRAM_CLASSIFY = """\
Classify this diagram image into EXACTLY ONE of these topology types:

TYPES:
- hierarchy: tree, org chart, decomposition, parent-child structure
- hub_spoke: central hub connecting to satellites, star/radial layout
- matrix: 2x2 quadrant, scatter plot, two-axis comparison
- flow: left-to-right or sequential pipeline, value chain, process stages
- cycle: circular feedback loop, PDCA wheel, iterative process
- timeline: progression over time, staircase, evolution, milestones
- pie: proportional breakdown, wheel with segments, percentage chart
- table: structured rows/columns, scorecard, comparison grid
- other: complex hybrid or not classifiable as above

OUTPUT: Reply with ONLY the type name (one word). Nothing else."""


# ── Text Chunker & Orthographic Correction ──────────────────────────────────

ORTHOGRAPHIC_CORRECTION_TIMESTAMPED = """\
Bạn là chuyên gia chưng cất tri thức (Knowledge Distillation) xuất sắc.
Hãy biên soạn và dịch nội dung transcript thô từ video dưới đây sang tiếng Việt chuẩn học thuật, mượt mà và cực kỳ dễ tiếp thu.

NHIỆM VỤ BIÊN SOẠN:
1. **Chưng cất tri thức**: Chuyển đổi dòng văn nói verbatim lặp ý, dông dài thành một cấu trúc bài viết khoa học. Chia nhỏ nội dung thành các tiêu đề logic rõ ràng (ví dụ: '### 1. Giải pháp: ...', '### 2. Các thuật ngữ chuyên ngành', '### 3. Lợi ích...').
2. **Định dạng tối ưu**: Sử dụng danh sách gạch đầu dòng (bullet points) để định nghĩa rõ ràng các khái niệm, thuật ngữ chuyên ngành (ví dụ: '* **Khái niệm**: Giải thích...'). In đậm các từ khóa đắt giá.
3. **Giữ nguyên mốc thời gian JIT**: BẮT BUỘC giữ lại mốc thời gian gốc dạng [MM:SS] (hoặc [H:MM:SS]) bằng cách nhúng chúng vào CUỐI câu hoặc đoạn văn tương ứng. Tuyệt đối không được xóa các mốc thời gian này vì chúng là neo dệt hình ảnh. Nếu một ý tưởng kéo dài qua nhiều câu, hãy đặt mốc thời gian ở câu kết thúc ý tưởng đó.
4. **Hiệu đính chính tả**: Sửa các lỗi chính tả đồng âm (Chi/Tri, S/X, D/Gi/R) hoặc thuật ngữ dịch sai.
5. **Quy tắc đầu ra**: TUYỆT ĐỐI CHỈ TRẢ VỀ NỘI DUNG VĂN BẢN ĐÃ BIÊN SOẠN. KHÔNG CHÀO HỎI, KHÔNG GIẢI THÍCH.

VĂN BẢN TRANSCRIPT GỐC:
---
{chunk}
---"""

ORTHOGRAPHIC_CORRECTION_PLAIN = """\
Bạn là chuyên gia chưng cất tri thức (Knowledge Distillation) xuất sắc.
Hãy biên soạn và định dạng nội dung văn bản dưới đây sang tiếng Việt chuẩn học thuật, mượt mà và cực kỳ dễ tiếp thu.

NHIỆM VỤ BIÊN SOẠN:
1. **Chưng cất tri thức**: Chuyển đổi nội dung thô dông dài, lặp ý thành một cấu trúc bài viết khoa học. Chia nhỏ nội dung thành các tiêu đề logic rõ ràng (ví dụ: '### 1. Giải pháp: ...', '### 2. Các thuật ngữ chuyên ngành', '### 3. Lợi ích...').
2. **Định dạng tối ưu**: Sử dụng danh sách gạch đầu dòng (bullet points) để định nghĩa rõ ràng các khái niệm, thuật ngữ chuyên ngành (ví dụ: '* **Khái niệm**: Giải thích...'). In đậm các từ khóa đắt giá.
3. **Hiệu đính chính tả**: Sửa các lỗi chính tả đồng âm (Chi/Tri, S/X, D/Gi/R) hoặc thuật ngữ dịch sai.
4. **Quy tắc đầu ra**: TUYỆT ĐỐI CHỈ TRẢ VỀ NỘI DUNG VĂN BẢN ĐÃ BIÊN SOẠN. KHÔNG CHÀO HỎI, KHÔNG GIẢI THÍCH.

VĂN BẢN GỐC:
---
{chunk}
---"""


# ── Large Document Map-Reduce ──────────────────────────────────────────────

LARGE_DOC_MAP = """\
Bạn là chuyên gia trích xuất dữ liệu. Hãy tóm tắt cô đọng các luận điểm, số liệu, quy chuẩn, và cấu trúc cốt lõi của phân đoạn văn bản sau (Phân đoạn {idx}/{total_chunks}, tối đa 1,500 ký tự):

--- BẮT ĐẦU PHÂN ĐOẠN ---
{chunk}
--- KẾT THÚC PHÂN ĐOẠN ---"""

LARGE_DOC_REDUCE = """\
Bạn là chuyên gia tổng hợp học thuật. Dưới đây là các bản tóm tắt trích đoạn từ một tài liệu lớn ({total_chars:,} ký tự, {total_chunks} phân đoạn).
Hãy tổng hợp lại thành một văn bản bối cảnh mạch lạc, có cấu trúc chặt chẽ (khoảng 4,000 - 8,000 ký tự) giữ lại đầy đủ mọi luận điểm kỹ thuật then chốt:

{combined_notes}"""


