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
import random
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
    "free",  # FreeLLMAPI is always available (no key needed)
    os.environ.get("GROQ_API_KEY", "").strip(),
    os.environ.get("OPENROUTER_API_KEY", "").strip(),
    os.environ.get("MISTRAL_API_KEY", "").strip(),
    os.environ.get("CEREBRAS_API_KEY", "").strip(),
    os.environ.get("ZAI_API_KEY", "").strip(),
    GEMINI_API_KEY,
]
if not any(_llm_keys):
    log.error("No LLM API key found. Set at least one of: "
              "GROQ_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY, "
              "CEREBRAS_API_KEY, ZAI_API_KEY, GEMINI_API_KEY")
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

# Read the base system prompt
with open(Path(__file__).parent / "system_prompt.txt", "r", encoding="utf-8") as f:
    _base_prompt = f.read()

# Build the voice profile block (goes at the TOP for primacy bias)
_voice_block = ""
_voice_path = Path.home() / "ai-twin-memory" / "voice_profile.md"
if _voice_path.exists():
    _voice = _voice_path.read_text(encoding="utf-8").strip()
    if _voice:
        _voice_block = (
            "### YOUR VOICE — MANDATORY — ADOPT THIS FOR EVERY MESSAGE\n\n"
            "This is YOUR voice. Not information about the user. YOUR voice when "
            "you write to the user. Every message you send must sound like this. "
            "This is not a suggestion. This is how you talk.\n\n"
            f"{_voice}\n\n"
        )
        log.info(f"Loaded voice profile from {_voice_path}")
    else:
        _voice_block = (
            "### YOUR VOICE\n\nNo voice profile set. Default to: short sentences, "
            "heavy contractions, casual tone, no fancy words, direct questions, "
            "no greetings or sign-offs.\n\n"
        )
else:
    _voice_block = (
        "### YOUR VOICE\n\nNo voice profile set. Default to: short sentences, "
        "heavy contractions, casual tone, no fancy words, direct questions, "
        "no greetings or sign-offs.\n\n"
    )

# Build the kill file block (goes right after the voice profile)
_kill_block = ""
_kill_path = Path.home() / "ai-twin-memory" / "banned_phrases.txt"
if _kill_path.exists():
    _kill = _kill_path.read_text(encoding="utf-8").strip()
    if _kill:
        _kill_block = (
            "### YOUR KILL FILE (personal banned phrases — never use these)\n\n"
            f"{_kill}\n\n"
        )
        log.info(f"Loaded kill file from {_kill_path}")

# Build the final check block (goes at the BOTTOM for recency bias)
_final_check = """
### FINAL CHECK BEFORE EVERY MESSAGE

Before you send any message to the user, re-read it. Does it sound like YOUR VOICE (the voice profile above)? If it sounds like a chatbot, an AI assistant, a helpful robot, a customer service agent, or anything other than a friend texting a friend — REWRITE IT.

The voice profile is not a suggestion. It is how you talk. Every message. No exceptions. If you can't tell whether it sounds right, read it out loud — if it sounds like something you'd never text a friend, it's wrong.
"""

# Assemble: voice profile (primacy) + kill file + base prompt + final check (recency)
SYSTEM_PROMPT = _voice_block + _kill_block + _base_prompt + _final_check

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

    NOTE: We do NOT use reply_to_message_id. The user doesn't want the
    "reply to" preview that Telegram shows above messages. All messages
    are sent as standalone messages in the chat.

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
            # Always send as standalone message (no reply_to_message_id)
            # This removes the "reply preview" that Telegram shows
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
        "/morning — what's the one thing today\n"
        "/evening — update my understanding\n"
        "/weekly — generate weekly review\n"
        "/search <word> — find something I remember\n"
        "/forget <topic> — let go of something\n"
        "/ping — ask me for a check-in question\n"
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
    """Morning prompt — now uses the knowledge base for context."""
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    knowledge = kb.get_all_knowledge()
    prompt = f"""{knowledge}

# YOUR TASK
The user just asked for their morning prompt. Look at what you know about them — their tasks, upcoming events, open threads — and tell them the ONE thing that matters most today. Be specific. Reference real items from their life. End with a short question.

Keep it under 5 lines. No pre-exposition. No closing wrapper. Just the point.
"""
    reply = _call_gemini(prompt)
    cm.append_to_today("twin", reply, observation="morning prompt")
    _safe_reply(message, reply)


@bot.message_handler(commands=["evening"])
def cmd_evening(message):
    """Evening — now triggers a knowledge base update instead of 3 questions."""
    if not _auth_user(message):
        return
    _send_typing(message.chat.id)
    _safe_reply(message, "Updating my understanding of today...")
    try:
        today = cm.get_today_context()
        results = kb.update_all(llm_client, SYSTEM_PROMPT, today)
        updated_count = sum(1 for v in results.values() if v > 0)
        _safe_reply(message, f"Done. I refreshed {updated_count} areas of my understanding.")
    except Exception as e:
        _safe_reply(message, f"Update failed: {type(e).__name__}: {e}")


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

    # Evening reflection flow — DISABLED per user request
    # The evening reflection was causing duplicate messages and no longer
    # serves a purpose. Knowledge base auto-updates capture the same info.
    user_id = message.from_user.id
    step = evening_state.get(user_id)
    if step:
        # Clear the evening state so it doesn't loop
        evening_state.pop(user_id, None)
        _safe_reply(message, "I've got everything I need from today. No more questions.")
        # Trigger a knowledge base update instead
        try:
            today = cm.get_today_context()
            threading.Thread(target=lambda: kb.update_all(
                llm_client, SYSTEM_PROMPT, today
            ), daemon=True).start()
        except Exception:
            pass
        return

    # Regular message — log it
    cm.append_to_today("user", text)

    # Track when the user last messaged (for proactive messaging)
    global _last_user_message_time
    _last_user_message_time = time.time()

    # CANCEL pending proactive reminders that are now redundant
    # If the user just messaged about something we were going to remind
    # them about, cancel that reminder — they already know.
    _cancel_redundant_reminders(text)

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

        # Auto-update knowledge base after conversations (not just evening)
        # This runs in a background thread so it doesn't delay the response
        # Only updates if there are enough new messages since last update
        try:
            _trigger_incremental_kb_update()
        except Exception as e:
            log.error(f"Incremental KB update trigger failed: {e}")
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

