# 📱 Obsidian Mobile Sync — Hướng dẫn Setup (Android)

## Kiến trúc tổng thể

```
💻 PC (D:\VvC_Notes\)
  ↕ vault_sync.py (60s poll, bidirectional)
☁️ Google Drive (G:\My Drive\VvC_Vault\)
  ↕ Google Drive cloud sync (auto)
☁️ Google Drive cloud
  ↕ FolderSync app (Android, scheduled 5min)
📱 Phone (/storage/emulated/0/VvC_Vault/)
  ↕ Obsidian Android (open as vault)
```

## Folder đồng bộ

| Folder | Size | Sync? | Lý do |
|---|---|---|---|
| `00 - Maps of Content/` | 0.1MB | ✅ | Index, MOC pages |
| `04 - Permanent/` | 0.9MB | ✅ | Concepts + Sources (knowledge) |
| `templates/` | ~0MB | ✅ | Note templates |
| `03 - Resources/` | 42MB | ❌ | Sách nặng, chỉ cần trên PC |
| `05 - Fleeting/` | ~0MB | ❌ | Daemon workspace, conflict risk |
| `99 - Archive/` | 105MB | ❌ | Ảnh đã xử lý |
| `scripts/` | 201MB | ❌ | Code, .venv |

**Tổng sync: ~1MB (319 files)** — rất nhẹ, sync gần như tức thì.

---

## Setup trên Android (từng bước)

