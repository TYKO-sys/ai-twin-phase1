"""
tools.py
========
Tool definitions for the AI twin's function calling system.

Each tool is:
- Free (no API keys beyond what's already configured)
- Android/Termux compatible (pure Python, no compiled dependencies)
- Safe (sandboxed file operations, no destructive actions)
- Useful (actually helps with daily life)

Tools available:
  1. web_search       — search the web via DuckDuckGo (no API key)
  2. read_url          — fetch a URL and extract text
  3. write_file        — write to the workspace folder
  4. read_file         — read from workspace or memory
  5. list_files        — list workspace contents
  6. save_note         — quick timestamped note
  7. get_notes         — retrieve recent notes
  8. create_task       — add to task list
  9. list_tasks        — show pending tasks
  10. complete_task    — mark a task done
  11. get_current_time — current date/time
  12. calculator       — safe math evaluation
  13. append_to_journal — add to a daily journal
  14. read_journal     — read journal entries
"""

from __future__ import annotations

import ast
import operator
import os
import re
import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests


# ---------------------------------------------------------------------- #
# Configuration
# ---------------------------------------------------------------------- #

WORKSPACE_DIR = Path.home() / "ai-twin-memory" / "workspace"
NOTES_DIR = Path.home() / "ai-twin-memory" / "notes"
TASKS_FILE = Path.home() / "ai-twin-memory" / "tasks.json"
JOURNAL_DIR = Path.home() / "ai-twin-memory" / "journal"

