# Cloud Deploy — Railway + GitHub + Cloudflare

**Goal:** No automation depends on Mac mini or MacBook Air being on. Either Mac is a development environment only — they `git clone` the same repo, edit, push, and Railway redeploys automatically. Cowork can fix anything on either machine.

**Deadline:** Monday May 4 EOD.

---

## Architecture (one picture)

```
                    ┌─────────────────┐
                    │     GitHub      │   ← single source of truth
                    │ private repo    │     (christopherjohnson/dealmatcher)
                    └────────┬────────┘
                             │
                  push       │       auto-deploy on push to main
            ┌────────────────┴──────────────┐
            ▼                               ▼
   ┌──────────────────┐          ┌──────────────────────┐
   │ Mac mini         │          │ Railway              │
   │ (Cowork edits)   │          │ Cron services:       │
   │                  │          │  • scraper (3x/day)  │
   │ MacBook Air      │          │  • jb_email (8 AM)   │
   │ (Cowork edits)   │          │  • jb_sms   (8:15)   │
   │                  │          │  • watchdog (9 AM)   │
   │ EITHER one can:  │          └──────────────────────┘
   │  git clone       │
   │  edit            │          ┌──────────────────────┐
   │  git push        │          │ Cloudflare Workers   │
   │  → Railway       │          │  • motivatedsellers  │
   │    redeploys     │          │  • propertyleads     │
   │                  │          │  • sendgrid-events*  │
   │ NO machine has   │          │  (always-on webhook  │
   │ a production job │          │   receivers)         │
   └──────────────────┘          └──────────────────────┘
                                                * to be built
```

**Mac mini and MacBook Air are interchangeable.** Either can `git clone git@github.com:christopherjohnson/dealmatcher.git`, run Cowork on it, push fixes, and within 2 minutes Railway has redeployed. Neither machine needs to be left running for the business to operate.

---

## One-time setup (Saturday May 2 — ~90 minutes total)

### Step 1 — Create the GitHub repo (5 min, your action)

1. Go to https://github.com/new
2. Repository name: `dealmatcher`
3. Visibility: **Private**
4. Do NOT initialize with README / license / .gitignore (we already have them)
5. Click "Create repository"

You'll see a page with the repo URL. Copy the `git@github.com:YOURUSER/dealmatcher.git` SSH URL.

### Step 2 — Push the existing code to GitHub (5 min)

Open Terminal and run:

```bash
cd ~/dealmatcher

# First-time git setup if needed
git config --global user.name "Christopher Johnson"
git config --global user.email "cbfcalcio5@me.com"

# Init + first commit
git init -b main
git add .
git status   # ← check that .env.cheaphomesfla is NOT in the list (gitignore working)
git commit -m "Initial commit — dealmatcher repo + cloud deploy package"

# Connect to GitHub and push
git remote add origin git@github.com:YOURUSER/dealmatcher.git
git push -u origin main
```

If you get an SSH key error, generate one with `ssh-keygen -t ed25519 -C "cbfcalcio5@me.com"`, then paste `~/.ssh/id_ed25519.pub` contents into github.com/settings/keys.

### Step 3 — Sign up for Railway (2 min, your action)

1. Go to https://railway.app
2. Sign up with GitHub (one click — uses the same account)
3. Verify the email if prompted
4. Pricing: Hobby plan ($5/mo, includes $5 of usage — more than enough for our crons)

### Step 4 — Create the Railway project (5 min, your action)

1. In Railway dashboard click **"New Project"** → **"Deploy from GitHub repo"**
2. Authorize Railway to read your GitHub account
3. Pick `dealmatcher`
4. Railway auto-detects Python, installs requirements.txt, creates one service
5. Click that service → **"Settings"** → rename to `scraper`
6. Click **"Settings"** → **"Cron Schedule"** → enter `0 14,18,22 * * *` (10 AM / 2 PM / 6 PM ET in UTC)
7. Click **"Settings"** → **"Custom Start Command"** → enter `python cheaphomesfla_scraper.py`

### Step 5 — Add the other 3 cron services (15 min, your action)

For each of these, click **"+ New"** → **"Empty Service"** → connect to same GitHub repo, then set start command + cron:

| Service name | Start command | Cron (UTC) | ET equivalent |
|---|---|---|---|
| `jb_email` | `python jb/email_campaign.py` | `0 12 * * 1-6` | 8 AM Mon-Sat |
| `jb_sms` | `python jb/sms_campaign.py` | `15 12 * * 1-6` | 8:15 AM Mon-Sat |
| `watchdog` | `python tools/system_watchdog.py` | `0 13 * * *` | 9 AM daily |

(EDT is UTC-4 in May. After Nov DST, all UTC values shift +1.)

### Step 6 — Set environment variables (10 min, your action)

