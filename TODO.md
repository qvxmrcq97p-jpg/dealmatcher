# dealmatcher — TODO

**Last updated:** 2026-05-03 (Sun)
**How to use:** Edit on either Mac, `git commit && git push`, the other Mac sees it on next `git pull`. Check off `[ ]` → `[x]` as things get done.

> When you sit down at any Mac, first command is `cd ~/dealmatcher && git pull`. Then read STATE.md + this file.

---

## TONIGHT (5–11 PM ET)

### Quick wins (5–10 min each)
- [ ] On MBA: finish homebrew install, then run `bash tools/bootstrap_macbook.sh`
- [ ] AirDrop `.env.cheaphomesfla` from Mac Mini → MBA → save in `~/dealmatcher/`
- [ ] On MBA: run `bash tools/mba_readiness_audit.sh` — should print all green
- [ ] Test sms_v2: text "STOP" to (954) 953-4554 from a non-SF phone → auto-reply, no iPhone forward
- [ ] Rotate Cloudflare API token (briefly appeared in chat earlier) → update GitHub secret `CLOUDFLARE_API_TOKEN`

### Data stack signups (apply, wait for approval emails)
- [ ] **PropertyRadar** — apply for API access at https://propertyradar.com
- [ ] **ATTOM Data** — apply at https://api.developer.attomdata.com (free tier exists)
- [ ] **TLO (TransUnion)** — apply for owner skip-tracing data
- [ ] **MLS RETS** — confirm if previously applied with local board; if not, start application
- [ ] **DataTree / FirstAm** — apply (alternative to ATTOM for sold-home records)

### Tonight's auto-watch
- [ ] **8:00 PM ET** — CheapHomesFLA scrape auto-fires from Railway. Open Railway dashboard → confirm fresh log. Phase 6's first cloud run.

### End-of-night
- [ ] Final smoke test: `bash tools/smoke_test_all.sh` — confirm all green
- [ ] `git commit && git push` whatever fixes/notes were captured

---

## TOMORROW MORNING (Mon May 4 — auto-watch)

- [ ] **8:00 AM ET** — Johnson Buys email campaign fires from Railway
- [ ] **8:15 AM ET** — Johnson Buys SMS campaign fires
- [ ] **9:00 AM ET** — Daily KPI email lands in inbox
- [ ] If any fail → Railway deploy webhook + system_watchdog SMS+email Chris within 1 min
- [ ] Mid-morning: review SF Lead inflow, opt-out counts, click-through

---

## THIS WEEK (Tue–Sun, 1–3 hr each block)

### Cloud + automation polish
- [ ] **Twilio multi-number sender pool** (target Wed/Thu so 10DLC clears by weekend)
  - Register A2P 10DLC Brand + Campaign in Twilio Console
  - Provision 6 outbound + 2 inbound numbers
  - Bundle into Messaging Service for auto-rotation
  - Update `jb_sms.py` to use Messaging Service SID
- [ ] **Twilio Advanced Opt-Out enablement** — separate Twilio Console toggle; helps sms_v2 classifier
- [ ] **5 Salesforce Task-based dashboards** — workaround the Task report-type API rejection by building in Lightning UI

### Funnel infrastructure (Tue 1–4 PM)
- [ ] **Run BUILD_PLAN.md 3-hour funnel build:**
  - Hour 1: Landing page + 4 free tools (comp lookup, flip calc, rental calc, daily deals)
  - Hour 2: Stripe products + 3 payment links + stripe-events Worker
  - Hour 3: Email sequences + smoke test
- [ ] Register domain: `dealmatcherpro.com` (or alternative if taken)
- [ ] Set up Calendly for kickoff calls (free tier)
- [ ] Set up Loom Pro account ($12/mo) for high-quality walkthroughs
- [ ] Customer support email: `support@dealmatcherpro.com` or alias to Chris

