#!/data/data/com.termux/files/usr/bin/bash
# create_freellmapi_key.sh — bootstrap FreeLLMAPI dashboard + create client key

DASHBOARD_EMAIL="mikey.maziq93@gmail.com"
DASHBOARD_PASSWORD="twin-dashboard-2026"  # only used once, write it down
BASE="http://localhost:3001"

echo "=== Step 1: Check current auth status ==="
STATUS=$(curl -s $BASE/api/auth/status)
echo "$STATUS"

echo ""
echo "=== Step 2: Sign up (if no user exists) ==="
SIGNUP_RESP=$(curl -s -X POST $BASE/api/auth/signup \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$DASHBOARD_EMAIL\",\"password\":\"$DASHBOARD_PASSWORD\"}")
echo "Signup: $SIGNUP_RESP"

echo ""
echo "=== Step 3: Log in to get session token ==="
LOGIN_RESP=$(curl -s -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$DASHBOARD_EMAIL\",\"password\":\"$DASHBOARD_PASSWORD\"}")
echo "Login: $LOGIN_RESP"

# Extract token (try common field names)
TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('token') or d.get('sessionToken') or d.get('accessToken') or d.get('data',{}).get('token') or '')" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo ""
  echo "Login response didn't include a token in a known field."
  echo "Paste the full login response above and I'll extract the right field."
  exit 1
fi

echo "Got session token: ${TOKEN:0:20}..."

echo ""
echo "=== Step 4: Create client profile ==="
PROFILE_RESP=$(curl -s -X POST $BASE/api/client-profiles \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"twin"}')
echo "Profile: $PROFILE_RESP"

# Extract the API key
API_KEY=$(echo "$PROFILE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('key') or '')" 2>/dev/null)

if [ -z "$API_KEY" ]; then
  echo ""
  echo "Profile response didn't include 'key'. Full response above."
  exit 1
fi

echo ""
echo "=== SUCCESS ==="
echo "Your FreeLLMAPI key is:"
echo "$API_KEY"
echo ""
echo "Adding it to ~/ai-twin/.env..."

# Update .env with the new key
python3 <<PYEOF
import re
path = "/data/data/com.termux/files/home/ai-twin/.env"
with open(path) as f: src = f.read()
new_src = re.sub(r'FREELLMAPI_API_KEY=.*', f'FREELLMAPI_API_KEY={API_KEY}', src)
with open(path, 'w') as f: f.write(new_src)
print("Updated .env")
PYEOF

echo ""
echo "=== Restarting twin ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo crashed, restarting in 5s; sleep 5; done"

sleep 15
echo "=== Last 15 log lines ==="
tail -15 ~/ai-twin-memory/twin.log

echo ""
echo "=== Testing FreeLLMAPI with new key ==="
curl -s http://localhost:3001/v1/models -H "Authorization: Bearer $API_KEY" | head -c 300
