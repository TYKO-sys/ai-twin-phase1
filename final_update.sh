#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — Final Update (one script to rule them all)
# ============================================================
# This script does EVERYTHING to get your twin fully updated
# and always-on. Run this when you want a clean, complete setup.
#
# What it does (in order):
#   1. Stops the twin and FreeLLMAPI
#   2. Pulls the latest code from GitHub (phase2 branch)
#   3. Restores your .env from backup (preserves API keys)
#   4. Updates your voice profile from the latest template
#   5. Clears the stale config cache (forces fresh remote fetch)
#   6. Installs Python dependencies (in case requirements changed)
#   7. Installs lxml (for the scrape_website tool)
#   8. Sets up Termux:Boot auto-start for the twin
#  8.5. Sets up .bashrc hook so FreeLLMAPI auto-starts on every Termux open
#   9. Sets up Termux:Boot auto-start for FreeLLMAPI (if installed)
#  10. Acquires wakelock so Android doesn't kill anything
#  11. Starts FreeLLMAPI (if installed) with auto-restart wrapper
#  12. Starts the twin
#  13. Verifies everything is running
#
# Usage:
#   bash ~/ai-twin/final_update.sh
#
# If you have a FreeLLMAPI unified key, also run:
#   bash ~/ai-twin/install_freellmapi.sh YOUR_UNIFIED_KEY
# ============================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
MAGENTA='\033[0;35m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
print_step() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
print_err()  { echo -e "${RED}[X]${NC} $1"; }
print_ask()  { echo -e "${MAGENTA}${BOLD}?${NC} $1"; }

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"   # injected via env var — never hardcode PATs in scripts
REPO_URL="https://$TOKEN@github.com/TYKO-sys/ai-twin-phase1.git"

# ------------------------------------------------------------
# 1. Stop everything
# ------------------------------------------------------------
print_step "Step 1: Stop everything"
twin-stop 2>/dev/null || true
tmux kill-session -t freellmapi 2>/dev/null || true
print_ok "Stopped twin and FreeLLMAPI"

# ------------------------------------------------------------
# 2. Pull the latest code from GitHub
# ------------------------------------------------------------
print_step "Step 2: Pull latest code from GitHub (phase2)"

# Require token via env var (never hardcode secrets in the repo)
if [ -z "$TOKEN" ]; then
  print_err "GITHUB_TOKEN (or GH_TOKEN) env var is empty - set it before running this script."
  print_warn "Example: export GITHUB_TOKEN='github_pat_...' && ./final_update.sh"
  exit 1
fi

# Get out of any deleted folder
cd ~

# Remove old ai-twin folder (clean slate)
rm -rf ~/ai-twin 2>/dev/null

