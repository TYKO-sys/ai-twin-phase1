"""
knowledge_base.py
=================
The twin's structured understanding of the user.

FIXED VERSION — addresses 5 critical problems:
1. Infinite growth → Each domain has a HARD MAX. Old entries removed.
2. Redundancy → Each domain has a UNIQUE PURPOSE. No overlap.
3. Single-occurrence assumptions → Patterns require 3+ observations.
4. Overly literal WHATs → Domains capture WHYs and understanding, not events.
5. Third person → All content written in second person ("you").
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("knowledge_base")

KNOWLEDGE_DIR = Path.home() / "ai-twin-memory" / "knowledge"

# Domain definitions: (filename, what it captures, update prompt, max_chars)
# max_chars is a HARD LIMIT. The LLM is told to stay under it.
# This prevents infinite growth.
DOMAINS = [
    ("identity.md",
     "who TYKO is at their core",
     """Update your understanding of who TYKO IS at their core.

This is about WHO they are, not WHAT happened to them.

RULES:
- Keep only traits that have shown up CONSISTENTLY across multiple days, not single occurrences.
- If something was observed only once, do NOT include it as a trait. One bad day doesn't define someone.
- Remove traits that no longer seem accurate.
- Write in second person: "You are..." not "They are..."
- MAXIMUM 3 sentences. No more. This is the essence, not a biography.
- If nothing changed about their core identity, keep the existing text and just update the date.

Write the updated identity now:""",
     500),  # ~125 tokens — strict limit

    ("situation.md",
     "current life circumstances — what TYKO is dealing with RIGHT NOW",
     """Update the current situation.

RULES:
- Only include things that are ACTIVE and CURRENT. If something is resolved, REMOVE it.
- Do NOT duplicate information from other domains. This is for SITUATIONS only, not tasks or relationships.
- Use absolute dates. Write "as of September 2" not "currently."
- Each bullet should be 1 line max. No paragraphs.
- MAXIMUM 6 bullets. If you have more, drop the least important.
- Remove anything that was resolved since the last update.
- Write in second person: "You are dealing with..." not "They are..."

Write the updated situation now:""",
     800),  # ~200 tokens

    ("tasks.md",
     "what needs doing — ACTIVE tasks only",
     """Update the task list. ACTIVE TASKS ONLY.

RULES:
- If a task was COMPLETED today, REMOVE it from this list. It goes to completed.md.
- If a task was completed in a PREVIOUS update, it should already be gone. Do not re-add it.
- Each task: ONE LINE. Format: "Task — due [date] — [status]"
- Do NOT include task history, context, or background. Just the task, date, and status.
- Statuses: pending, blocked, overdue. NOT "in progress" or "following up."
- MAXIMUM 8 tasks. If you have more, drop the least urgent.
- Remove tasks that are no longer relevant.
- Do NOT duplicate tasks that appear in upcoming.md.
- Write in second person.

Write the updated task list now:""",
     600),  # ~150 tokens

    ("relationships.md",
     "key people — who they are and what's unresolved",
     """Update the key people.

RULES:
- Only include people who are ACTIVELY RELEVANT to current situations.
- If a person is no longer relevant, REMOVE them.
- Each person: ONE LINE. Format: "Name — role — [dynamic] — [what's unresolved]"
- Do NOT include contact info, phone numbers, or fax numbers. That goes in tasks.
- Do NOT duplicate relationship info that appears in situation.md.
- MAXIMUM 6 people.
- Write in second person: "Your relationship with..."

Write the updated relationships now:""",
     500),  # ~125 tokens

    ("patterns.md",
     "behavioral patterns — observed 3+ times minimum",
     """Update behavioral patterns.

CRITICAL RULE:
- A pattern must be observed AT LEAST 3 TIMES across different days to be included.
- ONE occurrence is NOT a pattern. If you've only seen something once, do NOT add it.
- If a pattern was based on only 1-2 observations, REMOVE it.
- Patterns are about HOW you approach things, not WHAT happened.

RULES:
- MAXIMUM 5 patterns. Remove the least relevant if you have more.
- Each pattern: ONE sentence describing the behavior + ONE sentence on what helps.
- Do NOT include triggers, evidence lists, or detailed analysis. Just the pattern.
- Remove patterns that no longer apply.
- Write in second person: "You tend to..." not "The user tends to..."

Write the updated patterns now:""",
     500),  # ~125 tokens

    ("completed.md",
     "recent wins — what got done in the last 7 days only",
     """Update the completed items.

RULES:
- Only include items completed in the LAST 7 DAYS. Anything older gets REMOVED.
- Each item: ONE LINE. "Date — what was done."
- No paragraphs. No context. No analysis. Just the date and the action.
- MAXIMUM 8 items. This is a recent wins list, not a history book.
- Remove anything older than 7 days.
- Write in second person: "You completed..."

Write the updated completed list now:""",
     500),  # ~125 tokens

    ("upcoming.md",
     "what's coming — events within the next 30 days",
     """Update the upcoming events calendar.

RULES:
- Only events within the NEXT 30 DAYS. Anything past that gets removed.
- Each event: "Date — event name — time — [what needs to happen before then]"
- Do NOT include events that already passed.
- Do NOT duplicate tasks from tasks.md.
- MAXIMUM 5 events.
- Remove events that already happened.
- Write in second person: "You have..."

