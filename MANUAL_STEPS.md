# Manual Steps — What ONLY YOU Can Do

The bot scripts are written. The setup is automated. But there are 6 things
no AI can do for you, because they require your accounts, your phone, your
fingers. These are the only places you have to act.

Total time: 30-45 minutes. Take breaks. Do them in any order.

---

## Step 1 of 6 — Install Termux (5 min)

**Why:** Termux is the Linux terminal that runs on your phone. The bot lives here.

**Critical:** Get Termux from **F-Droid**, NOT Google Play Store. The Play Store version is abandoned and broken.

### How:

1. Open your phone's browser
2. Go to: https://f-droid.org/packages/com.termux/
3. Tap "Download APK"
4. Tap the downloaded file to install
5. If Android blocks install: tap "Settings" on the warning → enable "Allow from this source"
6. Open Termux. You'll see a black screen with text. That's normal.

**Verify it works:** Type `pkg update -y` and press Enter. If it shows updates downloading, Termux works.

---

## Step 2 of 6 — Install Telegram (3 min, if not already installed)

**Why:** This is the ONLY app you'll ever open to talk to your twin.

### How:

1. Google Play Store → search "Telegram" → install
2. Open Telegram
3. Sign in with your phone number
4. Set a username (Settings → Username) — needed in Step 3

---

## Step 3 of 6 — Create your Telegram bot (5 min)

**Why:** Each Telegram bot has a unique token. Only you can create yours, tied to your account.

### How:

1. In Telegram, search for `@BotFather`
2. Tap it, then tap START
3. Send the message: `/newbot`
4. BotFather asks for a name. Type: `AI Twin` (or anything you like)
5. BotFather asks for a username (must end in `bot`). Type: `yourname_twin_bot` (e.g. `alex_twin_bot`)
6. BotFather replies with a token that looks like:
   ```
   7123456789:AAH-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
7. **COPY THIS TOKEN.** Save it somewhere. You'll paste it into `.env` later.

**Verify:** Send any message to your new bot (search its username in Telegram). It won't reply yet — that's fine. The bot doesn't have a brain until we run the script.

---

## Step 4 of 6 — Get your Gemini API key (5 min)

**Why:** Gemini is the AI brain. Free tier gives you 1500 requests/day — way more than you'll use.

### How:

1. Open browser, go to: https://aistudio.google.com/apikey
2. Sign in with your Google account
3. Tap "Create API key"
4. Choose "Create API key in new project" (default)
5. Copy the key — it looks like:
   ```
   AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
6. **SAVE THIS KEY.** You'll paste it into `.env` later.

**Verify:** The key page should show your key with "Gemini" listed as the API.

**Cost note:** Free tier is 15 requests/minute, 1500/day. If you somehow exceed this, Gemini just slows down — no charges.

---

## Step 5 of 6 — Get your Telegram user ID (2 min)

**Why:** This locks the bot so ONLY YOU can talk to it. Without this, anyone who finds your bot's username could read your memory.

### How:

1. In Telegram, search for `@userinfobot`
2. Tap START
3. It replies with your user info. Look for the line that says "Id:" followed by a number, like:
   ```
   Id: 123456789
   ```
4. **COPY THAT NUMBER.** You'll paste it into `.env` as `ALLOWED_USER_ID`.

---

## Step 6 of 6 — Copy the ai-twin folder to Termux + run setup (15 min)

**Why:** The bot's code needs to be ON your phone, in Termux's storage, then set up.

### How to get the files onto your phone:

**Option A — Download from your computer (easiest):**
1. Transfer the `ai-twin/` folder to your phone (email yourself a zip, Google Drive, USB cable, whatever)
2. Save it to your phone's "Downloads" folder
3. Unzip if needed

**Option B — Clone from GitHub (if you uploaded it there):**
1. In Termux, run: `pkg install git`
2. Then: `git clone <your-repo-url> ~/ai-twin`

**Option C — Copy from Termux shared storage:**
1. Move the ai-twin folder to your phone's Downloads folder
2. In Termux, run:
   ```
   termux-setup-storage
   cp -r ~/storage/downloads/ai-twin ~/ai-twin
   ```

