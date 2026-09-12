#!/data/data/com.termux/files/usr/bin/bash
set -e
cd ~/ai-twin

echo "=== Location (0,0) detection patch ==="

python3 <<'PYEOF'
import os, re

path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

# Check if already patched
if '_loc_fail_count' in src:
    print("SKIP: location loop already patched (has _loc_fail_count)")
    import sys
    sys.exit(0)

# Find the location loop by its signature, replace the whole function
# Use regex with flexible whitespace
pattern = re.compile(
    r'def _location_logging_loop\(\):.*?log\.error\(f"Location logging error: \{e\}"\)',
    re.DOTALL
)

new_func = '''def _location_logging_loop():
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

match = pattern.search(src)
if match:
    src = src[:match.start()] + new_func + src[match.end():]
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: location loop patched")
else:
    print("FAIL: could not find _location_logging_loop function")
    import sys
    sys.exit(1)
PYEOF

# Verify
echo ""
echo "=== Verifying ==="
grep -c "_loc_fail_count" ~/ai-twin/twin_bot.py

# Commit and push
echo ""
echo "=== Committing ==="
git add twin_bot.py
git commit -m "fix(audit): location loop detects (0,0) and notifies user

Previous fix didn't land due to whitespace mismatch in pattern match.
Uses regex match now to be tolerant of whitespace differences."
git push origin phase2

echo ""
echo "=== Restarting twin ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo 'crashed, restarting in 5s'; sleep 5; done"
sleep 15
tail -10 ~/ai-twin-memory/twin.log