Write the updated upcoming list now:""",
     500),  # ~125 tokens

    ("insights.md",
     "deep understanding — the why behind things",
     """Update your deep insights.

RULES:
- This is your highest-level understanding. Not facts — wisdom.
- Write in SECOND PERSON: "You are..." not "They are..."
- MAXIMUM 3 sentences. No more.
- If an insight is no longer accurate, REPLACE it. Don't accumulate.
- Previous insights that are still true should be KEPT, not rewritten.
- Outdated insights should be REMOVED, not stacked.
- Do NOT repeat information from other domains. This is synthesis, not summary.

Write the updated insights now:""",
     400),  # ~100 tokens
]


class KnowledgeBase:
    """Manages the twin's structured understanding of the user."""

    def __init__(self, knowledge_dir: Path = None):
        self.dir = knowledge_dir or KNOWLEDGE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

        for filename, description, _, _ in DOMAINS:
            path = self.dir / filename
            if not path.exists():
                path.write_text(
                    f"# {description}\n\n_(not yet known — still learning)_\n",
                    encoding="utf-8"
                )

    def get_domain(self, filename: str) -> str:
        path = self.dir / filename
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        if "not yet known" in content:
            return ""
        return content

    def get_all_knowledge(self) -> str:
        """Get all knowledge domains formatted for context.

        Total target: under 1500 tokens (~6000 chars).
        """
        now = datetime.now()
        date_anchor = now.strftime("%A, %B %d, %Y at %I:%M %p")

        parts = [f"# CURRENT MOMENT\nIt is {date_anchor}.\n"]

        for filename, description, _, max_chars in DOMAINS:
            content = self.get_domain(filename)
            if content:
                # Enforce hard limit
                if len(content) > max_chars:
                    content = content[:max_chars] + "\n"
                # Clean up header
                lines = content.strip().splitlines()
                if lines and lines[0].startswith("# "):
                    lines = lines[1:]
                clean = "\n".join(lines).strip()
                if clean and "not yet known" not in clean:
                    domain_name = filename.replace(".md", "").replace("_", " ").title()
                    parts.append(f"## {domain_name}\n{clean}")

        return "\n\n---\n\n".join(parts)

    def update_all(self, llm_client, system_prompt: str, conversation_log: str) -> dict:
        """Update all knowledge domains based on recent conversations.

        Each domain is updated independently with strict size limits.
        """
        now = datetime.now().strftime("%Y-%m-%d at %H:%M")
        results = {}

        for filename, description, update_prompt, max_chars in DOMAINS:
            current = self.get_domain(filename)

            if not conversation_log and not current:
                continue

            # Include the max_chars limit in the prompt
            prompt = f"""{update_prompt}

# CURRENT DATE AND TIME
It is {now}.

# WHAT YOU ALREADY KNOW (previous version — read carefully)

{current if current else '_(empty — first update)_'}

# TODAY'S CONVERSATIONS

{conversation_log if conversation_log else '_(no new conversations — just refresh dates and remove outdated items)_'}

# REMINDER
- This domain must be UNDER {max_chars} characters. If the previous version is already at the limit, you MUST remove something to add new info.
- Write in second person ("you"), never third person ("they").
- Do NOT repeat information that belongs in other domains.
- Single occurrences are NOT patterns or traits.

Output ONLY the updated content for this domain. No preamble:"""

            try:
                updated = llm_client.generate(
                    prompt=prompt,
                    system_instruction="You are updating your own knowledge of someone you know well. Be accurate, specific, honest, and brief. Write in second person.",
                )

                if updated and len(updated) > 20:
                    cleaned = updated.strip()
                    # Remove preamble
                    if "# " in cleaned and not cleaned.startswith("# "):
                        idx = cleaned.index("# ")
                        cleaned = cleaned[idx:]

                    # HARD ENFORCEMENT of max_chars
                    if len(cleaned) > max_chars:
                        cleaned = cleaned[:max_chars].rsplit('\n', 1)[0] + "\n"

                    path = self.dir / filename
                    path.write_text(cleaned + "\n", encoding="utf-8")
                    results[filename] = len(cleaned)
                    log.info(f"Updated {filename} ({len(cleaned)}/{max_chars} chars)")
                else:
                    log.warning(f"Update for {filename} too short, keeping current")
                    results[filename] = 0
            except Exception as e:
                log.error(f"Failed to update {filename}: {e}")
                results[filename] = 0

        return results

    def get_status(self) -> str:
        lines = ["Knowledge Base Status:"]
        total_chars = 0
        for filename, description, _, max_chars in DOMAINS:
            content = self.get_domain(filename)
            chars = len(content) if content else 0
            total_chars += chars
            pct = (chars / max_chars * 100) if max_chars > 0 else 0
            status = "✓" if chars > 50 else "○"
            over = " ⚠️ OVER LIMIT" if chars > max_chars else ""
            lines.append(f"  {status} {filename} ({chars}/{max_chars} chars, {pct:.0f}%){over}")
        lines.append(f"  Total: {total_chars} chars (~{total_chars // 4} tokens)")
        return "\n".join(lines)


_kb = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
