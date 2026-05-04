# Scraper Subsystem Guide

> **For Claude (any session, any machine):** Read this when the user wants to work on the deal scraper, parser, or WhatsApp ingestion. After reading, ask "what do you want to fix or add?" — don't recap.

---

## What this subsystem does

Pulls fresh wholesaler deals from inbound channels (email + WhatsApp), parses them into structured records, matches each deal against CheapHomesFLA buyer criteria in Salesforce, and sends one personalized per-buyer email per run with the deals that match their buy-box.

Runs **3x/day on Railway** (10 AM / 2 PM / 6 PM ET) as service `dealmatcher` in project `luminous-spontaneity`.

---

## File map

```
~/dealmatcher/
├── cheaphomesfla_scraper.py     ← main entry point (was johnson_buys_deal_scraper.py v1)
├── parser.py                     ← pure parsing functions (no I/O — easy to unit test)
├── senders.txt                   ← wholesaler email addresses to accept (one per line)
├── tests/test_parser.py          ← parser unit tests — RUN BEFORE shipping parser changes
├── logs/scraper_stdout.log       ← latest stdout (also tail in Railway dashboard)
├── logs/scraper_stderr.log       ← latest stderr (errors land here)
└── cloudflare/whatsapp-worker/
    └── whatsapp_webhook_worker.js ← Green-API → SendGrid forwarder (re-emails WA into the inbox)
```

State files (still on Desktop — slated for migration):
- `~/Desktop/deal_scraper_log_YYYYMMDD.txt` — run logs (also `_latest.txt`)
- `~/Desktop/deal_scraper_state.json` — last-seen email IDs (dedup state)
- `~/Desktop/deal_scraper_ledger.json` — sent deal+buyer pairs (dedup against re-sends)
- `~/Desktop/deal_scraper_near_miss.json` — deals that almost matched a buyer

---

## Architecture (how a single run flows)

```
[Microsoft Graph API]                  [Salesforce]                  [SendGrid]
        │                                   │                             │
        │  pull new mail since last run     │                             │
        ▼                                   │                             │
  cheaphomesfla_scraper.py ─── filter senders.txt OR [WA-*] subjects      │
        │                                   │                             │
        │  for each new email body          │                             │
        ▼                                   │                             │
  parser.py ─── ParsedDeal records          │                             │
        │                                   │                             │
        │  pull buyers WHERE LeadSource =   │                             │
        │  'CheapHomesFLA_LandingPage'      │                             │
        │ ─────────────────────────────────►│                             │
        │  for each buyer                   │                             │
        │ ◄─────────────────────────────────│                             │
        │                                   │                             │
        │  match deals against buy-box                                    │
        │  (buyer.target_zips, beds, price band, etc.)                    │
        │                                   │                             │
        │  if match → render personalized email                           │
        │ ──────────────────────────────────────────────────────────────► │
        │                                   │                             │
        │  log a Task in SF (dedup ledger)  │                             │
        │ ─────────────────────────────────►│                             │
        ▼                                                                 │
  ledger.json + log txt                                                   ▼
                                                            buyer's inbox
```

WhatsApp lane:

```
WA group message
   → Green-API webhook (JSON POST to CF Worker)
   → cheaphomesfla-whatsapp-webhook Worker
       (auth via X-Webhook-Secret header)
   → SendGrid HTTP API
   → email lands in info@cheaphomesFLA.com inbox with subject [WA-Group:GroupName]
   → next scraper run picks it up like a regular email
   → parser.py uses WA-aware path (looks for [WA-*] subject prefix)
```

---

## Where the WhatsApp piece lives

The Worker file: `~/dealmatcher/cloudflare/whatsapp-worker/whatsapp_webhook_worker.js`

Deployed Worker URL: `https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/`
Health endpoint: `https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health`

To verify it's receiving WA messages, hit /health — `last_msg_at` should be within the last few hours during active hours.

---

## Common issues + how to fix

