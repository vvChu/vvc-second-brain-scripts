# 📄 RFC: Nâng Cấp Kỹ Năng `/ccba-new-feature` — Tự Động Phân Loại & Đề Xuất Claim Issue Backlog (Factory Model v1.3.0)

- **RFC ID:** `RFC-2026-09-01-SKILL-NEW-FEATURE`
- **Mục tiêu:** Nâng cấp kỹ năng `ccba-new-feature` tại CCBA Hub
- **Phân loại:** `_core` Platform Orchestrator Skill
- **Phiên bản đề xuất:** `v1.3.0` (từ `v1.2.0`)
- **Tác giả:** VvC Second Brain Architecture Team (`vvc-second-brain`)
- **Nơi tiếp nhận:** CCBA Agent Platform Hub (`ccba-agent-platform`)
- **Trạng thái:** `PROPOSED (Chờ duyệt)`

---

## 1. Tóm Tắt (Executive Summary)

Kỹ năng `/ccba-new-feature` hiện tại (v1.2.0) bắt buộc người dùng phải chủ động cung cấp mã Issue (`/ccba-new-feature #id`). Nếu người dùng chỉ gõ trần `/ccba-new-feature`, hệ thống sẽ rơi vào luồng phỏng vấn thủ công từng câu ("Loại công việc là gì?", "Mô tả tính năng là gì?"), hoàn toàn bỏ qua danh mục công việc (Backlog Issues) đang sẵn có trên remote repository (GitHub).

RFC này đề xuất bổ sung **Cơ chế Phân loại Tự hành & Đề xuất Claim Issue (Autonomous Issue Discovery & Smart Claiming)**:
Khi người dùng kích hoạt `/ccba-new-feature` mà không kèm tham số, Agent sẽ tự động truy vấn danh sách Open Issues trên GitHub, áp dụng thuật toán phân cấp ưu tiên phụ thuộc kỹ thuật (Topological Dependency Ranking), hiển thị Menu khuyến nghị thông minh để người dùng chọn chỉ với 1 click/phím bấm, sau đó tự động claim Issue (`gh issue edit --add-assignee "@me"`), tạo nhánh chuẩn định danh và nạp toàn bộ đặc tả vào Giai đoạn Lập kế hoạch (Planning Phase).

---

## 2. Bối Cảnh & Điểm Nghẽn Hiện Tại (Problem Statement)

### 2.1. Hạn chế trong logic Bước 3 của `SKILL.md` (v1.2.0)
Tại dòng 53–68 của `ccba-new-feature/SKILL.md`:
- **Trường hợp 1 (Có mã Issue):** Xử lý mượt mà qua `gh issue view <id>` hoặc offline fallback.
- **Trường hợp 2 (Không cung cấp mã Issue):** Rơi vào chế độ hỏi đáp thụ động:
  ```markdown
  Hỏi người dùng lần lượt các thông tin:
  - Loại công việc cần thực hiện: feat, fix, docs, refactor, hoặc experiment.
  - Mô tả ngắn gọn tính năng (3-5 từ).
  ```

### 2.2. Các hệ quả tiêu cực:
1. **Lãng phí thao tác của Kỹ sư**: Khi dự án đã quản lý backlog chuyên nghiệp trên GitHub Issues, kỹ sư phải mở trình duyệt hoặc gõ `gh issue list`, nhớ số ID, rồi mới gõ lại `/ccba-new-feature #<id>`.
2. **Bỏ quên các Issue kiến trúc cốt lõi**: Người dùng thường có xu hướng gõ ngay tính năng mới (`feat`), bỏ qua các Issue tái cấu trúc (`refactor`) hoặc sửa lỗi nền tảng (`fix`) đang cần làm trước để chống nợ kỹ thuật.
3. **Chưa phát huy tối đa vai trò của Autonomous Agent**: Thay vì là một Agent thông minh biết tự đọc backlog và đưa ra khuyến nghị chiến lược, Agent hiện tại chỉ hoạt động như một form nhập liệu dòng lệnh (CLI Form-filler).

---

## 3. Kiến Trúc Đề Xuất (Proposed Architecture)

