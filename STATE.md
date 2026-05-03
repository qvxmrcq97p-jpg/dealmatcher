# dealmatcher — Project State

**Last updated:** 2026-05-03 (Sun) — Cloud migration day
**Owner:** Christopher Johnson (cbfcalcio5@me.com / cbfcalcio5@gmail.com for Cloudflare)
**Scope:** Two real-estate businesses sharing infrastructure
- **Johnson Buys** — motivated-seller acquisition (we buy houses)
- **CheapHomesFLA** — off-market investor deal flow (we sell discounted houses to buyers)

> **For Claude (any session, any machine):** Read this file first. It captures everything currently deployed, every credential location, every pending task. After reading, ask the user "what do you want to work on?" — don't recap, just continue.

---

## 🟢 Currently deployed (cloud)

### GitHub
- Repo: `qvxmrcq97p-jpg/dealmatcher` (private)
- Auto-deploy: GitHub Actions → Cloudflare Workers on push to `main`
- Secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (set, verified)

### Railway — project `luminous-spontaneity` (production env)
8 cron services, all sharing the same `dealmatcher` Docker image:

| Service | Cron (UTC) | What it does |
|---|---|---|
| `dealmatcher` | every 4h | CheapHomesFLA scraper (3x/day equivalent) |
| `jb_email` | `0 12 * * 1-6` (8AM ET) | Johnson Buys morning email blast |
| `jb_sms` | `15 12 * * 1-6` (8:15AM ET) | Johnson Buys morning SMS blast |
| `jb_followup` | `0 18 * * 1-6` (2PM ET) | Same-day follow-up SMS to non-responders |
| `jb_digest` | `0 13 * * *` (9AM ET) | Daily summary email to Chris |
| `watchdog` | every 30 min | system_watchdog.py — pings Slack on issues |
| `cloud_health` | hourly business hours | cloud_health_check.py — multi-source ping |
| `daily_kpi` | `30 13 * * *` (9:30AM ET) | KPI summary email |

### Cloudflare Workers (account `7c8851172228e9e446dbfb4c53e8badf`)
| Worker | URL | KV namespace | Purpose |
|---|---|---|---|
| `propertyleads-ppl-worker` | `propertyleads-ppl-worker.cbfcalcio5.workers.dev` | `LAST_LEAD_AT` | Receives PropertyLeads PPL → SF Lead |
| `motivatedsellers-ppl-worker` | `motivatedsellers-ppl-worker.cbfcalcio5.workers.dev` | `LAST_LEAD_AT_MS` (binding=LAST_LEAD_AT) | Receives MotivatedSellers PPL → SF Lead |
| `sendgrid-events` | `sendgrid-events.cbfcalcio5.workers.dev` | `LAST_EVENT_AT` | Tracks email open/click/bounce → SF |
| `railway-deploy-alerts` | `railway-deploy-alerts.cbfcalcio5.workers.dev` | `LAST_ALERT_AT` | SMS+email when a Railway deploy fails |
| `cheaphomesfla-whatsapp-webhook` | `cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev` | `LAST_MSG_AT` | Twilio WhatsApp inbound forwarder |

All have `/health` endpoints that return JSON with `last_*_at` from KV.

### Webhooks wired up
- ✅ SendGrid Event Webhook → `sendgrid-events` Worker (configured via API)
- ✅ Railway deploy webhook → `railway-deploy-alerts` Worker (with `?secret=` auth)
- ✅ GitHub → Cloudflare Workers (auto-deploy on push to `main`)

### Twilio
- Account SID + Auth Token in `.env.cheaphomesfla`
- Phone: `+19549534554` (johnsonbuys.com)
- Function service: `johnson-buys-sms`
- `/sms` handler: **v1 currently deployed** — Phase 5 will swap to v2 (smart classifier)

### Salesforce
- Org: `johnsonshomes2.my.salesforce.com`
- Username: `info@johnsonbuys.com`
- 17 of 26 reports built (5 dashboards favorited on home screen)
- 4 custom fields added: `SMS_Opt_Out__c`, `Buyer_Target_Zips__c`, ...
- 5 Task-based dashboards still pending (Task report type API rejection — workaround needed)

### SendGrid
- Email API: free plan (100/day), Event Webhook configured
- Marketing Campaigns: trial expired, NOT upgrading (using Email API for sends)
- API key in `.env.cheaphomesfla`

---

## 🟡 In progress

