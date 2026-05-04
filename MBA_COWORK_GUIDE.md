# Cowork on MBA — Quick Reference Guide

> **Drop this file anywhere accessible (Desktop, Notes, paper). Use it as your cheat-sheet for any Cowork session on MBA.**

---

## Universal first message (paste into Cowork to start ANY session)

```
Read START_HERE.md and STATE.md. Then read TODO.md.
What's the current state and what should I work on?
```

That loads everything — current state, pending tasks, business model, monitoring status. Claude reads it all in seconds and tells you the most valuable next step.

---

## Scraper-specific first message

```
Read START_HERE.md, STATE.md, and docs/SCRAPER_GUIDE.md.
I want to work on the deal scraper (email + WhatsApp).
```

That signals scraper work, so Claude has full context.

---

## Common scraper tasks — paste any of these into Cowork on MBA

### Run a test scrape (no side effects, just inspection)

```
Run a test scrape of the last 12 hours.
Show me totals: email vs WhatsApp, deals parsed, parse failures.
```

### Source breakdown by wholesaler / by WA group

```
Show me which wholesalers and WhatsApp groups produced the most deals today.
```

### Health check the entire pipeline

```
Run tools/pipeline_health_monitor.py and tell me what's broken.
```

### Add a new wholesaler

```
Add `deals@newwholesaler.com` to senders.txt and push to GitHub.
```

### Fix a parser issue

```
The scraper is parsing addresses incorrectly — example: "25 mi... 1234 Main St".
Read parser.py and tests/test_parser.py, add a test case showing the desired clean output,
fix the parser, run tests, and push.
```

### Why isn't a specific wholesaler being captured?

```
Wholesaler `john@xyz.com` sends me deals but they're not in the scraper output.
Run a 24h test scrape with --show-misses, look for his emails in the misses list,
and add him to senders.txt if found.
```

### Check today's deal-buyer matches in Salesforce

```
Query Salesforce for Tasks created today where Subject starts with "Deal:".
Group by buyer Contact and show me the top 10.
```

### Refresh the Microsoft Graph token (every ~85 days, you'll get an SMS warning)

```
Run tools/refresh_graph_token.py and walk me through the device flow.
After completing it, update Railway env var GRAPH_TOKEN_CACHE_B64 with the new value.
```

---

## Workflow when something breaks

When you see an alert SMS/email saying something's broken:

```
Read docs/TROUBLESHOOTING.md and docs/RUNBOOK.md.
[paste the alert text here]
Diagnose and fix.
```

If the error matches a RUNBOOK entry, Claude pastes the fix. If not, Claude diagnoses fresh and ALSO adds a new RUNBOOK entry so the next person finds it.

---

## Workflow for adding new features

```
Read PRODUCT_STRATEGY.md and BUILD_PLAN.md.
I want to build [the feature you want].
Plan it out, then implement, then push.
```

---

## File locations on MBA (~/dealmatcher/)

| Need | File |
|---|---|
| Universal entry point | `START_HERE.md` |
| Current state | `STATE.md` |
| Active task list | `TODO.md` |
| Business strategy | `PRODUCT_STRATEGY.md` |
| Daily routine | `DAILY_PLAYBOOK.md` |
| Funnel build plan | `BUILD_PLAN.md` |
| Cross-Mac workflow | `MOBILE_DEV.md` |
| Scraper subsystem | `docs/SCRAPER_GUIDE.md` |
| Decision tree for "broken" | `docs/TROUBLESHOOTING.md` |
| Paste-the-fix for errors | `docs/RUNBOOK.md` |
| Alerting architecture | `docs/MONITORING.md` |
| Railway services + add new | `docs/RAILWAY_SERVICES.md` |
| Twilio SMS deploy | `docs/twilio_function_v2_deploy.md` |

## Tools on MBA (~/dealmatcher/tools/)

| Need | Script |
|---|---|
| Live status snapshot | `bash status` (or `python3 tools/mba_status_dashboard.py`) |
| Pipeline health (alerts on issues) | `python3 tools/pipeline_health_monitor.py` |
| Smoke test all services | `bash tools/smoke_test_all.sh` |
| Test scrape (no side effects) | `python3 tools/test_scrape_recent.py --hours=12` |
| Per-source breakdown | `python3 tools/scrape_summary_by_source.py --hours=12` |
| Audit scraper output | `python3 tools/audit_scraper_accuracy.py` |
| Refresh Graph token | `python3 tools/refresh_graph_token.py` |
| Rotate SF security token (all 5 places) | `bash tools/update_sf_security_token.sh` |
| Replay lost SF leads | `python3 tools/replay_failed_leads.py` |
| Set Railway Graph env vars | `bash tools/set_railway_graph_vars.sh` |
| First-time MBA setup | `bash tools/bootstrap_macbook.sh` |
| Verify MBA is set up | `bash tools/mba_readiness_audit.sh` |

---

## Sync across Macs (every Cowork session)

**At start:**
```
cd ~/dealmatcher && git pull
```

**Before switching Macs:**
```
git push origin main
```

**Anything you want the OTHER Mac to see has to go through git.** Don't AirDrop changes — push them.

The only file that's NOT synced via git is `.env.cheaphomesfla` (gitignored for security). That you AirDrop one time, then leave alone.

---

## Cloud services (open in browser, don't need MBA terminal)

| Service | URL |
|---|---|
| Salesforce | https://johnsonshomes2.my.salesforce.com |
| Railway dashboard | https://railway.com/dashboard |
| Cloudflare dashboard | https://dash.cloudflare.com |
| Twilio Console | https://console.twilio.com |
| SendGrid | https://app.sendgrid.com |
| Constant Contact | https://app.constantcontact.com |
| Green-API (WhatsApp) | https://console.green-api.com |
| FB Ads Manager | https://business.facebook.com/adsmanager |
| Google Ads | https://ads.google.com |
| GitHub repo | https://github.com/qvxmrcq97p-jpg/dealmatcher |

---

## Phone numbers + email addresses

- Chris's iPhone (alerts SMS to): `+1 (305) 575-9040`
- Twilio JB business number: `+1 (954) 953-4554`
- Email recipient (alerts + summaries): `info@johnsonbuys.com`

---

## When in doubt

```
Read STATE.md. I'm trying to do X. Tell me what tools/docs to use.
```

Claude points you at the right script or doc. You execute. Done.