### Bước 1: Cài apps
1. **Google Drive** — đã có sẵn trên Android
2. **FolderSync Pro** — [Play Store](https://play.google.com/store/apps/details?id=dk.tacit.android.foldersync.full) ($5 một lần)
   - Hoặc dùng bản free **FolderSync Lite** (giới hạn 1 folderpair)
3. **Obsidian** — [Play Store](https://play.google.com/store/apps/details?id=md.obsidian)

### Bước 2: Cấu hình FolderSync

1. **Thêm tài khoản Google:**
   - FolderSync → **Accounts** → **Add account**
   - Chọn **Google Drive**
   - Đăng nhập **chu.ibst@gmail.com**

2. **Tạo Folderpair:**
   - FolderSync → **Folderpairs** → **Create folderpair**
   - **Account:** Google Drive (chu.ibst@gmail.com)
   - **Sync type:** `Two-way`
   - **Remote folder:** `VvC_Vault` (chọn từ GDrive)
   - **Local folder:** Tạo folder `/VvC_Vault/` trong bộ nhớ trong
     - Gợi ý: `/storage/emulated/0/VvC_Vault/`

3. **Cấu hình nâng cao (QUAN TRỌNG):**

   Sau khi tạo folderpair, tap vào nó để vào trang cấu hình chi tiết.
   Bên dưới là **toàn bộ settings cần thiết**, chia theo từng mục:

---

#### 3a. Sync Options (Tùy chọn đồng bộ)

| Setting | Giá trị | Lý do |
|---|---|---|
| **Sync type** | `Two-way` | Cho phép đọc + viết từ cả 2 phía |
| **Sync subfolders** | ✅ Bật | Vault có cấu trúc thư mục lồng nhau |
| **Sync hidden files** | ❌ **Tắt** | Bỏ qua `.obsidian/` config, `.trash/` |
| **Sync deletions** | ✅ Bật | Khi xóa 1 bên → xóa bên kia |
| **Only resync source on change** | ❌ Tắt | Đảm bảo 2 chiều luôn được quét |

> ⚠️ **Sync hidden files = TẮT** là setting quan trọng nhất.
> Nếu bật, `.obsidian/` (plugins, themes, config) sẽ sync giữa PC ↔ Phone
> gây xung đột vì mỗi platform có plugin riêng.

---

#### 3b. Scheduling (Lịch đồng bộ)

| Setting | Giá trị | Lý do |
|---|---|---|
| **Scheduled sync** | ✅ Bật | Tự động sync theo lịch |
| **Sync interval** | `5 phút` | Cân bằng real-time vs pin |
| **Use WiFi** | `WiFi or mobile data` | Sync mọi lúc (vault chỉ ~1MB) |
| **Retry sync on fail** | ✅ Bật | Auto-retry nếu mất mạng |
| **Sync when charging** | Tùy chọn | Bật nếu lo pin |

> 💡 Vault chỉ **~1MB text**, nên sync qua 4G cũng không đáng kể.
> Nếu lo pin, tăng interval lên 15 phút.

---

#### 3c. Conflict Resolution (Xử lý xung đột)

| Setting | Giá trị | Lý do |
|---|---|---|
| **If conflict** | `Keep both` | An toàn nhất — không mất data |
| **Overwrite old files** | ✅ Bật | File mới hơn ghi đè file cũ |
| **If both modified** | `Keep both` | Tạo bản copy nếu cả 2 sửa |

> **Giải thích `Keep both`:**
> Nếu bạn edit `concept_A.md` trên cả PC và Phone trước khi sync kịp,
> FolderSync sẽ giữ **cả 2 bản** — bản mới hơn giữ tên gốc, bản cũ hơn
> được rename thành `concept_A (conflict).md`.
> Bạn mở Obsidian → so sánh → merge thủ công → xóa file conflict.

---

#### 3d. Filters (Bộ lọc — QUAN TRỌNG)

Vào tab **Filters** trong folderpair. Thêm các exclude filter sau:

**Exclude Folder filters** (tap "Add folder filter"):

| Filter type | Pattern | Mục đích |
|---|---|---|
| Folder name equals | `.obsidian` | Config/plugins PC ≠ Mobile |
| Folder name equals | `.trash` | Thùng rác Obsidian |
| Folder name equals | `.git` | Nếu dùng Git plugin |
| Folder name equals | `_command_archive` | Archive Command.md cũ |

**Exclude File filters** (tap "Add file filter"):

| Filter type | Pattern | Mục đích |
|---|---|---|
| File name contains | `_conflict_` | Bỏ qua conflict files từ vault_sync.py |
| File name equals | `.DS_Store` | macOS artifact (nếu có) |

> 💡 **Regex thay thế** (cho advanced users):
> Thay vì thêm từng folder, dùng 1 filter duy nhất:
> - Filter type: `Folder name RegEx`
> - Pattern: `^\.(obsidian|trash|git)$`
> Hiệu quả tương đương 3 folder filters trên.

---

#### 3e. Notifications & Battery

| Setting | Giá trị | Lý do |
|---|---|---|
| **Show notification** | `Only on changes` | Biết khi có file mới |
| **Show sync progress** | ❌ Tắt | Giảm distraction |
| **Exclude from force sync** | ❌ Tắt | Để "Sync All" bao gồm vault |

**Battery optimization (Android):**
1. Settings → Apps → FolderSync → Battery → `Unrestricted`
2. Hoặc: Settings → Battery → Battery optimization → FolderSync → `Don't optimize`

> ⚠️ Nếu không tắt battery optimization, Android sẽ kill FolderSync
> khi màn hình tắt → sync không chạy nền.

---

#### 3f. Obsidian Mobile Settings (sau khi sync xong)

Mở Obsidian trên phone → Settings → cấu hình:

| Setting | Giá trị | Lý do |
|---|---|---|
| **Editor → Spell check** | Tùy (nên tắt cho VN) | Spell check EN sẽ highlight tiếng Việt |
| **Files & Links → Default location for new notes** | `04 - Permanent/concepts` | Notes mới vào đúng folder |
| **Files & Links → Attachment folder path** | `attachments` | Ảnh đính kèm gọn gàng |
| **Core plugins → Templates** | Bật, folder: `templates` | Dùng template khi tạo note |
| **Appearance → Theme** | Tùy chọn | Khác theme PC cũng OK |

4. **Chạy sync lần đầu:**
   - Tap **Sync** button trên folderpair
   - Đợi hoàn tất (~319 files, ~1MB, <30s)

### Bước 3: Mở trong Obsidian

1. Mở **Obsidian** → **Open folder as vault**
2. Navigate to `/VvC_Vault/`
3. **Done!** 📱

### Bước 4: Test 2-way sync

**Test Phone → PC:**
1. Trên phone: Tạo note mới trong `04 - Permanent/concepts/`
2. Đợi FolderSync chạy (hoặc manual sync)
3. Trên PC: Check `D:\VvC_Notes\04 - Permanent\concepts\` — note mới xuất hiện

**Test PC → Phone:**
1. Trên PC: Daemon tạo concept note mới
2. vault_sync.py push lên GDrive (60s)
3. FolderSync pull xuống phone (5min)
4. Trên phone: Note mới xuất hiện

---

## Xử lý Conflict

**Khi nào conflict xảy ra?**
- Bạn edit **cùng 1 file** trên cả PC và Phone **cùng lúc** (hiếm)

**Cách hệ thống xử lý:**
- `vault_sync.py` (PC side): Nếu cả 2 bên modified within 5s → tạo file `_conflict_<timestamp>.md`
- FolderSync (Phone side): `Keep both` → giữ cả 2 version
- Bạn review và merge thủ công → xóa file conflict

---

## Lưu ý quan trọng

> ⚠️ **Không mở Obsidian trên cả 2 devices cùng lúc edit cùng file**
> 
> Sync qua cloud có delay (~1-5 phút). Nếu edit cùng file trên 2 devices
> trước khi sync kịp, sẽ tạo conflict.

> ⚠️ **Lần đầu mở Obsidian trên phone — đợi sync xong**
> 
> Sau khi FolderSync pull xong, mở Obsidian. Nếu mở trước khi sync xong,
> Obsidian có thể báo vault trống.

---

## Daemon architecture (PC side)

```
run_watcher.vbs
├── daemon.py              ← LLM OS (OCR, synthesis)
└── vault_sync.py          ← Vault ↔ GDrive (bidirectional)
```

Book ingestion (`book_ingestion_daemon.py`) chạy on-demand hoặc qua Task Scheduler.
Tất cả chạy headless via `pythonw.exe`, auto-start khi login.
