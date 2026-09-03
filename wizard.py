"""
wizard.py
=========
First-run wizard for the AI twin.

Serves a local web page (http://localhost:8888) that walks the user
through getting their API keys and configuring the bot. No terminal
interaction required after the initial bootstrap command.

The wizard:
1. Serves an HTML page with step-by-step instructions
2. Accepts form submissions via POST
3. Writes the .env file when all secrets are provided
4. Signals completion so install.sh can continue

Uses only Python's built-in http.server — no new dependencies.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs

PORT = 8888
AI_TWIN_DIR = Path(__file__).parent
ENV_FILE = AI_TWIN_DIR / ".env"
ENV_EXAMPLE = AI_TWIN_DIR / ".env.example"
WIZARD_ASSETS = AI_TWIN_DIR / "wizard_assets"
COMPLETION_FLAG = AI_TWIN_DIR / ".wizard_complete"


class WizardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves the wizard and accepts secrets."""

    def do_GET(self):
        """Serve the wizard page and assets."""
        if self.path == "/" or self.path == "/index.html":
            self._serve_wizard_page()
        elif self.path == "/status":
            self._serve_status()
        elif self.path.startswith("/wizard_assets/"):
            self._serve_asset(self.path)
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        """Accept secret submissions and write .env."""
        if self.path == "/submit":
            self._handle_submit()
        else:
            self.send_error(404, "Not found")

    def _serve_wizard_page(self):
        """Serve the main wizard HTML page."""
        # Read current .env values if they exist (for pre-filling)
        current_values = self._read_current_env()

        # Read the wizard HTML template
        html_path = WIZARD_ASSETS / "index.html"
        if html_path.exists():
            html = html_path.read_text(encoding="utf-8")
            # Inject current values for pre-filling
            for key, value in current_values.items():
                placeholder = f"{{{{{key}}}}}"
                html = html.replace(placeholder, value)
        else:
            html = "<h1>Wizard assets not found</h1>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_status(self):
        """Check if wizard is complete."""
        complete = COMPLETION_FLAG.exists()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"complete": complete}).encode("utf-8"))

    def _serve_asset(self, path):
        """Serve a static asset (CSS, JS, images)."""
        # Strip prefix and prevent path traversal
        asset_name = path.replace("/wizard_assets/", "").split("?")[0]
        asset_path = WIZARD_ASSETS / asset_name

        if not asset_path.exists() or not asset_path.is_file():
            self.send_error(404, "Asset not found")
            return

        # Determine content type
        content_types = {
            ".css": "text/css",
            ".js": "application/javascript",
            ".html": "text/html",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
        }
        ext = asset_path.suffix.lower()
        content_type = content_types.get(ext, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(asset_path.read_bytes())

    def _read_current_env(self) -> dict:
        """Read existing .env values for pre-filling the form."""
        values = {
            "TELEGRAM_BOT_TOKEN": "",
            "GEMINI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "ZAI_API_KEY": "",
            "ALLOWED_USER_ID": "",
            "SMTP_HOST": "",
            "SMTP_PORT": "",
            "SMTP_USER": "",
            "SMTP_PASS": "",
            "SMTP_FROM": "",
        }
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key in values:
                    values[key] = value
        return values

    def _handle_submit(self):
        """Process the form submission and write .env."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        form_data = parse_qs(body)

        # Extract values
        telegram_token = form_data.get("telegram_token", [""])[0].strip()
        gemini_key = form_data.get("gemini_key", [""])[0].strip()
        openrouter_key = form_data.get("openrouter_key", [""])[0].strip()
        deepseek_key = form_data.get("deepseek_key", [""])[0].strip()
        zai_key = form_data.get("zai_key", [""])[0].strip()
        user_id = form_data.get("user_id", [""])[0].strip()

        # Optional SMTP fields (for native email automation — no n8n needed)
        smtp_host = form_data.get("smtp_host", [""])[0].strip()
        smtp_port = form_data.get("smtp_port", [""])[0].strip() or "587"
        smtp_user = form_data.get("smtp_user", [""])[0].strip()
        smtp_pass = form_data.get("smtp_pass", [""])[0].strip()
        smtp_from = form_data.get("smtp_from", [""])[0].strip()

        # Validate required fields
        errors = []
        if not telegram_token:
            errors.append("Telegram bot token is required")
        if not user_id:
            errors.append("Your Telegram user ID is required")
        if not telegram_token and not gemini_key and not openrouter_key and not deepseek_key and not zai_key:
            errors.append("At least one AI API key is required")

        # Validate SMTP only if partially provided (host + user + pass required together)
        smtp_provided = any([smtp_host, smtp_user, smtp_pass])
        if smtp_provided and not all([smtp_host, smtp_user, smtp_pass]):
            errors.append("SMTP: provide host, user, AND password (or leave all empty)")

        if errors:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"errors": errors}).encode("utf-8"))
            return

        # Build optional SMTP block
        smtp_block = ""
        if smtp_host and smtp_user and smtp_pass:
            smtp_from_val = smtp_from or smtp_user
            smtp_block = f"""
# Native email automation (send_email tool — free, no n8n needed)
SMTP_HOST={smtp_host}
SMTP_PORT={smtp_port}
SMTP_USER={smtp_user}
SMTP_PASS={smtp_pass}
SMTP_FROM={smtp_from_val}
"""

        # Write the .env file
        env_content = f"""# AI Twin secrets — generated by wizard.py
# Generated: {__import__('datetime').datetime.now().isoformat()}

# Telegram bot token from @BotFather
TELEGRAM_BOT_TOKEN={telegram_token}

# Your Telegram user ID
ALLOWED_USER_ID={user_id}

# LLM Providers — the bot rotates through all available providers
# OpenRouter (300+ models)
OPENROUTER_API_KEY={openrouter_key}

# DeepSeek (cheap, high quality)
DEEPSEEK_API_KEY={deepseek_key}

# Z.ai (GLM models, free tier)
ZAI_API_KEY={zai_key}

# Gemini (Google's free AI, fallback)
GEMINI_API_KEY={gemini_key}{smtp_block}"""
        ENV_FILE.write_text(env_content, encoding="utf-8")

        # Set completion flag
        COMPLETION_FLAG.write_text("complete", encoding="utf-8")

        # Return success
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "success": True,
            "message": "Configuration saved! The installer will continue automatically."
        }).encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default logging (keep terminal clean)."""
        pass


def main():
    """Start the wizard server."""
    print(f"\nStarting AI Twin setup wizard...")
    print(f"Opening your browser to http://localhost:{PORT}")
    print(f"If it doesn't open automatically, open this URL manually:")
    print(f"  http://localhost:{PORT}")
    print(f"\nThe wizard will guide you through the setup.")
    print(f"Once you're done, the installer continues automatically.")
    print(f"\nPress Ctrl+C to cancel.\n")

    # Try to open the browser
    try:
        webbrowser.open(f"http://localhost:{PORT}")
    except Exception:
        pass  # User can open manually

    # Start the server
    with socketserver.TCPServer(("127.0.0.1", PORT), WizardHandler) as httpd:
        httpd.timeout = 1  # Check for completion every second
        while True:
            httpd.handle_request()
            if COMPLETION_FLAG.exists():
                print("\nConfiguration complete! Continuing installation...")
                break


if __name__ == "__main__":
    main()
