# 📐 Visual Ergonomics & Technical Standards Guide (v8.15.10)

Quy chuẩn kỹ thuật toàn diện khi tạo, nhúng và chuẩn hóa sơ đồ minh họa (Excalidraw, Mermaid, D2, Image Art), bảng biểu Markdown và khối mã nguồn trong Obsidian Vault.

---

## 1. Ngưỡng Vàng Lai Phân Tách Công Cụ (Hybrid Golden Threshold)

- **BẮT BUỘC tạo tệp Excalidraw 16:9** (`03 - Resources/attachments/...excalidraw.md`) và nhúng `![[...excalidraw.md|100%]]` khi sơ đồ thỏa mãn ít nhất 1 trong 3 điều kiện:
  1. Là Kiến trúc Hệ sinh thái / Ma trận Hệ thống đa tầng ($\ge 3$ phân tầng/layers).
  2. Tổng số nodes/boxes $\ge 9$.
  3. Đồ thị có kết nối chéo đa chiều phức tạp giữa $\ge 3$ subgraphs mà Dagre không thể xếp phẳng thành luồng 1 chiều.
- **Mermaid inline CHỈ DÙNG cho**:
  1. Luồng quy trình, thuật toán, pipeline xử lý tuyến tính (Sequence / Flowchart).
  2. Cặp tương tác song phương (Hub-and-Spoke 2 cụm, Edge vs Core 2 cụm).
  3. Sơ đồ cây phân nhánh hoặc chu trình tuần hoàn nhỏ $\le 8$ nodes.
- **D2 Vector SVG**: Ưu tiên cho kiến trúc hạ tầng kỹ thuật sâu, topology mạng và hệ thống phân tán (`03 - Resources/attachments/...d2.svg`).

---

## 2. Tiêu Chuẩn Obsidian Excalidraw 2.x

### 2.1. Cấu Trúc Bao Đóng Bắt Buộc (Wrapper Invariant)
Mọi tệp `.excalidraw.md` **BẮT BUỘC** tuân thủ cấu trúc 3 tầng chuẩn của Obsidian Excalidraw Plugin (phiên bản 2.x):
```markdown
# Excalidraw Data

## Text Elements
...

%%
## Drawing
```json
...
```
%%
```
- **Quy tắc**: Tuyệt đối không dùng H1 `# Drawing` hoặc bỏ qua `# Excalidraw Data`.
- **Hệ quả nếu vi phạm**: Plugin Obsidian sẽ tự động nhân bản header `# Text Elements` và làm rò rỉ thẻ neo `^txt_...` vào thân văn bản ghi chú.

### 2.2. Hình Học & Tọa Độ An Toàn (Geometry & Layout Seams)
- **Excalidraw ID Invariant**: Mọi Text Element ID bắt buộc có độ dài chính xác 8 ký tự `[a-zA-Z0-9_-]` để khớp với regex `/\s\^(.{8})[\n]+/g` và bước nhảy con trỏ 12 ký tự của plugin, khử trùng lặp qua `seen_ids`.
- **Universal Bounding Box**: Canvas tự động chuẩn hóa về toạ độ dương an toàn ($x \ge 80, y \ge 60$) qua `normalize_canvas_bounding_box`, tính cả toạ độ uốn của các mũi tên liên kết.
- **Shared Layout Seams**: `sync_bound_text_translation` đồng bộ dịch chuyển các khối text liên kết theo cả `boundElements` và `containerId == shape["id"]`.
- **Container Header Anchoring**: Tiêu đề khung bao bọc (enclosing containers) được tách khỏi bound text và neo ở đỉnh khung (`containerHeaderOf`) để ngăn engine tự động kéo về trung tâm làm đè chữ lên node con; Sugiyama Layout tự động bỏ qua khung container (`layout_router.py`).

