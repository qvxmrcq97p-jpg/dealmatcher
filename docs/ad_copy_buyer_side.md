# Ad Creative — Buyer Side (CheapHomes FLA)

Target: real estate investors and LLC buyers active in Miami-Dade.
Goal: drive signups at **`cheaphomesfla.com`** for off-market deal flow.
Position: exclusive direct-from-source deal pipeline (not another wholesaler).

---

## Audience targeting

### Facebook Custom Audience seed

- The Top 100 Buyers per Zip JSON (built by `tools/top_buyers_by_zip.py` once Comp Sales CSV lands)
- Below-market seed buyers (the savvy investors from `tools/build_below_market_seed.py`)
- Hashed via `tools/fb_audience_hash.py` → upload as Custom Audience
- 1% Lookalike for cold acquisition

### Demographic + interest (FB)

- Age: 28-65 (active investor age range)
- Geographic: South Florida (broader than seller side — investors travel)
- Interests: "Real estate investment", "Real estate investing", "BiggerPockets", "Real estate flipping", "Rental property", "BRRRR strategy", "Wholesale real estate", "Property flipping"
- Behaviors: "Real estate investors", "Small business owners" (proxy for LLC owners)
- Job titles: "Real estate investor", "Real estate developer"

### Google Customer Match

- Same hashed list as FB
- Search keywords below
- YouTube pre-roll on real estate investing channels (BiggerPockets podcast, Robert Kiyosaki, Pace Morby, etc.)

### LinkedIn (paid + organic)

- Job titles: Real Estate Investor, Real Estate Developer, Property Manager, Asset Manager, Acquisitions Manager, Principal, Managing Partner (in real estate)
- Companies: Match against your Top 100 Buyers per Zip LLC names

---

## FACEBOOK / INSTAGRAM ADS

Three variants tuned to different investor mindsets.

### Variant 1 — Off-market exclusivity

**Headline (40 chars):**
- A: `Off-market Miami deals — investor-only`
- B: `The Miami deals MLS doesn't show.`
- C: `Direct seller deals. No wholesaler markup.`

**Primary text (125 chars):**
> Tired of wholesalers padding ARVs and MLS deals everyone else sees? We get deals direct from motivated Miami sellers — daily. No middleman markup. Free to join. Investors only.

**CTA:** `Sign Up`
**Description:** `Daily deal flow, Miami direct sellers`

**Image direction:** Map of Miami-Dade with pins on properties. Subtitle overlay: "20+ off-market deals each week, sent directly to qualified investors."

**Landing:** `cheaphomesfla.com`

---

### Variant 2 — Speed / first-look angle

**Headline:**
- A: `See Miami deals 24h before anyone else.`
- B: `First-look access to Miami wholesale deals.`
- C: `Why pros get the best Miami flips first.`

**Primary text:**
> Top investors don't compete on Zillow. We send our buyer list off-market deals 24 hours before they hit any wholesaler email blast. Free to join — but we only accept serious investors.

**Description:** `First look, 24h before wholesaler blasts`
**CTA:** `Apply Now`

**Image direction:** Calendar / clock graphic showing "you" getting the deal at 8 AM and "competition" getting it at 8 AM the next day.

**Landing:** `cheaphomesfla.com?utm=first-look`

---

### Variant 3 — ARV-honest / data-driven angle

**Headline:**
- A: `Real ARVs. No wholesaler hype.`
- B: `Miami deals with verified comps.`
- C: `Investor-grade due diligence on every deal.`

**Primary text:**
> Most wholesale deal blasts inflate ARV by 15-20%. We attach real comp data to every deal we send — pulled from MD Property Appraiser, not someone's gut. You evaluate fairly. We get repeat buyers.

**Description:** `Verified comps. No padded numbers.`
**CTA:** `See How`

**Image direction:** Side-by-side comp data panel — wholesaler's claimed ARV crossed out, real ARV from public records highlighted. Honest investor-friendly aesthetic.

**Landing:** `cheaphomesfla.com?utm=verified-arv`

---

## INSTAGRAM CAROUSEL (uses your daily_deal_card_generator output)

The `tools/daily_deal_cards.py` already produces 1080×1080 branded cards. Use the daily output directly:

**Carousel structure (5 cards):**
1. Hook card: "Top 5 off-market Miami deals this week"
2-5. Four actual deal cards from today's scrape (auto-generated)
6. CTA card: "Get all 20-30 weekly deals direct → cheaphomesfla.com"

Post daily via Buffer (already in your stack). Ad-promote the best-performing organic posts.

---

## GOOGLE SEARCH ADS

### Keyword Group A — Off-market deal hunting

**Keywords:**
- `off market real estate miami`
- `wholesale houses miami`
- `miami investment property deals`
- `miami real estate investor lists`
- `cheap houses miami investors`
- `miami fixer upper deals`

**Ad copy variants:**

```
Variant A1
Headline 1: Off-Market Miami Deals — Direct
Headline 2: Investor-Only Buyer List
Headline 3: 20+ Deals Weekly, Free to Join
Description 1: Skip the wholesalers. Skip the markup. Direct seller deals across Miami-Dade. Verified comps included.
Description 2: For serious investors only. Apply free at cheaphomesfla.com.

Variant A2
Headline 1: Miami Off-Market Real Estate
Headline 2: BRRRR / Flip / Hold Deals
Headline 3: Get 24h Early Access
Description 1: We curate the best off-market deals across Miami-Dade and send them direct to qualified buyers — before they hit any blast list.
Description 2: Free to join. ARV verified. Real comps. cheaphomesfla.com
```

### Keyword Group B — BRRRR / Flip-specific

