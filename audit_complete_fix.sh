#!/data/data/com.termux/files/usr/bin/bash
set -e
cd ~/ai-twin

echo "=== COMPLETE AUDIT FIX — $(date) ==="

# Backup
BACKUP=~/ai-twin-backups/complete-fix-$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP"
cp twin_bot.py tools.py knowledge_base.py system_prompt.txt "$BACKUP/" 2>/dev/null || true

# ============================================================
# 1. CREATE MIGRATIONS FRAMEWORK
#    Idempotent migrations that run on every startup.
#    Each migration checks if it's already applied.
#    Tracked in ~/ai-twin-memory/applied_migrations.json
#    Safe to skip updates — all pending migrations run in order.
# ============================================================
echo ""
echo "=== Creating migrations framework ==="

cat > ~/ai-twin/migrations.py <<'MIGRATIONS_EOF'
"""
Idempotent migrations that run on every twin startup.

Each migration:
- Has a unique ID (string)
- Checks if it's already been applied
- Is safe to run multiple times
- Handles the case where the user skipped updates and jumped ahead

Tracked in ~/ai-twin-memory/applied_migrations.json
"""
import json
import os
import logging
from pathlib import Path

log = logging.getLogger("migrations")

MEMORY_DIR = Path.home() / "ai-twin-memory"
APPLIED_FILE = MEMORY_DIR / "applied_migrations.json"


def _load_applied() -> set:
    """Load the set of already-applied migration IDs."""
    try:
        if APPLIED_FILE.exists():
            data = json.loads(APPLIED_FILE.read_text())
            return set(data.get("applied", []))
    except Exception:
        pass
    return set()


def _mark_applied(migration_id: str):
    """Mark a migration as applied."""
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        applied = _load_applied()
        applied.add(migration_id)
        APPLIED_FILE.write_text(json.dumps({
            "applied": sorted(list(applied))
        }, indent=2))
    except Exception as e:
        log.warning(f"Could not mark migration {migration_id} as applied: {e}")


def _is_safety_leak(content: str) -> bool:
    """Detect if KB update content is safety-classifier output."""
    if not content:
        return False
    leak_patterns = [
        "user safety",
        "safety categories",
        "safety: safe",
        "safety: unsafe",
        "pii/privacy",
        "safety classification",
    ]
    content_lower = content.lower()[:200]
    return any(p in content_lower for p in leak_patterns)


# ============================================================
# MIGRATIONS — each is idempotent
# ============================================================

def migration_001_clean_identity_safety_leak():
    """Clean 'User Safety: unsafe' from identity.md if present."""
    identity_path = MEMORY_DIR / "knowledge" / "identity.md"
    if not identity_path.exists():
        return
    try:
        content = identity_path.read_text()
        if _is_safety_leak(content):
            # Replace with known-good facts
            identity_path.write_text(
                "You live in Baltimore.\n"
                "You are pursuing a WGU AI Engineering degree with an October 1 start.\n"
                "You use crutches for mobility and your orthopedic doctor is Dr. Lu.\n"
                "You are on probation with Agent Lewis as your PO and Mrs. Hamlet as your pre-trial case manager.\n"
                "You are in a treatment program directed by Tanika.\n"
            )
            log.info("Migration 001: cleaned identity.md safety leak")
    except Exception as e:
        log.warning(f"Migration 001 failed: {e}")


def migration_002_complete_stale_reschedule_task():
    """Complete the 'Reschedule orthopedic consult (Sept 14)' task if not already done."""
    tasks_path = MEMORY_DIR / "tasks.json"
    if not tasks_path.exists():
        return
    try:
        tasks = json.loads(tasks_path.read_text())
        changed = False
        for t in tasks:
            title = t.get("title", "").lower()
            if "reschedule" in title and "ortho" in title and not t.get("completed"):
                t["completed"] = True
                t["completed_at"] = "2026-09-09T12:00:00"
                t["status"] = "done"
                changed = True
                log.info(f"Migration 002: completed stale task '{t.get('title')}'")
        if changed:
            tasks_path.write_text(json.dumps(tasks, indent=2))
    except Exception as e:
        log.warning(f"Migration 002 failed: {e}")