### 2.3. Auto-Expand Container & Safe Vertical Padding
- Kích thước hình bao bọc (container shape) được tự động kiểm tra và nâng lên để đảm bảo $H_{container} \ge H_{text} + 30\text{px}$, duy trì khoảng đệm an toàn tối thiểu $30\text{px}$ ngăn chữ đè mép viền hoặc tràn ra ngoài khung hình.
- *Cảnh báo hình thoi/elip*: Diện tích khả dụng chứa văn bản hẹp hơn nhiều so với bounding box chữ nhật. Khi gặp nội dung nhiều dòng, cần tăng padding hoặc ưu tiên dùng `rectangle`.
- *Ràng buộc LLM*: Tiêu đề node súc tích gói gọn trong 1 dòng ($\le 35$ ký tự); node chứa metadata tag hoặc badge bổ sung bắt buộc có chiều rộng $W \ge 200\text{px}$.

### 2.4. Wheel Layout Multi-Tier Disambiguation & Anchor
- Phân tách 3 tầng hình học trong `wheel_layout.py`:
  - `header_ids`: Các banner tiêu đề độc lập (bậc kết nối $= 0$, chiều rộng $\ge 600\text{px}$, toạ độ $Y \le \text{center\_y}$) được neo cố định tại đỉnh canvas ở toạ độ an toàn $Y = 30\text{px}$.
  - `aux_shape_ids`: Các node phụ trợ hoặc chú thích độc lập (bậc kết nối $= 0$) được tách riêng, loại trừ khỏi tập hợp tính toán chu trình bánh xe để chống tạo các node ảo ("phantom nodes").
  - `connected_shape_ids`: Chỉ các node thực sự có kết nối luồng (bậc kết nối $> 0$) mới được phân bố đều trên vành đai vòng tròn tuần hoàn ($Y \ge 120\text{px}$).

### 2.5. Executive Typography 16:9 & Bảng Đặc Tả Kèm Dưới (v8.15.6)
Để triệt tiêu **Nghịch lý Co giãn Canvas (Canvas-to-Document Scaling Paradox)** khi nhúng sơ đồ Excalidraw vào cột đọc hẹp của Obsidian Reading View (~700-750px):
1. **Khóa Chiều Rộng Bounding Box 16:9**: Giới hạn trong khoảng $1.000\text{px} \le W \le 1.150\text{px}$ (tuyệt đối không dàn trải ra $1.400\text{px}-1.600\text{px}$) nhằm bảo đảm hệ số co giãn khi nhúng (Embed Scale Factor) luôn đạt $\ge 65\%-70\%$.
2. **Quy Chuẩn Cỡ Chữ Sàn (Floor Font Size Standards)**:
   - Tiêu đề chính canvas: $\ge 17\text{px}-20\text{px}$ (Bold).
   - Tiêu đề khối/phân tầng: $\ge 14\text{px}-16\text{px}$ (Bold).
   - Nội dung nhãn/badge: $\ge 12\text{px}-13\text{px}$ (Đảm bảo kích thước hiển thị thực tế trên màn hình luôn đạt $\ge 8.5\text{px}-11.5\text{px}$, đọc rõ mồn một mà không cần zoom).
3. **Nguyên Tắc Executive Poster & Cặp Bài Trùng**: Sơ đồ chỉ hiển thị các từ khóa, vai trò cốt lõi và badge ngắn gọn ($\le 2-3$ dòng mỗi hộp). Mọi thông số kỹ thuật chi tiết (Local Context, Domain Data, Task Logic, Conway Role...) BẮT BUỘC phải được trình bày trong **Bảng Đặc Tả Ma Trận Kiến Trúc (Architecture Specification Matrix Table)** bằng Markdown đặt ngay dưới sơ đồ, tuân thủ Section 4 dưới đây.

### 2.6. Quy Tắc Phân Tách Mũi Tên & Nhãn Kết Nối (Arrow-Label Clearance Invariant v8.15.6)
1. **Tách Rời Trục Tọa Độ Y**: Khi đặt nhãn mô tả cho mũi tên nối giữa các tầng, BẮT BUỘC tách rời tọa độ Y của nhãn văn bản và mũi tên với khoảng đệm an toàn $\ge 15\text{px}$ (ví dụ: text tại $Y=432$, mũi tên tại $Y=450 \rightarrow 468$). Tuyệt đối cấm đặt mũi tên và text cùng tọa độ khiến đường kẻ đâm xuyên qua chữ.
2. **Khoảng Cách Ngang Tối Thiểu (Horizontal Gap Clearance)**: Khoảng cách giữa 2 khối chức năng có mũi tên liên kết ngang kèm nhãn chữ (ví dụ `Cung cấp Logic`) bắt buộc phải đạt tối thiểu $\ge 80\text{px}-90\text{px}$ để nhãn text 1 dòng nằm vừa vặn, không bị co kéo hay chạm vào mũi tên.

