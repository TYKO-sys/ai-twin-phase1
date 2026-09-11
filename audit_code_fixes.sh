#!/data/data/com.termux/files/usr/bin/bash
set -e
cd ~/ai-twin

echo "=== AUDIT CODE FIXES — $(date) ==="

BACKUP=~/ai-twin-backups/code-fixes-$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP"
cp twin_bot.py tools.py knowledge_base.py "$BACKUP/" 2>/dev/null || true
echo "Backed up to $BACKUP"

# FIX #2 + #10: KB prompts leak personality into knowledge base
echo ""
echo "=== Fix #2 + #10: KB prompts store facts not personality ==="
python3 <<'PYEOF'
import os, re
path = os.path.expanduser('~/ai-twin/knowledge_base.py')
with open(path) as f: src = f.read()

OLD_ID = '''Update your understanding of who TYKO IS at their core.

This is about WHO they are, not WHAT happened to them.

RULES:
- Keep only traits that have shown up CONSISTENTLY across multiple days, not single occurrences.
- If something was observed only once, do NOT include it as a trait. One bad day doesn't define someone.
- Remove traits that no longer seem accurate.
- Write in second person: "You are..." not "They are..."
- MAXIMUM 3 sentences. No more. This is the essence, not a biography.
- If nothing changed about their core identity, keep the existing text and just update the date.

Write the updated identity now:'''

NEW_ID = '''Update the USER'S IDENTITY — facts about who Michael Mazique is.

This is FACTS about the USER, NOT descriptions of yourself (the twin).
NEVER write "You are a twin" or "You are an AI" or any description of yourself.
ONLY write facts like: "You live in Baltimore" / "You are pursuing a WGU degree" / "You use crutches".

RULES:
- Store only CONCRETE FACTS about the user's life (location, occupation, health, education, legal status).
- NEVER describe the twin's personality or role.
- NEVER write "You are supportive" / "You are action-oriented".
- Keep only facts that have been CONSISTENTLY mentioned across multiple days.
- Write in second person: "You live in..." not "Michael lives in..."
- MAXIMUM 5 facts. One per line. No paragraphs.

Output ONLY the updated identity facts:'''
src = src.replace(OLD_ID, NEW_ID)

OLD_PAT = '''Update behavioral patterns.

CRITICAL RULE:
- A pattern must be observed AT LEAST 3 TIMES across different days to be included.
- ONE occurrence is NOT a pattern. If you've only seen something once, do NOT add it.
- If a pattern was based on only 1-2 observations, REMOVE it.
- Patterns are about HOW you approach things, not WHAT happened.

RULES:
- MAXIMUM 5 patterns. Remove the least relevant if you have more.
- Each pattern: ONE sentence describing the behavior + ONE sentence on what helps.
- Do NOT include triggers, evidence lists, or detailed analysis. Just the pattern.
- Remove patterns that no longer apply.
- Write in second person: "You tend to..." not "The user tends to..."

Write the updated patterns now:'''

NEW_PAT = '''Update PATTERNS — the USER'S observed behaviors (not the twin's).

These are PATTERNS IN THE USER'S LIFE, NOT descriptions of the twin.
NEVER write "You are resilient" / "You thrive under pressure".
ONLY write: "You tend to juggle multiple tasks" / "You respond well to short reminders".

CRITICAL RULE:
- A pattern must be observed AT LEAST 3 TIMES across different days.
- ONE occurrence is NOT a pattern.

RULES:
- MAXIMUM 5 patterns. One sentence each.
- NEVER describe the twin. NEVER write "You are [adjective]".
- Remove patterns that no longer apply.

Output ONLY the updated patterns:'''
src = src.replace(OLD_PAT, NEW_PAT)

OLD_SYS = '"You are updating your own knowledge of someone you know well. Be accurate, specific, honest, and brief. Write in second person."'
NEW_SYS = '"You are updating a knowledge base of FACTS about the user. Store only concrete facts, dates, and observed behaviors. NEVER describe yourself (the twin) or write personality statements. Be accurate, specific, honest, brief. Write in second person addressing the user."'
src = src.replace(OLD_SYS, NEW_SYS)

with open(path, 'w') as f: f.write(src)
print("OK knowledge_base.py patched")
PYEOF

# Force-clean leaked KB data (uses search not match)
echo ""
echo "=== Force-clean leaked personality text from KB ==="
python3 <<'PYEOF'
import os, re
KB_DIR = os.path.expanduser('~/ai-twin-memory/knowledge')
LEAK_PATTERNS = [
    r'You are a (supportive|casual|resilient|action-oriented|protective|concrete|practical|steadfast)',
    r'You are (an? )?(AI twin|external brain|ally)',
    r'You move fastest',
    r'You tend to juggle',
    r'You rely on external prompts',
    r'You work best with',
    r'You feel overwhelmed facing',
    r'You respond well to (direct|gentle)',
    r'Structured, prioritized guidance amplifies',
    r'Through daily interaction, you serve',
]
LEAK_RE = re.compile('|'.join(LEAK_PATTERNS))
META_RE = re.compile(r'\[Updated [^\]]+\]:?\s*')

