# AI Twin — Phase 1

A Telegram bot that runs on your Android phone (via Termux), uses Google
Gemini as its brain, and remembers everything you tell it. Designed for
people whose executive function is overloaded — it does the thinking,
consolidating, and prompting so you don't have to.

## What this is

One Telegram chat. That's the entire interface. You send it text, voice
memos, screenshots. It remembers. It responds. It pings you at 9am and 9pm.
It writes weekly reviews every Sunday. It calls you on your contradictions.
It holds your context so you don't have to.

Behind the chat:
- **Termux** (Linux on Android) runs the bot 24/7
- **Google Gemini** (free tier, 250 req/day) is the brain
- **Plain markdown files** on your phone are the memory
- **Internal scheduler** triggers morning/evening/weekly pings

## What this isn't

- It's not a therapist. It's a thinking partner.
- It's not a replacement for human connection. You still need people.
- It's not magic. It needs 30-45 min of setup. Then it runs itself.
- It's not private from Google. Gemini API processes your messages.

## Phase 1 features

- Text, voice memo, and screenshot support
- Persistent memory in plain markdown files (daily logs, weekly reviews)
- Identity file (who you are, what you care about)
- Morning ping at 9am, evening reflection at 9pm, weekly review Sunday 8pm
- Forgetting commands (`/forget <topic>`, `/search <query>`)
- Robust network handling (survives AdGuard toggles, wifi switches)
- Model auto-recovery (survives Google deprecating model names)
- tmux-based background execution (survives Termux being closed)
- Boot script (auto-starts on phone reboot with Termux:Boot)

## Phase 2 (separate branch/release)

Phase 2 adds tool use — web search, file operations, task management,
calculator, journaling. The twin goes from "talks to you" to "does things
for you." See the `phase2` branch or the tools documentation.

## Quick start

1. Read `MANUAL_STEPS.md` end-to-end
2. Install Termux from F-Droid (NOT Play Store)
3. Install Telegram, create a bot via @BotFather
4. Get a Gemini API key from aistudio.google.com/apikey
5. Get your Telegram user ID from @userinfobot
6. Copy this folder to Termux, run `bash setup.sh`
7. Edit `.env` with your three secrets
8. Run `python twin_bot.py`
9. Message your bot on Telegram: `/start`

See `MANUAL_STEPS.md` for detailed tap-by-tap instructions.

## File layout

```
ai-twin/
├── twin_bot.py             # Main bot — runs 24/7
├── context_manager.py      # Memory: read, write, search, forget
├── summarizer.py           # Weekly auto-summary (Sundays)
├── gemini_client.py        # REST client for Gemini API (no SDK)
├── system_prompt.txt       # The bot's personality and rules
├── setup.sh                # Automated setup for Termux
├── keep_alive_setup.sh     # tmux + wakelock + boot script setup
├── safe_update.sh          # Update code without losing .env
├── start.sh                # Quick launcher
├── requirements.txt        # Python dependencies
├── .env.example            # Template for secrets
├── MANUAL_STEPS.md         # The 6 human-only steps
├── macrodroid_config.md    # Optional automation setup
└── README.md               # This file
```

## Commands

| Command              | What it does                                          |
|----------------------|-------------------------------------------------------|
| `/start`             | Intro message                                         |
| `/help`              | List all commands                                     |
| `/status`            | Bot health + memory size                              |
| `/search <query>`    | Find anything in memory                               |
| `/forget <topic>`    | Permanently delete mentions of a topic                |
| `/identity`          | Show what the bot knows about you                     |
| `/set_identity`      | Replace the identity file (send new text after)       |
| `/ping`              | Bot asks you one question to get unstuck              |
| `/morning`           | Morning prompt (auto at 9am)                          |
| `/evening`           | 3-question evening reflection (auto at 9pm)           |
| `/weekly`            | Generate weekly review now (auto Sunday 8pm)          |
| `/resend`            | Regenerate last response (if chunks were lost)        |
| `/debug`             | Toggle memory footer on/off (default: off)            |
| `/cancel`            | Cancel a pending command                              |

## Cost

- Termux: free
- Telegram: free
- Gemini API: free tier (250 req/day)
- MacroDroid: free (optional)
- Tasker: ~$3 (optional alternative)

**Total: $0**

## License

MIT — do whatever you want with this. Just don't blame me if it tells you
something you don't want to hear.

---

Built for one person who asked for an AI that would think for them when
their own thinking was overloaded. Hope it helps.