---

## 3. Bộ Ngũ Ràng Buộc Kỹ Thuật Mermaid (The 5 Mermaid Engineering Invariants v8.15.6)

1. **Khóa Cứng Thứ Bậc Dagre bằng Bất Đối Xứng Trọng Số Cạnh (Dagre Cycle Stabilization via Edge Weight Asymmetry)**:
   Khi có liên kết 2 chiều giữa 2 subgraphs/cụm (như Hub $\leftrightarrow$ Spoke), BẮT BUỘC gán bất đối xứng trọng số: tổng trọng số chiều xuôi $W_{down} \ge 3$ (dùng nét dày `===>` hoặc `<===>`) và chiều ngược $W_{up} = 1$ (dùng nét đứt `-.->`), đảm bảo $\Delta W = W_{down} - W_{up} \ge 2$. Tuyệt đối CẤM dùng các cạnh ngược chiều có cùng trọng số đối xứng (`-->` cả 2 chiều) khiến thuật toán Greedy FAS của Dagre ngẫu nhiên đảo chiều cạnh đi xuống và đẩy node con lên đỉnh.
2. **Triệt Tiêu Màu Vàng Mặc Định bằng Base Theme Directive (Academic Grayscale Init Invariant)**:
   Mọi khối Mermaid BẮT BUỘC phải mở đầu bằng chỉ thị khởi tạo Academic Grayscale:
   ```mermaid
   %%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ffffff', 'primaryBorderColor': '#0f172a', 'primaryTextColor': '#0f172a', 'lineColor': '#334155', 'clusterBkg': '#f8fafc', 'clusterBorder': '#cbd5e1', 'edgeLabelBackground': '#ffffff'}}}%%
   ```
   Nghiêm cấm để Mermaid render ở theme mặc định sinh ra màu vàng mù tạt `#ffffde`.
3. **Căn Lề Trái Khối Văn Bản & Thoát Ký Tự Node (Node Left-Alignment & HTML Entity Invariant)**:
   Mặc định Mermaid căn giữa mọi dòng chữ làm danh sách bullet points thụt thò nham nhở. BẮT BUỘC bọc nội dung có nhiều dòng hoặc bullet points trong `<div align='left'>...</div>`. BẮT BUỘC dùng thực thể HTML an toàn `#40;` và `#41;` thay cho dấu ngoặc đơn trần `()` bên trong nhãn text.
4. **Cưỡng Chế Thứ Tự Đọc Trực Quan LTR (Invisible Edge Reading Order Enforcement)**:
   Trong sơ đồ hoặc subgraph có `direction LR`, các cụm node song song không có luồng phụ thuộc trực tiếp BẮT BUỘC phải được liên kết bằng cạnh vô hình `T1 ~~~ T2 ~~~ T3` để khóa cứng thứ tự hiển thị từ trái sang phải theo đúng tiến trình ngữ nghĩa.
5. **Quy Tắc Phẳng Hóa Cặp Đối Trọng & Cấm Lồng Hộp (Flat Two-Node & Subgraph Title Invariant v8.15.6)**:
   - **Cấm Hộp Lồng Hộp (Box-in-a-Box Elimination)**: Khi sơ đồ biểu diễn cặp thực thể đối trọng song phương (như Tế bào vs Nền tảng, Client vs Server, Online vs Offline), CẤM TUYỆT ĐỐI việc tạo `subgraph` chỉ để chứa duy nhất 1 node con bên trong. BẮT BUỘC phẳng hóa thành 2 node độc lập (`Edge` và `Core`).
   - **Cấm Ngắt Dòng Trong Tiêu Đề Subgraph**: Nghiêm cấm sử dụng thẻ `<br/>` trong nhãn tiêu đề của `subgraph`. Engine Dagre của Mermaid tính toán sai chiều cao tiêu đề đa dòng, khiến dòng thứ hai bị đè lấp và cắt cụt (clipping) bởi đường viền của node con bên trong. Mọi tiêu đề và phụ đề phải được tích hợp trực tiếp vào bên trong node phẳng.
   - **Cưỡng Chế Căn Lề Trái 100%**: Mọi khối văn bản có nhiều dòng hoặc bullet points bên trong node BẮT BUỘC phải bọc trong `<div align='left'>...</div>`, triệt tiêu hoàn toàn hiện tượng các từ rớt dòng bị căn giữa thụt thò nham nhở.
