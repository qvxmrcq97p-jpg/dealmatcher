# Salesforce Dashboards — Build Guide (10 dashboards, ~60 min total)

**Goal:** One Salesforce login = full visibility into every part of both businesses. After this is built, you open Salesforce → Home → and you immediately see what to do today, who's hot, what just broke, and how much money the month is on track for.

**Time:** ~60 minutes of pure clicking. Pace yourself — dashboards 1, 2, 4, 6, 9 are the highest leverage; build those first if you only have 30 minutes.

**Prereqs:** All 4 custom fields exist (Buyer_Score__c, Buyer_Target_Zips__c, Seller_Score__c, Top_Buyer_Zips__c — already done). Your user has Reports + Dashboards permission (already true — you're org owner).

---

## Build order (priority-ranked)

| # | Dashboard | Why it matters | Time |
|---|---|---|---|
| 1 | **Daily Lead Inflow** | Catch a PPL provider going dark within 24h | 8 min |
| 2 | **Active Pipeline by Status** | What needs work right now | 6 min |
| 4 | **Hot Buyers (CHF)** | Buyers to call TODAY | 5 min |
| 6 | **Today's Follow-ups** | Calls + texts due | 4 min |
| 9 | **Revenue This Month** | Are we hitting $100k? | 6 min |
| 3 | Lead Source Performance | Where to scale spend | 6 min |
| 5 | Daily Deal Activity | CHF scraper output | 5 min |
| 7 | Campaign Health (SMS + Email) | Are sends actually delivering? | 8 min |
| 8 | Conversion Funnel | Where leads die | 6 min |
| 10 | Buyer-Match Rate | Per-buyer deal flow | 6 min |

---

## How to read this guide

Each dashboard has 3 parts:
- **Reports** — the underlying data (build these first, save each one)
- **Dashboard** — drag those reports onto a dashboard page
- **Pin** — make it appear on your Home tab

Format: `App Launcher → Reports → New Report → [Object] → Continue`. When I say "filter X" I mean the filter pane on the right of the Report builder. "Group by Y" means the group-by row at the top.

---

## Dashboard 1 — Daily Lead Inflow

**Why:** If propertyleads.com or motivatedsellers.com goes dark on their side, your inflow drops to zero and no system alerts you. This dashboard makes the drop visible the moment you log in.

### Reports (4)

**Report 1A — Leads created today**
1. App Launcher → Reports → New Report → **Leads** → Continue
2. Filters: `Created Date = TODAY`
3. Group by: `Lead Source`
4. Show: row count
5. Save as: **"Leads — Today by Source"**, Folder: *Sales Reports*

**Report 1B — Leads created last 7 days**
1. New Report → Leads → Continue
2. Filters: `Created Date = LAST_N_DAYS:7`
3. Group by: `Created Date (Day)` then `Lead Source`
4. Add chart: **Stacked column**
5. Save as: **"Leads — Last 7 Days by Source"**

**Report 1C — Leads created this month**
1. New Report → Leads → Continue
2. Filters: `Created Date = THIS_MONTH`
3. Show: row count only (no grouping)
4. Save as: **"Leads — Month-to-date count"**

**Report 1D — Leads created last 30d (trend)**
1. New Report → Leads → Continue
2. Filters: `Created Date = LAST_N_DAYS:30`
3. Group by: `Created Date (Day)`
4. Add chart: **Line chart**
5. Save as: **"Leads — 30-day daily trend"**

### Dashboard
1. App Launcher → Dashboards → **New Dashboard**
2. Name: **"01 Daily Lead Inflow"**, Folder: *Personal Dashboards*
3. **+ Component** → pick "Leads — Today by Source" → **Donut chart**
4. **+ Component** → "Leads — Last 7 Days by Source" → **Stacked column**
5. **+ Component** → "Leads — Month-to-date count" → **Counter** (big number)
6. **+ Component** → "Leads — 30-day daily trend" → **Line chart**
7. Refresh frequency: **Daily** (auto)
8. Save → **Done** → click pin icon to add to Home

---

## Dashboard 2 — Active Pipeline by Status

**Why:** At a glance, see what stage every lead is in. Hot statuses (Sent Contract, Working, Hot) get attention first.

### Reports (3)

**Report 2A — All open leads by status**
1. New Report → Leads
2. Filters: `Status NOT EQUAL TO Closed Won, Dead, Take me off the list, Doesn't own anymore`
3. Group by: `Status`
4. Add chart: **Bar (horizontal)**
5. Save as: **"Open Leads by Status"**

**Report 2B — "Sent Contract" leads (rolling 30d)**
1. New Report → Leads
2. Filters: `Status = Sent Contract` AND `Last Modified Date = LAST_N_DAYS:30`
3. Show columns: Name, Phone, Property Address, Last Modified, Owner Asking Price, Offer Amount
4. Save as: **"Sent Contract — last 30d"**

**Report 2C — Stale "Working" leads (>14 days no activity)**
1. New Report → Leads
2. Filters: `Status = Working` AND `Last Activity Date < LAST_N_DAYS:14`
3. Save as: **"Stale Working Leads (14d+)"**

### Dashboard
1. New Dashboard → **"02 Active Pipeline by Status"**
2. Add Report 2A as bar chart, 2B as table (top 10), 2C as counter (big number with red threshold > 50)
3. Save → pin to Home

---

## Dashboard 3 — Lead Source Performance

**Why:** Tells you which paid channels are converting and which are wasting money. Every source has a CPL and a conversion rate; this dashboard surfaces both.

### Reports (3)

**Report 3A — Conversion rate by Lead Source**
1. New Report → Leads
2. Filters: `Created Date = LAST_N_DAYS:60`
3. Add column: `Status`
4. Group by: `Lead Source`
5. Summarize: **Count** of records, **Count** of records where Status = "Closed Won"
6. Add formula column: `(Closed Won count / Total count) * 100` → label "Conv %"
7. Save as: **"Lead Source — Conv % (60d)"**

**Report 3B — Lead Source volume (60d)**
1. New Report → Leads
2. Filters: `Created Date = LAST_N_DAYS:60`
3. Group by: `Lead Source`
4. Save as: **"Lead Source — Volume (60d)"**

**Report 3C — Sent Contract rate by Lead Source**
1. New Report → Leads
2. Filters: `Created Date = LAST_N_DAYS:60`
3. Add column: `Status`
4. Group by: `Lead Source`
5. Summarize: count where Status = "Sent Contract"
6. Save as: **"Lead Source — Sent Contract (60d)"**

### Dashboard
1. New Dashboard → **"03 Lead Source Performance"**
2. Add 3A as table (sorted by Conv % DESC), 3B as bar, 3C as bar
3. Save → pin to Home

---

## Dashboard 4 — Hot Buyers (CHF)

**Why:** Buyers with Buyer_Score__c ≥ 70 are people who BOUGHT recently in your zip range and have the email/phone to be reached. Your single highest-ROI list.

### Reports (4)

**Report 4A — Hot Buyers (Score 70+)**
1. New Report → **Contacts**
2. Filters: `Lead Source = CheapHomesFLA_LandingPage` AND `Buyer Score >= 70`
3. Show columns: Name, Email, Phone, Buyer Score, Buyer Target Zips, Top Buyer Zips, Buyer Max Budget, Last Activity Date
4. Sort by: Buyer Score DESC
5. Save as: **"CHF Hot Buyers (Score 70+)"**

**Report 4B — Warm Buyers (50-69)**
1. New Report → Contacts
2. Filters: `Lead Source = CheapHomesFLA_LandingPage` AND `Buyer Score >= 50` AND `Buyer Score < 70`
3. Same columns as 4A
4. Save as: **"CHF Warm Buyers (50-69)"**

**Report 4C — Buyers missing target zips**
1. New Report → Contacts
2. Filters: `Lead Source = CheapHomesFLA_LandingPage` AND `Buyer Target Zips = ""` (or null)
3. Save as: **"CHF Buyers Missing Zips"** *(call or email each, fill in their zips manually until automated)*

**Report 4D — Total CHF buyer count by tier**
1. New Report → Contacts
2. Filters: `Lead Source = CheapHomesFLA_LandingPage`
3. Add Bucket field: `Tier` based on Buyer_Score__c:
   - 70+ → "Hot"
   - 50-69 → "Warm"
   - 1-49 → "Cold"
   - 0 or empty → "Unscored"
4. Group by: Tier
5. Add chart: **Donut**
6. Save as: **"CHF Buyer Tier Mix"**

### Dashboard
1. New Dashboard → **"04 Hot Buyers (CHF)"**
2. 4A as table (top 20, sorted by score DESC) — your call list for today
3. 4B as table (top 20)
4. 4C as counter (red if > 5)
5. 4D as donut
6. Save → pin to Home

---

## Dashboard 5 — Daily Deal Activity (CHF scraper output)

**Why:** Tells you whether the scraper is actually finding deals and matching them to buyers. If "deals scraped today" drops to 0, the scraper might be broken before the watchdog catches it.

### Reports (3)

**Report 5A — CH-DEAL Tasks created today**
1. New Report → **Tasks**
2. Filters: `Subject CONTAINS 'CH-DEAL-'` AND `Created Date = TODAY`
3. Show: row count
4. Save as: **"CHF Deals — Today"**

**Report 5B — CH-DEAL Tasks last 14 days (trend)**
1. New Report → Tasks
2. Filters: `Subject CONTAINS 'CH-DEAL-'` AND `Created Date = LAST_N_DAYS:14`
3. Group by: `Created Date (Day)`
4. Add chart: **Line**
5. Save as: **"CHF Deals — 14-day trend"**

**Report 5C — Deals matched per buyer (last 7 days)**
1. New Report → Tasks
2. Filters: `Subject CONTAINS 'CH-DEAL-'` AND `Created Date = LAST_N_DAYS:7`
3. Group by: `Contact: Name` (the matched buyer)
4. Save as: **"CHF Deals matched per buyer (7d)"**

### Dashboard
1. New Dashboard → **"05 Daily Deal Activity"**
2. 5A as counter, 5B as line chart, 5C as bar chart
3. Save → pin to Home

---

## Dashboard 6 — Today's Follow-ups

**Why:** Every morning you want a single page showing every Task due today or overdue. No more digging.

### Reports (2)

**Report 6A — Tasks due today**
1. New Report → Tasks
2. Filters: `Activity Date = TODAY` AND `Status != Completed`
3. Show columns: Subject, Who (lead/contact name), Phone, Priority, Comments
4. Sort by: Priority DESC
5. Save as: **"Tasks Due Today"**

**Report 6B — Overdue Tasks**
1. New Report → Tasks
2. Filters: `Activity Date < TODAY` AND `Status != Completed`
3. Same columns as 6A + Activity Date
4. Sort by: Activity Date ASC (oldest first)
5. Save as: **"Tasks Overdue"**

### Dashboard
1. New Dashboard → **"06 Today's Follow-ups"**
2. 6A as table (full list), 6B as table (full list)
3. Save → pin to Home (top of stack — you check this first every morning)

---

## Dashboard 7 — SMS + Email Campaign Health

**Why:** Confirms your campaigns are sending and replies aren't piling up unnoticed. Catches Twilio/SendGrid problems quickly.

### Reports (5)

**Report 7A — JB email sends today**
1. New Report → Tasks
2. Filters: `Subject STARTS_WITH 'JB-Day'` AND `Created Date = TODAY`
3. Group by: Subject (= touch type: Day1/Day7/Day21/Day45)
4. Save as: **"JB Email Sends — Today by Touch"**

**Report 7B — JB SMS sends last 7d**
1. New Report → Tasks
2. Filters: `Subject STARTS_WITH 'JB-SMS-'` AND `Created Date = LAST_N_DAYS:7`
3. Group by: Created Date (Day)
4. Add chart: Column
5. Save as: **"JB SMS Sends — 7-day trend"**

**Report 7C — Inbound SMS replies last 7d**
1. New Report → Tasks
2. Filters: `Subject CONTAINS 'Inbound SMS'` AND `Created Date = LAST_N_DAYS:7`
3. Group by: Created Date (Day)
4. Save as: **"Inbound SMS Replies — 7-day trend"**

**Report 7D — Opt-outs last 30d**
1. New Report → Leads
2. Filters: `Status = Take me off the list` AND `Last Modified Date = LAST_N_DAYS:30`
3. Group by: Last Modified Date (Day)
4. Save as: **"Opt-outs — 30-day trend"**

**Report 7E — JB email sends last 30d (volume)**
1. New Report → Tasks
2. Filters: `Subject STARTS_WITH 'JB-Day'` AND `Created Date = LAST_N_DAYS:30`
3. Group by: Created Date (Day)
4. Save as: **"JB Email Volume — 30d"**

### Dashboard
1. New Dashboard → **"07 Campaign Health"**
2. 7A bar, 7B line, 7C line, 7D bar (red if upward trend), 7E line
3. Save → pin to Home

---

## Dashboard 8 — Conversion Funnel

**Why:** Where are leads dying? Lead → Working → Hot → Sent Contract → Closed Won. The funnel reveals the bottleneck.

### Reports (1 funnel report + 4 stage counts)

**Report 8A — Funnel report**
1. New Report → Leads
2. Filters: `Created Date = LAST_N_DAYS:60`
3. Group by: `Status`
4. Add Bucket: `Funnel_Stage`:
   - "New", "Property Leads PPL", "Motivated Sellers PPL" → "1. New"
   - "Working" → "2. Working"
   - "Hot" → "3. Hot"
   - "Sent Contract" → "4. Sent Contract"
   - "Closed Won" → "5. Closed Won"
5. Group by: Funnel_Stage
6. Add chart: **Funnel chart**
7. Save as: **"Conversion Funnel (60d)"**

### Dashboard
1. New Dashboard → **"08 Conversion Funnel"**
2. Funnel chart from 8A as the centerpiece
3. + smaller counters for each stage's count
4. Save → pin to Home

---

## Dashboard 9 — Revenue This Month

**Why:** Are we tracking to $100k net? This is the dashboard you check at 6 PM every day to know if you're winning.

### Reports (4)

**Report 9A — Closed Won this month**
1. New Report → Leads
2. Filters: `Status = Closed Won` AND `Last Modified Date = THIS_MONTH`
3. Show: Name, Property Address, Owner Asking Price, Offer Amount, Last Modified
4. Add formula column: `Spread = Offer Amount - Owner Asking Price` (or define your own)
5. Save as: **"Closed Deals — This Month"**

**Report 9B — Sent Contract → expected revenue**
1. New Report → Leads
2. Filters: `Status = Sent Contract` AND `Last Modified Date = LAST_N_DAYS:30`
3. Show: same columns + days_in_status (formula: TODAY() - LastModifiedDate)
4. Save as: **"Sent Contract — Pipeline"**

**Report 9C — Closed deals last 6 months (trend)**
1. New Report → Leads
2. Filters: `Status = Closed Won` AND `Last Modified Date = LAST_N_DAYS:180`
3. Group by: Last Modified Date (Calendar Month)
4. Add chart: Column
5. Save as: **"Closed Deals — 6-month trend"**

**Report 9D — Active offers count (sent contract not closed)**
1. New Report → Leads
2. Filters: `Status = Sent Contract`
3. Show: row count
4. Save as: **"Active Offers count"**

### Dashboard
1. New Dashboard → **"09 Revenue This Month"**
2. 9A as table (full)
3. Counter from 9A: Sum of Spread → label "Closed Spread MTD"
4. 9B as table
5. 9C as column chart
6. 9D as counter
7. Save → pin to Home

---

## Dashboard 10 — Buyer-Match Rate

**Why:** Tells you whether each CHF buyer is actually getting matched deals. A buyer with 0 matches over 30 days is either expecting too narrow a zip or doesn't fit your inventory — adjust their preferences or churn them.

### Reports (3)

**Report 10A — CH-DEAL matches per buyer (30d)**
1. New Report → Tasks
2. Filters: `Subject CONTAINS 'CH-DEAL-'` AND `Created Date = LAST_N_DAYS:30`
3. Group by: `Contact: Name`
4. Sort by count DESC
5. Save as: **"Deal Matches per Buyer (30d)"**

**Report 10B — Buyers with 0 matches in 30d**
1. New Report → Contacts
2. Filters: `Lead Source = CheapHomesFLA_LandingPage`
3. Add Cross Filter: `Contacts WITHOUT Tasks where Subject CONTAINS 'CH-DEAL-' AND Created Date = LAST_N_DAYS:30`
4. Save as: **"CHF Buyers — 0 matches in 30d"**

**Report 10C — Average matches per active buyer**
*(Calculated as 10A total ÷ active buyer count — derived in dashboard)*

### Dashboard
1. New Dashboard → **"10 Buyer-Match Rate"**
2. 10A as bar chart (top 20 buyers)
3. 10B as table — these are buyers who need attention (re-engage or remove)
4. Counter showing total matches in last 30d
5. Save → pin to Home

---

## After all 10 dashboards exist

**Pin them all to Home in priority order:**

1. App Launcher → **Home**
2. Click the gear icon (top right) → **Edit Page**
3. In the Components panel (left), drag **Dashboard** components onto the Home layout
4. For each, pick the dashboard from above
5. Order: 6 (today's followups) → 9 (revenue this month) → 4 (hot buyers) → 1 (lead inflow) → 2 (active pipeline) → 5 (deal activity) → 7 (campaign health) → 3 (lead source) → 8 (funnel) → 10 (buyer-match)
6. Save → Activate
7. **Set Home as default** in Setup → User Interface → check "Home is the default tab"

Now every login lands you on a single screen with everything that matters.

---

## Refresh schedule

In each dashboard's settings:
- Daily dashboards (1, 5, 6, 7): refresh **every 1 hour**
- Pipeline dashboards (2, 4, 9): refresh **every 4 hours**
- Trend dashboards (3, 8, 10): refresh **daily**

This keeps your CRM data fresh without hammering Salesforce limits.

---

## Maintenance — what to do when

### When a new lead source goes live (e.g., a new PPL provider)
- The new LeadSource value automatically appears in dashboards 1, 3, 8 (they group by source)
- No re-build needed

### When you add new buyers
- Buyer Score must be set (already automated by `tools/buyer_score.py`)
- They appear in dashboards 4 and 10 within 1 hour of next refresh

### When you change Lead.Status picklist values (e.g., add "Pending Inspection")
- Dashboards 2, 8 need the bucket fields updated to include the new value
- Edit the report → Bucket field → add new value → Save

---

## Troubleshooting

**"I don't see Buyer_Score__c when building the report"**
→ FLS issue. Run `python3 tools/add_sf_fields_v2.py` to grant FLS to your user. (Already done as of May 1.)

**"My funnel chart is empty"**
→ Bucket field not aligned with actual Status values in your org. Open the bucket field, click "Add Value", paste the exact Status string from a lead.

**"Can I filter Reports by my custom fields like Buyer_Target_Zips__c?"**
→ Yes — they appear in the Filter pane under "Custom Fields". If they don't, FLS is the issue (see above).

**"How do I share a dashboard with someone else (Bonny, Tony, etc.)?"**
→ Dashboard → Settings → Folder → move to a Shared folder; permission inherits.
