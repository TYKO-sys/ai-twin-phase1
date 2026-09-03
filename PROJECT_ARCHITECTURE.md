# AI Twin — Complete Project Architecture

## Table of Contents
1. What This Is
2. Architecture Overview
3. Core Components
4. LLM Provider System
5. Memory & Knowledge Base
6. Tool System
7. Proactive Messaging
8. User Interface
9. Infrastructure & Keep-Alive
10. Installation & Setup
11. Configuration Reference
12. Current Capabilities
13. Planned Capabilities
14. Known Limitations
15. File Reference

---

## 1. What This Is

The AI Twin is a personal AI assistant that lives on an Android phone, runs 24/7, and communicates through Telegram. It remembers everything, thinks for the user when their own thinking is overloaded, and does things on their behalf — research, drafts, task management, phone integration.

**Cost: $0/month** (all free tiers)
**Platform: Android only** (via Termux)
**Interface: Telegram chat**

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                   Telegram                        │
│              (user interface)                     │
└──────────────┬─────────────────────┬──────────────┘
               │                     │
         ┌─────▼─────┐        ┌──────▼──────┐
         │  twin_bot  │        │  Proactive  │
         │   .py      │        │  Messaging  │
         │  (main)    │        │  (thread)   │
         └─────┬──────┘        └─────────────┘
               │
    ┌──────────┼──────────────────────────┐
    │          │                          │
┌───▼───┐ ┌───▼────────┐ ┌──────────────▼──────┐
│multi_ │ │knowledge_  │ │     tools.py         │
│provider│ │base.py    │ │  (32 tools)          │
│.py    │ │(8 domains)│ │  web search, OCR,    │
│(7 LLM │ │            │ │  phone, drafts, etc.  │
│providers)│ └──────────┘ └─────────────────────┘
└───┬───┘
    │
    ├── Groq (free, 14,400 req/day)
    ├── OpenRouter (free, 20+ models)
    ├── FreeLLMAPI (free, 34 providers, 7.4B tokens/month)
    ├── Mistral (free, 1B tokens/month)
    ├── Cerebras (free, 1M tokens/day)
    ├── Z.ai (free, GLM models)
    └── Gemini (free, 1,500 req/day)