for fname in os.listdir(KB_DIR):
    if not fname.endswith('.md'): continue
    path = os.path.join(KB_DIR, fname)
    with open(path) as f: content = f.read()
    original = content
    lines = content.split('\n')
    cleaned = []
    removed = 0
    for line in lines:
        if LEAK_RE.search(line):
            removed += 1
            continue
        line = META_RE.sub('', line)
        cleaned.append(line)
    new_content = '\n'.join(cleaned)
    while '\n\n\n' in new_content:
        new_content = new_content.replace('\n\n\n', '\n\n')
    new_content = new_content.strip() + '\n'
    if new_content != original:
        with open(path, 'w') as f: f.write(new_content)
        print(f"  {fname}: removed {removed} leaked lines")
    else:
        print(f"  {fname}: already clean")
PYEOF

# FIX #4: Phone lock heartbeat graceful degradation
echo ""
echo "=== Fix #4: heartbeat disables after 3 auth failures ==="
python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

OLD = '''def _update_phone_heartbeat():
    """Update the gist with a fresh heartbeat."""
    if not _gist_id or not _github_token:
        return

    try:
        content = json.dumps({"phone_id": _phone_id, "timestamp": time.time()})
        resp = requests.patch(
            f"https://api.github.com/gists/{_gist_id}",
            headers={
                "Authorization": f"token {_github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"files": {"lock.json": {"content": content}}},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning(f"Failed to update heartbeat: {resp.status_code}")
    except Exception as e:
        log.warning(f"Error updating heartbeat: {e}")


def _phone_lock_heartbeat_loop():
    """Background thread that sends a heartbeat every 5 minutes."""
    while True:
        time.sleep(300)  # 5 minutes
        _update_phone_heartbeat()'''

NEW = '''_heartbeat_fail_count = 0
_heartbeat_disabled = False


def _update_phone_heartbeat():
    """Update the gist with a fresh heartbeat. Disables itself after repeated 403s."""
    global _heartbeat_fail_count, _heartbeat_disabled
    if not _gist_id or not _github_token or _heartbeat_disabled:
        return

    try:
        content = json.dumps({"phone_id": _phone_id, "timestamp": time.time()})
        resp = requests.patch(
            f"https://api.github.com/gists/{_gist_id}",
            headers={
                "Authorization": f"token {_github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"files": {"lock.json": {"content": content}}},
            timeout=15,
        )
        if resp.status_code == 200:
            _heartbeat_fail_count = 0
            return
        if resp.status_code in (403, 401):
            _heartbeat_fail_count += 1
            log.warning(f"Heartbeat auth failed ({resp.status_code}) - attempt {_heartbeat_fail_count}/3")
            if _heartbeat_fail_count >= 3:
                _heartbeat_disabled = True
                try:
                    failed_path = Path.home() / "ai-twin-memory" / "gist_failed.txt"
                    failed_path.parent.mkdir(parents=True, exist_ok=True)
                    failed_path.write_text(f"heartbeat_disabled_{resp.status_code}", encoding="utf-8")
                except Exception:
                    pass
                log.warning("Phone lock heartbeat disabled after 3 auth failures. To re-enable: regenerate GitHub PAT with gist scope, delete ~/ai-twin-memory/gist_failed.txt and restart twin.")
        else:
            log.warning(f"Failed to update heartbeat: {resp.status_code}")
    except Exception as e:
        log.warning(f"Error updating heartbeat: {e}")


def _phone_lock_heartbeat_loop():
    """Background thread that sends a heartbeat every 5 minutes.
    Disables itself after 3 consecutive auth failures (403/401)."""
    while True:
        time.sleep(300)
        if _heartbeat_disabled:
            return
        _update_phone_heartbeat()'''

if OLD in src:
    src = src.replace(OLD, NEW)
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: heartbeat patched")
else:
    print("SKIP twin_bot.py: heartbeat pattern not found")
PYEOF

# FIX #7: Location (0,0) detection
echo ""
echo "=== Fix #7: location (0,0) detection ==="
python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

OLD = '''def _location_logging_loop():
    """Background thread that logs GPS location every 15 minutes.

    Builds a pattern over time so the twin can infer where the user is
    without calling GPS every time (see tool_infer_location). Only logs
    during waking hours (7am-10pm) to save battery. Failures are logged
    and swallowed — this thread must never crash the bot.
    """
    from tools import tool_get_current_location
    log.info("Location logging started (checks every 15 minutes)")

    while True:
        time.sleep(900)  # 15 minutes
        try:
            now = datetime.now()
            if now.hour < 7 or now.hour > 22:
                continue

            result = tool_get_current_location()
            if "Location:" in result:
                log.info(f"Location logged: {result[:80]}")
        except Exception as e:
            log.error(f"Location logging error: {e}")'''

