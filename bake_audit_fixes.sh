#!/data/data/com.termux/files/usr/bin/bash
set -e
cd ~/ai-twin

echo "=== Baking audit fixes (v2) ==="

python3 <<'PYEOF'
import os, re
path = os.path.expanduser('~/ai-twin/twin_bot.py')
with open(path) as f: src = f.read()

new_func = '''def _wait_for_freellmapi(timeout_seconds: int = 15):
    """Properly check FreeLLMAPI: socket first, then auth check. Non-blocking."""
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
        resp = session.get("http://127.0.0.1:3001/v1/models", headers=headers, timeout=(5, 10))
        try:
            body = resp.json()
        except Exception:
            logger.warning(f"FreeLLMAPI non-JSON (status {resp.status_code})")
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
        return False
'''

# Match the existing _wait_for_freellmapi function (multi-line signature, body until next def or end)
pattern = re.compile(r'def _wait_for_freellmapi\([^)]*\)[^:]*:.*?(?=\ndef |\Z)', re.DOTALL)
if pattern.search(src):
    src = pattern.sub(new_func + '\n\n', src, count=1)
    with open(path, 'w') as f: f.write(src)
    print("OK twin_bot.py: _wait_for_freellmapi replaced")
else:
    print("SKIP twin_bot.py: function not found")
PYEOF

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
    # DEDUP CHECK
    tasks = _load_tasks()
    title_lower = title.lower().strip()
    title_words = set(_tokenize(title_lower))
    for existing in tasks:
        if existing.get("completed"): continue
        existing_title = existing.get("title", "").lower().strip()
        existing_words = set(_tokenize(existing_title))
        if not existing_words or not title_words: continue
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
    # Match multi-line signature: def tool_create_task(...):\n    """..."""
    pattern = re.compile(r'(def tool_create_task\([^)]*\)[^:]*:\s*""".*?""")', re.DOTALL)
    match = pattern.search(src)
    if match:
        inject_point = match.end()
        src = src[:inject_point] + dedup_code + src[inject_point:]
        with open(path, 'w') as f: f.write(src)
        print("OK tools.py: dedup added to tool_create_task")
    else:
        print("SKIP tools.py: tool_create_task not found")
else:
    print("SKIP tools.py: already patched")
PYEOF

echo ""
echo "=== Verifying patches ==="
grep -c "socket.check" ~/ai-twin/twin_bot.py
grep -c "DEDUP CHECK" ~/ai-twin/tools.py

echo ""
echo "=== Committing and pushing ==="
git add -A
git commit -m "Audit fixes baked in: real FreeLLMAPI health check, task dedup, server-only FreeLLMAPI, archive script"
git push origin phase2
echo ""
echo "=== Done ==="