### Constant Contact transition (this week)
- [ ] **Constant Contact transition email** — write copy announcing migration
- [ ] Send transition email to existing CC list with tracking links
- [ ] Map open/click signals into SF for engagement-based segmentation

### Real estate data fundamentals (this week)
- [ ] **Day 5: Top 100 Buyers per Zip** — needs Comparable Sales CSV upload to populate. Framework already built.
- [ ] **FB Custom Audience setup** — hash helper exists. Still need: create FB Ad account + audience + upload hashed CSV

---

## 📊 DATA INFRASTRUCTURE (the next big leverage layer)

The whole stack gets dramatically smarter once we have these data sources wired up. Data unlocks better targeting, better products, better lead magnets.

### Historical sold-homes database
- [ ] **Pull every sold home in target counties (last 2-3 years)** — via ATTOM, DataTree, or FirstAm
  - Counties: Miami-Dade, Broward, Palm Beach, Hillsborough, Pinellas, Orange (start)
  - Fields per record: address, sold date, sold price, beds/baths/sqft, prior owner LLC, mortgage details, distance to nearest comp
  - Storage: SF custom object `Sold_Property__c` with 2M+ records expected
  - Refresh cadence: weekly delta pulls
- [ ] **Build `tools/import_sold_history.py`** — bulk-loads sold records into SF
- [ ] **Build comp-lookup view in SF** — given a property, shows 5 nearest sold comps with stats
- [ ] **Powers:** Comp Houses Lookup tool (free toolkit), sell_score_v3 accuracy, fix-and-flip calculator with real comps

### Top 100 investors per county (the proprietary investor index)
- [ ] **Build `tools/extract_top_investors.py`**
  - Source: Sold_Property__c records → group by buyer LLC name → rank by purchase volume last 12 months
  - Output: per-county top 100 list with: LLC name, # purchases, total spend, avg property value, common patterns (zip codes, beds, price range)
  - Cross-reference: TLO skip-trace to find LLC owner's actual phone/email/mailing address
- [ ] **Storage**: SF custom object `Active_Investor__c`, linked to Lead records by phone/email
- [ ] **Lead magnet product**: "Top 100 Investors in [County]" — gated PDF, requires email to download
  - Updates monthly automatically
  - Branded: "DealMatcher Pro Investor Index"
  - Each download = SF Lead with `Lead_Source__c = "Investor Index Download"`
- [ ] **Direct outreach product**: cold SMS/email to top investors with current matching deals
- [ ] **Powers:** buyer-side advertising, direct outreach campaigns, "we know who's buying in your area" pitch

### Distressed seller signals
- [ ] **Identify distress signals** in property records:
  - Tax delinquency (multi-year unpaid)
  - Code violations (multi-cited)
  - Foreclosure pre-filings (Notice of Default)
  - Probate filings
  - Divorce filings
  - Bankruptcy filings
- [ ] **Build `tools/score_distressed_sellers.py`** — combines signals into priority score
- [ ] **Output**: weekly batch of high-priority motivated-seller leads → SF
- [ ] **Refresh cadence**: weekly from county records (where API/scrape access exists)
- [ ] **Powers:** Johnson Buys outbound priority list, "we know your situation" SMS personalization

### Buyer behavior patterns
- [ ] **Track each buyer's pattern over time** in SF custom fields:
  - Avg price band, avg beds/baths, top 3 zip codes, response time, click-rate, conversion rate
- [ ] **Build `tools/buyer_pattern_extractor.py`** — runs nightly, updates each Lead's pattern fields
- [ ] **Output**: hyper-personalized email sends — only deals matching their exact pattern
- [ ] **Powers:** open/click rates 3x higher; reduces unsubscribes

---

## 🎯 TWO-SIDED ADVERTISING (use the data on both sides)

The data above isn't just for matching deals — it's for marketing to BOTH sides of every transaction.

