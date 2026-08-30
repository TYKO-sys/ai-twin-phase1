"""
context_manager.py
==================
Handles all reading/writing/searching of the AI twin's memory.

Memory layout (under MEMORY_DIR):
    memory/
        daily/
            2026-08-29.md         # today's log: user messages, bot replies, observations
            2026-08-28.md
            ...
        weekly/
            2026-08-24.md         # Sunday review summary
        identity/
            about_me.md           # who the user is — written by them, edited by bot
            patterns.md           # recurring themes the bot notices
            contradictions.md    # things they've said that conflict
        index.md                  # always-current summary, regenerated on each write

Design choices:
- Plain markdown files. No database. The user can read their own memory.
- One file per day. Easy to find, easy to forget, easy to archive.
- Weekly summaries so context doesn't bloat.
- Search is simple substring + date filtering. Good enough for personal scale.
- Forget command actually deletes (after confirmation). No soft delete. Honesty over recovery.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional


class ContextManager:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.daily_dir = self.base / "daily"
        self.weekly_dir = self.base / "weekly"
        self.identity_dir = self.base / "identity"
        for d in (self.daily_dir, self.weekly_dir, self.identity_dir):
            d.mkdir(parents=True, exist_ok=True)
        # Make sure index exists
        self._touch_index()

    # ------------------------------------------------------------------ #
    # Daily log
    # ------------------------------------------------------------------ #

    def _daily_path(self, date: Optional[datetime] = None) -> Path:
        date = date or datetime.now()
        return self.daily_dir / f"{date.strftime('%Y-%m-%d')}.md"

    def append_to_today(self, role: str, content: str,
                        observation: Optional[str] = None) -> None:
        """Append a single message + optional bot observation to today's log."""
        path = self._daily_path()
        timestamp = datetime.now().strftime("%H:%M")
        header = f"## {timestamp} — {role}\n"
        body = f"{content.strip()}\n"
        obs = ""
        if observation:
            obs = f"\n> **observed:** {observation.strip()}\n"
        entry = f"\n{header}{body}{obs}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
        self._refresh_index()

    # ------------------------------------------------------------------ #
    # Identity files
    # ------------------------------------------------------------------ #

    def get_identity(self) -> str:
        """Read the user's identity file. Returns empty string if missing."""
        path = self.identity_dir / "about_me.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def update_identity(self, new_content: str) -> None:
        path = self.identity_dir / "about_me.md"
        path.write_text(new_content.strip() + "\n", encoding="utf-8")

    def append_pattern(self, pattern: str) -> None:
        """Add a recurring pattern the bot noticed."""
        path = self.identity_dir / "patterns.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"\n- **{timestamp}** — {pattern.strip()}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)

    def append_contradiction(self, contradiction: str) -> None:
        """Add a contradiction the bot noticed."""
        path = self.identity_dir / "contradictions.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"\n- **{timestamp}** — {contradiction.strip()}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)

    # ------------------------------------------------------------------ #
    # Retrieval
    # ------------------------------------------------------------------ #

    def get_today_context(self) -> str:
        path = self._daily_path()
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def get_recent_days(self, days: int = 7) -> str:
        """Concatenate the last N days of logs."""
        chunks: List[str] = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            path = self._daily_path(date)
            if path.exists():
                chunks.append(f"### {date.strftime('%Y-%m-%d')}\n\n"
                              + path.read_text(encoding="utf-8"))
        return "\n\n".join(chunks)

    def get_recent_weekly(self, weeks: int = 4) -> str:
        """Concatenate recent weekly summaries."""
        chunks: List[str] = []
        files = sorted(self.weekly_dir.glob("*.md"), reverse=True)
        for path in files[:weeks]:
            chunks.append(f"### {path.stem}\n\n"
                          + path.read_text(encoding="utf-8"))
        return "\n\n".join(chunks)

    def search(self, query: str, limit: int = 10) -> str:
        """Simple substring search across all memory files. Returns matches."""
        query_lower = query.lower().strip()
        if not query_lower:
            return "Empty query."
        matches: List[str] = []
        # search daily + weekly + identity
        for sub in (self.daily_dir, self.weekly_dir, self.identity_dir):
            for path in sub.glob("*.md"):
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        # grab surrounding context
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        ctx = "\n".join(lines[start:end]).strip()
                        matches.append(
                            f"[{path.relative_to(self.base)}]\n{ctx}"
                        )
                        if len(matches) >= limit:
                            break
                if len(matches) >= limit:
                    break
            if len(matches) >= limit:
                break
        if not matches:
            return f"No matches for '{query}'."
        return f"Found {len(matches)} match(es) for '{query}':\n\n" + \
               "\n\n---\n\n".join(matches)

    # ------------------------------------------------------------------ #
    # Forget
    # ------------------------------------------------------------------ #

    def forget(self, query: str) -> str:
        """Remove lines containing the query from all memory files.
        Returns a summary of what was removed."""
        query_lower = query.lower().strip()
        if not query_lower:
            return "Nothing to forget — empty query."
        removed: List[str] = []
        for sub in (self.daily_dir, self.weekly_dir, self.identity_dir):
            for path in sub.glob("*.md"):
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                lines = text.splitlines(keepends=True)
                new_lines: List[str] = []
                removed_here = 0
                for line in lines:
                    if query_lower in line.lower():
                        removed_here += 1
                    else:
                        new_lines.append(line)
                if removed_here > 0:
                    path.write_text("".join(new_lines), encoding="utf-8")
                    removed.append(
                        f"  - {path.relative_to(self.base)}: "
                        f"{removed_here} line(s)"
                    )
        if not removed:
            return f"Nothing matched '{query}' — memory unchanged."
        self._refresh_index()
        return f"Forgot '{query}'. Removed:\n" + "\n".join(removed)

    # ------------------------------------------------------------------ #
    # Index (always-current summary the bot reads first)
    # ------------------------------------------------------------------ #

    def _touch_index(self) -> None:
        path = self.base / "index.md"
        if not path.exists():
            path.write_text(
                "# Memory Index\n\n"
                "(This file is auto-regenerated. Don't edit by hand.)\n\n",
                encoding="utf-8",
            )

    def _refresh_index(self) -> None:
        """Regenerate the top-level index summarizing what memory exists."""
        path = self.base / "index.md"
        today = self._daily_path()
        daily_files = sorted(self.daily_dir.glob("*.md"), reverse=True)
        weekly_files = sorted(self.weekly_dir.glob("*.md"), reverse=True)

        lines: List[str] = []
        lines.append("# Memory Index\n")
        lines.append(f"_Last updated: {datetime.now().isoformat(timespec='seconds')}_\n")
        lines.append("\n## Daily logs\n")
        for f in daily_files[:14]:
            marker = " *(today)*" if f.name == today.name else ""
            lines.append(f"- `{f.name}`{marker}")
        lines.append("\n## Weekly reviews\n")
        if weekly_files:
            for f in weekly_files[:8]:
                lines.append(f"- `{f.name}`")
        else:
            lines.append("- _(none yet — first Sunday review pending)_")
        lines.append("\n## Identity\n")
        ident = self.identity_dir / "about_me.md"
        if ident.exists():
            lines.append("- `about_me.md` exists")
        else:
            lines.append("- `about_me.md` missing — ask user to write one")
        for name in ("patterns.md", "contradictions.md"):
            p = self.identity_dir / name
            if p.exists():
                lines.append(f"- `{name}` exists")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Weekly summary (used by summarizer.py)
    # ------------------------------------------------------------------ #

    def write_weekly_summary(self, week_of: datetime, summary: str) -> Path:
        """Save a weekly summary. week_of should be the Sunday date."""
        path = self.weekly_dir / f"{week_of.strftime('%Y-%m-%d')}.md"
        path.write_text(
            f"# Week of {week_of.strftime('%Y-%m-%d')}\n\n"
            f"{summary.strip()}\n",
            encoding="utf-8",
        )
        self._refresh_index()
        return path

    def get_week_logs(self, week_of: datetime) -> str:
        """Get all daily logs from this week (Mon-Sun of week_of)."""
        # week_of is Sunday — back up 6 days for Monday
        monday = week_of - timedelta(days=6)
        chunks: List[str] = []
        for i in range(7):
            date = monday + timedelta(days=i)
            path = self._daily_path(date)
            if path.exists():
                chunks.append(f"### {date.strftime('%Y-%m-%d (%A)')}\n\n"
                              + path.read_text(encoding="utf-8"))
        return "\n\n".join(chunks)

    # ------------------------------------------------------------------ #
    # Full context builder (what the bot reads before responding)
    # ------------------------------------------------------------------ #

    def build_context_for_response(self) -> str:
        """Assemble the context window the bot reads before replying.

        Uses the running profile (small, ~1500 tokens) instead of
        sending 3 days of raw history (which was ~30K tokens).

        Context now includes:
        - Today's full log (needed for conversation flow)
        - Yesterday's log only if today's is very short

        The profile (managed by profile_manager.py) captures everything
        important from older conversations. This is the right tradeoff:
        the twin remembers who you are without burning tokens on raw history.
        """
        parts: List[str] = []

        today = self.get_today_context()
        if today:
            parts.append("# Today so far\n\n" + today)
        else:
            parts.append("# Today so far\n\n_(first message of the day)_")

            # If today is empty, include yesterday for continuity
            recent = self.get_recent_days(days=1)
            if recent:
                parts.append("# Yesterday\n\n" + recent)

        return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    # Quick smoke test
    cm = ContextManager("/tmp/ai_twin_test_memory")
    cm.append_to_today("user", "I'm feeling stuck today.")
    cm.append_to_today("twin", "What's the one thing you're avoiding?",
                       observation="user said 'stuck' — possible freeze state")
    print("=== Today's context ===")
    print(cm.get_today_context())
    print("\n=== Full response context ===")
    print(cm.build_context_for_response())
    print("\n=== Search 'stuck' ===")
    print(cm.search("stuck"))
    print("\n=== Forget 'stuck' ===")
    print(cm.forget("stuck"))
    print("\n=== After forget, today's context ===")
    print(cm.get_today_context())
