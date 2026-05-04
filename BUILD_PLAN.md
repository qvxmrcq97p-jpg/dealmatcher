# 2-3 Hour Build — Full Funnel Launch

**Goal:** stand up the customer-facing funnel so social posts can convert into:
- Free toolkit signups (email captured into SF Lead)
- $499 DIY Kit purchases (Stripe one-time)
- **$1,499 Landing Page Build purchases** (Stripe one-time + optional $499/mo A/B test recurring)
- $4,999 + $2,999/mo Managed sign-ups (Stripe setup + subscription)

**Output:** one polished landing page + 4 free tools + 2 Stripe products + automated email sequences + SF tagging.

**Time:** 3 hours of focused work. Reuses 80% of your existing stack.

---

## Hour 1 — Landing Page + Free Toolkit

### 1A. Main landing page (Swipe Pages — you already have account)

URL: `cheaphomesfla.com/investors` (or new domain `dealmatcherpro.com` if you want separation)

Sections (top to bottom):
1. **Hero**: "Find off-market deals before anyone else" + 30-sec embedded video (use one of your social posts)
2. **Free toolkit CTA** (hero CTA): big email-gated button → "Get Free Investor Toolkit"
3. **Featured deals strip**: 3 thumbnails from yesterday's outliers (auto-populated from SF)
4. **Toolkit benefits** (4 cards):
   - Daily 5 outlier deals direct to inbox
   - Comp Houses Lookup Tool
   - Fix-and-Flip Profit Calculator
   - Rental Cash-Flow & Cap Rate Calculator
5. **Pricing tiers** (3 cards): Free / DIY $499 / Managed $4,999+$2,999
6. **Social proof**: testimonials from existing CHF investors (placeholder for now)
7. **FAQ** + footer

### 1B. Free Tools (each = a small Cloudflare Worker page)

Build these as 4 separate static-ish pages, each with email gate before access:

**Tool 1: Comp Houses Lookup**
- Input: address or ZIP
- Output: 5 recent sold comps within 1 mile, last 6 months (uses ATTOM API once that lands)
- Until ATTOM lands: pulls from Zillow/Redfin scrape (legal-gray; works as MVP)
- File: `cloudflare/comps-tool/index.html` + Worker

**Tool 2: Fix-and-Flip Calculator**
- Inputs: List price, ARV, repair budget, holding months, financing rate
- Outputs: Estimated profit, profit %, break-even ARV
- Pure JS calculator, no backend needed
- File: `cloudflare/flip-calc/index.html`

**Tool 3: Rental Cash-Flow Calculator**
- Inputs: Purchase price, down payment, rate, term, monthly rent, taxes, insurance, vacancy %, mgmt %, repairs %, capex %
- Outputs: Monthly cash flow, cap rate, cash-on-cash return, 30-yr equity build
- Pure JS calculator
- File: `cloudflare/rental-calc/index.html`

**Tool 4: Daily Deal Alerts**
- Just an email signup that lands them on the SendGrid daily-deals list
- Form: email + investor type (fund/flipper/holder/wholesaler) + target zips

All 4 tools route through one CF Worker `lead-capture-worker` that:
- Receives form submission
- Auto-creates SF Lead with tags (`Lead_Source__c = "Toolkit:CompsLookup"`, etc.)
- Adds to SendGrid contact list
- Sends welcome email with link to the chosen tool

**Time: 1 hour** (most of this is HTML + JS for the calculators; SF/SendGrid wiring is 15 min)

---

## Hour 2 — Stripe Checkout for Paid Tiers

### 2A. Stripe products

In Stripe Dashboard:
1. Create product: **"DealMatcher DIY Kit"**
   - One-time payment, $499
   - Description: "Clone of our full stack: scraper + SF CRM template + Twilio SMS + SendGrid emails. Includes 90-min Loom walkthrough + Notion setup guide."
2. Create product: **"DealMatcher Done-For-You — Setup"**
   - One-time payment, $4,999
   - Description: "We clone our full stack into your org + train your team."
3. Create product: **"DealMatcher Done-For-You — Monthly"**
   - Recurring, $2,999/month
   - Description: "Ongoing management: deal scraping, lead routing, SF maintenance, monthly KPI report."

### 2B. Stripe Checkout buttons on landing page

For each tier, embed a Stripe Checkout button (no custom backend needed):
- Stripe → Payment Links → generate one for each product
- Paste the link as the CTA href on the landing page

For the Managed tier, the user buys "Setup ($4,999)" first → success page → schedule kickoff call via Calendly link.
After setup, your kickoff call captures their card for the recurring subscription via Stripe Billing.

### 2C. Stripe webhook → CF Worker