# Track incremental knowledge base updates
_last_kb_update_time = 0.0  # timestamp of last KB update
_kb_message_counter = 0  # messages since last KB update
_KB_UPDATE_INTERVAL = 5  # update KB every N messages
_KB_MIN_SECONDS_BETWEEN = 120  # at least 2 minutes between updates

# ----------------------------------------------------------------------
# PROACTIVE MESSAGING — INTELLIGENT, NOT TIMER-BASED
# ----------------------------------------------------------------------
# Old approach: message every 2 hours of silence. Predictable. Bot-like.
#
# New approach: score reach-out opportunities every 15 minutes. Only
# send when there's something specific to say. Variability built in:
#   - 30% random skip even when trigger fires
#   - 0-15min random delay after trigger
#   - Max 3 proactive messages per day (excl. appointment reminders)
#   - Min 2h gap between proactive messages
#   - Don't message if user was emotional recently (give space)
#   - Don't message during quiet hours (11pm-7am)
#   - Don't message if user just messaged (within 30 min)
#
# Triggers scored:
#   - Blocked tasks waiting on external dependency
#   - Task deadline within 24-48 hours
#   - Morning briefing (7-10am, once per day)
#   - Midday light check (12-2pm, if silence > 3h)
#   - Evening followup (5-8pm, if user had appointments)
#   - Long silence (>6h, ONE message max — don't keep bugging)
#   - New RSS content detected
#
# Each trigger has a relevance score and timing score. Combined
# score must clear a threshold to send. This is what makes it feel
# human — the twin reaches out when it has something to say, not
# when a timer fires.
# ----------------------------------------------------------------------

# Appointment-reminder dedup set (shared by appointment + silence paths)
_proactive_reminders_sent = set()

# Old constants — kept for backward compat with _check_silence (which
# is now unused by the smart loop but still defined below). The smart
# loop does NOT read these.
_last_silence_check_time = 0.0
_SILENCE_CHECK_INTERVAL = 3600  # deprecated; smart loop uses _PROACTIVE_CHECK_INTERVAL_SMART
_PROACTIVE_SILENCE_THRESHOLD = 7200  # deprecated; smart loop scores silence windows differently

# New proactive constants
_PROACTIVE_CHECK_INTERVAL_SMART = 900  # Check every 15 minutes
_PROACTIVE_MAX_DAILY = 3  # Max proactive (non-appointment) messages per day
_PROACTIVE_MIN_GAP = 7200  # Min 2 hours between proactive messages
_PROACTIVE_QUIET_HOURS = (23, 7)  # 11pm to 7am

# New proactive state
_proactive_sent_today = 0
_proactive_last_reset_date = None
_proactive_last_send_time = 0.0

# Defensive: _last_user_message_time was only bound inside a handler.
# The proactive loop reads it on every tick — make sure it exists at
# module load time so the first ~15 min of idle don't crash the loop.
_last_user_message_time = 0.0

# Scheduled times (24-hour format) — DISABLED per user request
# Morning/evening/weekly routines removed. The twin no longer pings on a schedule.
# Proactive messaging (event-driven) replaces these routines.
MORNING_HOUR = None
EVENING_HOUR = None
WEEKLY_DAY = None
WEEKLY_HOUR = None


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


def _trigger_incremental_kb_update():
    """Trigger a background knowledge base update after conversations.

    Instead of waiting for evening reflection, this updates the knowledge
    base every few messages. This means the twin's understanding stays
    current throughout the day — tasks completed, situations changed,
    new information learned — without the user having to explicitly ask.

    Runs in a background thread so it doesn't delay the response.
    """
    global _kb_message_counter, _last_kb_update_time

    _kb_message_counter += 1

    # Only update if enough messages have passed AND enough time has passed
    now = time.time()
    if _kb_message_counter < _KB_UPDATE_INTERVAL:
        return
    if now - _last_kb_update_time < _KB_MIN_SECONDS_BETWEEN:
        return

    # Reset counter and start update in background
    _kb_message_counter = 0
    _last_kb_update_time = now

    def update_in_background():
        try:
            log.info("Triggering incremental knowledge base update...")
            today = cm.get_today_context()
            if today and len(today) > 100:
                results = kb.update_all(llm_client, SYSTEM_PROMPT, today)
                updated_count = sum(1 for v in results.values() if v > 0)
                log.info(f"Incremental KB update done: {updated_count} domains refreshed")
        except Exception as e:
            log.error(f"Incremental KB update failed: {e}")

    # Run in background thread
    threading.Thread(target=update_in_background, daemon=True).start()