### Seller-side advertising (motivated-seller acquisition for JB)
- [ ] **FB / Google ads** targeting sellers with retargeting based on:
  - Visited but didn't fill out form → retarget with "We have buyers paying $X in your area" (uses sold-comp data)
  - Long-time owner (>10 yr) in zip → "Your home value has gone up X% — see your offer"
  - Distressed signal hit → custom audience for direct mail
- [ ] **Direct mail campaigns** triggered by distressed signals (weekly batch)
- [ ] **Cold SMS** to filtered list (using multi-number pool to avoid throttling)
- [ ] **Lead magnet for sellers**: "What's my home worth in [Zip]?" — gated tool that captures email + sends 24-hr "your offer" email

### Buyer-side advertising (investor acquisition for CHF + DealMatcher Pro)
- [ ] **FB / Google ads** targeting investors with:
  - Top-100-Investor-Index download as lead magnet (high-intent)
  - Retargeting based on which deal types they've clicked
  - Lookalike audiences from existing best-buyer SF Leads
- [ ] **LinkedIn ads** targeting fund managers + active investors by job title + industry
- [ ] **Cold outreach to top-100 list** with current matching deals (via the data)
- [ ] **Lead magnet for investors**: "Top 100 Investors in [County]" + monthly market reports
- [ ] **Retargeting**: anyone who downloads a free tool sees ads for the next tier

### Ad-spend optimization (becomes Managed-tier value-add)
- [ ] **Build `tools/ad_spend_dashboard.py`** — pulls FB + Google ads spend daily, calcs CPL by source, surfaces drift
- [ ] **Build `tools/auto_pause_underperforming.py`** — nightly, pauses ad sets with CPL > 2× target
- [ ] **Storage**: SF custom object `Ad_Performance_Daily__c` with daily snapshots
- [ ] **Powers:** Managed-tier monthly KPI report; ad-spend management revenue

---

## 🚀 DEALMATCHER PRO LAUNCH (productized service rollout)

**See PRODUCT_STRATEGY.md for full pricing/scope/GTM.** This is the operational checklist:

### Pre-launch (this week)
- [ ] Domain registration: `dealmatcherpro.com` (or alternative)
- [ ] Calendly setup
- [ ] Loom Pro account
- [ ] Stripe products configured (4 SKUs: DIY Kit, Landing Page Build, Managed Setup, Managed Monthly)
- [ ] Customer-support email + auto-responder

### DIY Kit content (week of May 11)
- [ ] **Record 60-90 min Loom walkthrough** of the full system
- [ ] **Package repo template** — sanitize away CHF/JB-specific data sources first
- [ ] **Write Notion setup guide** — step-by-step for non-developers
- [ ] **Bundle into zip** with all the above + a README
- [ ] **Manual delivery flow** initially (we email it on Stripe webhook); automate later

### Landing Page Build offering (week of May 11)
- [ ] **Document the build process** so you can replicate consistently
- [ ] **Create 3 reusable copy templates** (real estate, B2B service, e-commerce)
- [ ] **Build intake questionnaire** for new clients (Typeform or Google Form)

### Managed offering (weeks of May 18+)
- [ ] **Document install playbook** — what to ask client, what to ship, what to test
- [ ] **First friendly customer**: probably referral from existing CHF/JB network
- [ ] **Monthly KPI report template** — auto-generated from their stack
- [ ] **Ad-spend management SOP** (after first managed client is live ~30 days)

### The differentiator: Deal Q&A Agent
- [ ] **Build v1 of `cloudflare/deal-qa-agent/` Worker**
  - Inbound triggers: SendGrid Inbound Parse, Twilio SMS, manual DM endpoint
  - Classifier: Claude Haiku (cheap + fast)
  - Drafter: Claude Sonnet (higher quality replies)
  - Storage: CF KV for thread state
  - Routes to original source via SF `Source_Contact_Phone__c` / `Source_Contact_Email__c`
  - Logs full Q&A thread to SF Activity
- [ ] **Build for CHF first** (proof of concept)
- [ ] **Use as showcase in DealMatcher Pro pitch deck** (week of May 18)

