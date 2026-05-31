"""VvC Second Brain — Pipeline Prompt Registry.

Centralized prompt templates for the ingestion pipeline stages.
Prompts with placeholders use str.format(); static prompts are used as-is.

Modules that consume these prompts:
    - pipeline/ocr.py
    - pipeline/ground_truth.py
    - pipeline/synthesize.py
    - pipeline/self_correct.py
    - pipeline/map_reduce.py
    - pipeline/process_markdown.py
"""

# ── OCR Stage ──────────────────────────────────────────────────────────────

OCR_EXTRACT = """\
BƯỚC 1: Tìm số trang trong ảnh. Trả lời: PAGE: [số] hoặc PAGE: NONE

BƯỚC 2: Đọc toàn bộ văn bản trong ảnh. Phân loại thành 2 phần:

[HIGHLIGHTED]
Phần text được highlight/gạch chân/đánh dấu bằng bút. Đây là nội dung quan trọng nhất.

[CONTEXT]
Phần text không được đánh dấu nhưng nằm trên cùng trang. Đây là ngữ cảnh bổ sung.

QUY TẮC QUAN TRỌNG:
- Đọc chính xác từng chữ, KHÔNG dịch, KHÔNG tóm tắt
- Nối các dòng bị đứt gãy thành đoạn văn mạch lạc
- Nếu không có highlight, đặt toàn bộ text vào [HIGHLIGHTED]
- Bỏ qua header/footer trang (số trang, tên chương in hoa)
"""

TOC_EXTRACT = """\
Đây là ảnh chụp Mục lục (Table of Contents) của sách.
Hãy trích xuất thông tin dưới dạng JSON theo đúng cấu trúc sau:
{
  "book_title_vi": "Tên sách tiếng Việt",
  "book_title_original": "Tên sách gốc (nếu nhìn thấy, không thì copy title_vi)",
  "chapters": [
    {
      "chapter_num": 1,
      "title_vi": "Tên chương tiếng Việt",
      "title_original": "Tên chương gốc (nếu có, không thì copy title_vi)",
      "description_vi": null,
      "epub_file": null,
      "page_start": 15
    }
  ]
}
Chỉ trả về JSON, không giải thích.
"""

TOC_ALIGNMENT = """\
Đây là ảnh chụp Mục lục (Table of Contents) bằng tiếng Việt của một cuốn sách.
Dưới đây là cấu trúc chương sách gốc (tiếng Anh/tiếng bản ngữ) đã được hệ thống trích xuất từ trước:
---
{original_toc}
---

NHIỆM VỤ CỦA BẠN:
1. Đọc kỹ mục lục tiếng Việt trong ảnh chụp.
2. Dịch/So khớp từng chương từ ảnh chụp tiếng Việt với danh sách chương gốc tương ứng.
3. Bổ sung các trường sau vào từng chương trong JSON có sẵn:
   - "title_vi": "Tiêu đề tiếng Việt từ ảnh chụp"
   - "page_start": Số trang bắt đầu của chương này trên sách tiếng Việt ảnh chụp (kiểu integer).
   - "description_vi": "Mô tả ngắn tiếng Việt (nếu có)"
4. Tuyệt đối GIỮ NGUYÊN các trường "epub_file" và "title_original" của cấu trúc ban đầu để không làm mất liên kết tệp.
5. Cập nhật thêm "book_title_vi" ở gốc của JSON.
6. Nếu có chương mới trên mục lục tiếng Việt không khớp với chương nào trong template, hãy thêm mới chương đó với "epub_file": null.

Chỉ trả về JSON hoàn chỉnh sau khi cập nhật, không giải thích.
"""

# ── Ground Truth Stage ─────────────────────────────────────────────────────

OCR_CORRECTION = """\
Bạn là chuyên gia hiệu đính OCR tiếng Việt.

ĐOẠN OCR (có thể lỗi):
---
{ocr_text}
---

ĐOẠN GỐC TIẾNG ANH (Ground Truth):
---
{ground_truth}
---

NHIỆM VỤ: Sửa lỗi OCR, nối dòng đứt gãy, giữ nguyên tiếng Việt, KHÔNG dịch, KHÔNG giải thích.
Trả về TRỰC TIẾP đoạn văn đã sửa."""

