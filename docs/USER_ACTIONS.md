# Christopher's Action List — Cloud Migration + Launch

**Single source of truth for everything YOU need to click/sign-up/paste between now and Monday EOD.** Tasks are sequenced by dependency. Skip nothing.

**Deadline:** Monday May 4 EOD for migration. Sunday May 3 night for revenue-side activations.

---

## Phase 1 — GitHub repo + push (10 min total) — DO FIRST

### 1.1 — Create the GitHub repo (3 min)
1. Open https://github.com/new
2. Repository name: `dealmatcher`
3. Description: `Johnson Buys + CheapHomesFLA — full automation stack`
4. Visibility: **Private**
5. **Do not** initialize with README/license/.gitignore (we have them already)
6. Click "Create repository"
7. Copy the SSH URL: `git@github.com:YOURUSER/dealmatcher.git`

### 1.2 — Push everything (5 min)
Open Terminal:

```bash
cd ~/dealmatcher

# First-time git config (skip if already done)
git config --global user.name "Christopher Johnson"
git config --global user.email "cbfcalcio5@me.com"

# Initial commit
git init -b main
git add .
git status                 # ← verify .env.cheaphomesfla is NOT in the list
git commit -m "Initial commit — full dealmatcher stack"

# Connect + push
git remote add origin git@github.com:YOURUSER/dealmatcher.git
git push -u origin main
```

If SSH fails, generate a key and add to GitHub:
```bash
ssh-keygen -t ed25519 -C "cbfcalcio5@me.com"
pbcopy < ~/.ssh/id_ed25519.pub      # copies the public key to clipboard
# Paste into github.com/settings/keys → New SSH key
```

### 1.3 — Verify (2 min)
- Open https://github.com/YOURUSER/dealmatcher
- Confirm you see folder structure: `cloudflare/`, `jb/`, `tools/`, `docs/`, etc.
- Confirm `.env.cheaphomesfla` is NOT in the file list (it should be ignored)

---

## Phase 2 — Railway sign-up + 4 cron services (60 min)

### 2.1 — Sign up (3 min)
1. Open https://railway.app
2. Click "Login" → **Login with GitHub**
3. Authorize Railway to read your account
4. Choose **Hobby Plan** ($5/mo — $5 of usage credit, plenty for our crons)

### 2.2 — Create the project + first cron (15 min)
1. In Railway dashboard, click **"+ New Project"** → **"Deploy from GitHub repo"**
2. Authorize Railway to read your `dealmatcher` repo
3. Select `dealmatcher` → Railway auto-creates a service running `python cheaphomesfla_scraper.py`
4. Click that service → **Settings**:
   - Service Name: `scraper`
   - Custom Start Command: `python cheaphomesfla_scraper.py`
   - Cron Schedule: `0 14,18,22 * * *` (= 10 AM / 2 PM / 6 PM ET in UTC)
5. Don't deploy yet — first add env vars in step 2.3

### 2.3 — Add environment variables (10 min)
1. Project sidebar → **Shared Variables**
2. Click **"+ New Variable"** for each. Copy from your `~/dealmatcher/.env.cheaphomesfla`:

| Variable | Value (from .env.cheaphomesfla) |
|---|---|
| `SF_USERNAME` | info@johnsonbuys.com |
| `SF_PASSWORD` | (your SF password) |
| `SF_SECURITY_TOKEN` | (your token) |
| `SF_DOMAIN` | johnsonshomes2.my |
| `SENDGRID_API_KEY` | (your SG key) |
| `TWILIO_ACCOUNT_SID` | (Twilio SID) |
| `TWILIO_AUTH_TOKEN` | (Twilio auth) |
| `MS_TENANT_ID` | (Microsoft Graph tenant) |
| `MS_CLIENT_ID` | (Microsoft Graph client) |
| `MS_CLIENT_SECRET` | (Microsoft Graph secret) |
| `MS_USER_PRINCIPAL` | info@cheaphomesfla.com |
| `GREENAPI_INSTANCE_ID` | (Green API ID) |
| `GREENAPI_TOKEN` | (Green API token) |
| `EMAIL_ADDRESS` | info@johnsonbuys.com |
| `ALERT_TO` | info@johnsonbuys.com |
| `CLOUD_MODE` | true |

3. Save. Now click `scraper` service → **Deploy**.

### 2.4 — Add the other 5 cron services (25 min)
For each, click **"+ New"** → **"Empty Service"** → connect to same `dealmatcher` repo, then set Start Command and Cron:

