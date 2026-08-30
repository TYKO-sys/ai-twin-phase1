#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# AI Twin — quick launcher
# ============================================================
# Run this any time to start your twin.
#
#   bash ~/ai-twin/start.sh
#
# Or make it executable and just call:
#   ~/ai-twin/start.sh
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Make sure wakelock is held (in case Termux was restarted)
if command -v termux-wake-lock &>/dev/null; then
    termux-wake-lock 2>/dev/null || true
fi

# Make sure crond is running (for scheduled pings)
if command -v crond &>/dev/null; then
    pgrep crond > /dev/null || crond 2>/dev/null || true
fi

# Start the bot
echo "Starting AI Twin..."
echo "Press Ctrl+C to stop."
echo ""
python twin_bot.py
