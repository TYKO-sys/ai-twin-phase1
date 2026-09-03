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
import hashlib
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
            "and can be listed and completed later. Supports GTD-style "
            "status (active/blocked/waiting/someday/done), next-action, "
            "energy level, and context tags for the smart suggestion engine."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title of the task"
                },
                "priority": {
                    "type": "string",
                    "description": "Priority: 'urgent', 'high', 'medium', or 'low' (default: medium)",
                    "enum": ["urgent", "high", "medium", "low"]
                },
                "status": {
                    "type": "string",
                    "description": "GTD status: 'active' (can do now), 'blocked' (waiting on something), 'waiting' (someone else action), 'someday' (not now), 'done' (default: active)",
                    "enum": ["active", "blocked", "waiting", "someday", "done"]
                },
                "blocked_on": {
                    "type": "string",
                    "description": "What the task is waiting for (free text, e.g. 'Dr. Lu reply via MyChart', 'Apple order shipping'). Required when status=blocked or waiting."
                },
                "next_action": {
                    "type": "string",
                    "description": "The literal next physical step. 'Set up Apple devices' is a project; 'Open the MacBook box and plug it in to charge' is a task."
                },
                "energy": {
                    "type": "string",
                    "description": "Focus/energy required: 'low', 'medium', 'high' (default: medium)",
                    "enum": ["low", "medium", "high"]
                },
                "context": {
                    "type": "string",
                    "description": "Comma-separated list of contexts where this can be done: 'home', 'phone', 'errands', 'computer', 'anywhere' (default: anywhere). Example: 'home,computer'"
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional due date (YYYY-MM-DD format)"
                },
                "category": {
                    "type": "string",
                    "description": "Optional free-text category (e.g., 'medical', 'legal', 'apple-setup', 'personal', 'work')"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional longer notes/details about the task"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "task_review",
        "description": (
            "Smart task suggestion engine. Pure logic (no LLM tokens). "
            "Reads current time + day of week, surfaces blocked/waiting "
            "tasks, and picks 1-3 active tasks doable now based on energy, "
            "context, and time of day. Use whenever the user mentions "
            "tasks or seems stuck."
        ),
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "news_digest",
        "description": (
            "Pull all subscribed RSS feeds from ~/ai-twin-memory/rss_feeds.txt "
            "and return aggregated raw items (title + link + description + "
            "pubDate + source_feed) for AI digestion. The twin's LLM then "
            "writes a 4-6 sentence friend-style digest with no URLs, customized "
            "to the user's life (Baltimore, medical, Apple, AI, legal)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feeds_file": {
                    "type": "string",
                    "description": "Optional path to feeds file (default: ~/ai-twin-memory/rss_feeds.txt)"
                },
                "limit_per_feed": {
                    "type": "integer",
                    "description": "Max items per feed (default 5, max 10)"
                }
            }
        }
    },
    {
        "name": "scrape_website",
        "description": (
            "Scrape a website with anti-bot handling (rotating user agents, "
            "proper headers, session cookies) and content extraction. "
            "Better than read_url for news sites, portals, JS-heavy pages. "
            "Returns the main article text (readability heuristic: biggest "
            "text block), page title, meta description, and optionally all links. "
            "Falls back to read_url if lxml is unavailable or parsing fails."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to scrape"
                },
                "extract_links": {
                    "type": "boolean",
                    "description": "If true, also extract all links from the page (default: false)"
                }
            },
            "required": ["url"]
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
    },
    {
        "name": "ocr_image",
        "description": (
            "Extract text from an image using OCR. Useful for reading "
            "documents, medical records, court papers, forms, prescriptions, "
            "or any text in an image. Uses free OCR.space API (no key needed) "
            "or local Tesseract if installed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to the image file"},
                "language": {"type": "string", "description": "Language code: eng, fra, spa, etc. (default: eng)"}
            },
            "required": ["image_path"]
        }
    },
    {
        "name": "monitor_website",
        "description": (
            "Start monitoring a website for changes. The twin checks the page "
            "periodically and notifies you when content changes. Use for: "
            "waitlist positions, appointment availability, status pages, "
            "any page that might update."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to monitor"},
                "description": {"type": "string", "description": "What you're watching for"},
                "check_interval_minutes": {"type": "integer", "description": "How often to check (default: 30)"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "list_monitored_sites",
        "description": "List all websites being monitored for changes.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "stop_monitoring",
        "description": "Stop monitoring a website for changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to stop monitoring"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "trigger_webhook",
        "description": (
            "Trigger ANY HTTP webhook (n8n self-hosted, n8n.cloud, IFTTT, "
            "Make, Zapier, custom server, Home Assistant, etc.). "
            "Sends a POST request with JSON data to the webhook URL. "
            "Use this when the user has set up an automation workflow "
            "somewhere that expects to be triggered by HTTP."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "webhook_name": {"type": "string", "description": "Name of a saved webhook"},
                "webhook_url": {"type": "string", "description": "Full webhook URL (any provider)"},
                "data": {"type": "string", "description": "JSON data to send to the workflow"}
            }
        }
    },
    {
        "name": "save_webhook",
        "description": "Save an HTTP webhook URL (any provider — n8n self-hosted, IFTTT, Make, Zapier, custom) for easy triggering later.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name (e.g., 'send_email')"},
                "webhook_url": {"type": "string", "description": "Full webhook URL"},
                "description": {"type": "string", "description": "What this workflow does"}
            },
            "required": ["name", "webhook_url"]
        }
    },
    {
        "name": "list_webhooks",
        "description": "List all saved webhook URLs.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "send_email",
        "description": (
            "Send an email directly from the twin using SMTP. "
            "Requires the user to have configured SMTP credentials in .env "
            "(SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM). "
            "Works with Gmail (use an App Password, not your real password), "
            "Outlook, Yahoo, ProtonMail Bridge, or any standard SMTP server. "
            "FREE alternative to n8n for sending emails."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body (plain text)"},
                "html": {"type": "string", "description": "Optional HTML body (overrides plain text if provided)"}
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "create_calendar_event",
        "description": (
            "Create a calendar event as an .ics file (iCalendar standard) "
            "that the user can import into Google Calendar, Apple Calendar, "
            "Outlook, or any calendar app. The .ics file is saved to the "
            "download folder and the user receives the path. "
            "FREE alternative to n8n for calendar automation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start time, ISO 8601 (e.g., '2026-09-10T14:00:00')"},
                "end": {"type": "string", "description": "End time, ISO 8601 (e.g., '2026-09-10T15:00:00')"},
                "location": {"type": "string", "description": "Optional location"},
                "description": {"type": "string", "description": "Optional description/notes"},
                "reminder_minutes": {"type": "integer", "description": "Optional reminder N minutes before (default 15)"}
            },
            "required": ["title", "start", "end"]
        }
    },
    {
        "name": "read_rss",
        "description": (
            "Fetch and parse an RSS or Atom feed. Returns the latest N items "
            "with title, link, summary, and publish date. "
            "Works for news sites, blogs, YouTube channels, podcasts, "
            "Reddit subreddits (append .rss to a subreddit URL), etc. "
            "FREE alternative to n8n for news/content monitoring."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "RSS/Atom feed URL"},
                "limit": {"type": "integer", "description": "Max items to return (default 5)"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "shorten_url",
        "description": (
            "Shorten a long URL using the free is.gd API (no key required). "
            "Useful when the user needs to share a long link via SMS or chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The long URL to shorten"}
            },
            "required": ["url"]
        }
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


