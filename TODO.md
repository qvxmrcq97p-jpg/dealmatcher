# dealmatcher — TODO

**Last updated:** 2026-05-03 (Sun)
**How to use:** Edit on either Mac, `git commit && git push`, the other Mac sees it on next `git pull`. Check off `[ ]` → `[x]` as things get done.

> When you sit down at any Mac, first command is `cd ~/dealmatcher && git pull`. Then read STATE.md + this file.

---

## ⚡ MONITORING + SAFEGUARDS NOW RUNNING

After today's cascade of silent failures (scraper auth, SF token, WA secrets), we built layered alerting:

| Layer | What | Where |
|---|---|---|
| 1 | Scraper safeguards (3 alert types) | `tools/scraper_safeguards.py` wraps `cheaphomesfla_scraper.py:main()` |
| 2 | Railway deploy alerts | already running |
| 3 | Pipeline Health Monitor (hourly) | `tools/pipeline_health_monitor.py` — needs Railway service deployment |
| 4 | Daily KPI email (9:30 AM ET) | already running |

**Read first when something breaks:** `docs/TROUBLESHOOTING.md` (decision tree) → `docs/RUNBOOK.md` (paste-the-fix).

---

## ⚠️ STILL TO DEPLOY (today)
- [ ] **Push everything to GitHub** — `cd ~/dealmatcher && git add -A && git commit -m "May 4 silent-failure remediation: 3-layer monitoring + scraper auth fix + SF token rotation + WA worker fix" && git push origin main`
- [ ] **Set Railway env vars on `dealmatcher` service:**
  - `GRAPH_CLIENT_ID = b2143511-d5e1-49d9-a121-8df37116b895`
  - `GRAPH_TENANT_ID = 8dd6dc0e-8291-438e-b64f-57dbd2854c38`
  - `GRAPH_TOKEN_CACHE_B64` = paste contents of `~/Desktop/graph_token_cache_b64.txt`
- [ ] **Deploy `pipeline_health_monitor` as Railway cron service** — see "Adding new Railway services" section below
- [ ] **Replay lost Motivated Sellers leads** — `python3 tools/replay_failed_leads.py --dry-run --days=14` then drop --dry-run if count is reasonable

## 📝 PARSER REFINEMENT (queued — quality not blocking)

Today's 12h test showed 205 clean deals from 17 emails (93% extraction rate). Quality issues to fix:
- [ ] sqft extraction systematically wrong — picks up tiny numbers (50, 56, 5) instead of ~1500. Likely confusing room sqft vs total or grabbing other digits.
- [ ] Some addresses include surrounding text: `25 mi... 1201 NW 21 St`. Should strip distance prefixes.
- [ ] Address `000 XXX Ne 129 St` — clearly a parser miss, low priority.
- [ ] Add unit tests for these specific failure cases in `tests/test_parser.py` before fixing.

---

## TODAY (Mon May 4 — migration deadline + restart of CC sends)

### URGENT (must run today)
- [ ] **8:00 AM** — Watch JB email auto-fire from Railway; verify in inbox + SF Lead `Last_Email_Sent__c`
- [ ] **8:15 AM** — Watch JB SMS auto-fire from Railway; verify on phone
- [ ] **9:00 AM** — Read the daily KPI email; confirm numbers look right
- [ ] **10:00 AM** — First CHF scrape of the day (Railway service `dealmatcher`); confirms scraper running
- [ ] **10:30 AM** — Run new daily-aggregate-email build (see below); generates "Today's 5 Outlier Deals" HTML
- [ ] **10:55 AM** — Paste HTML into Constant Contact, schedule send for 11:00 AM (or auto-send via CC API if upgraded)
- [ ] **11:00 AM** — CC blast goes out to existing list (first campaign restart since migration)
- [ ] Build 5 remaining SF Task-based dashboards via Lightning UI (~75 min total — can do during afternoon)
- [ ] Final smoke test + commit + push by EOD

### Build NEW: Daily 11 AM CC Aggregate Email
- [ ] Build `tools/build_daily_cc_email.py`:
  - Runs at 10:30 AM ET (Railway cron)
  - Queries SF for today's scraped deals (matched to Property/Lead records from the morning scraper run)
  - Picks top 5 outliers (using $/sqft once ATTOM data lands; until then, lowest list price relative to size)
  - Renders polished HTML email with: address, list price, photos, "why it's a deal" data card, link to landing page
  - **v1 (manual paste):** emails the HTML to Chris at info@cheaphomesfla.com — Chris pastes into CC composer
  - **v2 (auto-send):** if CC API plan, posts directly to CC and schedules send for 11 AM
