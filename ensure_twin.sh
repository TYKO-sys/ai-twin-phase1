#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Ensure the AI Twin is running (called from .bashrc on every Termux open)
# ============================================================
# Sibling to ensure_freellmapi.sh — same pattern, different process.
# Idempotent: exits 0 if the twin is already up; starts it if not.

# Check if twin is already running (tmux session exists AND python process alive)
if tmux has-session -t twin 2>/dev/null; then
    # Twin session exists — check if the process is alive
    if pgrep -f "twin_bot.py" >/dev/null 2>&1; then
        # All good
        exit 0
    fi
fi

# Twin is not running — start it via the canonical wrapper if present
if [ -f "$HOME/bin/twin-start" ]; then
    bash "$HOME/bin/twin-start" >/dev/null 2>&1
    exit $?
fi

# Fallback: start directly inside ~/ai-twin
if [ -f "$HOME/ai-twin/twin_bot.py" ]; then
    cd "$HOME/ai-twin" && tmux new-session -d -s twin "python twin_bot.py" 2>/dev/null
    exit $?
fi

# Twin not installed yet — nothing to do
exit 0