# Ensure directories exist
for d in (WORKSPACE_DIR, NOTES_DIR, JOURNAL_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Initialize tasks file if it doesn't exist
if not TASKS_FILE.exists():
    TASKS_FILE.write_text("[]", encoding="utf-8")


# ---------------------------------------------------------------------- #
# Tool Definitions (for Gemini's function calling API)
# ---------------------------------------------------------------------- #

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current information. Returns titles, URLs, "
            "and snippets for the top results. Use this when you need "
            "up-to-date information, facts, or want to research a topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_url",
        "description": (
            "Fetch a web page and extract its text content. Useful for "
            "reading articles, documentation, or any publicly accessible "
            "web page. Returns the text content (HTML tags removed)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default 5000)"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "write_file",
        "description": (
            "Write text content to a file in the workspace folder. "
            "Use this to save documents, drafts, research notes, or any "
            "text the user might want later. Files are stored in "
            "~/ai-twin-memory/workspace/"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the file (e.g., 'research_notes.md')"
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write"
                },
                "append": {
                    "type": "boolean",
                    "description": "If true, append to existing file. If false, overwrite."
                }
            },
            "required": ["filename", "content"]
        }
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file from the workspace folder or "
            "memory folder. Returns the text content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the file to read"
                }
            },
            "required": ["filename"]
        }
    },
    {
        "name": "list_files",
        "description": (
            "List all files in the workspace folder. Returns filenames "
            "and their sizes."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "save_note",
        "description": (
            "Save a quick timestamped note. Notes are stored in "
            "~/ai-twin-memory/notes/ and can be retrieved later. "
            "Use for ideas, reminders, or anything worth keeping."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The note content"
                },
                "category": {
                    "type": "string",
                    "description": "Optional category (e.g., 'idea', 'reminder', 'todo')"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "get_notes",
        "description": (
            "Retrieve recent notes. Optionally filter by category."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional: only return notes with this category"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max notes to return (default 10)"
                }
            }
        }
    },
    {
        "name": "create_task",
        "description": (
            "Add a task to the task list. Tasks are stored persistently "
            "and can be listed and completed later."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title of the task"
                },
                "details": {
                    "type": "string",
                    "description": "Optional longer description"
                },
                "priority": {
                    "type": "string",
                    "description": "Priority: 'high', 'medium', or 'low' (default: medium)",
                    "enum": ["high", "medium", "low"]
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional due date (YYYY-MM-DD format)"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "list_tasks",
        "description": (
            "Show all pending tasks, sorted by priority and due date."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_completed": {
                    "type": "boolean",
                    "description": "If true, also show completed tasks (default: false)"
                }
            }
        }
    },
    {
        "name": "complete_task",
        "description": "Mark a task as completed by its title or index number.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "The task title or its index number (from list_tasks)"
                }
            },
            "required": ["identifier"]
        }
    },
    {
        "name": "get_current_time",
        "description": (
            "Get the current date and time. Useful for scheduling, "
            "deadlines, or when the user asks 'what day is it?'"
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "calculator",
        "description": (
            "Evaluate a mathematical expression safely. Supports +, -, *, /, "
            "**, %, parentheses, and common math functions (sqrt, sin, cos, "
            "tan, log, etc.). Use this instead of doing math in your head."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The math expression to evaluate (e.g., '2 + 2', 'sqrt(144)', '15 * 0.085')"
                }
            },
            "required": ["expression"]
        }
    },
    {
        "name": "append_to_journal",
        "description": (
            "Add an entry to today's journal. Journal entries are dated "
            "and stored in ~/ai-twin-memory/journal/. Use for daily "
            "reflections, progress notes, or recording events."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entry": {
                    "type": "string",
                    "description": "The journal entry text"
                }
            },
            "required": ["entry"]
        }
    },
    {
        "name": "read_journal",
        "description": (
            "Read journal entries. Can read today's, a specific date, "
            "or recent entries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Specific date to read (YYYY-MM-DD). If omitted, reads today."
                },
                "days": {
                    "type": "integer",
                    "description": "Read last N days (default: 1, only if date is omitted)"
                }
            }
        }
    },
    {
        "name": "create_goal",
        "description": (
            "Create a long-term goal with motivation, timeframe, and steps. "
            "Use for big-picture aspirations like 'graduate WGU by 2027' or "
            "'build a freelance business.'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The goal"},
                "why": {"type": "string", "description": "Why this matters"},
                "timeframe": {"type": "string", "description": "When (e.g., 'by December 2026')"},
                "steps": {"type": "string", "description": "Key steps to get there"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "list_goals",
        "description": "Show all active long-term goals.",
        "parameters": {
            "type": "object",
            "properties": {
                "include_completed": {"type": "boolean", "description": "Include completed goals (default: false)"}
            }
        }
    },
    {
        "name": "draft_message",
        "description": (
            "Create a draft message (email, text, letter) for the user "
            "to review. The twin NEVER sends anything — it drafts, the "
            "user sends. Use when the user needs to write something but "
            "doesn't want to start from scratch."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_type": {"type": "string", "description": "Type: 'email', 'text', or 'letter'"},
                "recipient": {"type": "string", "description": "Who it's to"},
                "purpose": {"type": "string", "description": "What the message is about"},
                "tone": {"type": "string", "description": "Tone: 'professional', 'casual', 'apologetic', etc."}
            },
            "required": ["message_type", "recipient", "purpose"]
        }
    },
    {
        "name": "save_draft",
        "description": "Save actual draft content to the drafts folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename for the draft"},
                "content": {"type": "string", "description": "The full draft text"}
            },
            "required": ["filename", "content"]
        }
    },
    {
        "name": "list_drafts",
        "description": "List all saved drafts.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "add_contact",
        "description": (
            "Add someone to the contact tracker. Useful for remembering "
            "who to follow up with and why."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's name"},
                "relationship": {"type": "string", "description": "How you know them"},
                "notes": {"type": "string", "description": "Any notes about them"},
                "follow_up": {"type": "string", "description": "What to follow up about and when"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "list_contacts",
        "description": "List contacts, optionally filtered by who needs follow-up.",
        "parameters": {
            "type": "object",
            "properties": {
                "need_follow_up": {"type": "boolean", "description": "Only show contacts needing follow-up"}
            }
        }
    },
    {
        "name": "create_routine",
        "description": (
            "Create a routine or habit the twin should remind the user about. "
            "The twin doesn't auto-execute — it reminds during morning/evening pings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the routine"},
                "frequency": {"type": "string", "description": "How often: 'daily', 'weekly', 'Mondays', etc."},
                "action": {"type": "string", "description": "What to do"},
                "reminder_time": {"type": "string", "description": "When to remind (e.g., '9am', 'before bed')"}
            },
            "required": ["name", "frequency", "action"]
        }
    },
    {
        "name": "list_routines",
        "description": "List all active routines and habits.",
        "parameters": {"type": "object", "properties": {}}
    }
]


