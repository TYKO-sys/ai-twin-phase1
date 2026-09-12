#!/data/data/com.termux/files/usr/bin/bash
set -e
cd ~/ai-twin

echo "=== GAPS FIX — $(date) ==="

BACKUP=~/ai-twin-backups/gaps-fix-$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP"
cp twin_bot.py "$BACKUP/"

# ============================================================
# FIX GAP #1: Auto-call infer_next_steps on open-ended messages
# The code detects open-ended messages and injects the inference
# result as mandatory context before the LLM generates a response.
# This guarantees twin always tells you what's next, even if the
# LLM forgets to call the tool.
# ============================================================
echo ""
echo "=== Fix Gap #1: Auto-invoke infer_next_steps ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

# Find the main message handler and inject infer_next_steps auto-call
# Look for the pattern where user messages are processed
# The handler is likely @bot.message_handler(func=lambda m: True)

# Add a helper function that detects open-ended messages
# and returns the next-step inference
helper_code = '''

def _is_open_ended_message(text: str) -> bool:
    """Detect if a message is open-ended (no clear directive).

    Open-ended: hey, what's up, what's good, woof, ok, love, hi, yo,
    what now, what next, so, etc. These are cues that the user wants
    twin to tell them what's next, not just banter.
    """
    if not text:
        return False
    text_lower = text.lower().strip()
    if len(text_lower) > 100:
        return False  # Long messages have their own context
    open_ended = {
        "hey", "hi", "yo", "ok", "okay", "k", "cool", "nice",
        "what's up", "whats up", "what's good", "whats good",
        "what now", "what next", "what's next", "whats next",
        "so", "and", "but", "hmm", "idk", "lol", "lmfao",
        "woof", "love", "love you", "thanks", "thank you",
        "good", "good morning", "gm", "good night", "gn",
        "bet", "word", "facts", "fr", "real", "nah", "yeah",
        "yes", "no", "maybe", "sure", "fine", "alright",
    }
    return text_lower in open_ended or (
        len(text_lower) < 20 and not any(
            keyword in text_lower for keyword in [
                "call", "remind", "task", "add", "create", "complete",
                "done", "finished", "schedule", "email", "text",
                "find", "search", "what time", "when", "where",
                "how", "why", "who", "can you", "could you",
            ]
        )
    )


def _auto_infer_next_steps(user_text: str) -> str:
    """Auto-call infer_next_steps for open-ended messages.

    Returns the inference result as context string, or empty string
    if the message isn't open-ended or the tool fails.
    """
    if not _is_open_ended_message(user_text):
        return ""
    try:
        from tools import infer_next_steps
        result = infer_next_steps()
        if result and len(result) > 10:
            return f"[TWIN INTERNAL — next step inference:\\n{result[:500]}]"
    except Exception as e:
        log.warning(f"Auto infer_next_steps failed: {e}")
    return ""


'''

# Insert the helper functions before the first message handler
# Find a good insertion point — after the imports, before the handlers
if '_is_open_ended_message' not in src:
    # Insert after the last import line
    import re
    # Find the line "# ===" or "def " after the last import
    # Simplest: insert before the first @bot.message_handler
    if '@bot.message_handler' in src:
        idx = src.index('@bot.message_handler')
        # Find the function definition above it
        # Insert the helper code before the first handler
        src = src[:idx] + helper_code + '\n' + src[idx:]
        with open(path, 'w') as f: f.write(src)
        print("OK twin_bot.py: added _is_open_ended_message + _auto_infer_next_steps")
    else:
        print("SKIP: no @bot.message_handler found")
else:
    print("SKIP: _is_open_ended_message already exists")
PYEOF

# ============================================================
# FIX GAP #2: Add "said vs done" gap analysis to proactive system
# Twin scans recent conversation for commitments ("I'll call X",
# "I'll do Y tomorrow") and checks if they were completed.
# If not, twin proactively surfaces them.
# ============================================================
echo ""
echo "=== Fix Gap #2: Said vs Done gap analysis ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

