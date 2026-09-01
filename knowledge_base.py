"""
knowledge_base.py
=================
The twin's structured understanding of the user.

Instead of storing raw conversation logs and truncating them (which loses
important context from long conversations), the twin maintains a knowledge
base — multiple files, each capturing a different domain of understanding.

The knowledge base is:
- DISTILLED: Captures meaning, not events. "User is avoiding the surgeon
  call because it triggers anxiety about surgery failure" not "user said
  they need to call the surgeon."
- CUMULATIVE: Each update considers the previous version. The twin builds
  on what it already knows.
- STRUCTURED: Each domain has a clear purpose. No duplication.
- DATED: Uses absolute dates everywhere. No relative dates that expire.
- SMALL: All domains combined are ~2000 tokens. Efficient.

Domains:
1. identity.md       — Who they are at their core
2. situation.md       — Current life circumstances
3. tasks.md          — What needs doing (with dates, priorities, why)
4. relationships.md  — Key people and dynamics
5. patterns.md       — Behavioral patterns observed over time
6. completed.md      — What's been done (progress tracking)
7. upcoming.md       — What's coming (calendar with context)
8. insights.md       — Deep understanding — the "why" behind things

Update process:
- After conversations, the twin analyzes what was said
- It reads each knowledge domain's current content
- It generates an updated version that preserves truth, adds new info,
  removes what's done or outdated
- Each update considers the previous version (cumulative, not from scratch)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("knowledge_base")

KNOWLEDGE_DIR = Path.home() / "ai-twin-memory" / "knowledge"

# Domain definitions: (filename, what it captures, update prompt)
DOMAINS = [
    ("identity.md", "who they are at their core — values, beliefs, personality, what defines them as a person",
     """Update your understanding of who this person IS at their core.

Consider:
- What values drive their decisions?
- What beliefs shape how they see the world?
- What personality traits keep showing up?
- What defines them beyond their current situation?

Keep what's still true. Add new insights about who they are. Remove anything
that was a temporary state mistaken for a trait. Deepen your understanding.
Use 2-4 sentences. This is about essence, not events."""),

    ("situation.md", "current life circumstances — health, legal, financial, housing, what they're dealing with right now",
     """Update your understanding of their current life situation.

Consider:
- What are they dealing with RIGHT NOW? (health, legal, financial, housing)
- What's the status of each major situation?
- What changed since the last update?

Use ABSOLUTE DATES. Write "as of September 1" not "currently."
Remove anything that's resolved or no longer relevant.
Keep this to 4-6 bullet points. Specific, not vague."""),

    ("tasks.md", "what needs doing — with absolute dates, priorities, and WHY each matters",
     """Update the task list.