def _proactive_messaging_loop_smart():
    """Intelligent proactive messaging. Not timer-based.

    Scores reach-out opportunities each check. Only sends when:
    - There's something specific to say (not "just checking in")
    - Timing fits the message
    - Daily cap not exceeded
    - Variability (30% random skip, 0-15min random delay)

    A real friend doesn't text you every 2 hours on a schedule. They text
    when they have something to share. So does this.
    """
    global _proactive_sent_today, _proactive_last_reset_date, _proactive_last_send_time

    log.info("Smart proactive messaging started (event-scored, not timer-based)")

    while True:
        time.sleep(_PROACTIVE_CHECK_INTERVAL_SMART)  # Check every 15 minutes

        try:
            now = datetime.now()
            now_ts = time.time()

            # Reset daily counter at midnight
            if _proactive_last_reset_date != now.date():
                _proactive_sent_today = 0
                _proactive_last_reset_date = now.date()

            # Quiet hours — no proactive messages 11pm to 7am
            if now.hour >= _PROACTIVE_QUIET_HOURS[0] or now.hour < _PROACTIVE_QUIET_HOURS[1]:
                continue

            # User just messaged (within 30 min) — give them space
            if now_ts - _last_user_message_time < 1800:
                continue

            # Daily cap reached
            if _proactive_sent_today >= _PROACTIVE_MAX_DAILY:
                # Still check appointment reminders (time-critical, separate path)
                _check_upcoming_appointments(now)
                continue

            # Min gap between proactive messages
            if now_ts - _proactive_last_send_time < _PROACTIVE_MIN_GAP:
                # Still check appointment reminders (time-critical, separate path)
                _check_upcoming_appointments(now)
                continue

            # Check for emotional context — if user was emotional recently, give space
            if _user_was_emotional_recently():
                continue

            # Check appointment reminders (still time-critical, separate path).
            # These do NOT count toward the daily proactive cap.
            _check_upcoming_appointments(now)

            # Score opportunities
            opportunity = _score_proactive_opportunity(now)
            if not opportunity:
                continue

            # 30% random skip (variability) — even valid triggers don't always fire
            if random.random() < 0.30:
                log.info(f"Proactive opportunity found ({opportunity['reason']}) — randomly skipped for variability")
                continue

            # Random delay 0-15 minutes (so timing isn't predictable)
            delay_seconds = random.randint(0, 900)
            log.info(f"Proactive opportunity: {opportunity['reason']}. Sending in {delay_seconds}s.")

            # Sleep in chunks so a shutdown is responsive (daemon thread dies with
            # the process anyway, but chunking avoids holding a long sleep that
            # would block testing). 60s chunks.
            slept = 0
            while slept < delay_seconds:
                time.sleep(min(60, delay_seconds - slept))
                slept += 60
                # If the user messaged during the delay, abort — they're here.
                if time.time() - _last_user_message_time < 300:
                    log.info("User messaged during delay. Skipping proactive.")
                    slept = delay_seconds  # break out
                    break

            # Re-check after delay (in case user messaged during the delay)
            if time.time() - _last_user_message_time < 300:
                continue

            # Send the message
            _send_smart_proactive(opportunity)

            _proactive_sent_today += 1
            _proactive_last_send_time = time.time()

        except Exception as e:
            log.error(f"Smart proactive check error: {e}")


def _user_was_emotional_recently() -> bool:
    """Check if the user sent something emotional in the last hour.

    If so, give them space — don't proactively message.
    """
    try:
        log_path = Path(MEMORY_DIR) / "today.md"
        if not log_path.exists():
            return False

        # Get the last ~2KB of the conversation log
        content = log_path.read_text(encoding="utf-8")
        recent = content[-2000:] if len(content) > 2000 else content
        recent_lower = recent.lower()

        # Only consider it "emotional" if the message is from the LAST HOUR.
        # today.md entries are timestamped; cheap check: look for a recent
        # timestamp near the tail of the file. If the file's mtime is older
        # than an hour, the user clearly hasn't said anything recently.
        mtime = log_path.stat().st_mtime
        if time.time() - mtime > 3600:
            return False

        emotional_markers = [
            "i need you", "i'm tired", "i cant", "i can't", "i'm done", "i'm over it",
            "help", "i don't know", "i dont know", "i'm scared", "i'm overwhelmed",
            "i miss", "i hate this", "this is hard", "give up",
            "my babe", "im tired", "im done", "im over it", "im scared",
            "im overwhelmed", "exhausted", "burnt out", "burned out",
        ]
        for marker in emotional_markers:
            if marker in recent_lower:
                return True
        return False
    except Exception:
        return False