# ── Self-Correction Stage ──────────────────────────────────────────────────

BLOCKQUOTE_VERIFY = """\
So sánh đoạn trích dẫn (blockquote) dưới đây với bản gốc tiếng Anh.

BLOCKQUOTE (từ concept note):
---
{blockquote}
---

GROUND TRUTH (bản gốc tiếng Anh):
---
{ground_truth}
---

NHIỆM VỤ:
1. Kiểm tra xem blockquote có phản ánh ĐÚNG nội dung Ground Truth không
2. Tìm các lỗi OCR còn sót: ký tự sai, thiếu dấu, thừa/thiếu từ
3. Nếu có lỗi, trả về blockquote ĐÃ SỬA (bắt đầu bằng "> ")
4. Nếu không có lỗi, trả về CHÍNH XÁC: "OK"

CHỈ trả về "OK" hoặc blockquote đã sửa. KHÔNG giải thích."""

# ── Synthesis Stage ────────────────────────────────────────────────────────

CONCEPT_SYNTHESIS = """\
Bạn là trợ lý biên soạn tri thức cho hệ thống Zettelkasten cá nhân.

THÔNG TIN NỀN VĨ MÔ CỦA CUỐN SÁCH:
{book_macro_context}

NHIỆM VỤ: Tạo 1 Concept Note tiếng Việt từ nội dung dưới đây.

<source_material>
NỘI DUNG HIGHLIGHT (đã sửa OCR):
---
{highlighted}
---

NGỮ CẢNH BỔ SUNG:
---
{context}
---

GROUND TRUTH (bản gốc tiếng Anh):
---
{ground_truth}
---
</source_material>

NGUỒN: {source_name}
CHƯƠNG: {chapter}
TRANG: {page}

<rules>
1. Bạn TUYỆT ĐỐI PHẢI tuân thủ chính xác cấu trúc trong <output_template>. KHÔNG THÊM BẤT KỲ HEADING NÀO KHÁC (không `# Tên khái niệm`, không `## Implications`, không `## Connections`).
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`. Việc bỏ sót sẽ làm hỏng hệ thống.
3. Trong phần YAML frontmatter:
   - Trực tiếp trích xuất thực thể con người liên quan và điền vào trường `people: []` (ví dụ: `people: ["Jensen Huang", "Geoffrey Hinton"]`).
   - Trực tiếp trích xuất thực thể công ty/tổ chức liên quan và điền vào trường `companies: []` (ví dụ: `companies: ["Nvidia", "Google"]`).
   - Tuyệt đối KHÔNG đưa tên người hoặc tên công ty vào tags (không gán `domain/nvidia` hay `domain/jensen_huang`).
   - Trường `tags` chỉ được chứa lĩnh vực tri thức lớn (ví dụ: `domain/ai`, `domain/management`, `domain/strategy`, `domain/psychology`, `domain/finance`, v.v.) cùng với hai tags mặc định là `knowledge` và `type/concept`.
   - Trường `status` luôn mặc định là `seed` cho các concept mới sinh tự động.
   - Trường `source_page` và `source_chapter` điền theo giá trị `{page}` và `{chapter_ref}`.
   - Trường `ground_truth_page` và `ground_truth_chapter` điền theo giá trị `{gt_page}` và `{gt_chapter_ref}`.
4. Triệt tiêu trùng lặp ngữ nghĩa & Chuẩn hóa song ngữ (CRITICAL):
   - Trường `summary` trong YAML: câu tuyên bố siêu súc tích phản ánh INSIGHT cốt lõi. PHẢI khác nội dung blockquote Evidence Hook bên dưới.
   - **Evidence Hook** (blockquote ngay dưới frontmatter): trích dẫn nguyên văn bằng tiếng Việt sát nghĩa nhất của phần highlight nguồn. Dưới blockquote này, bạn PHẢI tự động thêm một dòng trích dẫn khoa học dạng:
     `> — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])`
   - **`## Core Idea`**: PHÂN TÍCH THUẦN hoàn toàn bằng tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook. Tập trung diễn giải cơ chế, hệ quả, và kết nối với các khái niệm liên quan.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: PHẢI hiển thị bằng **tiếng Anh nguyên bản** lấy từ nguồn thô làm căn cứ học thuật để người đọc đối chiếu.
5. Viết nội dung phân tích hoàn toàn bằng tiếng Việt (trừ các thuật ngữ tiếng Anh chuyên môn chưa có từ tương đương).
6. Tên file (title) và aliases viết ở Title Case hoặc snake_case.
7. Tham chiếu tới tác giả hoặc ngữ cảnh từ {source_display} nếu cần.
8. Sử dụng hệ thống thuật ngữ nhất quán với từ điển định nghĩa trong thẻ <GLOSSARY> của THÔNG TIN NỀN VĨ MÔ (nếu có).
9. Tuân thủ nghiêm ngặt các chỉ dẫn biên soạn (khẩu vị phân rã, văn phong) được định nghĩa trong thẻ <COMPILATION_GUIDELINES> của THÔNG TIN NỀN VĨ MÔ (nếu có).
10. Sử dụng thông tin nhân vật và tổ chức định nghĩa sẵn trong thẻ <PEOPLE_AND_ORGANIZATIONS> (nếu có) để chuẩn hóa và hỗ trợ điền chính xác trường `people` và `companies` trong frontmatter.
</rules>

<output_template>
```markdown
---
title: "Tên khái niệm ngắn gọn"
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
source_page: "{page}"
source_chapter: "{chapter_ref}"
ground_truth_page: "{gt_page}"
ground_truth_chapter: "{gt_chapter_ref}"
source_type: image
summary: "Tuyên bố một câu đúc rút insight cốt lõi. KHÔNG lặp lại blockquote Evidence Hook bên dưới."
people: []
companies: []
status: seed
related: []
confidence: high
---

> "Trích dẫn lại nguyên văn phần quan trọng nhất (thường là NỘI DUNG HIGHLIGHT) dịch sát nghĩa sang tiếng Việt — Evidence Hook."
> — **Tên Tác Giả/Người Phát Biểu**, trích dẫn trong sách/bài viết *Tên Sách/Bài Viết* (Tên Nguồn phụ, [[{source_ref}|Tên Nguồn chính, Năm]])

## Core Idea

Đoạn phân tích thuần sâu sắc bằng tiếng Việt, giải thích cặn kẽ tại sao khái niệm này quan trọng, nó hoạt động như thế nào và có ý nghĩa gì. (Dài khoảng 150-300 từ). Tránh lặp lại câu trích dẫn Evidence Hook ở trên, thay vào đó hãy đi sâu phân tích cơ chế và hệ quả. Bạn có thể dùng các tiêu đề phụ (###) nếu cần.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> {ground_truth_excerpt}

---

## References

- [[{source_ref}]]
```
</output_template>
"""