---

## NEXT 30 DAYS (medium projects)

- [ ] **Constant Contact → SendGrid migration** — move CC contacts + drip sequences into SG; cut over CC sends
- [ ] **Email engagement → SF profile enrichment** — build email-engagement-worker; auto-tag leads on open/click; auto-create Lead if not in SF
- [ ] **PropertyRadar/ATTOM enrichment + sell_score_v3** (after API keys land):
  - `tools/attom_enrich.py` — pull historical sold comps for each scraped deal
  - `tools/tlo_enrich.py` — owner skip-trace lookup
  - `tools/sell_score_v3.py` — predictive scoring with learned weights from retrospective training
- [ ] **Social media video pipeline** (~6-8 hr build):
  - `tools/social_pick_outliers.py` — query top 5 outlier deals from SF + ATTOM
  - `tools/social_render_video.py` — generates one video given a deal
  - `tools/social_render_caption.py` — caption + hashtags via Claude
  - Railway service `social_media_generator` daily 7 AM ET
  - Output to ~/Desktop/social_videos/today/

---

## FUTURE / NON-URGENT

- [ ] **Retrospective training pipeline** — `build_training_set.py` + `learn_seller_weights.py` from historical SF data
- [ ] **LLM-powered SMS classifier** — replace keyword matching in sms_v2 with Claude/Haiku for nuanced replies
- [ ] **Constant Contact CF Worker** — webhook receiver for CC events mirroring `sendgrid-events`, captures CC engagement during transition period
- [ ] **Sell-side SOPs documented** — capture the close-to-close playbook after first full cycle
- [ ] **Investor list segmentation** — fund / flipper / holder buckets with different deal flows
- [ ] **Multi-channel marketing pipeline** — coordinated FB + Google + YouTube + Mail + SMS
- [ ] **Public market reports** — branded "Florida Investor Index Q2 2026" PDF, drives PR / social shares
- [ ] **Referral program** — DIY Kit customers get 30% commission on Managed referrals
- [ ] **Affiliate dashboard** — track + payout commissions automatically

---

## ALWAYS / OPS DISCIPLINE (recurring habits)

- [ ] End of work session → update `STATE.md` (next session reads it)
- [ ] After code changes → always `git push` before switching Macs
- [ ] On arrival at a Mac → always `git pull` before starting work
- [ ] Keep credentials out of GitHub (`.env.*` is gitignored — don't override)
- [ ] Watch deploy alerts — Railway webhook → SMS in <1 min on build failure
- [ ] **Quarterly:** rotate API keys (Twilio, SendGrid, Cloudflare) for hygiene
- [ ] **Monthly:** review KPI trends, ad-spend efficiency, customer churn signals
- [ ] **Weekly:** update STATE.md, TODO.md, push everything

---

## Done log (recent)

- 2026-05-03 ✅ Phase 1: GitHub repo + code pushed
- 2026-05-03 ✅ Phase 2: Railway 8 cron services configured
- 2026-05-03 ✅ Phase 3: Cloudflare 5 Workers deployed
- 2026-05-03 ✅ Phase 4: Wrangler secrets + 3 webhooks (SendGrid, Railway, GitHub Actions)
- 2026-05-03 ✅ Phase 5: Twilio /sms v2 deployed (after recover-from-broken-build incident)
- 2026-05-03 ✅ Phase 6: 7 Mac launchd jobs disabled — local Mac fully out of the loop
- 2026-05-03 ✅ STATE.md + MOBILE_DEV.md + DAILY_PLAYBOOK.md + BUILD_PLAN.md + PRODUCT_STRATEGY.md + bootstrap_macbook.sh + mba_readiness_audit.sh
- 2026-05-03 ✅ Product strategy locked: 4 tiers (Free / DIY $499 / Landing Page $1,499 / Managed $4,999+$2,999mo); CHF/JB IP stays private; data infrastructure roadmap added
