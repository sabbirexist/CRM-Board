# WorkBase CRM — Complete Setup Guide
## Telegram Bot + OpenClaw Skill + WhatsApp KB Import + Cloud Deploy

---

## 📁 Files in This Package

| File | Purpose |
|---|---|
| `app.py` | Flask backend (all APIs + Telegram webhook + WhatsApp importer) |
| `index.html` | Frontend dashboard (unchanged) |
| `crm.skill.js` | OpenClaw skill — drop into your skills/ folder |
| `requirements.txt` | Python deps: flask + gunicorn |
| `railway.toml` | Railway auto-deploy config |
| `fly.toml` | Fly.io deploy config |
| `Procfile` | Used by Railway / Render |

---

## ☁️ HOSTING: Which Platform to Pick

### 🥇 Railway — RECOMMENDED

**Why:** Easiest deploy, persistent disk (SQLite works perfectly), no cold starts, GitHub push-to-deploy.

**Free tier:** $5 credit/month — enough for ~1 month free, then ~$5/mo after.

**Steps:**

```bash
# 1. Push your files to a GitHub repo
git init && git add . && git commit -m "init"
git remote add origin https://github.com/YOU/workbase-crm.git
git push -u origin main

# 2. Go to railway.app → New Project → Deploy from GitHub
# 3. Select your repo
# 4. Railway auto-detects Python and deploys
```

**Set these environment variables in Railway dashboard → Variables:**

```
TELEGRAM_BOT_TOKEN   = 123456:ABC-your-actual-token
CRM_PASSWORD         = your-strong-password
SECRET_KEY           = random-string-32-chars
BOT_API_KEY          = another-random-string (for OpenClaw skill)
CRM_URL              = https://workbase-crm.up.railway.app  ← copy from Railway after first deploy
TELEGRAM_ALLOWED_USERS = your-telegram-user-id  ← get it by messaging @userinfobot
DB_PATH              = /data/crm.db             ← uses the persistent volume
```

**Add persistent volume:**
- Railway dashboard → your service → Volumes → Add Volume
- Mount path: `/data`
- This keeps your SQLite database across deploys

---

### 🥈 Fly.io — Best Free Tier

**Why:** Genuinely free tier (3 shared VMs), never sleeps, persistent volumes.

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Launch (first time)
fly launch --name workbase-crm --region sin

# Create persistent volume
fly volumes create crm_data --region sin --size 1

# Set secrets
fly secrets set \
  TELEGRAM_BOT_TOKEN="123456:your-token" \
  CRM_PASSWORD="your-password" \
  SECRET_KEY="random-32-chars" \
  BOT_API_KEY="your-bot-key" \
  CRM_URL="https://workbase-crm.fly.dev" \
  DB_PATH="/data/crm.db"

# Deploy
fly deploy

# Your URL: https://workbase-crm.fly.dev
```

---

### 🥉 Render — Easiest but sleeps on free tier

Free tier spins down after 15 min of inactivity (30s cold start). Fine if you access daily.

```
1. render.com → New Web Service → Connect GitHub repo
2. Build Command:  pip install -r requirements.txt
3. Start Command:  python app.py
4. Add environment variables (same as Railway above)
5. Add a Disk: /data, 1GB
```

---

## 🤖 TELEGRAM BOT SETUP

### Step 1: Create Your Bot

1. Open Telegram → search **@BotFather**
2. Send: `/newbot`
3. Give it a name: `WorkBase CRM`
4. Give it a username: `workbase_yourname_bot`
5. BotFather gives you a token: `123456789:AAHabc...`
6. **Copy this token** — paste it as `TELEGRAM_BOT_TOKEN` env variable

### Step 2: Get Your Telegram User ID

1. Message **@userinfobot** on Telegram
2. It replies with your numeric user ID (e.g. `987654321`)
3. Set `TELEGRAM_ALLOWED_USERS=987654321` in your env vars
4. Add multiple users: `987654321,112233445`

### Step 3: Register the Webhook

After your app is deployed and running:

```bash
# Option A: Visit this URL in your browser (while logged into the CRM)
https://your-app.railway.app/telegram/setup

# Option B: curl command
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-app.railway.app/telegram/webhook"}'

# Option C: Tell your bot in Telegram
/setwebhook
```

### Step 4: Add Bot to Your Team Group

1. Open your team group in Telegram
2. Group Settings → Add Members → search your bot username
3. The bot will now **silently absorb all group messages** into the `group_knowledge` table
4. From your private DM to the bot: `/syncgroups` — pushes all unsynced group messages into the KB
5. Or sync from the dashboard: **KB tab → Sync Groups button**

### Bot Commands Reference

| Command | What it does |
|---|---|
| `/tasks` | Summary of all tasks |
| `/todo` | List To Do items |
| `/inprogress` | In Progress items |
| `/overdue` | Overdue tasks with days count |
| `/newtask` | Start a new task (guided flow) |
| `/note` | Quick note |
| `/addkb` | Add KB entry |
| `/kb query` | Search KB |
| `/stats` | Dashboard numbers |
| `/team` | Team member list |
| `/syncgroups` | Sync group chat → KB |
| `/remind` | Set a reminder |

**Natural language also works in private chat:**
```
add task Review the Q2 proposal
note: Meeting recap - John wants redesign by Friday
remind me send invoice at 9am tomorrow
search kb onboarding
```

---

## 📱 WHATSAPP CHAT IMPORT → KB

### How to Export a WhatsApp Chat

**Android:**
1. Open the chat or group
2. ⋮ (3 dots) → More → Export Chat
3. Choose "Without Media"
4. Save the `.txt` file

**iPhone:**
1. Open the chat
2. Tap contact/group name at top
3. Scroll down → Export Chat
4. Choose "Without Media"
5. Share the `.txt` file to yourself

### How to Import to KB

**Method 1: From the dashboard (KB tab)**
```
KB Tab → Import WhatsApp → Upload .txt file → Set category → Import
```

**Method 2: API call**
```bash
# Upload file
curl -X POST https://your-app.railway.app/api/import/whatsapp \
  -H "Cookie: session=..." \
  -F "file=@/path/to/WhatsApp Chat with Team.txt" \
  -F "category=Team Conversations"

