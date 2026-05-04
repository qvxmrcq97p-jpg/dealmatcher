# DealMatcher Pro — Product Strategy

**Last updated:** 2026-05-03
**Status:** Strategy locked. Funnel build scheduled Tue May 5. First customer target: end of May.

> **One-liner:** We build and manage the entire customer-acquisition machine — landing page through CRM through ad spend — for operators in any industry. They bring the offering and the audience; we make every dollar of attention convert.

---

## The four-tier ladder

| Tier | Price | What client gets | What client does |
|---|---|---|---|
| **Free Investor Toolkit** | $0 | (CHF lead magnet only) Daily deals + comp tool + flip calc + rental calc | Sign up |
| **DIY Kit** | $499 one-time | Repo template + 90-min Loom walkthrough + Notion setup guide. The full machine, ready to install in their own infra. | Builds it themselves |
| **Landing Page Build** | $1,499 one-time + optional $499/mo A/B test | Mobile-optimized landing page + form-to-CRM wiring + 3 email templates + optional Stripe | Drives traffic, runs their own ads |
| **Done-For-You Managed** | $4,999 setup + $2,999/mo | Full machine: landing → CRM → email/SMS/Stripe → Q&A Agent → ad spend management → monthly KPI report | Almost nothing — bring offering + brand |

---

## What's IN the product (industry-agnostic)

| Component | Notes |
|---|---|
| Landing page (Swipe Pages or custom HTML) | High-converting, mobile-first |
| Email capture → CRM (SF / HubSpot / Pipedrive) | Auto-tagging, source attribution |
| Email drip sequences (SendGrid) | Welcome, nurture, re-engage |
| SMS infrastructure (Twilio + sms_v2 classifier) | Auto opt-out, hot-reply escalation, multi-number sender pool |
| Stripe checkout | One-time + recurring billing |
| Cloudflare Workers infra | Webhook receivers, alerts, KPI dashboards |
| **Deal Q&A Agent** (the differentiator) | AI middleman handling inbound product questions; routes to source if needed; replies polished |
| Monthly KPI dashboard + alerts | Auto-emailed to client; SMS on issues |
| **Ad-spend management** (Managed tier only) | FB + Google ads, weekly optimization, monthly reporting |
| Health monitoring + auto-recovery | Deploy alerts, watchdog, /health endpoints |

## What's OUT of the product (Chris's CHF/JB moat)

| Kept private | Why |
|---|---|
| CHF deal scraper + sources | Real estate IP |
| sell_score / buyer_score algorithms | Trained on Chris's data |
| PropertyRadar / ATTOM integrations | Real-estate-specific |
| Buyer-to-deal matching engine | Competitive advantage |
| Real estate sector judgment | That's the operator, not the SaaS |

---

## Go-to-market sequence

### Week of May 4 (this week)
- [ ] Mon: cloud migration goes live + observed
- [ ] Tue 1-4 PM: 3-hour funnel build (BUILD_PLAN.md)
- [ ] Wed: Twilio multi-number sender pool kickoff (10DLC paperwork)
- [ ] Wed: Record DIY Kit Loom walkthrough (60-90 min)
- [ ] Thu: Package DIY Kit zip; price/test Stripe products
- [ ] Fri: Soft launch — discrete CTA on cheaphomesfla.com footer ("Powered by DealMatcher Pro")

### Week of May 11
- [ ] Build Deal Q&A Agent v1 (6-8 hr)
- [ ] First social posts including subtle DealMatcher Pro mention
- [ ] Reach out to 5 CHF investor contacts who've expressed automation interest — pitch DIY Kit at $399 (early-bird discount)

