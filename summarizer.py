"""
summarizer.py
=============
Weekly auto-summarization. Runs every Sunday evening (cron in setup.sh),
reads the week's daily logs, asks Gemini to find patterns, and writes
a weekly summary to memory/weekly/.

Uses the pure-REST Gemini client (gemini_client.py) — no SDK, no
google-auth, no cryptography, no Rust. Installs cleanly on Termux/Android.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from context_manager import ContextManager
from gemini_client import GeminiClient


SUMMARY_PROMPT = """You are reviewing one week of someone's life, captured as daily logs of conversations with their AI twin.

Your job: notice what they cannot see from inside the week. Patterns. Avoided topics. Contradictions. Tiny progress. Recurring themes. What they said they'd do and didn't. What they keep coming back to.

Write a weekly summary in this exact format:

## What happened this week
(2-3 sentences, factual. What did they actually do?)

## Patterns I noticed
(Bullet list. Each pattern: one observation + one piece of evidence from the logs.)

## What they avoided
(Bullet list. Specific. No "seems like" — quote what they actually said.)

## Contradictions
(Bullet list. "On Monday they said X. On Thursday they said Y.")

## Progress (small counts)
(Bullet list. Even tiny things. Especially tiny things.)

## What next week's me should know
(3-5 sentences. Direct advice to future-you, the bot, about how to be with this person next week.)

## One question for them
(One question. The question that matters most given this week.)

Tone: honest, specific, no fluff. No "it sounds like you had a busy week." Just the truth, plainly.

Here is the week's logs:

"""


PATTERN_EXTRACTION_PROMPT = """From this weekly summary, extract 1-3 recurring patterns
that should be added to the user's long-term pattern file.

Each pattern as a single bullet, format:
- short name — one-sentence description with the evidence

Only include patterns that genuinely recur (mentioned 2+ times across the week,
or clearly significant). Skip one-offs.

Weekly summary:

"""


def run_weekly_summary(memory_dir: str, gemini_api_key: str,
                       week_of: datetime = None) -> str:
    """Generate and save the weekly summary. Returns the summary text."""
    cm = ContextManager(memory_dir)

    # Default: most recent Sunday
    if week_of is None:
        today = datetime.now()
        # Monday=0, Sunday=6 — find most recent Sunday
        days_since_sunday = (today.weekday() + 1) % 7
        week_of = today - timedelta(days=days_since_sunday)

    week_logs = cm.get_week_logs(week_of)
    if not week_logs.strip():
        return "(No logs found for this week — nothing to summarize.)"

    # Use the pure-REST Gemini client
    client = GeminiClient(api_key=gemini_api_key)

    # Generate summary
    summary = client.generate(SUMMARY_PROMPT + week_logs)
    summary = summary.strip()

    # Save
    cm.write_weekly_summary(week_of, summary)

    # Extract patterns and append to patterns.md
    patterns_text = client.generate(PATTERN_EXTRACTION_PROMPT + summary)
    patterns_text = patterns_text.strip()
    if patterns_text and "no patterns" not in patterns_text.lower():
        for line in patterns_text.splitlines():
            line = line.strip().lstrip("-").strip()
            if line:
                cm.append_pattern(
                    f"week of {week_of.strftime('%Y-%m-%d')}: {line}"
                )

    return summary


if __name__ == "__main__":
    # Manual run: python summarizer.py [memory_dir] [gemini_api_key]
    if len(sys.argv) < 3:
        print("Usage: python summarizer.py <memory_dir> <gemini_api_key>")
        sys.exit(1)
    summary = run_weekly_summary(sys.argv[1], sys.argv[2])
    print("=== Weekly summary generated ===\n")
    print(summary)