6. **Bộ Tứ Mẫu Thiết Kế Mermaid Công Thái Học (The 4 Mermaid Ergonomic Design Patterns v8.15.9)**:
   Nhằm đảm bảo tính trực quan, công thái học hiển thị trên Obsidian Reading View và chống hiện tượng layout gãy vỡ của Dagre, hệ thống chuẩn hóa 4 mẫu thiết kế Mermaid chuẩn mực:

   - **Pattern 1: Bố Cục Trục Nền Tảng & Đa Tế Bào (Macro Hub-and-Pods Layout)**:
     - *Mục đích*: Biểu diễn kiến trúc phân tán gồm 1 khối trung tâm (Hub/Platform) hỗ trợ cho 3+ khối vệ tinh (Pods/Spokes/Cells) nằm ngang cân đối.
     - *Kỹ thuật*: Sử dụng mũi tên dày `HUB ===> POD1`, `HUB ===> POD2`, `HUB ===> POD3` ($W \ge 3$) và cạnh vô hình `POD1 ~~~ POD2 ~~~ POD3` để khóa chặt trục ngang, chống Dagre xếp lệch tầng.
     - *Khung mã mẫu*:
       ```mermaid
       %%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ffffff', 'primaryBorderColor': '#0f172a', 'primaryTextColor': '#0f172a', 'lineColor': '#334155', 'clusterBkg': '#f8fafc', 'clusterBorder': '#cbd5e1', 'edgeLabelBackground': '#ffffff'}}}%%
       flowchart TD
           HUB["<b>PLATFORM CORE</b><br><i>Nền tảng Quản trị & Hạ tầng dùng chung</i>"]
           HUB ===> POD1["<b>POD 1: AI-Hierarchy</b><br><div align='left'>• 95% AI thực thi SOP<br>• 5% Human Calibrator</div>"]
           HUB ===> POD2["<b>POD 2: AI-Project</b><br><div align='left'>• Tam giác sắt AI-Native<br>• Context Architect & Hạm đội</div>"]
           HUB ===> POD3["<b>POD 3: AI-Innovation</b><br><div align='left'>• Two-Pizza AI Teams<br>• Tốc độ xoay trục tối đa</div>"]
           POD1 ~~~ POD2 ~~~ POD3
           classDef hubStyle fill:#0f172a,stroke:#0f172a,stroke-width:2px,color:#ffffff;
           classDef podStyle fill:#f8fafc,stroke:#334155,stroke-width:1.5px,color:#0f172a;
           class HUB hubStyle;
           class POD1,POD2,POD3 podStyle;
       ```

   - **Pattern 2: Cây Quyết Định Với Nhãn Ngữ Nghĩa (Semantic Decision Tree with Badges)**:
     - *Mục đích*: Trực quan hóa cây quyết định rẽ nhánh quy trình (như Reuse-First Gate) với bảng màu pastel ngữ nghĩa.
     - *Kỹ thuật*: Phân nhóm kết quả theo 3 màu: Xanh lá (`REUSE` - ưu tiên cao nhất), Xanh dương (`EXTEND` - bổ sung theo KISS), Vàng hổ phách (`CREATE NEW` - tạo mới kiểm soát chặt); nhãn kết luận dạng Badge: `<b>[1] REUSE</b>`, `<b>[2] EXTEND</b>`, `<b>[3] CREATE NEW</b>` kèm gạch đầu dòng căn lề trái.
     - *Khung mã mẫu*:
       ```mermaid
       %%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ffffff', 'primaryBorderColor': '#333333', 'primaryTextColor': '#111111', 'lineColor': '#555555'}}}%%
       flowchart TD
           REQ["<b>Yêu cầu nghiệp vụ mới</b>"] --> STEP1["<b>Bước 1: Catalog Lookup</b>"]
           STEP1 --> CHECK1{"Đã có Skill / Tool tương tự?"}
           CHECK1 -- "Có" --> FIT{"Đánh giá Scope Fit"}
           FIT -- "Khớp hoàn toàn" --> ACT_REUSE["<b>[1] REUSE</b><br><i>Tái sử dụng Hub Skill</i><br><div align='left'>• Zero mã nguồn mới<br>• Tận dụng công cụ đã kiểm thử</div>"]:::reuseNode
           FIT -- "Thiếu tính năng" --> STEP2["<b>Bước 2: Cost-Benefit Analysis</b>"]
           CHECK1 -- "Chưa có" --> STEP2
           STEP2 --> CHECK2{"Giải quyết bằng 10-15 dòng code? #40;KISS#41;"}
           CHECK2 -- "Được" --> ACT_EXTEND["<b>[2] EXTEND</b><br><i>Mở rộng cục bộ tại Spoke</i><br><div align='left'>• 10-15 dòng code đơn giản<br>• Không phụ thuộc bên ngoài</div>"]:::extendNode
           CHECK2 -- "Phức tạp" --> ACT_NEW["<b>[3] CREATE NEW</b><br><i>Tạo Skill Mới Chuẩn Hóa</i><br><div align='left'>• Phải qua ADR-0057 & Linter<br>• Đóng góp ngược về Hub</div>"]:::createNode
           classDef reuseNode fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d;
           classDef extendNode fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e3a8a;
           classDef createNode fill:#fffbeb,stroke:#d97706,stroke-width:2px,color:#78350f;
       ```

   - **Pattern 3: Phễu Lọc Kiến Trúc Đa Tầng (Multi-Tier Governance Funnel)**:
     - *Mục đích*: Trực quan hóa quy trình thẩm tra, kiểm soát chất lượng qua nhiều cửa ải (như Khung Quản trị 3 Tầng ADR-0057).
     - *Kỹ thuật*: Bố cục luồng dọc `flowchart TD` phân tách nhánh từ chối/hạ cấp (thực thi tiền định hoặc API đơn lẻ) và nhánh đạt chuẩn đi tiếp vào bộ lọc sâu hơn; tầng cuối cùng phân cấp theo điểm số định lượng ($GPI \ge 12.0 \rightarrow$ Standalone Kernel Skill; $GPI < 12.0 \rightarrow$ Spoke Recipe).
     - *Khung mã mẫu*:
       ```mermaid
       %%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ffffff', 'primaryBorderColor': '#333333', 'primaryTextColor': '#111111', 'lineColor': '#555555'}}}%%
       flowchart TD
           INPUT["<b>Ý tưởng Skill / Tool Mới</b>"] --> G0{"<b>CỔNG 0: Ranh giới Tiền định</b><br>Tác vụ có 100% tất định?"}
           G0 -- "Có #40;Regex, AST, Script#41;" --> NON_LLM["<b>Từ chối AI Skill</b><br><i>Viết Pure Deterministic Script</i>"]:::rejectNode
           G0 -- "Không #40;Cần suy luận phi cấu trúc#41;" --> G1{"<b>CỔNG 1: Điều phối Đa bước</b><br>Cần tương tác nhiều bước?"}
           G1 -- "Không #40;1 bước đơn lẻ#41;" --> SINGLE_LLM["<b>Từ chối Skill phức tạp</b><br><i>Dùng Single-Shot API Call</i>"]:::rejectNode
           G1 -- "Có #40;Vòng lặp, RAG, Công cụ#41;" --> TIER_EVAL{"<b>CỔNG 2: Đánh giá Điểm GPI</b><br>Tính điểm General Purpose Index"}
           TIER_EVAL -- "GPI ≥ 12.0" --> KERNEL["<b>STANDALONE KERNEL SKILL</b><br><i>Kỹ năng Nền tảng Hub (Tier 2B)</i><br><div align='left'>• Đa dự án, giá trị cao<br>• Lưu trữ tập trung tại Hub</div>"]:::kernelNode
           TIER_EVAL -- "GPI < 12.0" --> RECIPE["<b>SPOKE RECIPE</b><br><i>Quy trình Cục bộ (Tier 3)</i><br><div align='left'>• Giới hạn trong 1 tế bào<br>• Không làm phình Hub</div>"]:::recipeNode
           classDef rejectNode fill:#fef2f2,stroke:#ef4444,stroke-width:1.5px,color:#991b1b;
           classDef kernelNode fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d;
           classDef recipeNode fill:#f8fafc,stroke:#64748b,stroke-width:1.5px,color:#1e293b;
       ```

   - **Pattern 4: Phân Vùng Lãnh Thổ & Vòng Lặp Phản Hồi (Cross-Domain Subgraphs with Feedback Loop)**:
     - *Mục đích*: Mô hình hóa ranh giới phân quyền giữa hai vùng lãnh thổ (như Spoke Workspace vs Hub Governance) cùng chu trình đóng góp và phản hồi 2 chiều.
     - *Kỹ thuật*: Hai `subgraph` độc lập đại diện hai không gian thẩm quyền (`subgraph SpokeZone` vs `subgraph HubZone`); luồng đóng góp dùng nét đậm `==>` ($W \ge 3$), luồng phản hồi thẩm định dùng nét đứt `-.->` ($W = 1$) chống lộn ngược bố cục Dagre; luồng phân phối quay lại hoàn tất chu trình.
     - *Khung mã mẫu*:
       ```mermaid
       %%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ffffff', 'primaryBorderColor': '#333333', 'primaryTextColor': '#111111', 'lineColor': '#555555'}}}%%
       flowchart TD
           subgraph SpokeZone[" LÃNH THỔ TẾ BÀO #40;Spoke Workspace#41; "]
               direction TB
               SP_DEV["<b>Tế bào Phát triển</b><br>Viết tính năng / Kỹ năng mới"]
               SP_LOC["<b>Kiểm tra Cục bộ</b><br>Harness / Local Verification"]
               SP_SUBMIT["<b>Đóng gói Đóng góp</b><br>Tạo PR / Contribution Manifest"]
               SP_DEV --> SP_LOC --> SP_SUBMIT
           end
           subgraph HubZone[" HỆ THỐNG TRUNG TÂM #40;Hub Governance#41; "]
               direction TB
               HUB_GATE["<b>Hub Review Gate</b><br>Linter & 15-Gate CI"]
               HUB_MERGE["<b>Non-Destructive Merge</b><br>Tích hợp vào Central Repo"]
               HUB_DIST["<b>Phân phối Đồng bộ</b><br>Đẩy cập nhật về toàn mạng lưới"]
               HUB_GATE --> HUB_MERGE --> HUB_DIST
           end
           SP_SUBMIT ===>|"Gửi đóng góp"| HUB_GATE
           HUB_GATE -.->|"Yêu cầu chỉnh sửa #40;nếu lỗi#41;"| SP_DEV
           HUB_DIST ===>|"Đồng bộ tự động"| SP_DEV
           classDef spokeStyle fill:#f8fafc,stroke:#2563eb,stroke-width:1.5px,color:#1e3a8a;
           classDef hubStyle fill:#f8fafc,stroke:#16a34a,stroke-width:1.5px,color:#14532d;
           class SP_DEV,SP_LOC,SP_SUBMIT spokeStyle;
           class HUB_GATE,HUB_MERGE,HUB_DIST hubStyle;
       ```

