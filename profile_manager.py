"""
profile_manager.py — Rewritten for accurate memory and personality
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("profile")

PROFILE_PATH = Path.home() / "ai-twin-memory" / "identity" / "profile.md"


PROFILE_UPDATE_PROMPT = """You are updating the user's personalization profile.

You are the AI twin. You KNOW this person. You're updating your own understanding of them based on today's conversations.

CRITICAL RULES:
1. Read the EXISTING profile carefully. Keep everything that's still true.
2. Build ON TOP of what you already know — don't start from scratch.
3. Use ABSOLUTE DATES, never relative ones. Write "September 1" not "today." Write "August 31" not "yesterday."
4. If a task was completed, mark it done and remove it from open threads.
5. If a deadline passed, note that.
6. Keep the profile under 600 words. Be specific, not generic.
7. The "Open Threads" section is your TODO list. Put things here that need following up, with SPECIFIC dates.

Format:

# User Profile

## Who They Are
[2-3 sentences. Their real identity. What defines them. This is YOUR understanding, not a form.]

## Current Situation
[What's happening in their life RIGHT NOW. Specific events, deadlines, stressors. Use absolute dates.]

## What They're Working On
[Specific tasks and goals. With dates. What's done, what's pending, what's overdue.]

## Patterns I've Noticed
[What you've observed over time. Both helpful and unhelpful patterns. Be honest.]

## How They Use Me
[What they ask for, what works, what doesn't. How they like you to respond.]

## Open Threads
[Things that need following up. Each item should have a date and what needs to happen. Remove completed items.]

## Last Updated
[Current date and time]
"""


class ProfileManager:
    def __init__(self, profile_path: Path = None):
        self.path = profile_path or PROFILE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_profile(self) -> str:
        if not self.path.exists():
            return self._create_initial_profile()
        return self.path.read_text(encoding="utf-8")

    def _create_initial_profile(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        template = f"""# User Profile

## Who They Are
[Still getting to know you.]

## Current Situation
[No data yet.]

## What They're Working On
[Nothing logged yet.]

## Patterns I've Noticed
[Too early to tell.]

## How They Use Me
[Still figuring this out.]

## Open Threads
[None yet.]

## Last Updated
{now}
"""
        self.path.write_text(template, encoding="utf-8")
        return template

    def update_profile(self, llm_client, system_prompt: str, today_log: str) -> str:
        current_profile = self.get_profile()
        now = datetime.now().strftime("%Y-%m-%d at %H:%M")

        prompt = f"""{PROFILE_UPDATE_PROMPT}

# CURRENT DATE AND TIME
It is {now}.

# YOUR CURRENT PROFILE (what you already know)

{current_profile}

# TODAY'S CONVERSATIONS

{today_log}

# YOUR TASK

Update your profile. Read what you already knew, read what happened today, and produce the updated profile. Keep what's still true. Add what's new. Remove what's done. Use absolute dates everywhere.

Produce the updated profile now:"""

        try:
            updated = llm_client.generate(
                prompt=prompt,
                system_instruction="You are updating your own memory of someone you know well. Be accurate, specific, and honest.",
            )

            if updated and len(updated) > 100 and "# User Profile" in updated:
                self.path.write_text(updated.strip() + "\n", encoding="utf-8")
                log.info(f"Profile updated ({len(updated)} chars)")
                return updated.strip()
            else:
                log.warning("Profile update too short or malformed, keeping current")
                return current_profile
        except Exception as e:
            log.error(f"Profile update failed: {e}")
            return current_profile

    def get_profile_for_context(self) -> str:
        profile = self.get_profile()
        if not profile or "Still getting to know you" in profile:
            return ""

        # Add current date/time as an anchor so the twin always knows what day it is
        now = datetime.now()
        date_anchor = now.strftime("%A, %B %d, %Y at %I:%M %p")

        return f"""# CURRENT MOMENT
It is {date_anchor}.

# WHAT I KNOW ABOUT YOU (my running memory)

{profile}

---

"""


if __name__ == "__main__":
    pm = ProfileManager()
    print(pm.get_profile())
    print()
    print("=== Context version ===")
    print(pm.get_profile_for_context()[:500])
