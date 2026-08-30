# AI Twin — Troubleshooting

## The 10 most common issues and how to fix each.

---

### 1. The bot isn't responding to my messages

**Check:** Open Termux and run `twin-status`. Does it say "RUNNING"?

**If it says STOPPED:**
```
twin-start
```
Then wait 10 seconds and try sending a message again.

**If it says RUNNING but no response:**
- The AI provider might be down. Wait 5 minutes and try again.
- Check your internet connection.
- Run `twin-logs` to see what's happening. Look for error messages.

---

### 2. The bot says "rate limited" or "429 error"

**Cause:** You're using free AI models and hit the rate limit. This is common on cellular networks because your IP is shared with thousands of other users.

**Fix:** Add $5 to OpenRouter and switch to a paid model:
1. Go to https://openrouter.ai/credits
2. Add $5
3. In Termux: `nano ~/ai-twin/.env`
4. Add this line: `OPENROUTER_MODEL=deepseek/deepseek-chat`
5. Save (Ctrl+O, Enter, Ctrl+X)
6. Run: `twin-stop && twin-start`

$5 lasts months. No more rate limits.

---

### 3. The bot died overnight / after I closed Termux

**Cause:** Android killed Termux to save battery.

**Fix:**
1. Go to Android Settings → Apps → Termux → Battery
2. Set to "Unrestricted" or "Don't optimize"
3. Make sure Termux:Boot is installed (from F-Droid)
4. Open Termux — the bot auto-starts

**To prevent it:** Don't fully toggle AdGuard on/off. Use "Pause" instead. Toggling VPN apps kills Termux.

---

### 4. The bot's response got cut off mid-sentence

**Cause:** Either the AI hit a token limit or Telegram had a server error.

**Fix:** Send `/resend` to the bot. It will regenerate the response.

If it keeps happening, the response might be too long. Ask the twin to "keep it shorter" or "continue from where you left off."

---

### 5. I didn't get my morning/evening ping

**Cause:** The bot wasn't running at 9am/9pm, or the scheduler missed the window.

**Fix:**
1. Check `twin-status` — is the bot running?
2. If not, run `twin-start`
3. Send `/morning` or `/evening` manually to trigger it now

The scheduler checks every 60 seconds. If the bot is running at 9:00-9:01am, you'll get the ping. If the bot was dead at that time, you won't.

---

### 6. The bot is giving me confused/wrong responses

**Cause:** The profile might be outdated or the context might be confusing.

**Fix:**
1. Send `/profile` to see what the twin thinks it knows about you
2. If something's wrong, tell the twin directly: "Actually, I don't live in [X] anymore" or "That's not right, I actually [Y]"
3. Send `/profile update` to force a refresh
4. If it's still wrong, use `/forget <topic>` to delete bad memories about that topic

---

### 7. "command not found" when I type twin-start

**Cause:** The `~/bin` directory isn't in your PATH.

**Fix:**
```bash
export PATH="$HOME/bin:$PATH"
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.profile
twin-start
```

This fixes it permanently. Close and reopen Termux to verify.

---

### 8. The wizard didn't open in my browser

**Cause:** Termux can't always open the browser automatically.

**Fix:** Open your phone's browser manually and go to:
```
http://localhost:8888
```

The wizard page should load. If it doesn't, the wizard server might have crashed. In Termux, run:
```bash
cd ~/ai-twin && python wizard.py
```

---

### 9. I lost my .env file / my secrets are gone

**Cause:** An update went wrong, or the file got deleted.

**Fix:** Backups are stored in multiple places. Run:
```bash
ls ~/ai-twin/.env_backups/
ls ~/.env.backup*
```

Copy the most recent one back:
```bash
cp ~/ai-twin/.env_backups/.env.LATEST ~/ai-twin/.env
```

If no backups exist, re-run the wizard:
```bash
cd ~/ai-twin && python wizard.py
```

---

### 10. Python errors / the bot won't start

**Check:** Run the bot directly to see the error:
```bash
cd ~/ai-twin
python twin_bot.py
```

**Common causes:**

- **"Module not found":** Run `pip install --break-system-packages -r requirements.txt`
- **"KeyError" or env vars missing:** Your `.env` file is incomplete. Re-run the wizard.
- **"Address already in use":** Another instance is running. Run `twin-stop` first.
- **"Permission denied":** Run `chmod +x ~/ai-twin/*.sh`

If you see a stack trace you don't understand, take a screenshot and ask your twin: "What does this error mean?" It can read screenshots.

---

## Still stuck?

Send your twin a screenshot of the error. It can analyze images and often tell you what's wrong.

Or run `/status` in Telegram — it shows the bot's health, memory size, and which AI model is being used.