# Or send as JSON (paste text)
curl -X POST https://your-app.railway.app/api/import/whatsapp \
  -H "Content-Type: application/json" \
  -H "Cookie: session=..." \
  -d '{"text": "25/02/2024, 10:30 - John: Hello...", "category": "Client Chats"}'
```

Each day of conversation becomes a separate KB entry, searchable from the board and from the Telegram bot (`/kb query`).

---

## 🦞 OPENCLAW SKILL SETUP

The `crm.skill.js` file lets your local OpenClaw instance control the CRM board from your TUI or Telegram bot.

### Install the Skill

```bash
# Find your OpenClaw skills folder
ls ~/.openclaw/skills/
# or
ls ~/openclaw/skills/

# Copy the skill file there
cp crm.skill.js ~/.openclaw/skills/

# Restart OpenClaw or say "reload skills" in the TUI
```

### Set Environment Variables for the Skill

Add to your `~/.openclaw/.env` or OpenClaw config:

```bash
CRM_URL=https://your-app.railway.app
CRM_BOT_KEY=your-bot-api-key      # must match BOT_API_KEY in Railway
```

### What You Can Say to OpenClaw

```
"Show my CRM tasks"
"Create a task: Review Q2 report, high priority, due next Friday"
"Mark task #5 as done"
"Add urgent task: Fix payment bug"
"Search the KB for client onboarding"
"Add to KB: Our Git workflow is..."
"Save a note: Ideas from today's meeting..."
"CRM stats"
"Set a reminder: Weekly sync every Monday at 9am"
"Is the CRM online?"
```

OpenClaw understands these naturally and calls the right API.

---

## 🔑 ENVIRONMENT VARIABLES REFERENCE

| Variable | Required | Example | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes (for bot) | `123456:ABC...` | From @BotFather |
| `CRM_PASSWORD` | Yes | `mysecretpw` | Dashboard login password |
| `SECRET_KEY` | Yes | `random32chars` | Flask session secret |
| `BOT_API_KEY` | Yes (for OpenClaw) | `another-secret` | Shared key for /bot/* routes |
| `CRM_URL` | Yes (for bot) | `https://app.railway.app` | Your public URL |
| `DB_PATH` | Yes (Railway/Fly) | `/data/crm.db` | Path to SQLite file |
| `TELEGRAM_ALLOWED_USERS` | Optional | `123456,789012` | Restrict bot access |

---

## 🔒 SECURITY NOTES

1. **Change all default values** — `CRM_PASSWORD`, `SECRET_KEY`, `BOT_API_KEY`
2. **Set `TELEGRAM_ALLOWED_USERS`** — or anyone who finds your bot can use it
3. **Keep `BOT_TOKEN` secret** — it's a permanent token with full bot control
4. The `/bot/*` routes use `X-Bot-Key` header auth — keep `BOT_API_KEY` secret
5. Railway/Fly.io encrypt env variables at rest — don't put them in code

---

## 🧪 TESTING THE SETUP

```bash
# 1. Check bot is alive
curl https://api.telegram.org/bot<TOKEN>/getMe

# 2. Check webhook is set
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo

# 3. Test bot API (OpenClaw skill routes)
curl -H "X-Bot-Key: your-bot-key" https://your-app.railway.app/bot/ping
# → {"status": "ok", "time": "2024-..."}

curl -H "X-Bot-Key: your-bot-key" https://your-app.railway.app/bot/stats
# → {"total": 5, "in_progress": 2, ...}

# 4. Test task creation via API
curl -X POST https://your-app.railway.app/bot/tasks \
  -H "X-Bot-Key: your-bot-key" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test task from API", "priority": "high"}'
```

---

## 🔄 SYNC FLOW: Group Chat → KB

```
Team Telegram Group
       ↓ (every message)
group_knowledge table (raw storage)
       ↓ (you say /syncgroups or click Sync in dashboard)
kb_entries table (searchable, categorised as "Team Conversations")
       ↓
Searchable from bot: /kb what did we decide about X
       ↓
Accessible via OpenClaw: "Search KB for our meeting decisions"
```

---

## 📞 SUPPORT

- OpenClaw docs: https://docs.openclaw.ai
- OpenClaw Discord: https://discord.com/invite/clawd
- Railway docs: https://docs.railway.app
- Fly.io docs: https://fly.io/docs

---

*Built with WorkBase CRM — your business OS.*
