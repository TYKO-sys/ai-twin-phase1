#!/data/data/com.termux/files/usr/bin/bash
# collect_diagnostics.sh — bundle ALL diagnostic info into one file for upload
# Secrets are automatically redacted before output

OUT=~/ai-twin-memory/DIAGNOSTIC_BUNDLE.txt
> "$OUT"

section() {
    echo "" >> "$OUT"
    echo "================================================================" >> "$OUT"
    echo "=== $1 ===" >> "$OUT"
    echo "================================================================" >> "$OUT"
    echo "" >> "$OUT"
}

redact() {
    # Redact API keys, tokens, passwords, SMTP creds
    sed -E \
        -e 's/(github_pat_[A-Za-z0-9_]+)/REDACTED_PAT/g' \
        -e 's/(gsk_[A-Za-z0-9]+)/REDACTED_GROQ/g' \
        -e 's/(sk-or-v1-[A-Za-z0-9]+)/REDACTED_OPENROUTER/g' \
        -e 's/(freellmapi-[A-Za-z0-9]+)/REDACTED_FREELLMAPI/g' \
        -e 's/(csk-[A-Za-z0-9]+)/REDACTED_CEREBRAS/g' \
        -e 's/(AQ\.[A-Za-z0-9_-]+)/REDACTED_GEMINI/g' \
        -e 's/(J[0-9]+[A-Za-z0-9]{20,})/REDACTED_MISTRAL/g' \
        -e 's/(be[0-9a-f]{30,})/REDACTED_ZAI/g' \
        -e 's/(8958[0-9]+:[A-Za-z0-9_-]+)/REDACTED_TELEGRAM/g' \
        -e 's/(mike\.maziq93@gmail\.com)/REDACTED_EMAIL/g' \
        -e 's/(chromatic5)/REDACTED_SMTP_PASS/g' \
        -e 's/(7959193473)/REDACTED_USER_ID/g'
}

echo "Collecting diagnostics to $OUT ..."
echo "Bundle generated: $(date)" > "$OUT"

# === SYSTEM INFO ===
section "SYSTEM INFO"
{
    echo "Date: $(date)"
    echo "Uptime: $(uptime)"
    echo "Free memory:"
    free -h
    echo ""
    echo "Disk usage:"
    df -h ~/ai-twin-memory 2>/dev/null
    echo ""
    echo "tmux sessions:"
    tmux ls 2>&1
    echo ""
    echo "Twin processes:"
    ps aux | grep -E "twin_bot|freellmapi|node" | grep -v grep
    echo ""
    echo "FreeLLMAPI health check:"
    curl -s -m 3 http://localhost:3001/v1/models -H "Authorization: Bearer test" | head -c 200
    echo ""
    echo "Battery:"
    termux-battery-status 2>/dev/null | head -c 300
    echo ""
    echo "Network:"
    ip addr show wlan0 2>/dev/null | grep "inet " | head -1
    echo ""
    echo "Termux wake lock status:"
    cat /proc/locks 2>/dev/null | head -3
} >> "$OUT" 2>&1

# === GIT INFO ===
section "GIT INFO"
{
    cd ~/ai-twin
    echo "Current branch:"
    git branch --show-current
    echo ""
    echo "Last 10 commits:"
    git log --oneline -10
    echo ""
    echo "Last known commit file:"
    cat ~/ai-twin-memory/last_known_commit.txt 2>/dev/null
    echo ""
    echo "Git status:"
    git status --short
} >> "$OUT" 2>&1

# === TWIN LOG (LAST 800 LINES) ===
section "TWIN LOG (last 800 lines)"
tail -800 ~/ai-twin-memory/twin.log 2>/dev/null | redact >> "$OUT"

# === FREELLMAPI LOG (LAST 200 LINES) ===
section "FREELLMAPI LOG (last 200 lines)"
tail -200 ~/ai-twin-memory/freellmapi.log 2>/dev/null >> "$OUT"

# === MEMORY FILES ===
section "tasks.json"
cat ~/ai-twin-memory/tasks.json 2>/dev/null >> "$OUT"

section "reminders.json"
cat ~/ai-twin-memory/reminders.json 2>/dev/null >> "$OUT"

section "nudge_log.json"
cat ~/ai-twin-memory/nudge_log.json 2>/dev/null >> "$OUT"

section "unanswered_queue.json"
cat ~/ai-twin-memory/unanswered_queue.json 2>/dev/null >> "$OUT"

section "contacts.json"
cat ~/ai-twin-memory/contacts.json 2>/dev/null >> "$OUT"

section "routines.json"
cat ~/ai-twin-memory/routines.json 2>/dev/null >> "$OUT"

section "goals.json"
cat ~/ai-twin-memory/goals.json 2>/dev/null >> "$OUT"

section "location_log.json (last 20)"
python3 -c "
import json
try:
    with open('$HOME/ai-twin-memory/location_log.json') as f:
        data = json.load(f)
    print(json.dumps(data[-20:], indent=2))
except: print('not found or empty')
" >> "$OUT"

section "diagnostic.json (last run)"
cat ~/ai-twin-memory/diagnostic.json 2>/dev/null >> "$OUT"

section "gist_id.txt / phone_id.txt / env_backup.txt (REDACTED)"
{
    echo "gist_id.txt:"
    cat ~/ai-twin-memory/gist_id.txt 2>/dev/null | sed -E 's/[a-f0-9]{20,}/REDACTED/g'
    echo ""
    echo "phone_id.txt:"
    cat ~/ai-twin-memory/phone_id.txt 2>/dev/null | sed -E 's/[a-f0-9]{20,}/REDACTED/g'
    echo ""
    echo "gist_failed.txt (if exists):"
    cat ~/ai-twin-memory/gist_failed.txt 2>/dev/null
    echo ""
    echo "location_notified.txt (if exists):"
    cat ~/ai-twin-memory/location_notified.txt 2>/dev/null
} >> "$OUT"