# The tools object as Gemini expects it
GEMINI_TOOLS_CONFIG = {
    "functionDeclarations": TOOL_DEFINITIONS
}


# ---------------------------------------------------------------------- #
# Tool Execution
# ---------------------------------------------------------------------- #

def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name with the given arguments.

    Returns a string result (or JSON string for structured data).
    """
    try:
        func = _TOOL_FUNCTIONS.get(name)
        if not func:
            return f"Error: unknown tool '{name}'"
        result = func(**args)
        return result if isinstance(result, str) else json.dumps(result, indent=2)
    except Exception as e:
        return f"Error executing {name}: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------- #
# Individual Tool Implementations
# ---------------------------------------------------------------------- #

def tool_web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo's HTML endpoint (no API key needed)."""
    num_results = min(max(num_results, 1), 10)
    try:
        # Use DuckDuckGo's HTML endpoint — free, no API key
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query, "b": ""}

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        }

        resp = requests.post(url, data=data, headers=headers, timeout=15)
        resp.raise_for_status()

        # Parse results from HTML (simple regex — DuckDuckGo's HTML is stable)
        results = []
        # Result titles and URLs are in <a class="result__a" href="...">
        title_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        # Snippets are in <a class="result__snippet" ...>
        snippet_pattern = re.compile(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL
        )

        titles = title_pattern.findall(resp.text)
        snippets = snippet_pattern.findall(resp.text)

        for i, (raw_url, raw_title) in enumerate(titles[:num_results]):
            # Clean up the URL (DuckDuckGo wraps it)
            clean_url = raw_url
            if "uddg=" in raw_url:
                # Extract actual URL from redirect
                match = re.search(r"uddg=([^&]+)", raw_url)
                if match:
                    clean_url = urllib.parse.unquote(match.group(1))

            # Strip HTML tags from title and snippet
            clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
            clean_snippet = ""
            if i < len(snippets):
                clean_snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()

            results.append(
                f"{i+1}. {clean_title}\n   URL: {clean_url}\n   {clean_snippet}"
            )

        if not results:
            # Fallback: try the lite endpoint
            url2 = "https://lite.duckduckgo.com/lite/"
            resp2 = requests.post(url2, data=data, headers=headers, timeout=15)
            # Parse lite results (simpler HTML)
            lite_results = re.findall(
                r'<a[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                resp2.text, re.DOTALL
            )
            for i, (raw_url, raw_title) in enumerate(lite_results[:num_results]):
                clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
                results.append(f"{i+1}. {clean_title}\n   URL: {raw_url}")

        if not results:
            return f"No results found for '{query}'."

        return f"Search results for '{query}':\n\n" + "\n\n".join(results)

    except requests.exceptions.Timeout:
        return f"Search timed out for '{query}'. Try again."
    except Exception as e:
        return f"Search failed: {type(e).__name__}: {e}"


def tool_read_url(url: str, max_chars: int = 5000) -> str:
    """Fetch a URL and extract text content."""
    max_chars = min(max(max_chars, 1000), 20000)
    try:
        if not url.startswith("http"):
            url = "https://" + url

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        }

        resp = requests.get(url, headers=headers, timeout=20,
                            allow_redirects=True)
        resp.raise_for_status()

        html = resp.text

        # Remove script and style tags
        html = re.sub(r"<script[^>]*>.*?</script>", "", html,
                      flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html,
                      flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Decode HTML entities (basic)
        text = text.replace("&amp;", "&").replace("&lt;", "<")
        text = text.replace("&gt;", ">").replace("&quot;", '"')
        text = text.replace("&#39;", "'").replace("&nbsp;", " ")

        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... truncated ...]"

        return f"Content from {url}:\n\n{text}"

    except requests.exceptions.Timeout:
        return f"Fetching {url} timed out."
    except Exception as e:
        return f"Failed to fetch {url}: {type(e).__name__}: {e}"


