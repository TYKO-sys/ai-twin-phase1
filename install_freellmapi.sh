#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — Install FreeLLMAPI locally
# ============================================================
# FreeLLMAPI is a self-hosted router that aggregates 34 free
# LLM providers (Groq, OpenRouter, Mistral, Cerebras, Gemini,
# etc.) behind one OpenAI-compatible endpoint at localhost:3001/v1
#
# Usage:
#   bash install_freellmapi.sh              # install + start
#   bash install_freellmapi.sh YOUR_KEY     # install + set key + restart twin
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
print_step() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
print_err()  { echo -e "${RED}[X]${NC} $1"; }

UNIFIED_KEY="${1:-}"

# 1. Check Node.js
print_step "Checking Node.js"
if ! command -v node &>/dev/null; then
    print_step "Installing Node.js"
    pkg install -y nodejs-lts >/dev/null 2>&1 || pkg install -y nodejs >/dev/null 2>&1
fi

NODE_VERSION=$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1)
if [[ -z "$NODE_VERSION" ]] || [[ "$NODE_VERSION" -lt 22 ]]; then
    print_err "Node.js version too old. Need 22.13+. Have: $(node --version 2>/dev/null)"
    print_err "Run: pkg upgrade -y && pkg install -y nodejs-lts"
    exit 1
fi
print_ok "Node.js: $(node --version)"

# 2. Clone FreeLLMAPI
print_step "Cloning FreeLLMAPI"
if [[ -d "$HOME/freellmapi" ]]; then
    print_ok "FreeLLMAPI already cloned at ~/freellmapi"
    cd "$HOME/freellmapi"
    git pull --quiet 2>/dev/null || true
else
    git clone --depth 1 https://github.com/tashfeenahmed/freellmapi.git "$HOME/freellmapi"
    cd "$HOME/freellmapi"
    print_ok "Cloned to ~/freellmapi"
fi

# 3. Install dependencies
print_step "Installing dependencies (this takes 2-5 minutes)"
npm install --no-audit --no-fund 2>&1 | tail -5
print_ok "Dependencies installed"

# 4. Start FreeLLMAPI in tmux
print_step "Starting FreeLLMAPI"
if tmux has-session -t freellmapi 2>/dev/null; then
    print_ok "FreeLLMAPI already running in tmux session 'freellmapi'"
else
    tmux new-session -d -s freellmapi "cd $HOME/freellmapi && npm run dev"
    print_ok "Started in tmux session 'freellmapi'"
fi

# 5. Wait for it to come up
print_step "Waiting for FreeLLMAPI to start (30 seconds)..."
sleep 30

# 6. Verify it's responding
print_step "Verifying FreeLLMAPI"
if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
    print_ok "FreeLLMAPI is responding at http://localhost:3001/v1"
else
    print_warn "FreeLLMAPI might still be starting. Check logs with: tmux attach -t freellmapi"
fi

# 7. Open dashboard
print_step "Opening dashboard"
termux-open-url "http://localhost:5173" 2>/dev/null || true
echo ""
echo "============================================"
echo "  FreeLLMAPI Dashboard"
echo "============================================"
echo ""
echo "Open this URL in your browser (should open automatically):"
echo "  http://localhost:5173"
echo ""
echo "Steps in the dashboard:"
echo "  1. Go to the Keys page"
echo "  2. Add your API keys for the providers you have:"
echo "     - Groq (https://console.groq.com/)"
echo "     - OpenRouter (https://openrouter.ai/keys)"
echo "     - Mistral (https://console.mistral.ai/)"
echo "     - Cerebras (https://inference.cerebras.ai/)"
echo "     - Google/Gemini (https://aistudio.google.com/apikey)"
echo "  3. Copy the UNIFIED API KEY from the top of the Keys page"
echo "  4. Run this script again with the key:"
echo ""
echo "     bash install_freellmapi.sh YOUR_UNIFIED_KEY"
echo ""
echo "That will update the twin's .env and restart it."
echo "============================================"

# 8. If a unified key was provided, write it to .env and restart twin
if [[ -n "$UNIFIED_KEY" ]]; then
    print_step "Updating twin's .env with unified key"
    ENV_FILE="$HOME/ai-twin/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        print_err "~/ai-twin/.env not found. Install the twin first."
        exit 1
    fi

    # Remove any existing FREELLMAPI_API_KEY line
    sed -i '/^FREELLMAPI_API_KEY=/d' "$ENV_FILE"

    # Add the new key
    echo "FREELLMAPI_API_KEY=$UNIFIED_KEY" >> "$ENV_FILE"
    print_ok "Unified key written to $ENV_FILE"

    # Restart twin
    print_step "Restarting twin"
    twin-stop 2>/dev/null
    sleep 2
    twin-start
    sleep 3

    print_ok "Twin restarted. It now uses FreeLLMAPI as primary provider."
    echo ""
    echo "Test it: send a message to your twin in Telegram."
    echo "Check logs: twin-logs"
    echo "You should see 'Provider freellmapi succeeded for generate_with_tools'"
fi
