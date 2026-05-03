# Today's Checklist — Cloud Migration + Launch

**Total time:** ~3 hours for Phases 1-7. Phases 8-10 spread to Sunday-Monday.

**Single most-leverage item:** Phase 1 (GitHub push). Everything else is downstream.

When you finish a phase, send me "phase X done" — I'll confirm and tell you what to verify.

---

## 🚨 Quick wins (<5 min total — do first)

☐ Delete the test Lead `00QNt00000cHJ6nMAG` from Salesforce
   *(SF → Leads → search "TEST PROPERTY_LEADS_TEST" → Delete)*

☐ Paste worker URL into propertyleads.com webhook config + unpause delivery
   URL: `https://propertyleads-ppl-worker.cbfcalcio5.workers.dev`
   *(Until done, no real PPL leads flow.)*

---

## Phase 1 — GitHub (10 min) — UNBLOCKS EVERYTHING

☐ Create private repo at github.com/new → name `dealmatcher`
☐ `cd ~/dealmatcher && git init -b main && git add . && git commit -m "Initial commit"`
☐ `git remote add origin git@github.com:cbfcalcio5/dealmatcher.git`
☐ `git push -u origin main`
☐ Verify `.env.cheaphomesfla` is NOT in the pushed file list

---

## Phase 2 — Railway (~60 min)

☐ Sign up at railway.app (login with GitHub) — Hobby plan ($5/mo)
☐ New Project → Deploy from GitHub repo → select `dealmatcher`
☐ Rename auto-created service to `scraper`, set:
   - Start command: `python cheaphomesfla_scraper.py`
   - Cron: `0 14,18,22 * * *`
☐ Project sidebar → Shared Variables → paste all 16 env vars from `.env.cheaphomesfla`
   *(SF_*, SENDGRID_API_KEY, TWILIO_*, MS_*, GREENAPI_*, EMAIL_ADDRESS, ALERT_TO)*
☐ **Important:** add `CLOUD_MODE=true` (tells scripts not to write to ~/Desktop)
☐ Add `jb_email` service: `python jb/email_campaign.py` cron `0 12 * * 1-6`
☐ Add `jb_sms` service: `python jb/sms_campaign.py` cron `15 12 * * 1-6`
☐ Add `jb_followup` service: `python jb/followup.py` cron `0 12 * * *`
☐ Add `jb_digest` service: `python jb/digest.py` cron `30 12 * * *`
☐ Add `watchdog` service: `python tools/system_watchdog.py` cron `0 13 * * *`
☐ Add `cloud_health` service: `python tools/cloud_health_check.py` cron `0 13-1 * * 1-6`
☐ Add `daily_kpi` service: `python tools/daily_kpi_email.py` cron `15 13 * * 1-6`
☐ Manually trigger each of the 8 services once → verify logs are clean

---

## Phase 3 — Cloudflare Workers re-deploy (~20 min)

☐ propertyleads-worker:
```
cd ~/dealmatcher/cloudflare/propertyleads-worker
wrangler kv namespace create LAST_LEAD_AT
# paste returned id into wrangler.toml
wrangler deploy
```

☐ motivatedsellers-worker — same pattern with `LAST_LEAD_AT`

☐ whatsapp-worker — same pattern but with `LAST_MSG_AT`

☐ sendgrid-events:
```
cd ~/dealmatcher/cloudflare/sendgrid-events
wrangler kv namespace create LAST_EVENT_AT
# paste id → wrangler deploy
wrangler secret put SF_USERNAME       # info@johnsonbuys.com
wrangler secret put SF_PASSWORD
wrangler secret put SF_SECURITY_TOKEN
wrangler secret put SF_LOGIN_DOMAIN   # login
```

☐ railway-deploy-alerts:
```
cd ~/dealmatcher/cloudflare/railway-deploy-alerts
wrangler kv namespace create LAST_ALERT_AT
# paste id → wrangler deploy
openssl rand -hex 16   # save this secret
wrangler secret put SHARED_SECRET     # paste secret
wrangler secret put SENDGRID_API_KEY
wrangler secret put TWILIO_ACCOUNT_SID
wrangler secret put TWILIO_AUTH_TOKEN
wrangler secret put TWILIO_FROM       # +19549534554
wrangler secret put ALERT_SMS_TO      # +13055759040
wrangler secret put FROM_EMAIL        # info@johnsonbuys.com
wrangler secret put ALERT_TO          # info@johnsonbuys.com
```

☐ Test all 5 /health endpoints with curl — each returns `"ok": true`:
```
curl https://propertyleads-ppl-worker.cbfcalcio5.workers.dev/health
curl https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev/health
curl https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health
curl https://sendgrid-events.cbfcalcio5.workers.dev/health
curl https://railway-deploy-alerts.cbfcalcio5.workers.dev/health
```

---

## Phase 4 — Webhooks pointing AT the workers

☐ **SendGrid Event Webhook:**
   - Settings → Mail Settings → Event Webhook
   - URL: `https://sendgrid-events.cbfcalcio5.workers.dev/`
   - Events: Open, Click, Bounce, Spam Report, Unsubscribe, Group Unsubscribe, Dropped
   - Toggle ON → Save → Click "Test Your Integration"