New worker: `cloudflare/stripe-events/`
- Receives Stripe webhook events
- On `checkout.session.completed`:
  - If product = DIY Kit → email customer the kit zip + Loom link
  - If product = Managed Setup → email "schedule your kickoff" + Calendly
  - In both cases: tag SF Lead with `Customer_Tier__c` and `Stripe_Customer_ID__c`
- On `invoice.payment_succeeded` (monthly recurring):
  - Update SF Lead `Last_Payment_Date__c`
- On `invoice.payment_failed`:
  - SMS Chris + email
  - Tag SF Lead `Payment_Status__c = Past Due`

**Time: 1 hour** (Stripe Payment Links are no-code; webhook Worker is ~150 lines mirroring sendgrid-events)

---

## Hour 3 — Email Sequences + Polish + Test

### 3A. SendGrid email sequences

Three drip sequences, set up as SendGrid Marketing Automation flows OR as templated transactional sends triggered by lead-capture-worker:

**Sequence 1: Free Toolkit Welcome (immediate + 7 days)**
- Day 0: "Welcome — here's your toolkit access"
- Day 1: "Your first 5 deals" (real deals from yesterday's scrape)
- Day 3: "How [investor name] flipped a CHF deal for $87K profit"
- Day 7: "Want this entire system for yourself? DIY Kit walkthrough → $499"

**Sequence 2: DIY Kit Buyer Onboarding (immediate + 14 days)**
- Hour 0: "Welcome — your DIY Kit download" (zip + Loom)
- Day 1: "Setting up your CRM in 30 min" (link to Loom)
- Day 3: "Connecting your scraper to Salesforce"
- Day 7: "Stuck? Reply with screenshots, we'll help"
- Day 14: "Want to upgrade to Done-For-You? Schedule a call"

**Sequence 3: Managed Customer Welcome (immediate)**
- Hour 0: "Welcome — schedule your kickoff" (Calendly)
- Day 0 (after kickoff): "Your custom dashboard URL + first deal scrape running"
- Weekly: KPI digest

### 3B. Smoke test the full funnel

End-to-end:
1. Visit landing page in incognito
2. Submit free toolkit form → check SF for new Lead with correct tags
3. Receive welcome email within 2 min
4. Click DIY Kit Stripe link → use 4242 4242 4242 4242 test card → check SF tagged correctly + welcome email sent
5. Click Managed Setup → same flow
6. Trigger Stripe webhook test from Stripe Dashboard → verify SF + email fire

### 3C. Polish

- Test landing page on mobile (most social traffic)
- Verify all 4 free tools work end-to-end
- Confirm "DM @cheaphomesfla — link in bio" on socials points at the live URL
- Add Google Analytics or Plausible to landing page

**Time: 1 hour**

---

## File outputs

After this 3-hour build, you'll have:

```
~/dealmatcher/
├── cloudflare/
│   ├── lead-capture-worker/        ← captures all 4 toolkit forms
│   ├── stripe-events/              ← receives Stripe webhooks
│   ├── comps-tool/                 ← static page + worker
│   ├── flip-calc/                  ← static page (no backend)
│   └── rental-calc/                ← static page (no backend)
├── landing/
│   ├── index.html                  ← main /investors page (Swipe Pages export)
│   └── thanks.html                 ← post-purchase confirmation
├── templates/
│   ├── welcome_free.html           ← SendGrid template
│   ├── welcome_diy.html
│   └── welcome_managed.html
└── (existing files...)
```

Plus Stripe products + payment links + a SendGrid contact list per tier.

---

## What this DOES NOT include (separate projects)

- **Social media video pipeline** (~6-8 hr separate build) — see TODO.md
- **The DIY Kit content itself** (Loom walkthrough + zip) — record this Tue/Wed
- **Calendly setup** — 10 min, do during Hour 3
- **Domain + SSL** — assumes cheaphomesfla.com is fine; if you want a separate dealmatcherpro.com that's an extra step

---

## Suggested sequencing

If you have 3 contiguous hours later this week:
- Hour 1: Landing + free tools (front-end heavy, easier to focus)
- Break (15 min)
- Hour 2: Stripe + webhook (precise but fast)
- Break (15 min)
- Hour 3: Email sequences + smoke test

Total elapsed: ~3.5 hours including breaks. Single-session is doable but tiring.

---

## Recommended timing

Don't try to do this tonight. Tonight is migration polish + the 8 PM watch.

Best window: **Tuesday or Wednesday afternoon**. Reasons:
1. Migration is fully proven by Mon/Tue (no surprise outages)
2. PropertyRadar/ATTOM API approval may have landed → Comps Lookup can use real data
3. You'll have your first full day of cloud-only operation under the belt
4. Daily routine is dialed in by then

Pencil it in: **Tuesday May 5, 1:00–4:00 PM ET**.