7. **Quy Tắc Cú Pháp Nhãn Mũi Tên Mermaid (Mermaid Edge Label Invariant v8.15.10)**:
   - **Cấm Tuyệt Đối Cú Pháp Chèn Giữa Thân Mũi Tên (Zero Chimeric Arrows)**: Nghiêm cấm đưa nhãn text vào giữa các nét vẽ mũi tên (`===="text"====>`, `-."text".->`, `<===="text"====>`). Cú pháp này gây lỗi phân tích cú pháp nghiêm trọng (`Syntax error in text`) trên các phiên bản Mermaid hiện đại.
   - **Bắt Buộc Cú Pháp Pipe Chuẩn (Standard Pipe Labels)**:
     - Mũi tên đơn mảnh: `A -->|"Nhãn text"| B` hoặc `A -- "Nhãn text" --> B`
     - Mũi tên dày (thắt chặt thứ bậc): `A ===>|"Nhãn text"| B`
     - Mũi tên nét đứt (phản hồi/tham chiếu): `A -.->|"Nhãn text"| B`
     - Mũi tên dày hai chiều: `A <===>|"Nhãn text"| B`
   - **Chuẩn Hóa Toán Tử So Sánh Unicode**: Khi nhãn chứa phép so sánh, BẮT BUỘC sử dụng ký tự Unicode `≥` và `≤` thay vì ký tự ASCII thô `>=` hoặc `<=` (ví dụ: `===>|"Độ phức tạp ≥ 8"|`). Ký tự `>` hoặc `<` trong nhãn sẽ bị tokenizer của Mermaid nhầm lẫn với đầu mũi tên (`-->`, `<--`), gây crash sơ đồ.