def tool_write_file(filename: str, content: str, append: bool = False) -> str:
    """Write text to a file in the workspace folder.

    Returns the FULL content so the twin can include it in its response.
    The user cannot see the workspace — everything must be in the message.
    """
    try:
        safe_name = Path(filename).name
        if not safe_name:
            return "Error: invalid filename"

        filepath = WORKSPACE_DIR / safe_name

        mode = "a" if append else "w"
        with filepath.open(mode, encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")

        action = "Appended to" if append else "Wrote"
        # Return the FULL content so the twin can paste it into its response
        return (
            f"{action} {safe_name} ({len(content)} chars).\n\n"
            f"FILE CONTENT (paste this in your response so the user can see it):\n"
            f"---\n{content}\n---"
        )
    except Exception as e:
        return f"Write failed: {type(e).__name__}: {e}"


def tool_read_file(filename: str) -> str:
    """Read a file from workspace or memory folders.

    Returns the FULL content (up to 30K chars) so the twin can include it.
    The user cannot see the workspace — everything must be in the message.
    """
    try:
        safe_name = Path(filename).name

        # Try workspace first, then memory folders
        search_paths = [
            WORKSPACE_DIR / safe_name,
            Path.home() / "ai-twin-memory" / safe_name,
            Path.home() / "ai-twin-memory" / "identity" / safe_name,
            Path.home() / "ai-twin-memory" / "daily" / safe_name,
            Path.home() / "ai-twin-memory" / "drafts" / safe_name,
            DRAFTS_DIR / safe_name,
        ]

        for path in search_paths:
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8")
                if len(content) > 30000:
                    content = content[:30000] + "\n\n[... truncated, file is longer ...]"
                return f"Contents of {path.name}:\n\n{content}"

        return f"File '{filename}' not found in workspace or memory."
    except Exception as e:
        return f"Read failed: {type(e).__name__}: {e}"


def tool_list_files() -> str:
    """List files in the workspace folder."""
    try:
        files = []
        for path in sorted(WORKSPACE_DIR.iterdir()):
            if path.is_file():
                size = path.stat().st_size
                files.append(f"  {path.name} ({size} bytes)")

        if not files:
            return "Workspace is empty."

        return "Files in workspace:\n" + "\n".join(files)
    except Exception as e:
        return f"List failed: {type(e).__name__}: {e}"


def tool_save_note(content: str, category: str = "general") -> str:
    """Save a timestamped note."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")

        # Save to today's notes file
        notes_file = NOTES_DIR / f"{date_str}.md"

        entry = f"\n## {time_str} [{category}]\n{content}\n"

        with notes_file.open("a", encoding="utf-8") as f:
            f.write(entry)

        return f"Note saved ({category}) at {time_str} on {date_str}."
    except Exception as e:
        return f"Note save failed: {type(e).__name__}: {e}"


def tool_get_notes(category: str = None, limit: int = 10) -> str:
    """Retrieve recent notes, optionally filtered by category."""
    try:
        limit = min(max(limit, 1), 50)
        notes = []

        # Get all note files, sorted by date (newest first)
        note_files = sorted(NOTES_DIR.glob("*.md"), reverse=True)

        for note_file in note_files:
            content = note_file.read_text(encoding="utf-8")
            # Parse entries
            entries = content.split("\n## ")
            for entry in entries[1:]:  # Skip preamble
                if category and f"[{category}]" not in entry:
                    continue
                notes.append(f"## {entry.strip()}")
                if len(notes) >= limit:
                    break
            if len(notes) >= limit:
                break

        if not notes:
            if category:
                return f"No notes found in category '{category}'."
            return "No notes found."

        return f"Recent notes ({len(notes)}):\n\n" + "\n\n".join(notes)
    except Exception as e:
        return f"Get notes failed: {type(e).__name__}: {e}"


def _load_tasks() -> list:
    """Load tasks from the JSON file."""
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_tasks(tasks: list) -> None:
    """Save tasks to the JSON file."""
    TASKS_FILE.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def tool_create_task(title: str, details: str = "", priority: str = "medium",
                     due_date: str = "") -> str:
    """Add a task to the task list."""
    try:
        tasks = _load_tasks()
        task = {
            "id": len(tasks) + 1,
            "title": title,
            "details": details,
            "priority": priority,
            "due_date": due_date,
            "created": datetime.now().isoformat(),
            "completed": False,
            "completed_at": None,
        }
        tasks.append(task)
        _save_tasks(tasks)

        result = f"Task created: {title}"
        if priority == "high":
            result += f" (HIGH priority)"
        if due_date:
            result += f" — due {due_date}"
        return result
    except Exception as e:
        return f"Task creation failed: {type(e).__name__}: {e}"


def tool_list_tasks(include_completed: bool = False) -> str:
    """Show all pending tasks, sorted by priority and due date."""
    try:
        tasks = _load_tasks()

        if not include_completed:
            tasks = [t for t in tasks if not t["completed"]]

        if not tasks:
            return "No pending tasks. You're all caught up."

        # Sort by priority (high > medium > low), then by due date
        priority_order = {"high": 0, "medium": 1, "low": 2}
        tasks.sort(key=lambda t: (
            priority_order.get(t.get("priority", "medium"), 1),
            t.get("due_date", "9999-12-31")
        ))

        lines = [f"Tasks ({len(tasks)} pending):"]
        for i, task in enumerate(tasks):
            status = "✓" if task["completed"] else "○"
            line = f"{i+1}. [{status}] {task['title']}"
            if task.get("priority") == "high":
                line += " [HIGH]"
            if task.get("due_date"):
                line += f" — due {task['due_date']}"
            if task.get("details"):
                line += f"\n   {task['details']}"
            lines.append(line)

        return "\n".join(lines)
    except Exception as e:
        return f"List tasks failed: {type(e).__name__}: {e}"


def tool_complete_task(identifier: str) -> str:
    """Mark a task as completed by title or index."""
    try:
        tasks = _load_tasks()

        # Try to match by index number
        try:
            idx = int(identifier) - 1
            # Find the idx-th non-completed task
            count = 0
            for task in tasks:
                if not task["completed"]:
                    if count == idx:
                        task["completed"] = True
                        task["completed_at"] = datetime.now().isoformat()
                        _save_tasks(tasks)
                        return f"Completed: {task['title']}"
                    count += 1
            return f"Task #{identifier} not found (or already completed)."
        except ValueError:
            pass

        # Try to match by title (case-insensitive, partial match)
        identifier_lower = identifier.lower()
        for task in tasks:
            if not task["completed"] and identifier_lower in task["title"].lower():
                task["completed"] = True
                task["completed_at"] = datetime.now().isoformat()
                _save_tasks(tasks)
                return f"Completed: {task['title']}"

        return f"No pending task matching '{identifier}' found."
    except Exception as e:
        return f"Complete task failed: {type(e).__name__}: {e}"


def tool_get_current_time() -> str:
    """Get current date and time."""
    now = datetime.now()
    return (
        f"Current date: {now.strftime('%A, %B %d, %Y')}\n"
        f"Current time: {now.strftime('%I:%M %p')}\n"
        f"ISO format: {now.isoformat()}\n"
        f"Unix timestamp: {int(now.timestamp())}"
    )


# Safe math evaluation — only allows basic operators and math functions
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.FloorDiv: operator.floordiv,
}

_SAFE_FUNCTIONS = {
    "sqrt": __import__("math").sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sin": __import__("math").sin,
    "cos": __import__("math").cos,
    "tan": __import__("math").tan,
    "log": __import__("math").log,
    "log10": __import__("math").log10,
    "pi": __import__("math").pi,
    "e": __import__("math").e,
    "ceil": __import__("math").ceil,
    "floor": __import__("math").floor,
}


def _safe_eval(node):
    """Recursively evaluate an AST node safely."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {type(node.value)}")
    elif isinstance(node, ast.BinOp):
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        op_type = type(node.op)
        if op_type in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported operator: {op_type.__name__}")
    elif isinstance(node, ast.UnaryOp):
        operand = _safe_eval(node.operand)
        op_type = type(node.op)
        if op_type in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls allowed")
        func_name = node.func.id
        if func_name not in _SAFE_FUNCTIONS:
            raise ValueError(f"Function '{func_name}' not allowed")
        func = _SAFE_FUNCTIONS[func_name]
        args = [_safe_eval(arg) for arg in node.args]
        return func(*args)
    elif isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCTIONS:
            return _SAFE_FUNCTIONS[node.id]
        raise ValueError(f"Unknown variable: {node.id}")
    else:
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


