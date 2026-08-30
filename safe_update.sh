#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — SAFE update script
# ============================================================
# This script updates your ai-twin code WITHOUT touching your .env
# file. It's designed to be run repeatedly without risk.
#
# Usage:
#   1. Download the new ai-twin.zip to your phone's Downloads folder
#   2. In Termux, run:
#        bash ~/ai-twin/safe_update.sh
#
# What this script does:
#   1. Verifies your .env exists and is non-empty
#   2. Backs it up to THREE places (overkill, but safe)
#   3. Extracts the new zip to a TEMP folder
#   4. Copies ONLY the code files (not .env, not .env.example)
#   5. Verifies your .env is still intact
#   6. Restarts nothing — you do that manually
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

# ------------------------------------------------------------
# 0. Find the ai-twin folder
# ------------------------------------------------------------
AI_TWIN_DIR="$HOME/ai-twin"
if [[ ! -d "$AI_TWIN_DIR" ]]; then
    print_err "ai-twin folder not found at $AI_TWIN_DIR"
    print_err "Make sure you're running this from the right place."
    exit 1
fi
cd "$AI_TWIN_DIR"

# ------------------------------------------------------------
# 1. Verify .env exists and is non-empty
# ------------------------------------------------------------
print_step "Step 1: Verify your .env file"
if [[ ! -f ".env" ]]; then
    print_err ".env file NOT FOUND. Cannot proceed safely."
    print_err "Create one first: cp .env.example .env && nano .env"
    exit 1
fi

ENV_SIZE=$(wc -c < .env)
if [[ "$ENV_SIZE" -lt 50 ]]; then
    print_err ".env file is too small ($ENV_SIZE bytes). Looks empty or broken."
    exit 1
fi
print_ok ".env exists ($ENV_SIZE bytes)"

# ------------------------------------------------------------
# 2. Back up .env to THREE places (all in home folder — /tmp is
#    read-only on Termux)
# ------------------------------------------------------------
print_step "Step 2: Back up .env (triple redundancy)"

# Backup 1: home directory (top level)
cp .env "$HOME/.env.backup"
print_ok "Backup 1: $HOME/.env.backup"

# Backup 2: inside a hidden folder in ai-twin
mkdir -p .env_backups
cp .env ".env_backups/.env.$(date +%Y%m%d_%H%M%S)"
print_ok "Backup 2: .env_backups/"

# Backup 3: another copy in home with timestamp
cp .env "$HOME/.env.backup.$(date +%s)"
print_ok "Backup 3: $HOME/.env.backup.<timestamp>"

# ------------------------------------------------------------
# 3. Verify backups
# ------------------------------------------------------------
print_step "Step 3: Verify backups"
for backup in "$HOME/.env.backup" .env_backups/.env.* "$HOME/.env.backup."*; do
    if [[ -f "$backup" ]]; then
        SIZE=$(wc -c < "$backup")
        if [[ "$SIZE" -ge 50 ]]; then
            print_ok "$backup ($SIZE bytes)"
        else
            print_warn "$backup is suspiciously small ($SIZE bytes)"
        fi
    fi
done

# ------------------------------------------------------------
# 4. Find the new zip
# ------------------------------------------------------------
print_step "Step 4: Find the new ai-twin.zip"
ZIP_PATH=""
for candidate in \
    "$HOME/storage/downloads/ai-twin.zip" \
    "$HOME/ai-twin.zip" \
    "$HOME/storage/shared/Download/ai-twin.zip" \
    "$HOME/storage/shared/Downloads/ai-twin.zip"; do
    if [[ -f "$candidate" ]]; then
        ZIP_PATH="$candidate"
        break
    fi
done

if [[ -z "$ZIP_PATH" ]]; then
    print_err "ai-twin.zip not found in Downloads."
    print_err "Download it first, then re-run this script."
    print_err ""
    print_err "Checked:"
    print_err "  $HOME/storage/downloads/ai-twin.zip"
    print_err "  $HOME/ai-twin.zip"
    print_err "  $HOME/storage/shared/Download/ai-twin.zip"
    print_err "  $HOME/storage/shared/Downloads/ai-twin.zip"
    exit 1
