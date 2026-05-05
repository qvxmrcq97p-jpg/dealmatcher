# Runbook — paste-the-fix for every error you might hit

When something errors during the migration or daily ops, find the symptom below and paste the fix. If your error isn't here, paste it to me and I'll tell you the fix and add it to this doc.

> **For Claude (any session):** This is the FIRST thing to read when the user reports an error. Search this doc for the error text or symptom before diagnosing fresh. If the error isn't here, after fixing it, add a new entry so the next person finds it.

---

## Pipeline silent failures (May 5, 2026)

### Inbound SMS shows "unknown caller no SF lead match" but the person IS in SF
**Cause:** The Twilio Function `sms_v2.js` `sfFindLeadByPhone()` was using SOQL `LIKE '%${last10digits}%'` — only matched when the field contained the 10 digits CONSECUTIVELY with no separators. Salesforce stores phones with separators (`(786) 301-2767`, `786-301-2767`, `+1 786 301 2767`). All those contain the right 10 digits but with parens/dashes/spaces interrupting → no match.

**Fix:** changed query to match on LAST 4 DIGITS via SOQL LIKE, then post-filter in JS by normalizing each candidate's phone fields to digits-only and matching the full last 10.

**Apply if reverted:** the patched function is in `~/dealmatcher/twilio-functions/sms_v2.js`. Re-deploy with:
```bash
cd ~/dealmatcher && python3 tools/deploy_twilio_sms.py
```

**Verify after deploy:** in Twilio Functions logs, look for "SF Lead matched: 00Q..." on next inbound SMS that should match.

---

## Pipeline silent failures (May 4, 2026 — incidents we hit during go-live)

### `INVALID_LOGIN: Invalid username, password, security token; or user locked out` (Salesforce)
**Cause:** SF security token stale. SF auto-rotates the token whenever you reset your password OR sign in from a new IP. Token is stored in 5 places that all need updating.
**Fix:**
1. Get the current security token: SF → avatar → Settings → My Personal Information → Reset My Security Token (emails new token in 60s) — or copy the latest one if you already have it.
2. Run on your Mac:
   ```
   cd ~/dealmatcher && bash tools/update_sf_security_token.sh
   ```
   Paste new token when prompted. Script updates ALL 5 places SF auth lives:
   - `.env.cheaphomesfla`
   - Cloudflare Worker `propertyleads-ppl-worker`
   - Cloudflare Worker `motivatedsellers-ppl-worker`
   - Cloudflare Worker `sendgrid-events`
   - **Twilio Function `johnson-buys-sms` (handles cheaphomesFLA.com form fills via /buyer-webhook)**
3. Verify worker: send a test lead via curl (script prints the command at the end).
4. Test cheaphomesFLA.com form fill — should see "✓ Salesforce Contact created" in the notification email instead of "pending".

**If you only updated some places:** the symptom shows up as different things failing — Cloudflare workers OR Twilio Functions OR direct SF queries. Always run the update script so all 5 places get refreshed.

### `SendGrid error 401` from a Cloudflare Worker
**Cause:** Stale or missing `SENDGRID_API_KEY` in worker secrets.
**Fix (general):**
```
cd ~/dealmatcher/cloudflare/<worker-name>
echo "<SENDGRID_API_KEY>" | wrangler secret put SENDGRID_API_KEY
```
**Fix for WhatsApp worker specifically:**
```
cd ~/dealmatcher && bash tools/fix_whatsapp_worker_secrets.sh
```
This sets all 4 secrets (SG key, FROM_EMAIL, TO_EMAIL, SHARED_SECRET) at once.

### WhatsApp worker `last_message_at: null` despite Green-API being on
**Cause #1:** `SHARED_SECRET` not set on worker — every webhook gets 401.
**Cause #2:** Green-API webhook URL or token mismatch.
**Cause #3:** Phone disconnected from Green-API (WhatsApp Web session expired).
**Fix:**
1. Check `/health` bindings.shared_secret — if false, run `bash tools/fix_whatsapp_worker_secrets.sh`
2. Verify Green-API config:
   - webhookUrl: `https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/`
   - webhookUrlToken: value from `WA_SHARED_SECRET` in `.env`
   - notifications enabled: `incomingMessageReceived` AND `incomingMessageReceivedGroup`
3. Test directly with the curl command in `docs/SCRAPER_GUIDE.md` "Common issues" section.

