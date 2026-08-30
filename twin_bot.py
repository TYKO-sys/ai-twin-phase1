"""
twin_bot.py
===========
The AI twin. Long-running Telegram bot that lives on the user's phone
(via Termux) and acts as their second mind.

Architecture:
  - pyTelegramBotAPI (telebot) for the interface — lighter than
    python-telegram-bot, no Rust/cryptography dependency, installs
    cleanly on Termux with Python 3.12-3.14
  - Google Gemini for the brain (free tier, 15 req/min, 1500/day),
    called directly via REST API (no SDK, no google-auth, no cryptography)
  - Local markdown files for memory (under ~/ai-twin-memory/)

Features:
  - Text messages: contextual reply using recent memory
  - Voice messages: transcribed via Gemini, then handled as text
  - Photos/screenshots: Gemini vision reads them, then handled
  - /forget <topic>: deletes mentions from memory
  - /search <query>: searches memory
  - /identity: shows the user's identity file
  - /set_identity: replaces the identity file (user sends new text)
  - /ping: bot initiates a check-in (used by Tasker/MacroDroid)
  - /morning: triggered by automation at 9am
  - /evening: triggered by automation at 9pm
  - /weekly: triggered by automation on Sundays
  - /help: list commands
  - /status: shows bot health, memory size, last message time

Design choices:
  - All context is plain markdown. The user can read their own mind.
  - Every bot reply includes a footer showing which memory files were used.
  - If Gemini API fails (rate limit, network), bot retries with backoff.
  - No external database. Filesystem is the database.
  - One log file per day. Easy to find, easy to forget, easy to archive.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

import telebot
import requests

sys.path.insert(0, str(Path(__file__).parent))
from context_manager import ContextManager
from summarizer import run_weekly_summary
from gemini_client import GeminiClient

# ---------------------------------------------------------------------- #
# Configuration
# ---------------------------------------------------------------------- #

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("twin")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0") or "0")
MEMORY_DIR = os.environ.get("MEMORY_DIR",
                            str(Path.home() / "ai-twin-memory"))

if not TELEGRAM_BOT_TOKEN:
    log.error("TELEGRAM_BOT_TOKEN not set. Copy .env.example to .env and fill it in.")
    sys.exit(1)
if not GEMINI_API_KEY:
    log.error("GEMINI_API_KEY not set. Copy .env.example to .env and fill it in.")
    sys.exit(1)
if not ALLOWED_USER_ID:
    log.error("ALLOWED_USER_ID not set. Add your Telegram user ID.")
    sys.exit(1)

# ---------------------------------------------------------------------- #
# Globals
# ---------------------------------------------------------------------- #

cm = ContextManager(MEMORY_DIR)

# Configure Gemini client (pure REST, no SDK, no Rust)
# Model name is auto-verified on first call — falls back automatically
# if Google deprecates a model name.
GEMINI_MODEL_NAME = "gemini-3.7-flash"
gemini_client = GeminiClient(
    api_key=GEMINI_API_KEY,
    model=GEMINI_MODEL_NAME,
)

with open(Path(__file__).parent / "system_prompt.txt", "r",
          encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# Track which memory files were used in the last response (for footer)
_last_context_files: list[str] = []

# Evening reflection state (per user — only one user, so simple dict)
evening_state: dict = {}

# Identity-replacement pending state
identity_pending: bool = False
forget_pending: str = ""

# Debug mode — when True, bot appends memory footer to each message.
# Toggle with /debug command. Default: off (footer invisible).
_debug_mode: bool = False

# Message processing lock — ensures only one message is processed at a time.
_processing_lock = threading.Lock()
_currently_processing = False

# Initialize bot — plain text mode (no Markdown parsing).
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _auth_user(message) -> bool:
    """Only the owner can talk to this bot."""
    return message.from_user and message.from_user.id == ALLOWED_USER_ID


def _build_gemini_prompt(user_text: str) -> str:
    """Build the full prompt sent to Gemini: context + user message."""
    global _last_context_files
    _last_context_files = []

    context = cm.build_context_for_response()

    daily_files = sorted((Path(MEMORY_DIR) / "daily").glob("*.md"),
                         reverse=True)[:3]
    weekly_files = sorted((Path(MEMORY_DIR) / "weekly").glob("*.md"),
                          reverse=True)[:2]
    ident_file = Path(MEMORY_DIR) / "identity" / "about_me.md"
    _last_context_files = [f.name for f in daily_files]
    _last_context_files += [f.name for f in weekly_files]
    if ident_file.exists():
        _last_context_files.append("about_me.md")

    prompt = f"""# CONTEXT FROM MEMORY