☐ **Railway deploy webhook:**
   - Railway → Project → Settings → Notifications → Webhooks
   - URL: `https://railway-deploy-alerts.cbfcalcio5.workers.dev/?secret=YOUR_SECRET`
   - Triggers: Deploy Failed + Deploy Crashed
   - Save

☐ **GitHub Actions secrets** (for CF auto-deploy):
   - GitHub repo → Settings → Secrets → Actions → New repository secret
   - Name: `CLOUDFLARE_API_TOKEN` → create at dash.cloudflare.com/profile/api-tokens
   - Name: `CLOUDFLARE_ACCOUNT_ID` → from dash.cloudflare.com right sidebar

---

## Phase 5 — Twilio /sms v2 (~15 min)

☐ Open `~/dealmatcher/docs/twilio_function_v2_deploy.md`
☐ Follow steps 1-6 (paste sms_v2.js into Twilio Functions console)
☐ Test inbound SMS from your phone: text "STOP" to +19549534554
☐ Confirm: Lead status updates to "Take me off the list", auto-reply received

---

## Phase 6 — Mac cutover (5 min — ONLY after Phases 2-3 are green)

```
launchctl bootout gui/$(id -u)/com.johnsonbuys.emailcampaign 2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.smscampaign  2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.followup     2>/dev/null
launchctl bootout gui/$(id -u)/com.johnsonbuys.digest       2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.dealmatcher   2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.watchdog      2>/dev/null

mkdir -p ~/Library/LaunchAgents/_archived_2026-05-04
mv ~/Library/LaunchAgents/com.johnsonbuys.*.plist ~/Library/LaunchAgents/_archived_2026-05-04/ 2>/dev/null
mv ~/Library/LaunchAgents/com.cheaphomes.*.plist  ~/Library/LaunchAgents/_archived_2026-05-04/ 2>/dev/null
```

☐ Verify with: `launchctl list | grep -E "(johnsonbuys|cheaphomes)"` — should print nothing

---

## Phase 7 — Salesforce dashboards (~60 min — open `sf_dashboards_guide.pdf`)

☐ Pre-step: `python3 tools/sf_setup_helper.py` (creates 4 list views)

**Build the 5 high-priority dashboards first:**

☐ #1 Daily Lead Inflow
☐ #2 Active Pipeline by Status
☐ #4 Hot Buyers (CHF)
☐ #6 Today's Follow-ups
☐ #9 Revenue This Month

**Then the other 5 if you have time:**

☐ #3 Lead Source Performance
☐ #5 Daily Deal Activity
☐ #7 SMS + Email Campaign Health
☐ #8 Conversion Funnel
☐ #10 Buyer-Match Rate

☐ Pin all 10 to Home → Setup → User Interface → check "Home is the default tab"

---

## Phase 8 — Subscriptions (10 min of forms)

☐ **ATTOM Data** — attomdata.com → Get a Quote → distress indicators, Miami-Dade
☐ **TLO** — tlo.com → request demo, "skip-trace + property research"
☐ **healthchecks.io** — free tier signup → create check named "watchdog" → copy ping URL
   *(I'll wire this into watchdog when API key arrives)*
☐ **MLS RETS access** — miamirealtors.com → MLS access form (~$50-150/mo)

---

## Phase 9 — Constant Contact transition (Sunday)

☐ `python3 tools/build_investor_list.py` (generates full investor CSV from SF + senders.txt)
☐ Login to Constant Contact
☐ Create new email campaign → paste contents of `~/Desktop/cc_transition_email.html`
☐ Upload `~/Desktop/investor_contacts_clean.csv` as the recipient list
☐ Schedule send for Sunday morning

---

## Phase 10 — Marketing launches (Sunday-Monday)

☐ FB Ads Manager — build Custom Audiences (per `docs/audience_definitions.md`)
☐ FB Ads — build 1% Lookalikes
☐ FB Ads — apply **Special Ad Category = Housing** (legally required)
☐ FB Ads — save 3 seller-side variants as DRAFT (per `docs/ad_copy_seller_side.md`)
☐ FB Ads — save 3 buyer-side variants as DRAFT (per `docs/ad_copy_buyer_side.md`)
☐ Google Ads — Customer Match list upload (same hashed CSV)
☐ Google Ads — 3 search keyword groups + ads per `ad_copy_*.md`
☐ LinkedIn — manual outreach to top 5-10 LLC buyers per week (no spend)

---

## Notes for myself

- All credentials live in your `.env.cheaphomesfla` and 1Password — copy from there into Railway Shared Variables and Wrangler secrets
- After Phase 6, **neither Mac is required for production** — they're peer dev environments only
- Watchdog runs daily at 9 AM ET; daily KPI email at 9:15 AM ET. Silence after 9:30 AM = something's broken
- If a Phase 2 or 3 deploy errors, paste the error to me and I'll get you unstuck immediately
