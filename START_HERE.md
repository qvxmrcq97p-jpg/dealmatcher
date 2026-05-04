# START HERE — for any Mac, any session, any time

> If you (Chris OR Claude) are sitting at a Mac and don't know what to do or what's going on, this is the entry point.

---

## For Chris (any Mac, any time)

### Sitting down to work
```
cd ~/dealmatcher && git pull
```
Then open Cowork → first message to Claude:

> **"Read STATE.md and TODO.md. What's the current state and what should I work on?"**

Claude reads both, knows everything, suggests what's most valuable to do next.

### Something's broken (alerts fired, things acting weird)
```
cd ~/dealmatcher && git pull
python3 tools/pipeline_health_monitor.py
```
Then open Cowork → first message:

> **"Read TROUBLESHOOTING.md and RUNBOOK.md. Pipeline monitor reports the issues below — diagnose and fix.

> [paste monitor output]"**

Claude matches errors to known fixes. If it's a new error, Claude diagnoses fresh AND adds a new RUNBOOK entry after fixing.

### Want to keep building (new feature, new automation)
> **"Read STATE.md and PRODUCT_STRATEGY.md. I want to build [feature]. Plan it and let's start."**

### Quick fact lookup
> **"Read STATE.md. Where does X live / how is Y configured?"**

---

## For Claude (any session pickup)

When the user gives you any of the prompts above, here's your reading order:

1. **`STATE.md`** — always first. Captures everything currently deployed, every cred location, every pending task.
2. **The relevant subsystem doc** depending on what they want:
   - Reporting an error → `docs/TROUBLESHOOTING.md` then `docs/RUNBOOK.md`
   - Working on the scraper → `docs/SCRAPER_GUIDE.md`
   - Working on the funnel build → `BUILD_PLAN.md`
   - Working on monitoring → `docs/MONITORING.md`
   - Adding/changing a Railway service → `docs/RAILWAY_SERVICES.md`
   - Strategic / sales / product question → `PRODUCT_STRATEGY.md`
   - Daily routine question → `DAILY_PLAYBOOK.md`
3. **`TODO.md`** — for current priorities

After reading, ask the user "what do you want to work on?" — don't recap. They have the docs themselves; you read them so you have the same context.

When you fix a new issue (one not in RUNBOOK already), add a new entry to `docs/RUNBOOK.md` BEFORE finishing. That's how the system gets smarter over time.

---

## File index — what every doc contains

| File | Purpose |
|---|---|
| `START_HERE.md` | This file — entry point |
| `STATE.md` | Current operational state — what's running where, every cred location |
| `TODO.md` | Active task list (cross-Mac, edit + push to share) |
| `PRODUCT_STRATEGY.md` | DealMatcher Pro pricing tiers, GTM, revenue scenarios |
| `BUILD_PLAN.md` | 3-hour funnel build spec for Tuesday |
| `DAILY_PLAYBOOK.md` | Chris's daily 30-min recurring routine + business model |
| `MOBILE_DEV.md` | Cross-Mac switching workflow |
| `docs/TROUBLESHOOTING.md` | Decision tree for "something is wrong" |
| `docs/RUNBOOK.md` | Paste-the-fix entries for every known error |
| `docs/MONITORING.md` | 4-layer alerting architecture |
| `docs/SCRAPER_GUIDE.md` | Deal scraper + parser + WhatsApp pipeline |
| `docs/RAILWAY_SERVICES.md` | Cron services + how to add new ones |
| `docs/CLOUD_DEPLOY.md` | Cloudflare Workers deploy details |
| `docs/twilio_function_v2_deploy.md` | Twilio Function /sms v2 deployment |

---

## tools/ index — what every script does

Run `ls ~/dealmatcher/tools/` to see them all. Key ones:

### Diagnostic
- `pipeline_health_monitor.py` — checks every layer, alerts on issues
- `audit_scraper_accuracy.py` — full scraper quality report
- `test_scrape_recent.py` — read-only scrape of recent emails
- `mba_readiness_audit.sh` — check this Mac's setup
- `smoke_test_all.sh` — end-to-end stack health check

### Recovery / fixes
- `update_sf_security_token.sh` — rotate SF token across all 3 workers + .env
- `fix_whatsapp_worker_secrets.sh` — fix WA worker auth issues
- `refresh_graph_token.py` — rotate Microsoft Graph token (every 90d)
- `replay_failed_leads.py` — recover Motivated Sellers leads after worker outage
- `restore_twilio_functions.py` — recover from broken Twilio deploy

### Operational
- `bootstrap_macbook.sh` — first-time setup on a new Mac
- `cutover_to_cloud.sh` — Mac plist enable/disable
- `deploy_twilio_sms.py` — deploy /sms v2 via API
- `cf_set_secrets.sh` — bulk-set Cloudflare worker secrets

### Build
- `finish_migration.sh` — runs the migration phases sequentially

If you don't see what you need, ask Claude: *"Read STATE.md. I want to do X — does a tool exist? If not, write one."*

---

## "I'm at MBA tomorrow. What do I do?"

```
cd ~/dealmatcher && git pull
```

If you've never set up the MBA before, run the bootstrap first:
```
mkdir -p ~/dealmatcher && cd ~/dealmatcher && \
curl -fsSL https://raw.githubusercontent.com/qvxmrcq97p-jpg/dealmatcher/main/tools/bootstrap_macbook.sh -o bootstrap_macbook.sh && \
bash bootstrap_macbook.sh
```

Then:
```
bash tools/mba_readiness_audit.sh   # confirms everything's set up
```

Then open Cowork → use one of the "first message" prompts at the top of this doc.

The MBA has access to literally everything Mac Mini has, except:
- The original `.graph_token_cache.bin` lives on Mac Mini (transfer via AirDrop if you ever need to refresh from MBA)
- Twilio / Wrangler CLI logins are per-machine (do `wrangler login` once on MBA)