fi
print_ok "Found zip: $ZIP_PATH"

# ------------------------------------------------------------
# 5. Extract to a TEMP folder (in home, not /tmp which is read-only)
# ------------------------------------------------------------
print_step "Step 5: Extract new code to temp folder"
TEMP_DIR="$HOME/ai-twin-update-tmp-$(date +%s)"
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
unzip -q "$ZIP_PATH" -d "$TEMP_DIR"

# Verify extraction worked
if [[ ! -f "$TEMP_DIR/ai-twin/twin_bot.py" ]]; then
    print_err "Extraction failed — twin_bot.py not found in temp folder"
    exit 1
fi
print_ok "Extracted to $TEMP_DIR"

# ------------------------------------------------------------
# 6. Copy ONLY code files (never .env)
# ------------------------------------------------------------
print_step "Step 6: Update code files (preserving .env)"

# Files to update
CODE_FILES=(
    "twin_bot.py"
    "context_manager.py"
    "gemini_client.py"
    "openrouter_client.py"
    "multi_provider.py"
    "model_manager.py"
    "profile_manager.py"
    "error_handler.py"
    "summarizer.py"
    "tools.py"
    "wizard.py"
    "system_prompt.txt"
    "requirements.txt"
    "models_config.json"
    "SETUP_GUIDE.html"
    "install.sh"
    "start.sh"
    "keep_alive_setup.sh"
    "README.md"
    "USER_GUIDE.md"
    "TROUBLESHOOTING.md"
    ".env.example"
)

for f in "${CODE_FILES[@]}"; do
    if [[ -f "$TEMP_DIR/ai-twin/$f" ]]; then
        cp "$TEMP_DIR/ai-twin/$f" "$AI_TWIN_DIR/$f"
        print_ok "Updated: $f"
    fi
done

# Also copy the wizard_assets directory
if [[ -d "$TEMP_DIR/ai-twin/wizard_assets" ]]; then
    mkdir -p "$AI_TWIN_DIR/wizard_assets"
    cp -r "$TEMP_DIR/ai-twin/wizard_assets/"* "$AI_TWIN_DIR/wizard_assets/"
    print_ok "Updated: wizard_assets/"
fi

# ------------------------------------------------------------
# 6.5. Remove old/deprecated files
# ------------------------------------------------------------
print_step "Step 6.5: Remove old files"
OLD_FILES=(
    "FRIEND_NOTE.md"
    "FRIEND_NOTE_PHASE2.md"
    "MONETIZATION.md"
    "MANUAL_STEPS.md"
    "macrodroid_config.md"
    "setup.sh"
)
for f in "${OLD_FILES[@]}"; do
    if [[ -f "$AI_TWIN_DIR/$f" ]]; then
        rm -f "$AI_TWIN_DIR/$f"
        print_ok "Removed old file: $f"
    fi
done

# ------------------------------------------------------------
# 7. Verify .env is STILL intact
# ------------------------------------------------------------
print_step "Step 7: Verify .env survived"
if [[ ! -f ".env" ]]; then
    print_err ".env is GONE! Restoring from backup..."
    cp "$HOME/.env.backup" .env
    print_warn ".env restored from backup"
elif [[ $(wc -c < .env) -lt 50 ]]; then
    print_err ".env is corrupted! Restoring from backup..."
    cp "$HOME/.env.backup" .env
    print_warn ".env restored from backup"
else
    NEW_SIZE=$(wc -c < .env)
    print_ok ".env intact ($NEW_SIZE bytes)"
fi

# ------------------------------------------------------------
# 8. Clean up temp folder
# ------------------------------------------------------------
rm -rf "$TEMP_DIR"
print_ok "Cleaned up temp files"

# ------------------------------------------------------------
# 9. Done
# ------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Update complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Your .env is safe. Code files are updated."
echo ""
echo "To start the bot:"
echo -e "  ${CYAN}cd ~/ai-twin && python twin_bot.py${NC}"
echo ""
echo "Your .env backups are at:"
echo "  $HOME/.env.backup"
echo "  .env_backups/"
echo ""
