#!/data/data/com.termux/files/usr/bin/bash
# audit_cleanup.sh — Phase 9 bug audit fixes (data + Android layer)
set -e
cd ~/ai-twin

echo "=== AUDIT CLEANUP — $(date) ==="

# Backup current state
BACKUP=~/ai-twin-backups/audit-cleanup-$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP"
cp ~/ai-twin-memory/tasks.json "$BACKUP/"
cp ~/ai-twin-memory/reminders.json "$BACKUP/"
cp ~/ai-twin-memory/contacts.json "$BACKUP/"
cp ~/ai-twin-memory/nudge_log.json "$BACKUP/"
cp -r ~/ai-twin-memory/knowledge/ "$BACKUP/"
echo "Backed up to $BACKUP"

# FIX #5: Remove diagnostic test tasks
echo ""
echo "=== Fix #5: removing diagnostic test tasks ==="
python3 <<'PYEOF'
import json
path = '/data/data/com.termux/files/home/ai-twin-memory/tasks.json'
with open(path) as f: tasks = json.load(f)
before = len(tasks)
tasks = [t for t in tasks if t.get('title', '').lower().strip() != 'diagnostic test task']
after = len(tasks)
with open(path, 'w') as f: json.dump(tasks, f, indent=2)
print(f"Removed {before - after} diagnostic test tasks (was {before}, now {after})")
PYEOF

# FIX #9: Archive fired reminders older than 7 days
echo ""
echo "=== Fix #9: archiving old fired reminders ==="
python3 <<'PYEOF'
import json, os
from datetime import datetime, timedelta

MEMORY = '/data/data/com.termux/files/home/ai-twin-memory'
REMINDERS = f'{MEMORY}/reminders.json'
ARCHIVE = f'{MEMORY}/reminders_archive.json'

with open(REMINDERS) as f: reminders = json.load(f)
cutoff = datetime.now() - timedelta(days=7)

keep, archive = [], []
for r in reminders:
    if r.get('fired'):
        try:
            dt = datetime.fromisoformat(r.get('when_iso', ''))
            if dt < cutoff:
                archive.append(r)
                continue
        except: pass
    keep.append(r)

existing_archive = []
if os.path.exists(ARCHIVE):
    try:
        with open(ARCHIVE) as f: existing_archive = json.load(f)
    except: pass
existing_archive.extend(archive)

with open(REMINDERS, 'w') as f: json.dump(keep, f, indent=2)
with open(ARCHIVE, 'w') as f: json.dump(existing_archive, f, indent=2)
print(f"Kept {len(keep)} active. Archived {len(archive)} old fired. Total archive: {len(existing_archive)}")
PYEOF

# FIX #2 (partial): Clean corrupted KB files
echo ""
echo "=== Fix #2: cleaning leaked personality text from KB ==="
python3 <<'PYEOF'
import os, re

KB_DIR = '/data/data/com.termux/files/home/ai-twin-memory/knowledge'

# Patterns that indicate personality/prompt leak
LEAK_PATTERNS = [
    r'^You are (a |resilient|the |an )',
    r'^You move fastest',
    r'^You tend to',
    r'^You rely on',
    r'^You work best',
    r'^You feel overwhelmed',
    r'^You respond well',
]
LEAK_RE = re.compile('|'.join(LEAK_PATTERNS))

# Metadata artifacts
META_RE = re.compile(r'\[Updated [^\]]+\]:?\s*')

for fname in os.listdir(KB_DIR):
    if not fname.endswith('.md'):
        continue
    path = os.path.join(KB_DIR, fname)
    with open(path) as f: content = f.read()
    original = content
    
    # Remove leaked personality lines
    lines = content.split('\n')
    cleaned = []
    removed = 0
    for line in lines:
        if LEAK_RE.match(line.strip()):
            removed += 1
            continue
        # Strip [Updated ...] artifacts
        line = META_RE.sub('', line)
        cleaned.append(line)
    
    new_content = '\n'.join(cleaned).strip() + '\n'
    if new_content != original:
        with open(path, 'w') as f: f.write(new_content)
        print(f"  {fname}: removed {removed} leaked lines, stripped metadata")
    else:
        print(f"  {fname}: clean")