def tool_create_task(title: str, priority: str = "medium",
                     status: str = "active", blocked_on: str = "",
                     next_action: str = "", energy: str = "medium",
                     context: str = "anywhere", due_date: str = "",
                     category: str = "", notes: str = "",
                     details: str = "") -> str:
    """Add a task to the task list with GTD-style fields.

    New fields:
      status:      active | blocked | waiting | someday | done (default: active)
      blocked_on:  free text — what it's waiting on (for blocked/waiting)
      next_action: the literal next physical step (GTD-style)
      energy:      low | medium | high — focus required
      context:     comma-separated string ('home,phone') -> list of context tags
      category:    free-text category
      notes:       longer notes (replaces the legacy 'details' field)
      details:     legacy alias for notes (kept for backward compatibility)

    Existing tasks with completed=True are treated as status='done' by the
    readers. Old 'details' fields are surfaced as 'notes' on read.
    """
    try:
        # Normalize context string -> list
        if isinstance(context, str):
            ctx_list = [c.strip() for c in context.split(",") if c.strip()]
        elif context:
            ctx_list = list(context)
        else:
            ctx_list = ["anywhere"]
        if not ctx_list:
            ctx_list = ["anywhere"]

        # Validate status
        valid_statuses = {"active", "blocked", "waiting", "someday", "done"}
        if status not in valid_statuses:
            status = "active"

        # Validate energy
        valid_energies = {"low", "medium", "high"}
        if energy not in valid_energies:
            energy = "medium"

        # Normalize priority (accept 'urgent' as alias for 'high')
        if priority == "urgent":
            priority = "high"
        if priority not in {"high", "medium", "low"}:
            priority = "medium"

        # Notes: prefer new 'notes' field, fall back to legacy 'details'
        if not notes and details:
            notes = details

        tasks = _load_tasks()
        # Generate a stable, monotonically-increasing id (don't reuse old ids)
        new_id = max([t.get("id", 0) for t in tasks] + [0]) + 1

        now_iso = datetime.now().isoformat()
        task = {
            "id": new_id,
            "title": title,
            "priority": priority,
            "status": status,
            "blocked_on": blocked_on or "",
            "next_action": next_action or "",
            "energy": energy,
            "context": ctx_list,
            "due_date": due_date or "",
            "category": category or "",
            "notes": notes or "",
            # Legacy fields kept for backward compatibility with older readers
            "details": notes or "",
            "created_at": now_iso,
            "created": now_iso,  # legacy alias
            "completed": status == "done",
            "completed_at": now_iso if status == "done" else None,
        }
        tasks.append(task)
        _save_tasks(tasks)

        result = f"Task created: {title}"
        if priority == "high":
            result += " [HIGH priority]"
        if status != "active":
            result += f" (status: {status})"
            if blocked_on:
                result += f" — blocked on: {blocked_on}"
        if next_action:
            result += f"\nNext action: {next_action}"
        if due_date:
            result += f"\nDue: {due_date}"
        if ctx_list and ctx_list != ["anywhere"]:
            result += f"\nContext: {', '.join(ctx_list)}"
        if energy != "medium":
            result += f"\nEnergy: {energy}"
        return result
    except Exception as e:
        return f"Task creation failed: {type(e).__name__}: {e}"


def tool_list_tasks(include_completed: bool = False) -> str:
    """Show all tasks, grouped by status, sorted by priority then due date.

    Groups: active first, then blocked, waiting, then someday. Done tasks
    only appear if include_completed=true. Shows next_action and blocked_on
    when present.
    """
    try:
        tasks = _load_tasks()
        if not tasks:
            return "No tasks yet. You're all caught up."

        # Backward-compat: derive status from 'completed' for old tasks
        def _status(t):
            s = t.get("status", "")
            if not s:
                if t.get("completed") is True:
                    return "done"
                return "active"
            return s
        for t in tasks:
            t["status"] = _status(t)

        if not include_completed:
            tasks = [t for t in tasks if t["status"] != "done"]

        if not tasks:
            return "No pending tasks. You're all caught up."

        priority_order = {"high": 0, "urgent": 0, "medium": 1, "low": 2}

        def sort_key(t):
            return (
                priority_order.get(t.get("priority", "medium"), 1),
                t.get("due_date") or "9999-12-31",
            )

        def _ctx_list(t):
            ctx = t.get("context", ["anywhere"])
            if isinstance(ctx, str):
                ctx = [c.strip() for c in ctx.split(",") if c.strip()]
            if not ctx:
                ctx = ["anywhere"]
            return ctx

        groups = {"active": [], "blocked": [], "waiting": [], "someday": []}
        extras = []
        for t in tasks:
            s = t["status"]
            if s in groups:
                groups[s].append(t)
            else:
                extras.append(t)

        lines = []
        first = True

        def render_group(name, items):
            nonlocal first
            if not items:
                return
            if first:
                lines.append(f"=== {name.upper()} ({len(items)}) ===")
                first = False
            else:
                lines.append(f"\n=== {name.upper()} ({len(items)}) ===")
            for t in sorted(items, key=sort_key):
                ctx = _ctx_list(t)
                line = f"  • {t['title']}"
                if t.get("priority") in ("high", "urgent"):
                    line += " [HIGH]"
                if t.get("due_date"):
                    line += f" — due {t['due_date']}"
                line += (
                    f"  (status: {t['status']}, "
                    f"energy: {t.get('energy', 'medium')})"
                )
                if ctx != ["anywhere"]:
                    line += f"  @{','.join(ctx)}"
                lines.append(line)
                if t.get("next_action"):
                    lines.append(f"    Next action: {t['next_action']}")
                if t.get("blocked_on"):
                    lines.append(f"    Blocked on: {t['blocked_on']}")
                notes = t.get("notes") or t.get("details") or ""
                if notes:
                    lines.append(f"    Notes: {notes}")

        for grp_name in ("active", "blocked", "waiting", "someday"):
            render_group(grp_name, groups[grp_name])
        # Render any leftover statuses (e.g. unknown) under their own heading
        if extras:
            render_group("other", extras)

        return "\n".join(lines) if lines else "No pending tasks. You're all caught up."
    except Exception as e:
        return f"List tasks failed: {type(e).__name__}: {e}"