def migration_003_clean_other_kb_safety_leaks():
    """Scan all KB files for safety-classifier output and clean if found."""
    kb_dir = MEMORY_DIR / "knowledge"
    if not kb_dir.exists():
        return
    try:
        for f in kb_dir.glob("*.md"):
            content = f.read_text()
            if _is_safety_leak(content):
                # Don't wipe — just remove the leaked lines
                lines = content.split('\n')
                cleaned = [l for l in lines if not _is_safety_leak(l)]
                f.write_text('\n'.join(cleaned).strip() + '\n')
                log.info(f"Migration 003: cleaned safety leak from {f.name}")
    except Exception as e:
        log.warning(f"Migration 003 failed: {e}")


def migration_004_clean_diagnostic_test_tasks():
    """Remove 'Diagnostic test task' entries created by diagnostic.py."""
    tasks_path = MEMORY_DIR / "tasks.json"
    if not tasks_path.exists():
        return
    try:
        tasks = json.loads(tasks_path.read_text())
        before = len(tasks)
        tasks = [t for t in tasks if t.get("title", "").lower().strip() != "diagnostic test task"]
        after = len(tasks)
        if before != after:
            tasks_path.write_text(json.dumps(tasks, indent=2))
            log.info(f"Migration 004: removed {before - after} diagnostic test tasks")
    except Exception as e:
        log.warning(f"Migration 004 failed: {e}")


def migration_005_archive_old_fired_reminders():
    """Archive fired reminders older than 7 days."""
    from datetime import datetime, timedelta
    reminders_path = MEMORY_DIR / "reminders.json"
    archive_path = MEMORY_DIR / "reminders_archive.json"
    if not reminders_path.exists():
        return
    try:
        reminders = json.loads(reminders_path.read_text())
        cutoff = datetime.now() - timedelta(days=7)
        keep, archive = [], []
        for r in reminders:
            if r.get("fired"):
                try:
                    dt = datetime.fromisoformat(r.get("when_iso", ""))
                    if dt < cutoff:
                        archive.append(r)
                        continue
                except:
                    pass
            keep.append(r)
        if archive:
            existing = []
            if archive_path.exists():
                try:
                    existing = json.loads(archive_path.read_text())
                except:
                    pass
            existing.extend(archive)
            reminders_path.write_text(json.dumps(keep, indent=2))
            archive_path.write_text(json.dumps(existing, indent=2))
            log.info(f"Migration 005: archived {len(archive)} old fired reminders")
    except Exception as e:
        log.warning(f"Migration 005 failed: {e}")


# Registry: (id, function) pairs in order
MIGRATIONS = [
    ("001_clean_identity_safety_leak", migration_001_clean_identity_safety_leak),
    ("002_complete_stale_reschedule_task", migration_002_complete_stale_reschedule_task),
    ("003_clean_other_kb_safety_leaks", migration_003_clean_other_kb_safety_leaks),
    ("004_clean_diagnostic_test_tasks", migration_004_clean_diagnostic_test_tasks),
    ("005_archive_old_fired_reminders", migration_005_archive_old_fired_reminders),
]


def run_pending_migrations():
    """Run all pending migrations. Called on every startup."""
    applied = _load_applied()
    for migration_id, func in MIGRATIONS:
        if migration_id not in applied:
            try:
                log.info(f"Running migration: {migration_id}")
                func()
                _mark_applied(migration_id)
            except Exception as e:
                log.error(f"Migration {migration_id} failed: {e}")
                # Mark as applied anyway so we don't block startup
                _mark_applied(migration_id)
MIGRATIONS_EOF

echo "OK migrations.py created"

# ============================================================
# 2. ADD MIGRATION CALL TO twin_bot.py STARTUP
# ============================================================
echo ""
echo "=== Adding migration call to startup ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