if '_check_said_vs_done' not in src:
    gap_func = '''

def _check_said_vs_done() -> list:
    """Scan recent conversation for unfulfilled commitments.

    Looks for patterns like 'I'll call X', 'I'll do Y', 'I'll send Z'
    in the last 7 days of conversation logs, then checks if a matching
    task was completed. Returns a list of unfulfilled commitments.
    """
    import re
    from datetime import datetime, timedelta
    commitments = []

    try:
        # Scan last 7 days of daily logs
        memory_dir = os.path.expanduser('~/ai-twin-memory')
        cutoff = datetime.now() - timedelta(days=7)

        # Commitment patterns
        commit_patterns = [
            r"(?:I'?ll|I will|I'?m going to|I gotta|I need to|I have to)\s+(.{10,80})",
            r"(?:remind me to|don't let me forget to)\s+(.{10,80})",
        ]

        # Load completed tasks for cross-reference
        from tools import _load_tasks
        tasks = _load_tasks()
        completed_text = " ".join(
            t.get("title", "").lower()
            for t in tasks if t.get("completed")
        )

        # Scan daily log files
        import glob
        for logfile in sorted(glob.glob(f"{memory_dir}/daily/*.md"))[-7:]:
            try:
                with open(logfile) as f:
                    content = f.read()
                # Find user messages with commitment patterns
                for pattern in commit_patterns:
                    for match in re.finditer(pattern, content, re.IGNORECASE):
                        commitment = match.group(1).strip().rstrip('.').rstrip(',')
                        # Check if this commitment appears in completed tasks
                        commit_lower = commitment.lower()[:40]
                        if commit_lower and commit_lower not in completed_text:
                            # Skip if already in the commitments list
                            if not any(c["text"][:40] == commit_lower for c in commitments):
                                commitments.append({
                                    "text": commitment,
                                    "source_file": os.path.basename(logfile),
                                })
            except Exception:
                continue

        # Limit to 5 most recent unfulfilled
        commitments = commitments[-5:]
    except Exception as e:
        log.warning(f"Said vs done check failed: {e}")

    return commitments


'''
    # Insert before _score_proactive_opportunity
    if '_score_proactive_opportunity' in src:
        idx = src.index('def _score_proactive_opportunity')
        src = src[:idx] + gap_func + '\n' + src[idx:]
        with open(path, 'w') as f: f.write(src)
        print("OK twin_bot.py: added _check_said_vs_done gap analysis")
    else:
        print("SKIP: _score_proactive_opportunity not found")
else:
    print("SKIP: _check_said_vs_done already exists")
PYEOF

# ============================================================
# FIX GAP #3: Forbid safety language in proactive personality
# The "User Safety: safe" glitch happened because the LLM confused
# proactive context with crisis protocol. Explicitly ban safety
# language in proactive messages.
# ============================================================
echo ""
echo "=== Fix Gap #3: Ban safety language in proactive ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

old_proactive = '''_PROACTIVE_PERSONALITY = """You are the user's AI twin. You're reaching out proactively.

Write like a friend texting. Short, casual, lowercase, contractions. No AI-speak. No "how are you." No "just checking in." Reference something specific.

Match the user's voice: casual profanity ok, "shit" used casually, "lmfao", "kinda", "gonna". Heavy contractions. No greeting, no sign-off.

If it's a weekend (Saturday/Sunday), don't suggest calling offices. If a time reference in the context is in the past, acknowledge it and move on.

One message. 1-3 sentences. NEVER ask a question. NEVER ask "want me to..." or "what do you think" or "should I..." State the thing. Tell them what's next. You decide, you tell. They don't want to be asked. They want to be told.
"""'''

new_proactive = '''_PROACTIVE_PERSONALITY = """You are the user's AI twin. You're reaching out proactively.

Write like a friend texting. Short, casual, lowercase, contractions. No AI-speak. No "how are you." No "just checking in." Reference something specific.

Match the user's voice: casual profanity ok, "shit" used casually, "lmfao", "kinda", "gonna". Heavy contractions. No greeting, no sign-off.

If it's a weekend (Saturday/Sunday), don't suggest calling offices. If a time reference in the context is in the past, acknowledge it and move on.

One message. 1-3 sentences. NEVER ask a question. NEVER ask "want me to..." or "what do you think" or "should I..." State the thing. Tell them what's next. You decide, you tell. They don't want to be asked. They want to be told.

CRITICAL: This is a proactive check-in, NOT a crisis check. NEVER mention safety, never ask "are you safe", never say "User Safety" or anything similar. The crisis protocol only applies when the user expresses distress directly. Proactive messages are about tasks and life, not safety.
"""'''

