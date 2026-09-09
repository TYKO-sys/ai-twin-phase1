# Gumroad Product Page — "AI Twin Builder Kit"

## Product Title

AI Twin Builder Kit: Run a 24/7 Personal AI on Your Phone — That Knows Your Life Without You Telling It

## Tagline

The only personal AI that runs entirely on your phone. No cloud. No coding. No monthly fees. Just a Telegram chat that remembers everything, reads your inbox and call log, knows where you are, tells you what to do next — and never sleeps.

---

## Product Description

I built this because I was tired.

Tired of my brain spinning at 3 AM. Tired of forgetting what I said I'd do. Tired of apps that disappear when I need them and productivity systems that collapse after a week.

My AI twin lives in my phone's background. It remembers everything I tell it — and a lot of things I don't. It reads my emails. It reads my call log. It learns where I am from my location patterns and suggests tasks that fit where I actually am. It tells me what's next before I know I need to do it. It reaches out when it has something to say, not on a timer. It searches the web, scrapes sites, monitors RSS feeds, drafts my emails, tracks my goals, and calls me out when I'm lying to myself.

And it costs $0 per month to run — because it runs on FreeLLMAPI, a self-hosted router that puts 34 free AI providers behind one endpoint with automatic failover. When one provider rate-limits, it switches to another. I never see the switching.

This kit gives you everything I built — the code, the setup scripts, the system prompts, the FreeLLMAPI router, the phone-switch utility, the automation templates. You copy one command, paste it, follow a 5-step web wizard, and your twin is running. No coding. No terminal. No technical skills.

---

## What's in the Kit

### The Core Engine
- **Complete bot code** (Python) — the twin that runs 24/7 on your phone
- **FreeLLMAPI local router** — self-hosted aggregator that puts 34 free AI providers (Groq, OpenRouter, Mistral, Cerebras, Gemini, Z.ai, and ~28 more) behind one OpenAI-compatible endpoint at `localhost:3001/v1`. Automatic failover when a provider rate-limits. Roughly 7.4B tokens/month behind a single unified key. $0/month forever. No provider lock-in. You control the keys.
- **Multi-provider fallback** — even outside FreeLLMAPI, the twin can talk directly to 7 providers in priority order with per-provider cooldown. Belt and suspenders.
- **Remote model management** — the twin fetches the latest available AI models from a GitHub config file. When models change or get deprecated, the config updates automatically. No code changes needed. Ever.
- **Modular prompt architecture** — separate personalities for interactive conversation, proactive messages, knowledge-base updates, and news digests. Each call type loads only the context it needs, so responses stay focused and cheap. Reshape behavior by editing text files, not code.
- **Continuous knowledge base** — an 8-domain structured memory (identity, situation, tasks, relationships, patterns, completed, upcoming, insights) with hard size limits (~1,075 tokens total). Updates itself every few messages in the background. Distilled understanding, not raw logs. Always current — so there's no Sunday weekly-review ritual to keep up with.

### The Tools (48 total)
- **Information:** web search, URL reader, web scraper, RSS reader, news digest, website change monitor, calculator, time/date, URL shortener
- **Awareness (the ones that feel unreal):**
  - **read_emails** — reads your inbox via IMAP. You don't have to tell it "Dr. Lu replied." It checks.
  - **get_call_log** — reads your call history, matches numbers to your contacts, updates its understanding when you make or receive a call.
  - **get_current_location / infer_location / get_location_history** — learns your location patterns, infers where you are from history when GPS drops, and suggests tasks that fit where you actually are.
  - **infer_next_steps** — cross-references what you've done, what's coming, your goals, and your reminders, then tells you the gap: *"You have an ortho consult in 6 days but haven't pulled your imaging yet. Do that tonight."*
- **Files & notes:** write, read, list files; timestamped notes with categories
- **Tasks & goals:** GTD-style task creation (status, next-action, energy, context, due date), task list, complete task, task review, goal creation & listing
- **Drafts & comms:** draft message, save draft, list drafts, send email (SMTP), send SMS, dial phone, send notification
- **Reminders:** set reminders in plain English; the twin tracks them and surfaces them at the right time
- **Scheduling:** create calendar events
- **Contacts & routines:** add/list contacts with follow-up reminders; create/list routines and habits
- **Journaling:** append to journal, read journal
- **OCR:** read text from screenshots and photos (documents, medical records, court papers)
- **Automation:** monitor websites for changes, fire and save webhooks, trigger external automations
- **Self-control:** add/list/remove banned phrases (the twin never sounds like a corporate AI); update your own knowledge base directly