### "Microsoft Graph auth fails — AADSTS900144 / 'client_id' missing / tenant placeholder error"

This was the May 4, 2026 incident. Symptoms in Railway logs:
```
ERROR: FATAL: Device flow init failed: AADSTS900144: ... 'client_id'
```
or
```
Unable to get authority configuration for https://login.microsoftonline.com/<paste tenant id from step 6>
```

**Root cause:** `GRAPH_CLIENT_ID` and/or `GRAPH_TENANT_ID` env vars are unset OR contain a leftover placeholder string. Scraper's `os.getenv()` only reads OS environment, not `.env` files (without our auto-load patch).

**Fix:**
1. The scraper now auto-loads `.env.cheaphomesfla` at startup (and overrides env vars that look like placeholder strings, e.g. `<paste tenant id from step 6>`). If you've pulled latest code, this should "just work."
2. On Railway, ensure these 3 env vars are set in service `dealmatcher` → Variables:
   - `GRAPH_CLIENT_ID = b2143511-d5e1-49d9-a121-8df37116b895`
   - `GRAPH_TENANT_ID = 8dd6dc0e-8291-438e-b64f-57dbd2854c38`
   - `GRAPH_TOKEN_CACHE_B64 = (base64 of ~/Desktop/.graph_token_cache.bin)`
3. To regenerate the token cache (when refresh token expires ~90 days):
   ```bash
   python3 tools/refresh_graph_token.py
   ```
   It runs device flow locally, copies new base64 to clipboard, instruct Railway paste.
4. To clean leftover placeholder env vars in your shell: `unset GRAPH_TENANT_ID GRAPH_CLIENT_ID && grep -i "GRAPH_" ~/.zshrc`

**Prevention:** the safeguards module (`tools/scraper_safeguards.py`) now alerts via SMS+email within 60 sec of any fatal exception. Plus heartbeat tracking + token-expiry warnings 14 days before refresh token dies.

---

### "Parser is producing junk addresses"
The parser is conservative by design (rejects ambiguous matches). If a wholesaler's format isn't being parsed:
1. Save a sample of their email body to `tests/samples/<wholesaler>.txt`
2. Add a new test case to `tests/test_parser.py` showing what should be extracted
3. Run `python3 -m pytest tests/test_parser.py -v` — confirm it FAILS the way you expect
4. Adjust `parser.py` regex/cleanup until the test passes
5. Run ALL tests — make sure you didn't break anything else
6. Commit + push → Railway auto-deploys

### "A wholesaler's emails are being filtered out"
Check `senders.txt` — they need to be on that list (one address per line, lowercase). Add the address, commit, push.

### "Scraper hasn't run in over 4 hours"
1. Open Railway dashboard → project `luminous-spontaneity` → service `dealmatcher`
2. Check Deployments tab for failed builds
3. Check Logs tab for runtime errors
4. If healthy: probably the cron schedule. The cron is `0 */4 * * *` — fires every 4 hours
5. To trigger manually: Railway → service → click "Deploy" or use Railway CLI: `railway up`

### "Deals matching wrong buyers"
The buy-box logic lives in `cheaphomesfla_scraper.py`. Buyer fields used:
- `Buyer_Target_Zips__c` (semicolon-separated)
- `Min_Beds__c`, `Max_Beds__c`
- `Min_Price__c`, `Max_Price__c`
- `Investor_Type__c` (Flipper / Holder / Wholesaler / Fund)

If a buyer is getting wrong-zip deals, check their SF Contact record for stale `Buyer_Target_Zips__c`. Use `tools/audit_buyers.py` to see all buyers' criteria.

### "Re-sending the same deal to the same buyer"
The dedup ledger should prevent this. Check `~/Desktop/deal_scraper_ledger.json`:
```bash
grep "<deal_address>" ~/Desktop/deal_scraper_ledger.json
```
If the entry is missing, the SF Task that backs the ledger may have failed to create. Check SF for Task records on the buyer Contact with subject containing the deal address.

