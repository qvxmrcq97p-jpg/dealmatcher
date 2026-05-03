# Audience Definitions — copy-paste ready for Ads Manager

Pre-written audience definitions for both sides. Saturday's job is just clicking through Ads Manager and pasting these in.

---

## SELLER-SIDE Audiences (Johnson Buys → motivated sellers)

### 1. Custom Audience: Sell Score 70+ Miami-Dade Homeowners

**Source:** `~/dealmatcher/data/sell_score_YYYYMMDD.csv` (top 5,000 properties)
**Hash + format:** `python3 tools/fb_audience_hash.py --in data/sell_score_YYYYMMDD.csv --out data/fb_seller_score70_hashed.csv`
**Required:** Sell Score v3 has run (waits on parcels.csv + retrospective training)

**Audience name:** `Seller — Sell Score 70+ (Miami-Dade)`
**Source:** Customer File
**Match keys:** Email + Phone + ZIP + First Name + Last Name (whatever fields are populated)
**Description:** "Top 5,000 motivated-seller signal scores from public records analysis. Foreclosure / tax-delinquent / probate / out-of-state / high equity. Refresh weekly."

### 2. 1% Lookalike off the Sell Score Custom Audience

**Audience name:** `Seller — 1% Lookalike of Sell Score 70+ (FL)`
**Source audience:** `Seller — Sell Score 70+ (Miami-Dade)` (above)
**Country:** United States
**Audience size:** 1% (smaller = more similar; broaden to 5% later if you need volume)
**Geo restriction:** Florida only

### 3. Below-Market Buyer Lookalike (savvy buyers — sourcing seller-side targeting)

**Source:** `~/dealmatcher/data/below_market_seed.csv` (built from `tools/build_below_market_seed.py`)
**Audience name:** `Buyer — Below-Market Cash Investors (Miami-Dade)`
**Why it's also useful for seller side:** these are people who BOUGHT at deep discounts in the last 24 months. Modeling their "before-purchase" demographics tells us about people likely to *sell* into a similar deal — i.e., motivated sellers in the same zips/types.

### 4. Geographic / demographic layer

