# Monitoring Architecture

> Last updated: 2026-05-04
> If alerts stop firing for >24h, something with the alerting itself is broken — see "Self-monitoring" at the bottom.

---

## Layered alerting overview

The stack has 4 layers of monitoring. If layer N misses an issue, layer N+1 catches it.

| Layer | Latency to detection | Channel | Catches |
|---|---|---|---|
| 1. Inline scraper safeguards | <60s | SMS + email | Scraper crashes, scraper produces 0 deals 3 runs running, Graph token <14d to expiry |
| 2. Railway deploy webhook | <60s | SMS + email | Deploy build failures, deploy crashes |
| 3. Pipeline Health Monitor | <60 min | SMS + email | Worker auth failures, worker /health stale, SF/SendGrid/Twilio auth broken |
| 4. Daily KPI email | 24h | Email only | Volume drops, conversion-rate drops, list churn |

Plus reactive: humans noticing in Salesforce / inbox / phone.

---

## Layer 1 — Inline scraper safeguards

**Where:** `tools/scraper_safeguards.py` wraps `cheaphomesfla_scraper.py:main()`
**Triggers:** every scraper run
**Alerts on:**
- Any unhandled exception in main() — fires SMS+email with full traceback
- 3 consecutive runs producing 0 emails AND 0 parsed deals — fires once per stretch
- Graph refresh token > 75 days old — fires once until refreshed

**Output file:** `logs/scraper_heartbeat.json` (also read by Layer 3)

**To verify it's working:** run scraper manually with bad input:
```
GRAPH_CLIENT_ID="" python3 cheaphomesfla_scraper.py
# Should fire SMS+email about missing GRAPH_CLIENT_ID
```

---

## Layer 2 — Railway deploy webhook

**Where:** `cloudflare/railway-deploy-alerts/` worker, configured as Railway webhook
**Triggers:** Railway sends webhook on Deployment Failed / Crashed
**Alerts on:** any deploy that doesn't reach "running" state

**Webhook URL:** `https://railway-deploy-alerts.cbfcalcio5.workers.dev/?secret=<SHARED_SECRET>`
**Verified config:** Railway → Project Settings → Notifications → Webhooks

**To verify:** push a deliberately broken commit; expect SMS within 60s.

---

## Layer 3 — Pipeline Health Monitor

**Where:** `tools/pipeline_health_monitor.py`
**Schedule:** Railway service `pipeline_health_monitor` cron `0 * * * *` (every hour, top of hour UTC)

**Checks:**
1. All 5 Cloudflare Workers `/health` endpoints reachable (HTTP 200)
2. Each worker's required `bindings` are populated (e.g. WhatsApp worker `shared_secret: true`)
3. Each worker's freshness timestamp not too stale (varies 6-72h depending on worker; relaxed 4x outside business hours)
4. Scraper heartbeat file is fresh (<5h)
5. Scraper last run reported success
6. Salesforce auth works (live SOQL test)
7. SendGrid auth works (live profile fetch)
8. Twilio auth works (live account fetch)

**Dedup:** same exact failure text won't fire repeated alerts within 6 hours (state stored in `logs/monitor_alert_state.json`).

**To run manually:**
```
python3 tools/pipeline_health_monitor.py
```

**Adding a new check:** add a function in the Python file, call it from `main()`, append failures to the `failures` list. Dedup is automatic.

---

## Layer 4 — Daily KPI email

**Where:** `tools/daily_kpi_email.py`
**Schedule:** Railway service `daily_kpi` cron `30 13 * * *` (9:30 AM ET)
**Sends to:** `info@johnsonbuys.com`

**Reports:**
- # leads received yesterday (by source)
- # campaigns sent (email + SMS)
- Engagement: open rate, click rate, reply rate
- Top performers (best CTR sender, top zip etc.)
- Funnel anomalies

If you stop seeing this email at 9:30 AM ET, that's a Layer 3 alert that should have already fired (because daily_kpi service health is monitored).

---

## Self-monitoring

If you stopped getting alerts for >24h despite something being wrong:

1. Run health monitor manually — does it find issues?
2. Check Railway → service `pipeline_health_monitor` → Deployments — is it running?
3. Check Twilio → Messaging → Logs — are the alert SMS being sent?
4. Check SendGrid → Activity — are the alert emails being delivered?

If none of those show issues with alerting itself, the Pipeline Health Monitor service may have crashed silently. Restart it:
```
# Railway dashboard → service → Deployments → click latest → "Restart"
```

---

## Phone numbers + email addresses for alerts

- **SMS recipient:** `+13055759040` (Chris's iPhone)
- **Email recipient:** `info@johnsonbuys.com`
- **SMS sender:** `+19549534554` (Twilio JB number)

To change recipient, update env vars `ALERT_SMS_TO` / `ALERT_TO` on each worker + `pipeline_health_monitor` service. There are several so use a script.

---

## What is NOT monitored (gaps to close later)

- Per-buyer email engagement per send (handled by Layer 4 daily KPI)
- WhatsApp message volume drift (e.g., one specific group goes silent)
- Salesforce data quality (e.g., a custom field validation failing)
- Stripe payment failures (planned: stripe-events worker mirrors this pattern)
- Constant Contact send failures (planned: CC events worker mirrors this pattern)

These are queued in TODO.md.