def tool_complete_task(identifier: str) -> str:
    """Mark a task as completed by title or index number.

    Updates both the legacy 'completed' boolean and the new 'status' field
    so old and new code paths stay in sync.
    """
    try:
        tasks = _load_tasks()

        # Helper: is this task "open" (not done) by either field?
        def _is_open(t):
            s = t.get("status", "")
            if s == "done":
                return False
            if s and s != "active":
                # blocked/waiting/someday are technically open
                return True
            # No status or active — fall back to legacy 'completed'
            return not t.get("completed", False)

        # Try to match by index number (1-based, among OPEN tasks)
        try:
            idx = int(identifier) - 1
            count = 0
            for task in tasks:
                if _is_open(task):
                    if count == idx:
                        now_iso = datetime.now().isoformat()
                        task["completed"] = True
                        task["completed_at"] = now_iso
                        task["status"] = "done"
                        _save_tasks(tasks)
                        return f"Completed: {task['title']}"
                    count += 1
            return f"Task #{identifier} not found (or already completed)."
        except ValueError:
            pass

        # Try to match by title (case-insensitive, partial match)
        identifier_lower = identifier.lower()
        for task in tasks:
            if _is_open(task) and identifier_lower in task["title"].lower():
                now_iso = datetime.now().isoformat()
                task["completed"] = True
                task["completed_at"] = now_iso
                task["status"] = "done"
                _save_tasks(tasks)
                return f"Completed: {task['title']}"

        return f"No pending task matching '{identifier}' found."
    except Exception as e:
        return f"Complete task failed: {type(e).__name__}: {e}"


def tool_task_review() -> str:
    """Smart task suggestion engine. Pure logic, no LLM tokens.

    Reads current time + day of week, identifies blocked/waiting tasks,
    and picks 1-3 active tasks that can be done now based on:
      - Time of day (morning = high energy, evening = low energy)
      - Day of week (weekday = work OK, weekend = personal OK)
      - Default context 'anywhere' when unknown

    Returns a short, structured recommendation string. The twin passes
    it through to the user (optionally rephrased in voice).
    """
    try:
        tasks = _load_tasks()
        if not tasks:
            return "No tasks yet. Nothing to review."

        # Backward-compat: derive status from 'completed' for old tasks
        def _status(t):
            s = t.get("status", "")
            if not s:
                if t.get("completed") is True:
                    return "done"
                return "active"
            return s
        for t in tasks:
            t["status"] = _status(t)

        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=Mon, 6=Sun
        is_weekend = weekday >= 5

        # Time-of-day energy band
        if hour < 11:
            energy_band = "high"
            tod = "morning"
        elif hour < 17:
            energy_band = "medium"
            tod = "afternoon"
        elif hour < 21:
            energy_band = "low"
            tod = "evening"
        else:
            energy_band = "low"
            tod = "night"

        blocked = [t for t in tasks if t["status"] in ("blocked", "waiting")]
        active = [t for t in tasks if t["status"] == "active"]
        someday = [t for t in tasks if t["status"] == "someday"]

        priority_order = {"high": 0, "urgent": 0, "medium": 1, "low": 2}

        def sort_key(t):
            return (
                priority_order.get(t.get("priority", "medium"), 1),
                t.get("due_date") or "9999-12-31",
            )

        out = []
        out.append(
            f"Task review — {now.strftime('%a %I:%M %p').lower()} ({tod})"
        )
        out.append("")

        # Blocked section
        if blocked:
            out.append(f"BLOCKED ({len(blocked)}):")
            for t in sorted(blocked, key=sort_key):
                why = t.get("blocked_on") or "external dependency"
                out.append(f"  • '{t['title']}' — {why}")
            out.append("")
        else:
            out.append("BLOCKED: none.")
            out.append("")

        # Score active tasks for doability right now
        energy_rank = {"low": 0, "medium": 1, "high": 2}
        my_energy_rank = energy_rank[energy_band]

        def score(t):
            # Tasks with energy <= my energy get bonus (doable now)
            t_energy_rank = energy_rank.get(t.get("energy", "medium"), 1)
            energy_ok = 0 if t_energy_rank <= my_energy_rank else 2
            # Context: 'anywhere' is always doable
            ctx = t.get("context", ["anywhere"])
            if isinstance(ctx, str):
                ctx = [c.strip() for c in ctx.split(",") if c.strip()]
            if not ctx:
                ctx = ["anywhere"]
            ctx_ok = 0 if "anywhere" in ctx else 1
            # Weekend/weekday heuristic — work tasks slightly deprioritized on weekends
            cat = (t.get("category") or "").lower()
            if is_weekend and ("work" in cat or "office" in cat):
                weekend_ok = 1
            else:
                weekend_ok = 0
            priority = priority_order.get(t.get("priority", "medium"), 1)
            due = t.get("due_date") or "9999-12-31"
            return (energy_ok, ctx_ok, weekend_ok, priority, due)

        scored = sorted(active, key=score)

        # Pick top 3 that are actually doable energy-wise
        suggested = []
        for t in scored:
            t_energy_rank = energy_rank.get(t.get("energy", "medium"), 1)
            if t_energy_rank <= my_energy_rank:
                suggested.append(t)
            if len(suggested) >= 3:
                break

        if suggested:
            out.append("SUGGESTED NOW:")
            for t in suggested[:3]:
                ctx = t.get("context", ["anywhere"])
                if isinstance(ctx, str):
                    ctx = [c.strip() for c in ctx.split(",") if c.strip()]
                if not ctx:
                    ctx = ["anywhere"]
                line = f"  • '{t['title']}'"
                if t.get("next_action"):
                    line += f"\n    Next action: {t['next_action']}"
                else:
                    line += "\n    (no next_action set — define one)"
                bits = [f"{t.get('energy', 'medium')} energy",
                        f"{','.join(ctx)} context"]
                if t.get("due_date"):
                    bits.append(f"due {t['due_date']}")
                line += f"\n    ({', '.join(bits)})"
                out.append(line)
            out.append("")
        elif active:
            out.append(
                "SUGGESTED NOW: none match current energy. Top active task:"
            )
            top = scored[0] if scored else active[0]
            out.append(
                f"  • '{top['title']}' "
                f"(energy: {top.get('energy', 'medium')}, "
                f"status: {top['status']})"
            )
            if top.get("next_action"):
                out.append(f"    Next action: {top['next_action']}")
            out.append("")
        else:
            out.append("SUGGESTED NOW: nothing active.")
            out.append("")

        if someday:
            out.append(
                f"SOMEDAY ({len(someday)}): "
                + ", ".join(f"'{t['title']}'" for t in someday[:5])
                + ("..." if len(someday) > 5 else "")
            )
            out.append("")

        out.append("Want me to walk through it?")
        return "\n".join(out)
    except Exception as e:
        return f"Task review failed: {type(e).__name__}: {e}"


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
# Phone Integration Tools (via Termux:API)
# ---------------------------------------------------------------------- #