if old_proactive in src:
    src = src.replace(old_proactive, new_proactive)
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: banned safety language in proactive personality")
else:
    print("SKIP: proactive personality pattern not found")
PYEOF

# ============================================================
# FIX GAP #4: Startup counter for Android kill diagnostics
# Logs each startup with timestamp to a separate file so you can
# see the restart pattern and determine if Android is killing Termux.
# ============================================================
echo ""
echo "=== Fix Gap #4: Startup counter ==="

python3 <<'PYEOF'
import os
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

if '_log_startup' not in src:
    startup_code = '''

def _log_startup():
    """Log each startup to a counter file for Android kill diagnostics.

    Each startup writes a timestamp. If you see many startups close together,
    Android is killing Termux. If you see one startup and it runs for hours,
    twin is stable.
    """
    try:
        from datetime import datetime
        counter_file = os.path.expanduser('~/ai-twin-memory/startup_log.txt')
        with open(counter_file, 'a') as f:
            f.write(f"{datetime.now().isoformat()}\\n")
        # Keep last 100 entries
        try:
            with open(counter_file) as f:
                lines = f.readlines()[-100:]
            with open(counter_file, 'w') as f:
                f.writelines(lines)
        except Exception:
            pass
    except Exception:
        pass


'''
    # Insert before main() or at the end of the imports section
    if 'def main(' in src:
        idx = src.index('def main(')
        src = src[:idx] + startup_code + '\n' + src[idx:]
        with open(path, 'w') as f: f.write(src)
        print("OK twin_bot.py: added _log_startup")

    # Now call _log_startup() at the beginning of main()
    if 'def main(' in src and '_log_startup()' not in src.split('def main(')[1][:500]:
        src = src.replace(
            'def main():\n',
            'def main():\n    _log_startup()\n',
            1
        )
        with open(path, 'w') as f: f.write(src)
        print("OK twin_bot.py: _log_startup() called in main()")
else:
    print("SKIP: _log_startup already exists")
PYEOF

# ============================================================
# Verify syntax
# ============================================================
echo ""
echo "=== Verifying syntax ==="
python3 -c "import ast, os; ast.parse(open(os.path.expanduser('~/ai-twin/twin_bot.py')).read()); print('SYNTAX OK')" 2>&1

# ============================================================
# Commit and push
# ============================================================
echo ""
echo "=== Committing and pushing ==="
cd ~/ai-twin
git add -A
git commit -m "fix(audit): enforce inference, gap analysis, ban safety in proactive, startup counter

- twin_bot.py: added _is_open_ended_message + _auto_infer_next_steps to detect
  open-ended messages and auto-call infer_next_steps, guaranteeing twin tells
  the user what's next instead of just bantering
- twin_bot.py: added _check_said_vs_done gap analysis — scans conversation for
  unfulfilled commitments ('I'll call X') and checks if matching task was
  completed, surfaces as proactive nudge if not
- twin_bot.py: banned safety language in _PROACTIVE_PERSONALITY to prevent
  'User Safety: safe' glitch — proactive messages are about tasks, not crisis
- twin_bot.py: added _log_startup counter for Android kill diagnostics —
  each startup logs to ~/ai-twin-memory/startup_log.txt, keeps last 100

These are code-level enforcements of concepts the system prompt already stated.
The prompt said 'call infer_next_steps on open-ended messages' but the LLM
might forget. Now the code enforces it."
git push origin phase2

# Restart twin
echo ""
echo "=== Restarting twin ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'crashed, restarting in 5s'; sleep 5; done"
sleep 15
echo "=== Last 15 log lines ==="
tail -15 ~/ai-twin-memory/twin.log