# ── Map-Reduce Stage ───────────────────────────────────────────────────────

TOPIC_SEGMENTATION = """\
Bạn là chuyên gia phân tích ngữ nghĩa cho hệ thống Zettelkasten cá nhân.

THÔNG TIN NỀN VĨ MÔ CỦA CUỐN SÁCH:
{book_macro_context}

NHIỆM VỤ:
Đọc kỹ toàn bộ văn bản OCR được trích xuất từ các trang sách chụp dưới đây (thuộc cuốn sách "{book_name}"). \
Xác định xem văn bản này chứa những khái niệm/chủ đề nguyên tử (Atomic Concepts) độc lập nào. \
Mỗi khái niệm chỉ nên chứa một ý tưởng cốt lõi duy nhất. Một khái niệm có thể nằm trên 1 trang hoặc trải dài trên vài trang liên tiếp (ví dụ: trang 12 đến 14).

TUYỆT ĐỐI TUÂN THỦ CÁC QUY TẮC SAU:
1. Mỗi concept phải là "nguyên tử" (1 ý tưởng duy nhất). Không gộp các ý tưởng khác nhau vào cùng một concept.
2. Xác định chính xác ranh giới trang (trang bắt đầu `page_start` và trang kết thúc `page_end`) mà concept đó xuất hiện.
3. Tên concept (`title`) viết bằng tiếng Việt, viết hoa chữ cái đầu các từ quan trọng (Title Case), ngắn gọn nhưng phản ánh rõ bản chất (ví dụ: "Phản Ứng Với Tinh Thể", "Sự Tự Phủ Định Liên Tục").
4. Sử dụng hệ thống thuật ngữ nhất quán với từ điển định nghĩa trong thẻ <GLOSSARY> của THÔNG TIN NỀN VĨ MÔ ở trên.
5. Tuân thủ nghiêm ngặt các chỉ dẫn biên soạn (khẩu vị phân rã, văn phong) được định nghĩa trong thẻ <COMPILATION_GUIDELINES> của THÔNG TIN NỀN VĨ MÔ ở trên.
6. Trả về kết quả DƯỚI DẠNG MỘT JSON ARRAY HỢP LỆ. KHÔNG viết thêm bất kỳ lời giải thích nào ngoài khối JSON.

ĐỊNH DẠNG JSON YÊU CẦU:
[
  {{
    "title": "Tên khái niệm nguyên tử 1 bằng tiếng Việt",
    "page_start": 12,
    "page_end": 14,
    "rationale": "Lý do tách concept này (phân tích ngắn gọn cơ sở lập luận)."
  }},
  {{
    "title": "Tên khái niệm nguyên tử 2 bằng tiếng Việt",
    "page_start": 15,
    "page_end": 16,
    "rationale": "Lý do tách concept này."
  }}
]

NỘI DUNG VĂN BẢN OCR CỦA CÁC TRANG:
---
{formatted_ocr}
---
"""