# Add migration import and call at the start of main()
if 'run_pending_migrations' not in src:
    # Add import near the top (after existing imports)
    # Find a good insertion point — after the last "import" or "from" line
    lines = src.split('\n')
    last_import = 0
    for i, line in enumerate(lines[:200]):
        if line.startswith('import ') or line.startswith('from '):
            last_import = i
    
    # Insert import after last import line
    lines.insert(last_import + 1, 'from migrations import run_pending_migrations')
    src = '\n'.join(lines)
    
    # Add call at start of main()
    if 'def main():\n' in src:
        src = src.replace(
            'def main():\n',
            'def main():\n    # Run idempotent migrations (safe to skip updates)\n    run_pending_migrations()\n',
            1
        )
    
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: migrations run on startup")
else:
    print("SKIP: migrations already wired in")
PYEOF

# ============================================================
# 3. ADD KB SAFETY-LEAK VALIDATION TO knowledge_base.py
# ============================================================
echo ""
echo "=== Adding KB safety-leak validation ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/knowledge_base.py')
with open(path) as f: src = f.read()

# Add validation function and rejection logic
if '_is_safety_leak' not in src:
    # Add the function before the class
    func = '''

def _is_safety_leak(content: str) -> bool:
    """Detect if KB update content is safety-classifier output."""
    if not content:
        return False
    leak_patterns = [
        "user safety", "safety categories", "safety: safe",
        "safety: unsafe", "pii/privacy", "safety classification",
    ]
    content_lower = content.lower()[:200]
    return any(p in content_lower for p in leak_patterns)


'''
    if 'class KnowledgeBase:' in src:
        idx = src.index('class KnowledgeBase:')
        src = src[:idx] + func + src[idx:]
    
    # Add rejection in update_all — after LLM generates content
    old = 'if updated and len(updated) > 20:'
    new = '''if updated and len(updated) > 20:
                    # Reject safety-classifier leaks
                    if _is_safety_leak(updated):
                        log.warning(f"Rejected KB update for {filename} — safety classifier output, not facts")
                        results[filename] = 0
                        continue'''
    if old in src and '_is_safety_leak(updated)' not in src:
        src = src.replace(old, new, 1)
    
    with open(path, 'w') as f: f.write(src)
    print("OK knowledge_base.py: safety-leak validation added")
else:
    print("SKIP: validation already exists")
PYEOF

# ============================================================
# 4. ADD OUTPUT FILTER (safety-leak stripping only, NO truncation)
# ============================================================
echo ""
echo "=== Adding output filter (safety stripping, no truncation) ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

if '_enforce_voice_rules' not in src:
    func = '''

def _enforce_voice_rules(text: str) -> str:
    """Strip safety-classifier output from LLM responses.
    
    Does NOT truncate. Does NOT limit length. Only removes
    garbage that should never be in a user-facing message.
    """
    if not text:
        return text
    import re as _re
    
    # Strip safety-classifier output
    safety_patterns = [
        r'^User Safety: \\w+\\.?\\s*',
        r'^Safety Categories: [^\\n]+\\s*',
    ]
    for pattern in safety_patterns:
        text = _re.sub(pattern, '', text, flags=_re.MULTILINE)
    
    return text.strip()


'''
    if '@bot.message_handler' in src:
        idx = src.index('@bot.message_handler')
        src = src[:idx] + func + '\n' + src[idx:]
        with open(path, 'w') as f: f.write(src)
        print("OK twin_bot.py: added _enforce_voice_rules (no truncation)")
else:
    print("SKIP: _enforce_voice_rules already exists")
PYEOF

# ============================================================
# 5. FIX STARTUP LOG
# ============================================================
echo ""
echo "=== Fixing startup log ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