In Railway → Project → click **"Shared Variables"** in the sidebar (these apply to all services):

Paste each variable from your `~/dealmatcher/.env.cheaphomesfla` file. The required ones:

```
SF_USERNAME
SF_PASSWORD
SF_SECURITY_TOKEN
SF_DOMAIN
SENDGRID_API_KEY
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
MS_TENANT_ID
MS_CLIENT_ID
MS_CLIENT_SECRET
MS_USER_PRINCIPAL
GREENAPI_INSTANCE_ID
GREENAPI_TOKEN
EMAIL_ADDRESS
ALERT_TO
CLOUD_MODE=true        ← important: tells scripts not to write local files
```

### Step 7 — Smoke test each cron (15 min)

In Railway → each service → **"Deployments"** tab → click latest deploy → **"View Logs"**. Then click the **"Trigger"** button to run the cron manually right now.

For each service confirm:

- `scraper` — finds 0 or more deals, logs no Python errors
- `jb_email` — connects to SF, sends Day-1 to today's leads
- `jb_sms` — connects to SF + Twilio, sends today's batch
- `watchdog` — runs all 5 health checks, prints summary

If all 4 pass: **the cloud is live.**

### Step 8 — Cutover: unload Mac plists (5 min, your action)

ONLY after Step 7 passes. Open Terminal and run:

```bash
# Stop and unload all Mac launchd jobs — they're now redundant
launchctl bootout gui/$(id -u)/com.johnsonbuys.emailcampaign 2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.smscampaign 2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.followup 2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.digest 2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.dealmatcher 2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.watchdog 2>/dev/null

# Move the plists to an archive folder (don't delete — emergency rollback)
mkdir -p ~/Library/LaunchAgents/_archived_2026-05-04
mv ~/Library/LaunchAgents/com.johnsonbuys.*.plist ~/Library/LaunchAgents/_archived_2026-05-04/
mv ~/Library/LaunchAgents/com.cheaphomes.*.plist ~/Library/LaunchAgents/_archived_2026-05-04/

echo "Mac plists archived. Cloud is now sole production runtime."
```

**Keep the JB webhook plist** (`com.johnsonbuys.webhook.plist`) — that's the inbound SMS handler for legacy Twilio Function calls. Will move it to Twilio Functions in a separate task.

---

## Day-to-day workflow after migration

### Fixing a bug from EITHER Mac

```bash
# Open Cowork on Mac mini OR MacBook Air — same workflow either machine:
cd ~/dealmatcher
git pull                 # get latest from GitHub
# ... ask Cowork to fix the issue ...
git add -A && git commit -m "fix: <what changed>"
git push
# Within ~2 min Railway picks up the push and redeploys.
# Logs visible at railway.app → project → service → Deployments → Logs.
```

### Watching live logs from anywhere

- Railway dashboard → project → service → **"Deployments"** → click any deploy → live tail
- Or install the Railway CLI: `npm i -g @railway/cli`, then `railway logs --service scraper --tail`

### Pulling cron logs into a daily summary email

(Future task — `tools/build_daily_summary.py` will pull Railway's logs API and email Chris a one-page summary.)

---

## Why Railway and not [other thing]?

- **Heroku** — comparable, slightly more expensive, fewer cron-friendly features.
- **AWS Lambda + EventBridge** — cheaper at scale but 5-day setup, IAM hell, not a fit for "I need this Monday."
- **Render** — comparable to Railway, slower cold starts on cron.
- **Cloudflare Workers** — JS-only, cron-friendly, but our scripts are Python. We're already using CF Workers for the inbound webhooks (different problem).
- **DigitalOcean App Platform** — viable but Railway has cleaner cron UX.

Railway gives us: GitHub auto-deploy + cron + env-var management + log streaming + `$5/mo` predictable cost, all configured via web UI in 90 minutes.

---

## Rollback plan if Railway breaks

You have two reverse-stops, in increasing order of urgency:

1. **Railway rollback** — in Railway → service → Deployments → previous green deploy → **"Redeploy"**. ~30 seconds.
2. **Mac fallback** — un-archive the plists from `~/Library/LaunchAgents/_archived_2026-05-04/` and run `launchctl bootstrap gui/$(id -u)` on each. The Mac becomes production again until you fix Railway. ~5 minutes.

The Mac doesn't need to be running once Railway is solid, but the plists stay archived (not deleted) so the rollback path is real.

---

## What I (Cowork) can do for you from here

After steps 1–8 are complete, ask me to:

- "Add a new cron — daily SF dashboard refresh at 7 AM"
- "Tail the Railway logs for the scraper since 6 AM"
- "Why did the SMS campaign skip 200 leads yesterday — pull the log"
- "Build a /sms_v3 with [whatever new rule]"
- "Push a hotfix to production"

Either Mac, same workflow.