### Dynamic Proactive Messaging
The old version pinged at 9 AM, 9 PM, and a Sunday review. That was bot-like. I ripped it out.
- Scores reach-out opportunities every few minutes: blocked tasks, approaching deadlines, email replies, new RSS content, appointments, long silence, morning briefing, midday check, evening follow-up
- Pings only when the score clears a threshold — sometimes 9 AM, sometimes 2:47 PM, sometimes nothing
- Respects quiet hours (11 PM–7 AM), backs off when you're emotional, keeps a **nudge log** so it never repeats itself, max ~5 proactive messages a day
- A real friend doesn't text you on a schedule. Neither does this.

### Phone Switch & Multi-Phone Support
- **`phone_switch.sh backup`** — stops the twin, zips memory + personality + API keys + FreeLLMAPI config + boot scripts, uploads to GitHub
- **`phone_switch.sh restore`** — downloads on a new phone, installs everything, starts the twin back up
- The twin doesn't know it moved. Same memory. Same personality. Same knowledge of your life. ~30 minutes end to end
- Phone-locked identity so each device keeps its own state

### The User Experience
- **One-command installer** — paste one line, everything else is automated
- **Web-based setup wizard** — enter your API keys through a clean web page, not a terminal
- **Mobile setup guide** — a single HTML page with 5 steps, no jargon, big buttons
- **Error translation layer** — all technical errors are translated to friendly messages. Users never see stack traces, API codes, or file paths
- **One-tap recovery** — send `/fix` to the twin and it clears all errors and reconnects automatically

### The Infrastructure
- **tmux background execution** — the twin survives even if you close the terminal app
- **Auto-restart on crash** — if the bot dies, tmux restarts it in seconds
- **Boot script** — the twin starts automatically when your phone restarts
- **Keep-alive system** — wakelock, battery optimization guidance, auto-start configuration
- **Safe update script** — update the code without losing your configuration

### The Personality
- **Complete system prompt** — defines how the twin behaves: honest, direct, patient, present. Not a chatbot. A twin.
- **Forbidden phrases list** — the twin never sounds like a corporate AI. No "I understand how you feel." No "Let's dive in." No "In today's fast-paced world."
- **Voice profile + personal kill file** — load your own writing voice and your own list of phrases the twin must never use, from plain text files
- **Engagement instructions** — conversational, empathetic, heterogeneous paragraphs, short sentences. Sounds human.

### The Business Materials
- **Fiverr gig description** — post-ready, conversion-optimized, with pricing tiers ($99/$199/$399)
- **Substack newsletter template** — story-driven first issue that hooks readers
- **This Gumroad page** — the one you're reading right now, included as a template

---

## How It Works

1. **Download the kit** — you get a zip file with everything
2. **Open the setup guide** on your phone — a clean web page with 5 steps
3. **Install one app** — free, from F-Droid (link included)
4. **Paste one command** — the installer does the rest
5. **Follow the web wizard** — enter your API keys through a clean web page
6. **Done** — your twin is running. Open Telegram and say hi.

Total time: 5-15 minutes. No coding. No terminal exposure. No technical skills.

---

## What Makes This Different

### vs. ChatGPT / Claude / Gemini apps
Those are chatbots. You ask, they answer, you forget. They don't remember what you said last Tuesday. They don't ping you when something matters. They don't read your inbox or your call log. They don't know where you are. They don't write you a continuous understanding of your life. They don't move with you to a new phone.

This twin remembers everything. It reads your emails and your call log. It learns where you are. It infers your next step. It reaches out when it has a reason — not on a schedule. It holds your context so you don't have to. And it's portable across hardware.

### vs. Productivity apps (Notion, Todoist, etc.)
Those are tools you have to remember to use. They don't come to you. They don't ask you questions. They don't draft your emails or search the web for you. They don't know what's in your inbox.

This twin comes to you. It initiates. It asks. It reads your world. It does things while you sleep.

### vs. Therapy / coaching
Those are expensive, weekly, and human (which means they get tired, they forget, they have other clients).

This twin is free, 24/7, and never tires. It's not a replacement for therapy — but it's the thing that holds your context between sessions. It's the thing that notices the pattern your therapist would notice, but every day instead of once a week.

### vs. Other AI assistant setups
Most require a desktop, a cloud server, or monthly subscriptions. Most break when API models change. Most require technical maintenance. Most are glued to one machine.

This runs on a phone. Costs $0/month through FreeLLMAPI (34 providers, auto-failover). Maintains itself — when models change, it updates automatically. And it survives a phone switch with one command. No maintenance required.

---

## Perfect For

- **Overthinkers** who can't turn their brains off at 3 AM
- **ADHD brains** that need external memory, gentle accountability, and a thing that notices what they're avoiding
- **Busy professionals** drowning in tasks, emails, calls, and decisions
- **Students** who need structure, reminders, and a thinking partner that reads their school email
- **Anyone in therapy** who wants something holding context between sessions
- **Anyone who's tried productivity apps and abandoned them after a week**
- **Anyone who wants "set it and forget it" AI** — not another thing to manage
- **Anyone who upgrades phones** and is tired of starting over