### Scraper logs `FATAL: Device flow init failed: ... 'client_id'` (Microsoft Graph)
**Cause:** `GRAPH_CLIENT_ID` and/or `GRAPH_TENANT_ID` env vars missing or set to placeholder.
**Fix locally:** scraper now auto-loads `.env.cheaphomesfla` at startup — should self-correct after `git pull`.
**Fix on Railway:** add 3 env vars to service `dealmatcher` → Variables:
- `GRAPH_CLIENT_ID = b2143511-d5e1-49d9-a121-8df37116b895`
- `GRAPH_TENANT_ID = 8dd6dc0e-8291-438e-b64f-57dbd2854c38`
- `GRAPH_TOKEN_CACHE_B64` = paste contents of `~/Desktop/graph_token_cache_b64.txt`

### Scraper logs `Unable to get authority configuration ... <paste tenant id from step 6>`
**Cause:** Stale shell env var. Some prior session set `GRAPH_TENANT_ID` to a literal placeholder.
**Fix:**
```
unset GRAPH_TENANT_ID GRAPH_CLIENT_ID
grep -i "GRAPH_" ~/.zshrc ~/.zprofile ~/.bashrc ~/.bash_profile
```
If grep returns lines setting these to placeholders, edit those rc files and remove them. Restart Terminal.

### Refresh token expires (~85 days from last device flow)
**Symptom:** scraper safeguards SMS you "Graph refresh token is N days old".
**Fix:**
```
cd ~/dealmatcher && python3 tools/refresh_graph_token.py
```
Runs device flow on local Mac, copies new base64 to clipboard. Paste into Railway → service `dealmatcher` → Variables → `GRAPH_TOKEN_CACHE_B64`.

### Pipeline Health Monitor reports all workers as `HTTP Error 403: Forbidden`
**Cause:** Cloudflare bot detection blocking Python's default User-Agent.
**Fix:** the monitor sets a Mozilla UA. If you see this, `git pull` to grab the patched version.

### Test scrape says `bad-addr: 35` but parser samples look fine
**Cause:** test_scrape_recent.py was checking wrong field name (`address` vs `property_address`). Fixed in commit after May 4.
**Fix:** `git pull` on the affected machine.

---

## Phase 1 — GitHub push errors

### `Permission denied (publickey)` when pushing
**Cause:** GitHub doesn't have your SSH key.
**Fix:**
```
ssh-keygen -t ed25519 -C "cbfcalcio5@me.com"     # press Enter through prompts
pbcopy < ~/.ssh/id_ed25519.pub                    # copies public key
```
Then paste at https://github.com/settings/keys → New SSH key → Title "Mac mini 2026". Then retry the push.

### `fatal: remote origin already exists`
**Fix:**
```
git remote set-url origin git@github.com:cbfcalcio5/dealmatcher.git
git push -u origin main
```

### `! [rejected] main -> main (fetch first)`
**Cause:** You created the GitHub repo with a README/license and now there's history conflict.
**Fix:**
```
git pull origin main --allow-unrelated-histories
# resolve any conflicts, then:
git push -u origin main
```