def _score_proactive_opportunity(now: datetime) -> Optional[dict]:
    """Find something specific to reach out about. Returns the opportunity or None.

    Looks for concrete reasons to message — not just "you've been silent."
    """
    opportunities = []

    try:
        # Load tasks once — used by multiple checks
        try:
            from tools import _load_tasks, tool_task_review
            tasks = _load_tasks()
            review = tool_task_review()
        except Exception:
            tasks = []
            review = ""

        # 1. Blocked task waiting on external dependency
        if tasks and review and "BLOCKED" in review:
            blocked_tasks = [t for t in tasks
                             if t.get("status") in ("blocked", "waiting")]
            if blocked_tasks:
                opportunities.append({
                    "reason": "blocked_tasks",
                    "context": review[:500],
                    "timing_score": 0.7,
                    "relevance_score": 0.8,
                })

        # 2. Task with deadline in next 24-48 hours
        soon = now + timedelta(hours=48)
        import re
        for t in tasks:
            due_str = t.get("due_date", "")
            if not due_str:
                continue
            try:
                date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', due_str)
                if date_match:
                    due_date = datetime(int(date_match.group(1)),
                                        int(date_match.group(2)),
                                        int(date_match.group(3)))
                    if now < due_date <= soon:
                        opportunities.append({
                            "reason": "deadline_approaching",
                            "context": f"Task '{t.get('title', 'unknown')}' is due {due_str}",
                            "timing_score": 0.9,
                            "relevance_score": 0.9,
                        })
            except Exception:
                pass

        # 3. Time-of-day based opportunity (only if there's something to say)
        hour = now.hour
        if 7 <= hour < 10:
            # Morning — could send "here's what's on your plate" if we haven't yet today
            if not _sent_morning_briefing_today():
                if tasks:
                    active_tasks = [t for t in tasks if t.get("status") == "active"]
                    if active_tasks:
                        opportunities.append({
                            "reason": "morning_briefing",
                            "context": review[:500] if review else
                                      f"You have {len(active_tasks)} active tasks.",
                            "timing_score": 0.8,
                            "relevance_score": 0.7,
                        })
        elif 12 <= hour < 14:
            # Midday — could send a light "you good?" if silence is long
            silence_hours = (time.time() - _last_user_message_time) / 3600
            if silence_hours > 3:
                opportunities.append({
                    "reason": "midday_check",
                    "context": f"Silent for {silence_hours:.1f}h. Light check-in.",
                    "timing_score": 0.5,
                    "relevance_score": 0.4,
                })
        elif 17 <= hour < 20:
            # Evening — could ask "how'd today go" if there were appointments today
            try:
                upcoming = kb.get_domain("upcoming.md") or ""
                today_str = now.strftime("%Y-%m-%d")
                if today_str in upcoming:
                    opportunities.append({
                        "reason": "evening_followup",
                        "context": "You had appointments today. How'd they go?",
                        "timing_score": 0.7,
                        "relevance_score": 0.8,
                    })
            except Exception:
                pass
        # 21-23 (late evening): intentionally NOT a trigger — let the user
        # initiate reflection. Don't push reflection on them.

        # 4. Silence that's longer than usual — only ONE message, not repeated
        silence_hours = (time.time() - _last_user_message_time) / 3600
        if silence_hours > 6:
            silence_key = f"long_silence_{int(_last_user_message_time)}"
            if silence_key not in _proactive_reminders_sent:
                opportunities.append({
                    "reason": "long_silence",
                    "context": f"Silent for {silence_hours:.1f}h.",
                    "timing_score": 0.4,
                    "relevance_score": 0.3,
                    "dedup_key": silence_key,
                })

        # 5. New RSS items in user's subscribed feeds
        try:
            rss_seen_path = Path(MEMORY_DIR) / "rss_seen.json"
            if rss_seen_path.exists():
                mtime = rss_seen_path.stat().st_mtime
                if time.time() - mtime < 1800:
                    opportunities.append({
                        "reason": "new_rss_content",
                        "context": "New content in your RSS feeds. Want me to send the digest?",
                        "timing_score": 0.6,
                        "relevance_score": 0.7,
                    })
        except Exception:
            pass

        # Score and pick the best opportunity
        if not opportunities:
            return None

        # Combined score = relevance * timing, with a small random jitter
        best = max(opportunities, key=lambda o: o["relevance_score"] * o["timing_score"]
                                          + random.random() * 0.1)

        # If the best score is too low, don't send — better silent than spammy
        if best["relevance_score"] * best["timing_score"] < 0.3:
            return None

        return best

    except Exception as e:
        log.error(f"Opportunity scoring error: {e}")
        return None


def _sent_morning_briefing_today() -> bool:
    """Check if we already sent a morning briefing today."""
    try:
        tracker = Path(MEMORY_DIR) / "proactive_state.json"
        if not tracker.exists():
            return False
        import json
        state = json.loads(tracker.read_text(encoding="utf-8"))
        return state.get("morning_briefing_date") == datetime.now().date().isoformat()
    except Exception:
        return False


def _mark_morning_briefing_sent():
    """Record that we sent the morning briefing today."""
    try:
        tracker = Path(MEMORY_DIR) / "proactive_state.json"
        import json
        state = {}
        if tracker.exists():
            state = json.loads(tracker.read_text(encoding="utf-8"))
        state["morning_briefing_date"] = datetime.now().date().isoformat()
        tracker.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"Could not mark morning briefing sent: {e}")


def _send_smart_proactive(opportunity: dict):
    """Send an intelligent proactive message based on the opportunity."""
    try:
        reason = opportunity.get("reason", "unknown")
        context = opportunity.get("context", "")

        # Different prompts for different reasons
        if reason == "morning_briefing":
            prompt = f"""Write a 2-4 sentence morning brief to TYKO about today. Reference specific tasks. End with one direct question. Casual, lowercase, contractions, no AI-speak.

Task context:
{context}

Write the message:"""
            _mark_morning_briefing_sent()
        elif reason == "blocked_tasks":
            prompt = f"""Write a 1-2 sentence check-in to TYKO. They have blocked tasks. Don't nag. Just acknowledge the situation and ask if they want help. Casual, lowercase, contractions, no AI-speak.

Task context:
{context}

Write the message:"""
        elif reason == "deadline_approaching":
            prompt = f"""Write a 1-2 sentence reminder to TYKO about a deadline. Be specific. End with one direct question. Casual, lowercase, contractions, no AI-speak.

Context:
{context}

Write the message:"""
        elif reason == "midday_check":
            prompt = """Write a 1-sentence light check-in to TYKO. Not clingy. Just "you good?" energy. Casual, lowercase, contractions, no AI-speak.

Write the message:"""
        elif reason == "evening_followup":
            prompt = f"""Write a 1-2 sentence evening check-in to TYKO about their appointments today. Casual, lowercase, contractions, no AI-speak.

Context:
{context}

Write the message:"""
        elif reason == "long_silence":
            prompt = f"""Write a 1-sentence check-in to TYKO who's been silent for a while. Not clingy. Just "what's up" energy. Casual, lowercase, contractions, no AI-speak.

Context:
{context}

Write the message:"""
        elif reason == "new_rss_content":
            prompt = """Write a 1-sentence note to TYKO saying there's new content in their RSS feeds if they want to check. Casual, lowercase, contractions, no AI-speak.

Write the message:"""
        else:
            log.warning(f"Unknown proactive reason: {reason} — skipping")
            return  # Unknown reason, don't send

        response = llm_client.generate(
            prompt=prompt,
            system_instruction="You write like a friend texting another friend. Short, lowercase, contractions, casual. No AI-speak. No 'how are you' openers. No 'just checking in.'",
        )
        msg = (response or "").strip()
        if msg:
            _send_telegram_message(ALLOWED_USER_ID, msg)
            cm.append_to_today("twin", f"Smart proactive: {reason}",
                               observation="proactive")
            log.info(f"Sent smart proactive: {reason}")

            # Mark dedup keys (e.g., long_silence) so the same trigger
            # doesn't fire again for the same silence period.
            dedup_key = opportunity.get("dedup_key")
            if dedup_key:
                _proactive_reminders_sent.add(dedup_key)
    except Exception as e:
        log.error(f"Smart proactive send failed: {e}")