# === KNOWLEDGE BASE ===
section "KNOWLEDGE BASE — all 8 domain files"
{
    for f in ~/ai-twin-memory/knowledge/*.md; do
        echo "--- $(basename $f) ---"
        cat "$f" 2>/dev/null
        echo ""
    done
} >> "$OUT"

# === DAILY CONVERSATION LOGS (last 3 days) ===
section "DAILY LOGS (last 3 days)"
{
    for f in $(ls -t ~/ai-twin-memory/daily/*.md 2>/dev/null | head -3); do
        echo "--- $(basename $f) ---"
        cat "$f" 2>/dev/null
        echo ""
    done
} >> "$OUT"

# === JOURNAL (current month) ===
section "JOURNAL (current month)"
{
    for f in $(ls -t ~/ai-twin-memory/journal/*.md 2>/dev/null | head -5); do
        echo "--- $(basename $f) ---"
        cat "$f" 2>/dev/null
        echo ""
    done
} >> "$OUT"

# === NOTES (last 5) ===
section "NOTES (last 5)"
{
    for f in $(ls -t ~/ai-twin-memory/notes/*.md 2>/dev/null | head -5); do
        echo "--- $(basename $f) ---"
        cat "$f" 2>/dev/null
        echo ""
    done
} >> "$OUT"

# === DRAFTS (last 5) ===
section "DRAFTS (last 5)"
{
    for f in $(ls -t ~/ai-twin-memory/drafts/*.md 2>/dev/null | head -5); do
        echo "--- $(basename $f) ---"
        cat "$f" 2>/dev/null
        echo ""
    done
} >> "$OUT"

# === IDENTITY FILES ===
section "IDENTITY (identity/ folder)"
{
    for f in ~/ai-twin-memory/identity/*.md 2>/dev/null; do
        echo "--- $(basename $f) ---"
        cat "$f" 2>/dev/null
        echo ""
    done
} >> "$OUT"

section "index.md"
cat ~/ai-twin-memory/index.md 2>/dev/null >> "$OUT"

# === .env (REDACTED) ===
section ".env (REDACTED — secrets masked)"
cat ~/ai-twin/.env 2>/dev/null | redact >> "$OUT"

# === VOICE PROFILE ===
section "voice_profile.md"
cat ~/ai-twin-memory/voice_profile.md 2>/dev/null >> "$OUT"

# === SYSTEM PROMPT ===
section "system_prompt.txt"
cat ~/ai-twin/system_prompt.txt 2>/dev/null >> "$OUT"

# === MODELS CONFIG ===
section "models_config.json"
cat ~/ai-twin/models_config.json 2>/dev/null >> "$OUT"

# === SOURCE CODE FILES ===
section "twin_bot.py"
cat ~/ai-twin/twin_bot.py 2>/dev/null | redact >> "$OUT"

section "tools.py"
cat ~/ai-twin/tools.py 2>/dev/null | redact >> "$OUT"

section "knowledge_base.py"
cat ~/ai-twin/knowledge_base.py 2>/dev/null >> "$OUT"

section "multi_provider.py"
cat ~/ai-twin/multi_provider.py 2>/dev/null | redact >> "$OUT"

section "freellmapi-run.sh"
cat ~/ai-twin/freellmapi-run.sh 2>/dev/null >> "$OUT"
echo "--- ~/freellmapi-run.sh ---" >> "$OUT"
cat ~/freellmapi-run.sh 2>/dev/null >> "$OUT"

section "Termux boot script"
cat ~/.termux/boot/start-twin.sh 2>/dev/null >> "$OUT"

section ".bashrc (twin-related lines)"
grep -E "twin|freellmapi|ensure_" ~/.bashrc 2>/dev/null | redact >> "$OUT"

# === HEALTH/STATUS FILES ===
section "health_report.txt"
cat ~/ai-twin-memory/health_report.txt 2>/dev/null >> "$OUT"

section "twin_last_session.log"
cat ~/ai-twin-memory/twin_last_session.log 2>/dev/null >> "$OUT"

# === LIST OF ALL MEMORY FILES ===
section "ALL FILES in ~/ai-twin-memory/ (ls -la)"
ls -la ~/ai-twin-memory/ >> "$OUT" 2>&1

section "ALL FILES in ~/ai-twin-memory/knowledge/"
ls -la ~/ai-twin-memory/knowledge/ >> "$OUT" 2>&1

section "ALL FILES in ~/ai-twin/ (ls -la)"
ls -la ~/ai-twin/ >> "$OUT" 2>&1

# === DONE ===
section "END OF BUNDLE"
echo "Bundle complete. Total size:" >> "$OUT"
wc -c "$OUT" >> "$OUT"
wc -l "$OUT" >> "$OUT"

echo ""
echo "=========================================="
echo "Diagnostic bundle saved to:"
echo "  $OUT"
echo ""
echo "Size: $(wc -c < "$OUT") bytes"
echo "Lines: $(wc -l < "$OUT")"
echo ""
echo "To upload: open Termux, then:"
echo "  termux-open $OUT"
echo ""
echo "Or copy to shared storage:"
echo "  cp $OUT ~/storage/shared/"
echo "  termux-open ~/storage/shared/DIAGNOSTIC_BUNDLE.txt"
echo "=========================================="
