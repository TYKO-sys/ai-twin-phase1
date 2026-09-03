#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — One-Command Installer
# ============================================================
# This script takes a fresh Termux install to a working AI twin
# in under 5 minutes of active user attention.
#
# Usage:
#   bash install.sh
#
# The user pastes ONE command. Everything else is automated.
# The wizard.py serves a web page for entering secrets.
# ============================================================

set -e

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

# ------------------------------------------------------------
# 0. Welcome
# ------------------------------------------------------------
clear
echo -e "${CYAN}${BOLD}"
echo "============================================================"
echo "  AI Twin — One-Command Installer"
echo "  Your personal AI assistant, set up in 5 minutes."
echo "============================================================"
echo -e "${NC}"
echo ""
echo "This installer will:"
echo "  1. Install required packages"
echo "  2. Open a web wizard for your API keys"
echo "  3. Set up the bot to run 24/7"
echo "  4. Start your AI twin"
echo ""
echo "You'll need:"
echo "  - A Telegram account"
echo "  - A Google account (for free Gemini API)"
echo "  - About 5 minutes"
echo ""
read -p "Press ENTER to begin, or Ctrl+C to cancel..."

# ------------------------------------------------------------
# 1. Compatibility check
# ------------------------------------------------------------
print_step "Checking compatibility"

# Check we're in Termux
if [[ -z "$PREFIX" ]] || [[ ! -d "/data/data/com.termux" ]]; then
    print_err "This script must be run in Termux on Android."
    print_err "Install Termux from F-Droid: https://f-droid.org/packages/com.termux/"
    exit 1
fi
print_ok "Running in Termux"

# Check Android version
ANDROID_VERSION=$(getprop ro.build.version.release 2>/dev/null || echo "unknown")
if [[ "$ANDROID_VERSION" != "unknown" ]]; then
    if [[ "$ANDROID_VERSION" -lt 10 ]]; then
        print_warn "Android $ANDROID_VERSION detected. Minimum recommended: Android 10+."
        print_warn "The bot may work but is untested on this version."
    else
        print_ok "Android $ANDROID_VERSION"
    fi
fi

# Check available storage
AVAILABLE_KB=$(df -k "$HOME" 2>/dev/null | tail -1 | awk '{print $4}')
if [[ -n "$AVAILABLE_KB" ]] && [[ "$AVAILABLE_KB" -lt 500000 ]]; then
    print_err "Not enough storage space. Need at least 500MB free."
    exit 1
fi
print_ok "Storage space sufficient"

# ------------------------------------------------------------
# 2. Install packages
# ------------------------------------------------------------
print_step "Installing packages (this takes 1-2 minutes)"

pkg update -y >/dev/null 2>&1
pkg install -y python python-pip git termux-api tmux >/dev/null 2>&1

print_ok "Python: $(python --version 2>&1)"
print_ok "tmux installed"
print_ok "termux-api installed"

# ------------------------------------------------------------
# 3. Set up the ai-twin directory
# ------------------------------------------------------------
print_step "Setting up AI Twin directory"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# If we're running from the ai-twin folder, use it directly
if [[ -f "twin_bot.py" ]]; then
    AI_TWIN_DIR="$SCRIPT_DIR"
    print_ok "Using current directory: $AI_TWIN_DIR"
else
    # Otherwise, check if it's already installed
    if [[ -d "$HOME/ai-twin" ]] && [[ -f "$HOME/ai-twin/twin_bot.py" ]]; then
        AI_TWIN_DIR="$HOME/ai-twin"
        print_ok "Found existing installation: $AI_TWIN_DIR"
    else
        print_err "Could not find ai-twin files."
        print_err "Make sure install.sh is in the same folder as twin_bot.py"
        exit 1
    fi
fi

cd "$AI_TWIN_DIR"

# ------------------------------------------------------------
# 4. Install Python dependencies
# ------------------------------------------------------------
print_step "Installing Python dependencies"

export PIP_BREAK_SYSTEM_PACKAGES=1
pip install --break-system-packages -q -r requirements.txt 2>&1 | tail -5

print_ok "Python dependencies installed"

# ------------------------------------------------------------
# 5. Run the wizard
# ------------------------------------------------------------
print_step "Starting setup wizard"