### 3.1. Luồng Điều Phối Cải Tiến (State Flow)

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffffff', 'edgeLabelBackground':'#ffffff', 'tertiaryColor': '#ffffff'}}}%%
flowchart TD
    START(["/ccba-new-feature"]) ===> CHECK_PARAM{"Has #issue_id argument?"}
    
    CHECK_PARAM -->|"Yes (#id provided)"| DIRECT_VIEW["gh issue view <id> / Local Fallback"]
    CHECK_PARAM -->|"No (Bare invocation)"| SCAN_REMOTE["Auto-Scan: gh issue list --state open"]
    
    SCAN_REMOTE ===> HAS_ISSUES{"Found Open Issues?"}
    
    HAS_ISSUES -->|"No (Empty Backlog)"| MANUAL_INTERVIEW["Fallback: Interactive Interview (feat/fix/refactor)"]
    HAS_ISSUES -->|"Yes (Issues exist)"| RANK_ENGINE["Topological & Priority Ranking Engine"]
    
    subgraph Priority_Heuristics ["Topological Priority Heuristics"]
        P1["1. Hotfix / Critical Bugs"]
        P2["2. Architectural Refactoring & Deep Modules"]
        P3["3. Features & Enhancements"]
        P4["4. Performance & Documentation"]
        P1 ~~~ P2 ~~~ P3 ~~~ P4
    end
    
    RANK_ENGINE ===> Priority_Heuristics
    Priority_Heuristics ===> SHOW_MENU["Present Ranked Triage Menu (ask_question)"]
    
    SHOW_MENU ===> USER_SELECT{"User Choice"}
    
    USER_SELECT -->|"Selects Issue #X"| AUTO_CLAIM["Autonomous Claim: gh issue edit #X --add-assignee @me"]
    USER_SELECT -->|"Chooses 'Create new ad-hoc'"| MANUAL_INTERVIEW
    
    AUTO_CLAIM ===> AUTO_BRANCH["Auto-synthesize Branch: type/issue-X-slug"]
    DIRECT_VIEW ===> AUTO_BRANCH
    MANUAL_INTERVIEW ===> MANUAL_BRANCH["Synthesize Manual Branch"]
    
    AUTO_BRANCH ===> PLANNING_MODE["Step 6: Planning Phase (Auto-inject Issue Spec)"]
    MANUAL_BRANCH ===> PLANNING_MODE
```

### 3.2. Thuật Toán Phân Cấp Ưu Tiên (Topological Priority Heuristics)
Khi quét danh sách issues qua `gh issue list --state open --json number,title,labels,updatedAt,assignees`, Agent áp dụng 3 quy tắc lọc:

1. **Lọc trạng thái gán việc (Assignee Filter)**:
   - Ưu tiên các Issue **chưa có người nhận** (`assignees` rỗng) hoặc được gán cho chính user hiện tại (`@me`).
2. **Phân loại nhãn kỹ thuật (Label & Type Weight)**:
   - `P0 (Trọng số 4)`: Nhãn `bug`, `hotfix`, `critical` (cần vá trước để bảo đảm độ ổn định).
   - `P1 (Trọng số 3)`: Nhãn `refactor`, `architecture`, `clean-seams` (cần tối ưu cấu trúc trước khi đắp thêm tính năng mới để tránh merge conflicts).
   - `P2 (Trọng số 2)`: Nhãn `enhancement`, `feat`, `feature` (phát triển nghiệp vụ mới).
   - `P3 (Trọng số 1)`: Nhãn `performance`, `docs`, `chore`.
3. **Phân tích phụ thuộc ngữ nghĩa (Semantic Dependency Detection)**:
   - Nếu Issue $A$ là `refactor` một module (ví dụ: `wiki_health`) và Issue $B$ là `feat` bổ sung tính năng vào module đó (ví dụ: `BridgeCandidateFinder`), Agent sẽ tự động xếp Issue $A$ lên vị trí `(Recommended)` số 1 kèm lý do: *"Nền tảng kiến trúc cần giải quyết trước để tránh xung đột mã nguồn"*.

### 3.3. Tương Tác Người Dùng (Human-in-the-Loop Safeguard)
Để đảm bảo an toàn, Agent **không tự ý checkout âm thầm**, mà hiển thị menu tương tác trực quan:
```text
Phát hiện 3 Issues đang mở trên repository vvChu/vvc-second-brain-scripts:

1. (Recommended) #3 refactor(health): decompose wiki_health.py into deep module package
   ↳ Lý do: Tái cấu trúc nền tảng trước khi triển khai tính năng phụ thuộc.
2. #4 feat(graph): implement BridgeCandidateFinder for cross-domain knowledge synthesis
3. #5 perf(vectorstore): implement context-managed batch flush
4. [Tạo tính năng mới ngoài backlog] (Phỏng vấn thủ công)
```

---

## 4. Đặc Tả Sửa Đổi Cho `SKILL.md` (Code Diff Specification)

Dưới đây là phần nội dung sẽ được cập nhật vào **Bước 3** của tệp `ccba-new-feature/SKILL.md`:

```markdown
### Bước 3: Thu thập thông tin & Bóc tách Issue tự động (Hỗ trợ Autonomous Triage & Offline Fallback)