BOOK_CONTEXT_ENRICHMENT = """\
Bạn là chuyên gia thiết kế và phân tích cấu trúc Zettelkasten.

Dưới đây là tệp tin cấu hình ngữ cảnh vĩ mô hiện tại của cuốn sách "{book_name}":
---
{current_context}
---

Và đây là bảng mục lục tiếng Việt hoàn chỉnh của cuốn sách (`_toc.json`):
---
{toc_json}
---

NHIỆM VỤ CỦA BẠN:
Hãy thực hiện "làm giàu" (Enrich) tệp tin ngữ cảnh vĩ mô trên bằng cách thay thế các placeholders trống bằng kiến thức học thuật vĩ mô thực tế của cuốn sách nổi tiếng này.

TUYỆT ĐỐI TUÂN THỦ CÁC QUY TẮC SAU:
1. Giữ nguyên toàn bộ cấu trúc XML, tên các thẻ, và thông tin metadata ở trên dải phân cách '---'.
2. Trong thẻ <SUMMARY>: Viết một tóm tắt lý thuyết chiến lược, học thuật sâu sắc (từ 3-5 câu) về cuốn sách.
3. Trong thẻ <STRUCTURE>: Đối với từng chương được liệt kê trong mục lục, hãy viết tóm tắt ngắn gọn từ 2-3 câu phản ánh chính xác nội dung học thuật thực tế của chương đó (thay thế hoàn toàn cho dòng placeholder "(Thêm tóm tắt chương tại đây để LLM nắm ngữ cảnh phân tích)").
4. Trong thẻ <GLOSSARY>: Liệt kê từ 8-15 thuật ngữ chuyên ngành học thuật quan trọng nhất của cuốn sách kèm theo bản dịch Việt - Anh chuẩn hóa và định nghĩa ngắn gọn (thay thế cho placeholder "Thuật ngữ 1...").
5. Trong thẻ <PEOPLE_AND_ORGANIZATIONS>: Trích xuất và điền danh sách các nhân vật nổi bật (các tác giả, chuyên gia được đề cập) và các công ty/tổ chức case-study tiêu biểu xuất hiện xuyên suốt cuốn sách (thay thế cho placeholders).
6. Hãy trả về TOÀN BỘ nội dung của file _context.txt mới sau khi làm giàu, bao gồm phần metadata ở đầu, dải phân cách '---', và khối <BOOK_CONTEXT> hoàn chỉnh. 
7. KHÔNG viết lời dẫn đầu, lời giải thích hay lời kết, chỉ trả về đúng định dạng của tệp _context.txt.
"""