### Weeks of May 18 + 25
- [ ] Refine pitch deck for Managed tier ($4,999 + $2,999/mo)
- [ ] First Managed install attempt with friendly customer (probably from JB seller-list referral)
- [ ] Document the install playbook (so install #2 takes half the time)

### June (month 2)
- [ ] Open public marketing on dealmatcherpro.com (or whatever domain)
- [ ] Run paid ads to landing page ($500 test budget)
- [ ] Target: 2-3 paying customers across all tiers

### July–September (months 3-5)
- [ ] Standard sales motion: weekly content + outbound + referrals from existing CHF customers
- [ ] Target: 1 Managed install/month + 5 DIY/Landing Page sales/month

---

## Revenue scenarios

Based on different sales velocity, all assuming infra cost ~$50-100/mo per client.

### Conservative (slow start)
- 1 DIY Kit/month × $499 = $499/mo
- 1 Landing Page/month × $1,499 = $1,499/mo
- 1 Managed install every 2 months × $4,999 setup, $2,999/mo recurring
- **Year 1 revenue: ~$60-80k**

### Base case (proven sales velocity)
- 5 DIY/month × $499 = $2,495/mo
- 2 Landing Pages/month × $1,499 = $2,998/mo
- 1 Managed/month × $4,999 setup + cumulative MRR ramp
- **Year 1 revenue: ~$180-250k**

### Aggressive (good content + paid ads working)
- 10 DIY/month × $499 = $4,990/mo
- 4 Landing Pages/month × $1,499 = $5,996/mo
- 2 Managed/month × $4,999 setup + cumulative MRR ramp
- **Year 1 revenue: ~$400-550k**

In all cases, this is **on top of** CHF + JB real-estate revenue.

---

## Why this is hard for competitors to replicate

1. **You eat your own dog food.** CHF + JB run on this stack. Every feature is battle-tested before it ships to a client.
2. **Compounding intelligence.** Every customer's data improves the system for ALL customers (same scoring/matching infra, just different copy).
3. **The Deal Q&A Agent is genuinely novel.** Most automation tools don't have AI middlemen handling product questions. This is the moat.
4. **Vertical case study from the start.** You don't need testimonials — your CHF deal flow IS the proof.
5. **Pricing ladder, not "let's chat".** Buyers can self-serve at lower tiers. Most consultants are stuck at "fill out this form to talk to sales."
6. **You understand operator psychology.** You ARE one. Most agencies sell automation by feature; you sell by outcome.

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Managed clients drift from infrastructure (SMS reply storm, SF auth expires, etc.) | Monthly health check + automated alerts (already built) |
| DIY Kit customers ask for too much support | Clear scope doc + "1 onboarding call included, $200/hr after" |
| First Managed client has too-rough requirements | First customer should be a friendly referral; document everything for install #2 |
| Real estate IP leakage in the kit | Audit kit contents before shipping; remove any CHF/JB-specific data sources |
| Twilio/SendGrid pricing shocks | Pass through usage above included threshold; document threshold clearly |
| Ad-spend management becomes time-sink | Cap initial Managed clients at 3-5 until process is well-defined |

---

## Key pre-launch decisions

- [ ] Domain choice: `dealmatcherpro.com` vs subdomain of `cheaphomesfla.com`?
- [ ] Brand colors / logo (or use placeholder for now and refine post-first-sale)
- [ ] Calendly link for kickoff calls (free)
- [ ] Loom Pro account ($12/mo) for high-quality walkthrough videos
- [ ] Notion workspace for the DIY Kit setup guide (free tier sufficient)
- [ ] Customer Support email — `support@dealmatcherpro.com` or `support@cheaphomesfla.com`?
- [ ] Refund policy on DIY Kit (recommend: 30-day money-back if they haven't installed it)

---

## North star metric

**MRR from Managed tier**, since that's the highest-margin recurring revenue.

Target trajectory:
- End of May: $0
- End of June: $3k MRR (1 customer)
- End of August: $9k MRR (3 customers)
- End of November: $18k MRR (6 customers)
- End of February 2027: $30k MRR (10 customers)

At $30k MRR + retained customers + DIY/Landing Page sales, this becomes a meaningful business worth significantly more than your current real-estate income alone.
