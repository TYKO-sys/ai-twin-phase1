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
from profile_manager import ProfileManager
from knowledge_base import get_knowledge_base
from tools import GEMINI_TOOLS_CONFIG, execute_tool
from multi_provider import MultiProviderClient
from error_handler import translate_error, friendly_status
from markdown_to_telegram import convert_markdown_to_telegram_html, split_for_telegram

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
if not ALLOWED_USER_ID:
    log.error("ALLOWED_USER_ID not set. Add your Telegram user ID.")
    sys.exit(1)

# Check that at least one LLM key is set
_llm_keys = [
    os.environ.get("GROQ_API_KEY", "").strip(),
    os.environ.get("OPENROUTER_API_KEY", "").strip(),
    os.environ.get("MISTRAL_API_KEY", "").strip(),
    os.environ.get("CEREBRAS_API_KEY", "").strip(),
    os.environ.get("ZAI_API_KEY", "").strip(),
    os.environ.get("DEEPSEEK_API_KEY", "").strip(),
    GEMINI_API_KEY,
]
if not any(_llm_keys):
    log.error("No LLM API key found. Set at least one of: "
              "GROQ_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY, "
              "CEREBRAS_API_KEY, ZAI_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY")
    sys.exit(1)

# ---------------------------------------------------------------------- #
# Globals
# ---------------------------------------------------------------------- #

cm = ContextManager(MEMORY_DIR)
pm = ProfileManager()
kb = get_knowledge_base()  # structured knowledge base

# Initialize multi-provider LLM client
# Automatically rotates through OpenRouter → DeepSeek → Z.ai → Gemini
llm_client = MultiProviderClient()
LLM_PROVIDER = "multi-provider"
LLM_MODEL = llm_client.model
USE_OPENROUTER = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())

# Backward compatibility: keep gemini_client as an alias
gemini_client = llm_client

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
# telebot processes sequentially by default, but we use this to send a
# "I see your message, processing..." notification when messages queue up.
_processing_lock = threading.Lock()
_currently_processing = False

# Initialize bot — HTML mode for rich text formatting.
# All LLM responses (which are Markdown) get converted to Telegram HTML
# before sending. This gives the user bold, italic, code blocks, links, etc.
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML")


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _auth_user(message) -> bool:
    """Only the owner can talk to this bot."""
    return message.from_user and message.from_user.id == ALLOWED_USER_ID


def _build_gemini_prompt(user_text: str) -> str:
    """Build the full prompt sent to the LLM: knowledge base + today's conversation + message.

    The knowledge base provides STRUCTURED UNDERSTANDING (not raw logs).
    Today's conversation provides immediate context (flow).
    The user's message is the new input.
    """
    global _last_context_files
    _last_context_files = []

    # The knowledge base — distilled understanding, not raw logs
    knowledge = kb.get_all_knowledge()
    _last_context_files.append("knowledge_base")

    # Today's conversation for immediate flow
    context = cm.build_context_for_response()

    prompt = f"""{knowledge}

---

# TODAY'S CONVERSATION

{context}

# NEW MESSAGE FROM USER

{user_text}
"""
    return prompt


