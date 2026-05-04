# Railway Services — what runs in cloud + how to add new ones

> Last updated: 2026-05-04

## Currently running on Railway (project `luminous-spontaneity`)

| Service | Schedule (UTC) | What it runs | Status |
|---|---|---|---|
| `dealmatcher` | every 4h | `cheaphomesfla_scraper.py` — pull mail + WA, parse, match, email per-buyer | active |
| `jb_email` | `0 12 * * 1-6` | `johnson_buys_email_campaign.py` — 8 AM ET morning email blast | active |
| `jb_sms` | `15 12 * * 1-6` | `johnson_buys_sms_campaign.py` — 8:15 AM ET SMS blast | active |
| `jb_followup` | `0 18 * * 1-6` | `johnson_buys_followup.py` — 2 PM ET same-day follow-up | active |
| `jb_digest` | `0 13 * * *` | `johnson_buys_digest.py` — 9 AM ET daily digest | active |
| `watchdog` | every 30 min | `tools/system_watchdog.py` — multi-source health pinger | active |
| `cloud_health` | hourly | `tools/cloud_health_check.py` — broader sentinel | active |
| `daily_kpi` | `30 13 * * *` | `tools/daily_kpi_email.py` — 9:30 AM ET KPI summary | active |
| `pipeline_health_monitor` | `0 * * * *` | `tools/pipeline_health_monitor.py` — alert on layer-3 failures | **TODO: deploy** |

---

## Adding a new Railway service (template)

The Railway CLI + dashboard make this a 5-minute task. Process:

### Option A — via Railway CLI (preferred)

```bash
cd ~/dealmatcher
railway login            # one-time
railway link             # connect to luminous-spontaneity project
railway add              # create new service in the project
# Pick: empty service, give it a name (e.g. pipeline_health_monitor)

# Set env vars to mirror what's needed:
railway variables set --service pipeline_health_monitor \
  SENDGRID_API_KEY="$(grep ^SENDGRID_API_KEY= .env.cheaphomesfla | cut -d= -f2)" \
  TWILIO_ACCOUNT_SID="$(grep ^TWILIO_ACCOUNT_SID= .env.cheaphomesfla | cut -d= -f2)" \
  TWILIO_AUTH_TOKEN="$(grep ^TWILIO_AUTH_TOKEN= .env.cheaphomesfla | cut -d= -f2)" \
  TWILIO_FROM="+19549534554" \
  ALERT_SMS_TO="+13055759040" \
  ALERT_TO="info@johnsonbuys.com" \
  FROM_EMAIL="info@johnsonbuys.com" \
  SF_USERNAME="$(grep ^SF_USERNAME= .env.cheaphomesfla | cut -d= -f2)" \
  SF_PASSWORD="$(grep ^SF_PASSWORD= .env.cheaphomesfla | cut -d= -f2)" \
  SF_SECURITY_TOKEN="$(grep ^SF_SECURITY_TOKEN= .env.cheaphomesfla | cut -d= -f2)"

# Set the start command + cron schedule:
railway variables set --service pipeline_health_monitor \
  RAILWAY_RUN_CMD="python3 tools/pipeline_health_monitor.py" \
  RAILWAY_CRON_SCHEDULE="0 * * * *"

railway up --service pipeline_health_monitor
```

### Option B — via Railway dashboard (browser)

1. https://railway.com/dashboard → project `luminous-spontaneity`
2. Click `+ New` → Service → Empty Service
3. Name: `pipeline_health_monitor`
4. Settings → Source → connect to GitHub repo `qvxmrcq97p-jpg/dealmatcher`, branch `main`
5. Settings → Service Settings → Start Command: `python3 tools/pipeline_health_monitor.py`
6. Settings → Cron Schedule: `0 * * * *` (every hour)
7. Variables tab → add (mirror what's listed in Option A above):
   - SENDGRID_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, ALERT_SMS_TO, ALERT_TO, FROM_EMAIL, SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN
8. Save → Railway deploys

After first cron firing, check Logs tab — should see "ALL CHECKS PASSED" or actionable issues.

---

## Removing / pausing a service

Each service can be paused in dashboard → service → Settings → "Pause Service". Or remove entirely with the trash icon. **Never remove `dealmatcher` or `watchdog`** — those are core.

---

## Restarting a service after env-var changes

Railway auto-redeploys when env vars change in dashboard. If you set them via CLI it does NOT auto-redeploy — run `railway redeploy --service <name>` to force.

---

## Pricing notes (so we don't get surprised)

- Railway Hobby tier: $5/mo includes 500h of execution + $0.000463/GB-min RAM
- Cron services billed per-execution time (a 30s health check costs ~$0 worth of $5/mo budget)
- 9 services total currently; expected monthly: $5-10 well under their threshold