### Pre-commit hook blocks your commit unexpectedly
**Cause:** A real or false-positive secret was detected.
**Fix:**
- If real secret: replace the literal value with `os.environ['VAR_NAME']`, add to `.env.cheaphomesfla` and Railway Shared Variables. Then `git add` and recommit.
- If false positive (rare): `git commit --no-verify` (only if you're 100% sure).

---

## Phase 2 — Railway errors

### Service stuck on "Building..." for >5 minutes
**Cause:** Usually a dependency install timeout or missing requirements.txt.
**Fix:** Click the service → Deployments → latest → Logs. Look for the failing pip install or python error. Often `pandas` or `lxml` need a build tool — Railway auto-installs them via Nixpacks but slow networks fail. Click "Restart" once.

### `ModuleNotFoundError: No module named 'X'` in Railway logs
**Fix:** Add the missing package to `requirements.txt` locally, commit, push. Railway re-installs on each deploy.
```
echo "missing-package==1.0.0" >> requirements.txt
git add requirements.txt && git commit -m "fix: add missing-package dep" && git push
```

### `KeyError: 'SF_PASSWORD'` in service logs
**Cause:** Railway env var not set on this service.
**Fix:** Project sidebar → **Shared Variables** → confirm SF_PASSWORD exists. If yes, click the service → Variables tab → confirm "Inherit shared variables" is ON. Restart the deploy.

### Cron service runs at the wrong hour
**Cause:** Railway crons are UTC. ET = UTC-4 (EDT, May-Oct) or UTC-5 (EST, Nov-Apr).
**Fix:** For 8 AM ET in May, use `0 12 * * *` (12 UTC). After November DST shift, change to `0 13 * * *`.

### Railway dashboard says "Deployment Failed" with no obvious cause
**Fix:** Open the failed deploy → Logs → scroll to the very TOP of the logs (not bottom). The first error is usually the real cause; subsequent errors are cascading.

---

## Phase 3 — Cloudflare wrangler errors

### `Authentication error [code: 10000]`
**Fix:**
```
wrangler logout
wrangler login              # opens browser
```

### `Could not find a wrangler.toml in the current directory`
**Cause:** You ran `wrangler deploy` from the repo root.
**Fix:** `cd` into the specific worker directory first:
```
cd ~/dealmatcher/cloudflare/propertyleads-worker
wrangler deploy
```

### `[code: 10026] Workers.dev subdomain has been disabled`
**Cause:** First-time setup needs you to claim a workers.dev subdomain.
**Fix:** Open https://dash.cloudflare.com → Workers & Pages → Subdomain → register `cbfcalcio5` (or whatever your subdomain).

### KV namespace binding error: `binding LAST_LEAD_AT not found`
**Cause:** `id` in wrangler.toml still says `PASTE_KV_ID_HERE`.
**Fix:**
```
wrangler kv namespace create LAST_LEAD_AT
# copy returned id (e.g., "abc123def...") into wrangler.toml replacing PASTE_KV_ID_HERE
wrangler deploy
```

### `wrangler secret put` says "Permission denied" or "401"
**Cause:** Wrong account selected.
**Fix:**
```
wrangler whoami           # see which account is active
# If wrong, log out and back in:
wrangler logout && wrangler login
```

### Deployed worker returns 500 on first POST
**Cause:** Usually a missing secret (script throws on `env.SF_PASSWORD` undefined).
**Fix:**
```
wrangler tail propertyleads-ppl-worker
```
In another terminal, send a test POST. The tail will show the exact error. Most common: missing `wrangler secret put` step. Re-run the secret commands from `cloudflare/<worker>/DEPLOY.md`.

---

## Phase 4 — Webhook configuration errors

### SendGrid Event Webhook "Test Your Integration" returns red ✗
**Cause:** Worker URL wrong, or SHARED_SECRET set on worker but missing in URL.
**Fix:**
1. Confirm worker URL responds to `curl https://sendgrid-events.cbfcalcio5.workers.dev/health` returning `"ok": true`
2. If you set `SHARED_SECRET`, the URL in SendGrid must include `?secret=YOUR_SECRET`
3. Toggle the webhook OFF then ON in SendGrid (sometimes the test caches a stale URL)

### Railway webhook never fires the alert worker on a failed deploy
**Cause:** Railway didn't actually mark the deploy as `FAILED` (it might be `BUILDING` and stuck, not failed).
**Fix:**
1. Verify in Railway → Deployments → the failed run shows `FAILED` status (not `BUILDING`)
2. If status is right, check `wrangler tail railway-deploy-alerts` → trigger another redeploy
3. Most common cause: SHARED_SECRET in Railway URL doesn't match the wrangler secret

### GitHub Action `deploy-cloudflare.yml` fails with `wrangler: command not found`
**Cause:** `npm install -g wrangler` didn't run before `wrangler deploy`.
**Fix:** The workflow already includes that step — re-run the failed action via "Re-run jobs" button. If it persists, check Node version (workflow uses Node 20).

### GitHub Action fails with `Error: not authenticated [code 10000]`
**Cause:** `CLOUDFLARE_API_TOKEN` secret missing or wrong.
**Fix:** Recreate the token at https://dash.cloudflare.com/profile/api-tokens with the **Edit Cloudflare Workers** template. Update GitHub Settings → Secrets → Actions → CLOUDFLARE_API_TOKEN.

---

## Phase 5 — Twilio /sms v2 errors

### Function deploy says "Service does not exist"
**Cause:** You're in the wrong Twilio account, or the `johnson-buys-sms` service wasn't created.
**Fix:** Log in at https://console.twilio.com — top-right confirm the right account. Functions and Assets → Services → confirm `johnson-buys-sms` exists.

### Inbound SMS arrives but Function returns 502
**Cause:** SF login failing inside the Function (curl can't reach SF, or env vars missing).
**Fix:** Twilio console → service → Logs → click the failed invocation. Most common: `SF_PASSWORD` env var missing on the Function service. Add it (gear icon → Environment variables).

### Auto-reply SMS not arriving on test
**Cause:** Twilio Function returned valid TwiML but the test phone number is the same as the From number, or A2P 10DLC blocked.
**Fix:** Test from a different phone (your iPhone, not the Twilio Console). If still no auto-reply, check Twilio → Insights → Errors for an A2P violation.

---

## Phase 6 — Mac cutover errors

### `launchctl bootout` says "No such process"
**Cause:** The plist was already unloaded (or never loaded).
**Fix:** Safe to ignore — the goal state is achieved.

### `launchctl bootstrap` says "Bootstrap failed: Resource busy"
**Cause:** That plist is already loaded.
**Fix:** First unload it:
```
launchctl bootout gui/$(id -u)/com.cheaphomes.dealmatcher
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cheaphomes.dealmatcher.plist
```

### After cutover, JB email didn't fire at 8 AM ET
**Cause:** Either Railway cron didn't run (timezone wrong) or env var missing.
**Fix:**
1. Railway → `jb_email` → Deployments → latest → Logs (scroll for SF login)
2. If "no logs": cron string wrong. For 8 AM ET use `0 12 * * 1-6` (UTC).
3. If logs show "auth failed": SF_PASSWORD or SF_SECURITY_TOKEN env var wrong in Railway.

---

## Salesforce errors (any phase)

### `INVALID_SESSION_ID` error in any script
**Cause:** SF security token rotated, or password changed.
**Fix:**
1. Reset token: SF → Setup → Personal Information → Reset Security Token (emails new one)
2. Update token in Railway Shared Variables AND in `.env.cheaphomesfla` locally
3. Re-trigger any failing service

### `INSUFFICIENT_ACCESS_OR_READONLY` on a custom field
**Cause:** FLS not granted to info@johnsonbuys.com user for that field.
**Fix:**
```
cd ~/dealmatcher && python3 tools/add_sf_fields_v2.py
```
This re-grants FLS via PermissionSet for all 4 custom fields.

### Reports show fewer leads than expected
**Cause:** Filter likely includes "IsConverted = false" — converted leads disappear from Lead reports.
**Fix:** Use a Lead+Contact joined report, or add `IsConverted = true OR false` to the filter explicitly.

---

## Cron skipped a day — what to do

If the daily KPI email or watchdog didn't email by 9:30 AM, here's the diagnosis order:

1. Check Railway → service → Deployments — was the cron supposed to fire? (UTC time match?)
2. If yes: click the failed run → Logs — find the actual error
3. If no logs at all: Railway cron string is wrong, or service is paused
4. Manual trigger: Railway → service → ▶ Trigger button — runs it on-demand

For JB email/SMS catchup the same day: trigger the service manually after fixing the bug. Day-1 sends are idempotent (SF Task tag prevents double-send to same lead), so no harm.

---

## Quick `curl` reference for sanity-checking after any change

```bash
# All 5 worker /health checks at once
bash ~/dealmatcher/tools/verify_workers.sh

# SF auth (proves credentials work)
curl -s -X POST "https://johnsonshomes2.my.salesforce.com/services/Soap/u/58.0" \
  -H "Content-Type: text/xml" -H "SOAPAction: login" \
  -d "<soapenv:Envelope xmlns:soapenv='http://schemas.xmlsoap.org/soap/envelope/' xmlns:urn='urn:partner.soap.sforce.com'><soapenv:Body><urn:login><urn:username>info@johnsonbuys.com</urn:username><urn:password>YOUR_PASS+YOUR_TOKEN</urn:password></urn:login></soapenv:Body></soapenv:Envelope>" \
  | grep sessionId

# Twilio account info (proves SID/auth)
curl -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID.json

# SendGrid stats (proves SG key)
curl -H "Authorization: Bearer $SENDGRID_API_KEY" \
  "https://api.sendgrid.com/v3/stats?start_date=$(date +%F)"
```

---

## Escalation

If you hit an error not covered here, paste the entire error message (with command that produced it) into Cowork and I'll respond with:
1. Root cause
2. Exact fix command
3. Prevention so it doesn't happen again
4. I add it to this runbook for future-you