For each task:
- What needs to happen?
- When is it due? (absolute date, not "tomorrow")
- Why does it matter? (what happens if it doesn't get done)
- What's the status? (not started, in progress, blocked, overdue)

Remove completed tasks (they go in completed.md).
Add new tasks that came up today.
Update statuses of existing tasks.
If a deadline passed, mark it OVERDUE.
Keep each task to 1-2 lines. Prioritize by urgency."""),

    ("relationships.md", "key people in their life — who they are, what they mean, what's unresolved",
     """Update your understanding of the key people in their life.

For each person:
- Who are they? (name, role, relationship)
- What's the dynamic? (supportive, tense, complicated, estranged)
- What's unresolved? (what needs to happen with this person?)

Add new people mentioned today. Update dynamics that shifted.
Remove people who are no longer relevant.
Keep each person to 1-2 lines."""),

    ("patterns.md", "behavioral patterns observed over time — both helpful and unhelpful",
     """Update the patterns you've noticed over time.

Consider:
- What behaviors keep showing up? (avoidance, overcommitment, isolation, etc.)
- What triggers these patterns?
- What helps break unhelpful patterns?
- What patterns are they not aware of?

Only include patterns you've observed MULTIPLE TIMES, not one-offs.
Add new patterns noticed today. Update existing patterns with new evidence.
Remove patterns that no longer apply.
Be honest. This is for them, not about them."""),

    ("completed.md", "what they've gotten done — progress tracking, not just task completion",
     """Update the record of what they've accomplished.

Consider:
- What tasks were completed?
- What progress was made (even partial)?
- What difficult things did they face?
- What should be celebrated?

Add new completions from today. Keep previous entries.
This is a WIN file. Track progress, not just checkbox items.
Keep it to bullet points with dates."""),

    ("upcoming.md", "what's coming — calendar with context, not just dates",
     """Update the upcoming events calendar.

For each upcoming item:
- What's happening? (appointment, deadline, court date, etc.)
- When? (absolute date and time)
- What needs to happen before then?
- Why does it matter?

Add new items mentioned today. Remove items that passed.
Sort by date, soonest first.
Only include things within the next 30 days."""),

    ("insights.md", "deep understanding — the why behind patterns, the connections between domains",
     """Update your deep insights about this person.

Consider:
- What connections do you see between their identity, situation, and patterns?
- What are they not seeing about themselves?
- What's the deeper story behind what they're going through?
- What would help them most right now?

This is your highest-level understanding. Not facts — wisdom.
Be honest. Be specific. Be brief. 3-5 sentences max.
Previous insights that are still true should be kept and deepened.
Outdated insights should be replaced, not accumulated."""),
]


class KnowledgeBase:
    """Manages the twin's structured understanding of the user."""

    def __init__(self, knowledge_dir: Path = None):
        self.dir = knowledge_dir or KNOWLEDGE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

        # Initialize any missing domain files
        for filename, description, _ in DOMAINS:
            path = self.dir / filename
            if not path.exists():
                path.write_text(
                    f"# {description}\n\n_(not yet known — still learning)_\n",
                    encoding="utf-8"
                )

    def get_domain(self, filename: str) -> str:
        """Read a single knowledge domain."""
        path = self.dir / filename
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        # Skip placeholder content
        if "not yet known" in content:
            return ""
        return content

    def get_all_knowledge(self) -> str:
        """Get all knowledge domains formatted for context.

        This is what the twin reads before responding. Small, dense, meaningful.
        """
        now = datetime.now()
        date_anchor = now.strftime("%A, %B %d, %Y at %I:%M %p")

        parts = [f"# CURRENT MOMENT\nIt is {date_anchor}.\n"]

        for filename, description, _ in DOMAINS:
            content = self.get_domain(filename)
            if content:
                # Clean up the header
                lines = content.strip().splitlines()
                # Skip the first line (our auto-generated header)
                if lines and lines[0].startswith("# "):
                    lines = lines[1:]
                clean = "\n".join(lines).strip()
                if clean and "not yet known" not in clean:
                    domain_name = filename.replace(".md", "").replace("_", " ").title()
                    parts.append(f"## {domain_name}\n{clean}")

        return "\n\n---\n\n".join(parts)

    def update_all(self, llm_client, system_prompt: str, conversation_log: str) -> dict:
        """Update all knowledge domains based on recent conversations.

        Each domain is updated independently, considering its previous content
        and the new conversation. This is cumulative — each update builds on
        the last.

        Args:
            llm_client: The LLM client
            system_prompt: The twin's system prompt
            conversation_log: Today's conversation log

        Returns:
            Dict of {filename: updated_content}
        """
        now = datetime.now().strftime("%Y-%m-%d at %H:%M")
        results = {}

        for filename, description, update_prompt in DOMAINS:
            current = self.get_domain(filename)

            # Skip if no conversation and no existing content
            if not conversation_log and not current:
                continue

            prompt = f"""{update_prompt}

# CURRENT DATE AND TIME
It is {now}.

# WHAT YOU ALREADY KNOW (previous version of this domain)

{current if current else '_(empty — this is the first update)_'}

# TODAY'S CONVERSATIONS

{conversation_log if conversation_log else '_(no conversations today — just refresh dates and statuses if needed)_'}

# YOUR TASK

Update this knowledge domain. Read what you already knew, read what happened today, and produce the updated content. Keep what's still true. Add what's new. Remove what's done or outdated. Use absolute dates.

Output ONLY the updated content for this domain. No preamble, no explanation. Just the content:"""

            try:
                updated = llm_client.generate(
                    prompt=prompt,
                    system_instruction="You are updating your own knowledge of someone you know well. Be accurate, specific, honest, and brief.",
                )

                if updated and len(updated) > 20:
                    # Clean up the response
                    cleaned = updated.strip()
                    # Remove any preamble the model might add
                    if "# " in cleaned and not cleaned.startswith("# "):
                        idx = cleaned.index("# ")
                        cleaned = cleaned[idx:]

                    path = self.dir / filename
                    path.write_text(cleaned + "\n", encoding="utf-8")
                    results[filename] = len(cleaned)
                    log.info(f"Updated {filename} ({len(cleaned)} chars)")
                else:
                    log.warning(f"Update for {filename} too short, keeping current")
                    results[filename] = 0
            except Exception as e:
                log.error(f"Failed to update {filename}: {e}")
                results[filename] = 0

        return results

    def get_status(self) -> str:
        """Get a status summary for debugging."""
        lines = ["Knowledge Base Status:"]
        total_chars = 0
        for filename, description, _ in DOMAINS:
            content = self.get_domain(filename)
            chars = len(content) if content else 0
            total_chars += chars
            status = "✓" if chars > 50 else "○"
            lines.append(f"  {status} {filename} ({chars} chars)")
        lines.append(f"  Total: {total_chars} chars (~{total_chars // 4} tokens)")
        return "\n".join(lines)


# Singleton
_kb = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


if __name__ == "__main__":
    kb = KnowledgeBase()
    print("=== Knowledge Base ===")
    print(kb.get_status())
    print()
    print("=== Full Knowledge for Context ===")
    print(kb.get_all_knowledge()[:2000])