---

## 4. Markdown Table Invariants & Reading View Aesthetics (v8.15.2)

1. **Quy tắc Thoát Ký tự Pipe Bắt buộc trong Ô Bảng (Table Wikilink Pipe Escaping Invariant)**:
   - Tuyệt đối KHÔNG viết dấu gạch đứng trần `|` bên trong ô bảng Markdown khi sử dụng liên kết có bí danh (alias).
   - Bắt buộc phải thoát ký tự (escape) bằng dấu gạch chéo ngược: `[[slug\|[3]]]` hoặc `[[Note Title\|Display Name]]`.
   - Ngăn chặn triệt để hiện tượng gãy parser bảng, rách mép hiển thị và mất thẻ đóng `]]`.
   - **Thoát Ký Tự Pipe Trong Tiêu Đề (Embedded Title Pipe Escaping)**: Khi hiển thị tiêu đề chứa dấu gạch đứng (ví dụ: `Thuật toán | Giải thuật`), bắt buộc chuẩn hóa qua `clean_title = raw_title.replace(r"\|", "|").replace("|", r"\|")` trước khi đưa vào `[[stem\|clean_title]]` để chống vỡ cột bảng Markdown.
2. **Quy tắc Khoá Mũi tên Điều hướng Chống Rớt Dòng (Non-Breaking Arrow Invariant)**:
   - Khi sử dụng ký tự phân cấp, mũi tên luồng (`↳`, `→`, `•`) sau thẻ ngắt dòng `<br>`, BẮT BUỘC phải dùng khoảng trắng không ngắt dòng `&nbsp;` liền kề: `↳&nbsp;Nội dung`.
