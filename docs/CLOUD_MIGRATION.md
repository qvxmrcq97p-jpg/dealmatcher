# Cloud Migration — End-to-End Runbook

> Goal: kill the Mac Mini's launchd dependency for the daily CHF magazine
> blast. Everything that currently runs locally moves to GitHub Actions
> (or Railway, your call). The Mini becomes a backup/dev machine, not
> production infrastructure.

## Operating model — read this first (added 2026-05-13)

The daily CHF pipeline now has **two** emails that go out, both magazine-
template, both growing in audience size as new investors set criteria:

| Email | Audience | Sender | How it's filtered |
|---|---|---|---|
| **Personalized SendGrid blast** | Every SF Contact with `LeadSource='CheapHomesFLA_LandingPage'` and criteria set | `info@johnsonbuys.com` (SendGrid subuser 70541431) | Each recipient sees only their selected counties; salutation is their first name |
| **Constant Contact broadcast** | The full CC list (~22K subscribers) | `info@cheaphomesfla.com` (Constant Contact) | Firehose; CTA is "set your buy-box to filter this" |

The personalized list is small today (~16–20 investors) but **grows every
day** as CC subscribers convert via the broadcast's hero CTA. The broadcast
list is the conversion pipeline for the personalized list. They are
complementary, not redundant. Both should fire every weekday from the
same cloud run.

### The May 13, 2026 incident — why this section exists

This is the failure mode we're locking out:

- 07:51 ET — GitHub Actions cloud workflow fired the personalized SendGrid
  blast. Edward Sellos (`selloscapitalmanagement@gmail.com`) received his
  Broward + Miami-Dade magazine, salutation "Hi Edward". Fine — this is
  the system working as designed.
- 08:25 ET — Mac Mini `morning_send_*.sh` independently ran the scraper +
  matched-buyer Field Reports (6 buyers got their deal-card emails). Also
  fine — but a totally separate channel with its own log path.
- 08:30 ET — Cowork scheduled task `cheaphomesfla-daily-blast-prep` ran,
  built the CC broadcast HTML/.eml/summary, and told Chris to paste it
  into CC and hit send.
- 09:30 ET — Chris noticed Eddie's 07:51 email and asked "did the blast
  already go out?". We almost double-sent to the criteria-set overlap.

Three jobs running in three places, no single source of truth on "who
got what today." The duplicate risk was real. The Cowork prep task was
operating on a stale assumption: that the broadcast was still gated on
a manual paste. The cloud already owns the personalized leg; the
broadcast is the only remaining manual piece.

### New target operational model

One scheduled cloud run per weekday morning. It does everything in
sequence and no other job touches the blast:

```
09:30 ET  →  scrape wholesaler inbox (cloud Microsoft Graph)
             │   Wholesalers typically finish their morning sends by
             │   ~9:15 ET. Moving scrape from 08:00 to 09:30 catches
             │   the full morning batch instead of missing the late ones.
             │
09:31 ET  →  matched-buyer Field Reports → SF buyers (existing scraper behavior)
09:33 ET  →  build broadcast HTML
09:34 ET  →  Constant Contact broadcast push (CC API — once OAuth wired, Step 6)
09:35 ET  →  personalized SendGrid blast → every CHF investor with criteria
09:38 ET  →  write run log + post #blast-summary alert
```

Single workflow, single log, single point of "did the blast run?" check.
No Mac launchd morning jobs (the Mac plist 10/14/18 schedule can keep
the afternoon/evening catch-up scrapes for late wholesaler drops, but
the **morning leg is cloud-only**). No Cowork prep task.

### Action items to get to that state (in priority order)

1. **Retire the Cowork prep task** (`cheaphomesfla-daily-blast-prep`).
   It builds artifacts that the cloud will fire automatically once Step 6
   is done — keeping it around is the exact failure that caused the
   May 13 near-double-send. Disable it in the scheduled-tasks list, or
   repurpose it to *verify* the cloud run landed (read GH Actions API,
   confirm both legs sent, alert if not).
2. **Move `daily-blast.yml` cron from 09:00 → 09:30 ET** so the scrape
   catches the full wholesaler morning batch. Change `cron: "0 13 * * 1-5"`
   to `cron: "30 13 * * 1-5"` and the DST companion to `"30 14 * * 1-5"`.
3. **Finish Step 6 below** (CC API OAuth) so the broadcast push is
   automated. Until this is done, the broadcast leg still requires a
   manual paste — and that's the leg most likely to be missed when the
   personalized side is silently succeeding.
4. **Wire alert webhook (Step 7)** so a failed run is loud, not silent.
   Currently a GH Actions failure shows up as a red dot on the Actions
   tab — fine for active monitoring, useless if Chris isn't looking.
5. **Disable the Mac Mini morning scrape** once the cloud is the source
   of truth (keep the 14:00 / 18:00 launchd entries for afternoon
   catch-up). Currently both fire and write to the same JSON, which is
   benign but adds confusion.

