# Daily Playbook — Chris's "Soup-to-Nuts" Daily Routine

**Goal:** your daily JOB is posting 5 deals to socials, responding to inbound leads, and overseeing the cloud stack. Everything else is automated.

---

## The Business Model (single source of truth)

You operate three offerings funneled from one piece of daily content:

| Tier | Price | Delivery | Target |
|---|---|---|---|
| **Free Investor Toolkit** (lead magnet) | $0 | Email-gated access to: daily deal alerts • comp-houses lookup tool • fix-and-flip calculator • rental cash-flow calculator | Investors building their stack |
| **DIY Kit** | $499 one-time | Zip + Loom walkthrough + repo template of the customer-acquisition machine (landing → CRM → email/SMS automation → Stripe). **Does NOT include real-estate deal-finding IP.** | Tech-comfortable folks in any industry who'll build their own funnel |
| **Landing Page Build** | $1,499 one-time (+ optional $499/mo A/B test) | High-converting landing page + email capture wired to their existing CRM + 3 email templates + optional Stripe checkout | Anyone in any industry who needs a converting funnel but not the full backend |
| **Done-For-You Managed** | $4,999 setup + $2,999/mo | Full customer-acquisition machine (landing + CRM + email/SMS + Stripe + Q&A agent + KPI dashboard) + **ongoing ad-spend management** (FB/Google) + monthly reporting. Industry-agnostic — they bring the offering. | Operators in any industry who want their entire lead/customer pipeline run for them |

All three CTAs sit on **one landing page**. Social posts drive traffic to that page.

---

## Daily Routine — Mon–Sat (~30 min total)

### 7:00 AM — Wake to alerts
- Daily KPI email lands at 9 AM
- Railway deploy alerts SMS you if anything broke overnight
- system_watchdog SMSes you if cron jobs failed

### 7:15 AM — SMS arrives: "5 videos ready in social_videos/today/"
*(Once the social pipeline is built — for now, see "Manual Mode" below)*

### 7:30 AM — Coffee + review
- Open `~/Desktop/social_videos/today/` on phone via iCloud
- Quick scroll through the 5 videos to make sure they look right
- If one looks weird → swap with #6 (script generates 6, picks 5)

### 8:00 AM — Post to socials (~25 min)
- **TikTok:** open app → post each video, paste caption from `caption.txt`
- **Instagram Reels:** same flow — both have native schedulers if you want to batch
- 5 min per video × 5 videos = 25 min
- Each video / caption ends with: "DM us @cheaphomesfla — link in bio"
- Link in bio → your **landing page**

### 8:30 AM — Check inbound
- New email leads (free tier signups)
- New Stripe purchases (kit + managed)
- New DMs on Instagram / TikTok
- New SF Leads from PPL Workers (motivated sellers)

### 9:00 AM — 30-min admin
- Respond to DMs (templated responses for common Qs in `~/dealmatcher/templates/`)
- Reply to any "STOP" or opt-out requests if Twilio/SF didn't auto-handle
- Schedule kickoff calls for new managed clients (Calendly link)

### 9:30 AM – 11:00 AM — Deep work
- Build/improve the stack (whatever's at the top of TODO.md)
- This is where YOU iterate, not where you do tasks the system can do for you

### After 11 AM
- Meetings, calls, family, life. You've done the daily job.
- Cron continues running in cloud regardless of where you are.

---

## Manual Mode (until social video pipeline is built — this week)

The video pipeline is ~6-8 hr to build properly. Until it lands, your morning has a 15-min "pick + screenshot" step instead of just reviewing pre-built videos:

### 7:30 AM — Manual pick (15 min)
1. `cd ~/dealmatcher && bash tools/show_outliers.py` (we'll write this)
   - Prints: top 10 outlier deals from yesterday's scrape
   - Each row: address, list price, comp avg, % below market
2. You eyeball top 5, pick the most photogenic
3. For each pick:
   - Open the listing on the source site
   - Screenshot 3-4 photos to your phone via AirDrop
   - Note the address + numbers in a sticky for caption

### 8:00 AM — Post (25 min)
- TikTok / IG Reels native: pick 4-5 photos, apply Ken Burns built-in
- Add text overlays: "List: $245K • Comp avg: $385K • Profit: $100K"
- Caption: "[Address area] just listed below market. Comparable sales averaging $385K. DM for details. Link in bio for free deal alerts."
- Post

This works *today*. The automated pipeline just removes the manual screenshot/edit step.

---

## Weekly Rhythm

| Day | Focus |
|---|---|
| **Mon** | Review last week's KPIs (KPI email aggregates Sat–Sun); plan week |
| **Tue–Thu** | Daily routine + stack improvements / new features |
| **Fri** | Daily routine + invoicing managed clients + KPI snapshot |
| **Sat** | Daily routine (deals don't stop on weekends) |
| **Sun** | Off / strategy / personal |

---

## Failure Handling

If something breaks during the day, the SMS alerts tell you within 60s. Common scenarios:

| Symptom | First check |
|---|---|
| Railway deploy SMS | Open Railway dashboard → Deployments tab → last failed log |
| No KPI email at 9 AM | `bash tools/smoke_test_all.sh` → see what's red |
| SMS replies stop coming | Twilio Console → Phone Numbers → +1 (954) 953-4554 → check Messaging webhook still points at /sms |
| Salesforce auth fails | Reset security token in SF user settings, update `.env.cheaphomesfla`, push secret to all 4 Workers |
| Social video pipeline missing files | `ls ~/Desktop/social_videos/` — if empty, the cron failed; manual mode fallback |

Everything has a fix path documented in `docs/RUNBOOK.md`.

---

## Personal Goal

The whole point of this setup is: **you are NOT the bottleneck for deal flow, lead gen, or campaign sends.** Those run in the cloud whether you're at a desk, on a beach, or asleep.

Your job is the irreducibly human stuff: relationships with investors, picking the deals that catch your eye, closing managed-client engagements. Everything else gets compounding work via automation while you sleep.