When pairing with any custom audience above:
- **Location:** Miami-Dade County (or specific zips: 33125, 33127, 33135, 33142, 33147, 33150, 33161, 33168, 33150, 33169, 33034)
- **Age:** 35-75
- **Special Ad Category:** Housing (LEGALLY REQUIRED for home-buying ads)
- **Exclude:** anyone in your existing CHF buyer Custom Audience (they're not the seller target)

---

## BUYER-SIDE Audiences (CheapHomesFLA → investors)

### 1. Custom Audience: Top 100 Buyers per Zip (Miami-Dade)

**Source:** `~/dealmatcher/data/top_buyers_by_zip.json` (built by `tools/top_buyers_by_zip.py`)
**Required:** parcels.csv + comparable_sales.csv downloaded; tool run with `--no-sf-update` first time

**Audience name:** `Buyer — Top 100 Active Investors per Zip (MD)`
**Source:** Customer File (extract names + emails + phones from the JSON; the outreach CSV at `data/top_buyers_outreach_candidates.csv` is what we hash)
**Hash + format:** `python3 tools/fb_audience_hash.py --in data/top_buyers_outreach_candidates.csv --out data/fb_top_buyers_hashed.csv`

### 2. Custom Audience: Existing CHF Buyer Pipeline

**Source:** Salesforce Contacts where `LeadSource = 'CheapHomesFLA_LandingPage'`
**Use:** EXCLUSION audience — when running cold acquisition ads to find NEW investors, exclude the ones you already have

**Audience name:** `Buyer — CHF Existing Pipeline (EXCLUDE)`
**Source:** Customer File or Salesforce sync (use Lightning Sync for FB Custom Audiences)

### 3. 1% Lookalike — Top 100 Active Investors

**Audience name:** `Buyer — 1% LAL of Top Investors (FL)`
**Source audience:** `Buyer — Top 100 Active Investors per Zip (MD)`
**Country:** United States
**Audience size:** 1%
**Geo:** Florida (consider expanding to FL + GA + TX if list is volume-thin)

### 4. Interest + Behavior Layer for Cold Acquisition

When pairing with the lookalike above, layer in:
- **Interests:** Real estate investing, BiggerPockets, Real estate flipping, Rental property, BRRRR strategy, Real estate investment trust, Property management
- **Behaviors:** Real estate investors, Small business owners
- **Geographic:** South Florida (Miami-Dade + Broward + Palm Beach)

---

## Google Customer Match

### Seller side
- **Customer list:** `data/fb_seller_score70_hashed.csv` (same hashed file works for Google)
- **Upload at:** Google Ads → Audience Manager → Audiences → Customer list → Upload
- **Use cases:**
  - Search remarketing to people who searched "we buy houses miami" AND match the list
  - YouTube pre-roll to the matched users
  - Display retargeting after they hit `johnsonbuys.com/sell`

### Buyer side
- **Customer list:** `data/fb_top_buyers_hashed.csv`
- **Use cases:**
  - YouTube pre-roll on BiggerPockets / Pace Morby / real estate channels
  - Search remarketing on investor-intent keywords
  - Display retargeting after they hit `cheaphomesfla.com`

---

## LinkedIn Audiences (buyer side only)

### Job-title-based

LinkedIn → Campaign Manager → Matched Audiences → New Audience:
- **Job Titles:**
  - Real Estate Investor
  - Real Estate Developer
  - Acquisitions Manager
  - Asset Manager
  - Principal (with company including "real estate", "investments", "capital", "holdings", "properties")
  - Managing Partner (real estate firms)
- **Geographic:** Florida (Miami-Dade + Broward + Palm Beach)
- **Company size:** 1-50 (small/medium investors, not REITs)

### Company-name-based (more precise)

If you want to target the LLCs from your `top_buyers_by_zip.json`:
1. Export the LLC names to a CSV (one per row)
2. LinkedIn → Audiences → Company List → Upload
3. Run InMail / Sponsored Content campaigns to employees of those companies

---

## Direct Mail Audiences

### Seller side — Yellow Letter list

**Source:** `~/dealmatcher/data/sell_score_YYYYMMDD.csv` filter score ≥ 70
**Volume:** 4,000/month
**Provider options:** Handwrytten ($4-6/letter, premium), REI Print Mail ($1.25-1.50/letter, mid), or Lob (varies)
**Best provider for budget:** REI Print Mail or Lob → yellow letter format → $5,000/mo at 4k pieces

### Buyer side — LinkedIn-only or no-mail

Don't direct-mail investors — they hate it. Stick to digital + LinkedIn for buyer side.

---

## Quick checklist before launching ads Saturday

**Seller side:**
- [ ] Have `sell_score_YYYYMMDD.csv` from Sell Score v3 run
- [ ] Hash it with `tools/fb_audience_hash.py`
- [ ] Upload to FB Ads → Custom Audience
- [ ] Build 1% Lookalike off the upload
- [ ] Apply Special Ad Category = Housing
- [ ] Exclude existing JB Lead pipeline (anyone in `Status="Take me off the list"` etc.)
- [ ] Create 3 ad variants from `ad_copy_seller_side.md`
- [ ] Set budget $50/day per variant
- [ ] Save as DRAFT — review tomorrow before activating

**Buyer side:**
- [ ] Have `top_buyers_by_zip.json` and `outreach_candidates.csv` from `tools/top_buyers_by_zip.py` run
- [ ] Hash with `tools/fb_audience_hash.py`
- [ ] Upload to FB Ads → Custom Audience
- [ ] Build 1% Lookalike
- [ ] Exclude existing CHF Contacts
- [ ] Create 3 ad variants from `ad_copy_buyer_side.md`
- [ ] Set budget $30/day per variant
- [ ] Save as DRAFT

**Google:**
- [ ] Customer Match list uploaded (same hashed CSV)
- [ ] 3 search keyword groups + ads from each `ad_copy_*.md`
- [ ] YouTube pre-roll set with Customer Match audience
- [ ] DRAFT saved

**Activation order (when ready to launch — Sun May 4 or after trip):**
1. Activate FB seller-side ads first (highest income channel)
2. Then Google seller-side
3. Then FB buyer-side
4. Then YouTube + LinkedIn buyer-side

Stage launches 2-3 days apart so you can debug each before the next.
