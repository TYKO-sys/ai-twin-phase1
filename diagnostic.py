#!/usr/bin/env python3
"""
AI Twin — comprehensive diagnostic.

Tests every tool and every API key in .env, prints a status report,
and writes a structured summary to ~/ai-twin-memory/diagnostic.json.

Usage:
    python diagnostic.py
"""

import json
import os
import sys
import time
from pathlib import Path

# Ensure we can import the local tools module
sys.path.insert(0, str(Path(__file__).parent))

import tools


GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

MEM_DIR = Path.home() / "ai-twin-memory"
MEM_DIR.mkdir(parents=True, exist_ok=True)


def ok(msg: str) -> str:
    return f"{GREEN}[OK]{NC} {msg}"

def warn(msg: str) -> str:
    return f"{YELLOW}[!]{NC} {msg}"

def fail(msg: str) -> str:
    return f"{RED}[X]{NC} {msg}"

def header(msg: str) -> str:
    return f"\n{CYAN}{BOLD}--- {msg} ---{NC}"


# ---------------------------------------------------------------------- #
# Tool tests — each returns (status, message)
# status: "ok" | "warn" | "fail" | "skip"
# ---------------------------------------------------------------------- #

TOOL_TESTS = [
    ("get_current_time", lambda: tools.tool_get_current_time()),
    ("calculator", lambda: tools.tool_calculator("2 + 2")),
    ("save_note", lambda: tools.tool_save_note("Diagnostic test note", category="diagnostic")),
    ("get_notes", lambda: tools.tool_get_notes(limit=3)),
    ("create_task", lambda: tools.tool_create_task("Diagnostic test task", priority="low")),
    ("list_tasks", lambda: tools.tool_list_tasks()),
    ("complete_task", lambda: tools.tool_complete_task("1")),  # may fail if no task #1
    ("append_to_journal", lambda: tools.tool_append_to_journal("Diagnostic test entry")),
    ("read_journal", lambda: tools.tool_read_journal()),
    ("list_files", lambda: tools.tool_list_files()),
    ("write_file", lambda: tools.tool_write_file("diagnostic_test.txt", "test")),
    ("read_file", lambda: tools.tool_read_file("diagnostic_test.txt")),
    ("list_webhooks", lambda: tools.tool_list_webhooks()),
    ("list_monitored_sites", lambda: tools.tool_list_monitored_sites()),
    ("list_contacts", lambda: tools.tool_list_contacts()),
    ("list_drafts", lambda: tools.tool_list_drafts()),
    ("list_goals", lambda: tools.tool_list_goals()),
    ("list_routines", lambda: tools.tool_list_routines()),
    ("shorten_url", lambda: tools.tool_shorten_url("https://github.com")),
    ("read_rss", lambda: tools.tool_read_rss("https://hnrss.org/frontpage", limit=2)),
    ("get_battery_status", lambda: tools.tool_get_battery_status()),
    ("get_clipboard", lambda: tools.tool_get_clipboard()),
    ("create_calendar_event",
     lambda: tools.tool_create_calendar_event(
         title="Diag Test",
         start="2026-12-31T23:59:00",
         end="2026-12-31T23:59:30",
     )),
]

# Tools that NEED external resources and may legitimately fail offline
NETWORK_TOOLS = [
    ("web_search", lambda: tools.tool_web_search("current time")),
    ("read_url", lambda: tools.tool_read_url("https://example.com")),
]

# Tools that NEED termux-api (only work on Android)
TERMUX_TOOLS = [
    ("send_sms", "needs phone permission"),
    ("dial_phone", "needs phone permission"),
    ("get_location", "needs location permission"),
    ("set_alarm", "needs alarm permission"),
    ("send_notification", "needs notification permission"),
    ("open_url", "needs browser"),
    ("copy_to_clipboard", "needs clipboard"),
    ("ocr_image", "needs image input"),
]