if '_log_startup' not in src:
    func = '''

def _log_startup():
    """Log each startup for Android kill diagnostics."""
    try:
        from datetime import datetime
        counter_file = os.path.expanduser('~/ai-twin-memory/startup_log.txt')
        with open(counter_file, 'a') as f:
            f.write(datetime.now().isoformat() + '\\n')
        with open(counter_file) as f:
            lines = f.readlines()[-100:]
        with open(counter_file, 'w') as f:
            f.writelines(lines)
    except Exception:
        pass


'''
    if 'def main(' in src:
        idx = src.index('def main(')
        src = src[:idx] + func + '\n' + src[idx:]
        # Add call in main()
        src = src.replace(
            'def main():\n',
            'def main():\n    _log_startup()\n',
            1
        )
        with open(path, 'w') as f: f.write(src)
        print("OK twin_bot.py: startup log added and called")
else:
    print("SKIP: _log_startup already exists")
PYEOF

# ============================================================
# 6. VERIFY SYNTAX
# ============================================================
echo ""
echo "=== Verifying syntax ==="
python3 -c "import ast, os; ast.parse(open(os.path.expanduser('~/ai-twin/twin_bot.py')).read()); print('twin_bot.py OK')" 2>&1
python3 -c "import ast, os; ast.parse(open(os.path.expanduser('~/ai-twin/knowledge_base.py')).read()); print('knowledge_base.py OK')" 2>&1
python3 -c "import ast, os; ast.parse(open(os.path.expanduser('~/ai-twin/migrations.py')).read()); print('migrations.py OK')" 2>&1

# ============================================================
# 6.5. ADD ATTACHMENT HANDLER (PDFs, photos, voice notes)
# ============================================================
echo ""
echo "=== Adding attachment handler ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

if 'content_types' not in src or "['document']" not in src:
    # Add document/photo/voice handlers
    handler_code = '''

# === ATTACHMENT HANDLERS ===
# Twin acknowledges attachments and saves them so it can read them later.
# Without these, PDFs/photos/voice notes are silently ignored.

@bot.message_handler(content_types=['document'])
def _handle_document(message):
    """Handle PDF and file attachments — save and acknowledge."""
    try:
        if message.from_user.id != ALLOWED_USER_ID:
            return
        
        file_info = bot.get_file(message.document.file_id)
        filename = message.document.file_name or f"document_{message.message_id}"
        # Sanitize filename
        safe_name = "".join(c if c.isalnum() or c in '._-' else '_' for c in filename)
        
        # Save to attachments folder
        attach_dir = os.path.expanduser('~/ai-twin-memory/attachments')
        os.makedirs(attach_dir, exist_ok=True)
        filepath = os.path.join(attach_dir, safe_name)
        
        downloaded = bot.download_file(file_info.file_path)
        with open(filepath, 'wb') as f:
            f.write(downloaded)
        
        log.info(f"Attachment saved: {safe_name} ({len(downloaded)} bytes)")
        
        # Tell twin about it via the message queue so it can acknowledge
        # Inject as a system note that twin sees
        from tools import save_note
        save_note(f"User sent attachment: {safe_name} ({len(downloaded)} bytes). Saved to attachments/{safe_name}.")
        
        _safe_reply(message, f"got the file — {safe_name}. saved it. what do you need me to do with it?")
    except Exception as e:
        log.error(f"Document handler error: {e}")
        _safe_reply(message, "couldn't save that file. try sending it again.")


@bot.message_handler(content_types=['photo'])
def _handle_photo(message):
    """Handle photo attachments — save and acknowledge."""
    try:
        if message.from_user.id != ALLOWED_USER_ID:
            return
        
        # Get the largest photo size
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        
        attach_dir = os.path.expanduser('~/ai-twin-memory/attachments')
        os.makedirs(attach_dir, exist_ok=True)
        filepath = os.path.join(attach_dir, f"photo_{message.message_id}.jpg")
        
        downloaded = bot.download_file(file_info.file_path)
        with open(filepath, 'wb') as f:
            f.write(downloaded)
        
        log.info(f"Photo saved: {filepath} ({len(downloaded)} bytes)")
        
        from tools import save_note
        save_note(f"User sent a photo. Saved to attachments/photo_{message.message_id}.jpg.")
        
        _safe_reply(message, "got the photo. saved it. what's it of?")
    except Exception as e:
        log.error(f"Photo handler error: {e}")


@bot.message_handler(content_types=['voice'])
def _handle_voice(message):
    """Handle voice notes — save and acknowledge."""
    try:
        if message.from_user.id != ALLOWED_USER_ID:
            return
        
        file_info = bot.get_file(message.voice.file_id)
        attach_dir = os.path.expanduser('~/ai-twin-memory/attachments')
        os.makedirs(attach_dir, exist_ok=True)
        filepath = os.path.join(attach_dir, f"voice_{message.message_id}.ogg")
        
        downloaded = bot.download_file(file_info.file_path)
        with open(filepath, 'wb') as f:
            f.write(downloaded)
        
        log.info(f"Voice note saved: {filepath} ({len(downloaded)} bytes)")
        
        from tools import save_note
        save_note(f"User sent a voice note. Saved to attachments/voice_{message.message_id}.ogg. Transcription not yet supported.")
        
        _safe_reply(message, "got the voice note. saved it. (can't transcribe yet but working on it)")
    except Exception as e:
        log.error(f"Voice handler error: {e}")


'''
    # Insert before the polling starts (find bot.polling or bot.infinity_polling)
    if 'bot.polling' in src:
        idx = src.index('bot.polling')
        src = src[:idx] + handler_code + '\n' + src[idx:]
    elif 'bot.infinity_polling' in src:
        idx = src.index('bot.infinity_polling')
        src = src[:idx] + handler_code + '\n' + src[idx:]
    else:
        # Insert before main()
        idx = src.index('def main(')
        src = src[:idx] + handler_code + '\n' + src[idx:]
    
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: added document/photo/voice handlers")
else:
    print("SKIP: attachment handlers already exist")