| Phase | Status | Owner | Next action |
|---|---|---|---|
| **Phase 5** — Twilio /sms v2 deploy | Script written, not yet run | Chris | `python3 tools/deploy_twilio_sms.py --dry-run` |
| **Phase 6** — Mac plist cutover | Script written, not yet run | Chris | `bash tools/cutover_to_cloud.sh` (dry-run first) |
| **End-to-end smoke test** | Pending Phase 5/6 | Claude | Will write after Phase 6 completes |
| **MacBook Air bootstrap** | Pending | Claude | `bootstrap_macbook.sh` — write today 2 PM |
| **Constant Contact transition email** | Email drafted | Chris | Coordinate scrape + email blast 3 PM |
| **PropertyRadar / ATTOM signup** | Not started | Chris | Apply for both today |

---

## 🔴 Hard deadlines

- **Mon May 4, 8:00 AM ET** — Cloud must be running. Mac local launchd jobs must be off (Phase 6).
- **Mon May 4, EOD** — Full migration acceptance.
- **Tonight, 8:00 PM ET** — CheapHomesFLA scrape auto-fires from Railway (first cloud run). Watch logs.

---

## 📁 File layout (~/dealmatcher)

```
.
├── STATE.md                    ← this file
├── .env.cheaphomesfla          ← all credentials (gitignored, never committed)
├── cheaphomesfla_scraper.py    ← main CHF scraper (pulled into Railway as image)
├── cloudflare/
│   ├── propertyleads-worker/
│   ├── motivatedsellers-worker/
│   ├── sendgrid-events/
│   ├── railway-deploy-alerts/
│   └── whatsapp-worker/
├── twilio-functions/
│   ├── sms_v2.js               ← Phase 5 target
│   └── test_classifier.py
├── tools/
│   ├── cf_set_secrets.sh       ← (done) seeds wrangler secrets from .env
│   ├── deploy_twilio_sms.py    ← Phase 5
│   ├── cutover_to_cloud.sh     ← Phase 6 (dry-run / --apply / --rollback)
│   ├── test_railway_alert.sh   ← end-to-end test for Railway webhook
│   ├── configure_sendgrid_webhook.sh  ← configures Event Webhook via API
│   ├── system_watchdog.py
│   ├── cloud_health_check.py
│   ├── daily_kpi_email.py
│   └── ...
├── docs/
│   ├── RUNBOOK.md
│   ├── master_plan.pdf
│   └── twilio_function_v2_deploy.md
└── .github/workflows/
    └── deploy-workers.yml      ← auto-deploys CF Workers on push
```

---

## 🔑 Credentials reference (location, not values)

All actual values are in `.env.cheaphomesfla` (line numbers may shift):

| Key | Where | Used by |
|---|---|---|
| `SF_USERNAME` / `SF_PASSWORD` / `SF_SECURITY_TOKEN` | .env | All SF scripts + 4 Workers |
| `SENDGRID_API_KEY` | .env | All email scripts + 3 Workers |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | .env | All SMS scripts + 3 Workers |
| `CLOUDFLARE_API_TOKEN` | GitHub repo secrets | GitHub Actions auto-deploy |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub repo secrets | GitHub Actions auto-deploy |
| `SHARED_SECRET` (Railway webhook) | Cloudflare Worker secret | Railway webhook auth |
| Cloudflare Account ID | hardcoded `7c8851172228e9e446dbfb4c53e8badf` | All wrangler.toml |

The `.env.cheaphomesfla` file is **NOT** in GitHub (gitignored). It must be transferred manually to a new machine — see `MOBILE_DEV.md` (will be written during MBA bootstrap).

---

## 🔁 Working from another Mac (e.g. MacBook Air)

The cloud doesn't care which machine you're on. To set up a second Mac:

1. Install Homebrew if absent: https://brew.sh
2. Run: `brew install git python3 node gh wrangler twilio-cli`
3. Generate SSH key: `ssh-keygen -t ed25519 -C "cbfcalcio5@me.com" -N "" -f ~/.ssh/id_ed25519`
4. `cat ~/.ssh/id_ed25519.pub | pbcopy` → add to https://github.com/settings/keys
5. `git clone git@github.com:qvxmrcq97p-jpg/dealmatcher.git ~/dealmatcher`
6. AirDrop `.env.cheaphomesfla` from primary Mac to MBA → save in `~/dealmatcher/`
7. Auth wrangler: `wrangler login` (one-time browser flow)
8. Open Cowork → select `~/dealmatcher` folder → first prompt: "Read STATE.md and continue"

A `bootstrap_macbook.sh` script automating most of this will be written 2 PM today.

---

## 🧠 What Claude should know (for any session pickup)

