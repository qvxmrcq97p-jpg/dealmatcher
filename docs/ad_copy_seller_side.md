# Ad Creative — Seller Side (Johnson Buys)

Target: motivated Miami-Dade homeowners in distress.
Goal: drive form fill at **`johnsonbuys.com/sell?town=X&problem=Y`** (or specific zip pages).
Compliance: every ad needs a clear "we are NOT real estate agents" disclosure to satisfy FB/Google policies for the home-buying category.

---

## Audience targeting (across channels)

### Facebook Custom Audience seed (after sell_score_v3 lands)

- Top 5,000 Sell Score 70+ homeowners in Miami-Dade
- Hashed CSV uploaded via `tools/fb_audience_hash.py` → Custom Audience
- 1% Lookalike off this seed → primary cold acquisition audience
- Exclude: anyone in your existing SF Lead `Status="Take me off the list"`, "Dead", "Doesn't own anymore"

### Demographic + interest layer (FB)

- Age: 35-75 (homeowners)
- Geographic: Miami-Dade County only (or specific zips for hyper-local creative)
- Behaviors: "Likely to move" + "Recently moved" excluded (we want *not yet* moved)
- Interests: "Foreclosure", "Tax preparation", "Divorce", "Probate" (where Meta allows — sometimes restricted), "Real estate investment trust"
- Life events: "Moved", "Divorced", "Recently inherited"

### Google Customer Match (Search + YouTube + Display)

- Same hashed CSV from your skip-traced motivated-seller list
- "We Buy Houses" intent keywords (see Google section below)
- Display retargeting: anyone who hit `johnsonbuys.com/sell` but didn't fill the form

---

## FACEBOOK / INSTAGRAM ADS

Three variants tuned to different emotional states. Run all three; let Meta optimize. Budget ~$50/day per variant for first 7 days, then double down on the winner.

### Variant 1 — Speed angle (foreclosure-imminent)

**Headline (40 chars max):**
- A: `Behind on your mortgage? Cash in 7 days.`
- B: `Stop the foreclosure. We pay cash.`
- C: `Need to sell your house fast in Miami?`

**Primary text (125 chars before truncation):**
> Facing foreclosure or just need to sell fast? We're local Miami buyers who pay cash, close in 7 days, and buy any condition. No agents, no fees, no repairs. Get a free no-obligation offer in 24 hours.

**Description (30 chars):**
- `Free cash offer in 24 hours`

**CTA button:** `Get Offer`

**Image direction:** Photo of a Miami residential street (NOT distressed/run-down — keep it dignified), Chris (or stock realtor) shaking hands with a homeowner. Avoid: foreclosure signs, distressed properties, anything that telegraphs "your house is bad."

**Landing page:** `johnsonbuys.com/sell` (or zip-specific dynamic page)

---

### Variant 2 — Inherited / probate angle

**Headline:**
- A: `Inherited a house in Miami you don't want?`
- B: `We buy inherited houses. Fast cash.`
- C: `Sell your inherited Miami home — no probate hassle.`

**Primary text:**
> Inheriting a property is overwhelming. We buy inherited Miami-Dade homes for cash, handle all the paperwork, and close around your timeline — even before probate is finalized. No repairs, no agent fees, no stress. Free offer in 24 hours.

**Description:** `Free offer, 24 hours, no probate hassle`

**CTA button:** `Get Cash Offer`

**Image direction:** Older Miami home (1950s-70s build), warm lighting, family-photo aesthetic. Subtitle: "We honor what these homes meant. We buy them fairly."

**Landing page:** `johnsonbuys.com/sell?problem=inherited`

---

### Variant 3 — As-is / repairs angle

**Headline:**
- A: `Don't fix it — we'll buy it as-is.`
- B: `House needs work? We pay cash anyway.`
- C: `Skip the repairs. Skip the agent. Get cash.`