---

## Pricing

### DIY Kit — $39
Everything above. You install it yourself using the 5-step guide. If you can copy and paste, you can do this. Includes FreeLLMAPI router, 48 tools, dynamic proactive messaging, continuous knowledge base, phone-switch utility, and all business materials.

### Done-For-You Setup — $199
I install it on your phone via a 30-minute screen-share call. You get the kit too, plus custom personality tuning, email/call-log/location awareness wired to your accounts, next-step inference configured to your goals, phone-switch backup set up, and 30 days of support.

### Builder's License — $399
The kit, plus a commercial license to sell this as a service to your own clients. Includes the Fiverr gig template, Substack content, and Gumroad page template. You keep 100% of what you charge clients.

---

## FAQ

**Q: Does this work on iPhone?**
A: Not yet. The backend requires Android via Termux. iPhone support is planned for a future version.

**Q: What is FreeLLMAPI and why is it $0/month?**
A: FreeLLMAPI is a small self-hosted router that aggregates 34 free AI providers (Groq, OpenRouter, Mistral, Cerebras, Gemini, Z.ai, and ~28 more) behind a single OpenAI-compatible endpoint on your phone. You add your free API keys once, get one unified key back, and the twin talks to that one key. When a provider rate-limits, FreeLLMAPI automatically routes the request to another. The combined free pool is roughly 7.4 billion tokens a month — far more than any single person will use. You never see the switching. You just see responses. It costs $0 because every underlying provider has a free tier, and FreeLLMAPI stitches them together.

**Q: What if I switch phones?**
A: One command (`phone_switch.sh backup`) stops the twin, zips your memory, personality, API keys, FreeLLMAPI config, and boot scripts, and uploads the backup to your GitHub. On the new phone, one command (`phone_switch.sh restore`) downloads it, installs everything, and starts the twin back up. Same memory. Same personality. Same knowledge of your life. The twin doesn't know it moved. Plan on ~30 minutes end to end.

**Q: It reads my emails and call log — is that safe?**
A: It only reads what you give it access to, and only you can talk to your twin (it's locked to your Telegram account). Email reading uses your own IMAP credentials stored locally on your phone. Call-log access uses Termux's call-log API, which only works with permissions you grant. Nothing is uploaded to a third party. Your conversations are plain text files on your device.

**Q: Will it cost me money every month?**
A: No. The free AI tiers cover normal use many times over through FreeLLMAPI. If you want faster responses on a specific provider, you can add $5 to that one provider — that lasts months. $0/month works for almost everyone.

**Q: Is my data private?**
A: Your conversations are stored locally on your phone as plain text files. Your messages go to AI providers for processing (that's how it thinks) — but through your own FreeLLMAPI router, which you control. The bot is locked to your Telegram account. No one else can talk to your twin. No cloud syncing. No third-party data harvesting.

**Q: What if I'm not technical?**
A: You don't need to be. The setup guide has 5 steps with big buttons. The installer does everything. The web wizard collects your API keys through a clean form. If you can install an app and copy-paste, you can build this.

**Q: What if something breaks?**
A: Send the twin a `/fix` command in Telegram. It clears all errors and reconnects automatically. The kit also includes a troubleshooting guide with the 10 most common issues and plain-English fixes.

**Q: Can I customize the personality?**
A: Yes. The system prompt is a plain text file — edit it to change how your twin behaves. The modular prompt architecture means you can reshape conversation, proactive messages, and digests independently. The kit includes the full prompt I use, which you can modify.

**Q: Can I sell this to others?**
A: Yes, with the Builder's License ($399). You get commercial rights and all the marketing materials. Charge whatever you want — $99, $199, $500. You keep everything.

**Q: What if the AI models change or get deprecated?**
A: The twin fetches the latest model list from a GitHub config file every 6 hours. When a model gets deprecated, you (or anyone) updates the config on GitHub, and all twins automatically pick up the change. No code updates. No app restarts. It just keeps working.

---

## What Happens After You Buy

1. You get an instant download link with the complete kit (zip file)
2. You open `SETUP_GUIDE.html` on your phone
3. You follow 5 steps (install one app, paste one command, follow the wizard)
4. Your twin is running in 5-15 minutes
5. You open Telegram and say hi

If you bought Done-For-You ($199) or Builder's License ($399), you'll also get an email within 24 hours to schedule your setup call.

---

## Refund Policy

If the kit doesn't work on your phone, email me within 14 days for a full refund. No questions asked. I'll also help you troubleshoot first — if we can't get it working, you get your money back.

---

*The twin isn't the product. The transformation is. Your brain doesn't have to be the only one holding your weight — and it doesn't have to be the only one paying attention, either.*

*— TYKO*