# ── Markdown Processing Stage ─────────────────────────────────────────────

MARKDOWN_SYNTHESIS = """\
Bạn là trợ lý biên soạn tri thức. Phân tích nội dung văn bản (transcript/bài viết) dưới đây và bóc tách thành các Concept Notes độc lập.

NỘI DUNG:
---
{content}
---

NHIỆM VỤ:
1. Đọc toàn bộ nội dung và xác định các KHÁI NIỆM (Concepts), MÔ HÌNH TƯ DUY (Mental Models), hoặc Ý TƯỞNG (Ideas) cốt lõi và có giá trị nhất.
2. Lọc bỏ thông tin thừa, hội thoại lan man hoặc ví dụ rườm rà.
3. Với MỖI khái niệm lớn, hãy tạo 1 Concept Note hoàn chỉnh (YAML frontmatter + body). 
4. Bắt buộc phân tách các concept notes bằng dòng chữ chính xác: ===CONCEPT_SEPARATOR===

<rules>
1. Bạn TUYỆT ĐỐI PHẢI tuân thủ chính xác cấu trúc trong <output_template>. KHÔNG THÊM BẤT KỲ HEADING NÀO KHÁC (không `# Tên khái niệm`, không `## Implications`, không `## Connections`).
2. BẮT BUỘC PHẢI CÓ heading `## Core Idea`. Việc bỏ sót sẽ làm hỏng hệ thống.
3. Quy tắc ngôn ngữ NGHIÊM NGẶT:
   - **Evidence Hook** (blockquote đầu tiên): BẮT BUỘC bằng TIẾNG VIỆT. Nếu nguồn thô là tiếng Anh, phải dịch sát nghĩa sang tiếng Việt.
   - **Citation Line**: Ngay dưới Evidence Hook, cùng khối blockquote. Ghi rõ tên tác giả, tên tác phẩm, nguồn thô.
   - **`## Core Idea`**: PHÂN TÍCH THUẦN hoàn toàn bằng tiếng Việt. KHÔNG lồng thêm quote thứ hai bên trong. KHÔNG lặp lại Evidence Hook. Tập trung diễn giải cơ chế, hệ quả.
   - **`## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)`**: BẮT BUỘC bằng TIẾNG ANH nguyên bản. Nếu nguồn hoàn toàn bằng tiếng Việt, ghi `(không có)`.
4. Mỗi concept = 1 ý tưởng atomic, đứng độc lập.
5. related: tự động suy luận 5-10 links liên quan nhất.
6. Nếu bài viết chỉ có 1 ý chính → tạo 1 concept. Nếu có nhiều ý → tạo nhiều concept (ví dụ 3-5 concepts cho video 1 tiếng).
</rules>

<output_template>
---
title: "Tên khái niệm"
aliases: []
tags:
  - knowledge
  - type/concept
  - domain/<lĩnh_vực>
type: concept
date_created: {today}
date_modified: {today}
source: "{source_name}"
source_type: text
summary: "Tóm tắt 2-3 câu"
people: []
companies: []
status: seed
related: []
confidence: medium
---

> "Trích dẫn nguyên văn BẮT BUỘC bằng tiếng Việt — Evidence Hook."
> — **Tên Tác Giả**, trích dẫn trong *Tên Tác Phẩm* ([[source_note_stem|Nguồn, Năm]])

## Core Idea

Phân tích chuyên sâu (200-400 từ) diễn giải ý tưởng này — hoàn toàn bằng tiếng Việt.

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> "Original English passage from source..." (BẮT BUỘC tiếng Anh nguyên bản)

---

## References

- [[source_note_stem]]
</output_template>
"""

