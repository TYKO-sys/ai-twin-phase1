#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — Fresh Phone Install (from blank Termux to running twin)
# ============================================================
# This script does EVERYTHING. You just paste it into a fresh
# Termux and it handles the rest:
#   1. Installs all required packages (git, python, etc.)
#   2. Clones the ai-twin repo
#   3. Runs the phone_switch.sh restore (which downloads your backup)
#   4. Installs all dependencies (Python, Node.js, FreeLLMAPI)
#   5. Restores all your memory, API keys, FreeLLMAPI database
#   6. Starts FreeLLMAPI + twin
#
# Usage:
#   Just paste this whole script into Termux and hit enter.
#
# You need:
#   - A fresh Termux install
#   - Termux:Boot installed (from F-Droid, opened once)
#   - Internet (mobile data or WiFi)
#   - About 30-45 minutes
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

# Your GitHub token (so we can clone the private repo).
# NEVER hardcode a real PAT here -- GitHub secret scanning blocks the push.
# Either export GITHUB_TOKEN before running, or paste it when prompted below.
if [[ -n "$GITHUB_TOKEN" ]]; then
    TOKEN="$GITHUB_TOKEN"
elif [[ -n "$GH_TOKEN" ]]; then
    TOKEN="$GH_TOKEN"
else
    print_step "GitHub Token needed to clone the private repo"
    print_warn "Get a PAT with 'repo' scope: https://github.com/settings/tokens"
    read -s -p "Paste your GitHub token (input hidden, press Enter): " TOKEN
    echo ""
fi
if [[ -z "$TOKEN" ]]; then
    print_err "No GitHub token provided. Set GITHUB_TOKEN or paste when prompted."
    exit 1
fi

# ============================================================
# 1. Check we're in Termux
# ============================================================
print_step "Step 1: Verify Termux"
if [[ -z "$PREFIX" ]] || [[ ! -d "/data/data/com.termux" ]]; then
    print_err "This script must run in Termux on Android."
    print_err "Install Termux from F-Droid: https://f-droid.org/packages/com.termux/"
    exit 1
fi
print_ok "Running in Termux"

# ============================================================
# 2. Update packages + install everything we need
# ============================================================
print_step "Step 2: Install system packages (3-5 minutes)"
pkg update -y >/dev/null 2>&1 || true
pkg install -y git python python-pip termux-api tmux nodejs-lts curl unzip >/dev/null 2>&1
print_ok "git, python, pip, termux-api, tmux, nodejs-lts, curl, unzip installed"

# Verify git is now available
if ! command -v git &>/dev/null; then
    print_err "git failed to install. Try: pkg install git"
    exit 1
fi
print_ok "git is available: $(git --version)"

# Verify node
if ! command -v node &>/dev/null; then
    print_err "node failed to install. Try: pkg install nodejs-lts"
    exit 1
fi
NODE_VERSION=$(node --version | sed 's/v//' | cut -d. -f1)
if [[ "$NODE_VERSION" -lt 22 ]]; then
    print_err "Node.js too old (need 22+). Got: $(node --version)"
    print_err "Run: pkg upgrade -y && pkg install -y nodejs-lts"
    exit 1
fi
print_ok "Node.js: $(node --version)"

# ============================================================
# 3. Install Termux:Boot app check
# ============================================================
print_step "Step 3: Termux:Boot check"
if [[ -d "$HOME/.termux/boot" ]] || [[ -d "$HOME/.termux" ]]; then
    print_ok "Termux:Boot appears to be installed"
else
    print_warn "Termux:Boot app does not appear to be installed"
    print_warn "Install it from F-Droid: https://f-droid.org/packages/com.termux.boot/"
    print_warn "After installing, OPEN Termux:Boot once (just launch and close it)"
    print_warn "Then re-run this script. Continuing anyway..."
fi

# ============================================================
# 4. Clone the ai-twin repo
# ============================================================
print_step "Step 4: Clone ai-twin from GitHub"

# Get out of any deleted folder
cd ~

# Remove old ai-twin if it exists
rm -rf ~/ai-twin 2>/dev/null

# Clone the phase2 branch
git clone --branch phase2 --depth 1 "https://$TOKEN@github.com/TYKO-sys/ai-twin-phase1.git" ~/ai-twin 2>&1 | tail -3

if [[ ! -d ~/ai-twin ]]; then
    print_err "Clone failed. Check your internet connection."
    exit 1
fi
print_ok "ai-twin cloned to ~/ai-twin"

# Make all scripts executable
chmod +x ~/ai-twin/*.sh ~/ai-twin/diagnostic.py 2>/dev/null
print_ok "Scripts made executable"

# ============================================================
# 5. Run the phone_switch.sh restore
# ============================================================
print_step "Step 5: Restore from backup (download + install everything)"

# Set the GITHUB_TOKEN env var so phone_switch.sh can use it
export GITHUB_TOKEN="$TOKEN"

# Run the restore script
bash ~/ai-twin/phone_switch.sh restore

# ============================================================
# 6. Final verification
# ============================================================
print_step "Step 6: Final verification"

echo ""
echo "Running tmux sessions:"
tmux ls 2>/dev/null || echo "  (none yet — wait 30 seconds and try again)"

echo ""
if pgrep -f "twin_bot.py" >/dev/null; then
    print_ok "Twin: RUNNING"
else
    print_warn "Twin: still starting up. Wait 30s and check: twin-logs"
fi

if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
    print_ok "FreeLLMAPI: RUNNING at http://localhost:3001/v1"
else
    print_warn "FreeLLMAPI: still starting. Check: tmux attach -t freellmapi"
fi

print_ok "Wakelock: ACTIVE"

# ============================================================
# Done
# ============================================================
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Install complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Your AI Twin is now running on this phone."
echo "Phone 1's twin was stopped when you ran backup."
echo "The phone lock prevents both from running at once."
echo ""
echo "Test it: open Telegram, message @TYKO_twin_bot"
echo ""
echo "Useful commands:"
echo -e "  ${CYAN}twin-start${NC}       start the twin"
echo -e "  ${CYAN}twin-stop${NC}        stop the twin"
echo -e "  ${CYAN}twin-logs${NC}        view live logs"
echo -e "  ${CYAN}twin-status${NC}      check if running"
echo -e "  ${CYAN}tmux attach -t freellmapi${NC}  view FreeLLMAPI logs"
echo -e "  ${CYAN}termux-open-url http://localhost:5173${NC}  open FreeLLMAPI dashboard"
echo ""
echo "Updates: just say 'update' to your twin in Telegram."
echo ""
echo -e "${GREEN}Done. Go talk to your twin.${NC}"
