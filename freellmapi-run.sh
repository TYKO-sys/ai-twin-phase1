#!/data/data/com.termux/files/usr/bin/bash
cd ~/freellmapi
LOG=~/ai-twin-memory/freellmapi.log
while true; do
    echo "[$(date)] FreeLLMAPI server starting (server only)..." >> "$LOG"
    npm run dev -w server 2>&1 | tee -a "$LOG"
    echo "[$(date)] FreeLLMAPI crashed, restarting in 5s..." >> "$LOG"
    sleep 5
done