**Primary text:**
> Need to sell but the house needs work? We buy any condition — termites, roof, mold, code violations. You don't fix a thing. Cash close in 7 days, $0 in repair costs out of your pocket. Free offer today.

**Description:** `Any condition. Any reason.`

**CTA button:** `Get Free Offer`

**Image direction:** Modest Miami home with visible "needs love" — peeling paint, old AC unit. Caption overlay: "We buy it just like this."

**Landing page:** `johnsonbuys.com/sell?problem=needs-repair`

---

### Carousel / video supplement

If running video, 15-second YouTube + Instagram Reels:
- 0-3 sec: HOOK — "Need to sell your Miami house fast?"
- 3-9 sec: VALUE — "Cash. Any condition. 7-day close."
- 9-13 sec: PROOF — "Helped 200+ Miami homeowners since 2022" (use real number)
- 13-15 sec: CTA — "Get your free offer at johnsonbuys.com/sell"

---

## GOOGLE SEARCH ADS

Three keyword groups + matching ad copy. Each group has 3 ad variants for A/B testing.

### Keyword Group A — High-intent "we buy houses" searches

**Keywords (exact + phrase match):**
- `we buy houses miami`
- `cash for my house miami`
- `sell my house fast miami`
- `cash home buyers miami dade`
- `quick house sale miami`
- `buy my house cash`

**Ad copy variants:**

```
Variant A1
Headline 1: We Buy Miami Houses — Cash
Headline 2: Free Offer in 24 Hours
Headline 3: Close in 7 Days, Any Condition
Description 1: Local Miami investor pays cash for any house. No agent fees. No repairs. Free no-obligation offer in 24 hours.
Description 2: Behind on payments? Inherited property? Code violations? We buy as-is.

Variant A2
Headline 1: Sell Your Miami House Fast
Headline 2: Cash Offer Today, Close This Week
Headline 3: Any Condition. Any Reason.
Description 1: Skip the agent. Skip the repairs. Local cash buyers since 2022. Free offer at no obligation.
Description 2: We've helped Miami homeowners through foreclosure, probate, divorce. Quick honest cash offers.

Variant A3
Headline 1: Need to Sell House in Miami?
Headline 2: We Pay Cash. No Fees. 7-Day Close.
Headline 3: Free Offer — No Obligation
Description 1: Tired of agents and showings? We're Miami investors who pay cash and close fast. Get your offer today.
Description 2: Selling because of foreclosure, repair costs, or relocation? We make it simple.
```

### Keyword Group B — Distress-specific searches

**Keywords:**
- `stop foreclosure miami`
- `sell house before foreclosure`
- `tax delinquent home sale`
- `inherited house sell fast`
- `probate property miami sale`

**Ad copy:** more empathetic, problem-aware

```
Variant B1
Headline 1: Avoid Foreclosure — We Pay Cash
Headline 2: Local Miami Help, No Judgment
Headline 3: Stop the Stress. Free Offer Today.
Description 1: We're local Miami investors who help homeowners avoid foreclosure. Cash, fast close, no shame.
Description 2: One quick call. Free no-obligation offer in 24 hours. We'll explain every step.
```

### Keyword Group C — "How to" searches

**Keywords:**
- `how to sell house fast miami`
- `cash buyer for my house`
- `sell house without agent miami`

**Ad copy:** educational + soft sell

```
Variant C1
Headline 1: How Cash House Sales Work
Headline 2: We Pay Cash, Close in 7 Days
Headline 3: Step-by-Step Free Guide
Description 1: Learn how Miami homeowners are skipping agents and selling for cash. Free guide + no-obligation offer.
Description 2: 1) Submit details 2) Get offer in 24h 3) Close in 7 days. No fees ever.
```

---

## YOUTUBE PRE-ROLL (15-sec + 30-sec)

Run after the FB campaigns are validated; YouTube reaches the same Lookalike via Google Customer Match.

### 15-sec — Awareness build