{context}

# END CONTEXT

# NEW MESSAGE FROM USER

{user_text}
"""
    return prompt


def _call_gemini(prompt: str, image_bytes: Optional[bytes] = None,
                  audio_bytes: Optional[bytes] = None) -> str:
    """Call Gemini via REST. Retries are handled inside the client."""
    return gemini_client.generate(
        prompt=prompt,
        system_instruction=SYSTEM_PROMPT,
        image_bytes=image_bytes,
        audio_bytes=audio_bytes,
    )


def _footer() -> str:
    """Footer showing which memory files were consulted.

    Now invisible by default — it's a backend diagnostic, not something
    the user needs to see in every message. Enable with /debug command.
    """
    if not _debug_mode:
        return ""
    if not _last_context_files:
        return ""
    files = ", ".join(_last_context_files[:5])
    return f"\n\n— Memory used: {files}"


def _check_network_connectivity() -> bool:
    """Quick check if we can reach external services."""
    import socket
    try:
        socket.gethostbyname("api.telegram.org")
        return True
    except Exception:
        return False


def _wait_for_network(max_wait: int = 90) -> bool:
    """Wait until network connectivity returns."""
    for i in range(max_wait // 3):
        if _check_network_connectivity():
            return True
        log.info(f"Waiting for network... ({i*3}s)")
        time.sleep(3)
    return False


def _send_typing(chat_id: int) -> None:
    """Send the 'typing' chat action."""
    try:
        bot.send_chat_action(chat_id, "typing")
    except Exception:
        pass


def _send_telegram_message(chat_id: int, text: str,
                           reply_to: int = None) -> bool:
    """Send a single Telegram message with robust retry logic."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            if reply_to:
                bot.send_message(chat_id, text,
                                 reply_to_message_id=reply_to,
                                 timeout=60)
            else:
                bot.send_message(chat_id, text, timeout=60)
            return True
        except Exception as e:
            wait = 2 ** (attempt + 1)
            log.warning(
                f"Telegram send failed (attempt {attempt+1}/{max_retries}): "
                f"{type(e).__name__}: {e}. Retrying in {wait}s..."
            )
            if attempt < max_retries - 1:
                time.sleep(wait)
    log.error(f"Telegram send failed after {max_retries} attempts. "
              f"Message LOST ({len(text)} chars).")
    return False


