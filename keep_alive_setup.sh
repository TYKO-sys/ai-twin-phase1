#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — keep-alive setup
# ============================================================
# This script configures Android + Termux so the bot survives:
#   1. Battery optimization being aggressive
#   2. Android's phantom process killer (Android 12+)
#   3. The phone rebooting (auto-start on boot)
#   4. You accidentally closing Termux
#
# Run this ONCE. It's idempotent — safe to run multiple times.
#
#   bash ~/ai-twin/keep_alive_setup.sh
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
print_err()  { echo -e "${RED}[X]${NC} $1"; }
print_step() { echo -e "${CYAN}=== $1 ===${NC}"; }

echo -e "${CYAN}"
echo "============================================================"
echo "  AI Twin — Keep-Alive Setup"
echo "  This configures Android + Termux so your bot never dies."
echo "============================================================"
echo -e "${NC}"

# ------------------------------------------------------------
# 1. Acquire wakelock (prevents CPU from sleeping)
# ------------------------------------------------------------
print_step "Step 1: Acquire wakelock"
if command -v termux-wake-lock &>/dev/null; then
    termux-wake-lock
    print_ok "Wakelock acquired — CPU won't sleep while Termux is running"
else
    print_warn "termux-wake-lock not found. Install termux-api: pkg install termux-api"
fi

# ------------------------------------------------------------
# 2. Install tmux (lets the bot run in a detached session)
# ------------------------------------------------------------
print_step "Step 2: Install tmux (detached sessions)"
if ! command -v tmux &>/dev/null; then
    pkg install -y tmux
fi
print_ok "tmux installed — bot can run in background even if Termux is closed"

# Create ~/bin directory if it doesn't exist (for the launcher scripts)
if [[ ! -d "$HOME/bin" ]]; then
    mkdir -p "$HOME/bin"
    print_ok "Created ~/bin directory"
fi

# Make sure ~/bin is in PATH (so twin-start etc. work from anywhere)
# Termux sources .profile on startup (not .bashrc), so we need to add
# the PATH export to BOTH files to be safe.
PATH_LINE='export PATH="$HOME/bin:$PATH"'

# Add to .profile (Termux's primary startup file)
PROFILE_FILE="$HOME/.profile"
if [[ ! -f "$PROFILE_FILE" ]] || ! grep -q 'HOME/bin' "$PROFILE_FILE" 2>/dev/null; then
    echo "" >> "$PROFILE_FILE"
    echo "# Add ~/bin to PATH for AI twin commands" >> "$PROFILE_FILE"
    echo "$PATH_LINE" >> "$PROFILE_FILE"
    print_ok "Added ~/bin to PATH in ~/.profile"
fi

# Also add to .bashrc (in case user uses bash interactively)
BASHRC_FILE="$HOME/.bashrc"
if [[ ! -f "$BASHRC_FILE" ]] || ! grep -q 'HOME/bin' "$BASHRC_FILE" 2>/dev/null; then
    echo "" >> "$BASHRC_FILE"
    echo "# Add ~/bin to PATH for AI twin commands" >> "$BASHRC_FILE"
    echo "$PATH_LINE" >> "$BASHRC_FILE"
    print_ok "Added ~/bin to PATH in ~/.bashrc"
fi

# Export for the current script session
export PATH="$HOME/bin:$PATH"

# ------------------------------------------------------------
# 3. Install termux-services (for auto-restart on crash)
# ------------------------------------------------------------
print_step "Step 3: Install termux-services"
if ! command -v sv &>/dev/null; then
    pkg install -y termux-services
    # Source the services script so we can use sv command
    source "$PREFIX/etc/profile.d/start-services.sh" 2>/dev/null || true
fi
print_ok "termux-services installed"

# ------------------------------------------------------------
# 4. Create a tmux launcher script
# ------------------------------------------------------------
print_step "Step 4: Create bot launcher (runs in tmux)"
cat > "$HOME/bin/twin-start" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Start the AI twin in a tmux session so it survives Termux being closed.

# Acquire wakelock if not already held
command -v termux-wake-lock &>/dev/null && termux-wake-lock 2>/dev/null

# Check if the session is already running
if tmux has-session -t twin 2>/dev/null; then
    echo "AI Twin is already running in tmux session 'twin'."
    echo "To attach to it:   tmux attach -t twin"
    echo "To stop it:        twin-stop"
    exit 0
fi

# Start the bot in a new detached tmux session
# The 'while true' loop auto-restarts the bot if it crashes
# (prevents tmux session from dying when Python exits)
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py; echo 'Bot crashed, restarting in 5 seconds...'; sleep 5; done"

echo "AI Twin started in background tmux session."
echo ""
echo "  View live logs:   twin-logs"
echo "  Attach to session: tmux attach -t twin"
echo "  Stop the bot:     twin-stop"
echo ""
echo "The bot will keep running even if you close Termux."
echo "If the bot crashes, it auto-restarts after 5 seconds."
EOF
chmod +x "$HOME/bin/twin-start"

# ------------------------------------------------------------
# 5. Create a logs viewer
# ------------------------------------------------------------
cat > "$HOME/bin/twin-logs" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Attach to the twin tmux session to see live logs.
# Press Ctrl+B then D to detach without stopping the bot.

if ! tmux has-session -t twin 2>/dev/null; then
    echo "AI Twin is not running. Start it with: twin-start"
    exit 1
fi

tmux attach -t twin
EOF
chmod +x "$HOME/bin/twin-logs"

# ------------------------------------------------------------
# 6. Create a stop script
# ------------------------------------------------------------
cat > "$HOME/bin/twin-stop" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Stop the AI twin.

