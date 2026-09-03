# Self-Hosting n8n on Android — FREE Alternative to n8n.cloud

**The problem:** n8n.cloud's free tier was removed. The cloud version now requires payment.
**The solution:** Self-host n8n on the same phone running your AI twin. It's 100% free, runs entirely on your device, and gives you the same 400+ integrations.

This guide walks you through installing n8n locally on Termux, exposing it to the internet via ngrok (so external services like Gmail/Slack can reach your workflows), and connecting it to your AI twin.

---

## What You'll Need

- A phone already running your AI twin (Termux + Python)
- ~400 MB free storage (n8n + Node.js)
- A free ngrok account (https://dashboard.ngrok.com/signup)
- 15 minutes

---

## Architecture

```
[ External service ]  ←→  [ ngrok tunnel ]  ←→  [ n8n on Termux ]  ←→  [ your AI twin ]
   (Gmail, Slack,                       https://your-tunnel.ngrok-free.app    localhost:5678
    Sheets, etc.)
```

- **n8n** runs on your phone at `http://localhost:5678`
- **ngrok** creates a public HTTPS URL that forwards to localhost:5678
- **Your AI twin** triggers workflows by POSTing to that URL (or to `localhost:5678` directly when on the same device)
- External services (Gmail webhooks, Slack, etc.) reach your workflows via the ngrok URL

---

## Step 1: Install Node.js in Termux

n8n is a Node.js app. Install Node.js in the same Termux environment as your twin:

```bash
pkg install nodejs -y
node --version   # should print v20+ (LTS)
npm --version
```

If `pkg install nodejs` fails or gives an old version, use the Termux community repo:

```bash
pkg install nodejs-lts -y
```

---

## Step 2: Install n8n globally

```bash
npm install -g n8n
```

This takes 3–5 minutes on a phone. When it finishes, verify:

```bash
n8n --version
```

---

## Step 3: Configure n8n for headless operation

n8n normally wants a browser, but you'll run it headless and access it through ngrok.

Create a config file at `~/.n8n/.env` (Termux auto-loads this):

```bash
mkdir -p ~/.n8n
cat > ~/.n8n/.env <<'EOF'
# Run n8n on localhost only — ngrok exposes it publicly
N8N_HOST=localhost
N8N_PORT=5678
N8N_PROTOCOL=http
WEBHOOK_URL=http://localhost:5678
# Disable the browser auto-open
N8N_DIAGNOSTICS_ENABLED=false
N8N_PERSONALIZATION_ENABLED=false
# Use a secure editor password (set your own)
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=change-this-password
EOF
```

**Important:** change `change-this-password` to something only you know.

---

## Step 4: Start n8n in the background

Use tmux so n8n keeps running even if you close Termux:

```bash
# Start a tmux session for n8n
tmux new-session -d -s n8n 'n8n start'

# Check it's running
curl -s http://localhost:5678 | head -c 200
# You should see HTML output, not an error
```

To view n8n's logs later:

```bash
tmux attach -t n8n
# Detach with Ctrl+B then D
```

---

## Step 5: Expose n8n publicly with ngrok

### 5a. Sign up for ngrok (free)

1. Go to https://dashboard.ngrok.com/signup
2. Create a free account
3. Copy your **authtoken** from https://dashboard.ngrok.com/get-started/your-authtoken

### 5b. Install ngrok in Termux

```bash
# Download the ARM64 build (works on modern Android phones)
curl -L -o /tmp/ngrok.zip https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.zip
unzip /tmp/ngrok.zip -d /tmp/
mv /tmp/ngrok $PREFIX/bin/
chmod +x $PREFIX/bin/ngrok
ngrok version
```

### 5c. Authenticate ngrok

```bash
ngrok config add-authtoken YOUR_TOKEN_HERE
```

### 5d. Start the tunnel

```bash
# In a new tmux session
tmux new-session -d -s ngrok 'ngrok http 5678'
```

Get your public URL:

```bash
curl -s http://localhost:4040/api/tunnels | python -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"
```

You'll get something like:

```
https://a1b2c3d4.ngrok-free.app
```

This is your permanent public URL for n8n (as long as ngrok keeps running). Bookmark it.

### 5e. Update n8n's webhook URL

Edit `~/.n8n/.env` and set `WEBHOOK_URL` to your ngrok URL:

```bash
WEBHOOK_URL=https://a1b2c3d4.ngrok-free.app
```

Then restart n8n:

```bash
tmux kill-session -t n8n
tmux new-session -d -s n8n 'n8n start'
```

---

## Step 6: Open the n8n editor

On your phone, open a browser (Chrome, Firefox) and navigate to:

```
http://localhost:5678
```

(or your ngrok URL if you're on a different device)

Log in with the username/password you set in Step 3.

You'll see the n8n workflow editor. Build your first workflow:

1. Click **"Add workflow"**
2. Click **"Add a trigger"** → choose **"Webhook"**
3. In the webhook node, set:
   - **HTTP Method**: `POST`
   - **Path**: `send-email` (or whatever you want)
   - **Authentication**: None (your twin handles auth via your Telegram user ID)
4. Click the **+** next to the webhook node to add the next step
5. Search for "Gmail" (or whichever integration you want)
6. Authenticate with your Google account when prompted
7. Configure the action (e.g., "Send Email")
8. Click **Save**, then **Active**

Now you have a webhook URL like:

```
https://a1b2c3d4.ngrok-free.app/webhook/send-email
```

---

## Step 7: Connect your AI twin to n8n

In Telegram, tell your twin:

> Save this webhook: name is "send_email", URL is https://a1b2c3d4.ngrok-free.app/webhook/send-email, it sends emails via Gmail

The twin will save it via the `save_webhook` tool. From now on, when you say something like:

> Email Sarah the meeting notes from today

The twin will infer it should call `trigger_webhook(webhook_name="send_email", data='{...}')`.

You can also trigger it directly:

> Trigger the send_email webhook with data: {"to":"sarah@example.com","subject":"Meeting notes","body":"..."}

---

## Step 8: Make it auto-start on reboot

Add to your `~/.termux/boot/start-twin.sh` (this is what Termux:Boot runs at startup):

```bash
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock

# Start n8n
tmux new-session -d -s n8n 'n8n start'

# Wait for n8n to be ready
sleep 10

# Start ngrok tunnel
tmux new-session -d -s ngrok 'ngrok http 5678'

# Start the AI twin
tmux new-session -d -s twin 'cd ~/ai-twin && python twin_bot.py'
```

Make it executable:

```bash
chmod +x ~/.termux/boot/start-twin.sh
```

Now everything starts together on reboot.

---

## Optional: Use Nodera to monitor workflows

Nodera is a free Android app that gives you a mobile-friendly dashboard for n8n:

1. Install Nodera from the Play Store
2. Open it, tap **Add instance**
3. Enter your ngrok URL (`https://a1b2c3d4.ngrok-free.app`)
4. Enter the username/password from Step 3

Now you can monitor workflow runs, see errors, and re-trigger workflows from a phone-native UI instead of the browser editor.

---

## Troubleshooting

### `n8n` command not found

```bash
npm config set prefix '$HOME/.npm-global'
echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
npm install -g n8n
```

### n8n crashes on startup (out of memory)

Phones with <4 GB RAM may struggle. Add swap:

```bash
# Create a 2GB swap file
dd if=/dev/zero of=$HOME/swapfile bs=1M count=2048
chmod 600 $HOME/swapfile
# Termux doesn't support mkswap directly — use proot swap as a workaround
# OR: run n8n on a Raspberry Pi / cheap VPS instead of the phone
```

If memory is consistently an issue, consider running n8n on a free Oracle Cloud ARM VPS (always free tier) and only running the twin on the phone.

### ngrok URL changes on restart

The free ngrok tier gives you a random URL each time you restart ngrok. To get a stable URL:

- Upgrade to ngrok's paid tier ($8/mo), OR
- Use Cloudflare Tunnels (free, stable URL): https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/

### Workflows trigger from external services but not from the twin

Make sure the twin is calling the right URL. From Telegram:

> List all saved webhooks

Verify the URL matches what n8n shows in the editor.

### `EADDRINUSE: address already in use 5678`

Something else is using port 5678. Kill it and restart:

```bash
pkill -f "n8n start"
tmux new-session -d -s n8n 'n8n start'
```

---

## Why this is better than n8n.cloud

| Feature | n8n.cloud (paid) | Self-hosted on Android |
|---------|------------------|------------------------|
| Monthly cost | $20+ | $0 |
| Data residency | n8n's servers | Your phone |
| Workflow limit | Per-tier | Unlimited |
| Execution limit | Per-tier | Unlimited (CPU-bound) |
| Works offline | No | Yes (for local integrations) |
| Setup time | 5 min | 15 min |
| Maintenance | Zero | Low (rare updates) |

---

## When NOT to self-host n8n on your phone

- You have <4 GB RAM (n8n + Node + Termux + Python may thrash)
- You need 100% uptime (phones reboot, lose signal, drain battery)
- You're processing heavy data (large spreadsheets, many webhooks/sec)

In those cases, run n8n on a free Oracle Cloud ARM VPS (truly always-free tier: 4 ARM cores, 24 GB RAM) and keep the twin on the phone. The twin will trigger the remote n8n via HTTPS — same webhook tools, just a different URL.

---

## File locations

| Path | Purpose |
|------|---------|
| `~/.n8n/` | n8n database, configs, credentials |
| `~/.n8n/.env` | n8n environment config (host, port, auth) |
| `~/.n8n/database.sqlite` | All workflows, credentials, execution history |
| `~/.ngrok2/ngrok.yml` | ngrok authtoken config |
| `~/ai-twin-memory/n8n_webhooks.json` | Saved webhook URLs (used by twin) |

Back up `~/.n8n/database.sqlite` regularly — it contains everything.

---

## Quick reference — daily commands

```bash
# Check what's running
tmux ls

# View n8n logs
tmux attach -t n8n        # Ctrl+B, D to detach

# View ngrok status
curl -s http://localhost:4040/api/tunnels | python -m json.tool

# Restart n8n
tmux kill-session -t n8n && tmux new-session -d -s n8n 'n8n start'

# Restart ngrok
tmux kill-session -t ngrok && tmux new-session -d -s ngrok 'ngrok http 5678'

# Stop everything
tmux kill-session -t n8n
tmux kill-session -t ngrok

# Open n8n editor (on phone)
# Browser → http://localhost:5678
```

---

## Alternative: skip n8n entirely

Your twin now has native tools for the most common automation use cases:

| Use case | Native twin tool | n8n workflow |
|----------|-------------------|--------------|
| Send an email | `send_email` | Gmail node |
| Create calendar event | `create_calendar_event` | Google Calendar node |
| Fetch news/blog posts | `read_rss` | RSS Read node |
| Shorten a URL | `shorten_url` | HTTP Request node |
| Save a note | `save_note` | Notion/Evernote node |
| Create a task | `create_task` | Todoist/Trello node |
| Send an SMS | `send_sms` | Twilio node |

For these common tasks, you don't need n8n at all — just configure SMTP credentials in `.env` (see `send_email` tool description) and the twin handles everything natively.

Only set up n8n if you need integrations beyond this list (Slack, Discord, Google Sheets, Airtable, custom APIs, multi-step workflows, conditional routing, scheduled jobs, etc.).