def _call_gemini(prompt: str, image_bytes: Optional[bytes] = None,
                  audio_bytes: Optional[bytes] = None) -> str:
    """Call LLM via multi-provider system.

    The multi-provider client automatically tries OpenRouter → DeepSeek →
    Z.ai → Gemini. If one is rate-limited or down, it tries the next.
    No manual fallback logic needed here.
    """
    # For multimodal messages (images/audio), skip tools
    if image_bytes or audio_bytes:
        return llm_client.generate(
            prompt=prompt,
            system_instruction=SYSTEM_PROMPT,
            image_bytes=image_bytes,
        )

    # Text-only — use tool-enabled generation
    return llm_client.generate_with_tools(
        prompt=prompt,
        system_instruction=SYSTEM_PROMPT,
        tools_config=GEMINI_TOOLS_CONFIG,
        tool_executor=execute_tool,
        max_iterations=5,
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
    """Quick check if we can reach external services.

    Tries to resolve api.telegram.org. If DNS works, network is up.
    Used to detect AdGuard toggling, wifi switches, etc.
    """
    import socket
    try:
        socket.gethostbyname("api.telegram.org")
        return True
    except Exception:
        return False


def _wait_for_network(max_wait: int = 90) -> bool:
    """Wait until network connectivity returns. Returns True if back.

    Polls every 3 seconds for up to max_wait seconds. Used when AdGuard
    is toggled or wifi switches — those can take 15-30s to stabilize.
    """
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
    """Send a single Telegram message with robust retry logic.

    Converts Markdown to Telegram HTML before sending for rich text display.
    Falls back to plain text if HTML conversion fails.

    Telegram's API sometimes returns 502 Bad Gateway or times out,
    especially during peak hours. We retry with exponential backoff:
    2s, 4s, 8s, 16s, 32s — total ~1 minute of retries before giving up.

    Returns True if sent, False if all retries failed.
    """
    # Convert Markdown to Telegram HTML
    try:
        html_text = convert_markdown_to_telegram_html(text)
    except Exception:
        # If conversion fails, escape HTML and send as-is
        html_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    max_retries = 5
    for attempt in range(max_retries):
        try:
            if reply_to:
                bot.send_message(chat_id, html_text,
                                 reply_to_message_id=reply_to,
                                 timeout=60)
            else:
                bot.send_message(chat_id, html_text, timeout=60)
            return True
        except Exception as e:
            wait = 2 ** (attempt + 1)  # 2, 4, 8, 16, 32 seconds
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
    """Reply, splitting long messages into chunks if needed.

    Telegram's message limit is 4096 chars. We split at 4000 to leave room.
    We send chunks sequentially with a delay between them, and use
    robust retry logic for each chunk. If a chunk is permanently lost,
    we tell the user.
    """
    chat_id = message.chat.id
    reply_to_id = message.message_id
    MAX = 4000

    if len(text) <= MAX:
        if not _send_telegram_message(chat_id, text, reply_to=reply_to_id):
            # Even a short message failed after 5 retries. Tell the user.
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

    # Split on paragraph boundaries if possible
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

    # Send each chunk sequentially. First chunk replies to the user's message.
    # Subsequent chunks are standalone. Add a delay between successful sends
    # so Telegram doesn't rate-limit us.
    lost_chunks = 0
    for i, part in enumerate(parts):
        reply_target = reply_to_id if i == 0 else None
        sent = _send_telegram_message(chat_id, part, reply_to=reply_target)
        if not sent:
            lost_chunks += 1
        # Delay between chunks (only if this one succeeded and there's more)
        if i < len(parts) - 1 and sent:
            time.sleep(1.0)

    if lost_chunks > 0:
        # Tell the user that part of the response was lost
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
        "Here's what I can do:\n\n"
        "Just talk to me — that's the main thing. Send text, voice, photos.\n\n"
        "Commands:\n"
        "/status — check if I'm running smoothly\n"
        "/fix — get me back online if I'm having trouble\n"
        "/profile — see what I know about you\n"
        "/profile update — refresh my memory\n"
        "/search <word> — find something I remember\n"
        "/forget <topic> — let go of something\n"
        "/ping — ask me for a check-in question\n"
        "/morning — get today's focus point\n"
        "/evening — start evening reflection\n"
        "/weekly — generate weekly review\n"
        "/resend — say that again\n\n"
        "Or just send me anything. I'll figure it out."
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
        f"I'm here and running smoothly.\n\n"
        f"Time: {_now()}\n"
        f"Memory: {mem_kb:.0f} KB across {daily_count} days\n"
        f"Your Telegram ID: {message.from_user.id}\n\n"
        f"If something feels off, send /fix and I'll get myself back online."
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
    # Two-step confirm
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
    # Reset evening state for this user
    evening_state.pop(message.from_user.id, None)
    _safe_reply(message, "Cancelled.")


@bot.message_handler(commands=["morning"])
def cmd_morning(message):
    """Triggered by automation at 9am (or manually)."""
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
    """Triggered by automation at 9pm (or manually)."""
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
    """Generate the weekly review now."""
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
    """Manual check-in. Bot asks one question based on current state."""
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
    """Toggle debug mode (shows memory footer on each message)."""
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


@bot.message_handler(commands=["checkboot"])
def cmd_checkboot(message):
    """Diagnose auto-start on boot issues — user-friendly, no technical jargon."""
    if not _auth_user(message):
        return

    import subprocess
    diagnostics = ["Boot Diagnostics:\n"]

    # Check if Termux:Boot is installed (but don't call it that to the user)
    try:
        result = subprocess.run(
            ["pm", "list", "packages", "com.termux.boot"],
            capture_output=True, text=True, timeout=5
        )
        if "com.termux.boot" in result.stdout:
            diagnostics.append("✓ Auto-start app is installed")
        else:
            diagnostics.append("✗ Auto-start app is NOT installed")
            diagnostics.append("  Install from: https://f-droid.org/packages/com.termux.boot/")
    except Exception:
        diagnostics.append("? Cannot check auto-start app status")

    # Check boot script exists
    boot_script = Path.home() / ".termux" / "boot" / "start-twin.sh"
    if boot_script.exists():
        diagnostics.append("✓ Startup script is configured")
    else:
        diagnostics.append("✗ Startup script is missing")
        diagnostics.append("  Run the keep-alive setup to fix this")

    # Check .bashrc auto-start
    bashrc = Path.home() / ".bashrc"
    if bashrc.exists() and "twin-start" in bashrc.read_text():
        diagnostics.append("✓ Auto-start is enabled")
    else:
        diagnostics.append("✗ Auto-start is NOT enabled")

    # Check .profile auto-start
    profile = Path.home() / ".profile"
    if profile.exists() and "twin-start" in profile.read_text():
        diagnostics.append("✓ Auto-start is in profile")
    else:
        diagnostics.append("✗ Auto-start is NOT in profile")

    diagnostics.append("\nIf auto-start fails after reboot:")
    diagnostics.append("1. Open the auto-start app once (registers with Android)")
    diagnostics.append("2. Set its battery to 'Unrestricted'")
    diagnostics.append("3. Set this app's battery to 'Unrestricted'")
    diagnostics.append("4. Reboot phone and wait 60 seconds")

    _safe_reply(message, "\n".join(diagnostics))


@bot.message_handler(commands=["fix"])
def cmd_fix(message):
    """One-tap recovery. Restarts the bot's connection and clears errors.

    The user never sees what broke. They just see: "I'm back online."
    """
    if not _auth_user(message):
        return

    _safe_reply(message, "Give me a moment. I'm getting myself back online...")

    # Clear all provider cooldowns
    try:
        for name, client in llm_client.providers:
            if hasattr(client, "_mark_success"):
                client._mark_success()
            if hasattr(client, "_cooldown_until"):
                client._cooldown_until = 0.0
            if hasattr(client, "_consecutive_failures"):
                client._consecutive_failures = 0
        log.info("All provider cooldowns cleared by /fix")
    except Exception as e:
        log.error(f"Error clearing cooldowns: {e}")

    # Also clear model_manager failures
    try:
        from model_manager import get_model_manager
        get_model_manager().clear_failures()
        log.info("Model manager failures cleared by /fix")
    except Exception as e:
        log.error(f"Error clearing model failures: {e}")

    # Send a test message
    _send_typing(message.chat.id)
    test_reply = _call_gemini("Say 'I'm back online' in 5 words or less.")
    if test_reply and not translate_error(test_reply).startswith("Something went wrong"):
        _safe_reply(message, "I'm back online. Everything's working now.")
    else:
        _safe_reply(
            message,
            "I'm still having trouble. My AI services might be busy. "
            "Try again in a minute, or send /status to check what's happening."
        )


@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    """View or update the twin's knowledge base."""
    if not _auth_user(message):
        return

    # Check if user wants to force an update
    text = message.text.partition(" ")[2].strip().lower()
    if text == "update":
        _send_typing(message.chat.id)
        _safe_reply(message, "Updating my understanding based on today's conversations...")
        try:
            today = cm.get_today_context()
            results = kb.update_all(llm_client, SYSTEM_PROMPT, today)
            updated_count = sum(1 for v in results.values() if v > 0)
            _safe_reply(message, f"Done. I refreshed {updated_count} areas of my understanding.")
        except Exception as e:
            _safe_reply(message, f"Update failed: {type(e).__name__}: {e}")
        return

    # Show the knowledge base
    knowledge = kb.get_all_knowledge()
    if not knowledge or len(knowledge) < 100:
        _safe_reply(message, "I'm still getting to know you. Talk to me more and I'll build my understanding.")
        return
    _safe_reply(message, f"Here's what I know:\n\n{knowledge}")


@bot.message_handler(commands=["resend"])
def cmd_resend(message):
    """Regenerate the last response (useful if chunks were lost)."""
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    # Get today's last user message
    today = cm.get_today_context()
    # Find the last "## HH:MM — user" entry
    import re
    user_messages = re.findall(
        r"## \d{2}:\d{2} — user\n(.*?)(?=\n## |\n> \*\*|$)",
        today, re.DOTALL
    )
    if not user_messages:
        _safe_reply(message, "I don't have a recent message to regenerate from.")
        return
    # Skip the /resend command itself
    last_user_msg = None
    for msg in reversed(user_messages):
        if not msg.strip().startswith("/resend") and not msg.strip().startswith("[voice]") and not msg.strip().startswith("[photo]"):
            last_user_msg = msg.strip()
            break
    if not last_user_msg:
        _safe_reply(message, "I don't have a recent message to regenerate from.")
        return
    # Log the resend request
    cm.append_to_today("user", "/resend (regenerating last response)")
    # Build prompt and call Gemini
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

    # If we're awaiting identity replacement
    if identity_pending:
        cm.update_identity(text)
        identity_pending = False
        _safe_reply(
            message,
            "Identity updated. I'll read this before every reply from now on."
        )
        return

    # Evening reflection flow
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

            # Now update the knowledge base based on today's conversations
            # This happens silently in the background after the reflection
            try:
                log.info("Updating knowledge base after evening reflection...")
                results = kb.update_all(llm_client, SYSTEM_PROMPT, today)
                updated_count = sum(1 for v in results.values() if v > 0)
                log.info(f"Knowledge base updated: {updated_count} domains refreshed")
            except Exception as e:
                log.error(f"Knowledge base update failed: {e}")
            return

    # Regular message — log it
    cm.append_to_today("user", text)

    # Check if we're already processing another message.
    # telebot processes sequentially, so if the user sent multiple messages
    # quickly, the earlier ones are still being processed. Let them know
    # we see their message but need a moment.
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

    # Acquire lock and process
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
        # Download the voice file
        file_info = bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
        r = requests.get(file_url, timeout=30)
        r.raise_for_status()
        ogg_bytes = r.content

        # Use Gemini to transcribe + respond (it can handle audio)
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
        # Get the largest photo
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
# The bot runs 24/7 in Termux, so it can trigger morning/evening/weekly
# pings itself — no need for MacroDroid or cron to send commands.
# MacroDroid is now optional backup only.
#
# The scheduler runs in a background thread and checks the time every
# 60 seconds. When it's time for a ping, it sends the message directly
# to the user via Telegram API (not as a /command to itself).

# Track what we've already triggered today so we don't double-fire
_last_morning_date = None
_last_evening_date = None
_last_weekly_date = None

# Scheduled times (24-hour format)
MORNING_HOUR = 9   # 9:00 AM
EVENING_HOUR = 21   # 9:00 PM
WEEKLY_DAY = 6      # Sunday (0=Monday, 6=Sunday)
WEEKLY_HOUR = 20    # 8:00 PM


def _send_direct_message(text: str) -> bool:
    """Send a message directly to the user (not as a reply).

    Used by the scheduler to initiate morning/evening/weekly pings
    without needing the user to send a command first.
    """
    try:
        bot.send_message(ALLOWED_USER_ID, text, timeout=60)
        return True
    except Exception as e:
        log.error(f"Direct message send failed: {e}")
        return False


def _trigger_morning():
    """Send the morning ping directly."""
    global _last_morning_date
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    _last_morning_date = today_str
    log.info("Triggering morning ping (internal scheduler)")

    today = cm.get_today_context()
    recent = cm.get_recent_days(days=2)
    current_time_str = now.strftime("%I:%M %p on %A, %B %d, %Y")
    prompt = f"""It is {current_time_str}. This is the morning ping.

The time above is the ACTUAL current time. Do not confuse this with evening or bedtime. If it says AM, it is morning. If the user was sleeping, they are now waking up.

Generate the morning message in the format described in your instructions:
- One thing that matters most today, based on yesterday's context
- A specific, small, doable step
- One sentence of context for why this is the thing
- End with a yes/no or short-answer question

Under 5 lines total. Be direct. Do NOT reference sleep, bedtime, or evening routines — it is morning.

# RECENT CONTEXT

{recent}

# TODAY SO FAR (if anything)

{today}
"""
    reply = _call_gemini(prompt)
    cm.append_to_today("twin", reply, observation="morning ping (auto)")
    _send_direct_message(reply)


def _trigger_evening():
    """Start the evening reflection directly."""
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
    """Generate the weekly review directly."""
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
        # Send the summary (may be long, use _send_direct_message in chunks)
        MAX = 4000
        if len(summary) <= MAX:
            _send_direct_message(summary)
        else:
            # Split into chunks
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
    """Background thread that checks the time every minute and triggers
    morning/evening/weekly pings at the scheduled times.

    Runs independently of Telegram polling — even if the network hiccups,
    the scheduler keeps running.
    """
    global _last_morning_date, _last_evening_date, _last_weekly_date
    log.info("Internal scheduler started "
             f"(morning={MORNING_HOUR}:00, evening={EVENING_HOUR}:00, "
             f"weekly=Sunday {WEEKLY_HOUR}:00)")

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # Morning ping (9:00 AM)
            if (now.hour == MORNING_HOUR and now.minute == 0
                    and _last_morning_date != today_str):
                _trigger_morning()

            # Evening ping (9:00 PM)
            if (now.hour == EVENING_HOUR and now.minute == 0
                    and _last_evening_date != today_str):
                _trigger_evening()

            # Weekly review (Sunday 8:00 PM)
            if (now.weekday() == WEEKLY_DAY
                    and now.hour == WEEKLY_HOUR and now.minute == 0
                    and _last_weekly_date != today_str):
                _trigger_weekly()

        except Exception as e:
            log.error(f"Scheduler error: {e}")

        # Check every 60 seconds
        time.sleep(60)


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #

def main() -> None:
    log.info("=" * 60)
    log.info("AI Twin starting up")
    log.info(f"  Memory dir: {MEMORY_DIR}")
    log.info(f"  LLM provider: {LLM_PROVIDER}")
    log.info(f"  LLM model: {LLM_MODEL}")
    log.info(f"  Allowed user: {ALLOWED_USER_ID}")
    log.info(f"  Library: pyTelegramBotAPI (telebot)")
    log.info(f"  Scheduler: morning={MORNING_HOUR}am, "
             f"evening={EVENING_HOUR}pm, "
             f"weekly=Sunday {WEEKLY_HOUR}pm")
    log.info("=" * 60)
    log.info("Bot running. Press Ctrl+C to stop.")

    # Start the internal scheduler in a background thread
    scheduler_thread = threading.Thread(target=_scheduler_loop,
                                        daemon=True)
    scheduler_thread.start()
    log.info("Scheduler thread started")

    # Wrap polling in a retry loop. Android's network management kills
    # long-polling connections periodically (ConnectionAbortedError 103).
    # AdGuard toggling also kills all connections for 15-30 seconds.
    # We wait for network to return before reconnecting.
    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=30,
                # Don't let telebot's internal error handler swallow crashes
                # that we want to catch and retry
                logger_level=None,
            )
        except KeyboardInterrupt:
            log.info("Bot stopped by user.")
            break
        except (ConnectionError, OSError, Exception) as e:
            # ConnectionAbortedError, ConnectionResetError, network blips,
            # AdGuard toggling, Android doze mode — all of these crash
            # infinity_polling. Wait for network to return, then reconnect.
            log.warning(
                f"Polling crashed: {type(e).__name__}: {e}. "
                f"Checking network..."
            )
            # Wait for network to come back (up to 90 seconds)
            if _wait_for_network(max_wait=90):
                log.info("Network is back. Reconnecting in 5 seconds...")
                time.sleep(5)
            else:
                log.warning(
                    f"Network still down after 90s. "
                    f"Will keep retrying every 30 seconds..."
                )
                # Keep trying indefinitely — the bot should never give up
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