| Name | Start Command | Cron (UTC) | What it is |
|---|---|---|---|
| `jb_email` | `python jb/email_campaign.py` | `0 12 * * 1-6` | 8 AM ET drip |
| `jb_sms` | `python jb/sms_campaign.py` | `15 12 * * 1-6` | 8:15 AM ET batch SMS |
| `jb_followup` | `python jb/followup.py` | `0 12 * * *` | 8 AM ET status SMS |
| `jb_digest` | `python jb/digest.py` | `30 12 * * *` | 8:30 AM ET digest |
| `watchdog` | `python tools/system_watchdog.py` | `0 13 * * *` | 9 AM ET health check |
| `cloud_health` | `python tools/cloud_health_check.py` | `0 13-1 * * 1-6` | hourly 9 AM-9 PM ET |
| `daily_kpi` | `python tools/daily_kpi_email.py` | `15 13 * * 1-6` | 9:15 AM ET success summary |

(Times above assume EDT. Adjust UTC values by +1 for EST in November.)

### 2.5 — Smoke test (10 min)
For each service in Railway:
1. Click the service → **Deployments** → click latest deploy → **Logs**
2. Click the **▶ Trigger** button to manually fire it now
3. Confirm:
   - `scraper` — connects to email + WhatsApp + SF, finds N or 0 deals
   - `jb_email` — connects to SF + SendGrid, sends today's Day-1 batch
   - `jb_sms` — connects to SF + Twilio, sends today's SMS batch
   - `watchdog` — runs all 6 health checks, prints summary
   - `cloud_health` — pings the 4 Cloudflare workers, returns OK or 🟡 alerts
   - `daily_kpi` — connects to SF, prints the snapshot

If all 7 pass → **migration is live.**

---

## Phase 3 — Cloudflare Workers re-deploy from repo (20 min)

The Workers are already live, but they need to be re-deployed from `~/dealmatcher/cloudflare/` (not the old `~/Desktop/` location) AND the new `/health` endpoints + KV namespaces need to be created.

### 3.1 — Create KV namespaces (5 min)

```bash
cd ~/dealmatcher/cloudflare/propertyleads-worker
wrangler kv namespace create LAST_LEAD_AT
# Copy the printed `id` value into wrangler.toml (replace PASTE_KV_ID_HERE)

cd ../motivatedsellers-worker
wrangler kv namespace create LAST_LEAD_AT
# Copy id → wrangler.toml

cd ../whatsapp-worker
wrangler kv namespace create LAST_MSG_AT
# Copy id → wrangler.toml

cd ../sendgrid-events
wrangler kv namespace create LAST_EVENT_AT
# Copy id → wrangler.toml
```

### 3.2 — Re-deploy each worker (5 min)

```bash
cd ~/dealmatcher/cloudflare/propertyleads-worker  && wrangler deploy
cd ~/dealmatcher/cloudflare/motivatedsellers-worker && wrangler deploy
cd ~/dealmatcher/cloudflare/whatsapp-worker        && wrangler deploy
cd ~/dealmatcher/cloudflare/sendgrid-events        && wrangler deploy
```

### 3.3 — Set sendgrid-events secrets (3 min)

```bash
cd ~/dealmatcher/cloudflare/sendgrid-events
wrangler secret put SF_USERNAME      # paste info@johnsonbuys.com
wrangler secret put SF_PASSWORD      # paste SF password
wrangler secret put SF_SECURITY_TOKEN
wrangler secret put SF_LOGIN_DOMAIN  # paste login
```

### 3.4 — Test /health endpoints (2 min)

```bash
curl https://propertyleads-ppl-worker.cbfcalcio5.workers.dev/health
curl https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev/health
curl https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health
curl https://sendgrid-events.cbfcalcio5.workers.dev/health
```

Each should return JSON with `"ok": true`.

### 3.5 — Configure SendGrid Event Webhook (5 min)
See `cloudflare/sendgrid-events/DEPLOY.md` step 4 for click-by-click.

---

## Phase 4 — Twilio /sms v2 deploy (15 min)

Replaces v1 (forwards every reply to your phone) with v2 (auto-classifies + opt-outs without bothering you).

Follow `~/dealmatcher/docs/twilio_function_v2_deploy.md` — 6 steps, ~15 minutes.

---

## Phase 5 — Mac cutover (5 min, ONLY after Phases 2-3 are green)

```bash
# Stop all Mac launchd jobs — Railway is now production
launchctl bootout gui/$(id -u)/com.johnsonbuys.emailcampaign 2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.smscampaign  2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.followup     2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.digest       2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.dealmatcher   2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.watchdog      2>/dev/null

# Archive plists (don't delete — emergency rollback path)
mkdir -p ~/Library/LaunchAgents/_archived_2026-05-04
mv ~/Library/LaunchAgents/com.johnsonbuys.*.plist ~/Library/LaunchAgents/_archived_2026-05-04/ 2>/dev/null
mv ~/Library/LaunchAgents/com.cheaphomes.*.plist ~/Library/LaunchAgents/_archived_2026-05-04/ 2>/dev/null

echo "✓ Cutover complete. Mac is now a development machine only."
```

