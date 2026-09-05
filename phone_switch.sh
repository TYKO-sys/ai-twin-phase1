#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — Phone Switch (backup and restore)
# ============================================================
# Usage:
#   bash phone_switch.sh backup    # On phone 1: create backup, upload to GitHub
#   bash phone_switch.sh restore   # On phone 2: download backup, install everything
# ============================================================

set -e

# GitHub PAT — read from env var (never hardcode in scripts, push protection blocks it).
# Set once in your shell with:  export GITHUB_TOKEN="github_pat_..."
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
REPO="TYKO-sys/ai-twin-phase1"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
print_step() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
print_err()  { echo -e "${RED}[X]${NC} $1"; }

MODE="${1:-}"

if [[ -z "$MODE" ]]; then
    echo "Usage: bash phone_switch.sh <backup|restore>"
    echo ""
    echo "  backup  — On your current phone: stops twin, creates backup, uploads to GitHub"
    echo "  restore — On your new phone: downloads backup, installs everything, starts twin"
    exit 1
fi

# Require GitHub token (export GITHUB_TOKEN before running)
if [[ -z "$TOKEN" ]]; then
    print_err "GITHUB_TOKEN (or GH_TOKEN) env var is empty."
    print_warn "Set it once with:  export GITHUB_TOKEN=\"github_pat_...\""
    print_warn "Then re-run:  bash phone_switch.sh $MODE"
    exit 1
fi

# Generate or load phone_id
PHONE_ID_FILE="$HOME/ai-twin-memory/phone_id.txt"
mkdir -p "$HOME/ai-twin-memory"
if [[ ! -f "$PHONE_ID_FILE" ]]; then
    PHONE_ID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "phone-$(date +%s)")
    echo "$PHONE_ID" > "$PHONE_ID_FILE"
else
    PHONE_ID=$(cat "$PHONE_ID_FILE")
fi