if ! tmux has-session -t twin 2>/dev/null; then
    echo "AI Twin is not running."
    exit 0
fi

tmux kill-session -t twin
echo "AI Twin stopped."
EOF
chmod +x "$HOME/bin/twin-stop"

# ------------------------------------------------------------
# 7. Create a status checker
# ------------------------------------------------------------
cat > "$HOME/bin/twin-status" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Check if the AI twin is running.

if tmux has-session -t twin 2>/dev/null; then
    echo "Status: RUNNING (tmux session 'twin' is active)"
    echo ""
    echo "To view logs:   twin-logs"
    echo "To stop:        twin-stop"
else
    echo "Status: STOPPED"
    echo "To start:       twin-start"
fi
EOF
chmod +x "$HOME/bin/twin-status"

print_ok "Commands installed: twin-start, twin-logs, twin-stop, twin-status"

# ------------------------------------------------------------
# 8. Auto-start the bot when Termux opens
# ------------------------------------------------------------
print_step "Step 5: Auto-start bot when Termux opens"

BASHRC="$HOME/.bashrc"
# Remove any old twin autostart lines
if [[ -f "$BASHRC" ]]; then
    sed -i '/twin-start/d' "$BASHRC" 2>/dev/null || true
fi

# Add the autostart line (only if not already there)
if ! grep -q "twin-start" "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "# Auto-start AI twin on Termux open" >> "$BASHRC"
    echo "twin-start" >> "$BASHRC"
    print_ok "Added to ~/.bashrc — bot will auto-start when Termux opens"
else
    print_ok "Auto-start already in ~/.bashrc"
fi

# ------------------------------------------------------------
# 9. Instructions for battery optimization (manual step)
# ------------------------------------------------------------
print_step "Step 6: Battery optimization (MANUAL — you must do this)"

echo ""
echo -e "${YELLOW}IMPORTANT: You need to do these steps manually on your phone.${NC}"
echo ""
echo "1. Open Android Settings"
echo "2. Go to Apps → Termux"
echo "3. Tap Battery"
echo "4. Set to 'Unrestricted' or 'Don't optimize'"
echo ""
echo "5. Go back to Apps → Termux"
echo "6. Tap 'Force stop' — make sure it's NOT forced stopped"
echo ""
echo "7. (Android 12+) Disable Phantom Process Killer:"
echo "   This requires ADB from a computer. If you have one:"
echo "   adb shell device_config put activity_manager max_phantom_processes 2147483647"
echo "   Otherwise, this step can be skipped — tmux helps a lot already."
echo ""
echo "8. (Android 14+) Disable 'App sleeping':"
echo "   Settings → Apps → Termux → Battery → 'Don't sleep'"
echo ""

# ------------------------------------------------------------
# 10. Install Termux:Boot for auto-start on phone reboot
# ------------------------------------------------------------
print_step "Step 7: Auto-start on phone reboot (Termux:Boot)"

BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"

cat > "$BOOT_DIR/start-twin.sh" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start the AI twin when the phone boots.
# This runs automatically if Termux:Boot is installed.

# Wait for network to come up (critical — bot needs internet)
sleep 30

# Set PATH (Termux:Boot doesn't source .profile)
export PATH="$HOME/bin:$PATH"

# Acquire wakelock (prevents Android from killing the bot)
termux-wake-lock 2>/dev/null

# Start the bot using the full path (in case PATH isn't set)
if [ -x "$HOME/bin/twin-start" ]; then
    $HOME/bin/twin-start
else
    # Fallback: start directly
    cd ~/ai-twin
    tmux new-session -d -s twin "while true; do python twin_bot.py; echo 'Bot crashed, restarting in 5 seconds...'; sleep 5; done"
fi
EOF
chmod +x "$BOOT_DIR/start-twin.sh"

print_ok "Boot script created at ~/.termux/boot/start-twin.sh"
echo ""
echo -e "${YELLOW}To enable auto-start on phone reboot:${NC}"
echo ""
echo "1. Install Termux:Boot from F-Droid:"
echo "   https://f-droid.org/packages/com.termux.boot/"
echo ""
echo "2. Open Termux:Boot ONCE (just open and close it — that registers it with Android)"
echo ""
echo "3. IMPORTANT: Also whitelist Termux:Boot in battery settings:"
echo "   Android Settings → Apps → Termux:Boot → Battery → Unrestricted"
echo ""
echo "4. Test it: restart your phone. Wait 60 seconds. The bot should start automatically."
echo ""
echo "If it doesn't start, the most common cause is Android killing Termux:Boot."
echo "Make sure BOTH Termux AND Termux:Boot have battery set to 'Unrestricted'."
echo ""

# ------------------------------------------------------------
# 11. Summary
# ------------------------------------------------------------
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Keep-alive setup complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "Your bot is now defended against:"
echo "  ✓ CPU sleep (wakelock)"
echo "  ✓ Termux being closed (tmux keeps it running)"
echo "  ✓ Termux crash (auto-restart via .bashrc)"
echo "  ✓ Phone reboot (Termux:Boot — install separately)"
echo ""
echo "Commands:"
echo "  twin-start    — start the bot (auto-runs on Termux open)"
echo "  twin-logs     — view live logs (Ctrl+B then D to detach)"
echo "  twin-stop     — stop the bot"
echo "  twin-status   — check if running"
echo ""
echo "STILL TODO (manual, on your phone):"
echo "  1. Android Settings → Apps → Termux → Battery → Unrestricted"
echo "  2. Install Termux:Boot from F-Droid (for auto-start on reboot)"
echo ""
echo "After doing those, start the bot with:"
echo -e "  ${CYAN}twin-start${NC}"