def _check_upcoming_appointments(now: datetime):
    """Check the knowledge base for upcoming appointments. Zero tokens.

    Parses the upcoming.md file locally (string matching) to find
    appointments within the next hour or next 24 hours. Only calls the
    LLM to generate the reminder message when an event is confirmed.
    """
    try:
        upcoming = kb.get_domain("upcoming.md")
        if not upcoming:
            return

        now_ts = now.timestamp()

        # Parse upcoming.md for date patterns
        # Look for lines with dates and times
        import re
        from datetime import timedelta

        # Find date+time patterns like "2026-09-07 at 11:30" or "September 7 at 11:30 AM"
        date_patterns = [
            # ISO format: 2026-09-07 at 11:30
            (r'(\d{4}-\d{2}-\d{2})\s+at\s+(\d{1,2}:\d{2})\s*(AM|PM)?',
             lambda m: f"{m.group(1)} {m.group(2)} {'AM' if m.group(3) == 'AM' else 'PM' if m.group(3) else ''}".strip()),
            # "September 7" or "September 7 at 11:30 AM"
            (r'(\w+\s+\d{1,2})(?:\s+at\s+(\d{1,2}:\d{2})\s*(AM|PM)?)?',
             None),  # Complex parsing, skip for now
        ]

        # Simple approach: look for absolute dates in the upcoming file
        # and check if any are within the next hour or 24 hours
        lines = upcoming.split('\n')
        for line in lines:
            # Look for ISO dates
            date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', line)
            if date_match:
                try:
                    event_date = datetime(int(date_match.group(1)),
                                        int(date_match.group(2)),
                                        int(date_match.group(3)))
                    # Check for time in the same line
                    time_match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', line)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        if time_match.group(3) and time_match.group(3).upper() == 'PM' and hour != 12:
                            hour += 12
                        elif time_match.group(3) and time_match.group(3).upper() == 'AM' and hour == 12:
                            hour = 0
                        event_date = event_date.replace(hour=hour, minute=minute)

                    event_ts = event_date.timestamp()
                    hours_until = (event_ts - now_ts) / 3600

                    # Within 1 hour — urgent reminder
                    if 0 < hours_until <= 1:
                        reminder_key = f"urgent_{date_match.group(0)}"
                        if reminder_key not in _proactive_reminders_sent:
                            _proactive_reminders_sent.add(reminder_key)
                            _send_proactive_reminder(
                                line, hours_until, urgent=True
                            )

                    # Within 24 hours — heads-up (sent once)
                    elif 1 < hours_until <= 24:
                        reminder_key = f"heads_up_{date_match.group(0)}"
                        if reminder_key not in _proactive_reminders_sent:
                            _proactive_reminders_sent.add(reminder_key)
                            _send_proactive_reminder(
                                line, hours_until, urgent=False
                            )

                except Exception:
                    pass  # Date parsing failed, skip

    except Exception as e:
        log.error(f"Appointment check failed: {e}")


def _send_proactive_reminder(event_text: str, hours_until: float, urgent: bool):
    """Generate and send a proactive reminder. This is the ONLY point
    where tokens are used — to generate the message text.

    Even here, we use a very short prompt to minimize token usage.
    """
    try:
        # Very short, cheap prompt — just generate a natural reminder
        if urgent:
            prompt = f"Write a 1-2 sentence reminder to someone that they have something in {hours_until:.0f} minutes. Event: {event_text[:200]}. Be natural, specific, and brief. No greeting."
        else:
            prompt = f"Write a 1-2 sentence heads-up to someone that they have something in about {hours_until:.0f} hours. Event: {event_text[:200]}. Be natural, specific, and brief. No greeting."

        response = llm_client.generate(
            prompt=prompt,
            system_instruction="Write a short, natural text message. Be brief and specific. No fluff.",
        )

        if response and len(response) > 5:
            _send_telegram_message(ALLOWED_USER_ID, response)
            cm.append_to_today("twin", response, observation="proactive reminder")
            log.info(f"Sent proactive reminder ({'urgent' if urgent else 'heads-up'}): {response[:80]}...")

    except Exception as e:
        log.error(f"Proactive reminder failed: {e}")


