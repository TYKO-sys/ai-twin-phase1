# AI Twin — User Guide

## What is this?

Your AI twin is a personal assistant that lives in a Telegram chat on your phone. It remembers what you tell it. It helps you think. It reminds you of things. It does research for you. It drafts messages. It tracks your goals and tasks.

You talk to it like a person. It talks back.

## How to use it

### Day-to-day

**Just send messages.** That's it. Text, voice memos, screenshots — whatever's on your mind. The twin responds like a friend who knows you well.

**Every morning at 9am:** The twin sends you one thing to focus on today. Based on what you talked about yesterday.

**Every night at 9pm:** The twin asks three questions:
1. What actually happened today?
2. What did you avoid?
3. What's one true thing you want tomorrow-you to know?

Answer honestly. This is how the twin learns you.

**Every Sunday at 8pm:** The twin writes a weekly review — patterns it noticed, progress you made, things you avoided. Read it Monday morning.

### Things you can ask it to do

- "Search the web for..." — it searches and summarizes
- "What's the latest news about..." — it finds current info
- "Draft an email to..." — it writes the email, you review and send
- "Create a task:..." — it adds to your task list
- "What tasks do I have?" — it shows your list
- "Create a goal:..." — it tracks long-term goals
- "Add a contact:..." — it remembers who to follow up with
- "What's 15% of 347?" — it calculates
- "Save this note:..." — it saves to your notes
- "Journal this:..." — it writes to today's journal

You don't have to use special commands. Just talk normally. The twin figures out what you need.

### Commands

Send these in Telegram for specific actions:

- `/start` — intro message
- `/help` — list all commands
- `/status` — check bot health
- `/profile` — see what the twin knows about you
- `/profile update` — refresh the twin's memory from today
- `/search <word>` — find anything in your memory
- `/forget <topic>` — delete mentions of a topic
- `/ping` — twin asks you one question to get unstuck
- `/morning` — trigger morning prompt manually
- `/evening` — trigger evening reflection manually
- `/weekly` — generate weekly review now
- `/resend` — regenerate last response if it got cut off
- `/debug` — show technical info (for troubleshooting)

### Managing the bot (in Termux)

If you need to check on the bot, open Termux and use:

- `twin-start` — start the bot
- `twin-logs` — see live logs (press Ctrl+B then D to exit)
- `twin-stop` — stop the bot
- `twin-status` — check if it's running

You shouldn't need to do this often. The bot runs itself.

## Tips for getting the most out of it

**Be honest.** The twin can only help if you tell it the truth. If you're avoiding something, say so. If you're struggling, say so. The twin won't judge you.

**Be consistent.** The twin learns from patterns. If you talk to it every day, it gets smarter about you. If you only talk to it when you're in crisis, it has less to work with.

**Let it push back.** Sometimes the twin will call you out. "You said you'd do X yesterday and you didn't. What happened?" That's the twin doing its job. Don't get defensive. Just answer honestly.

**Use the evening reflection.** The three questions at 9pm are the most important part. They're how the twin builds its understanding of you. Two minutes a night. Worth it.

**Review your profile.** Send `/profile` occasionally to see what the twin knows about you. If something's wrong, tell it. It'll update.

## What the twin can't do

- It can't send messages for you. It drafts, you send.
- It can't control your phone's apps. No clicking buttons, no opening apps.
- It can't make phone calls or send texts.
- It's not a therapist. It's a thinking partner.
- It's not private from the AI provider. Your messages go to OpenRouter or Google.

If you need something the twin can't do, ask it anyway. It'll tell you what it CAN do instead.

## When something breaks

See `TROUBLESHOOTING.md` for the most common issues and how to fix them.

Or just send `/status` to your twin — it'll tell you if something's wrong.

## Privacy

Your conversations are stored on your phone as plain text files. You can read them anytime in Termux at `~/ai-twin-memory/`. You can delete them with `/forget`.

Your messages also go to the AI provider (OpenRouter or Google) for processing. That's how the twin thinks. If you want full privacy, you'd need to run a local AI model — but that's slower and less capable.

The bot is locked to your Telegram account. No one else can talk to it.

## Questions?

Ask your twin. That's what it's there for.
