# dealmatcher — TODO

**Last updated:** 2026-05-03 (Sun)
**How to use:** Edit on either Mac, `git commit && git push`, the other Mac sees it on next `git pull`. Check off `[ ]` → `[x]` as things get done.

> When you sit down at any Mac, first command is `cd ~/dealmatcher && git pull`. Then read this file + STATE.md.

---

## TODAY (when back from break)

### Quick wins (5–10 min each)
- [ ] Push MBA readiness audit script — `cd ~/dealmatcher && git add -A && git commit -m "Add MBA readiness audit" && git push origin main`
- [ ] On MBA: finish homebrew install, then run `bash tools/bootstrap_macbook.sh`
- [ ] AirDrop `.env.cheaphomesfla` from Mac Mini → MBA → save in `~/dealmatcher/`
- [ ] On MBA: run `bash tools/mba_readiness_audit.sh` — should print all green
- [ ] Test sms_v2: text "STOP" to (954) 953-4554 from a non-SF phone → auto-reply, no iPhone forward
- [ ] Rotate Cloudflare API token (briefly appeared in chat earlier) → update GitHub secret `CLOUDFLARE_API_TOKEN`

### Data stack signups (apply now, wait for approval emails)
- [ ] **PropertyRadar** — apply for API access at https://propertyradar.com
- [ ] **ATTOM Data** — apply at https://api.developer.attomdata.com (free tier exists)
- [ ] **TLO (TransUnion)** — apply if you want owner skip-tracing data
- [ ] **MLS RETS** — confirm if previously applied with local board; if not, start application

### Tonight (auto-watch)
- [ ] **8:00 PM ET** — CheapHomesFLA scrape auto-fires from Railway. Open https://railway.com/dashboard, click luminous-spontaneity → dealmatcher service → confirm a fresh log entry. Phase 6 first cloud run.

---

## TOMORROW (Mon May 4 — auto-watch)

- [ ] **8:00 AM ET** — Johnson Buys email campaign fires from Railway
- [ ] **8:15 AM ET** — Johnson Buys SMS campaign fires
- [ ] **9:00 AM ET** — Daily KPI email lands in inbox
- [ ] If any fail → Railway deploy webhook + system_watchdog SMS+email you within 1 min

---

## THIS WEEK (1–3 hr each)

- [ ] **Twilio multi-number sender pool** (target Wed/Thu so 10DLC clears by weekend)
  - Register A2P 10DLC Brand + Campaign in Twilio Console
  - Provision 6 outbound + 2 inbound numbers
  - Bundle into Messaging Service for auto-rotation
  - Update `jb_sms.py` to use Messaging Service SID
- [ ] **Constant Contact transition email** — send to existing list announcing migration; track opens/clicks
- [ ] **5 Salesforce Task-based dashboards** — workaround the Task report-type API rejection by building in Lightning UI directly
- [ ] **Twilio Advanced Opt-Out enablement** — separate Twilio Console toggle; helps sms_v2 classifier
- [ ] **Day 5: Top 100 Buyers per Zip** — needs Comparable Sales CSV upload to populate. Framework already built.
- [ ] **FB Custom Audience** — hash helper exists. Still need: create FB Ad account + audience + upload hashed CSV

---

## NEXT 30 DAYS (medium projects)

- [ ] **Constant Contact → SendGrid migration** — move CC contacts + drip sequences into SG; cut over CC sends
- [ ] **Email engagement → SF profile enrichment** (the workflow Chris described May 3):
  - On open/click of a deal email: auto-tag SF Lead with deal's county/city/zip/price band as a preference signal
  - If the email recipient isn't in SF: auto-create a Lead with the inferred preference
  - Build as new CF Worker `email-engagement-worker` consuming SendGrid Event Webhook events
  - ~6 hr to build properly
- [ ] **PropertyRadar/ATTOM enrichment + sell_score_v3** — once API keys land:
  - `tools/attom_enrich.py` — pull historical sold comps for each scraped deal
  - `tools/tlo_enrich.py` — owner skip-trace lookup
  - `tools/sell_score_v3.py` — predictive scoring with learned weights from retrospective training
- [ ] **Multi-channel marketing pipeline** — FB + Google + YouTube + Mail + SMS coordinated send

---

## FUTURE / NON-URGENT

- [ ] **Retrospective training pipeline** — `build_training_set.py` + `learn_seller_weights.py` from historical SF data
- [ ] **LLM-powered SMS classifier** — replace keyword matching in sms_v2 with Claude/Haiku for nuanced replies
- [ ] **Constant Contact CF Worker** — webhook receiver for CC events mirroring `sendgrid-events`, captures CC engagement during transition period
- [ ] **Sell-side SOPs documented** — capture the close-to-close playbook after first full cycle
- [ ] **Investor list segmentation** — fund / flipper / holder buckets with different deal flows

---

## ALWAYS / OPS DISCIPLINE (recurring habits)

- [ ] End of work session → update `STATE.md` (next session reads it)
- [ ] After code changes → always `git push` before switching Macs
- [ ] On arrival at a Mac → always `git pull` before starting work
- [ ] Keep credentials out of GitHub (`.env.*` is gitignored — don't override)
- [ ] Watch deploy alerts — Railway webhook → SMS in <1 min on build failure
- [ ] **Quarterly:** rotate API keys (Twilio, SendGrid, Cloudflare) for hygiene

---

## Done log (recent)

- 2026-05-03 ✅ Phase 1: GitHub repo + code pushed
- 2026-05-03 ✅ Phase 2: Railway 8 cron services configured
- 2026-05-03 ✅ Phase 3: Cloudflare 5 Workers deployed
- 2026-05-03 ✅ Phase 4: Wrangler secrets + 3 webhooks (SendGrid, Railway, GitHub Actions)
- 2026-05-03 ✅ Phase 5: Twilio /sms v2 deployed (after recover-from-broken-build incident)
- 2026-05-03 ✅ Phase 6: 7 Mac launchd jobs disabled — local Mac fully out of the loop
- 2026-05-03 ✅ MOBILE_DEV.md + bootstrap_macbook.sh + STATE.md + TODO.md (this file) committed
