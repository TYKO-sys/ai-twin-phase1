#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — automated setup for Termux on Android
# ============================================================
# This script:
#   1. Updates Termux packages
#   2. Installs Python, dependencies, and tools
#   3. Acquires a wakelock so Android doesn't kill the bot
#   4. Asks for the folder where you unzipped ai-twin/
#   5. Sets up the secrets file (.env) if not already done
#   6. Verifies everything is in place
#   7. Optionally starts the bot immediately
#
# Run it AFTER you've:
#   - Installed Termux (from F-Droid)
#   - Copied the ai-twin/ folder into Termux's home
#   - Gotten your Telegram bot token and Gemini API key
#
# To run:
#   cd ~/ai-twin
#   bash setup.sh
# ============================================================

set -e  # exit on any error

# Colors for clarity
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # no color

print_step() {
    echo -e "${CYAN}=== $1 ===${NC}"
}
print_ok() {
    echo -e "${GREEN}[OK] $1${NC}"
}
print_warn() {
    echo -e "${YELLOW}[!] $1${NC}"
}
print_err() {
    echo -e "${RED}[X] $1${NC}"
}

# ------------------------------------------------------------
# 0. Welcome
# ------------------------------------------------------------
clear
echo -e "${CYAN}"
echo "============================================================"
echo "  AI TWIN — automated setup"
echo "  This installs everything and gets your bot ready to run."
echo "============================================================"
echo -e "${NC}"
echo ""
echo "Press ENTER to continue, or Ctrl+C to cancel."
read -r

# ------------------------------------------------------------
# 1. Where are we?
# ------------------------------------------------------------
print_step "Locating ai-twin folder"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/twin_bot.py" ]]; then
    print_err "twin_bot.py not found in $SCRIPT_DIR"
    print_warn "Make sure you're running this from inside the ai-twin/ folder."
    print_warn "Expected files: twin_bot.py, context_manager.py, summarizer.py,"
    print_warn "                 system_prompt.txt, requirements.txt, .env.example"
    exit 1
fi
print_ok "Found ai-twin at: $SCRIPT_DIR"
cd "$SCRIPT_DIR"

# ------------------------------------------------------------
# 2. Termux storage permission (so we can read/write shared storage
#    if needed later — for backups etc.)
# ------------------------------------------------------------
print_step "Requesting storage permission"
if ! command -v termux-setup-storage &>/dev/null; then
    print_warn "termux-setup-storage not available. Skipping."
    print_warn "If you want backups later, run: pkg install termux-api"
else
    termux-setup-storage
    print_ok "Storage permission requested (check your phone for a dialog)"
fi

# ------------------------------------------------------------
# 3. Update packages + install Python and tools
# ------------------------------------------------------------
print_step "Updating Termux packages (this takes a minute)"
pkg update -y && pkg upgrade -y

print_step "Installing Python and tools"
pkg install -y python python-pip termux-api git nano

print_ok "Python installed: $(python --version 2>&1)"

# ------------------------------------------------------------
# 4. Install Python dependencies
# ------------------------------------------------------------
print_step "Installing Python libraries"

# Termux externally manages pip — `pip install --upgrade pip` is blocked.
# We use --break-system-packages instead, which is the official Termux workaround.
export PIP_BREAK_SYSTEM_PACKAGES=1

# Do NOT upgrade pip itself — Termux forbids that and will error out.
pip install --break-system-packages -r requirements.txt
print_ok "Python libraries installed"

# ------------------------------------------------------------
# 5. Acquire wakelock so Android doesn't kill the bot
# ------------------------------------------------------------
print_step "Acquiring wakelock (prevents Android from killing the bot)"
if command -v termux-wake-lock &>/dev/null; then
    termux-wake-lock
    print_ok "Wakelock acquired. Bot can run in background."
    print_warn "IMPORTANT: Also go to Android Settings → Apps → Termux"
    print_warn "           → Battery → 'Don't optimize' / 'Unrestricted'"
else
    print_warn "termux-wake-lock not found. Install termux-api: pkg install termux-api"
fi

# ------------------------------------------------------------
# 6. Set up the .env secrets file
# ------------------------------------------------------------
print_step "Setting up secrets file (.env)"
if [[ -f .env ]]; then
    print_ok ".env already exists — leaving it alone"
else
    cp .env.example .env
    print_ok "Created .env from .env.example"
    print_warn ""
    print_warn "NOW YOU NEED TO EDIT .env AND ADD YOUR SECRETS."
    print_warn "Open it in nano:   nano .env"
    print_warn "Or use any text editor."
    print_warn ""
    print_warn "You need:"
    print_warn "  - TELEGRAM_BOT_TOKEN  (from @BotFather on Telegram)"
    print_warn "  - GEMINI_API_KEY      (from https://aistudio.google.com/apikey)"
    print_warn "  - ALLOWED_USER_ID     (message @userinfobot to get your ID)"
    print_warn ""
    echo "Press ENTER once you've edited .env and saved it."
    echo "(Or press Ctrl+C to stop here and run the bot later.)"
    read -r