NEW = '''def _location_logging_loop():
    """Background thread that logs GPS location every 15 minutes.

    Detects (0,0) returns and surfaces a one-time notification so the user
    knows location is silently broken (GPS off, permission missing, or
    airplane mode).
    """
    from tools import tool_get_current_location
    log.info("Location logging started (checks every 15 minutes)")

    _loc_fail_count = 0
    _loc_notified = False

    while True:
        time.sleep(900)
        try:
            now = datetime.now()
            if now.hour < 7 or now.hour > 22:
                continue

            result = tool_get_current_location()
            if "Location:" in result:
                if "lat=0, lon=0" in result or "location unavailable" in result.lower():
                    _loc_fail_count += 1
                    log.warning(f"Location unavailable ({_loc_fail_count}x). GPS may be off or permission missing.")
                    if _loc_fail_count >= 3 and not _loc_notified:
                        notified_path = Path.home() / "ai-twin-memory" / "location_notified.txt"
                        if not notified_path.exists():
                            try:
                                _send_telegram_message(
                                    "Location access seems broken (returning 0,0). "
                                    "If you want location features, run: termux-setup-location "
                                    "and enable GPS in Android settings."
                                )
                                notified_path.write_text("notified", encoding="utf-8")
                                _loc_notified = True
                            except Exception:
                                pass
                else:
                    _loc_fail_count = 0
                    log.info(f"Location logged: {result[:80]}")
        except Exception as e:
            log.error(f"Location logging error: {e}")'''

if OLD in src:
    src = src.replace(OLD, NEW)
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: location patched")
else:
    print("SKIP twin_bot.py: location pattern not found")
PYEOF

# FIX #8: set_reminder stores due date in separate field
echo ""
echo "=== Fix #8: set_reminder no longer embeds due in what ==="
python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/tools.py')
with open(path) as f: src = f.read()

OLD = '''        # FIX (TWIN-REMINDER-LOGGING-FIX-1): Embed the ABSOLUTE due date
        # into the `what` text so that, when the reminder fires, the LLM
        # sees "call northern pharmacy (due: Tuesday, September 09 at
        # 09:00 AM)" instead of the raw relative phrase ("tomorrow
        # morning"). Without this, the twin would read "tomorrow morning"
        # back verbatim at fire time -- even if it is now THIS morning --
        # and say "tomorrow" again. With the absolute date baked in, the
        # LLM can compute the correct relative term (today / tomorrow /
        # in 2 hours) from the due date + current time context.
        what_with_date = (
            f"{what} "
            f"(due: {target_time.strftime('%A, %B %d at %I:%M %p')})"
        )

        reminder = {
            "what": what_with_date,
            "when_iso": target_time.isoformat(),
            "when_display": target_time.strftime("%a %I:%M %p"),
            "created": now.isoformat(),
            "fired": False,
        }'''

NEW = '''        # Store the absolute due date in a SEPARATE field so the LLM
        # can compute relative time at fire time without the reminder
        # text itself containing "(due: ...)" noise.
        reminder = {
            "what": what,
            "due_display": target_time.strftime('%A, %B %d at %I:%M %p'),
            "when_iso": target_time.isoformat(),
            "when_display": target_time.strftime("%a %I:%M %p"),
            "created": now.isoformat(),
            "fired": False,
        }'''

if OLD in src:
    src = src.replace(OLD, NEW)
    with open(path, 'w') as f: f.write(src)
    print("OK tools.py: set_reminder patched")
else:
    print("SKIP tools.py: reminder pattern not found")
PYEOF

# Clean existing reminders.json
echo ""
echo "=== Clean existing reminders of embedded due text ==="
python3 <<'PYEOF'
import json, re, os
path = os.path.expanduser('~/ai-twin-memory/reminders.json')
with open(path) as f: reminders = json.load(f)
cleaned = 0
for r in reminders:
    what = r.get('what', '')
    m = re.search(r'\s*\(due: [^)]+\)\s*$', what)
    if m:
        r['what'] = what[:m.start()].strip()
        if 'due_display' not in r:
            due_text = what[m.start():m.end()].strip().replace('(due: ', '').replace(')', '').strip()
            r['due_display'] = due_text
        cleaned += 1
with open(path, 'w') as f: json.dump(reminders, f, indent=2)
print(f"Cleaned {cleaned} reminders")
PYEOF

# Commit and push
echo ""
echo "=== Committing and pushing ==="
git add -A
git commit -m "fix(audit): KB personality leak, heartbeat 403 spam, location 0,0, reminder due text

- knowledge_base.py: rewrite identity/patterns prompts to forbid personality descriptions of the twin, only store user facts
- twin_bot.py: heartbeat disables after 3 consecutive 403/401 failures, writes gist_failed marker
- twin_bot.py: location loop detects (0,0) returns and surfaces one-time notification
- tools.py: set_reminder stores due date in separate field instead of embedding in what text
- KB data: cleaned leaked 'You are...' lines from identity.md and patterns.md
- reminders.json: stripped embedded '(due: ...)' text from existing reminders"
git push origin phase2

echo ""
echo "=== Restarting twin ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'crashed, restarting in 5s'; sleep 5; done"
sleep 15
echo ""
echo "=== Last 15 log lines ==="
tail -15 ~/ai-twin-memory/twin.log