def run_tool_tests() -> list:
    """Returns list of dicts: [{name, status, message}]."""
    results = []

    # Always-run tool tests
    for name, fn in TOOL_TESTS:
        try:
            result = fn()
            if isinstance(result, str) and ("fail" in result.lower() or "error" in result.lower()):
                status = "warn"
            else:
                status = "ok"
            msg = result[:120].replace("\n", " ")
            results.append({"name": name, "status": status, "message": msg})
        except Exception as e:
            results.append({"name": name, "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})

    # Network-dependent tool tests
    for name, fn in NETWORK_TOOLS:
        try:
            result = fn()
            if isinstance(result, str) and ("fail" in result.lower() or "error" in result.lower()):
                status = "warn"
            else:
                status = "ok"
            msg = result[:120].replace("\n", " ")
            results.append({"name": name, "status": status, "message": msg})
        except Exception as e:
            results.append({"name": name, "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})

    # Termux-only tools (just check they exist in registry; running them needs Android)
    for name, reason in TERMUX_TOOLS:
        if name in tools._TOOL_FUNCTIONS:
            results.append({"name": name, "status": "ok",
                            "message": f"available ({reason})"})
        else:
            results.append({"name": name, "status": "fail",
                            "message": "not in registry"})

    # Webhook tools (just check they exist)
    for name in ("trigger_webhook", "save_webhook"):
        if name in tools._TOOL_FUNCTIONS:
            results.append({"name": name, "status": "ok",
                            "message": "available (needs URL)"})

    # Email tool
    if "send_email" in tools._TOOL_FUNCTIONS:
        smtp = tools._load_smtp_config()
        if smtp.get("host"):
            results.append({"name": "send_email", "status": "ok",
                            "message": f"SMTP configured: {smtp['host']}"})
        else:
            results.append({"name": "send_email", "status": "warn",
                            "message": "SMTP not configured (run hook_up.sh to enable)"})

    # Website monitoring
    if "monitor_website" in tools._TOOL_FUNCTIONS:
        sites = tools._load_monitored_sites()
        if isinstance(sites, list):
            count = len(sites)
        elif isinstance(sites, dict):
            count = len(sites.get("sites", []))
        else:
            count = 0
        results.append({"name": "monitor_website", "status": "ok",
                        "message": f"monitoring {count} site(s)"})

    return results


# ---------------------------------------------------------------------- #
# API key checks
# ---------------------------------------------------------------------- #

def check_api_keys() -> list:
    """Check each provider's API key validity by making a tiny test call."""
    results = []

    # FreeLLMAPI — always available (no key needed)
    results.append({"name": "FreeLLMAPI", "status": "ok",
                    "message": "always available (no key needed)"})

    # Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            from gemini_client import GeminiClient
            client = GeminiClient(api_key=gemini_key)
            resp = client.generate_text(prompt="Reply with exactly: ok",
                                         max_tokens=10)
            if "ok" in resp.lower():
                results.append({"name": "Gemini", "status": "ok",
                                "message": "live (test succeeded)"})
            else:
                results.append({"name": "Gemini", "status": "warn",
                                "message": f"got response but unexpected: {resp[:60]}"})
        except Exception as e:
            results.append({"name": "Gemini", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "Gemini", "status": "skip",
                        "message": "no key in .env"})

    # OpenRouter
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        try:
            from openrouter_client import OpenRouterClient
            client = OpenRouterClient(api_key=or_key)
            resp = client.generate_text(prompt="Reply with exactly: ok",
                                          max_tokens=10)
            if "ok" in resp.lower():
                results.append({"name": "OpenRouter", "status": "ok",
                                "message": "live"})
            else:
                results.append({"name": "OpenRouter", "status": "warn",
                                "message": f"unexpected: {resp[:60]}"})
        except Exception as e:
            results.append({"name": "OpenRouter", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "OpenRouter", "status": "skip",
                        "message": "no key in .env"})

    # Z.ai
    zai_key = os.environ.get("ZAI_API_KEY", "")
    if zai_key:
        try:
            import requests
            resp = requests.post(
                "https://api.z.ai/api/paas/v4/chat/completions",
                headers={
                    "Authorization": f"Bearer {zai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "glm-4-flash",
                    "messages": [{"role": "user", "content": "Reply with: ok"}],
                    "max_tokens": 10,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                results.append({"name": "Z.ai", "status": "ok",
                                "message": "live"})
            else:
                results.append({"name": "Z.ai", "status": "fail",
                                "message": f"HTTP {resp.status_code}: {resp.text[:80]}"})
        except Exception as e:
            results.append({"name": "Z.ai", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "Z.ai", "status": "skip",
                        "message": "no key in .env"})

    # Groq
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        try:
            import requests
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": "Reply with: ok"}],
                    "max_tokens": 10,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                results.append({"name": "Groq", "status": "ok",
                                "message": "live"})
            else:
                results.append({"name": "Groq", "status": "fail",
                                "message": f"HTTP {resp.status_code}: {resp.text[:80]}"})
        except Exception as e:
            results.append({"name": "Groq", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "Groq", "status": "skip",
                        "message": "no key in .env"})

    # Mistral
    mistral_key = os.environ.get("MISTRAL_API_KEY", "")
    if mistral_key:
        try:
            import requests
            resp = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {mistral_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-small-latest",
                    "messages": [{"role": "user", "content": "Reply with: ok"}],
                    "max_tokens": 10,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                results.append({"name": "Mistral", "status": "ok",
                                "message": "live"})
            else:
                results.append({"name": "Mistral", "status": "fail",
                                "message": f"HTTP {resp.status_code}: {resp.text[:80]}"})
        except Exception as e:
            results.append({"name": "Mistral", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "Mistral", "status": "skip",
                        "message": "no key in .env"})

    # Cerebras
    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
    if cerebras_key:
        try:
            import requests
            resp = requests.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {cerebras_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama3.1-8b",
                    "messages": [{"role": "user", "content": "Reply with: ok"}],
                    "max_tokens": 10,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                results.append({"name": "Cerebras", "status": "ok",
                                "message": "live"})
            else:
                results.append({"name": "Cerebras", "status": "fail",
                                "message": f"HTTP {resp.status_code}: {resp.text[:80]}"})
        except Exception as e:
            results.append({"name": "Cerebras", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "Cerebras", "status": "skip",
                        "message": "no key in .env"})

    # Telegram bot token
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        try:
            import requests
            resp = requests.get(
                f"https://api.telegram.org/bot{tg_token}/getMe",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot_username = data["result"]["username"]
                    results.append({"name": "Telegram bot", "status": "ok",
                                    "message": f"@{bot_username}"})
                else:
                    results.append({"name": "Telegram bot", "status": "fail",
                                    "message": f"API said not ok: {data}"})
            else:
                results.append({"name": "Telegram bot", "status": "fail",
                                "message": f"HTTP {resp.status_code}"})
        except Exception as e:
            results.append({"name": "Telegram bot", "status": "fail",
                            "message": f"{type(e).__name__}: {e}"})
    else:
        results.append({"name": "Telegram bot", "status": "fail",
                        "message": "no token in .env"})

    # SMTP
    smtp_host = os.environ.get("SMTP_HOST", "")
    if smtp_host:
        results.append({"name": "SMTP/email", "status": "ok",
                        "message": f"configured: {smtp_host}"})
    else:
        results.append({"name": "SMTP/email", "status": "skip",
                        "message": "not configured (optional)"})

    return results


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #

def main():
    print(header("AI Twin Diagnostic"))
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Memory dir: {MEM_DIR}")
    print(f"Tools registered: {len(tools._TOOL_FUNCTIONS)}")

    # Run tool tests
    print(header("Tool tests"))
    tool_results = run_tool_tests()
    ok_count = sum(1 for r in tool_results if r["status"] == "ok")
    warn_count = sum(1 for r in tool_results if r["status"] == "warn")
    fail_count = sum(1 for r in tool_results if r["status"] == "fail")
    for r in tool_results:
        if r["status"] == "ok":
            print(ok(f"{r['name']}: {r['message']}"))
        elif r["status"] == "warn":
            print(warn(f"{r['name']}: {r['message']}"))
        elif r["status"] == "fail":
            print(fail(f"{r['name']}: {r['message']}"))
    print(f"\nTools: {ok_count} OK, {warn_count} warnings, {fail_count} failures")

    # API key checks
    print(header("API key checks"))
    api_results = check_api_keys()
    for r in api_results:
        if r["status"] == "ok":
            print(ok(f"{r['name']}: {r['message']}"))
        elif r["status"] == "warn":
            print(warn(f"{r['name']}: {r['message']}"))
        elif r["status"] == "fail":
            print(fail(f"{r['name']}: {r['message']}"))
        else:
            print(f"    {r['name']}: {r['message']}")

    # Save JSON report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tools": tool_results,
        "api_keys": api_results,
        "summary": {
            "tools_ok": ok_count,
            "tools_warn": warn_count,
            "tools_fail": fail_count,
            "api_ok": sum(1 for r in api_results if r["status"] == "ok"),
            "api_warn": sum(1 for r in api_results if r["status"] == "warn"),
            "api_fail": sum(1 for r in api_results if r["status"] == "fail"),
            "api_skip": sum(1 for r in api_results if r["status"] == "skip"),
        }
    }
    json_path = MEM_DIR / "diagnostic.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{ok('JSON report:')} {json_path}")

    # Print summary verdict
    print(header("Verdict"))
    total_fail = fail_count + sum(1 for r in api_results if r["status"] == "fail")
    if total_fail == 0:
        print(ok("All systems green. The twin is fully operational."))
    elif total_fail <= 2:
        print(warn(f"{total_fail} issue(s) found — twin will work but with reduced capacity."))
    else:
        print(fail(f"{total_fail} issue(s) found — twin may not work reliably."))
        print(fail("Run hook_up.sh again, or check the .env file."))

    # Exit code reflects total failures
    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
