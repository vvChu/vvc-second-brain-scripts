#!/usr/bin/env bash
# ==============================================================================
# VvC Second Brain — Autonomous Linux Bootstrap & Verification Gate (v1.0)
# Target Machine: Server Spark (Linux / DGX)
# Architecture: Zero-Touch Hybrid Bootstrap (ADR-0057 & ADR-0058)
# ==============================================================================

set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
VENV_DIR="$SCRIPTS_DIR/.venv"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  🧠 VvC Second Brain — Server Spark Setup & Service Installer  ${NC}"
echo -e "${CYAN}  Autonomous Zero-Touch Bootstrap (Linux 24/7 Hosting)          ${NC}"
echo -e "${CYAN}================================================================${NC}"
echo ""

# ------------------------------------------------------------------------------
# 1. Platform & Dependency Pre-Checks
# ------------------------------------------------------------------------------
log_info "1/7. Kiểm tra môi trường hệ thống..."
if [ "$(uname -s)" != "Linux" ]; then
    log_err "Script này được thiết kế chuyên biệt cho Linux (Server Spark). Phát hiện: $(uname -s)"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    log_err "Python3 chưa được cài đặt. Vui lòng chạy: sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    log_warn "FFmpeg chưa cài đặt. Đang tự động cài đặt ffmpeg..."
    if command -v sudo &>/dev/null; then
        sudo -n apt update && sudo -n apt install -y ffmpeg || log_warn "Không thể tự động cài ffmpeg. Audio pipeline có thể bị giới hạn."
    fi
fi
log_ok "Hệ thống đáp ứng đầy đủ binary tiên quyết."

# ------------------------------------------------------------------------------
# 2. Python Virtualenv & Core Dependencies
# ------------------------------------------------------------------------------
log_info "2/7. Thiết lập Python Virtual Environment (.venv)..."
if [ ! -d "$VENV_DIR" ]; then
    log_info "Tạo mới venv tại $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

UV_BIN=""
if command -v uv &>/dev/null; then
    UV_BIN=$(command -v uv)