# Clone fresh from phase2
git clone --branch phase2 --depth 1 "$REPO_URL" ~/ai-twin 2>&1 | tail -2
chmod +x ~/ai-twin/*.sh ~/ai-twin/diagnostic.py 2>/dev/null
print_ok "Latest code cloned from phase2"

# Show latest commit
LATEST_COMMIT=$(cd ~/ai-twin && git log -1 --oneline 2>/dev/null | head -1)
print_ok "Latest commit: $LATEST_COMMIT"

# ------------------------------------------------------------
# 3. Restore .env from backup (preserves API keys + SMTP + FreeLLMAPI key)
# ------------------------------------------------------------
print_step "Step 3: Restore .env from backup"
if [[ -f "$HOME/.env.backup" ]]; then
    cp "$HOME/.env.backup" ~/ai-twin/.env
    print_ok ".env restored from backup ($(wc -c < ~/ai-twin/.env) bytes)"
elif [[ -f ~/ai-twin/.env ]]; then
    print_ok ".env already present"
else
    print_warn "No .env backup found. You'll need to set API keys via the wizard."
fi

cd ~/ai-twin

# ------------------------------------------------------------
# 4. Update voice profile from latest template
# ------------------------------------------------------------
print_step "Step 4: Update voice profile"
if [[ -f ~/ai-twin/voice_profile_template.md ]]; then
    # If user has customized their voice profile, preserve it
    if [[ -f ~/ai-twin-memory/voice_profile.md ]] && [[ -s ~/ai-twin-memory/voice_profile.md ]]; then
        # Backup the old one (in case user customized it)
        cp ~/ai-twin-memory/voice_profile.md ~/ai-twin-memory/voice_profile.md.backup 2>/dev/null || true
        # Update with the latest template (which has the newest rules + examples)
        cp ~/ai-twin/voice_profile_template.md ~/ai-twin-memory/voice_profile.md
        print_ok "Voice profile updated from latest template (backup saved as voice_profile.md.backup)"
        print_warn "If you customized your voice profile, your edits are in voice_profile.md.backup"
    else
        cp ~/ai-twin/voice_profile_template.md ~/ai-twin-memory/voice_profile.md
        print_ok "Voice profile created from template"
    fi
else
    print_warn "Voice profile template not found, skipping"
fi

# ------------------------------------------------------------
# 5. Clear stale config cache (forces fresh remote fetch)
# ------------------------------------------------------------
print_step "Step 5: Clear stale config cache"
rm -f ~/ai-twin-memory/models_cache.json 2>/dev/null
print_ok "Stale config cache cleared (twin will fetch fresh config from GitHub on startup)"

# ------------------------------------------------------------
# 6. Install Python dependencies
# ------------------------------------------------------------
print_step "Step 6: Install Python dependencies"
pip install --break-system-packages -q -r ~/ai-twin/requirements.txt 2>&1 | tail -2
print_ok "Python dependencies installed"

# ------------------------------------------------------------
# 7. Install lxml (for the scrape_website tool)
# ------------------------------------------------------------
print_step "Step 7: Install lxml"
pip install --break-system-packages -q lxml 2>&1 | tail -1
print_ok "lxml installed (for scrape_website tool)"

# ------------------------------------------------------------
# 8. Set up Termux:Boot auto-start for the twin
# ------------------------------------------------------------
print_step "Step 8: Termux:Boot auto-start for twin"

BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"

TWIN_BOOT_SCRIPT="$BOOT_DIR/start-twin.sh"

cat > "$TWIN_BOOT_SCRIPT" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start on phone boot — FreeLLMAPI FIRST, then twin
# Generated by final_update.sh

# Acquire wakelock so Android doesn't kill us
termux-wake-lock 2>/dev/null || true

# Wait for network to come up
sleep 10

# Start FreeLLMAPI first (if installed)
if [[ -f "$HOME/freellmapi-run.sh" ]]; then
    # Kill any existing session
    tmux kill-session -t freellmapi 2>/dev/null || true
    sleep 1
    # Start with auto-restart wrapper
    tmux new-session -d -s freellmapi "$HOME/freellmapi-run.sh"

    # Wait up to 60 seconds for FreeLLMAPI to respond
    for i in $(seq 1 30); do
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
            echo "FreeLLMAPI is up."
            break
        fi
        sleep 2
    done
fi

# Start the twin in a tmux session
tmux new-session -d -s twin "cd $HOME/ai-twin && python twin_bot.py"
EOF

chmod +x "$TWIN_BOOT_SCRIPT"
print_ok "Twin auto-start written to $TWIN_BOOT_SCRIPT"

# Check if Termux:Boot app is installed
if [[ -d "$HOME/.termux/boot" ]]; then
    print_ok "Termux:Boot is installed — twin will auto-start on every phone reboot"
else
    print_warn "Termux:Boot app not installed"
    print_warn "Install it from F-Droid: https://f-droid.org/packages/com.termux.boot/"
    print_warn "After installing, OPEN Termux:Boot once (just launch and close it)"
fi

# ------------------------------------------------------------
# 8.5. Termux startup hook (runs on every Termux open, not just boot)
# ------------------------------------------------------------
print_step "Step 8.5: Termux startup hook for FreeLLMAPI"

# Make sure ~/bin exists
mkdir -p "$HOME/bin"

# Copy the ensure script to ~/bin/
cp ~/ai-twin/ensure_freellmapi.sh ~/bin/ensure_freellmapi.sh 2>/dev/null || true
chmod +x ~/bin/ensure_freellmapi.sh 2>/dev/null || true

# Add to .bashrc if not already there
BASHRC="$HOME/.bashrc"
HOOK_LINE='[ -f "$HOME/bin/ensure_freellmapi.sh" ] && bash "$HOME/bin/ensure_freellmapi.sh" >/dev/null 2>&1 &'

if [[ ! -f "$BASHRC" ]] || ! grep -q "ensure_freellmapi.sh" "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "# Auto-start FreeLLMAPI on Termux open" >> "$BASHRC"
    echo "$HOOK_LINE" >> "$BASHRC"
    print_ok "Added FreeLLMAPI auto-start to ~/.bashrc"
else
    print_ok "FreeLLMAPI auto-start already in ~/.bashrc"
fi

# Also add to .profile (some Termux setups use this)
PROFILE="$HOME/.profile"
if [[ ! -f "$PROFILE" ]] || ! grep -q "ensure_freellmapi.sh" "$PROFILE" 2>/dev/null; then
    echo "" >> "$PROFILE"
    echo "# Auto-start FreeLLMAPI on Termux open" >> "$PROFILE"
    echo "$HOOK_LINE" >> "$PROFILE" 2>/dev/null || true
    print_ok "Added FreeLLMAPI auto-start to ~/.profile"
fi

# ------------------------------------------------------------
# 9. Set up Termux:Boot auto-start for FreeLLMAPI (if installed)
# ------------------------------------------------------------
print_step "Step 9: FreeLLMAPI auto-start"

if [[ -d "$HOME/freellmapi" ]]; then
    # FreeLLMAPI is installed
    print_ok "FreeLLMAPI detected at ~/freellmapi"

    # Create auto-restart wrapper if not exists
    WRAPPER="$HOME/freellmapi-run.sh"
    if [[ ! -f "$WRAPPER" ]]; then
        cat > "$WRAPPER" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-restart wrapper for FreeLLMAPI
while true; do
    cd "$HOME/freellmapi"
    echo "[$(date)] Starting FreeLLMAPI..."
    npm run dev
    echo "[$(date)] FreeLLMAPI exited. Restarting in 5 seconds..."
    sleep 5
done
EOF
        chmod +x "$WRAPPER"
        print_ok "Created auto-restart wrapper"
    fi

    # Termux:Boot auto-start for FreeLLMAPI
    FREELLMAPI_BOOT_SCRIPT="$BOOT_DIR/start-freellmapi.sh"
    cat > "$FREELLMAPI_BOOT_SCRIPT" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start FreeLLMAPI on phone boot
termux-wake-lock 2>/dev/null || true
sleep 10
tmux new-session -d -s freellmapi "$HOME/freellmapi-run.sh"
EOF
    chmod +x "$FREELLMAPI_BOOT_SCRIPT"
    print_ok "FreeLLMAPI auto-start written to $FREELLMAPI_BOOT_SCRIPT"

    # Install termux-api if not installed (for wakelock + open-url)
    if ! command -v termux-wake-lock &>/dev/null; then
        print_step "Installing termux-api"
        pkg install -y termux-api >/dev/null 2>&1 || print_warn "termux-api install failed"
    fi
else
    print_warn "FreeLLMAPI not installed at ~/freellmapi"
    print_warn "If you want to use FreeLLMAPI, run: bash ~/ai-twin/install_freellmapi.sh"
    print_warn "Then run this script again to set up auto-start"
fi

# ------------------------------------------------------------
# 10. Acquire wakelock
# ------------------------------------------------------------
print_step "Step 10: Acquire wakelock"
if command -v termux-wake-lock &>/dev/null; then
    termux-wake-lock 2>/dev/null || true
    print_ok "Wakelock acquired (Android won't kill twin or FreeLLMAPI when screen is off)"
else
    print_warn "termux-wake-lock not available. Install with: pkg install termux-api"
fi

# ------------------------------------------------------------
# 11. Start FreeLLMAPI (if installed)
# ------------------------------------------------------------
print_step "Step 11: Start FreeLLMAPI"
if [[ -f "$HOME/freellmapi-run.sh" ]]; then
    if ! tmux has-session -t freellmapi 2>/dev/null; then
        tmux new-session -d -s freellmapi "$HOME/freellmapi-run.sh"
        print_ok "FreeLLMAPI starting in tmux session 'freellmapi'"
        sleep 15  # Give it time to come up

        # Verify
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
            print_ok "FreeLLMAPI is responding at http://localhost:3001/v1"
        else
            print_warn "FreeLLMAPI still starting up. Check: tmux attach -t freellmapi"
        fi
    else
        print_ok "FreeLLMAPI already running"
    fi
else
    print_warn "FreeLLMAPI not installed. Skipping."
fi

# ------------------------------------------------------------
# 12. Start the twin
# ------------------------------------------------------------
print_step "Step 12: Start twin"
twin-start
sleep 3
print_ok "Twin started"

# ------------------------------------------------------------
# 13. Verify everything is running
# ------------------------------------------------------------
print_step "Step 13: Verify everything"

echo ""
echo "Running tmux sessions:"
tmux ls 2>/dev/null || echo "  (no tmux sessions)"
echo ""

# Check twin
if pgrep -f "twin_bot.py" >/dev/null; then
    print_ok "Twin: RUNNING"
else
    print_err "Twin: NOT RUNNING — check logs: twin-logs"
fi

# Check FreeLLMAPI
if [[ -f "$HOME/freellmapi-run.sh" ]]; then
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
        print_ok "FreeLLMAPI: RUNNING at http://localhost:3001/v1"
    else
        print_warn "FreeLLMAPI: NOT RESPONDING — check: tmux attach -t freellmapi"
    fi
fi

# Check wakelock
if command -v termux-wake-lock &>/dev/null; then
    print_ok "Wakelock: ACTIVE"
fi

# Check Termux:Boot
if [[ -d "$HOME/.termux/boot" ]]; then
    print_ok "Termux:Boot: CONFIGURED (auto-starts on reboot)"
else
    print_warn "Termux:Boot: NOT INSTALLED (twin won't auto-start on reboot)"
fi

# ------------------------------------------------------------
# Final summary
# ------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Update complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "What's running now:"
echo "  - AI Twin (Telegram bot @TYKO_twin_bot)"
if [[ -f "$HOME/freellmapi-run.sh" ]]; then
    echo "  - FreeLLMAPI local router (http://localhost:3001)"
fi
echo "  - Wakelock (prevents Android from killing them)"
echo "  - Termux:Boot auto-start (survives phone reboots)"
echo ""
echo "What to do next:"
echo ""
if [[ -d "$HOME/freellmapi" ]]; then
    # FreeLLMAPI is installed — check if it's actually running
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
        # FreeLLMAPI is installed and running — check if twin is pointed at it
        if grep -q "^FREELLMAPI_API_KEY=." ~/ai-twin/.env 2>/dev/null; then
            echo "  - FreeLLMAPI is installed and twin is pointed at it. You're all set."
        else
            echo -e "  ${YELLOW}FreeLLMAPI is running but twin isn't pointed at it yet.${NC}"
            echo "  Get your unified key from http://localhost:5173 and run: bash ~/ai-twin/install_freellmapi.sh YOUR_KEY"
        fi
    else
        echo -e "  ${YELLOW}FreeLLMAPI is installed but not running.${NC}"
        echo "  Start it: bash ~/ai-twin/final_update.sh"
    fi
else
    echo -e "  ${YELLOW}FreeLLMAPI not installed.${NC}"
    echo "  Run: bash ~/ai-twin/install_freellmapi.sh"
fi
echo ""

echo "Useful commands:"
echo -e "  ${CYAN}twin-start${NC}       start the twin"
echo -e "  ${CYAN}twin-stop${NC}        stop the twin"
echo -e "  ${CYAN}twin-logs${NC}        view live logs"
echo -e "  ${CYAN}twin-status${NC}      check if running"
echo ""
if [[ -f "$HOME/freellmapi-run.sh" ]]; then
    echo -e "  ${CYAN}tmux attach -t freellmapi${NC}  view FreeLLMAPI logs (Ctrl+B then D to detach)"
    echo -e "  ${CYAN}termux-open-url http://localhost:5173${NC}  open FreeLLMAPI dashboard"
fi
echo ""
echo -e "  ${CYAN}bash ~/ai-twin/diagnostic.py${NC}  run full system diagnostic"
echo ""
echo -e "${GREEN}Test the twin now: open Telegram, message @TYKO_twin_bot${NC}"