# Check if .env already exists and is complete
if [[ -f ".env" ]] && grep -q "TELEGRAM_BOT_TOKEN=." .env && grep -q "ALLOWED_USER_ID=." .env; then
    print_ok "Configuration already exists"
    echo ""
    read -p "Reconfigure? (y/N) " RECONFIGURE
    if [[ "$RECONFIGURE" != "y" && "$RECONFIGURE" != "Y" ]]; then
        print_ok "Keeping existing configuration"
        # Remove completion flag if it exists
        rm -f .wizard_complete
    fi
fi

# Run the wizard if .env is missing or user wants to reconfigure
if [[ ! -f ".env" ]] || [[ "$RECONFIGURE" == "y" ]] || [[ "$RECONFIGURE" == "Y" ]]; then
    rm -f .wizard_complete

    echo ""
    echo -e "${CYAN}A web page should open in your browser.${NC}"
    echo -e "${CYAN}If it doesn't, open this URL manually: http://localhost:8888${NC}"
    echo ""

    # Run the wizard (it will exit when complete)
    python wizard.py

    # Verify .env was created
    if [[ ! -f ".env" ]]; then
        print_err "Setup was not completed. The .env file is missing."
        print_err "Run this script again to retry."
        exit 1
    fi
fi

# ------------------------------------------------------------
# 6. Keep-alive setup
# ------------------------------------------------------------
print_step "Setting up keep-alive (prevents Android from killing the bot)"

# Create ~/bin directory if needed
mkdir -p "$HOME/bin"

# Add ~/bin to PATH in .profile if not already there
if ! grep -q 'HOME/bin' "$HOME/.profile" 2>/dev/null; then
    echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.profile"
fi

# Run the keep-alive setup
if [[ -f "keep_alive_setup.sh" ]]; then
    bash keep_alive_setup.sh >/dev/null 2>&1 || true
    print_ok "Keep-alive configured"
else
    print_warn "keep_alive_setup.sh not found — skipping"
fi

# ------------------------------------------------------------
# 6.5. Optional: n8n self-hosting (FREE alternative to n8n.cloud)
# ------------------------------------------------------------
print_step "Optional: n8n self-hosting"

echo ""
echo -e "${CYAN}n8n.cloud now requires payment. You can self-host n8n on this phone${NC}"
echo -e "${CYAN}for free, OR use the twin's built-in tools for email/calendar/RSS.${NC}"
echo ""
echo "The twin has native tools for:"
echo "  - send_email (via SMTP — free with Gmail App Passwords)"
echo "  - create_calendar_event (.ics files — works with any calendar app)"
echo "  - read_rss (news, blogs, YouTube, podcasts)"
echo "  - shorten_url (free is.gd/v.gd API)"
echo ""
echo -e "${YELLOW}Self-hosting n8n gives you 400+ integrations (Slack, Sheets, Discord, etc.)${NC}"
echo -e "${YELLOW}but uses ~400MB extra storage and ~300MB RAM while running.${NC}"
echo ""
read -p "Install n8n + ngrok for self-hosted automation? (y/N) " INSTALL_N8N

if [[ "$INSTALL_N8N" == "y" || "$INSTALL_N8N" == "Y" ]]; then
    print_step "Installing Node.js + n8n + ngrok (5-10 minutes)"

    # Node.js
    pkg install -y nodejs-lts >/dev/null 2>&1 || pkg install -y nodejs >/dev/null 2>&1
    if command -v node &>/dev/null; then
        print_ok "Node.js: $(node --version)"
    else
        print_warn "Node.js install failed — n8n step skipped. See N8N_SELFHOST_GUIDE.md"
    fi

    # n8n
    if command -v node &>/dev/null; then
        npm install -g n8n >/dev/null 2>&1
        if command -v n8n &>/dev/null; then
            print_ok "n8n: $(n8n --version)"
        else
            print_warn "n8n install failed — see N8N_SELFHOST_GUIDE.md for manual steps"
        fi
    fi

    # ngrok (ARM64 binary)
    NGROK_BIN="$PREFIX/bin/ngrok"
    if [[ ! -x "$NGROK_BIN" ]]; then
        curl -sL -o /tmp/ngrok.zip https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.zip 2>/dev/null
        if [[ -f /tmp/ngrok.zip ]]; then
            unzip -o /tmp/ngrok.zip -d /tmp/ >/dev/null 2>&1
            mv /tmp/ngrok "$NGROK_BIN" 2>/dev/null && chmod +x "$NGROK_BIN"
            rm -f /tmp/ngrok.zip
            print_ok "ngrok installed"
        else
            print_warn "ngrok download failed — see N8N_SELFHOST_GUIDE.md"
        fi
    else
        print_ok "ngrok already installed"
    fi

    # n8n basic config
    mkdir -p "$HOME/.n8n"
    if [[ ! -f "$HOME/.n8n/.env" ]]; then
        cat > "$HOME/.n8n/.env" <<'N8NENV'