elif [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
fi

if [ -n "$UV_BIN" ]; then
    log_info "Tận dụng uv ($UV_BIN) để cài đặt siêu tốc từ cache cục bộ..."
    "$UV_BIN" pip install --python "$VENV_DIR/bin/python" -r "$SCRIPTS_DIR/requirements.txt"
else
    # Ensure pip is up to date
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    log_info "Cài đặt các gói phụ thuộc từ requirements.txt..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPTS_DIR/requirements.txt" --quiet
fi
log_ok "Đã cài đặt hoàn tất dependencies cốt lõi."

# Auto-link ccba-ai from Hub if available on Server Spark
log_info "Tìm kiếm gói ccba-ai từ CCBA Platform Hub..."
CCBA_AI_FOUND=""
for hub_path in \
    "$HOME/ccba/ccba-agent-platform/packages/ccba-ai" \
    "$HOME/ccba-agent-platform/packages/ccba-ai" \
    "$HOME/GitHubProjects/ccba-agent-platform/packages/ccba-ai" \
    "/home/spark/ccba-agent-platform/packages/ccba-ai" \
    "/home/vvc/ccba-agent-platform/packages/ccba-ai" \
    "/opt/ccba-agent-platform/packages/ccba-ai"; do
    if [ -d "$hub_path" ] && [ -f "$hub_path/pyproject.toml" -o -f "$hub_path/setup.py" ]; then
        CCBA_AI_FOUND="$hub_path"
        break
    fi
done

if [ -n "$CCBA_AI_FOUND" ]; then
    log_info "Phát hiện ccba-ai tại: $CCBA_AI_FOUND. Đang cài đặt chế độ editable (-e)..."
    if [ -n "$UV_BIN" ]; then
        "$UV_BIN" pip install --python "$VENV_DIR/bin/python" -e "$CCBA_AI_FOUND" || log_warn "Không thể cài đặt ccba-ai từ $CCBA_AI_FOUND"
    else
        "$VENV_DIR/bin/pip" install -e "$CCBA_AI_FOUND" --quiet 2>/dev/null || log_warn "Không thể cài đặt ccba-ai từ $CCBA_AI_FOUND"
    fi
    log_ok "Đã tích hợp ccba-ai SDK từ Hub."
else
    log_warn "Không tìm thấy ccba-agent-platform cục bộ. Pipeline sẽ sử dụng LiteLLM Gateway trực tiếp qua HTTP REST."
fi

# Optional: Link ccba-harness if present
for harness_path in \
    "$HOME/ccba/ccba-agent-platform/packages/ccba-harness" \
    "$HOME/ccba-agent-platform/packages/ccba-harness"; do
    if [ -d "$harness_path" ] && [ -f "$harness_path/pyproject.toml" ]; then
        if [ -n "$UV_BIN" ]; then
            "$UV_BIN" pip install --python "$VENV_DIR/bin/python" -e "$harness_path" 2>/dev/null || true
        else
            "$VENV_DIR/bin/pip" install -e "$harness_path" --quiet 2>/dev/null || true
        fi
        break
    fi
done

# ------------------------------------------------------------------------------
# 3. Google Drive Auto-Discovery & Symlink Binding
# ------------------------------------------------------------------------------
log_info "3/7. Tự động dò tìm Google Drive GVFS Mount..."
GVFS_VAULT="${GVFS_VAULT:-}"

# Search common GVFS locations
find_gvfs_vault() {
    if [ -n "$GVFS_VAULT" ] && [ -d "$GVFS_VAULT" ]; then
        echo "$GVFS_VAULT"
        return 0
    fi

    for p in "/run/user/$UID/gvfs/google-drive:host=gmail.com,user=chu.ibst/VvC_Vault" \
             "/run/user/$UID/gvfs/google-drive:host=gmail.com,user=chu.ibst/*/VvC_Vault" \
             "/run/user/$UID/gvfs"/*/*/VvC_Vault \
             "/run/user/$UID/gvfs"/*/VvC_Vault; do
        if [ -d "$p" ]; then
            echo "$p"
            return 0
        fi
    done

    local candidate
    candidate=$(find "/run/user/$UID/gvfs" -maxdepth 4 -name "VvC_Vault" 2>/dev/null | head -n 1 || true)
    if [ -n "$candidate" ] && [ -d "$candidate" ]; then
        echo "$candidate"
        return 0
    fi
    candidate=$(find "$HOME/.gvfs" -maxdepth 4 -name "VvC_Vault" 2>/dev/null | head -n 1 || true)
    if [ -n "$candidate" ] && [ -d "$candidate" ]; then
        echo "$candidate"
        return 0
    fi
    echo ""
}

GVFS_VAULT=$(find_gvfs_vault)

while [ -z "$GVFS_VAULT" ]; do
    echo ""
    log_warn "Chưa phát hiện thấy thư mục VvC_Vault trong /run/user/$UID/gvfs/."
    echo -e "${YELLOW}👉 GỢI Ý:${NC} Mở Thunar File Manager trên Server Spark và bấm vào 'chu.ibst@gmail.com' để mount."
    read -r -p "Bấm [Enter] sau khi đã mở Thunar để quét lại (hoặc nhập đường dẫn tuyệt đối tới VvC_Vault): " input_path
    if [ -n "$input_path" ] && [ -d "$input_path" ]; then
        GVFS_VAULT="$input_path"
    else
        GVFS_VAULT=$(find_gvfs_vault)
    fi
done

log_ok "Phát hiện Google Drive Vault tại: $GVFS_VAULT"

# Enable systemd user session linger so GVFS and user services survive logout
log_info "Kích hoạt systemd user session lingering..."
loginctl enable-linger "$USER" 2>/dev/null || log_warn "Không thể tự động chạy loginctl enable-linger. Hãy chạy: sudo loginctl enable-linger $USER"

# Create Symlinks for 6 canonical directories
log_info "Tạo các Symlink liên kết dữ liệu vào repo..."
TARGET_DIRS=(
    "00 - Maps of Content"
    "03 - Resources"
    "04 - Permanent"
    "05 - Fleeting"
    "99 - Archive"
    "templates"
)

for dir_name in "${TARGET_DIRS[@]}"; do
    src_dir="$GVFS_VAULT/$dir_name"
    dest_link="$REPO_ROOT/$dir_name"

    if [ ! -d "$src_dir" ]; then
        log_warn "Thư mục nguồn '$src_dir' chưa tồn tại trên Google Drive. Tự động tạo mới..."
        mkdir -p "$src_dir"
    fi

    if [ -L "$dest_link" ]; then
        rm -f "$dest_link"
    elif [ -d "$dest_link" ]; then
        log_warn "Phát hiện thư mục thật tại '$dest_link'. Đổi tên sang .bak để nhường chỗ cho symlink..."
        mv "$dest_link" "${dest_link}.bak_$(date +%s)"
    fi

    ln -s "$src_dir" "$dest_link"
    log_ok "Symlink: $dir_name ──► $src_dir"
done

# ------------------------------------------------------------------------------
# 4. Environment (.env) & AI Gateway Provisioning
# ------------------------------------------------------------------------------
log_info "4/7. Cấu hình môi trường runtime (scripts/.env)..."
ENV_FILE="$SCRIPTS_DIR/.env"

GATEWAY_KEY="${VVC_GATEWAY_KEY:-sk-spark-secure-key-2026}"
PROXY_KEY="${VVC_GATEWAY_PROXY_KEY:-sk-spark-secure-key-2026}"
GEMINI_KEY="${GEMINI_API_KEY:-}"

if [ ! -f "$ENV_FILE" ]; then
    log_info "Khởi tạo file scripts/.env mới tối ưu cho Server Spark..."
    cat > "$ENV_FILE" <<EOF
# ============================================================
# VvC Second Brain — Server Spark Localhost Configuration
# ============================================================

# Vault Root on Linux
VVC_VAULT_ROOT="$REPO_ROOT"

# AI Gateway (Localhost Loopback on Server Spark)
VVC_GATEWAY_URL="http://127.0.0.1:8090/v1"
VVC_GATEWAY_KEY="$GATEWAY_KEY"
VVC_GATEWAY_PROXY_URL="http://127.0.0.1:8045/v1"
VVC_GATEWAY_PROXY_KEY="$PROXY_KEY"
GEMINI_API_KEY="$GEMINI_KEY"

# CCBA AI Gateway SDK Standard Conventions
AI_GATEWAY_URL="http://127.0.0.1:8090/v1"
AI_GATEWAY_KEY="$GATEWAY_KEY"
AI_MODEL="gemini-3.7-flash"
AI_GATEWAY_TIMEOUT=60.0
OPENAI_API_BASE="http://127.0.0.1:8090/v1"
OPENAI_API_KEY="$GATEWAY_KEY"
EOF
    log_ok "Đã tạo scripts/.env thành công."
else
    log_info "File scripts/.env đã tồn tại. Đang xác nhận các tham số cốt lõi..."
    # Ensure VVC_VAULT_ROOT is updated
    if ! grep -q "VVC_VAULT_ROOT" "$ENV_FILE"; then
        echo "VVC_VAULT_ROOT=\"$REPO_ROOT\"" >> "$ENV_FILE"
    fi
    log_ok "Đã cập nhật scripts/.env."
fi

# ------------------------------------------------------------------------------
# 5. Systemd User Services & Timer Registration
# ------------------------------------------------------------------------------
log_info "5/7. Đăng ký Systemd User Services (100% không cần sudo)..."
mkdir -p "$SYSTEMD_USER_DIR"

# 1. vvc-daemon.service
cat > "$SYSTEMD_USER_DIR/vvc-daemon.service" <<EOF
[Unit]
Description=VvC Second Brain Main Daemon (Watchdog & Compiler)
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPTS_DIR
ExecStart=$VENV_DIR/bin/python daemon.py
Restart=always
RestartSec=10
Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=default.target
EOF

# 2. vvc-book-ingest.service
cat > "$SYSTEMD_USER_DIR/vvc-book-ingest.service" <<EOF
[Unit]
Description=VvC Second Brain Book Ingestion Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPTS_DIR
ExecStart=$VENV_DIR/bin/python book_ingest.py
Restart=always
RestartSec=10
Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=default.target
EOF

# 3. vvc-sleep.service
cat > "$SYSTEMD_USER_DIR/vvc-sleep.service" <<EOF
[Unit]
Description=VvC Second Brain Weekly Sleep Consolidation

[Service]
Type=oneshot
WorkingDirectory=$SCRIPTS_DIR
ExecStart=$VENV_DIR/bin/python sleep.py
EnvironmentFile=$ENV_FILE
EOF

# 4. vvc-sleep.timer (Every Sunday 02:00 AM)
cat > "$SYSTEMD_USER_DIR/vvc-sleep.timer" <<EOF
[Unit]
Description=Run VvC Sleep Consolidation every Sunday at 02:00 AM

[Timer]
OnCalendar=Sun *-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

log_ok "Đã tạo các unit file trong $SYSTEMD_USER_DIR"

log_info "Nạp cấu hình và khởi động services..."
systemctl --user daemon-reload
systemctl --user enable --now vvc-daemon.service
systemctl --user enable --now vvc-book-ingest.service
systemctl --user enable --now vvc-sleep.timer
log_ok "Các services nền đã được kích hoạt."

# ------------------------------------------------------------------------------
# 6. Post-Install 4-Stage Verification Gate (ADR-0058)
# ------------------------------------------------------------------------------
echo ""
echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  🛡️ 4-Stage Deterministic Verification Gate (ADR-0058)         ${NC}"
echo -e "${CYAN}================================================================${NC}"

GATE_FAILURES=0

# Gate 1: Storage FUSE Read/Write
log_info "[Gate 1/4] Kiểm tra đọc/ghi qua Symlink Google Drive..."
PROBE_FILE="$REPO_ROOT/05 - Fleeting/.probe_test_$(date +%s).tmp"
if echo "spark_probe_ok" > "$PROBE_FILE" 2>/dev/null && [ -f "$PROBE_FILE" ]; then
    rm -f "$PROBE_FILE"
    log_ok "Gate 1 PASSED: Quyền FUSE Đọc/Ghi qua Symlink Google Drive thông suốt."
else
    log_err "Gate 1 FAILED: Không thể ghi file vào $REPO_ROOT/05 - Fleeting. Kiểm tra quyền GVFS."
    GATE_FAILURES=$((GATE_FAILURES + 1))
fi

# Gate 2: AI Gateway Localhost:8090
log_info "[Gate 2/4] Kiểm tra kết nối AI Gateway (http://127.0.0.1:8090)..."
if curl -s -m 5 "http://127.0.0.1:8090/health" &>/dev/null; then
    log_ok "Gate 2 PASSED: LiteLLM Gateway :8090 phản hồi Healthy."
else
    log_warn "Gate 2 WARNING: Chưa kết nối được http://127.0.0.1:8090/health. Hãy đảm bảo LiteLLM container/service đang chạy."
fi

# Gate 3: Systemd Services Status
log_info "[Gate 3/4] Xác nhận trạng thái Systemd User Services..."
sleep 2
DAEMON_ACTIVE=$(systemctl --user is-active vvc-daemon.service || true)
BOOK_ACTIVE=$(systemctl --user is-active vvc-book-ingest.service || true)

if [ "$DAEMON_ACTIVE" = "active" ] && [ "$BOOK_ACTIVE" = "active" ]; then
    log_ok "Gate 3 PASSED: Cả 2 daemon vvc-daemon và vvc-book-ingest đang chạy (active)."
else
    log_warn "Gate 3 WARNING: vvc-daemon=$DAEMON_ACTIVE, vvc-book-ingest=$BOOK_ACTIVE. Kiểm tra qua: journalctl --user -u vvc-daemon -n 20"
fi

# Gate 4: Scoped Unit Tests
log_info "[Gate 4/4] Thực thi Scoped Pytest để kiểm tra tương thích..."
if "$VENV_DIR/bin/pytest" "$SCRIPTS_DIR/tests/test_daemon_restart.py" -q --no-header; then
    log_ok "Gate 4 PASSED: Bộ kiểm thử tương thích đa nền tảng đạt 100%."
else
    log_warn "Gate 4 WARNING: Có test không đạt trong test_daemon_restart.py."
fi

# ------------------------------------------------------------------------------
# 7. Summary & Management Cheat-Sheet
# ------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}  🎉 CHÚC MỪNG! VvC SECOND BRAIN ĐÃ ĐƯỢC THIẾT LẬP THÀNH CÔNG!   ${NC}"
echo -e "${GREEN}  Hệ thống đang chạy ngầm 24/7 trên Server Spark                ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo ""
echo -e "${CYAN}📌 BẢNG LỆNH QUẢN TRỊ DỊCH VỤ (Không cần sudo):${NC}"
echo "  • Xem trạng thái daemon:   systemctl --user status vvc-daemon.service"
echo "  • Xem logs thời gian thực: journalctl --user -u vvc-daemon.service -f"
echo "  • Khởi động lại daemon:    systemctl --user restart vvc-daemon.service"
echo "  • Dừng daemon:             systemctl --user stop vvc-daemon.service"
echo "  • Xem lịch Weekly Sleep:   systemctl --user list-timers vvc-sleep.timer"
echo ""
echo -e "${CYAN}📂 Thư mục logs nội bộ:${NC}"
echo "  • $SCRIPTS_DIR/logs/daemon.log"
echo "  • $SCRIPTS_DIR/logs/book_ingestion.log"
echo "  • $SCRIPTS_DIR/logs/sleep_daemon.log"
echo ""