fi

# ------------------------------------------------------------
# 7. Validate .env
# ------------------------------------------------------------
print_step "Validating secrets"
# Source the .env (it's just KEY=value lines)
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
    print_err "TELEGRAM_BOT_TOKEN is empty in .env"
    exit 1
fi
if [[ -z "$GEMINI_API_KEY" ]]; then
    print_err "GEMINI_API_KEY is empty in .env"
    exit 1
fi
if [[ -z "$ALLOWED_USER_ID" ]]; then
    print_err "ALLOWED_USER_ID is empty in .env"
    exit 1
fi
print_ok "All three secrets are set"

# ------------------------------------------------------------
# 8. Quick syntax check on Python files
# ------------------------------------------------------------
print_step "Syntax-checking Python files"
python -m py_compile twin_bot.py && print_ok "twin_bot.py OK"
python -m py_compile context_manager.py && print_ok "context_manager.py OK"
python -m py_compile summarizer.py && print_ok "summarizer.py OK"

# ------------------------------------------------------------
# 9. Set up the cron jobs for morning / evening / weekly
# ------------------------------------------------------------
print_step "Setting up scheduled pings (cron)"

# Write the cron schedule to a script we can call
mkdir -p "$HOME/bin"
cat > "$HOME/bin/twin_morning.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Triggered by cron at 9am daily. Sends /morning to the bot.
source "$(dirname "$0")/../ai-twin/.env" 2>/dev/null || source "$HOME/ai-twin/.env"
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${ALLOWED_USER_ID}" \
    -d "text=/morning" > /dev/null
EOF
chmod +x "$HOME/bin/twin_morning.sh"

cat > "$HOME/bin/twin_evening.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Triggered by cron at 9pm daily. Sends /evening to the bot.
source "$(dirname "$0")/../ai-twin/.env" 2>/dev/null || source "$HOME/ai-twin/.env"
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${ALLOWED_USER_ID}" \
    -d "text=/evening" > /dev/null
EOF
chmod +x "$HOME/bin/twin_evening.sh"

cat > "$HOME/bin/twin_weekly.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Triggered by cron at 8pm on Sundays. Sends /weekly to the bot.
source "$(dirname "$0")/../ai-twin/.env" 2>/dev/null || source "$HOME/ai-twin/.env"
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${ALLOWED_USER_ID}" \
    -d "text=/weekly" > /dev/null
EOF
chmod +x "$HOME/bin/twin_weekly.sh"

# Install cron
pkg install -y cronie termux-services
# Try to start crond
if command -v crond &>/dev/null; then
    pkill crond 2>/dev/null || true
    crond
    print_ok "Cron daemon started"
fi

# Add our schedule to crontab
CRON_TMP="$(mktemp)"
# Preserve existing entries
crontab -l 2>/dev/null > "$CRON_TMP" || true
# Remove any prior twin entries to avoid duplicates
grep -v "twin_morning\|twin_evening\|twin_weekly" "$CRON_TMP" > "${CRON_TMP}.new" || true
mv "${CRON_TMP}.new" "$CRON_TMP"
# Add fresh entries
echo "0 9 * * * $HOME/bin/twin_morning.sh" >> "$CRON_TMP"
echo "0 21 * * * $HOME/bin/twin_evening.sh" >> "$CRON_TMP"
echo "0 20 * * 0 $HOME/bin/twin_weekly.sh" >> "$CRON_TMP"
crontab "$CRON_TMP"
rm -f "$CRON_TMP"
print_ok "Scheduled: 9am morning, 9pm evening, Sunday 8pm weekly"

# ------------------------------------------------------------
# 10. Optionally start the bot now
# ------------------------------------------------------------
echo ""
print_step "Setup complete"
echo ""
echo -e "${GREEN}Everything is ready.${NC}"
echo ""
echo "Your twin's memory will live in: $HOME/ai-twin-memory"
echo "Your secrets are in:            $SCRIPT_DIR/.env"
echo "Your bot code is in:            $SCRIPT_DIR"
echo ""
echo "To START your twin now, run:"
echo -e "  ${CYAN}cd $SCRIPT_DIR && python twin_bot.py${NC}"
echo ""
echo "To make it start automatically when Termux opens, run:"
echo -e "  ${CYAN}echo 'cd $SCRIPT_DIR && python twin_bot.py' >> ~/.bashrc${NC}"
echo ""
echo "Want me to start it now? (y/N)"
read -r START_NOW
if [[ "$START_NOW" == "y" || "$START_NOW" == "Y" ]]; then
    echo -e "${CYAN}Starting AI twin...${NC}"
    echo "Send /start to your bot on Telegram once it's running."
    echo "Press Ctrl+C to stop."
    python twin_bot.py
else
    echo "OK. Start it anytime with:"
    echo -e "  ${CYAN}cd $SCRIPT_DIR && python twin_bot.py${NC}"
fi