- **Trường hợp 1 (Có mã Issue cụ thể, ví dụ `/ccba-new-feature #228`):**
  - Gọi GitHub CLI để nạp đặc tả:
    ```bash
    gh issue view <issue_id> --json title,body,labels,assignees
    ```
  - **Tự động nhận diện loại công việc & tên branch:**
    - `feat(...)` -> `feat/issue-<id>-<slug>`
    - `fix(...)` -> `fix/issue-<id>-<slug>`
    - `refactor(...)` -> `refactor/issue-<id>-<slug>`
    - `perf(...)` -> `perf/issue-<id>-<slug>`
  - Chuyển thẳng sang Bước 4 (hoặc Bước 5) mà không hỏi lại người dùng.

- **Trường hợp 2 (Gọi trần không kèm mã Issue — Autonomous Remote Triage):**
  1. **Quét Backlog trên Remote Repo:**
     ```bash
     gh issue list --state open --limit 10 --json number,title,labels,assignees,updatedAt
     ```
  2. **Nếu có Open Issues:**
     - Phân loại và xếp hạng theo quy chuẩn: `bug/fix` > `refactor/architecture` > `feat/enhancement` > `perf/docs`.
     - Phân tích phụ thuộc ngữ nghĩa giữa các Issues (ví dụ: refactor nền tảng trước khi thêm tính năng vào cùng module).
     - Hiển thị menu cho người dùng xác nhận:
       - Lựa chọn 1: `(Khuyến nghị) #<id> <tiêu đề> [Lý giải kỹ thuật]`
       - Lựa chọn 2..N: Các Issues khả dụng khác
       - Lựa chọn cuối: `Tạo công việc mới ngoài backlog`
     - **Tự động Claim & Gán việc:**
       Sau khi người dùng chọn một Issue, Agent tự động gán việc cho người dùng hiện tại:
       ```bash
       gh issue edit <issue_id> --add-assignee "@me"
       ```
     - Chuyển tiếp sang Bước 4 để tạo branch gắn mã Issue tương ứng.
  3. **Nếu KHÔNG có Open Issues (hoặc người dùng chọn làm việc mới ngoài backlog):**
     - Rơi về luồng phỏng vấn tiêu chuẩn:
       + Loại công việc: `feat`, `fix`, `docs`, `refactor`, `perf`, `experiment`.
       + Mô tả ngắn gọn (3-5 từ).
```

---

## 5. Đánh Giá Khả Năng Tương Thích & Phòng Vệ Lỗi (Resilience & Backward Compatibility)

1. **Khả năng chạy Offline (Zero-Network Resilience)**:
   - Nếu lệnh `gh issue list` thất bại do mất mạng hoặc chưa xác thực token GitHub (`gh auth`), Agent tự động quét thư mục cục bộ `.md/knowledge/issues/` (nếu có).
   - Nếu cả hai đều không khả dụng, Agent lập tức fallback 100% sang luồng phỏng vấn thủ công hiện tại mà không văng exception hay làm dừng quy trình.
2. **Khả năng tương thích ngược (100% Backward Compatible)**:
   - Mọi câu lệnh cũ dạng `/ccba-new-feature #123` vẫn giữ nguyên 100% hành vi hiện tại (Trường hợp 1).
   - Không phá vỡ bất kỳ workflow CI/CD hay scripts tự động hóa nào đã có.
3. **Phòng vệ Trùng Lặp (Duplicate Claim Defense)**:
   - Chỉ khuyến nghị các issue chưa có người claim hoặc đang được gán cho chính user hiện tại, tránh xung đột quyền làm việc giữa các thành viên trong đội ngũ.

---

## 6. Lộ Trình Triển Khai Upstream Lên CCBA Hub

1. **Giai đoạn 1 (Đệ trình RFC & Phê duyệt)**:
   - Trình bày bản RFC này cho Core Architecture Team của CCBA Hub.
2. **Giai đoạn 2 (Cập nhật mã nguồn Hub)**:
   - Chỉnh sửa `ccba-agent-platform/.agents/skills/ccba-new-feature/SKILL.md`.
   - Bump version `metadata.version` lên `"1.3.0"`.
3. **Giai đoạn 3 (Kiểm chứng & Đồng bộ Spoke)**:
   - Chạy bộ kiểm thử tự động của Hub:
     ```bash
     python -m ccba_harness verify-patch
     ```
   - Chạy công cụ đồng bộ spoke (`python scripts/sync_spoke.py`) để các dự án thành viên (Spokes) tự động nhận diện năng lực mới.