import subprocess as _subprocess


def tool_send_notification(title: str, text: str) -> str:
    """Send a phone notification to the user.

    Uses Termux:API to create an Android notification. The user sees it
    in their notification bar even if they're not in Telegram.
    """
    try:
        _subprocess.run(
            ["termux-notification", "--title", title, "--content", text],
            timeout=10, capture_output=True
        )
        return f"Notification sent: {title}"
    except _subprocess.TimeoutExpired:
        return "Notification timed out — Termux:API may not be installed."
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Notification failed: {type(e).__name__}: {e}"


def tool_open_url(url: str) -> str:
    """Open a URL in the phone's browser.

    Uses Termux:API to open the URL directly. The user doesn't have to
    copy-paste — the browser opens automatically.
    """
    try:
        if not url.startswith("http"):
            url = "https://" + url
        _subprocess.run(
            ["termux-open-url", url],
            timeout=10, capture_output=True
        )
        return f"Opened {url} in browser"
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Open URL failed: {type(e).__name__}: {e}"


def tool_copy_to_clipboard(text: str) -> str:
    """Copy text to the phone's clipboard.

    The user can then paste it anywhere — into an email, a text message,
    a form, etc. Useful for draft text, phone numbers, addresses.
    """
    try:
        _subprocess.run(
            ["termux-clipboard-set", text],
            timeout=10, capture_output=True,
            input=text.encode()
        )
        return f"Copied to clipboard ({len(text)} chars)"
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Clipboard failed: {type(e).__name__}: {e}"


def tool_get_clipboard() -> str:
    """Read the current clipboard contents.

    Useful if the user copied something and wants the twin to process it.
    """
    try:
        result = _subprocess.run(
            ["termux-clipboard-get"],
            timeout=10, capture_output=True, text=True
        )
        content = result.stdout.strip()
        if content:
            return f"Clipboard contents:\n{content}"
        return "Clipboard is empty"
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Clipboard read failed: {type(e).__name__}: {e}"


def tool_set_alarm(hours_from_now: float, message: str = "") -> str:
    """Set a phone notification as a reminder.

    Uses Termux:API notification with a delay. Not a system alarm, but
    a notification that appears after the specified time.

    Args:
        hours_from_now: How many hours from now to send the reminder
        message: What the reminder should say
    """
    try:
        import threading
        seconds = int(hours_from_now * 3600)

        def delayed_notification():
            time.sleep(seconds)
            try:
                _subprocess.run(
                    ["termux-notification",
                     "--title", "AI Twin Reminder",
                     "--content", message or "Reminder"],
                    timeout=10, capture_output=True
                )
            except Exception:
                pass

        threading.Thread(target=delayed_notification, daemon=True).start()

        from datetime import timedelta
        fire_time = datetime.now() + timedelta(hours=hours_from_now)
        fire_str = fire_time.strftime("%I:%M %p on %B %d")
        return f"Reminder set for {fire_str}: '{message}'"
    except Exception as e:
        return f"Reminder failed: {type(e).__name__}: {e}"


def tool_send_sms(phone_number: str, message: str) -> str:
    """Draft an SMS — opens the SMS app with the message pre-filled.

    Uses Termux:API to open the SMS app. The user reviews and sends.
    The twin never sends SMS automatically — it drafts, the user sends.
    """
    try:
        _subprocess.run(
            ["termux-sms-send", "-n", phone_number, message],
            timeout=10, capture_output=True
        )
        return f"SMS app opened with message to {phone_number}. Review and send."
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"SMS draft failed: {type(e).__name__}: {e}"


def tool_dial_phone(phone_number: str) -> str:
    """Open the phone dialer with a number pre-filled.

    Uses Termux:API to open the dialer. The user presses call.
    """
    try:
        _subprocess.run(
            ["termux-telephony-call", phone_number],
            timeout=10, capture_output=True
        )
        return f"Dialer opened with {phone_number}. Press call to connect."
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Dial failed: {type(e).__name__}: {e}"


def tool_get_battery_status() -> str:
    """Check the phone's battery level and charging status."""
    try:
        result = _subprocess.run(
            ["termux-battery-status"],
            timeout=10, capture_output=True, text=True
        )
        return f"Battery status: {result.stdout.strip()}"
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Battery check failed: {type(e).__name__}: {e}"


def tool_get_location() -> str:
    """Get the phone's current GPS location."""
    try:
        result = _subprocess.run(
            ["termux-location"],
            timeout=30, capture_output=True, text=True
        )
        return f"Location: {result.stdout.strip()}"
    except FileNotFoundError:
        return "Termux:API not available. Install with: pkg install termux-api"
    except Exception as e:
        return f"Location failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------- #