**Keywords:**
- `brrrr deals miami`
- `flip houses miami`
- `flip property miami`
- `miami buy and hold real estate`

**Ad copy:** strategy-aware

```
Variant B1
Headline 1: Miami BRRRR Deals — Pre-Vetted
Headline 2: Verified ARV. Real Numbers.
Headline 3: Investor List Open Now
Description 1: We pre-screen every Miami deal for BRRRR / Flip / Buy-and-Hold viability. Comps attached. Investor list — apply free.
Description 2: 20+ deals weekly. Direct from motivated sellers. cheaphomesfla.com
```

### Keyword Group C — "Investor list" searches

**Keywords:**
- `miami real estate investor list`
- `miami wholesale list signup`
- `cash buyer list miami`

**Ad copy:**

```
Variant C1
Headline 1: Miami Cash Buyer List — Direct
Headline 2: Real Deals, Verified Numbers
Headline 3: Free, Investor-Only Access
Description 1: Join the Miami investor list that gets direct-from-seller deals — not third-hand wholesaler blasts.
Description 2: Apply at cheaphomesfla.com. Approval fast. No spam.
```

---

## YOUTUBE PRE-ROLL — Investor channels

Run on:
- BiggerPockets podcast / videos
- Pace Morby
- Robert Kiyosaki
- Real estate flipper YouTubers
- Florida-specific real estate channels

### 30-sec script

> [0-5s] Hook: "If you're investing in Miami real estate and competing on Zillow, you're getting the leftovers."
> [5-12s] Pain: "Wholesalers pad ARVs. MLS deals everyone sees. Off-market lists you can't access."
> [12-22s] Solution: "We curate Miami's off-market deals — direct from motivated sellers — and send them to a qualified investor list. Verified comps. Real numbers. No middleman markup."
> [22-28s] Proof: "200+ active investors on our list. 20-30 deals every week."
> [28-30s] CTA: "Apply free at cheaphomesfla.com. Investor list only."

---

## LINKEDIN OUTREACH (paid InMail or organic DMs)

### Targeted audience

Use the unmatched outreach candidates from `tools/top_buyers_by_zip.py` (Top 100 per zip who AREN'T already CHF buyers).

### InMail / DM template

```
Subject: Off-market Miami deal flow — investor-to-investor

Hi [First Name],

Saw you closed a few properties in [Zip code / specific neighborhood]
recently — solid plays. I run an off-market deal aggregator focused on
Miami-Dade. We get 20-30 direct-from-seller deals every week, before any
wholesaler blast. Free to join — investor-only.

Worth a look? cheaphomesfla.com

Chris Johnson
Johnson Buys / CheapHomes FLA
```

Don't blast — pick 5-10 highest-LLC-deal-count buyers per week, personalize each one. Conversion is much higher.

---

## EMAIL OUTREACH (cold to LLC owners)

Once skip-trace data is in (BatchLeads or TLO when subscribed), the Top 100 outreach candidates each get a single personalized cold email:

```
Subject: Miami off-market deals — for [LLC name]

Hi [First Name],

I noticed [LLC Name] picked up [X properties] in [zip codes] this year.
We curate Miami-Dade off-market deal flow — direct from motivated sellers,
no wholesaler markup, 20-30 properties weekly.

If [LLC Name] would benefit from earlier deal access, our investor list
is free to join: cheaphomesfla.com

Worth a 5-minute call?

Chris Johnson
Johnson Buys / CheapHomes FLA
(305) 575-9040
```

One touch only. If they respond, work them. If not, no follow-up — respect the inbox.

---

## Tracking

- UTM: `?utm_source=fb&utm_campaign=chf-buyer-X&utm_content=variant-A1`
- Salesforce Contact `LeadSource__c` values:
  - `FB - Off-Market`
  - `FB - First Look`
  - `FB - Verified ARV`
  - `Google - Off-Market`
  - `Google - BRRRR`
  - `LinkedIn - DM`
  - `Email - Cold to LLC`
  - `Daily Deal Card Click` (organic IG)
  
- Track in dashboards: signups by source, signups → deal-match rate, deal-match → contract rate

---

## Budget plan (first 30 days)

| Channel | Daily | Monthly |
|---|---|---|
| FB ads (3 variants) | $30 | $900 |
| Google search (3 keyword groups) | $20 | $600 |
| YouTube pre-roll | $10 | $300 |
| Buffer (already in stack) | — | $15 |
| LinkedIn (manual outreach, no spend) | — | $0 |
| **Total month 1** | | **$1,815** |

Target month 1: 50-100 new CHF buyer signups. Cost per signup: $20-40. After warming up, drop to $10-25.

---

## Why this works (the strategic thesis)

You're not selling "deals" — you're selling **earlier access** and **honest math**. Both are scarce in the Miami investor market. Wholesalers blast garbage to lists of 10,000 people; sophisticated investors get burned and want a better source. CHF positions exactly there: smaller list, vetted deals, real comps.

The conversion path:
1. Investor sees ad → "actually different from generic wholesaler stuff"
2. Lands at cheaphomesfla.com → form fill (collected via Zapier/Cloudflare, lands as SF Contact)
3. Buyer Score computed (Hot/Warm/Cold)
4. Daily deal-match emails (per-buyer email v2 — already wired)
5. Buyer responds on Hot deal → convert to closed sale
6. Repeat customer over months

Mistakes to avoid:
- Don't add to lists they didn't opt in to (CAN-SPAM)
- Don't blast cold ads to existing buyers (it tells them they're not VIP)
- Don't show them deals they can't afford (filter by Buyer_Max_Budget__c)