def tool_calculator(expression: str) -> str:
    """Safely evaluate a math expression."""
    try:
        # Remove whitespace
        expr = expression.strip()
        if not expr:
            return "Error: empty expression"

        # Parse the expression into an AST
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree.body)

        if isinstance(result, float):
            # Clean up floating point
            if result == int(result):
                result = int(result)
            else:
                result = round(result, 10)

        return f"{expression} = {result}"
    except SyntaxError:
        return f"Error: invalid expression '{expression}'"
    except ValueError as e:
        return f"Error: {e}"
    except ZeroDivisionError:
        return f"Error: division by zero"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def tool_append_to_journal(entry: str) -> str:
    """Add an entry to today's journal."""
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")
        journal_file = JOURNAL_DIR / f"{date_str}.md"

        header = ""
        if not journal_file.exists():
            header = f"# Journal — {date_str}\n\n"

        content = f"## {time_str}\n{entry}\n\n"

        with journal_file.open("a", encoding="utf-8") as f:
            if header:
                f.write(header)
            f.write(content)

        return f"Journal entry saved at {time_str} on {date_str}."
    except Exception as e:
        return f"Journal save failed: {type(e).__name__}: {e}"


def tool_read_journal(date: str = "", days: int = 1) -> str:
    """Read journal entries."""
    try:
        if date:
            # Read specific date
            journal_file = JOURNAL_DIR / f"{date}.md"
            if journal_file.exists():
                return f"Journal for {date}:\n\n" + \
                       journal_file.read_text(encoding="utf-8")
            return f"No journal entry for {date}."

        # Read last N days
        days = min(max(days, 1), 30)
        entries = []
        for i in range(days):
            day = datetime.now() - __import__("datetime").timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            journal_file = JOURNAL_DIR / f"{date_str}.md"
            if journal_file.exists():
                entries.append(f"### {date_str}\n\n" +
                               journal_file.read_text(encoding="utf-8"))

        if not entries:
            return "No journal entries found."

        return "\n\n---\n\n".join(entries)
    except Exception as e:
        return f"Read journal failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------- #