### How to run setup:

1. Open Termux
2. Navigate to the folder:
   ```
   cd ~/ai-twin
   ```
3. Run the setup script:
   ```
   bash setup.sh
   ```
4. Follow the prompts. It will:
   - Install Python and dependencies (~3 min)
   - Acquire a wakelock so Android doesn't kill it
   - Create `.env` from `.env.example`
   - **PAUSE** and ask you to edit `.env`

### When setup pauses for .env editing:

1. In Termux, type: `nano .env`
2. Fill in three lines:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAH-xxxxx...
   GEMINI_API_KEY=AIzaxxxxx...
   ALLOWED_USER_ID=123456789
   ```
3. Save: press Ctrl+O, then Enter, then Ctrl+X to exit
4. Press ENTER in the setup script to continue

### After setup finishes:

1. It will ask "Want me to start it now?" — type `y` and press Enter
2. The bot is now running. You'll see log output in Termux.
3. Open Telegram, find your bot, send: `/start`
4. Your twin will reply.

---

## Step 7 (optional but recommended) — Battery optimization exclusion

**Why:** Android will kill Termux in the background to save battery. This breaks the bot.

### How:

1. Open Android Settings
2. Apps → Termux
3. Battery → "Battery optimization" or "Background restrictions"
4. Select "Don't optimize" or "Unrestricted" or "Allow background activity"

(Exact wording varies by phone manufacturer. Look for anything that says
"don't restrict" or "allow in background.")

Also do the same for MacroDroid if you install it.

---

## Step 8 (optional but recommended) — Install MacroDroid for scheduling

**Why:** Termux's cron works only while Termux is running. MacroDroid triggers
reliably even if Termux is asleep. Belt and suspenders.

### How:

1. Google Play → search "MacroDroid" → install
2. Open MacroDroid, give it the permissions it asks for
3. Open the file `macrodroid_config.md` (it's in the ai-twin folder)
4. Follow its instructions to create 3 macros (morning, evening, weekly)
5. Each macro takes ~2 minutes to set up

---

## You're done. Now what?

Once Steps 1-6 are complete and the bot is running:

1. **Send `/start`** to your bot in Telegram
2. **Send `/set_identity`** then write a few paragraphs about yourself:
   - What's true in your life right now
   - What you're working on
   - What you're avoiding
   - What you want in 6 months
3. **Send a voice memo or text** about whatever's on your mind
4. Wait for the 9am ping tomorrow morning — your twin will reach out first

---

## Troubleshooting

**Bot doesn't reply when I message it:**
- Check Termux is open and showing log output
- Run `/status` in Telegram — if no reply, the bot isn't running
- In Termux, check for errors: `python twin_bot.py 2>&1 | tail -50`

**Bot replies with "I'm having trouble thinking right now":**
- Gemini API error. Check your API key in `.env`
- Verify the key works at https://aistudio.google.com/apikey
- You might have hit the rate limit. Wait 60 seconds.

**Bot forgets things:**
- Check `~/ai-twin-memory/daily/` — files should be there
- Run `/search <keyword>` to verify memory exists
- If files are missing, you may have a permissions issue. Run:
  `chmod -R 755 ~/ai-twin-memory`

**Android kills the bot:**
- Re-run `termux-wake-lock` in Termux
- Check battery optimization is OFF for Termux (Step 7)
- Open Termux once a day to keep it "warm"

**Cron doesn't fire:**
- Verify crond is running: `ps aux | grep crond`
- Start it manually: `crond`
- Or install MacroDroid and use that instead (more reliable)

---

## What I (the AI building this) cannot do for you

I cannot:
- Open your phone's browser
- Install apps from the Play Store
- Sign into your Telegram or Google accounts
- Create a Telegram bot on your behalf (BotFather requires your auth)
- Generate a Gemini API key tied to your Google account
- Tap "Allow" on Android permission dialogs
- Run Termux commands on your phone (Termux is on YOUR device, not mine)

Everything above the line "Step 1" — the code, the prompts, the configs,
the setup script — that's done. Below the line is yours.

Take your time. Come back to it. The bot will wait.