PYEOF

# FIX #7: Detect location (0,0) and notify user once
echo ""
echo "=== Fix #7: location check ==="
python3 <<'PYEOF'
import json, os
LOG = '/data/data/com.termux/files/home/ai-twin-memory/twin.log'
NOTIFIED = '/data/data/com.termux/files/home/ai-twin-memory/location_notified.txt'

# Check last 100 lines for "location unavailable"
try:
    with open(LOG) as f:
        lines = f.readlines()[-100:]
except: lines = []

loc_fail = sum(1 for l in lines if 'location unavailable' in l.lower())
if loc_fail > 0 and not os.path.exists(NOTIFIED):
    print(f"WARNING: Location returning (0,0) in {loc_fail} recent log lines.")
    print("Possible causes: GPS off, location permission missing, airplane mode.")
    print("Run: termux-setup-location  (then enable GPS in Android settings)")
    open(NOTIFIED, 'w').write('notified')
else:
    print("Location OK or already notified")
PYEOF

# FIX #11: Backfill missing task fields
echo ""
echo "=== Fix #11: backfilling task schema ==="
python3 <<'PYEOF'
import json
path = '/data/data/com.termux/files/home/ai-twin-memory/tasks.json'
with open(path) as f: tasks = json.load(f)

defaults = {
    'status': 'active',
    'blocked_on': '',
    'next_action': '',
    'energy': 'medium',
    'context': [],
    'category': '',
    'notes': '',
}
backfilled = 0
for t in tasks:
    for k, v in defaults.items():
        if k not in t:
            t[k] = v
            backfilled += 1
    # Ensure created_at exists (use 'created' if missing)
    if 'created_at' not in t and 'created' in t:
        t['created_at'] = t['created']

with open(path, 'w') as f: json.dump(tasks, f, indent=2)
print(f"Backfilled {backfilled} missing fields across {len(tasks)} tasks")
PYEOF

# FIX #3: Install Termux:Boot setup + wakelock (Android stability)
echo ""
echo "=== Fix #3: Termux:Boot setup ==="
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-twin.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start twin on device boot
sleep 10
termux-wake-lock
tmux kill-session -t twin 2>/dev/null || true
tmux kill-session -t freellmapi 2>/dev/null || true
sleep 2
tmux new-session -d -s freellmapi "bash ~/freellmapi-run.sh"
sleep 8
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'crashed, restarting in 5s'; sleep 5; done"
EOF
chmod +x ~/.termux/boot/start-twin.sh
echo "Created ~/.termux/boot/start-twin.sh"
echo ""
echo "IMPORTANT: Install Termux:Boot from F-Droid to activate:"
echo "  https://f-droid.org/packages/com.termux.boot/"
echo "After install, open Termux:Boot ONCE (just launch and close)."
echo ""
echo "Also: disable battery optimization for Termux:"
echo "  Android Settings → Apps → Termux → Battery → Unrestricted"

# FIX #4: Make phone lock gracefully degrade on 403
echo ""
echo "=== Fix #4: phone lock graceful degradation ==="
# This needs twin_bot.py code change — flag it for next round
echo "Phone lock 403 fix requires code change to twin_bot.py (deferred to next round)"
echo "WORKAROUND: regenerate your GitHub PAT with 'gist' scope at"
echo "  https://github.com/settings/tokens"
echo "  (edit existing token → check 'gist' → save)"

# Acquire wakelock now
echo ""
echo "=== Acquiring wakelock now ==="
termux-wake-lock 2>/dev/null && echo "Wakelock acquired" || echo "termux-wake-lock not available (install termux-api)"

echo ""
echo "=== Done. Restarting twin ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'crashed, restarting in 5s'; sleep 5; done"
sleep 10
echo "=== Last 10 log lines ==="
tail -10 ~/ai-twin-memory/twin.log