def _check_silence(now_ts: float):
    """Check if the user has been silent long enough to warrant a check-in.

    Uses the task_review tool to find something useful to suggest.
    Only fires if:
    - User hasn't messaged in 2+ hours
    - We haven't already sent a check-in for this silence period
    - There are tasks in tasks.json
    """
    global _last_user_message_time

    silence_duration = now_ts - _last_user_message_time
    if silence_duration < _PROACTIVE_SILENCE_THRESHOLD:
        return

    # Check if there are tasks via the new tool
    try:
        from tools import _load_tasks
        tasks = _load_tasks()
        if not tasks:
            return
    except Exception:
        # Fallback to old knowledge_base check
        tasks_md = kb.get_domain("tasks.md")
        if not tasks_md or len(tasks_md) < 20:
            return

    # Check if we already sent a silence check-in after the last user message
    silence_key = f"silence_{int(_last_user_message_time)}"
    if silence_key in _proactive_reminders_sent:
        return

    _proactive_reminders_sent.add(silence_key)

    # Use task_review to get smart suggestions
    try:
        from tools import tool_task_review
        review = tool_task_review()
    except Exception:
        review = None

    # Generate a specific check-in
    try:
        if review and len(review) > 50:
            prompt = f"""Write a 1-3 sentence check-in text to TYKO who hasn't talked to you in {silence_duration/3600:.0f} hours. Use this task review to reference something specific. Be casual, not clingy. No "how are you." No "just checking in." Reference a real task or blocked item. End with one direct question.

Task review:
{review}

Write the message now (in TYKO's voice — short, casual, lowercase, contractions):"""
        else:
            prompt = f"""Write a 1-2 sentence check-in text to TYKO who hasn't talked to you in {silence_duration/3600:.0f} hours. Be casual, not clingy. No "how are you." No "just checking in." Reference something from their life. End with one direct question.

Write the message now (in TYKO's voice — short, casual, lowercase, contractions):"""

        response = llm_client.generate(
            prompt=prompt,
            system_instruction="You write like a friend texting another friend. Short, lowercase, contractions, casual. No AI-speak. No 'how are you' openers.",
        )
        msg = (response or "").strip()
        if msg:
            _send_telegram_message(ALLOWED_USER_ID, msg)
            cm.append_to_today("twin", f"Proactive silence check-in sent after {silence_duration/3600:.0f}h silence", observation="proactive")
            log.info(f"Sent silence check-in after {silence_duration/3600:.0f}h silence")
    except Exception as e:
        log.error(f"Silence check-in failed: {e}")


def _safe_reply_to_user(text: str):
    """Send a message to the user as a proactive check-in."""
    try:
        _send_telegram_message(ALLOWED_USER_ID, text)
        cm.append_to_today("twin", text, observation="proactive message")
    except Exception as e:
        log.error(f"Proactive message send failed: {e}")


def _website_monitoring_loop():
    """Background thread that checks monitored websites for changes.

    Zero tokens when idle. Only uses tokens when a change is detected
    and the twin needs to generate a notification message.
    """
    from tools import _check_monitored_sites, _load_monitored_sites
    log.info("Website monitoring started (checks every 5 minutes)")

    while True:
        time.sleep(300)  # Check every 5 minutes

        try:
            sites = _load_monitored_sites()
            active = [s for s in sites if s.get("active")]
            if not active:
                continue  # Nothing to monitor

            # Quiet hours — don't send change notifications at night
            now = datetime.now()
            if now.hour >= 23 or now.hour < 7:
                continue

            changed = _check_monitored_sites()

            for change in changed:
                # Send notification about the change
                try:
                    _send_telegram_message(
                        ALLOWED_USER_ID,
                        f"Website changed: {change['description']}\n"
                        f"URL: {change['url']}\n\n"
                        f"Go check it."
                    )
                    cm.append_to_today("twin",
                        f"Website change detected: {change['url']}",
                        observation="website monitor")
                    log.info(f"Website change detected: {change['url']}")
                except Exception as e:
                    log.error(f"Failed to send website change notification: {e}")

        except Exception as e:
            log.error(f"Website monitoring error: {e}")


