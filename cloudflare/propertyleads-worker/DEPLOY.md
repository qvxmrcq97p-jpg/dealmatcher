# Deploy: propertyleads-ppl-worker

Full deploy in ~10 min. Three phases: install wrangler → set secrets → deploy.

---

## Step 1 — Install wrangler if not already (1 min)

```bash
which wrangler || npm install -g wrangler
wrangler --version    # should print 3.x or 4.x
wrangler whoami       # confirms you're logged into the right Cloudflare account
```

If `wrangler whoami` says "not logged in":
```bash
wrangler login        # opens browser; sign in with the same Cloudflare account that has motivatedsellers-ppl-worker
```

---

## Step 2 — Set the secrets (5 min)

These are the same values you set for motivatedsellers-ppl-worker. Paste each `wrangler secret put <NAME>` and enter the value at the prompt.

```bash
cd ~/Desktop/propertyleads-worker

wrangler secret put SF_USERNAME           # info@johnsonbuys.com
wrangler secret put SF_PASSWORD           # your SF password
wrangler secret put SF_SECURITY_TOKEN     # your SF security token
wrangler secret put SF_LOGIN_DOMAIN       # login

wrangler secret put SENDGRID_API_KEY      # same key as motivatedsellers worker
wrangler secret put FROM_EMAIL            # info@johnsonbuys.com
wrangler secret put FROM_NAME             # Chris @ Johnson Buys
wrangler secret put ALERT_TO              # info@johnsonbuys.com

wrangler secret put TWILIO_ACCOUNT_SID    # ACa9378ff6...
wrangler secret put TWILIO_AUTH_TOKEN     # d29dfef85...
wrangler secret put TWILIO_FROM           # +19549534554
```

You can pull the exact values from the existing motivatedsellers-worker secrets if you forget them — they're the same.

---

## Step 3 — Deploy (1 min)

```bash
cd ~/Desktop/propertyleads-worker
wrangler deploy
```

Output will print the Worker URL — something like:
```
https://propertyleads-ppl-worker.<your-subdomain>.workers.dev
```

**Copy that URL.** That's what you give to propertyleads.com.

---

## Step 4 — Test before hooking up propertyleads.com (3 min)

Send a synthetic lead to your new worker:

```bash
WORKER_URL="<paste your worker URL here>"

curl -X POST "$WORKER_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "TEST",
    "last_name":  "PROPERTY_LEADS_TEST",
    "email":      "test+pl@cbfcalcio5.com",
    "phone":      "+13055551234",
    "address":    "123 Test St",
    "city":       "Miami",
    "state":      "FL",
    "zip":        "33125",
    "timeframe":  "ASAP",
    "estimated_value": "350000",
    "motivation": "TEST RUN — please delete"
  }'
```

Expected response:
```json
{"ok": true, "sf_lead_id": "00Q...", "sms_sent": true, "welcome_email_sent": true, ...}
```

Verify in Salesforce → Leads:
- Filter LeadSource = "Property Leads PPL"
- See the test lead at the top
- **Delete the test lead** after confirming

If `sf_lead_id` came back null, check `errors` in the response and fix whatever's wrong. Most common: a wrong secret. Re-run the failing `wrangler secret put` and re-test.

---

## Step 5 — Configure propertyleads.com (2 min)

Open: https://leads.propertyleads.com/res_partners/$AvhulvRQ/brpage.php?pageID=51 *(or whichever page in your propertyleads dashboard handles webhook setup)*

In their **Lead Delivery** settings:
- Method: **HTTP POST** (or Webhook)
- URL: `https://propertyleads-ppl-worker.<your-subdomain>.workers.dev`
- Format: JSON (or form-encoded — the Worker accepts either)
- Headers: leave empty unless they require something specific

Save.

If propertyleads.com lets you send a "test webhook," do that. Verify a fresh test lead appears in Salesforce.

---

## Step 6 — Mark the worker tested + active (1 min)

In Cloudflare dashboard:
- Workers & Pages → propertyleads-ppl-worker
- Add a tag or note: "Active — propertyleads.com configured 2026-05-01"

---

## Verification when real leads start flowing

First real propertyleads.com lead:

1. Worker should return HTTP 200 (you'll see it in propertyleads.com's delivery log)
2. SF should have the new Lead with `LeadSource = "Property Leads PPL"`
3. Lead's owner should get the welcome SMS within ~5 seconds
4. Lead's owner should get the welcome email within ~10 seconds
5. You should get a notification email at `info@johnsonbuys.com`

Watch the Cloudflare worker logs (Workers & Pages → propertyleads-ppl-worker → Logs) for the first hour to confirm everything's clean. Set `DEBUG=1` env var temporarily if you want to see the raw payload from propertyleads.com (helpful for confirming field-name mappings).

---

## Field-mapping adjustments

The Worker accepts a broad set of synonyms for common field names. If propertyleads.com uses a field name that's NOT in the synonym list, you'll see that field come through empty in Salesforce.

To debug: turn on DEBUG=1 with `wrangler secret put DEBUG` → `1`. The worker will log the raw payload. After 1-2 real leads, check the logs and confirm:

- Phone parses correctly
- Email parses
- Address fields parse
- Optional fields (timeframe, motivation, condition, notes) parse

If anything is missing, edit `propertyleads_ppl_worker.js` line ~155 (the `normalizeLead` function) to add the field name to the right `get(...)` call. Re-deploy with `wrangler deploy`. No downtime.

---

## Reporting in Salesforce

You can now slice ALL Leads by source:

- **Setup → Reports → Leads** → group by `LeadSource`
- You'll see "Motivated Sellers PPL" + "Property Leads PPL" as separate categories
- Compare per-provider metrics: lead volume, conversion rate, contract rate, deal size

This is the whole reason for separate workers. Provider ROI is now measurable.

---

## Rollback

If propertyleads.com becomes a low-quality source and you want to disable:

```bash
cd ~/Desktop/propertyleads-worker
wrangler delete
```

Or just remove the URL from propertyleads.com's webhook config (faster, less destructive). The worker stays live but no leads route to it.