- [ ] Add Railway cron service `daily_cc_email` with schedule `30 14 * * *` (10:30 AM ET in UTC)
- [ ] Decision needed: check Constant Contact plan tier — does it include API access? If not, decide whether to upgrade or stay on manual-paste flow

### Constant Contact plan check
- [ ] Log into CC, verify current plan tier (Lite / Standard / Premium)
- [ ] If on Lite or Standard: API access may be limited; manual-paste workflow is fine for first 2-3 weeks
- [ ] Decision: upgrade now ($35-80/mo) for full automation, OR plan migration to SendGrid (already on $0/free Email API tier with 100/day) within next 30 days
- [ ] **Recommended:** stay on current CC plan; use manual paste; commit to SG migration in late May to consolidate billing

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

## 🚀 PROPSTREAM INTEGRATION (priority data source — replaces ATTOM)

**Decision (May 4):** PropStream over ATTOM. One $199/mo subscription powers:
- Buyer-side: build out the investor database for daily blast targeting
- Seller-side: distressed seller leads for Johnson Buys outreach
- Enrichment: verify bed/bath/sqft on each scraped deal (replaces missing/wrong wholesaler data)
- Training data: historical sold home records → feed sell_score_v3 ML model

### This week — PropStream rollout
- [ ] **Sign up for PropStream 7-day free trial** at propstream.com
- [ ] Verify it covers FL counties at the depth needed (it does — but confirm in trial)
- [ ] Upgrade to **Premium ($199/mo)** for API access if trial proves out
- [ ] Get API key → save to `.env.cheaphomesfla` as `PROPSTREAM_API_KEY`
- [ ] Set Railway env var `PROPSTREAM_API_KEY` for cloud scripts

### Scripts to build (~6 hr work spread Tue–Thu)
- [ ] `tools/propstream_enrich.py` — per-deal enrichment after scraper run (verifies bed/bath/sqft, adds owner LLC, distress flags)
- [ ] `tools/propstream_investor_index.py` — pulls top 100 investors per FL county weekly; saves to SF as Contacts with `LeadSource = "PropStream Investor Index"`
- [ ] `tools/propstream_seller_leads.py` — pulls distressed-seller leads weekly (foreclosure, tax delinquent, probate, code violations) for Johnson Buys cold outreach
- [ ] `tools/build_investor_index_pdf.py` — generates monthly "Top 100 Investors in [County]" PDF lead magnet (CHF marketing asset)

### After integration runs for 30 days
- [ ] Pull historical sold-home data (each property + signals that preceded sale)
- [ ] Train `sell_score_v3` ML model on the data
- [ ] Output: per-property "likelihood to sell within 60 days at X% below market" score
- [ ] Use score to prioritize daily-blast deals + investor outreach

### Result by end of May 2026
- ~5,000-10,000 verified active investors auto-added to CC list (from PropStream)
- Daily emails go to a much larger, higher-quality database
- Each scraped deal has verified property data + distress flags
- sell_score_v3 starts producing predictive scores on day 30+ of training data

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

## 🌍 GEO-LINKED ARTICLES (NEW — SEO leverage for johnsonbuys.com)

**Concept:** every CC daily email's article links back to a geo-specific page on `johnsonbuys.com` (or related Johnson Buys domains). Drives traffic + signal to the existing 234-page SEO engine.

**Implementation pattern:**

Each article includes city/zip-specific data → article lives at `johnsonbuys.com/articles/<topic>/<city>` (or `/<county>`). Examples:

- "Insurance crisis" article → links to `johnsonbuys.com/articles/insurance/miami-dade`, `/articles/insurance/hillsborough`, etc. — 67 county pages × 14 articles = ~940 unique landing pages
- "STR markets softening" → only links to coastal counties (Miami-Dade, Broward, Pinellas)
- "Probate calendar" → links to per-county probate clerk pages

**Why this works:**
- Each CC email send drives 100-500 visitors to the same URL → strong RANK signal for that page
- Geo-specific pages outrank generic ones for "insurance Miami-Dade investor"
- 14 articles × 67 counties = 938 evergreen landing pages indexed
- Internal links from articles to other Johnson Buys content (fix-and-flip calc, etc.) compound authority

**Build steps:**
- [ ] Wire article URLs in `build_daily_cc_email.py` to use geo-specific destinations based on top deals' counties that day
- [ ] Build geo article template in johnsonbuys.com's SEO engine (probably 1 template, dynamic content per geo)
- [ ] Set canonical tags + sitemap.xml entries
- [ ] Add Schema.org markup (BlogPosting + LocalBusiness)
- [ ] Track per-page traffic + conversions in Google Analytics
- [ ] After 30 days, see which geo+article combos drive most form fills → scale those

**Time:** ~6-8 hr setup. Then auto-generated content from CC sends.

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
