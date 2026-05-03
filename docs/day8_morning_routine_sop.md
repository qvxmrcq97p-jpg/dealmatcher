# Daily morning routine — Johnson Buys + CheapHomesFLA

**Print this. Pin it inside your laptop bag. Coffee + 30 minutes = the whole machine stays healthy.**

---

## Day-of routine (30 min, anywhere with cell signal)

### Step 1 — Open laptop, sync iCloud (1 min)
- Wait 30 seconds for `~/dealmatcher` to finish syncing from Mac mini
- If on iPhone hotspot, enable Personal Hotspot on phone first

### Step 2 — System preflight (3 min)
```
cd ~/dealmatcher && python3 tools/morning_preflight.py
```

What to look for in the output:

- ✓ **All 6 launchd jobs loaded** — emailcampaign, smscampaign, followup, digest, webhook, cheaphomes.dealmatcher
- ✓ **JB email campaign log** modified within last 24h
- ✓ **JB SMS campaign log** modified within last 24h
- ✓ **CHF scraper log** modified within last 8h (last fired 10/14/18 schedule)
- ✓ **JB Tasks created today** > 0
- ✓ **CHF deal Tasks today** > 0 if scraper has fired

If anything is ✗, read the issue and triage:
- Stale JB email log → `launchctl start com.johnsonbuys.emailcampaign`, then re-run preflight
- Stale CHF scraper → `launchctl start com.cheaphomes.dealmatcher`
- Job not loaded → `launchctl load ~/Library/LaunchAgents/<name>.plist`

### Step 3 — Open Salesforce, work the call list (15 min)
1. Home tab → see your 3 pinned dashboards (CHF Buyer Pipeline, Deal Pipeline, Seller Lead Pipeline)
2. Open list view: **"Sellers — Hot Score (call today)"** (Lead object)
3. Make 3-5 phone calls to the highest Seller_Score__c leads — these are your morning's deals
4. Open list view: **"CHF — Hot Buyers (call today)"** (Contact object) — text/call any Hot tier buyer about top STEAL deals scraped overnight

### Step 4 — Reply to inbounds (5 min, then sporadic throughout day)
- Inbound form fills → Salesforce mobile app push notification
- Inbound SMS → forwarded to your iPhone via Twilio Function
- Inbound call → forwarded to your iPhone with whisper ("Johnson Buys lead, NAME, property at ADDRESS, calling from PHONE. Press any key to accept.")

### Step 5 — Sanity-check ad performance (5 min)
- Open Facebook Ads Manager → check yesterday's spend, leads delivered
- Open Google Ads → check yesterday's spend, conversions
- If a campaign is dramatically over/under target, pause and investigate; otherwise leave alone

### Step 6 — Done (1 min)
- Close laptop. Phone is the rest of your day.

---

## Throughout the day (sporadic, 5-15 min as needed)

- **Inbound form fills**: reply within 5 minutes (SF mobile alerts you)
- **Inbound Twilio SMS**: respond from phone (forwarded conversation)
- **Inbound calls**: take when they ring (iPhone)
- **Hot Buyer matches**: when CH-DEAL-* fires, you get push from Cowork — phone-call the Hot tier buyers personally on top deals

---

## Weekly Monday routine (1 hour)

1. Run morning preflight as usual
2. Open `~/dealmatcher/sample_data/v1_vs_v2_summary.txt` — verify scraper still producing clean output
3. Review last week's KPIs in Salesforce dashboards:
   - Total form fills by source
   - CHF deal-match Tasks per day trend
   - JB campaign sends per day trend
4. Top 10 STEAL deals of the week — note which closed vs which slipped
5. Sell Score auto-refreshes via cron — verify it ran (check `data/sell_score_*.csv` mtime)
6. Reupload top-scored Lead list to Facebook Custom Audience (refreshes weekly)
7. 30-min ad creative iteration: A/B test a new headline or landing page copy

---

## Emergency contacts

| Who | Contact | What for |
|---|---|---|
| Hard money lender | (lender 1 number) | When a deal needs cash close in 7 days |
| Hard money lender (backup) | (lender 2 number) | If lender 1 is unavailable |
| Title company | (title number) | Closing logistics |
| RE attorney | (attorney number) | Contract questions, dispute |
| CPA | (CPA number) | Tax questions, year-end |

(Fill in the actual numbers before printing.)

---

## Backup plans

| Problem | Fix |
|---|---|
| Facebook ad disapproved | Pause campaign, edit creative, resubmit. Don't escalate to FB support — wastes time. |
| MacBook battery dying mid-call | iPhone hotspot drains laptop fast — keep MagSafe handy. Otherwise, finish call on phone. |
| Lost iPhone signal | Use laptop on hotel/cafe wifi, log into Salesforce mobile via Lightning UI |
| Salesforce login error from new IP | Salesforce sometimes triggers IP-based MFA. Open SF on phone first to verify, then laptop |
| Cheaphomesfla scraper stops firing | Rare — usually means token expired. Re-run `launchctl start com.cheaphomes.dealmatcher` and re-auth Microsoft Graph if prompted |
| JB campaign hits SendGrid daily limit | Already on Essentials (50k/mo). If it ever hits the cap, login to SendGrid and check Account Details → Daily Sending Limit |
| Twilio number gets carrier-rejected | Switch outbound to backup number +1(786)648-8624 in `johnson_buys_sms_all_today.py` |

---

## Where everything lives

| Component | Location |
|---|---|
| Python code | `~/dealmatcher/` |
| Logs | `~/dealmatcher/logs/` (CHF scraper) and `~/Desktop/campaign_log_*.txt` + `sms_*.txt` (JB campaigns) |
| Data files | `~/dealmatcher/data/` |
| .env (secrets) | `~/dealmatcher/.env.cheaphomesfla` (NEVER commit / share) |
| launchd jobs | `~/Library/LaunchAgents/com.johnsonbuys.*.plist` and `com.cheaphomes.dealmatcher.plist` |
| Salesforce | https://johnsonshomes2.lightning.force.com |
| SendGrid | https://app.sendgrid.com (login: info@johnsonbuys.com) |
| Twilio | https://console.twilio.com |
| Cloudflare | https://dash.cloudflare.com |
| Swipe Pages | https://app.swipepages.com |
| Salesforce mobile app | iPhone → search "Salesforce" |

---

## When in doubt

Run morning_preflight. If it's all ✓, the system is healthy.
If something's ✗, the fix is usually `launchctl start <jobname>` + tail the log.

If actually broken, ask Claude — paste the preflight output + the error.