Each subsequent day, the personalized list will be larger (more CC
subscribers converted via yesterday's broadcast CTA) and the broadcast
list will be slightly smaller (those converts dropping off the firehose).
That's the intended flywheel and it only works if both legs fire reliably.

---

## Current state (the problem)

| Job | Where it runs today | Frequency |
|---|---|---|
| Wholesaler email scraper | Mac Mini launchd (`com.cheaphomes.dealmatcher.plist`) | 10/14/18 ET |
| Watchdog | Mac Mini launchd (`com.cheaphomes.watchdog.plist`) | 09:00 ET |
| Field Reports → 9 SF buyers | Same scraper job | 3x daily |
| CHF magazine broadcast (CC blast to 22K) | **Manual paste into CC composer** | 5x/week |
| Personalized SendGrid blast (per-investor) | **Manual `python3 send_personalized_blast.py --send`** | 5x/week |
| WhatsApp ingestion | Cloudflare Worker (`whatsapp-worker`) | 24/7 event-driven |
| Pipeline health monitor | GitHub Actions (`.github/workflows/pipeline-health-monitor.yml`) | Every hour |

If the Mac Mini sleeps, loses power, or unmounts the env file, the daily
pipeline silently breaks. We've felt that pain. Cloud-native fixes it.

## Target state (the goal)

| Job | New home | Why |
|---|---|---|
| Scraper + Field Reports + broadcast HTML build + personalized SendGrid blast | **GitHub Actions** (this repo) — `.github/workflows/daily-blast.yml` | Zero infrastructure to babysit, free for our run volume |
| CC broadcast push | Same workflow, once OAuth wired (Step 6 below) | Eliminates the manual paste |
| Watchdog | Same workflow's failure-summary step + the existing pipeline_health_monitor (already cloud) | Watchdog becomes "did the daily-blast job land green" |
| Mac Mini launchd plists | **Disabled** (kept on disk for fallback) | The Mini is no longer load-bearing |

## Migration plan — single tomorrow session, ~90 minutes

You'll be at both machines (MacBook Air + Mac Mini joined). I'll drive
each step from chat. Where you have to do something with your own login
that I can't do for you, the step is marked **(YOUR ACTION)**.

### Step 1 — Add GitHub repository secrets (15 min, YOUR ACTION + my guidance)

Go to: `https://github.com/<owner>/<repo>/settings/secrets/actions`

Add these secrets one at a time. **Names must match the workflow file
exactly** (`.github/workflows/daily-blast.yml` env block):

| Secret name | Value | Where to find it on the Mac |
|---|---|---|
| `SF_USERNAME` | info@johnsonbuys.com | `~/Desktop/.env.cheaphomesfla` line `SF_USERNAME=` |
| `SF_PASSWORD` | (Salesforce password) | same file, `SF_PASSWORD=` |
| `SF_SECURITY_TOKEN` | (SF security token) | same file, `SF_SECURITY_TOKEN=` |
| `SENDGRID_API_KEY` | `SG.xxxxx...` | same file, `SENDGRID_API_KEY=` |
| `GRAPH_CLIENT_ID` | (Azure AD app client ID) | same file, `GRAPH_CLIENT_ID=` |
| `GRAPH_TENANT_ID` | (Azure AD tenant ID) | same file, `GRAPH_TENANT_ID=` |
| `GRAPH_USER_EMAIL` | `info@cheaphomesfla.com` | same file, `GRAPH_USER_EMAIL=` |
| `GRAPH_TOKEN_CACHE_B64` | base64 of the token cache file | see Step 2 |

The token cache deserves its own step.

### Step 2 — Encode + upload the Microsoft Graph token cache (5 min)

The scraper authenticates to M365 using a token cache that was created
via interactive device-flow login on your Mac. We ship that file as a
secret and the cloud runner writes it back to disk before running.

On the Mac (terminal):

```bash
base64 -i ~/Desktop/.graph_token_cache.bin | pbcopy
```

That copies the base64 of the cache to your clipboard. Paste into the
`GRAPH_TOKEN_CACHE_B64` secret value field on GitHub.

⚠ **Token rotation:** the cache contains tokens that expire. The refresh
token works for ~90 days. When it stops working, the cloud runs will
fail; the fix is to re-cache locally and re-paste the secret. You'll see
this once a quarter at most. Step 6 below removes this dependency for
good.

### Step 3 — Smoke test the workflow (DRY RUN) (5 min)

GitHub → Actions tab → "Daily CHF Morning Blast" → **Run workflow**:
- `send_mode`: `dry`
- `skip_scrape`: `false`

Expected:
1. Scraper runs, pulls 0+ deals
2. Broadcast HTML builds
3. Personalized blast runs in dry mode (logs every recipient + their counties, no SendGrid sends)
4. CC step logs "manual_paste_required" (expected — Step 6 not done yet)
5. Workflow ends green
6. Artifact `morning-blast-<run-id>` uploaded with the rendered HTML + JSON logs

If anything's red: download the artifact, inspect `cloud_morning_run_*.json`
for the failed step, share with me, we fix together.

### Step 4 — Live test (one investor only) (5 min)

We don't want to fire to all CHF investors on the first live run.
Workaround: Add a temporary line to `send_personalized_blast.py` to
hardcode `--only=YOUR_TEST_EMAIL`, OR run the script locally first with:

```bash
python3 ~/dealmatcher/tools/send_personalized_blast.py \
    --only=cbfcalcio5@me.com --send
```

Confirm: you receive a personalized email with your selected counties
(if you've submitted criteria via cheaphomesfla.com), correct salutation,
correct from-address (`info@cheaphomesfla.com`), correct subject.

### Step 5 — Disable the Mac Mini launchd plists (5 min)

Once Step 4 passes, the Mini stops being authoritative:

```bash
launchctl bootout gui/$(id -u)/com.cheaphomes.dealmatcher 2>/dev/null
launchctl bootout gui/$(id -u)/com.cheaphomes.watchdog    2>/dev/null
# Move the plists out of LaunchAgents so they don't auto-load on reboot
mv ~/Library/LaunchAgents/com.cheaphomes.dealmatcher.plist \
   ~/Library/LaunchAgents/disabled.com.cheaphomes.dealmatcher.plist
mv ~/Library/LaunchAgents/com.cheaphomes.watchdog.plist \
   ~/Library/LaunchAgents/disabled.com.cheaphomes.watchdog.plist
```

Verify:
```bash
launchctl list | grep cheaphomes   # should print nothing
```

The `dealmatcher/plists/*.plist` files in the repo stay — they're our
fallback if cloud breaks and we need to bring the Mini back up fast.

### Step 6 — Wire Constant Contact API (30 min, YOUR ACTION + my code)

Until this step, the broadcast still requires manual paste. After this
step, the morning runner pushes the HTML straight into CC and schedules
the send via API.

What you do (one-time):
1. Go to https://app.constantcontact.com/account/api → "Create API Key"
2. Copy the API key + Secret. Save these somewhere secure.
3. We do an OAuth dance once to get an access + refresh token. I'll
   write a small `tools/cc_oauth_init.py` helper that walks you through
   it (5 minutes, browser-based).
4. Add `CC_ACCESS_TOKEN`, `CC_REFRESH_TOKEN`, `CC_API_KEY`, `CC_LIST_ID`
   as GitHub secrets.

The runner already has the conditional code — once those secrets exist,
Step 4 of the morning pipeline switches from "log manual_paste_required"
to "push to CC API and fire the send." No code change needed on our
side.

### Step 7 — Set up an alert webhook (5 min, optional but recommended)

So you don't have to check GitHub Actions every morning to know the
pipeline ran:

1. Slack: create a channel, add an Incoming Webhook integration, copy
   the webhook URL
2. OR Discord: same thing, channel → Edit → Integrations → Webhooks
3. Add as `ALERT_WEBHOOK_URL` GitHub secret
4. Every morning the workflow posts a one-liner: `📰 CHF morning blast —
   2026-05-12 · ✓ scraper · ✓ build_broadcast · ✓ personalized_blast
   (sent=27, failed=0)`

Failures auto-alert in the same channel.

### Step 8 — Move the Microsoft 365 auth to app-only (one-time, eliminates token rotation)

Optional but the right long-term answer. Removes the 90-day token
expiry headache.

1. Azure Portal → App registrations → your CHF Graph app → API
   permissions → Application permissions → grant `Mail.Read` (read all
   mailboxes) instead of Delegated.
2. Admin consent (M365 admin login required — that's you).
3. Update the scraper's auth flow to use client_credentials grant
   instead of device flow. I'll write the patch; takes ~30 lines of
   Python.
4. Replace `GRAPH_TOKEN_CACHE_B64` secret with `GRAPH_CLIENT_SECRET`.
5. Tokens auto-refresh forever. No more quarterly maintenance.

This is genuinely the last load-bearing manual step.

## Rollback plan

If something breaks in cloud and you need to ship today's blast:

```bash
# Re-enable the Mac Mini plist (Mini)
mv ~/Library/LaunchAgents/disabled.com.cheaphomes.dealmatcher.plist \
   ~/Library/LaunchAgents/com.cheaphomes.dealmatcher.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cheaphomes.dealmatcher.plist

# Manually fire the personalized track from MBA
python3 ~/dealmatcher/tools/send_personalized_blast.py --send

# Build and paste broadcast manually (existing playbook)
# See docs/DAILY_CC_BLAST.md
```

## What "done" looks like

- [ ] All secrets present in GitHub Actions
- [ ] Step 3 (dry-run smoke test) passes green
- [ ] Step 4 (live single-recipient test) passes
- [ ] Step 5 (disable Mac plists) executed, `launchctl list` clean
- [ ] First fully-cloud morning blast lands tomorrow at 9 AM ET
- [ ] Step 6 (CC API) wired so the manual paste step is gone
- [ ] Step 7 (alert webhook) firing
- [ ] Step 8 (app-only Graph auth) — ideally before next quarter

After Step 5 you can put the Mac Mini to sleep, take it on the road,
or unplug it entirely. The pipeline runs from Github's data centers.