- **Don't ask "where are we?" — read this file.** It's the answer.
- The user is moving fast. Keep responses concise. Skip recap. Get to action.
- The user pastes URLs into Terminal by mistake — when giving URLs, explicitly mark "in Chrome address bar" or "for Terminal: `bash <script>`".
- All scripts in `tools/` follow a consistent pattern: read `.env.cheaphomesfla` for credentials, log to stdout, accept `--dry-run` where destructive.
- If a webhook URL needs pasting, write a `tools/<thing>_helper.sh` that uses `pbcopy` to put it on the clipboard, then `open -a "Google Chrome" <url>`.
- When the user says "do this", first try the API. Manual UI clicking is the slow fallback.
- For long file paths in conversation, use `~/dealmatcher/` not the absolute /Users path.

---

## 📝 Open questions / future work (non-urgent)

1. **PropertyRadar/ATTOM API integration** — for cross-referencing scraped CHF deals against historical sold-homes data. Predictive scoring v3.
2. **Constant Contact → SendGrid migration** — move existing CC contact list + drip sequences to SG over next 30 days.
3. **Email engagement → SF profile enrichment** — when someone opens/clicks a deal email, auto-tag their SF Lead with the deal's county/zip/price band. Auto-create Lead if not in SF yet.
4. **FB/Google lookalike audiences** — once we have ~1k active leads, hash + upload as Custom Audiences for ad targeting.
5. **5 remaining Task-based dashboards** — Task report-type API rejection. Workaround: build via Lightning UI or use ActivityHistory with workaround.
6. **MLS RETS subscription** — applied for? Need to confirm.
7. **Twilio Advanced Opt-Out** — separate enablement (helps the v2 classifier reduce STOP false-negatives).
8. **Twilio multi-number sender pool (TARGET: this week)** — currently all inbound + outbound goes through `+19549534554`. Needs:
   - **Inbound routing**: provision 2-3 dedicated inbound numbers so different lead sources (PropertyLeads vs MotivatedSellers vs Constant Contact opt-in vs FB ads) route to different functions or get distinct branding.
   - **Outbound sender pool**: provision 6 additional outbound numbers, group them in a Twilio Messaging Service so the SDK auto-rotates. Defeats T-Mobile/AT&T throttling that kicks in around ~200 msgs/day from a single 10DLC number.
   - **A2P 10DLC compliance**: register Brand + Campaign in Twilio Console (takes 2-7 days for carrier approval). Without this, new numbers will be heavily filtered.
   - **Cost estimate**: 8 new numbers × ~$1.15/mo = ~$9/mo + per-message fees. Plus one-time 10DLC registration ($4 brand + $10 campaign).
   - **Implementation**: provision via API (`tools/twilio_provision_pool.py` to be written), update jb_sms.py to use Messaging Service SID instead of single From number.

---

## 🆘 Quick commands

```bash
# Health check all 5 Cloudflare Workers
for w in propertyleads-ppl motivatedsellers-ppl sendgrid-events railway-deploy-alerts cheaphomesfla-whatsapp-webhook; do
  curl -sS "https://${w}.cbfcalcio5.workers.dev/health" | python3 -m json.tool
done

# Check Railway service status (requires Railway CLI auth)
railway status

# Test Railway deploy webhook end-to-end
bash tools/test_railway_alert.sh

# Deploy code change to all Workers (manual; auto on push)
cd cloudflare/<worker> && wrangler deploy

# View latest cron run logs (Railway CLI)
railway logs --service jb_email

# Rollback Phase 6 if needed
bash tools/cutover_to_cloud.sh --rollback
```

---

## ✅ Done log (last 7 days summary)

- Day 1-2: Buyer_Target_Zips__c custom field + 4 buyers updated
- Day 3: below-market seed builder
- Day 4: Sell Score scoring engine + Workbook v2
- Day 5: Top 100 Buyers per Zip framework
- Day 6: FB Custom Audience hash helper
- Day 7: per-buyer email v2 wired into scraper
- Day 8: morning SOP doc + new-laptop checklist
- May 1: Sell Score v2 finalized
- May 2: Master plan PDF (18 pages)
- May 3 AM: Phase 1 (GitHub) + Phase 2 (Railway 8 services) + Phase 3 (5 CF Workers) + Phase 4 (secrets + 3 webhooks)
- May 3 PM (in progress): Phase 5 (Twilio v2) + Phase 6 (plist cutover) + smoke test + MBA bootstrap

---

*Update this file at the end of each work session. Keep it under 500 lines so it stays scannable.*