def _rss_monitoring_loop():
    """Background thread that checks subscribed RSS feeds.

    Reads the list of feeds from ~/ai-twin-memory/rss_feeds.txt (one URL per line).
    Checks each feed every 30 minutes, stores the latest item timestamp per feed,
    and notifies the user when a new item appears.

    Zero tokens when idle. Only uses tokens when a new item is detected.
    """
    from tools import tool_read_rss
    feeds_file = Path.home() / "ai-twin-memory" / "rss_feeds.txt"
    seen_file = Path.home() / "ai-twin-memory" / "rss_seen.json"
    log.info("RSS monitoring started (checks every 30 minutes)")

    # Load the "already seen" set
    def load_seen() -> dict:
        try:
            if seen_file.exists():
                return json.loads(seen_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_seen(seen: dict) -> None:
        try:
            seen_file.write_text(json.dumps(seen, indent=2), encoding="utf-8")
        except Exception as e:
            log.error(f"Could not save RSS seen file: {e}")

    while True:
        time.sleep(1800)  # Check every 30 minutes

        try:
            if not feeds_file.exists():
                continue
            feeds = [line.strip() for line in feeds_file.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#")]
            if not feeds:
                continue

            # Quiet hours — don't send RSS notifications at night
            now = datetime.now()
            if now.hour >= 23 or now.hour < 7:
                continue

            seen = load_seen()

            for feed_url in feeds:
                try:
                    # Fetch latest 5 items
                    result = tool_read_rss(feed_url, limit=5)
                    # Parse out items (the format is "1. Title\n   Published: ...\n   Link: ...")
                    import re
                    items = re.findall(r"\d+\.\s+(.+?)\n\s+Published:\s+(.+?)\n\s+Link:\s+(\S+)", result)
                    if not items:
                        continue

                    feed_seen = seen.get(feed_url, [])
                    new_items = []
                    for title, pub, link in items:
                        # Use link as the dedup key
                        if link not in feed_seen:
                            new_items.append((title, pub, link))

                    if not new_items:
                        continue

                    # Send notification
                    if len(new_items) == 1:
                        title, pub, link = new_items[0]
                        msg = f"📡 New item in feed:\n{title}\n{link}"
                    else:
                        msg = f"📡 {len(new_items)} new items in feed:\n"
                        for title, _, link in new_items[:3]:
                            msg += f"  • {title}\n    {link}\n"
                        if len(new_items) > 3:
                            msg += f"  ... and {len(new_items) - 3} more"

                    _send_telegram_message(ALLOWED_USER_ID, msg)
                    cm.append_to_today("twin",
                        f"RSS new items for {feed_url}: {len(new_items)}",
                        observation="rss monitor")
                    log.info(f"RSS update: {feed_url} -> {len(new_items)} new item(s)")

                    # Update seen list (keep last 50 per feed)
                    updated = list({link for _, _, link in new_items}) + feed_seen
                    seen[feed_url] = updated[:50]
                except Exception as e:
                    log.error(f"RSS fetch error for {feed_url}: {e}")

            save_seen(seen)

        except Exception as e:
            log.error(f"RSS monitoring error: {e}")


def _daily_digest_loop():
    """Background thread that pushes an AI-curated news digest once per day.

    Default time: 8am (configurable via DAILY_DIGEST_HOUR in .env, 0-23).
    Calls news_digest tool, passes the aggregated raw items to the LLM with
    instructions to write a 4-6 sentence friend-style digest (no URLs,
    no headers, no bullet points), customized to the user's actual life
    (Baltimore local, medical, Apple ecosystem, AI tools, legal/probation),
    and sends it as a single Telegram message.

    Uses llm_client.generate() (the plain-text generate path on
    MultiProviderClient). Falls back to generate_with_tools() with
    tools_config=None if generate() ever grows a different signature on
    a subclass. Tries generate_text() as well in case a future provider
    client exposes that name.
    """
    from tools import tool_news_digest

    try:
        digest_hour = int(os.environ.get("DAILY_DIGEST_HOUR", "8"))
    except Exception:
        digest_hour = 8
    # Clamp to a sensible range
    if digest_hour < 0 or digest_hour > 23:
        digest_hour = 8
    log.info(f"Daily digest scheduled for {digest_hour:02d}:00 local time")

    last_run_date = None

    while True:
        time.sleep(60)  # Check every minute

        try:
            now = datetime.now()

            # Only run on the configured hour
            if now.hour != digest_hour:
                continue
            # Only run once per day
            if now.date() == last_run_date:
                continue
            # Skip anything outside the 7am to 10pm quiet-hours window
            if now.hour < 7 or now.hour > 22:
                continue

            # Check if the user has any RSS feeds subscribed
            feeds_file = Path.home() / "ai-twin-memory" / "rss_feeds.txt"
            if not feeds_file.exists():
                continue
            feeds = [line.strip() for line in
                     feeds_file.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#")]
            if not feeds:
                continue

            log.info("Running daily news digest...")

            # Pull all feeds
            raw_items = tool_news_digest()
            if not raw_items or "No items" in raw_items or "No RSS feeds" in raw_items:
                continue

            digest_prompt = f"""Read these RSS items and write a 4-6 sentence text message to me, like a friend texting me the news. Pick ONLY the 3-5 items relevant to my life:
- I live in Baltimore city
- I'm on probation (transferred to Baltimore)
- I have medical follow-ups (Dr. Lu via MyChart)
- I'm setting up new Apple devices (MacBook Pro, iPhone)
- I follow AI tools and developments

NO URLs. NO headers. NO bullet points. NO links. Just a friend-style text. End with one optional question like "want more on any of these?"

RSS ITEMS:
{raw_items}

Your text:"""

            digest_system = ("You write like a friend texting another friend. "
                             "Short, specific, no AI-speak. No corporate blog "
                             "phrases. Use contractions. Vary sentence length.")

            digest_text = None
            # Preferred: plain-text generate() (no tool loop needed for a digest)
            try:
                digest_text = llm_client.generate(
                    prompt=digest_prompt,
                    system_instruction=digest_system,
                )
            except Exception as e:
                log.warning(f"llm_client.generate() failed for digest: {e}")

            # Fallback 1: generate_text() if a provider client exposes it
            if not digest_text:
                try:
                    digest_text = llm_client.generate_text(
                        prompt=digest_prompt,
                        system_instruction=digest_system,
                    )
                except AttributeError:
                    pass
                except Exception as e:
                    log.warning(f"llm_client.generate_text() not available: {e}")

            # Fallback 2: generate_with_tools() with no tools
            if not digest_text:
                try:
                    digest_text = llm_client.generate_with_tools(
                        prompt=digest_prompt,
                        system_instruction=digest_system,
                        tools_config=None,
                        tool_executor=None,
                        max_iterations=1,
                    )
                except Exception as e:
                    log.error(f"Daily digest LLM call failed: {e}")
                    continue

            digest_text = (digest_text or "").strip()
            if not digest_text:
                continue

            # Send to Telegram
            try:
                _send_telegram_message(ALLOWED_USER_ID, digest_text)
                cm.append_to_today("twin", "Daily news digest sent",
                                   observation="daily digest")
                log.info("Daily news digest sent")
                last_run_date = now.date()
            except Exception as e:
                log.error(f"Daily digest Telegram send failed: {e}")

        except Exception as e:
            log.error(f"Daily digest error: {e}")


def _daily_check_in_loop():
    """Background thread that pushes a morning task review once per day.

    Default time: 9am (configurable via DAILY_CHECKIN_HOUR in .env, 0-23)
    Different from the news digest — this focuses on tasks, not news.
    Calls task_review tool, sends result to LLM for digestion, pushes to Telegram.
    """
    checkin_hour = int(os.environ.get("DAILY_CHECKIN_HOUR", "9"))
    log.info(f"Daily check-in scheduled for {checkin_hour}:00 local time")

    last_run_date = None

    while True:
        time.sleep(60)

        try:
            now = datetime.now()

            if now.hour != checkin_hour:
                continue
            if now.date() == last_run_date:
                continue
            if now.hour < 7 or now.hour > 22:
                continue

            log.info("Running daily check-in...")

            from tools import tool_task_review
            review = tool_task_review()

            if not review or len(review) < 20:
                continue  # Nothing to check in about

            prompt = f"""Write a 2-4 sentence morning check-in text to TYKO. Reference the blocked tasks and the suggested-now task. Be casual, in TYKO's voice (short, lowercase, contractions, no AI-speak). End with one direct question like "want me to walk through it?" or "what's the move?"

Task review:
{review}

Write the message now:"""

            try:
                response = llm_client.generate(
                    prompt=prompt,
                    system_instruction="You write like a friend texting another friend. Short, lowercase, contractions, casual. No AI-speak.",
                )
                msg = (response or "").strip()
                if msg:
                    _send_telegram_message(ALLOWED_USER_ID, msg)
                    cm.append_to_today("twin", "Daily check-in sent", observation="daily check-in")
                    log.info("Daily check-in sent")
                    last_run_date = now.date()
            except Exception as e:
                log.error(f"Daily check-in LLM call failed: {e}")

        except Exception as e:
            log.error(f"Daily check-in error: {e}")


def _cancel_redundant_reminders(user_text: str):
    """Cancel pending proactive reminders that are now redundant.

    When the user messages, check if what they're talking about overlaps
    with any pending reminders. If so, cancel those reminders — they're
    already aware, so pinging them about it would be annoying.

    This prevents the scenario where:
    1. Twin decides to remind about the probation appointment
    2. User messages "I already talked to my probation officer"
    3. Twin sends the reminder anyway (annoying and redundant)

    Instead:
    1. Twin decides to remind about the probation appointment
    2. User messages "I already talked to my probation officer"
    3. _cancel_redundant_reminders detects the overlap and removes the reminder
    4. Twin responds to the user's message (may include the reminder info naturally)
    """
    global _proactive_reminders_sent

    if not _proactive_reminders_sent:
        return  # Nothing to cancel

    text_lower = user_text.lower()

    # Keywords that indicate the user is already handling something
    completion_keywords = [
        "done", "finished", "called", "completed", "already", "took care",
        "handled", "sent", "picked up", "went to", "saw", "talked to",
        "texted", "emailed", "faxed", "rescheduled", "cancelled",
        "don't need", "dont need", "not happening", "resolved",
        "forgot about", "never mind", "nevermind", "skip",
    ]

    # Check if the user's message indicates they already handled something
    already_handled = any(kw in text_lower for kw in completion_keywords)

    # Get the knowledge base to check what reminders might be relevant
    upcoming = kb.get_domain("upcoming.md")
    tasks = kb.get_domain("tasks.md")

    # Keywords from the upcoming/tasks that we might have reminders for
    # If the user's message contains words from the reminder topics, cancel
    reminders_to_remove = set()

    for reminder_key in list(_proactive_reminders_sent):
        # Extract the date/topic from the reminder key
        # Reminder keys look like: "urgent_2026-09-07", "heads_up_2026-09-07",
        # "silence_1234567890"

        if reminder_key.startswith("silence_"):
            # Cancel silence check-ins when user messages (they're no longer silent)
            reminders_to_remove.add(reminder_key)
            log.info(f"Cancelled silence check-in (user returned)")

        elif already_handled and (upcoming or tasks):
            # Check if the user's message relates to any upcoming events or tasks
            # Extract date from reminder key
            import re
            date_match = re.search(r'\d{4}-\d{2}-\d{2}', reminder_key)
            if date_match:
                date_str = date_match.group(0)
                # Check if this date appears in the upcoming/tasks AND the user's message
                # references the same topic
                if date_str in (upcoming or "") or date_str in (tasks or ""):
                    # User might be talking about this event
                    # Check if their message contains related keywords
                    # from the upcoming/tasks line
                    for line in (upcoming or "").split('\n') + (tasks or "").split('\n'):
                        if date_str in line:
                            # Extract keywords from the line
                            words = re.findall(r'[a-zA-Z]{4,}', line.lower())
                            # If user's message contains any of these keywords,
                            # they're probably already talking about it
                            if any(w in text_lower for w in words):
                                reminders_to_remove.add(reminder_key)
                                log.info(f"Cancelled redundant reminder {reminder_key} (user already discussing)")
                                break

    if reminders_to_remove:
        _proactive_reminders_sent -= reminders_to_remove
        log.info(f"Cancelled {len(reminders_to_remove)} redundant reminders")


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

            # Morning/evening/weekly routines DISABLED per user request
            # The proactive messaging system handles reaching out instead.
            # Knowledge base auto-updates handle the evening reflection task.

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
    log.info(f"  Scheduler: routines disabled, proactive messaging active")
    log.info("=" * 60)
    log.info("Bot running. Press Ctrl+C to stop.")

    # Start the internal scheduler in a background thread
    scheduler_thread = threading.Thread(target=_scheduler_loop,
                                        daemon=True)
    scheduler_thread.start()
    log.info("Scheduler thread started")

    # Start the proactive messaging system in a background thread (smart, scored)
    proactive_thread = threading.Thread(target=_proactive_messaging_loop_smart,
                                         daemon=True)
    proactive_thread.start()
    log.info("Smart proactive messaging thread started")

    # Start the website monitoring thread
    monitor_thread = threading.Thread(target=_website_monitoring_loop,
                                       daemon=True)
    monitor_thread.start()
    log.info("Website monitoring thread started")

    # Start the RSS monitoring thread (subscribed feeds)
    rss_thread = threading.Thread(target=_rss_monitoring_loop,
                                    daemon=True)
    rss_thread.start()
    log.info("RSS monitoring thread started")

    # Start the daily news digest thread (once-per-day AI-curated briefing)
    digest_thread = threading.Thread(target=_daily_digest_loop, daemon=True)
    digest_thread.start()
    log.info("Daily digest thread started")

    # Start the daily check-in thread (morning task review)
    checkin_thread = threading.Thread(target=_daily_check_in_loop, daemon=True)
    checkin_thread.start()
    log.info("Daily check-in thread started")

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