N8N_HOST=localhost
N8N_PORT=5678
N8N_PROTOCOL=http
N8N_DIAGNOSTICS_ENABLED=false
N8N_PERSONALIZATION_ENABLED=false
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=change-this-password
N8NENV
        print_ok "n8n config created at ~/.n8n/.env"
        print_warn "EDIT ~/.n8n/.env to change the admin password before first run"
    fi

    echo ""
    echo -e "${GREEN}${BOLD}n8n setup complete. To use it:${NC}"
    echo "  1. Sign up for ngrok: https://dashboard.ngrok.com/signup"
    echo "  2. Set your token:   ngrok config add-authtoken YOUR_TOKEN"
    echo "  3. Start n8n:         tmux new-session -d -s n8n 'n8n start'"
    echo "  4. Start ngrok:       tmux new-session -d -s ngrok 'ngrok http 5678'"
    echo "  5. Open editor at:    http://localhost:5678"
    echo ""
    echo "  Full guide: N8N_SELFHOST_GUIDE.md"
else
    print_ok "Skipping n8n — twin has native email/calendar/RSS tools"
    echo "  You can install n8n later — see N8N_SELFHOST_GUIDE.md"
fi

# ------------------------------------------------------------
# 7. Acquire wakelock
# ------------------------------------------------------------
print_step "Acquiring wakelock"
if command -v termux-wake-lock &>/dev/null; then
    termux-wake-lock 2>/dev/null || true
    print_ok "Wakelock acquired"
else
    print_warn "termux-wake-lock not available"
fi

# ------------------------------------------------------------
# 8. Self-test
# ------------------------------------------------------------
print_step "Running self-test"

# Start the bot in background
export PATH="$HOME/bin:$PATH"
twin-start 2>/dev/null || python twin_bot.py &

# Wait for bot to start
sleep 5

# Check if bot is running
if tmux has-session -t twin 2>/dev/null; then
    print_ok "Bot is running"
else
    # Check if python process is running
    if pgrep -f "twin_bot.py" >/dev/null 2>&1; then
        print_ok "Bot is running"
    else
        print_warn "Bot may not have started properly"
        print_warn "Check logs with: twin-logs"
    fi
fi

# ------------------------------------------------------------
# 9. Success
# ------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}"
echo "============================================================"
echo "  ✓ AI Twin is installed and running!"
echo "============================================================"
echo -e "${NC}"
echo ""
echo "Your twin is now live. Here's what to do next:"
echo ""
echo -e "  ${CYAN}1. Open Telegram${NC} and find your bot"
echo -e "  ${CYAN}2. Send the message:${NC} /start"
echo -e "  ${CYAN}3. Start talking to your twin${NC}"
echo ""
echo -e "${YELLOW}Two things you still need to do on your phone:${NC}"
echo ""
echo -e "  ${BOLD}1. Battery exemption:${NC}"
echo "     Android Settings → Apps → Termux → Battery → Unrestricted"
echo ""
echo -e "  ${BOLD}2. Auto-start on reboot:${NC}"
echo "     Install Termux:Boot from F-Droid:"
echo "     https://f-droid.org/packages/com.termux.boot/"
echo "     Then open Termux:Boot once (just open and close it)"
echo ""
echo "Commands you can use in Termux:"
echo -e "  ${CYAN}twin-start${NC}  — start the bot"
echo -e "  ${CYAN}twin-logs${NC}   — view live logs"
echo -e "  ${CYAN}twin-stop${NC}   — stop the bot"
echo -e "  ${CYAN}twin-status${NC} — check if running"
echo ""
echo "In Telegram, send /help to see all commands."
echo ""
echo -e "${GREEN}Done. Go say hi to your twin.${NC}"