3. **Thiết lập Độ rộng Đáy Tự nhiên (Baseline Width Stabilization)**:
   - Thêm nhãn phụ tiếng Anh ngắn trong ngoặc đơn hoặc phụ đề in nghiêng: `**Tên Tiêu Chí**<br>*(Sub-label)*` để neo khung chặn kích thước cơ sở (~18-22% viewport), chống bóp nghẹt Cột 1 thành dải chữ dọc.
4. **Cấu trúc Phân tầng Thị giác 2 Nhịp (Two-Tier Visual Hierarchy for Matrix Cells)**:
   - Mỗi ô so sánh cấu trúc thành 2 nhịp:
     - Nhịp 1 (In đậm): Khái niệm / Từ khóa đối lập cốt lõi.
     - Nhịp 2 (`<br>↳&nbsp;`): Cơ chế vận hành súc tích ($\le 40$ ký tự mỗi dòng). Triệt tiêu 100% thanh cuộn ngang.
5. **Quy Tắc Cách Ly Ngữ Cảnh Thực Thể HTML (Strict HTML Entity Context Isolation Invariant v8.15.10)**:
   - **Khoanh Vùng Phạm Vi**: Các thực thể HTML thoát ký tự như `#40;` và `#41;` CHỈ ĐƯỢC PHÉP xuất hiện bên trong khối code ````mermaid` (nơi chúng ngăn chặn lỗi phân tích cú pháp node shape).
   - **Cấm Rò Rỉ Ra Bảng Biểu & Thân Bài**: Tuyệt đối KHÔNG sử dụng `#40;` hoặc `#41;` trong bảng biểu Markdown hoặc văn bản thông thường. Obsidian không tự động giải mã các thực thể này trong môi trường bảng/văn bản chuẩn, khiến chúng hiển thị thô dạng chữ gây mất thẩm mỹ.
   - **Ngoặc Đơn Tròn Chuẩn**: Trong các ô bảng và văn bản Markdown, bắt buộc sử dụng dấu ngoặc đơn thông thường `()` (ví dụ: `Chiến lược (Phần 1)`, `Dữ liệu (VN)`).