**Keep `com.johnsonbuys.webhook.plist`** — that's the Flask inbound SMS handler. We'll move it to Twilio Functions in a future task; for now, leave it loaded.

---

## Phase 6 — Salesforce dashboards (60 min — your build)

Open `~/Desktop/sf_dashboards_guide.pdf` and click through. 10 dashboards. Build the priority 5 first (#1, #2, #4, #6, #9 in the guide — Daily Lead Inflow, Active Pipeline, Hot Buyers, Today's Follow-ups, Revenue This Month). Then the other 5 if you have time.

Pre-step: run `python3 tools/sf_setup_helper.py` from your Mac — pre-creates the underlying list views.

---

## Phase 7 — Subscriptions to apply for (10 min)

Online forms — apply now, approval lands in 1-7 business days:

1. **ATTOM Data** — https://www.attomdata.com/ → "Get a Quote" → fill form: residential properties, distress indicators, ~30k records/month for Miami-Dade. Mention "Property API access".
2. **TLO** — https://www.tlo.com/ → request demo → mention "skip-trace + property research, ~500 lookups/month".
3. **healthchecks.io** — https://healthchecks.io → free tier signup. After signup, create one check named "watchdog" → copy ping URL → paste into `tools/system_watchdog.py` (I'll wire this on Sunday).
4. **MLS RETS access** (Miami Realtors) — https://www.miamirealtors.com → MLS access form. ~$50-150/mo. Tell them "RETS data feed for in-house property analysis tooling".

---

## Phase 8 — Constant Contact transition email (when ready Sunday)

I'll generate the draft + the cleaned investor list this evening. You'll:
1. Login to Constant Contact
2. Create a new email campaign
3. Paste the draft (will be in `~/Desktop/transition_email_draft.html`)
4. Upload the new investor list (will be at `~/Desktop/investor_contacts_clean.csv`)
5. Schedule send for Sunday morning

---

## Phase 9 — FB + Google + LinkedIn ad campaigns (Sunday-Monday)

`~/dealmatcher/docs/audience_definitions.md` has copy-paste-ready audience definitions. `ad_copy_seller_side.md` and `ad_copy_buyer_side.md` have the creative.

Action sequence:
1. Build FB Custom Audiences (need Sell Score CSV first — needs ATTOM)
2. Build 1% Lookalikes
3. Apply Special Ad Category = Housing (legally required)
4. Save 3 ad variants per side as DRAFT
5. Activate after subscriptions land + scoring is current

---

## Quick reference — when something breaks

| Symptom | Look at | Fix |
|---|---|---|
| No emails sent today | Railway → `jb_email` → Logs | Re-deploy from GitHub or trigger manually |
| No SMS sent today | Railway → `jb_sms` → Logs | Same |
| No leads from PPL provider | `cloud_health` Logs OR `curl <worker>/health` | Check provider's webhook URL config |
| Watchdog hasn't emailed in 2 days | healthchecks.io alert page | watchdog itself is broken — check Railway |
| Salesforce shows no Tasks for emails | sendgrid-events Worker logs | Webhook URL pasted in SendGrid? Secret matches? |
| Build broke after a push | Railway → Deployments → red entry → Logs | Roll back via "Redeploy previous green deploy" |

---

## What's done before you read this

(So you know what NOT to redo.)

- ✓ All Python scripts moved into `~/dealmatcher/jb/` and env-var-patched
- ✓ All Cloudflare workers moved into `~/dealmatcher/cloudflare/`
- ✓ `.gitignore`, `.env.example`, `requirements.txt`, `railway.json`, `Procfile` — all set
- ✓ Watchdog + plists ready to load (the Mac plists are still your fallback)
- ✓ `tools/cloud_health_check.py` built (closes alert gaps a, b, c, e)
- ✓ `tools/daily_kpi_email.py` built (closes alert gap i)
- ✓ All 4 CF Workers have `/health` endpoint + KV `LAST_*_AT` writes
- ✓ `cloudflare/sendgrid-events/` worker built (open/click → SF Tasks)
- ✓ `docs/CLOUD_DEPLOY.md` (Railway deploy guide)
- ✓ `docs/SF_DASHBOARDS.md` + PDF (10 dashboards click-by-click)
- ✓ `docs/automation_map.pdf` (every cron, alert, gap)
- ✓ `docs/master_plan.pdf` (18-page plan)

---

## When in doubt

Send "next" or a specific question — I respond immediately. Anything in this list that's confusing, ask before clicking. We have until Monday EOD.