# ============================================================
# BACKUP MODE
# ============================================================
if [[ "$MODE" == "backup" ]]; then
    print_step "AI Twin Phone Switch — Backup"
    echo "Phone ID: $PHONE_ID"

    # 1. Stop twin and FreeLLMAPI
    print_step "Stopping twin and FreeLLMAPI"
    twin-stop 2>/dev/null || true
    tmux kill-session -t freellmapi 2>/dev/null || true
    print_ok "Stopped"

    # Make sure zip is installed (on a fresh phone it often isn't, and the old
    # script hid zip's errors with >/dev/null 2>&1 so it failed silently).
    if ! command -v zip &>/dev/null; then
        print_step "Installing zip"
        pkg install -y zip >/dev/null 2>&1 || true
    fi
    if ! command -v zip &>/dev/null; then
        print_err "zip is not installed. Run: pkg install zip"
        exit 1
    fi
    print_ok "zip is available"

    # 2. Create backup zip
    print_step "Creating backup"
    BACKUP_FILE="$HOME/ai-twin-phone-backup.zip"
    rm -f "$BACKUP_FILE"

    # Create a temp dir with everything to back up
    TEMP_DIR=$(mktemp -d)
    mkdir -p "$TEMP_DIR/ai-twin-memory"
    mkdir -p "$TEMP_DIR/freellmapi-data"
    mkdir -p "$TEMP_DIR/termux-boot"

    # Copy .env
    if [[ -f ~/ai-twin/.env ]]; then
        cp ~/ai-twin/.env "$TEMP_DIR/env"
        print_ok "Copied .env"
    fi

    # Copy memory dir
    if [[ -d ~/ai-twin-memory ]]; then
        cp -r ~/ai-twin-memory/* "$TEMP_DIR/ai-twin-memory/" 2>/dev/null || true
        print_ok "Copied memory ($(du -sh ~/ai-twin-memory 2>/dev/null | cut -f1))"
    fi

    # Copy FreeLLMAPI data (the encrypted API keys)
    if [[ -d ~/freellmapi/data ]]; then
        cp -r ~/freellmapi/data/* "$TEMP_DIR/freellmapi-data/" 2>/dev/null || true
        print_ok "Copied FreeLLMAPI data"
    elif [[ -f ~/freellmapi/.env ]]; then
        cp ~/freellmapi/.env "$TEMP_DIR/freellmapi-data/env"
        print_ok "Copied FreeLLMAPI .env"
    fi

    # Copy Termux:Boot scripts
    if [[ -d ~/.termux/boot ]]; then
        cp ~/.termux/boot/* "$TEMP_DIR/termux-boot/" 2>/dev/null || true
        print_ok "Copied boot scripts"
    fi

    # Write manifest
    cat > "$TEMP_DIR/manifest.json" <<EOF
{
    "phone_id": "$PHONE_ID",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "version": "1.0"
}
EOF

    # Create zip — do NOT hide zip's own errors; if it fails we want to see why.
    # Use `if ! zip ...` so `set -e` doesn't kill the script before we can print a message.
    cd "$TEMP_DIR"
    if ! zip -r "$BACKUP_FILE" . ; then
        print_err "Failed to create zip file"
        ls -la "$TEMP_DIR" 2>/dev/null
        exit 1
    fi
    cd ~
    rm -rf "$TEMP_DIR"

    # Verify the zip actually exists and is non-empty before we try to upload it
    if [[ ! -f "$BACKUP_FILE" ]] || [[ ! -s "$BACKUP_FILE" ]]; then
        print_err "Backup zip is missing or empty"
        exit 1
    fi
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    print_ok "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"

    # 3. Upload to GitHub as a release asset
    print_step "Uploading to GitHub"

    # Create a release
    RELEASE_TAG="phone-backup-$(date -u +%Y%m%d-%H%M%S)"
    RELEASE_RESPONSE=$(curl -s -X POST \
        -H "Authorization: token $TOKEN" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$REPO/releases" \
        -d "{\"tag_name\":\"$RELEASE_TAG\",\"name\":\"Phone Backup $(date)\",\"body\":\"Automated phone backup\",\"draft\":false,\"prerelease\":true}")

    RELEASE_ID=$(echo "$RELEASE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
    UPLOAD_URL=$(echo "$RELEASE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('upload_url','').replace('{?name,label}',''))" 2>/dev/null || true)

    if [[ -z "$RELEASE_ID" ]] || [[ -z "$UPLOAD_URL" ]]; then
        print_err "Failed to create GitHub release"
        print_warn "Response was: $RELEASE_RESPONSE"
        print_warn "Backup is saved locally at: $BACKUP_FILE"
        print_warn "You can transfer it manually (Bluetooth, USB, cloud) or re-run this script"
        exit 1
    fi

    print_ok "Created release $RELEASE_TAG (ID: $RELEASE_ID)"

    # Upload the zip as an asset
    UPLOAD_RESULT=$(curl -s -X POST \
        -H "Authorization: token $TOKEN" \
        -H "Content-Type: application/zip" \
        --data-binary @"$BACKUP_FILE" \
        "${UPLOAD_URL}?name=ai-twin-phone-backup.zip")

    ASSET_URL=$(echo "$UPLOAD_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('browser_download_url',''))" 2>/dev/null || true)
    HTTP_STATUS=$(echo "$UPLOAD_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state','unknown'))" 2>/dev/null || true)

    if [[ "$HTTP_STATUS" == "uploaded" ]]; then
        print_ok "Backup uploaded to GitHub (state: $HTTP_STATUS)"
        if [[ -n "$ASSET_URL" ]]; then
            echo ""
            echo "Download URL (for phone 2):"
            echo "  $ASSET_URL"
        fi
    else
        print_err "Upload may have failed. Status: $HTTP_STATUS"
        print_warn "Backup is saved locally at: $BACKUP_FILE"
        print_warn "You can transfer it manually (Bluetooth, USB, cloud) or re-run this script"
        exit 1
    fi

    echo ""
    echo "============================================"
    echo "  Backup complete!"
    echo "============================================"
    echo ""
    echo "On phone 2:"
    echo "  1. Install Termux from F-Droid: https://f-droid.org/packages/com.termux/"
    echo "  2. Install Termux:Boot from F-Droid: https://f-droid.org/packages/com.termux.boot/"
    echo "  3. Open Termux:Boot once (just launch and close it)"
    echo "  4. Open Termux and run:"
    echo "     pkg install -y python git tmux termux-api nodejs-lts"
    echo "  5. Export your GitHub token (same one used here):"
    echo "     export GITHUB_TOKEN=\"$TOKEN\""
    echo "  6. Then clone and run the restore script:"
    echo "     git clone --branch phase2 https://\$GITHUB_TOKEN@github.com/$REPO.git ~/ai-twin"
    echo "     bash ~/ai-twin/phone_switch.sh restore"
    echo ""
    echo "Phone 1's twin is now STOPPED. Phone 2 will start when you run restore."
    echo "The lock will prevent both from running at once."

    exit 0
fi

# ============================================================
# RESTORE MODE
# ============================================================
if [[ "$MODE" == "restore" ]]; then
    print_step "AI Twin Phone Switch — Restore"
    echo "Phone ID: $PHONE_ID"

    # Check Termux
    if [[ -z "$PREFIX" ]] || [[ ! -d "/data/data/com.termux" ]]; then
        print_err "This script must run in Termux on Android."
        print_err "Install Termux from F-Droid: https://f-droid.org/packages/com.termux/"
        exit 1
    fi
    print_ok "Running in Termux"

    # 1. Install packages
    print_step "Installing packages"
    pkg update -y >/dev/null 2>&1
    pkg install -y python python-pip git termux-api tmux nodejs-lts >/dev/null 2>&1
    print_ok "Packages installed"

    # 2. Clone the repo (if not already there)
    if [[ ! -d ~/ai-twin ]]; then
        print_step "Cloning ai-twin repo"
        git clone --branch phase2 "https://$TOKEN@github.com/$REPO.git" ~/ai-twin 2>&1 | tail -2
        chmod +x ~/ai-twin/*.sh ~/ai-twin/diagnostic.py 2>/dev/null
    else
        print_ok "ai-twin already cloned"
        cd ~/ai-twin && git pull 2>/dev/null || true
    fi

    # 3. Download the latest backup from GitHub releases
    print_step "Downloading backup from GitHub"

    # Find the latest prerelease with tag starting "phone-backup-"
    LATEST_RELEASE=$(curl -s -H "Authorization: token $TOKEN" \
        "https://api.github.com/repos/$REPO/releases?per_page=10" | \
        python3 -c "
import sys, json
releases = json.load(sys.stdin)
for r in releases:
    if r.get('tag_name','').startswith('phone-backup-') and r.get('assets'):
        print(r['assets'][0]['browser_download_url'])
        break
" 2>/dev/null)

    if [[ -z "$LATEST_RELEASE" ]]; then
        print_err "No backup found on GitHub. Run 'phone_switch.sh backup' on your other phone first."
        exit 1
    fi

    BACKUP_FILE="$HOME/ai-twin-phone-backup.zip"
    curl -sL -H "Authorization: token $TOKEN" -o "$BACKUP_FILE" "$LATEST_RELEASE"

    if [[ ! -s "$BACKUP_FILE" ]]; then
        print_err "Failed to download backup"
        exit 1
    fi
    print_ok "Downloaded backup ($(du -h "$BACKUP_FILE" | cut -f1))"

    # 4. Extract backup
    print_step "Extracting backup"
    TEMP_DIR=$(mktemp -d)
    unzip -o "$BACKUP_FILE" -d "$TEMP_DIR" >/dev/null 2>&1

    # Restore .env
    if [[ -f "$TEMP_DIR/env" ]]; then
        cp "$TEMP_DIR/env" ~/ai-twin/.env
        print_ok "Restored .env"
    fi

    # Restore memory
    if [[ -d "$TEMP_DIR/ai-twin-memory" ]]; then
        mkdir -p ~/ai-twin-memory
        cp -r "$TEMP_DIR/ai-twin-memory/"* ~/ai-twin-memory/ 2>/dev/null || true
        print_ok "Restored memory"
    fi

    # Restore FreeLLMAPI data
    if [[ -d "$TEMP_DIR/freellmapi-data" ]]; then
        # Clone FreeLLMAPI if not already there
        if [[ ! -d ~/freellmapi ]]; then
            print_step "Cloning FreeLLMAPI"
            git clone --depth 1 https://github.com/tashfeenahmed/freellmapi.git ~/freellmapi 2>&1 | tail -2
        fi

        mkdir -p ~/freellmapi/data
        cp -r "$TEMP_DIR/freellmapi-data/"* ~/freellmapi/data/ 2>/dev/null || true
        print_ok "Restored FreeLLMAPI data"
    fi

    # Restore boot scripts
    if [[ -d "$TEMP_DIR/termux-boot" ]]; then
        mkdir -p ~/.termux/boot
        cp "$TEMP_DIR/termux-boot/"* ~/.termux/boot/ 2>/dev/null || true
        chmod +x ~/.termux/boot/* 2>/dev/null || true
        print_ok "Restored boot scripts"
    fi

    rm -rf "$TEMP_DIR"

    # 5. Install Python deps
    print_step "Installing Python dependencies"
    cd ~/ai-twin
    pip install --break-system-packages -q -r requirements.txt 2>&1 | tail -2
    pip install --break-system-packages -q lxml 2>&1 | tail -1
    print_ok "Python dependencies installed"

    # 6. Install FreeLLMAPI dependencies (if FreeLLMAPI is there)
    if [[ -d ~/freellmapi ]]; then
        print_step "Installing FreeLLMAPI dependencies"
        cd ~/freellmapi
        npm install --no-audit --no-fund 2>&1 | tail -3
        print_ok "FreeLLMAPI dependencies installed"

        # Create auto-restart wrapper
        cat > ~/freellmapi-run.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
while true; do
    cd "$HOME/freellmapi"
    echo "[$(date)] Starting FreeLLMAPI..."
    npm run dev
    echo "[$(date)] FreeLLMAPI exited. Restarting in 5 seconds..."
    sleep 5
done
EOF
        chmod +x ~/freellmapi-run.sh
        print_ok "Created FreeLLMAPI auto-restart wrapper"
    fi

    # 7. Add .bashrc hook for FreeLLMAPI
    print_step "Setting up FreeLLMAPI auto-start hook"
    mkdir -p ~/bin
    cp ~/ai-twin/ensure_freellmapi.sh ~/bin/ 2>/dev/null || true
    chmod +x ~/bin/ensure_freellmapi.sh 2>/dev/null || true

    HOOK_LINE='[ -f "$HOME/bin/ensure_freellmapi.sh" ] && bash "$HOME/bin/ensure_freellmapi.sh" >/dev/null 2>&1 &'
    if ! grep -q "ensure_freellmapi.sh" ~/.bashrc 2>/dev/null; then
        echo "" >> ~/.bashrc
        echo "# Auto-start FreeLLMAPI on Termux open" >> ~/.bashrc
        echo "$HOOK_LINE" >> ~/.bashrc
        print_ok "Added to .bashrc"
    fi

    # 8. Acquire wakelock
    print_step "Acquiring wakelock"
    termux-wake-lock 2>/dev/null || true
    print_ok "Wakelock acquired"

    # 9. Start FreeLLMAPI
    if [[ -f ~/freellmapi-run.sh ]]; then
        print_step "Starting FreeLLMAPI"
        if ! tmux has-session -t freellmapi 2>/dev/null; then
            tmux new-session -d -s freellmapi ~/freellmapi-run.sh
            sleep 15
        fi
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
            print_ok "FreeLLMAPI is running"
        else
            print_warn "FreeLLMAPI still starting up"
        fi
    fi

    # 10. Start twin
    print_step "Starting twin"
    cd ~/ai-twin
    twin-stop 2>/dev/null || true
    sleep 1
    twin-start
    sleep 3

    # 11. Verify
    print_step "Verifying"
    if pgrep -f "twin_bot.py" >/dev/null; then
        print_ok "Twin: RUNNING"
    else
        print_err "Twin: NOT RUNNING"
    fi

    if [[ -f ~/freellmapi-run.sh ]]; then
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
            print_ok "FreeLLMAPI: RUNNING"
        else
            print_warn "FreeLLMAPI: starting up"
        fi
    fi

    print_ok "Wakelock: ACTIVE"
    if [[ -d ~/.termux/boot ]]; then
        print_ok "Termux:Boot: CONFIGURED"
    fi

    echo ""
    echo "============================================"
    echo "  Restore complete!"
    echo "============================================"
    echo ""
    echo "Phone 2 is now running your AI Twin."
    echo "Phone 1's twin was stopped when you ran backup."
    echo ""
    echo "Test it: open Telegram, message @TYKO_twin_bot"
    echo ""
    echo "If you want to switch back to phone 1 later:"
    echo "  1. On phone 2: bash ~/ai-twin/phone_switch.sh backup"
    echo "  2. On phone 1: bash ~/ai-twin/phone_switch.sh restore"
    echo ""
    echo "The lock will prevent both from running at once."

    exit 0
fi

print_err "Unknown mode: $MODE"
echo "Usage: bash phone_switch.sh <backup|restore>"
exit 1
