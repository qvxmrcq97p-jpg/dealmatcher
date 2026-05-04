# Troubleshooting Guide — "Something is wrong, where do I start?"

> **For Claude (any session, any Mac):** When the user reports something broken, vague, or "X stopped working," follow this decision tree before guessing.

---

## Step 1 — Run the health monitor (10 sec)

```
cd ~/dealmatcher && python3 tools/pipeline_health_monitor.py
```

This checks every layer at once. If it returns "ALL CHECKS PASSED" — the problem is somewhere unmonitored. If it lists issues, fix those first.

---

## Step 2 — Match symptom to runbook entry

```
grep -i "<error keyword>" docs/RUNBOOK.md
```

`docs/RUNBOOK.md` has paste-the-fix entries for every known failure mode. ALWAYS check it before diagnosing fresh.

---

## Step 3 — Identify which subsystem owns the problem

| Symptom | Likely subsystem | Read this doc |
|---|---|---|
| No new deals showing in SF | Scraper or WhatsApp pipeline | `docs/SCRAPER_GUIDE.md` |
| Email/SMS campaigns aren't firing | Railway cron services | `docs/CLOUD_DEPLOY.md` |
| New leads from website not in SF | Cloudflare Workers (lead capture) | `docs/RUNBOOK.md` SF auth section |
| Twilio inbound replies misrouted | Twilio Function /sms v2 | `docs/twilio_function_v2_deploy.md` |
| Anything slow/down across the stack | Run smoke test | `bash tools/smoke_test_all.sh` |
| Email open/click data missing in SF | SendGrid Event Webhook | `docs/RUNBOOK.md` SendGrid section |

---

## Step 4 — Check system state

| What | How |
|---|---|
| All Workers healthy | `bash tools/smoke_test_all.sh` |
| Scraper last run | `cat logs/scraper_heartbeat.json` |
| Scraper recent activity | `python3 tools/audit_scraper_accuracy.py` |
| Worker logs | Cloudflare dashboard → Workers → click worker → Logs |
| Railway logs | https://railway.com/dashboard → luminous-spontaneity → service → Logs |
| Salesforce inbound leads | SF → Reports → "Today's Leads" |
| SendGrid recent sends | https://app.sendgrid.com → Activity |
| Twilio recent SMS | https://console.twilio.com → Messaging → Logs |

---

## Step 5 — If still stuck, gather diagnostic and ask for help

```
echo "═══ DIAGNOSTIC SNAPSHOT ═══"
echo ""
echo "--- Health monitor ---"
python3 tools/pipeline_health_monitor.py
echo ""
echo "--- Scraper heartbeat ---"
cat logs/scraper_heartbeat.json 2>/dev/null || echo "(no heartbeat)"
echo ""
echo "--- Recent commits ---"
git log --oneline -10
echo ""
echo "--- Smoke test ---"
bash tools/smoke_test_all.sh 2>&1 | tail -30
```

Paste that block to Claude in chat.

---

## Documented past incidents (with fixes)

| Date | What broke | Fix |
|---|---|---|
| 2026-05-02 | Scraper Graph auth (silent failure for 2 days) | `tools/refresh_graph_token.py` + Railway env vars |
| 2026-05-04 | SF security token stale on 3 workers | `tools/update_sf_security_token.sh` |
| 2026-05-04 | WhatsApp worker SHARED_SECRET missing | `tools/fix_whatsapp_worker_secrets.sh` |
| 2026-05-04 | WhatsApp worker SENDGRID_API_KEY stale | Same script as above |
| 2026-05-04 | Test scrape false-negative bad-addr report | Fixed in `tools/test_scrape_recent.py` |
| 2026-05-04 | Health monitor Cloudflare 403 Forbidden | UA header added to monitor |

---

## Top-of-mind safeguards (running now)

- **Pipeline Health Monitor** — runs every hour on Railway service `pipeline_health_monitor`. SMS+email if any layer is broken. 6-hour dedup.
- **Scraper safeguards** — wrap main(): SMS+email on fatal exception, 3-zero-run alert, token expiry warning at day 75.
- **Railway deploy webhook** — SMS+email within 60s of any deploy failure.
- **System watchdog** — runs every 30 min as Railway service `watchdog`. Pings cloud_health_check.

If you stopped getting alerts for >24h, run the monitor manually to confirm it's still working:
```
python3 tools/pipeline_health_monitor.py
```

---

## "I'm at the MBA / a different machine and don't know what's going on"

1. `cd ~/dealmatcher && git pull` — get latest state
2. Read STATE.md "Done log" — what was the last meaningful change?
3. Check `git log --since="yesterday" --oneline` — what commits landed recently?
4. Run health monitor (Step 1 above)
5. If you find an error: search RUNBOOK.md → apply fix → if not there, document the fix after solving so next person finds it