### "WhatsApp Worker /health shows last_msg_at is hours stale"
Either Green-API isn't forwarding or the SHARED_SECRET mismatched.
1. Test the Worker directly:
   ```bash
   curl -X POST https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/ \
     -H "X-Webhook-Secret: $SHARED_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"from":"test","body":"123 Test St for $200K","group":"TestGroup"}]}'
   ```
   Expected: HTTP 200, email lands in info@cheaphomesFLA.com inbox in <60s.
2. If 401: SHARED_SECRET in Worker doesn't match what Green-API is sending. Reset both.

---

## How to run the scraper manually for debugging

From your Mac (not Railway):

```bash
cd ~/dealmatcher
python3 cheaphomesfla_scraper.py --dry-run
```

Dry-run does everything except sending emails to buyers. Useful to verify parsing + matching without spamming people.

For a full real run (sends emails):
```bash
python3 cheaphomesfla_scraper.py
```

Watch the log file:
```bash
tail -f logs/scraper_stdout.log
```

---

## How to add a new wholesaler sender

1. Get their sending email (e.g. `deals@bigwholesaler.com`)
2. `echo "deals@bigwholesaler.com" >> ~/dealmatcher/senders.txt`
3. `git add senders.txt && git commit -m "Add bigwholesaler to senders" && git push`
4. Railway auto-deploys; next run picks them up

---

## How to test parser changes

```bash
cd ~/dealmatcher
python3 -m pytest tests/test_parser.py -v
```

If you're modifying parsing logic, ALWAYS:
1. Add a test case first (TDD-style) showing the desired behavior
2. Run tests (they fail)
3. Implement the fix
4. Run tests (they pass)
5. Run ALL tests (make sure nothing else broke)

Never push parser changes without `pytest tests/test_parser.py` going green.

---

## Salesforce schema relevant to scraper

| Object / Field | Purpose |
|---|---|
| Contact (where LeadSource = `CheapHomesFLA_LandingPage`) | Active buyers — scraper sends them emails |
| Contact.Buyer_Target_Zips__c | Semicolon-separated list of target zip codes |
| Contact.Min_Beds__c / Max_Beds__c | Buy-box bed range |
| Contact.Min_Price__c / Max_Price__c | Buy-box price range |
| Contact.Investor_Type__c | Flipper / Holder / Wholesaler / Fund |
| Contact.SMS_Opt_Out__c | If true, SMS campaign skips them (separate from email) |
| Task (subject pattern: "Deal: <address> → <buyer>") | Dedup ledger |
| Lead (where LeadSource = PropertyLeads / MotivatedSellers) | Motivated sellers — different pipeline |

---

## Future improvements (queued in TODO.md)

- [ ] Migrate state files from `~/Desktop/` into the repo (or to S3) so MBA can also see them
- [ ] Replace keyword-based parser with Claude/Haiku for nuanced extraction
- [ ] Add per-deal photos extraction (currently text-only) for richer email rendering
- [ ] Add scoring layer: prioritize sending hottest deals first when buyer matches multiple
- [ ] Add the Deal Q&A Agent (Cloudflare Worker) so buyer questions auto-route to wholesaler

---

## Quick commands

```bash
# Tail latest scraper log
tail -50 ~/dealmatcher/logs/scraper_stdout.log

# See last error
tail -50 ~/dealmatcher/logs/scraper_stderr.log

# Run unit tests
cd ~/dealmatcher && python3 -m pytest tests/test_parser.py -v

# Dry-run scraper locally
cd ~/dealmatcher && python3 cheaphomesfla_scraper.py --dry-run

# Deploy WhatsApp Worker
cd ~/dealmatcher/cloudflare/whatsapp-worker && wrangler deploy

# Check WhatsApp Worker health
curl https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health | python3 -m json.tool

# See all wholesaler senders
cat ~/dealmatcher/senders.txt

# Audit all buyer buy-boxes in SF
cd ~/dealmatcher && python3 tools/audit_buyers.py
```
