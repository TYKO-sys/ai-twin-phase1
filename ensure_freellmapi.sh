#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Ensure FreeLLMAPI is running (called from .bashrc on every Termux open)
# ============================================================

# Only run if FreeLLMAPI is installed
if [[ ! -f "$HOME/freellmapi-run.sh" ]]; then
    exit 0
fi

# Check if it's already running in tmux
if tmux has-session -t freellmapi 2>/dev/null; then
    # Session exists, but is FreeLLMAPI actually responding?
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
        # All good, do nothing
        exit 0
    fi
fi

# FreeLLMAPI is not running or not responding — start it
tmux kill-session -t freellmapi 2>/dev/null || true
sleep 1
tmux new-session -d -s freellmapi "$HOME/freellmapi-run.sh"

# Wait up to 60 seconds for it to come up
for i in $(seq 1 30); do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/v1/models 2>/dev/null | grep -q "200\|401\|403"; then
        echo "[OK] FreeLLMAPI is up at http://localhost:3001"
        exit 0
    fi
    sleep 2
done

echo "[!] FreeLLMAPI didn't start in 60 seconds. Check: tmux attach -t freellmapi"
exit 1