```

---

## 3. Core Components

### twin_bot.py — The Main Bot
- Telegram bot interface (pyTelegramBotAPI)
- Receives text, voice, and photo messages
- Routes to LLM via multi-provider system
- Logs all messages to daily files
- Handles commands (/help, /status, /fix, /profile, /search, etc.)
- Sends responses with Markdown-to-HTML conversion for rich text
- No reply-to-message previews (standalone messages)

### multi_provider.py — LLM Provider Rotation
- 7 free LLM providers, tried in priority order
- Automatic failover when one provider is rate-limited
- Each provider has a 60-second cooldown after failure
- Model configuration fetched remotely from GitHub (model_manager.py)
- FreeLLMAPI added as provider #3 (34 free models behind one endpoint)

### knowledge_base.py — Structured Memory
- 8 domains, each with HARD character limits:
  - identity.md (500 chars) — who TYKO is at their core
  - situation.md (800 chars) — current life circumstances
  - tasks.md (600 chars) — active tasks only
  - relationships.md (500 chars) — key people
  - patterns.md (500 chars) — behaviors observed 3+ times
  - completed.md (500 chars) — last 7 days of wins
  - upcoming.md (500 chars) — events within 30 days
  - insights.md (400 chars) — deep understanding
- Total max: 4,300 chars (~1,075 tokens)
- Updates every 5 messages (incremental, background thread)
- Never truncates — compresses intelligently
- All content in second person ("you"), never third person

### tools.py — 32 Tools
- **Information:** web_search, read_url, get_current_time, calculator
- **Files:** write_file, read_file, list_files
- **Notes:** save_note, get_notes
- **Tasks:** create_task, list_tasks, complete_task
- **Goals:** create_goal, list_goals
- **Drafts:** draft_message, save_draft, list_drafts
- **Contacts:** add_contact, list_contacts
- **Routines:** create_routine, list_routines
- **Journal:** append_to_journal, read_journal
- **Phone integration:** send_notification, open_url, copy_to_clipboard, get_clipboard, set_alarm, send_sms, dial_phone, get_battery_status, get_location

### system_prompt.txt — Personality & Behavioral Rules
- Engagement-focused, conversational, empathetic
- Banned ChatGPT phrases (40+ terms)
- Behavioral principles (not banned-word lists):
  - Match energy, don't escalate
  - Be genuine, not performative
  - Say what needs saying, stop (epigrammatic)
  - Don't have a "signature" closing
  - Don't meta-comment on being an AI
  - Address user directly ("you"), never third person ("they")
  - Use relative dates in speech, absolute dates internally
  - Time-awareness: don't suggest impossible tasks
  - Don't forget what YOU said
  - Know what's next and do it (don't ask "what do you want to do?")
  - Proactivity: do things without asking permission
  - Don't bring up completed tasks
  - File operations are background (never user-facing)
  - Name: TYKO in conversation, Michael Mazique in formal documents

---

## 4. LLM Provider System

Provider priority order:
1. **Groq** — fastest, 14,400 req/day, free
2. **OpenRouter** — 20+ free models via unified router
3. **FreeLLMAPI** — 34 free providers, 7.4B tokens/month, no key needed
4. **Mistral** — 1B tokens/month, free
5. **Cerebras** — 1M tokens/day, very fast
6. **Z.ai** — GLM models, free
7. **Gemini** — Google's free tier, 1,500 req/day

Model configuration is managed remotely via `models_config.json` on GitHub. When models get deprecated, the config is updated on GitHub and all clients pick it up within 6 hours.

---

## 5. Memory & Knowledge Base

The twin has TWO layers of memory:

**Layer 1: Knowledge Base (structured, small, always in context)**
- 8 domains with hard limits (~1,075 tokens total)
- Distilled understanding, not raw logs
- Updated every 5 messages (background thread)
- Cumulative — each update builds on the previous

**Layer 2: Daily Logs (raw, searchable, not in context)**
- Every message logged to daily/YYYY-MM-DD.md
- Today's log is included in context for conversation flow
- Previous days are searchable via /search
- Weekly summaries generated on Sundays

---

## 6. Proactive Messaging

**Event-driven, zero idle tokens:**
- Checks every 5 minutes (local string parsing, no LLM calls)
- Triggers when:
  - Appointment within 1 hour → urgent reminder
  - Appointment within 24 hours → heads-up
  - User silent 4+ hours with open tasks → check-in
- LLM only called to GENERATE the message (not to DECIDE whether to send)
- Cancels redundant reminders when user is already discussing the topic
- Quiet hours: 11 PM to 7 AM
- At least 1 hour between proactive messages

---

## 7. User Interface

- Telegram chat (the only interface after setup)
- Messages sent as standalone (no reply-to preview)
- Markdown converted to Telegram HTML for rich text
- Bold, italic, code blocks, links, bullet points, headings
- Commands: /help, /status, /fix, /profile, /search, /forget, /morning, /evening, /weekly, /resend, /ping, /checkboot, /debug

---

## 8. Infrastructure

- **Termux** — Linux on Android
- **tmux** — background session (survives Termux being closed)
- **Auto-restart** — tmux while-loop restarts bot on crash
- **Wakelock** — prevents CPU sleep
- **Termux:Boot** — auto-starts on phone reboot
- **Tasker** (optional) — relaunches Termux if Android kills it
- **Safe update** — updates code without losing .env

---

## 9. Installation

One command:
```bash
bash install.sh
```

The installer:
1. Checks compatibility
2. Installs packages (Python, tmux, termux-api)
3. Installs Python dependencies
4. Opens web wizard for API keys
5. Runs keep-alive setup
6. Starts the bot
7. Self-tests

---

## 10. Configuration Reference

### .env file keys:
- TELEGRAM_BOT_TOKEN (required)
- ALLOWED_USER_ID (required)
- FREELLMAPI_API_KEY=free (always available)
- GROQ_API_KEY (recommended)
- OPENROUTER_API_KEY
- MISTRAL_API_KEY
- CEREBRAS_API_KEY
- ZAI_API_KEY
- GEMINI_API_KEY

### models_config.json:
- Remote: https://raw.githubusercontent.com/TYKO-sys/ai-twin-phase1/main/models_config.json
- Local fallback: models_config.json in the repo
- Refreshed: every 6 hours

---

## 11. Current Capabilities

- Text, voice memo, and photo understanding
- 32 tools (web search, drafts, tasks, phone integration, etc.)
- 8-domain knowledge base with hard size limits
- Proactive messaging (event-driven, zero idle tokens)
- 7 free LLM providers with automatic failover
- Remote model management (no code updates needed for model changes)
- Rich text formatting in Telegram
- Error translation (user never sees technical details)
- 24/7 operation with auto-restart

---

## 12. Planned Capabilities (from resource analysis)

### Immediate (implementable now):
- **PaddleOCR** — read documents, medical records, court papers from photos
- **Changedetection.io** — monitor websites for changes (waitlist, appointment slots)
- **n8n.cloud integration** — connect twin to 400+ services via free cloud automation

### When laptop arrives (Phase 2):
- **Browser automation** (browser-use) — twin can navigate websites, fill forms, log in
- **Ollama** — local LLM for privacy mode (zero API costs)
- **MCP server support** — modular tool ecosystem (1,000+ agent skills)
- **CRM integration** (trycompai/crm) — for selling twin as a service

### Future:
- **Multi-worker architecture** — specialized agents (research, drafting, scheduling)
- **Real-time live mode** — teleprompter during phone calls
- **Social media manager** — auto-post and respond to comments
- **Cross-platform messaging** — manage conversations across all platforms

---

## 13. Known Limitations

- **Android only** — no iPhone support
- **No browser automation** on phone (requires laptop/desktop)
- **No app control** — can't click buttons in other apps
- **Shared IP rate limiting** — free models rate-limited by IP on cellular
- **Termux can be killed** by aggressive battery management (Tasker mitigates)
- **No real ambient awareness** — twin knows what you tell it, not what it sees

---

## 14. File Reference

### Core:
- `twin_bot.py` — main bot
- `multi_provider.py` — LLM provider rotation
- `knowledge_base.py` — structured memory (8 domains)
- `tools.py` — 32 tool definitions
- `system_prompt.txt` — personality & behavioral rules
- `model_manager.py` — remote model config fetching

### Infrastructure:
- `install.sh` — one-command installer
- `wizard.py` + `wizard_assets/` — web-based API key setup
- `keep_alive_setup.sh` — tmux, wakelock, boot script
- `safe_update.sh` — update without losing .env
- `markdown_to_telegram.py` — rich text converter
- `error_handler.py` — friendly error messages

### Support:
- `gemini_client.py` — Gemini REST client (fallback)
- `openrouter_client.py` — OpenRouter client (legacy)
- `profile_manager.py` — legacy profile system (replaced by knowledge_base)
- `context_manager.py` — daily log management
- `summarizer.py` — weekly reviews
- `models_config.json` — model configuration
- `.env` — secrets (never committed to Git)

### Documentation:
- `SETUP_GUIDE.html` — mobile-first setup guide
- `USER_GUIDE.md` — non-technical user guide
- `TROUBLESHOOTING.md` — common issues
- `README.md` — one-sentence entry point

### Marketing:
- `MARKETING_FIVERR.md` — Fiverr gig description
- `MARKETING_SUBSTACK.md` — newsletter first issue
- `MARKETING_GUMROAD.md` — product page