# Dynamic Tools — Goal tracking, decisions, contacts, drafts
# ---------------------------------------------------------------------- #

GOALS_FILE = Path.home() / "ai-twin-memory" / "goals.json"
CONTACTS_FILE = Path.home() / "ai-twin-memory" / "contacts.json"
DRAFTS_DIR = Path.home() / "ai-twin-memory" / "drafts"

for f in [GOALS_FILE, CONTACTS_FILE]:
    if not f.exists():
        f.write_text("[]", encoding="utf-8")
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_json(path: Path, data: list) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def tool_create_goal(title: str, why: str = "", timeframe: str = "",
                     steps: str = "") -> str:
    """Create a long-term goal with steps and motivation."""
    try:
        goals = _load_json(GOALS_FILE)
        goal = {
            "id": len(goals) + 1,
            "title": title,
            "why": why,
            "timeframe": timeframe,
            "steps": steps,
            "created": datetime.now().isoformat(),
            "completed": False,
        }
        goals.append(goal)
        _save_json(GOALS_FILE, goals)
        result = f"Goal created: {title}"
        if why:
            result += f"\n   Why: {why}"
        if timeframe:
            result += f"\n   Timeframe: {timeframe}"
        if steps:
            result += f"\n   Steps: {steps}"
        return result
    except Exception as e:
        return f"Goal creation failed: {type(e).__name__}: {e}"