def _safe_reply(message, text: str) -> None:
    """Reply, splitting long messages into chunks if needed."""
    chat_id = message.chat.id
    reply_to_id = message.message_id
    MAX = 4000

    if len(text) <= MAX:
        if not _send_telegram_message(chat_id, text, reply_to=reply_to_id):
            try:
                bot.send_message(
                    chat_id,
                    "(I tried to reply but Telegram's servers are having "
                    "issues. Please wait a minute and resend your message.)",
                    timeout=60,
                )
            except Exception:
                pass
        return

    parts = []
    while text:
        if len(text) <= MAX:
            parts.append(text)
            break
        cut = text.rfind("\n\n", 0, MAX)
        if cut == -1 or cut < MAX // 2:
            cut = text.rfind("\n", 0, MAX)
        if cut == -1 or cut < MAX // 2:
            cut = MAX
        parts.append(text[:cut])
        text = text[cut:].lstrip()

    log.info(f"Splitting reply into {len(parts)} chunks "
             f"(total {sum(len(p) for p in parts)} chars)")

    lost_chunks = 0
    for i, part in enumerate(parts):
        reply_target = reply_to_id if i == 0 else None
        sent = _send_telegram_message(chat_id, part, reply_to=reply_target)
        if not sent:
            lost_chunks += 1
        if i < len(parts) - 1 and sent:
            time.sleep(1.0)

    if lost_chunks > 0:
        try:
            bot.send_message(
                chat_id,
                f"(Note: {lost_chunks} of {len(parts)} parts of my response "
                f"failed to send due to Telegram server issues. "
                f"Say 'resend' and I'll regenerate my full reply.)",
                timeout=60,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------- #
# Command handlers
# ---------------------------------------------------------------------- #

@bot.message_handler(commands=["start"])
def cmd_start(message):
    if not _auth_user(message):
        return
    intro = (
        "I'm here. I'm your twin.\n\n"
        "Send me anything — text, voice, screenshots. I'll remember it all "
        "and use it to think with you.\n\n"
        "Things I can do:\n"
        "• Reply with context from everything you've ever told me\n"
        "• Read screenshots you send\n"
        "• Transcribe voice memos and respond\n"
        "• /forget <topic> — wipe something from my memory\n"
        "• /search <query> — find anything I remember\n"
        "• /identity — see what I know about you\n"
        "• /set_identity — replace it (send new text after)\n"
        "• /status — check my health\n"
        "• /help — see all commands\n\n"
        "I'll ping you at 9am and 9pm automatically.\n\n"
        "First thing: send me a voice memo or a few sentences about who you "
        "are right now, what's on your plate, and what you're avoiding. "
        "That becomes my first real memory of you."
    )
    _safe_reply(message, intro)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    if not _auth_user(message):
        return
    help_text = (
        "Commands:\n\n"
        "/start — intro message\n"
        "/help — this list\n"
        "/status — bot health + memory size\n"
        "/search <query> — find anything in my memory\n"
        "/forget <topic> — wipe mentions of a topic from memory\n"
        "/identity — show what I know about you\n"
        "/set_identity — replace identity (send new text after)\n"
        "/ping — I'll check in with you\n"
        "/morning — morning prompt (usually auto-triggered)\n"
        "/evening — evening reflection (usually auto-triggered)\n"
        "/weekly — generate weekly review now\n"
        "/resend — regenerate my last response (if chunks were lost)\n"
        "/debug — toggle memory footer on/off (default: off)\n\n"
        "Just send me anything else. Text, voice, photos. "
        "I'll figure it out."
    )
    _safe_reply(message, help_text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    if not _auth_user(message):
        return
    daily_count = len(list((Path(MEMORY_DIR) / "daily").glob("*.md")))
    weekly_count = len(list((Path(MEMORY_DIR) / "weekly").glob("*.md")))
    ident_exists = (Path(MEMORY_DIR) / "identity" / "about_me.md").exists()
    mem_size = sum(
        f.stat().st_size
        for f in Path(MEMORY_DIR).rglob("*.md")
        if f.is_file()
    )
    mem_kb = mem_size / 1024
    status = (
        f"Status: running\n"
        f"Time: {_now()}\n"
        f"Memory dir: {MEMORY_DIR}\n"
        f"Daily logs: {daily_count}\n"
        f"Weekly reviews: {weekly_count}\n"
        f"Identity file: {'exists' if ident_exists else 'MISSING — set one'}\n"
        f"Total memory: {mem_kb:.1f} KB\n"
        f"Gemini model: {GEMINI_MODEL_NAME}\n"
        f"Your Telegram ID: {message.from_user.id}"
    )
    _safe_reply(message, status)


@bot.message_handler(commands=["search"])
def cmd_search(message):
    if not _auth_user(message):
        return
    query = message.text.partition(" ")[2].strip()
    if not query:
        _safe_reply(message, "Usage: /search <query>")
        return
    results = cm.search(query, limit=10)
    _safe_reply(message, results)


@bot.message_handler(commands=["forget"])
def cmd_forget(message):
    global forget_pending
    if not _auth_user(message):
        return
    query = message.text.partition(" ")[2].strip()
    if not query:
        _safe_reply(message, "Usage: /forget <topic>")
        return
    if forget_pending != query:
        forget_pending = query
        _safe_reply(
            message,
            f"You want me to forget '{query}'. "
            "This permanently deletes matching lines from all memory files. "
            f"Send /forget {query} again to confirm."
        )
        return
    forget_pending = ""
    result = cm.forget(query)
    _safe_reply(message, result)


@bot.message_handler(commands=["identity"])
def cmd_identity(message):
    if not _auth_user(message):
        return
    identity = cm.get_identity()
    if not identity:
        _safe_reply(
            message,
            "I don't have an identity file for you yet. "
            "Use /set_identity and send me a few paragraphs about who you "
            "are, what you care about, what you're working on, what you're "
            "avoiding, what you want in 6 months."
        )
        return
    _safe_reply(message, identity)


@bot.message_handler(commands=["set_identity"])
def cmd_set_identity(message):
    global identity_pending
    if not _auth_user(message):
        return
    identity_pending = True
    _safe_reply(
        message,
        "Send me your new identity text now. "
        "Next message you send will replace what I know about you. "
        "(Send /cancel to abort.)"
    )


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    global identity_pending, forget_pending
    if not _auth_user(message):
        return
    identity_pending = False
    forget_pending = ""
    evening_state.pop(message.from_user.id, None)
    _safe_reply(message, "Cancelled.")


@bot.message_handler(commands=["morning"])
def cmd_morning(message):
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    today = cm.get_today_context()
    recent = cm.get_recent_days(days=2)
    prompt = f"""It's morning. The user just woke up (or you're prompting them).

Generate the morning message in the format described in your instructions:
- One thing that matters most today, based on yesterday's context
- A specific, small, doable step
- One sentence of context for why this is the thing
- End with a yes/no or short-answer question

Under 5 lines total. Be direct.

# RECENT CONTEXT

{recent}

# TODAY SO FAR (if anything)

{today}
"""
    reply = _call_gemini(prompt) + _footer()
    cm.append_to_today("twin", reply, observation="morning ping triggered")
    _safe_reply(message, reply)


@bot.message_handler(commands=["evening"])
def cmd_evening(message):
    if not _auth_user(message):
        return
    cm.append_to_today("twin", "Evening check-in started.",
                       observation="evening ping triggered")
    evening_state[message.from_user.id] = 1
    _safe_reply(
        message,
        "Evening. Three questions, one at a time.\n\n"
        "1. What actually happened today?"
    )


@bot.message_handler(commands=["weekly"])
def cmd_weekly(message):
    if not _auth_user(message):
        return
    _safe_reply(message, "Generating weekly review. This takes about 30 seconds...")
    try:
        summary = run_weekly_summary(MEMORY_DIR, GEMINI_API_KEY)
        _safe_reply(message, summary)
    except Exception as e:
        log.error(f"Weekly summary failed: {e}")
        _safe_reply(message, f"Weekly review failed: {type(e).__name__}: {e}")


@bot.message_handler(commands=["ping"])
def cmd_ping(message):
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    today = cm.get_today_context()
    prompt = f"""The user pinged you. They want a check-in.

Look at today's context (if any) and ask ONE question that helps them
move forward. Not three. One. The question that matters most right now.

# TODAY SO FAR

{today}
"""
    reply = _call_gemini(prompt)
    cm.append_to_today("twin", reply, observation="manual ping")
    _safe_reply(message, reply)


@bot.message_handler(commands=["debug"])
def cmd_debug(message):
    global _debug_mode
    if not _auth_user(message):
        return
    _debug_mode = not _debug_mode
    state = "ON" if _debug_mode else "OFF"
    _safe_reply(
        message,
        f"Debug mode: {state}\n\n"
        f"When ON, each reply shows which memory files were used.\n"
        f"When OFF (default), replies are clean with no footer.\n\n"
        f"Current model: {gemini_client.model}\n"
        f"Models tried this session: {gemini_client._tried_models or 'none'}"
    )


@bot.message_handler(commands=["resend"])
def cmd_resend(message):
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    today = cm.get_today_context()
    import re
    user_messages = re.findall(
        r"## \d{2}:\d{2} — user\n(.*?)(?=\n## |\n> \*\*|$)",
        today, re.DOTALL
    )
    if not user_messages:
        _safe_reply(message, "I don't have a recent message to regenerate from.")
        return
    last_user_msg = None
    for msg in reversed(user_messages):
        if not msg.strip().startswith("/resend") and not msg.strip().startswith("[voice]") and not msg.strip().startswith("[photo]"):
            last_user_msg = msg.strip()
            break
    if not last_user_msg:
        _safe_reply(message, "I don't have a recent message to regenerate from.")
        return
    cm.append_to_today("user", "/resend (regenerating last response)")
    prompt = _build_gemini_prompt(last_user_msg)
    reply = _call_gemini(prompt) + _footer()
    cm.append_to_today("twin", reply, observation="regenerated via /resend")
    _safe_reply(message, reply)


# ---------------------------------------------------------------------- #
# Message handlers
# ---------------------------------------------------------------------- #

@bot.message_handler(content_types=["text"])
def handle_text(message):
    global identity_pending
    if not _auth_user(message):
        return
    text = message.text or ""

    if identity_pending:
        cm.update_identity(text)
        identity_pending = False
        _safe_reply(
            message,
            "Identity updated. I'll read this before every reply from now on."
        )
        return

    user_id = message.from_user.id
    step = evening_state.get(user_id)
    if step:
        cm.append_to_today("user", f"(evening Q{step}) {text}")
        if step == 1:
            evening_state[user_id] = 2
            _safe_reply(message, "2. What did you avoid?")
            return
        elif step == 2:
            evening_state[user_id] = 3
            _safe_reply(
                message,
                "3. What's one true thing you want tomorrow-you to know?"
            )
            return
        elif step == 3:
            evening_state.pop(user_id, None)
            _send_typing(message.chat.id)
            today = cm.get_today_context()
            prompt = f"""Evening reflection complete. The user answered three questions.
Write a short reflection (3-5 sentences). Honest. Specific. No fluff.

# Today's full log

{today}
"""
            reply = _call_gemini(prompt) + _footer()
            cm.append_to_today("twin", reply, observation="evening reflection")
            _safe_reply(message, reply)
            return

    cm.append_to_today("user", text)

    global _currently_processing
    if _currently_processing:
        try:
            bot.send_message(
                message.chat.id,
                "I see your message. Give me a moment — I'm still thinking "
                "about your previous one. I'll get to this right after.",
                timeout=30,
            )
        except Exception:
            pass

    _currently_processing = True
    try:
        _send_typing(message.chat.id)
        prompt = _build_gemini_prompt(text)
        reply = _call_gemini(prompt) + _footer()
        cm.append_to_today("twin", reply)
        _safe_reply(message, reply)
    finally:
        _currently_processing = False


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    try:
        file_info = bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
        r = requests.get(file_url, timeout=30)
        r.raise_for_status()
        ogg_bytes = r.content

        full = gemini_client.generate(
            prompt=(
                "Transcribe this voice memo. Then on a new line write "
                "'---TRANSCRIPTION END---' and after that, respond as the twin "
                "would to the transcribed content. Use the context from the user's "
                "memory if relevant."
            ),
            system_instruction=SYSTEM_PROMPT,
            audio_bytes=ogg_bytes,
            audio_mime="audio/ogg",
        )
        if "---TRANSCRIPTION END---" in full:
            parts = full.split("---TRANSCRIPTION END---", 1)
            transcription = parts[0].strip()
            reply = parts[1].strip()
        else:
            transcription = full
            reply = "(Couldn't separate transcription from response.)"

        cm.append_to_today("user", f"[voice] {transcription}")
        cm.append_to_today("twin", reply, observation="voice memo processed")
        _safe_reply(message, f"I heard: {transcription}\n\n{reply}" + _footer())
    except Exception as e:
        log.error(f"Voice handling failed: {e}\n{traceback.format_exc()}")
        _safe_reply(
            message,
            f"Couldn't process that voice memo. Error: {type(e).__name__}. "
            "Try sending it as text."
        )


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    try:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
        r = requests.get(file_url, timeout=30)
        r.raise_for_status()
        img_bytes = r.content

        caption = message.caption or "(no caption)"
        prompt = _build_gemini_prompt(
            f"The user sent a screenshot/photo. Their caption: '{caption}'. "
            "Look at the image. Tell them what you see. Then ask: "
            "'what do you need from me on this?'"
        )
        reply = _call_gemini(prompt, image_bytes=img_bytes) + _footer()
        cm.append_to_today("user", f"[photo] {caption}")
        cm.append_to_today("twin", reply, observation="screenshot analyzed")
        _safe_reply(message, reply)
    except Exception as e:
        log.error(f"Photo handling failed: {e}\n{traceback.format_exc()}")
        _safe_reply(
            message,
            f"Couldn't process that image. Error: {type(e).__name__}."
        )


# ---------------------------------------------------------------------- #
# Internal Scheduler (morning / evening / weekly pings)
# ---------------------------------------------------------------------- #

_last_morning_date = None
_last_evening_date = None
_last_weekly_date = None

MORNING_HOUR = 9
EVENING_HOUR = 21
WEEKLY_DAY = 6
WEEKLY_HOUR = 20


def _send_direct_message(text: str) -> bool:
    try:
        bot.send_message(ALLOWED_USER_ID, text, timeout=60)
        return True
    except Exception as e:
        log.error(f"Direct message send failed: {e}")
        return False


def _trigger_morning():
    global _last_morning_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    _last_morning_date = today_str
    log.info("Triggering morning ping (internal scheduler)")

    today = cm.get_today_context()
    recent = cm.get_recent_days(days=2)
    prompt = f"""It's morning. The user just woke up.

Generate the morning message in the format described in your instructions:
- One thing that matters most today, based on yesterday's context
- A specific, small, doable step
- One sentence of context for why this is the thing
- End with a yes/no or short-answer question

Under 5 lines total. Be direct.

# RECENT CONTEXT

{recent}

# TODAY SO FAR (if anything)

{today}
"""
    reply = _call_gemini(prompt)
    cm.append_to_today("twin", reply, observation="morning ping (auto)")
    _send_direct_message(reply)


def _trigger_evening():
    global _last_evening_date, evening_state
    today_str = datetime.now().strftime("%Y-%m-%d")
    _last_evening_date = today_str
    log.info("Triggering evening ping (internal scheduler)")

    cm.append_to_today("twin", "Evening check-in started.",
                       observation="evening ping (auto)")
    evening_state[ALLOWED_USER_ID] = 1
    _send_direct_message(
        "Evening. Three questions, one at a time.\n\n"
        "1. What actually happened today?"
    )


def _trigger_weekly():
    global _last_weekly_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    _last_weekly_date = today_str
    log.info("Triggering weekly review (internal scheduler)")

    _send_direct_message(
        "Generating weekly review. This takes about 30 seconds..."
    )
    try:
        from summarizer import run_weekly_summary
        summary = run_weekly_summary(MEMORY_DIR, GEMINI_API_KEY)
        MAX = 4000
        if len(summary) <= MAX:
            _send_direct_message(summary)
        else:
            parts = []
            while summary:
                if len(summary) <= MAX:
                    parts.append(summary)
                    break
                cut = summary.rfind("\n\n", 0, MAX)
                if cut == -1 or cut < MAX // 2:
                    cut = summary.rfind("\n", 0, MAX)
                if cut == -1 or cut < MAX // 2:
                    cut = MAX
                parts.append(summary[:cut])
                summary = summary[cut:].lstrip()
            for part in parts:
                _send_direct_message(part)
                time.sleep(1.0)
    except Exception as e:
        log.error(f"Auto weekly summary failed: {e}")
        _send_direct_message(f"Weekly review failed: {type(e).__name__}: {e}")


def _scheduler_loop():
    global _last_morning_date, _last_evening_date, _last_weekly_date
    log.info("Internal scheduler started "
             f"(morning={MORNING_HOUR}:00, evening={EVENING_HOUR}:00, "
             f"weekly=Sunday {WEEKLY_HOUR}:00)")

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            if (now.hour == MORNING_HOUR and now.minute == 0
                    and _last_morning_date != today_str):
                _trigger_morning()

            if (now.hour == EVENING_HOUR and now.minute == 0
                    and _last_evening_date != today_str):
                _trigger_evening()

            if (now.weekday() == WEEKLY_DAY
                    and now.hour == WEEKLY_HOUR and now.minute == 0
                    and _last_weekly_date != today_str):
                _trigger_weekly()

        except Exception as e:
            log.error(f"Scheduler error: {e}")

        time.sleep(60)


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #

def main() -> None:
    log.info("=" * 60)
    log.info("AI Twin starting up")
    log.info(f"  Memory dir: {MEMORY_DIR}")
    log.info(f"  Gemini model: {GEMINI_MODEL_NAME}")
    log.info(f"  Allowed user: {ALLOWED_USER_ID}")
    log.info(f"  Library: pyTelegramBotAPI (telebot)")
    log.info(f"  Scheduler: morning={MORNING_HOUR}am, "
             f"evening={EVENING_HOUR}pm, "
             f"weekly=Sunday {WEEKLY_HOUR}pm")
    log.info("=" * 60)
    log.info("Bot running. Press Ctrl+C to stop.")

    scheduler_thread = threading.Thread(target=_scheduler_loop,
                                        daemon=True)
    scheduler_thread.start()
    log.info("Scheduler thread started")

    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=30,
                logger_level=None,
            )
        except KeyboardInterrupt:
            log.info("Bot stopped by user.")
            break
        except (ConnectionError, OSError, Exception) as e:
            log.warning(
                f"Polling crashed: {type(e).__name__}: {e}. "
                f"Checking network..."
            )
            if _wait_for_network(max_wait=90):
                log.info("Network is back. Reconnecting in 5 seconds...")
                time.sleep(5)
            else:
                log.warning(
                    f"Network still down after 90s. "
                    f"Will keep retrying every 30 seconds..."
                )
                while not _wait_for_network(max_wait=30):
                    log.warning("Still no network. Retrying in 30s...")
                log.info("Network finally back. Reconnecting...")
                time.sleep(5)
            continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
    except Exception as e:
        log.error(f"Fatal: {e}\n{traceback.format_exc()}")
        sys.exit(1)
