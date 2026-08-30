"""
profile_manager.py
==================
Running personalization profile for the AI twin.

Instead of sending 3 days of raw conversation history (which costs ~30K
tokens per request), the twin maintains a structured profile that captures
who the user is, what they're working on, what they need, and what the
twin has noticed.

The profile is:
- Small (~1500-2500 tokens) — read before every response
- Structured — organized by category, not freeform
- Growing — updated daily during evening reflection + weekly review
- Persistent — survives model switches, context truncation, everything

Profile structure:
  # User Profile
  ## Identity
    - Name, age, situation, core traits
  ## Current Situation
    - What they're working on, deadlines, immediate stressors
  ## Patterns & Tendencies
    - What the twin has noticed over time
  ## Goals & Direction
    - What they want, where they're heading
  ## Relationship with Twin
    - How they use the twin, what works, what doesn't
  ## Open Threads
    - Things to follow up on, unresolved conversations
  ## Last Updated
    - When the profile was last refreshed
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("profile")

PROFILE_PATH = Path.home() / "ai-twin-memory" / "identity" / "profile.md"


# The prompt used when asking the LLM to update the profile
PROFILE_UPDATE_PROMPT = """You are updating the user's personalization profile based on recent conversations.

Read the current profile and today's conversation log. Then produce an UPDATED profile that:

1. Keeps all existing information that's still accurate
2. Adds new facts learned today (commitments, deadlines, preferences, traits)
3. Updates anything that's changed (completed tasks, shifted priorities)
4. Notes new patterns you've observed
5. Removes anything that's clearly outdated or no longer relevant

The profile must be STRUCTURED and CONCISE. Use this exact format:

# User Profile

## Identity
[2-3 sentences: who they are, core traits, what defines them]

## Current Situation
[Bullet list: what they're working on NOW, deadlines, immediate stressors]

## Patterns & Tendencies
[Bullet list: recurring behaviors the twin has noticed — both helpful and unhelpful]

## Goals & Direction
[2-3 sentences: what they want, where they're heading, what matters to them]

## Relationship with Twin
[1-2 sentences: how they use the twin, what style of interaction works]

## Open Threads
[Bullet list: unresolved conversations, follow-ups needed, things to check on]

## Last Updated
[Today's date and time]

RULES:
- Be specific. "Has a dentist appointment Tuesday" not "has appointments."
- Be honest. If they avoided something, say so.
- Be brief. The whole profile should be under 800 words.
- Don't repeat the same information in multiple sections.
- If you learned nothing new today, just update the timestamp.
"""


class ProfileManager:
    """Manages the running personalization profile."""

    def __init__(self, profile_path: Path = None):
        self.path = profile_path or PROFILE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_profile(self) -> str:
        """Read the current profile. Returns empty string if none exists."""
        if not self.path.exists():
            return self._create_initial_profile()
        return self.path.read_text(encoding="utf-8")

    def _create_initial_profile(self) -> str:
        """Create a blank profile template for a new user."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        template = f"""# User Profile

## Identity
[Not yet known — the twin is still learning who you are.]

## Current Situation
[No data yet.]

## Patterns & Tendencies
[No patterns observed yet.]

## Goals & Direction
[Not yet discussed.]

## Relationship with Twin
[Still being figured out.]

## Open Threads
[None yet.]

## Last Updated
{now}
"""
        self.path.write_text(template, encoding="utf-8")
        return template

    def update_profile(self, llm_client, system_prompt: str,
                       today_log: str) -> str:
        """Use the LLM to update the profile based on today's conversations.

        Args:
            llm_client: The LLM client (OpenRouter or Gemini)
            system_prompt: The twin's system prompt
            today_log: Today's conversation log

        Returns:
            The updated profile text.
        """
        current_profile = self.get_profile()

        prompt = f"""{PROFILE_UPDATE_PROMPT}

# CURRENT PROFILE

{current_profile}

# TODAY'S CONVERSATION LOG

{today_log}

# YOUR TASK

Produce the updated profile now. Use the exact format specified above.
"""

        try:
            # Use plain generate (no tools) for profile updates
            updated = llm_client.generate(
                prompt=prompt,
                system_instruction=system_prompt,
            )

            if updated and len(updated) > 100:
                # Sanity check — make sure it's a real profile, not an error
                self.path.write_text(updated.strip() + "\n",
                                     encoding="utf-8")
                log.info(f"Profile updated ({len(updated)} chars)")
                return updated.strip()
            else:
                log.warning("Profile update too short, keeping current")
                return current_profile
        except Exception as e:
            log.error(f"Profile update failed: {e}")
            return current_profile

    def get_profile_for_context(self) -> str:
        """Get the profile formatted for inclusion in conversation context.

        This is what gets prepended to every twin response.
        """
        profile = self.get_profile()
        if not profile or "Not yet known" in profile:
            return ""
        return f"# USER PROFILE (running context)\n\n{profile}\n\n---\n\n"


if __name__ == "__main__":
    pm = ProfileManager()
    print("=== Initial profile ===")
    print(pm.get_profile())
    print()
    print("=== Profile for context ===")
    print(pm.get_profile_for_context()[:500])