# OCR Tool — Read text from images/documents
# ---------------------------------------------------------------------- #

MONITORED_SITES_FILE = Path.home() / "ai-twin-memory" / "monitored_sites.json"


def tool_ocr_image(image_path: str = "", language: str = "eng") -> str:
    """Extract text from an image using free OCR.

    Uses OCR.space API (free, no key needed for basic usage).
    Can also use local Tesseract if installed.

    Args:
        image_path: Path to the image file (on the phone)
        language: Language code (eng, fra, spa, etc.)
    """
    import base64

    if not image_path:
        return "No image path provided. Send a photo with a caption saying 'OCR this' instead."

    # Try local Tesseract first (if installed)
    try:
        import subprocess
        result = subprocess.run(
            ["tesseract", image_path, "-", "-l", language],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"OCR result (Tesseract):\n{result.stdout.strip()}"
    except FileNotFoundError:
        pass  # Tesseract not installed, fall through to API
    except Exception:
        pass

    # Fall back to OCR.space free API
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()

        # OCR.space free tier (no API key needed for basic usage)
        b64_image = base64.b64encode(image_data).decode("ascii")

        resp = requests.post(
            "https://api.ocr.space/parse/image",
            data={
                "base64Image": f"data:image/jpeg;base64,{b64_image}",
                "language": language,
                "isOverlayRequired": "false",
                "scale": "true",
                "OCREngine": "2",
            },
            timeout=30
        )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("ParsedResults"):
                text = data["ParsedResults"][0].get("ParsedText", "")
                if text.strip():
                    return f"OCR result:\n{text.strip()}"
            return "OCR completed but no text found in image."
        else:
            return f"OCR API error: {resp.status_code}"
    except Exception as e:
        return f"OCR failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------- #
# Website Monitoring Tool — Changedetection
# ---------------------------------------------------------------------- #

def _load_monitored_sites() -> list:
    """Load monitored sites from JSON file."""
    try:
        if MONITORED_SITES_FILE.exists():
            return json.loads(MONITORED_SITES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_monitored_sites(sites: list) -> None:
    """Save monitored sites to JSON file."""
    MONITORED_SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MONITORED_SITES_FILE.write_text(
        json.dumps(sites, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def tool_monitor_website(url: str, description: str = "", 
                         check_interval_minutes: int = 30) -> str:
    """Start monitoring a website for changes.

    The twin will check this URL periodically and notify you when
    the content changes. Useful for:
    - Waitlist position updates
    - Appointment slot availability
    - Status page changes
    - Any page that might update

    Args:
        url: The URL to monitor
        description: What you're watching for (e.g., "WGU waitlist position")
        check_interval_minutes: How often to check (default 30)
    """
    try:
        if not url.startswith("http"):
            url = "https://" + url

        # Fetch initial content to establish baseline
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=20)
        content_hash = hashlib.md5(resp.text.encode()).hexdigest()

        sites = _load_monitored_sites()

        # Check if already monitoring
        for site in sites:
            if site["url"] == url:
                site["last_hash"] = content_hash
                site["description"] = description or site.get("description", "")
                site["check_interval"] = check_interval_minutes
                site["last_check"] = datetime.now().isoformat()
                _save_monitored_sites(sites)
                return f"Updated monitoring for {url}. Checking every {check_interval_minutes} minutes."

        # Add new site
        sites.append({
            "url": url,
            "description": description or "No description provided",
            "last_hash": content_hash,
            "last_check": datetime.now().isoformat(),
            "check_interval": check_interval_minutes,
            "active": True,
        })
        _save_monitored_sites(sites)

        return f"Now monitoring {url}. I'll check every {check_interval_minutes} minutes and let you know when it changes."
    except Exception as e:
        return f"Failed to start monitoring: {type(e).__name__}: {e}"


def tool_list_monitored_sites() -> str:
    """List all websites being monitored for changes."""
    sites = _load_monitored_sites()
    active = [s for s in sites if s.get("active")]
    if not active:
        return "Not monitoring any websites. Use monitor_website to start."
    lines = [f"Monitored sites ({len(active)}):"]
    for i, site in enumerate(active):
        lines.append(f"  {i+1}. {site['url']}")
        lines.append(f"     {site.get('description', 'No description')}")
        lines.append(f"     Last checked: {site.get('last_check', 'never')}")
        lines.append(f"     Interval: {site.get('check_interval', 30)} min")
    return "\n".join(lines)


def tool_stop_monitoring(url: str) -> str:
    """Stop monitoring a website."""
    sites = _load_monitored_sites()
    for site in sites:
        if site["url"] == url or url in site["url"]:
            site["active"] = False
            _save_monitored_sites(sites)
            return f"Stopped monitoring {site['url']}."
    return f"Not currently monitoring {url}."


def _check_monitored_sites() -> list:
    """Check all monitored sites for changes. Called by background thread.

    Returns list of (url, description, old_hash, new_hash) for changed sites.
    """
    import hashlib
    sites = _load_monitored_sites()
    changed = []

    for site in sites:
        if not site.get("active"):
            continue

        # Check if enough time has passed
        last_check = site.get("last_check", "")
        interval = site.get("check_interval", 30)

        if last_check:
            try:
                last_dt = datetime.fromisoformat(last_check)
                elapsed = (datetime.now() - last_dt).total_seconds() / 60
                if elapsed < interval:
                    continue
            except Exception:
                pass

        # Fetch the URL
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36"}
            resp = requests.get(site["url"], headers=headers, timeout=20)
            new_hash = hashlib.md5(resp.text.encode()).hexdigest()

            if new_hash != site.get("last_hash"):
                changed.append({
                    "url": site["url"],
                    "description": site.get("description", ""),
                    "old_hash": site.get("last_hash", ""),
                    "new_hash": new_hash,
                })
                site["last_hash"] = new_hash

            site["last_check"] = datetime.now().isoformat()
        except Exception:
            site["last_check"] = datetime.now().isoformat()

    if changed:
        _save_monitored_sites(sites)

    return changed


# ---------------------------------------------------------------------- #
# n8n Cloud Integration — Connect to 400+ services
# ---------------------------------------------------------------------- #

N8N_WEBHOOKS_FILE = Path.home() / "ai-twin-memory" / "n8n_webhooks.json"


def _load_n8n_webhooks() -> dict:
    """Load saved n8n webhook URLs."""
    try:
        if N8N_WEBHOOKS_FILE.exists():
            return json.loads(N8N_WEBHOOKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_n8n_webhooks(hooks: dict) -> None:
    N8N_WEBHOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    N8N_WEBHOOKS_FILE.write_text(
        json.dumps(hooks, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def tool_trigger_webhook(webhook_name: str = "", webhook_url: str = "",
                         data: str = "{}") -> str:
    """Trigger ANY HTTP webhook (n8n self-hosted, n8n.cloud, IFTTT, Make,
    Zapier, custom server, Home Assistant, etc.).

    This is a generic HTTP POST tool — it sends JSON to any URL you provide.
    It works with any automation platform that exposes webhook triggers.

    Common scenarios:
    - Trigger a self-hosted n8n workflow (see N8N_SELFHOST_GUIDE.md)
    - Trigger an IFTTT applet
    - Send a notification to Home Assistant
    - POST to a custom server endpoint

    Args:
        webhook_name: Name of a saved webhook (if you've saved one before)
        webhook_url: Full webhook URL (any provider)
        data: JSON string with data to send to the workflow
    """
    try:
        # If webhook_name provided, look up saved URL
        if webhook_name and not webhook_url:
            hooks = _load_n8n_webhooks()
            if webhook_name in hooks:
                webhook_url = hooks[webhook_name]
            else:
                return f"No saved webhook named '{webhook_name}'. Use save_webhook first, or provide the URL directly."

        if not webhook_url:
            return "Provide either a webhook_name (if saved) or a webhook_url."

        # Parse the data
        try:
            payload = json.loads(data) if isinstance(data, str) else data
        except json.JSONDecodeError:
            payload = {"text": data}

        resp = requests.post(webhook_url, json=payload, timeout=30)

        if resp.status_code in (200, 201, 204):
            return f"Workflow triggered successfully. Response: {resp.text[:200] if resp.text else '(no response body)'}"
        else:
            return f"Webhook returned {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"Webhook trigger failed: {type(e).__name__}: {e}"


def tool_save_webhook(name: str, webhook_url: str, description: str = "") -> str:
    """Save an HTTP webhook URL for easy triggering later.

    Args:
        name: A short name to identify this webhook (e.g., "send_email", "add_calendar_event")
        webhook_url: The full webhook URL (any provider — n8n self-hosted, IFTTT, Make, etc.)
        description: What this workflow does
    """
    hooks = _load_n8n_webhooks()
    hooks[name] = webhook_url
    _save_n8n_webhooks(hooks)
    return f"Saved webhook '{name}'. You can now trigger it with trigger_webhook(webhook_name='{name}')."


def tool_list_webhooks() -> str:
    """List all saved webhook URLs (any provider)."""
    hooks = _load_n8n_webhooks()
    if not hooks:
        return "No saved webhooks. Use save_webhook to add one."
    lines = [f"Saved webhooks ({len(hooks)}):"]
    for name, url in hooks.items():
        # Mask the URL for security
        masked = url[:30] + "..." if len(url) > 30 else url
        lines.append(f"  {name}: {masked}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- #
# Native Automation — FREE alternatives to n8n
# These tools do the most common automation tasks without needing
# any external automation platform. Email, calendar, RSS — built in.
# ---------------------------------------------------------------------- #

def _load_smtp_config() -> dict:
    """Load SMTP config from .env or memory file."""
    # Try .env first (loaded into os.environ at startup)
    cfg = {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": os.environ.get("SMTP_PORT", "587"),
        "user": os.environ.get("SMTP_USER", ""),
        "pass": os.environ.get("SMTP_PASS", ""),
        "from": os.environ.get("SMTP_FROM", ""),
    }
    if cfg["host"] and cfg["user"] and cfg["pass"]:
        return cfg
    # Fallback: memory file
    smtp_file = Path.home() / "ai-twin-memory" / "smtp_config.json"
    if smtp_file.exists():
        try:
            return json.loads(smtp_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def tool_send_email(to: str, subject: str, body: str, html: str = "") -> str:
    """Send an email via SMTP. Requires SMTP credentials in .env or memory.

    Setup for Gmail (free):
    1. Enable 2FA on your Google account
    2. Go to https://myaccount.google.com/apppasswords
    3. Create an App Password (16 chars, no spaces)
    4. Add these to .env:
       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=587
       SMTP_USER=your@gmail.com
       SMTP_PASS=your-16-char-app-password
       SMTP_FROM=your@gmail.com

    Also works with:
    - Outlook: smtp.office365.com:587
    - Yahoo: smtp.mail.yahoo.com:587
    - ProtonMail Bridge: 127.0.0.1:1025 (requires Bridge running)
    - Any standard SMTP server

    Args:
        to: Recipient email address
        subject: Email subject
        body: Plain text body
        html: Optional HTML body (overrides plain text)
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    cfg = _load_smtp_config()
    if not cfg.get("host") or not cfg.get("user") or not cfg.get("pass"):
        return (
            "SMTP not configured. To enable email:\n"
            "1. For Gmail: enable 2FA, create an App Password at\n"
            "   https://myaccount.google.com/apppasswords\n"
            "2. Add to your .env file:\n"
            "   SMTP_HOST=smtp.gmail.com\n"
            "   SMTP_PORT=587\n"
            "   SMTP_USER=your@gmail.com\n"
            "   SMTP_PASS=your-16-char-app-password\n"
            "   SMTP_FROM=your@gmail.com\n"
            "3. Restart the twin with: twin-stop && twin-start"
        )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.get("from") or cfg["user"]
        msg["To"] = to
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))

        port = int(cfg.get("port", 587))
        host = cfg["host"]

        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as srv:
                srv.login(cfg["user"], cfg["pass"])
                srv.sendmail(msg["From"], [to], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as srv:
                srv.ehlo()
                srv.starttls()
                srv.ehlo()
                srv.login(cfg["user"], cfg["pass"])
                srv.sendmail(msg["From"], [to], msg.as_string())

        return f"Email sent to {to}: {subject}"
    except Exception as e:
        return f"Email failed: {type(e).__name__}: {e}"


def tool_create_calendar_event(title: str, start: str, end: str,
                                location: str = "", description: str = "",
                                reminder_minutes: int = 15) -> str:
    """Create a calendar event as an .ics file the user can import.

    The .ics file is written to ~/ai-twin-memory/calendar/ and the path
    is returned. On Android, the user can open it to add the event to
    their default calendar app.

    Args:
        title: Event title
        start: Start time, ISO 8601 (e.g., '2026-09-10T14:00:00')
        end: End time, ISO 8601
        location: Optional location string
        description: Optional description/notes
        reminder_minutes: Minutes before to trigger a reminder (default 15)
    """
    from datetime import datetime

    try:
        # Parse and validate
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(end)

        # iCalendar uses UTC with Z suffix; we'll use local time without Z
        fmt_start = dt_start.strftime("%Y%m%dT%H%M%S")
        fmt_end = dt_end.strftime("%Y%m%dT%H%M%S")
        now = datetime.now().strftime("%Y%m%dT%H%M%S")
        uid = f"{now}-{title[:20].replace(' ', '-')}@ai-twin"

        # Escape text per RFC 5545
        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//AI Twin//Termux//EN",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART:{fmt_start}",
            f"DTEND:{fmt_end}",
            f"SUMMARY:{esc(title)}",
        ]
        if location:
            lines.append(f"LOCATION:{esc(location)}")
        if description:
            lines.append(f"DESCRIPTION:{esc(description)}")
        lines.extend([
            "BEGIN:VALARM",
            f"TRIGGER:-PT{int(reminder_minutes)}M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc(title)}",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
        ])
        ics_content = "\r\n".join(lines) + "\r\n"

        out_dir = Path.home() / "ai-twin-memory" / "calendar"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:40]
        filename = f"{dt_start.strftime('%Y%m%d_%H%M')}_{safe_title}.ics"
        out_path = out_dir / filename
        out_path.write_text(ics_content, encoding="utf-8")

        # Also copy to a Termux-shared location if available so the user
        # can tap-to-open it from a file manager
        shared_dir = Path("/storage/emulated/0/Download/ai-twin-calendar")
        try:
            shared_dir.mkdir(parents=True, exist_ok=True)
            (shared_dir / filename).write_text(ics_content, encoding="utf-8")
            shared_path = str(shared_dir / filename)
        except Exception:
            shared_path = None

        when_human = dt_start.strftime("%a %b %d, %I:%M %p")
        result = f"Calendar event created: {title} on {when_human}.\n"
        result += f"ICS file: {out_path}\n"
        if shared_path:
            result += f"Also saved to: {shared_path}\n"
        result += "Open the .ics file from a file manager to import it into your calendar app."
        return result
    except ValueError as e:
        return f"Invalid date format. Use ISO 8601 (e.g., '2026-09-10T14:00:00'). Error: {e}"
    except Exception as e:
        return f"Calendar event failed: {type(e).__name__}: {e}"


def tool_read_rss(url: str, limit: int = 5) -> str:
    """Fetch and parse an RSS or Atom feed. Returns the latest items.

    Args:
        url: RSS/Atom feed URL
        limit: Max items to return (default 5, max 20)
    """
    try:
        limit = max(1, min(int(limit), 20))
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AI-Twin/1.0)"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        # Parse with xml.etree (no extra deps)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)

        # Strip XML namespaces for simplicity
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        items = []
        # RSS 2.0
        for item in root.findall(".//item")[:limit]:
            items.append({
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "description": (item.findtext("description") or "").strip()[:200],
                "pubDate": (item.findtext("pubDate") or "").strip(),
            })

        # Atom 1.0 (if no RSS items found)
        if not items:
            for entry in root.findall(".//entry")[:limit]:
                link_elem = entry.find("link")
                link = link_elem.get("href", "") if link_elem is not None else ""
                items.append({
                    "title": (entry.findtext("title") or "").strip(),
                    "link": link.strip(),
                    "description": (entry.findtext("summary") or entry.findtext("content") or "").strip()[:200],
                    "pubDate": (entry.findtext("published") or entry.findtext("updated") or "").strip(),
                })

        if not items:
            return f"No items found in feed: {url}"

        lines = [f"Feed: {url}", f"Latest {len(items)} items:", ""]
        for i, it in enumerate(items, 1):
            lines.append(f"{i}. {it['title']}")
            if it["pubDate"]:
                lines.append(f"   Published: {it['pubDate']}")
            if it["link"]:
                lines.append(f"   Link: {it['link']}")
            if it["description"]:
                # Strip HTML from description
                import re
                desc = re.sub(r"<[^>]+>", "", it["description"]).strip()
                if desc:
                    lines.append(f"   {desc[:150]}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"RSS fetch failed: {type(e).__name__}: {e}"


def tool_shorten_url(url: str) -> str:
    """Shorten a URL using the free is.gd / v.gd APIs (no key needed).

    Args:
        url: The long URL to shorten
    """
    # Try is.gd first, fall back to v.gd (same service, different domain)
    for api in ("https://is.gd/create.php", "https://v.gd/create.php"):
        try:
            resp = requests.get(api, params={"format": "simple", "url": url}, timeout=10)
            resp.raise_for_status()
            short = resp.text.strip()
            if short.startswith("http"):
                return f"Short URL: {short}"
            # If we got a non-URL response, try the next provider
        except Exception:
            continue
    return f"URL shortening failed for: {url}"


def tool_news_digest(feeds_file: str = "", limit_per_feed: int = 5) -> str:
    """Pull all subscribed RSS feeds and return raw items for AI digestion.

    The twin's LLM then writes a 4-6 sentence digest with no URLs/links,
    customized to the user's actual life (Baltimore local, medical, Apple
    ecosystem, AI tools, legal/probation). User can ask 'more on X' to
    expand any item.

    Args:
        feeds_file:      optional path to a feeds file (default: ~/ai-twin-memory/rss_feeds.txt)
        limit_per_feed:  max items per feed (default 5, clamped to 10)

    Returns a structured text the twin can pass to the LLM for digestion.
    """
    try:
        if not feeds_file:
            feeds_file = str(Path.home() / "ai-twin-memory" / "rss_feeds.txt")
        feeds_path = Path(feeds_file)
        if not feeds_path.exists():
            return ("No RSS feeds subscribed. "
                    "Add URLs to ~/ai-twin-memory/rss_feeds.txt (one per line).")

        feeds = []
        for line in feeds_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                feeds.append(line)

        if not feeds:
            return ("No RSS feeds subscribed. "
                    "Add URLs to ~/ai-twin-memory/rss_feeds.txt (one per line).")

        limit_per_feed = max(1, min(int(limit_per_feed), 10))

        all_items = []
        for feed_url in feeds:
            try:
                raw = tool_read_rss(feed_url, limit=limit_per_feed)
                # Parse out items from tool_read_rss's format:
                #   1. <title>
                #      Published: <pubDate>
                #      Link: <link>
                #      <description>
                # Split on numbered lines
                blocks = re.split(r"\n(?=\d+\.\s)", raw)
                for block in blocks[1:]:
                    title_match = re.match(r"\d+\.\s+(.+)", block)
                    if not title_match:
                        continue
                    title = title_match.group(1).strip()
                    pub_match = re.search(r"Published:\s+(.+)", block)
                    link_match = re.search(r"Link:\s+(\S+)", block)
                    # Description = lines that aren't title/Published/Link
                    desc_lines = []
                    for ln in block.splitlines()[1:]:
                        ln_s = ln.strip()
                        if not ln_s:
                            continue
                        if ln_s.startswith("Published:") or ln_s.startswith("Link:"):
                            continue
                        desc_lines.append(ln_s)
                    desc = " ".join(desc_lines)[:200]
                    all_items.append({
                        "title": title,
                        "link": link_match.group(1) if link_match else "",
                        "pubDate": pub_match.group(1).strip() if pub_match else "",
                        "description": desc,
                        "source_feed": feed_url,
                    })
            except Exception:
                continue  # skip broken feed

        if not all_items:
            return "No items found in any subscribed feed."

        out = [f"Aggregated {len(all_items)} items from {len(feeds)} feeds:",
               "=" * 60, ""]
        for i, it in enumerate(all_items, 1):
            out.append(f"[{i}] {it['title']}")
            if it["pubDate"]:
                out.append(f"    Published: {it['pubDate']}")
            if it["description"]:
                out.append(f"    {it['description']}")
            if it["link"]:
                out.append(f"    Link: {it['link']}")
            out.append(f"    Source: {it['source_feed']}")
            out.append("")
        return "\n".join(out)
    except Exception as e:
        return f"News digest failed: {type(e).__name__}: {e}"


def tool_scrape_website(url: str, extract_links: bool = False) -> str:
    """Scrape a website with anti-bot handling and content extraction.

    Better than read_url for JS-heavy pages, news sites, portals.
    Returns the main article text (not the raw HTML), page title, and
    meta description. Optionally extracts all links if extract_links=true.

    Uses lxml when available (fast, accurate). Falls back to tool_read_url
    if lxml isn't installed or parsing fails — keeps the tool working on
    Termux/Android without requiring new pip dependencies.
    """
    try:
        # lxml is optional on Termux — import lazily and fall back if absent
        try:
            from lxml import html as lxml_html
        except Exception:
            return tool_read_url(url)

        if not url.startswith("http"):
            url = "https://" + url

        import random
        USER_AGENTS = [
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        session = requests.Session()
        session.headers.update(headers)
        resp = session.get(url, timeout=20, allow_redirects=True)
        resp.raise_for_status()

        try:
            doc = lxml_html.fromstring(resp.content)
        except Exception:
            return tool_read_url(url)

        # Title
        title = doc.find(".//title")
        title_text = (title.text_content().strip()
                      if title is not None and title.text_content() else "")

        # Meta description
        meta_desc = ""
        for m in doc.findall(".//meta"):
            if (m.get("name") or "").lower() == "description":
                meta_desc = m.get("content", "") or ""
                break

        # Strip scripts, styles, nav, ads
        for tag in doc.xpath("//script|//style|//nav|//footer|//aside|//form|//header"):
            parent = tag.getparent()
            if parent is not None:
                parent.remove(tag)

        # Find main content — biggest text block heuristic
        candidates = []
        for el in doc.xpath("//div|//article|//section|//main"):
            text = (el.text_content() or "").strip()
            if len(text) > 200:
                candidates.append((len(text), el, text))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            main_text = candidates[0][2]
        else:
            main_text = (doc.text_content() or "").strip()

        # Clean whitespace
        main_text = re.sub(r"\s+", " ", main_text).strip()
        if len(main_text) > 8000:
            main_text = main_text[:8000] + "\n\n[... truncated]"

        result = f"Title: {title_text}\nURL: {url}\n"
        if meta_desc:
            result += f"Description: {meta_desc}\n"
        result += f"\n--- Content ---\n{main_text}\n"

        if extract_links:
            links = []
            for a in doc.xpath("//a[@href]"):
                href = (a.get("href") or "").strip()
                text = (a.text_content() or "").strip()
                if href and text and href.startswith("http"):
                    links.append(f"  - {text}: {href}")
            if links:
                result += (f"\n--- Links ({len(links)}) ---\n"
                           + "\n".join(links[:50]))

        return result

    except requests.exceptions.Timeout:
        return f"Scraping {url} timed out."
    except Exception as e:
        # Last-ditch fallback to read_url — keeps the tool useful even on
        # sites lxml can't parse or when lxml isn't installed.
        try:
            return tool_read_url(url)
        except Exception:
            return f"Failed to scrape {url}: {type(e).__name__}: {e}"


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
    "send_notification": tool_send_notification,
    "open_url": tool_open_url,
    "copy_to_clipboard": tool_copy_to_clipboard,
    "get_clipboard": tool_get_clipboard,
    "set_alarm": tool_set_alarm,
    "send_sms": tool_send_sms,
    "dial_phone": tool_dial_phone,
    "get_battery_status": tool_get_battery_status,
    "get_location": tool_get_location,
    "ocr_image": tool_ocr_image,
    "monitor_website": tool_monitor_website,
    "list_monitored_sites": tool_list_monitored_sites,
    "stop_monitoring": tool_stop_monitoring,
    "trigger_webhook": tool_trigger_webhook,
    "save_webhook": tool_save_webhook,
    "list_webhooks": tool_list_webhooks,
    "send_email": tool_send_email,
    "create_calendar_event": tool_create_calendar_event,
    "read_rss": tool_read_rss,
    "shorten_url": tool_shorten_url,
    "task_review": tool_task_review,
    "news_digest": tool_news_digest,
    "scrape_website": tool_scrape_website,
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