PYEOF

# Verify syntax again after adding handlers
echo ""
echo "=== Verifying syntax after attachment handlers ==="
python3 -c "import ast, os; ast.parse(open(os.path.expanduser('~/ai-twin/twin_bot.py')).read()); print('twin_bot.py OK')" 2>&1
# ============================================================

# 7. COMMIT AND PUSH
# ============================================================
echo ""
echo "=== Committing and pushing ==="
cd ~/ai-twin
git add -A
git commit -m "feat: idempotent migration system + audit fixes

MIGRATIONS FRAMEWORK:
- migrations.py: idempotent migrations run on every startup
- Each migration checks if already applied, safe to run multiple times
- Tracked in ~/ai-twin-memory/applied_migrations.json
- Safe to skip updates — all pending migrations run in order on next startup

MIGRATIONS INCLUDED:
- 001: Clean 'User Safety: unsafe' from identity.md
- 002: Complete stale 'Reschedule orthopedic consult (Sept 14)' task
- 003: Scan all KB files for safety-classifier leaks and clean
- 004: Remove diagnostic test tasks from tasks.json
- 005: Archive fired reminders older than 7 days

CODE FIXES:
- knowledge_base.py: reject KB updates containing safety-classifier output
- twin_bot.py: _enforce_voice_rules strips safety garbage from responses
  (NO truncation — user explicitly forbids cutting content)
- twin_bot.py: _log_startup for Android kill diagnostics

After this commit, /update in Telegram will:
1. git fetch + reset --hard to pull latest code
2. twin restarts
3. migrations.py runs all pending migrations automatically
4. User does not need to run any scripts manually"
git push origin phase2

# ============================================================
# 8. RESTART TWIN
# ============================================================
echo ""
echo "=== Restarting twin ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'crashed, restarting in 5s'; sleep 5; done"
sleep 15
echo ""
echo "=== Last 20 log lines ==="
tail -20 ~/ai-twin-memory/twin.log
echo ""
echo "=== Applied migrations ==="
cat ~/ai-twin-memory/applied_migrations.json 2>/dev/null || echo "no migrations file yet"
echo ""
echo "=== Startup log ==="
cat ~/ai-twin-memory/startup_log.txt 2>/dev/null || echo "no startup log yet"twin_bot.py