def tool_list_goals(include_completed: bool = False) -> str:
    """Show all active goals."""
    try:
        goals = _load_json(GOALS_FILE)
        if not include_completed:
            goals = [g for g in goals if not g.get("completed")]
        if not goals:
            return "No active goals."
        lines = [f"Goals ({len(goals)} active):"]
        for i, g in enumerate(goals):
            status = "✓" if g.get("completed") else "○"
            line = f"{i+1}. [{status}] {g['title']}"
            if g.get("timeframe"):
                line += f" ({g['timeframe']})"
            if g.get("why"):
                line += f"\n   Why: {g['why']}"
            if g.get("steps"):
                line += f"\n   Steps: {g['steps']}"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        return f"List goals failed: {type(e).__name__}: {e}"


def tool_draft_message(message_type: str, recipient: str, purpose: str,
                       tone: str = "professional") -> str:
    """Draft a message (email, text, letter) for the user to review and send.

    The draft is saved to the drafts folder. The user reviews it and
    sends it themselves — the twin never sends anything directly.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_recipient = "".join(c if c.isalnum() else "_" for c in recipient)
        filename = f"{message_type}_to_{safe_recipient}_{timestamp}.md"
        filepath = DRAFTS_DIR / filename

        # This is a template — the actual content will be filled by the LLM
        # when it calls this tool, then sends the draft as its response
        draft_content = f"""# {message_type.upper()} DRAFT

To: {recipient}
Purpose: {purpose}
Tone: {tone}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

[Draft content will be generated by the twin and placed here]

---

