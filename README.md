# dealmatcher

Production home for **Johnson Buys** (motivated-seller acquisition) +
**CheapHomesFLA** (off-market investor deal flow). Single repo. Single source of truth.

```
GitHub (this repo)
   ├──→ Railway      runs Python crons (scraper, JB email/SMS, watchdog, KPI, health)
   └──→ Cloudflare   runs always-on webhooks (PPL providers, WA, SendGrid events, Railway alerts)
```

Both Mac mini and MacBook Air are interchangeable dev environments. Either one `git clone`s the repo, opens Cowork, edits, pushes — Railway + Cloudflare auto-deploy within ~2 minutes. Neither machine needs to be on for production to run.

---

## First-time setup on a new machine

```bash
git clone git@github.com:cbfcalcio5/dealmatcher.git ~/dealmatcher
cd ~/dealmatcher

# Python deps
python3 -m pip install -r requirements.txt

# Local creds (copy from your password manager — NEVER commit this file)
cp .env.example .env.cheaphomesfla
$EDITOR .env.cheaphomesfla            # paste real values

# CLIs you'll want occasionally
brew install gh                       # GitHub CLI
npm install -g wrangler               # Cloudflare deploys
npm install -g @railway/cli           # Railway log tailing
```

---

## Layout

```
~/dealmatcher/
├── README.md                  ← you are here
├── .env.example               ← template; copy to .env.cheaphomesfla locally
├── .gitignore                 ← keeps secrets, logs, state out of git
├── requirements.txt           ← Railway auto-installs from this
├── railway.json + Procfile    ← Railway service config
│
├── cheaphomesfla_scraper.py   ← main scraper (3×/day Railway cron)
├── parser.py                  ← address + email + WA parser
│
├── jb/                        ← Johnson Buys Python crons
│   ├── email_campaign.py      ← 8 AM Mon-Sat — Day 1/7/21/45 drip
│   ├── sms_campaign.py        ← 8:15 AM Mon-Sat — master multi-campaign
│   ├── followup.py            ← 8 AM daily — status-driven SMS
│   ├── digest.py              ← 8:30 AM daily — overdue-task digest
│   └── sms_inbound.py         ← legacy Flask handler (Twilio Fn replacing)
│
├── tools/                     ← shared utilities + analytics
│   ├── system_watchdog.py     ← 9 AM daily — health alerts
│   ├── cloud_health_check.py  ← hourly — CF + PPL + SG monitoring
│   ├── daily_kpi_email.py     ← 9:15 AM daily — green-day summary
│   ├── sell_score.py          ← motivated-seller scorer (Phase 1)
│   ├── buyer_score.py         ← CHF buyer tier scorer
│   ├── top_buyers_by_zip.py   ← top 100 buyers per zip
│   ├── build_*_pdf.py         ← regenerate the docs/*.pdf files
│   └── …                      (see docs/master_plan.pdf for the full index)
│
├── cloudflare/                ← all webhook receivers (auto-deployed via .github/workflows)
│   ├── propertyleads-worker/      ← Property Leads PPL → SF
│   ├── motivatedsellers-worker/   ← Motivated Sellers PPL → SF
│   ├── whatsapp-worker/           ← Green-API WA → email forward
│   ├── sendgrid-events/           ← Email open/click → SF Tasks
│   └── railway-deploy-alerts/     ← Failed Railway deploy → SMS + email
│
├── twilio-functions/          ← Twilio Functions source (deployed via Twilio console)
│   └── sms_v2.js              ← smart inbound classifier
│
├── docs/
│   ├── master_plan.pdf        ← 20-page operating manual (regen via tools/)
│   ├── automation_map.pdf     ← every cron + alert + gap (regen via tools/)
│   ├── sf_dashboards_guide.pdf← 17-page click-by-click for 10 SF dashboards
│   ├── user_actions.pdf       ← 14-page checklist of clicks YOU need to do
│   ├── CLOUD_DEPLOY.md        ← Railway deploy step-by-step
│   ├── USER_ACTIONS.md        ← markdown source of user_actions.pdf
│   ├── SF_DASHBOARDS.md       ← markdown source of sf_dashboards_guide.pdf
│   ├── twilio_function_v2_deploy.md
│   ├── ad_copy_seller_side.md + ad_copy_buyer_side.md
│   ├── audience_definitions.md
│   ├── cc_transition_email.html
│   ├── day8_morning_routine_sop.md
│   └── new_laptop_setup_checklist.md
│
├── tests/                     ← pytest suite (parser, classifier, sell-score)
├── plists/                    ← macOS launchd plists (Mac fallback only)
├── data/                      ← state files, scoring outputs (gitignore'd)
└── .github/workflows/         ← CF Worker auto-deploy
```

---

## Daily workflow on either Mac

```bash
cd ~/dealmatcher
git pull                        # always start fresh
# ... open Cowork, ask it to fix a thing ...
git add -A && git commit -m "fix: <what>"
git push                        # ~2 min later, Railway + CF redeploy
```

Watch deploys land: https://railway.app and https://github.com/cbfcalcio5/dealmatcher/actions.

---

## When something breaks

| Symptom | Look at | Fix |
|---|---|---|
| No emails sent today | Railway → `jb_email` → Logs | `git revert HEAD && git push` to roll back |
| No SMS sent today | Railway → `jb_sms` → Logs | Same |
| No leads from PPL | `cloud_health` Logs OR `curl <worker>/health` | Check provider's webhook URL config |
| Watchdog hasn't emailed | healthchecks.io | Watchdog itself broken — check Railway |
| SF Tasks not appearing for opens | `sendgrid-events` Worker logs | SG webhook URL? Secret matches? |
| Build broke after a push | Railway → Deployments → red entry → Logs | Roll back via "Redeploy previous green deploy" |
| Railway deploy alert SMS | Check the SMS for service name | Open Railway → that service → Logs |

---

## Quick commands

```bash
# Run the full test suite locally
python3 -m pytest tests/

# Regenerate any of the PDFs after editing the markdown
python3 tools/build_master_plan_pdf.py
python3 tools/build_automation_map_pdf.py
python3 tools/build_sf_dashboards_pdf.py
python3 tools/build_user_actions_pdf.py

# Pull fresh investor list from SF + senders.txt
python3 tools/build_investor_list.py

# Manual scraper run (debug)
python3 cheaphomesfla_scraper.py

# Manual cloud-health check
python3 tools/cloud_health_check.py --report

# Manual KPI email (prints to stdout)
python3 tools/daily_kpi_email.py --print

# Tail Railway logs from your laptop
railway logs --service scraper --tail
```

---

## Source of truth

If this README disagrees with code, **the code wins**. If two docs disagree, the most recently modified wins. If you're confused, run the script with `--help` or `--dry-run` first.

Canonical operating doc: `docs/master_plan.pdf` (regenerate any time with `python3 tools/build_master_plan_pdf.py`).