**Script:**
> [0-3s] Open: Chris on a Miami street, neighborhood visible
> "Tired of agents and showings to sell your house?"
> [3-9s] Cut to before/after: distressed home, then sold sign + handshake
> "We buy Miami houses for cash. Any condition. Close in seven days."
> [9-13s] On-screen text: 200+ Miami homeowners helped
> "Local. Honest. Fair."
> [13-15s] CTA: johnsonbuys.com/sell — free no-obligation offer

### 30-sec — Conversion focused

**Script:**
> [0-5s] Hook: Chris addresses camera. "If you need to sell your house fast in Miami, here's how it works."
> [5-12s] Walk through process: 1) Tell us about it 2) Free offer in 24h 3) Pick close date 4) Get cash
> [12-22s] Real testimonial (find one, even short) or Chris explaining what makes JB different — local, no agents, any condition, no repairs
> [22-27s] Soft proof: $X invested in Miami real estate, X houses bought
> [27-30s] CTA: Visit johnsonbuys.com/sell or call (305) 575-9040

---

## DIRECT MAIL (Yellow Letter format)

For the top 4,000 Sell-Score-70+ properties per month. Use `tools/fb_audience_hash.py` to also hash for digital, but mail is sent via Handwrytten/Lob/REI Print Mail.

### Letter copy (handwritten-style, 1 page max)

```
Hi [First Name],

I'm Chris, and I'm a local home buyer in Miami. I noticed your house at
[Property Address] and wanted to reach out personally.

If you've been thinking about selling — for any reason — I'd love to make
you a fair, no-obligation cash offer. I close in seven days, you don't
fix or clean anything, and there are no agent fees.

Would you have time for a quick 5-minute call this week? My number is
(305) 575-9040, or you can text me anytime.

If now's not the right time, no worries — I'll just delete this from
my list. Just text "STOP" and you'll never hear from me again.

Best,
Chris Johnson
Johnson Buys, LLC
(305) 575-9040
johnsonbuys.com
```

### Postcard (cheaper, 4,000 at $0.65 = $2,600)

**Front:** Photo of a Miami neighborhood + headline:
> **WE BUY MIAMI HOUSES FOR CASH**
> Any condition. 7-day close. No fees.

**Back:** Personalized:
> Hi [First Name], I noticed your home at [Property Address]. If you've ever considered selling, I can give you a fair cash offer in 24 hours. — Chris, (305) 575-9040, johnsonbuys.com

---

## Compliance & disclosures

Every ad MUST include in fine print or by clear context:
- "Not a real estate agent"
- "Cash offer subject to property inspection"
- Twilio A2P 10DLC compliance for any SMS-driven follow-up
- HONEST: never imply you'll pay full market value

For FB specifically:
- Use Special Ad Category: "Housing" (legally required for ads about real estate purchase)
- This restricts age/gender/location targeting somewhat — plan around it

---

## Rotation + budget plan

Week 1: $50/day × 3 FB variants × 7 days = $1,050 total ad spend
Week 1: $30/day × 3 Google search ad groups × 7 days = $630
Week 1: Direct mail 1,000 letters at $1.25 = $1,250
**Week 1 total: ~$2,930**

After week 1, kill bottom 30% of variants by CPL, double the winners.

Target: 3-5 form fills per $1,000 ad spend in weeks 2-4. If you're hitting that, scale proportionally.

---

## Tracking

- All FB ads should have UTM: `?utm_source=fb&utm_campaign=fb-cold-XXXX&utm_content=variant-A1`
- Google: auto-tagging on
- Mail: include a unique phone number per batch (Twilio sub-numbers — $1/mo each, justifies tracking which mail piece converted)
- Salesforce: add a `Marketing_Source__c` field on Lead, or use the existing `LeadSource` picklist with values: `FB - Speed`, `FB - Inherited`, `FB - As-Is`, `Google - Group A`, `Direct Mail - Yellow Letter`, etc.
