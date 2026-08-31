"""
error_handler.py
================
Translates technical errors into user-friendly messages.

The user should never see:
- "Termux" in any message
- File paths like /data/data/com.termux/...
- Command names like "pkg install", "python", "tmux"
- Stack traces or Python error types
- API status codes (404, 429, 503)

Instead, they see:
- "Your twin needs a moment. I'm reconnecting."
- "I'm having trouble thinking right now. Try again in a minute."
- "I lost my connection. Give me a few seconds."

This module provides:
- translate_error(raw_error) → friendly_message
- is_user_facing_error(text) → bool
- friendly_status() → clean status message
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------- #
# Error translation rules
# ---------------------------------------------------------------------- #

# Map technical patterns to friendly messages
ERROR_TRANSLATIONS = [
    # Rate limiting
    (r"429|rate.?limit|too many requests",
     "I'm getting a lot of requests right now. Give me 60 seconds and try again."),

    # Server errors
    (r"503|service unavailable|server error|overloaded",
     "My thinking service is busy right now. I'll be back in a moment."),

    # Connection errors
    (r"connection.?abort|connection.?reset|connection.?error|timeout|timed.?out",
     "I lost my connection for a second. I'm reconnecting now."),

    # Network errors
    (r"network|dns|host.?name|resolve",
     "I can't reach the internet right now. Check your connection and try again."),

    # API key errors
    (r"401|unauthorized|invalid.?api.?key|authentication",
     "I need my API keys refreshed. This is a setup issue — contact support."),

    # Payment errors
    (r"402|payment required|insufficient",
     "My AI service needs credits. Add a small amount to your account to continue."),

    # Model errors
    (r"404|not found|model.*not.*available|deprecated",
     "My AI model needs updating. I'll switch to a different one automatically."),

    # Permission errors
    (r"permission denied|forbidden|403",
     "I don't have permission to do that yet. Check your phone settings."),

    # Python errors
    (r"ImportError|ModuleNotFoundError",
     "I'm missing a component. A quick update will fix this."),

    # File errors
    (r"FileNotFoundError|No such file",
     "I can't find something I need. I'll recreate it."),

    # Generic Python exceptions
    (r"Exception|Error|Traceback",
     "Something went wrong on my end. I'm recovering."),

    # Telegram errors
    (r"telegram.*error|Bad Request|can't parse entities",
     "I had trouble sending that message. I'll try again."),

    # Termux-specific (must be hidden)
    (r"termux|pkg install|/data/data/com\.termux",
     "I need to refresh my connection. One moment."),
]


# Patterns that indicate the error is already user-friendly
FRIENDLY_PATTERNS = [
    r"^I'm ",
    r"^My ",
    r"^I can't",
    r"^I need",
    r"^I lost",
    r"^Give me",
    r"^Try again",
    r"^Your twin",
]


def translate_error(raw_error: str) -> str:
    """Translate a technical error message into a user-friendly one.

    Args:
        raw_error: The raw error string (may contain Termux paths, stack traces, etc.)

    Returns:
        A friendly message that doesn't expose technical details.
    """
    if not raw_error:
        return "Something went wrong. I'm recovering."

    error_lower = raw_error.lower()

    # Check if it's already friendly
    for pattern in FRIENDLY_PATTERNS:
        if re.match(pattern, raw_error, re.IGNORECASE):
            return raw_error  # Already friendly, return as-is

    # Try each translation rule
    for pattern, friendly in ERROR_TRANSLATIONS:
        if re.search(pattern, error_lower, re.IGNORECASE):
            return friendly

    # Default fallback — never show the raw error
    return "Something went wrong on my end. I'm recovering."


def is_user_facing_error(text: str) -> bool:
    """Check if a message is already user-friendly (doesn't need translation)."""
    if not text:
        return False

    # Check for technical indicators
    technical_indicators = [
        "termux", "pkg install", "/data/data/", "traceback",
        "error 4", "error 5", "status_code", "exception",
        ".py", "line ", "file ", "import ",
    ]

    text_lower = text.lower()
    for indicator in technical_indicators:
        if indicator in text_lower:
            return False

    return True


def sanitize_log_message(message: str) -> str:
    """Remove technical details from a message before showing to user.

    Strips:
    - File paths
    - Line numbers
    - Stack traces
    - Technical command names
    """
    if not message:
        return ""

    # Remove file paths
    message = re.sub(r"/data/data/com\.termux[^ ]*", "", message)
    message = re.sub(r"/home/[^ ]+", "", message)
    message = re.sub(r"~/[^ ]+", "", message)

    # Remove Python file references
    message = re.sub(r"\w+\.py(?::\d+)?", "", message)

    # Remove stack trace patterns
    message = re.sub(r"File \"[^\"]+\", line \d+", "", message)
    message = re.sub(r"Traceback \(most recent call last\):", "", message)

    # Remove command names
    message = re.sub(r"`pkg install[^`]*`", "", message)
    message = re.sub(r"`python[^`]*`", "", message)
    message = re.sub(r"`tmux[^`]*`", "", message)

    # Clean up extra whitespace
    message = re.sub(r"\s+", " ", message).strip()

    return message


def friendly_status() -> str:
    """Generate a friendly status message (no technical details)."""
    return (
        "I'm here and ready. Everything's running smoothly.\n\n"
        "If you need anything, just ask. If something breaks, "
        "send /fix and I'll get myself back online."
    )


def friendly_error_for_provider(provider_name: str, error: str) -> str:
    """Generate a friendly error message for a specific provider failure.

    The user should never know which provider failed — they just know
    their twin is having trouble thinking.
    """
    # Don't mention the provider name — translate to a generic message
    return translate_error(error)


if __name__ == "__main__":
    # Test the error translations
    test_errors = [
        "OpenRouter 429 rate limited",
        "Gemini 503 server error",
        "ConnectionAbortedError: [Errno 103] Software caused connection abort",
        "ModuleNotFoundError: No module named 'telebot'",
        "FileNotFoundError: /data/data/com.termux/files/home/.env",
        "Traceback (most recent call last): File 'twin_bot.py', line 123",
        "deepseek error 402: Payment required",
        "zai error 400: Bad Request",
        "termux-wake-lock: command not found",
        "I'm having trouble thinking right now.",
    ]

    for err in test_errors:
        print(f"RAW: {err}")
        print(f"FRIENDLY: {translate_error(err)}")
        print()
