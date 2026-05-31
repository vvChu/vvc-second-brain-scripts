"""VvC Second Brain — Services Prompt Registry.

Centralized prompt templates for interactive services and workers.
Prompts with placeholders use str.format(); static prompts are used as-is.

Modules that consume these prompts:
    - services/brain_dump/concept_synthesis.py
    - services/command.py
    - services/ea_worker.py
    - services/excalidraw_worker.py
    - services/legal_sync_worker.py
    - services/mermaid_worker.py
    - services/vision_qc_worker.py
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
     `> — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])`
   - **`## Core Idea`**: PHÂN TÍCH THUẦN hoàn toàn bằng tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook. Tập trung diễn giải cơ chế, hệ quả.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: PHẢI hiển thị bằng **tiếng Anh nguyên bản** (nếu nguồn gốc là tiếng Anh) để làm căn cứ học thuật đối chiếu. Nếu nguồn hoàn toàn bằng tiếng Việt, hãy ghi rõ "(không có)".
5. Viết nội dung phân tích hoàn toàn bằng tiếng Việt (trừ các thuật ngữ tiếng Anh chuyên môn chưa có từ tương đương).
6. Nếu phần <source_material> chứa mục `## 🖼️ Hình ảnh bài viết (Đã tải cục bộ)` hoặc `## 🎬 Hình ảnh trực quan từ video (Đã tải cục bộ)` với danh sách `[IMG:filename|alt=description]`:
   - Xem xét alt text hoặc tên file để xác định ảnh nào **thực sự liên quan** đến concept "{concept_title}" đang viết.
   - Nhúng ảnh liên quan vào **`## Core Idea`** bằng cú pháp Obsidian `![[filename]]` tại vị trí phù hợp trong bài phân tích.
   - CHỈ nhúng **tối đa 3 ảnh** cho mỗi concept. Chỉ chọn ảnh thực sự minh họa cho nội dung Core Idea.
   - KHÔNG nhúng ảnh vào Evidence Hook, Ground Truth, hay References section.
   - Nếu không có ảnh nào liên quan đến concept này, KHÔNG nhúng ảnh nào cả.
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

> "Original English quote or paragraph representing the academic ground truth for this concept."

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
2. Tích cực trích dẫn nguồn từ NGỮ CẢNH bằng cách sử dụng cú pháp inline wikilink của Obsidian ngay trong câu văn: `[[file|[id]]]` (ví dụ: `[[tai_tao_to_chuc|[1]]]`, `[[ly_luan_he_sinh_thai|[2]]]`). TUYỆT ĐỐI KHÔNG chỉ viết ngoặc vuông trống không như `[1]`.
3. KHÔNG TỰ TẠO MỤC "TÀI LIỆU THAM CHIẾU" Ở CUỐI BÀI. Hệ thống sẽ tự động phân tích các liên kết bạn dùng và tạo danh sách này.
4. Vẽ sơ đồ: chèn ![[tên_sơ_đồ.excalidraw.md|100%]] hoặc ![[tên_sơ_đồ.mermaid.md|100%]] (TUYỆT ĐỐI KHÔNG DÙNG DẤU NGOẶC KÉP)
5. Tạo báo cáo/hồ sơ Word: chèn ![[tên_file.docx]] (TUYỆT ĐỐI KHÔNG DÙNG DẤU NGOẶC KÉP)
6. Trích xuất Excel/CSV: chèn ![[tên_file.csv]] hoặc ![[tên_file.xlsx]] (TUYỆT ĐỐI KHÔNG DÙNG DẤU NGOẶC KÉP)
7. Cấu trúc bài viết rõ ràng với heading và sections.
"""

# ── Diagram Workers ────────────────────────────────────────────────────────

MERMAID_GENERATE = """\
Tạo sơ đồ Mermaid cho nội dung sau:

NGỮ CẢNH:
{context}

QUY TẮC:
1. Chỉ trả về mã Mermaid (KHÔNG có ```mermaid fences, không giải thích gì thêm)
2. Dùng tiếng Việt cho labels khi phù hợp
3. Ưu tiên flowchart TD (Top-Down) cho sơ đồ cây/phân cấp hoặc flowchart LR (Left-to-Right) cho các chuỗi tuyến tính/tiến trình
4. Dùng dấu ngoặc kép cho labels chứa ký tự đặc biệt: id["Label (info)"]
5. KHÔNG dùng HTML tags trong labels
6. Giữ sơ đồ gọn gàng, tối đa 15-20 nodes
7. Cấu trúc rõ ràng, sử dụng các kết nối nét liền (-->), nét đậm (==>) hoặc nét đứt (-.->)
8. CHỌN ĐÚNG LOẠI SƠ ĐỒ theo nội dung:
   - `flowchart TD`: phân cấp, cây tổ chức, phân rã khái niệm
   - `flowchart LR`: chuỗi tiến trình, pipeline, value chain ngang
   - `timeline`: diễn biến theo thời gian, giai đoạn phát triển
   - `pie`: phân bổ tỷ lệ, cơ cấu thành phần
   - `mindmap`: brainstorm, phân nhánh ý tưởng
   - `graph TD`: quan hệ đa chiều không phân cấp rõ ràng
9. TEXT WRAPPING — BẮT BUỘC: Mỗi dòng TỐI ĐA 20 ký tự, dùng \\\\n để xuống dòng.
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
5. Example of a valid containerized text node:
   [
     {{"type": "rectangle", "id": "rect1", "x": 100, "y": 100, "width": 150, "height": 60, "boundElements": [{{"id": "txt1", "type": "text"}}] }},
     {{"type": "text", "id": "txt1", "text": "Khái niệm", "containerId": "rect1", "fontSize": 16, "fontFamily": 3, "textAlign": "center", "verticalAlign": "middle", "x": 110, "y": 110, "width": 130, "height": 40 }}
   ]
6. Use clean aesthetics: `roughness: 0`, `fontFamily: 3` (Monospace).
7. Connect shapes with arrows using `startBinding` and `endBinding`.
8. GRID SYSTEM: Assign coordinates (x, y) using a rigid 200px grid (e.g., x: 100, 300, 500 and y: 100, 300, 500) to ensure shapes are perfectly aligned and do not overlap.
9. Ensure all text elements have double-newline (\\n\\n) for line breaks if needed.

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
