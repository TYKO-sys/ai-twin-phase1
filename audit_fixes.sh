#!/data/data/com.termux/files/usr/bin/bash
# audit_fixes.sh — apply audit fixes to ai-twin (v2 — fixed import bug)
set -e
cd ~/ai-twin

echo "=== AI Twin Audit Fixes (v2) ==="
echo "Backing up current files..."
mkdir -p ~/ai-twin-backups/audit-$(date +%Y%m%d_%H%M%S)
BACKUP=~/ai-twin-backups/audit-$(date +%Y%m%d_%H%M%S)
cp twin_bot.py "$BACKUP/" 2>/dev/null || true
cp tools.py "$BACKUP/" 2>/dev/null || true
cp diagnostic.py "$BACKUP/" 2>/dev/null || true
cp ~/freellmapi-run.sh "$BACKUP/" 2>/dev/null || true
echo "Backed up to $BACKUP"

echo ""
echo "Applying audit patches (no git reset — keep current state)..."

# Patch 1: FreeLLMAPI health check (twin_bot.py)
python3 <<'PYEOF'
import os, re
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

new_check = '''def _check_freellmapi_available(max_wait=15):
    """Properly check FreeLLMAPI: socket first (fast), then auth check (real)."""
    import socket
    import requests
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(('127.0.0.1', 3001))
        sock.close()
        if result != 0:
            logger.warning("FreeLLMAPI not listening on :3001")
            return False
    except Exception as e:
        logger.warning(f"FreeLLMAPI socket check failed: {e}")
        return False
    
    try:
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(total=0))
        session.mount('http://', adapter)
        
        api_key = os.getenv('FREELLMAPI_API_KEY', '').strip()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        
        resp = session.get(
            "http://127.0.0.1:3001/v1/models",
            headers=headers,
            timeout=(5, 10)
        )
        
        try:
            body = resp.json()
        except Exception:
            logger.warning(f"FreeLLMAPI returned non-JSON (status {resp.status_code})")
            return False
        
        if "error" in body:
            logger.warning(f"FreeLLMAPI auth error: {body['error'].get('message', 'unknown')}")
            return False
        
        if "data" not in body or not body["data"]:
            logger.warning("FreeLLMAPI returned no models")
            return False
        
        logger.info(f"FreeLLMAPI is up ({len(body['data'])} models)")
        return True
        
    except requests.exceptions.Timeout:
        logger.warning("FreeLLMAPI read timed out (10s)")
        return False
    except Exception as e:
        logger.warning(f"FreeLLMAPI check failed: {e}")
        return False'''

pattern = re.compile(r'def _check_freellmapi_available\([^)]*\)[^:]*:.*?(?=\ndef |\Z)', re.DOTALL)
if pattern.search(src):
    src = pattern.sub(new_check + '\n\n', src, count=1)
    with open(path, 'w') as f: f.write(src)
    print("OK Patched _check_freellmapi_available")
else:
    print("SKIP could not find _check_freellmapi_available")
PYEOF

# Patch 2: FreeLLMAPI startup script — server only
cat > ~/freellmapi-run.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/freellmapi
LOG=~/ai-twin-memory/freellmapi.log
while true; do
    echo "[$(date)] FreeLLMAPI server starting (server only)..." >> "$LOG"
    npm run dev -w server 2>&1 | tee -a "$LOG"
    echo "[$(date)] FreeLLMAPI server crashed, restarting in 5s..." >> "$LOG"
    sleep 5
done
EOF
chmod +x ~/freellmapi-run.sh
echo "OK Patched freellmapi-run.sh (server only)"

# Patch 3: Add task dedup check to tools.py
python3 <<'PYEOF'
import os, re
path = os.path.expanduser('~/ai-twin/tools.py')
with open(path) as f: src = f.read()

if '_tokenize' not in src:
    tokenize_func = '''
def _tokenize(text):
    """Split text into meaningful word tokens, ignoring stopwords."""
    import re
    stopwords = {"the", "a", "an", "to", "for", "and", "or", "of", "in", "on", "at", "by", "with", "is", "are", "was", "were", "be", "your", "you", "my", "me", "i", "this", "that"}
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return [t for t in tokens if t not in stopwords and len(t) > 2]

'''
    src = src.replace('\ndef ', tokenize_func + '\ndef ', 1)