---

## 5. Zero-ASCII Art Invariant & Native Code Fences (v8.15.3)

1. **Cấm Tuyệt Đối Sơ Đồ Ký Tự Text (Zero-ASCII / Unicode Box Invariant)**:
   - TUYỆT ĐỐI KHÔNG vẽ sơ đồ kiến trúc, ma trận phân nhánh, flowcharts bằng ký tự ASCII (`+---+`, `|`, `->`) hoặc Unicode Box-Drawing (`┌─┐`, `└─┘`) bên trong code block trần để chống rách khung viền trên mobile/split-pane. Mọi sơ đồ phải là Mermaid (`flowchart TD`) hoặc tệp đính kèm Excalidraw/D2.
2. **Cưỡng Chế Native Code Fences cho Tệp Dữ Liệu & Cấu Hình**:
   - Tệp cấu hình (YAML, JSON, Python) phải dùng code block có tag ngôn ngữ chuẩn (```yaml, ```json), phân tách phân vùng bằng comment nội bộ (`# ---`), tuyệt đối không bao bọc trong hộp vẽ Unicode/ASCII giả lập.

---

## 6. Công Thái Học Đóng Gói Khối Mã Dài & Callout Invariants (v8.15.5)

Mọi khối mã nguồn hoặc cấu hình dài **$> 15$ dòng** BẮT BUỘC phải được đóng gói bên trong Obsidian Callout:
- *Nhánh 1 (Cấu hình mẫu, Schema, Code minh họa tri thức)*: Bọc trong Callout Mở Sẵn: `> [!abstract]+ Tiêu đề Cấu hình / Mã nguồn` (KHÔNG chèn emoji).
- *Nhánh 2 (Log kỹ thuật thô, Siêu dữ liệu, Báo cáo)*: Bọc trong Callout Đóng Sẵn: `> [!info]- Tiêu đề Siêu dữ liệu / Log` (KHÔNG chèn emoji).

**Bộ Ba Ràng Buộc Trình Bày Callout (The 3 Callout Presentation Invariants)**:
1. *Clean Callout Header Invariant*:
   - **Cấm Emoji Trong Tiêu Đề Callout**: Tránh lỗi Double Icon Glitch (Obsidian tự tiêm SVG icon).
   - **Cấm Backticks Trong Tiêu Đề Callout**: Tên tệp hoặc định danh kỹ thuật trong tiêu đề Callout BẮT BUỘC phải để dạng plain text (ví dụ: `Cấu trúc: workspace_context.yaml`, cấm `` `workspace_context.yaml` ``) để chống vỡ baseline text và chevron.
2. *Target Language Syntax Alignment Invariant*:
   - Mọi câu văn giải thích chú thích phải dùng đúng chuẩn comment của ngôn ngữ đích (`#` cho YAML/Python, `//` cho JSONC/JS/TS, `<!-- -->` cho HTML/Markdown, `--` cho SQL).
3. *Minimal Banner Invariant*:
   - Thay thế các dải kẻ trang trí dài `# ================================` bằng comment ngắn gọn `# --- GLOBAL SECTION ---` để khử rác thị giác trên Light Theme.

---

## 7. Diagrams-as-Code (D2) & Hero Image Standards (v8.13.3)

- **D2 Worker**: Gửi `User-Agent` tùy biến vượt Cloudflare WAF của Kroki (HTTP 403), vệ sinh cấm layout engine thương mại `tala`, escape an toàn cú pháp JSON prompt.
- **Hero Image Standards**: Tuân thủ cấu hình Gateway SSOT (`gateway_image_model`) và áp dụng Rào cản Phủ định (Negative Constraints) triệt tiêu phong cách tranh hoạt hình, anime, hoặc 3D nhựa đồ chơi, bảo đảm chất lượng điện ảnh học thuật tối giản.
- **Windows CRLF-Safe**: Môi trường Windows sử dụng `\r\n`. Khi xử lý YAML frontmatter hoặc chèn ảnh dưới H1 bằng regex, luôn sử dụng mẫu regex an toàn `\r?\n` hoặc module `core.frontmatter`.
