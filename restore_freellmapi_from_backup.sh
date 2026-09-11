#!/data/data/com.termux/files/usr/bin/bash
# restore_freellmapi_from_backup.sh

set -e
GITHUB_TOKEN=$(grep GITHUB_TOKEN ~/ai-twin/.env | cut -d= -f2)
REPO="TYKO-sys/ai-twin-phase1"
TAG="phone-backup-20260909-213324"

echo "=== Finding backup asset ==="
ASSET_JSON=$(curl -sL -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/releases/tags/$TAG")

ASSET_ID=$(echo "$ASSET_JSON" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for a in r.get('assets', []):
    if a['name'] == 'ai-twin-phone-backup.zip':
        print(a['id'])
        break
")

if [ -z "$ASSET_ID" ]; then
  echo "Could not find backup asset. Available assets:"
  echo "$ASSET_JSON" | python3 -c "import sys,json; [print(a['name'], a['size']) for a in json.load(sys.stdin).get('assets',[])]"
  exit 1
fi

echo "Found asset ID: $ASSET_ID"

echo ""
echo "=== Downloading backup ==="
curl -sL -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/octet-stream" \
  -o /tmp/backup.zip \
  "https://api.github.com/repos/$REPO/releases/assets/$ASSET_ID"

ls -la /tmp/backup.zip

echo ""
echo "=== Extracting FreeLLMAPI data ==="
cd /tmp
unzip -o backup.zip 'freellmapi-data/*' -d /tmp/

ls -la /tmp/freellmapi-data/

echo ""
echo "=== Stopping FreeLLMAPI ==="
tmux kill-session -t freellmapi 2>/dev/null || true
sleep 2

echo ""
echo "=== Restoring FreeLLMAPI database + encryption key ==="
# Backup the new phone's database (in case)
mv ~/freellmapi/server/data/freeapi.db ~/freellmapi/server/data/freeapi.db.newphone.bak 2>/dev/null || true
mv ~/freellmapi/server/data/freeapi.db-shm ~/freellmapi/server/data/freeapi.db-shm.bak 2>/dev/null || true
mv ~/freellmapi/server/data/freeapi.db-wal ~/freellmapi/server/data/freeapi.db-wal.bak 2>/dev/null || true

# Restore old database + encryption key
cp /tmp/freellmapi-data/freeapi.db ~/freellmapi/server/data/
cp /tmp/freellmapi-data/.encryption-key ~/freellmapi/server/data/ 2>/dev/null

ls -la ~/freellmapi/server/data/freeapi.db ~/freellmapi/server/data/.encryption-key

echo ""
echo "=== Starting FreeLLMAPI ==="
tmux new-session -d -s freellmapi "bash ~/freellmapi-run.sh"
sleep 10

echo ""
echo "=== Testing with old key ==="
OLD_KEY="freellmapi-1e0f09a7a887c3683a38c04866168e216df8eebde697089e"
curl -s http://localhost:3001/v1/models -H "Authorization: Bearer $OLD_KEY" | head -c 500

echo ""
echo ""
echo "=== If the curl above returned JSON with model IDs, you're done. ==="
echo "=== Restart twin: ==="
tmux kill-session -t twin 2>/dev/null || true
sleep 2
tmux new-session -d -s twin "while true; do cd ~/ai-twin && python twin_bot.py 2>&1 | tee -a ~/ai-twin-memory/twin.log; echo crashed, restarting in 5s; sleep 5; done"

sleep 15
echo ""
echo "=== Last 15 log lines ==="
tail -15 ~/ai-twin-memory/twin.log