if 'DEDUP CHECK' not in src:
    dedup_code = '''
    # DEDUP CHECK — prevent creating duplicate tasks
    tasks = _load_tasks()
    title_lower = title.lower().strip()
    title_words = set(_tokenize(title_lower))
    for existing in tasks:
        if existing.get("completed"):
            continue
        existing_title = existing.get("title", "").lower().strip()
        existing_words = set(_tokenize(existing_title))
        if not existing_words or not title_words:
            continue
        intersection = title_words & existing_words
        union = title_words | existing_words
        similarity = len(intersection) / len(union) if union else 0
        is_substring = (title_lower in existing_title or existing_title in title_lower)
        if similarity >= 0.55 or is_substring:
            return {
                "status": "duplicate_detected",
                "existing_task_id": existing["id"],
                "existing_title": existing["title"],
                "message": f"Similar task already exists (#{existing['id']}). Use update_task instead."
            }
'''
    pattern = re.compile(r'(def tool_create_task\([^)]*\):.*?""".*?""")', re.DOTALL)
    match = pattern.search(src)
    if match:
        inject_point = match.end()
        src = src[:inject_point] + dedup_code + src[inject_point:]
        with open(path, 'w') as f: f.write(src)
        print("OK Patched tool_create_task with dedup check")
    else:
        print("SKIP could not find tool_create_task")
else:
    print("SKIP tool_create_task already patched")
PYEOF

# Patch 4: Fix diagnostic.py to load dotenv
python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/diagnostic.py')
with open(path) as f: src = f.read()

if 'from dotenv import load_dotenv' not in src:
    src = src.replace(
        'import os\n',
        'import os\nfrom dotenv import load_dotenv\nload_dotenv(os.path.join(os.path.expanduser("~/ai-twin"), ".env"))\n',
        1
    )
    with open(path, 'w') as f: f.write(src)
    print("OK Patched diagnostic.py to load .env")
else:
    print("SKIP diagnostic.py already loads dotenv")
PYEOF

# Patch 5: Create archive script
cat > ~/ai-twin/archive_stale_tasks.py <<'PYEOF'
#!/usr/bin/env python3
"""Archive tasks that are completed or more than 7 days overdue."""
import json, os
from datetime import datetime, timedelta

MEMORY = os.path.expanduser("~/ai-twin-memory")
TASKS = os.path.join(MEMORY, "tasks.json")
ARCHIVE = os.path.join(MEMORY, "tasks_archive.json")

def main():
    if not os.path.exists(TASKS): return
    with open(TASKS) as f: tasks = json.load(f)
    cutoff = datetime.now() - timedelta(days=7)
    keep, archive = [], []
    for t in tasks:
        if not t.get("completed"):
            due = t.get("due_date", "")
            if due and len(due) >= 10:
                try:
                    if datetime.fromisoformat(due[:10]) < cutoff:
                        archive.append(t); continue
                except: pass
            keep.append(t)
        else:
            comp = t.get("completed_at", "")
            if comp:
                try:
                    dt = datetime.fromisoformat(comp[:19] if "T" in comp else comp[:10])
                    if dt < cutoff: archive.append(t); continue
                except: pass
            keep.append(t)
    existing = []
    if os.path.exists(ARCHIVE):
        try:
            with open(ARCHIVE) as f: existing = json.load(f)
        except: pass
    existing.extend(archive)
    with open(TASKS, 'w') as f: json.dump(keep, f, indent=2)
    with open(ARCHIVE, 'w') as f: json.dump(existing, f, indent=2)
    print(f"Kept {len(keep)} active. Archived {len(archive)} stale. Total archive: {len(existing)}")

if __name__ == "__main__": main()
PYEOF
chmod +x ~/ai-twin/archive_stale_tasks.py
echo "OK Created archive_stale_tasks.py"

echo ""
echo "Archiving stale tasks..."
python3 ~/ai-twin/archive_stale_tasks.py

echo ""
echo "=== Restarting twin and FreeLLMAPI ==="
pkill -f "freellmapi" 2>/dev/null || true
sleep 2
tmux kill-session -t freellmapi 2>/dev/null || true
tmux kill-session -t twin 2>/dev/null || true
sleep 2

tmux new-session -d -s freellmapi "bash ~/freellmapi-run.sh"
sleep 8

tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'Bot crashed, restarting in 5s...'; sleep 5; done"

echo ""
echo "=== Done ==="
echo "Watch logs:  twin-logs  (or: tail -f ~/ai-twin-memory/twin.log)"