Saved to: {filepath}
"""

        filepath.write_text(draft_content, encoding="utf-8")
        return (f"Draft template created for {message_type} to {recipient}. "
                f"File: {filename}. Now write the actual draft content "
                f"and I'll save it to this file.")
    except Exception as e:
        return f"Draft creation failed: {type(e).__name__}: {e}"


def tool_save_draft(filename: str, content: str) -> str:
    """Save actual draft content to a file in the drafts folder."""
    try:
        safe_name = Path(filename).name
        filepath = DRAFTS_DIR / safe_name
        filepath.write_text(content, encoding="utf-8")
        return f"Draft saved to {safe_name} ({len(content)} chars). "
    except Exception as e:
        return f"Save draft failed: {type(e).__name__}: {e}"


def tool_list_drafts() -> str:
    """List all saved drafts."""
    try:
        files = sorted(DRAFTS_DIR.glob("*.md"), reverse=True)
        if not files:
            return "No drafts saved."
        lines = [f"Drafts ({len(files)}):"]
        for f in files[:20]:
            size = f.stat().st_size
            lines.append(f"  {f.name} ({size} bytes)")
        return "\n".join(lines)
    except Exception as e:
        return f"List drafts failed: {type(e).__name__}: {e}"


def tool_add_contact(name: str, relationship: str = "",
                     notes: str = "", follow_up: str = "") -> str:
    """Add someone to the contact tracker with follow-up notes."""
    try:
        contacts = _load_json(CONTACTS_FILE)
        contact = {
            "id": len(contacts) + 1,
            "name": name,
            "relationship": relationship,
            "notes": notes,
            "follow_up": follow_up,
            "added": datetime.now().isoformat(),
        }
        contacts.append(contact)
        _save_json(CONTACTS_FILE, contacts)
        result = f"Contact added: {name}"
        if relationship:
            result += f" ({relationship})"
        if follow_up:
            result += f"\n   Follow up: {follow_up}"
        return result
    except Exception as e:
        return f"Contact add failed: {type(e).__name__}: {e}"


def tool_list_contacts(need_follow_up: bool = False) -> str:
    """List contacts, optionally filtered by who needs follow-up."""
    try:
        contacts = _load_json(CONTACTS_FILE)
        if need_follow_up:
            contacts = [c for c in contacts if c.get("follow_up")]
        if not contacts:
            return "No contacts found."
        lines = [f"Contacts ({len(contacts)}):"]
        for i, c in enumerate(contacts):
            line = f"{i+1}. {c['name']}"
            if c.get("relationship"):
                line += f" — {c['relationship']}"
            if c.get("follow_up"):
                line += f"\n   Follow up: {c['follow_up']}"
            if c.get("notes"):
                line += f"\n   Notes: {c['notes']}"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        return f"List contacts failed: {type(e).__name__}: {e}"


def tool_create_routine(name: str, frequency: str, action: str,
                        reminder_time: str = "") -> str:
    """Create a routine/habit the twin should remind the user about.

    Routines are stored and the twin can reference them during morning
    and evening pings. The twin doesn't auto-execute them — it reminds.
    """
    try:
        routines_file = Path.home() / "ai-twin-memory" / "routines.json"
        routines = _load_json(routines_file)
        routine = {
            "id": len(routines) + 1,
            "name": name,
            "frequency": frequency,
            "action": action,
            "reminder_time": reminder_time,
            "created": datetime.now().isoformat(),
            "active": True,
        }
        routines.append(routine)
        _save_json(routines_file, routines)
        return (f"Routine created: {name}\n"
                f"   Frequency: {frequency}\n"
                f"   Action: {action}\n"
                + (f"   Reminder: {reminder_time}\n" if reminder_time else ""))
    except Exception as e:
        return f"Routine creation failed: {type(e).__name__}: {e}"


def tool_list_routines() -> str:
    """List all active routines/habits."""
    try:
        routines_file = Path.home() / "ai-twin-memory" / "routines.json"
        routines = _load_json(routines_file)
        routines = [r for r in routines if r.get("active")]
        if not routines:
            return "No active routines."
        lines = [f"Routines ({len(routines)} active):"]
        for i, r in enumerate(routines):
            line = f"{i+1}. {r['name']} ({r['frequency']})"
            line += f"\n   {r['action']}"
            if r.get("reminder_time"):
                line += f"\n   Reminder: {r['reminder_time']}"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        return f"List routines failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------- #
# Tool Function Registry
# ---------------------------------------------------------------------- #

_TOOL_FUNCTIONS = {
    "web_search": tool_web_search,
    "read_url": tool_read_url,
    "write_file": tool_write_file,
    "read_file": tool_read_file,
    "list_files": tool_list_files,
    "save_note": tool_save_note,
    "get_notes": tool_get_notes,
    "create_task": tool_create_task,
    "list_tasks": tool_list_tasks,
    "complete_task": tool_complete_task,
    "get_current_time": tool_get_current_time,
    "calculator": tool_calculator,
    "append_to_journal": tool_append_to_journal,
    "read_journal": tool_read_journal,
    "create_goal": tool_create_goal,
    "list_goals": tool_list_goals,
    "draft_message": tool_draft_message,
    "save_draft": tool_save_draft,
    "list_drafts": tool_list_drafts,
    "add_contact": tool_add_contact,
    "list_contacts": tool_list_contacts,
    "create_routine": tool_create_routine,
    "list_routines": tool_list_routines,
}


# ---------------------------------------------------------------------- #
# Self-test
# ---------------------------------------------------------------------- #

if __name__ == "__main__":
    print("=== Tool definitions ===")
    print(f"{len(TOOL_DEFINITIONS)} tools defined")
    for t in TOOL_DEFINITIONS:
        print(f"  - {t['name']}")
    print()

    print("=== Testing calculator ===")
    print(tool_calculator("2 + 2"))
    print(tool_calculator("sqrt(144)"))
    print(tool_calculator("15 * 0.085"))
    print(tool_calculator("2 ** 10"))
    print()

    print("=== Testing get_current_time ===")
    print(tool_get_current_time())
    print()

    print("=== Testing save_note ===")
    print(tool_save_note("Test note from tools.py", category="test"))
    print()

    print("=== Testing get_notes ===")
    print(tool_get_notes(limit=3))
    print()

    print("=== Testing create_task ===")
    print(tool_create_task("Test task", priority="high"))
    print()

    print("=== Testing list_tasks ===")
    print(tool_list_tasks())
    print()

    print("=== Testing list_files ===")
    print(tool_list_files())
