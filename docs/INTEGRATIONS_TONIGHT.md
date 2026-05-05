# Integrations to wire tonight — CC + PropStream

Both built. Just needs API keys + deployments.

---

## 1. Constant Contact Events Webhook

### What it does
Every email open / click / unsubscribe / bounce in CC pushes to Salesforce as an Activity on the matching Contact. UTM tags from clicked URLs (county, deal_id, zip) get parsed and logged as structured fields.

After 7 days you can query SF: "show me Sarah's last 30 days of clicks" and see exactly which counties/deals she engaged with.

### Deploy steps (~10 min)

**1. Create KV namespace + deploy worker:**

```bash
cd ~/dealmatcher/cloudflare/cc-events-worker

# Create KV namespace
wrangler kv namespace create LAST_EVENT_AT_CC
# Output gives you an ID like: id = "abc123..."
# Paste that into wrangler.toml replacing REPLACE_AFTER_FIRST_DEPLOY

# Deploy
wrangler deploy
```

**2. Set secrets on the deployed worker:**

```bash
# Generate webhook secret (CC will send this in Authorization header)
SECRET=$(openssl rand -hex 16)
echo "WEBHOOK SECRET (save this): $SECRET"
echo "$SECRET" | wrangler secret put CC_WEBHOOK_SECRET

# Salesforce auth (re-use existing values)
grep ^SF_USERNAME= ../../.env.cheaphomesfla | cut -d= -f2 | wrangler secret put SF_USERNAME
grep ^SF_PASSWORD= ../../.env.cheaphomesfla | cut -d= -f2 | wrangler secret put SF_PASSWORD
grep ^SF_SECURITY_TOKEN= ../../.env.cheaphomesfla | cut -d= -f2 | wrangler secret put SF_SECURITY_TOKEN
```

**3. Verify worker is alive:**

```bash
curl https://cc-events-worker.cbfcalcio5.workers.dev/health | python3 -m json.tool
```

Expected: all bindings true.

**4. Configure CC to send webhooks here:**

In Constant Contact dashboard:
- **Settings** → **API Keys & Webhooks** (or **Integrations** → **Webhooks**)
- Click **Add Webhook**
- **URL:** `https://cc-events-worker.cbfcalcio5.workers.dev/?secret=<YOUR_SECRET_FROM_STEP_2>`
- **Events to send:**
  - ✓ Email Opened
  - ✓ Email Clicked
  - ✓ Email Bounced
  - ✓ Unsubscribed
  - ✓ Spam Complaint
- **Auth method:** Bearer Token (paste the secret) — OR — leave unauthenticated and rely on URL `?secret=`
- Save

**5. Test:**

In CC, send a test email to yourself. Click a link. Within 30s:

```bash
curl https://cc-events-worker.cbfcalcio5.workers.dev/health | python3 -m json.tool
```

`last_event_at` should populate. Then in Salesforce, find your Contact — should have a new Task: "🔗 Email Click: ..."

---

## 2. PropStream Property Enrichment

### What it does
For every scraped deal, calls PropStream API to verify bed/bath/sqft + add owner LLC + distress flags + photos. Cached forever per address.

### Setup steps (~5 min after sign-up)

**1. Sign up for PropStream Premium ($199/mo):**

- propstream.com → Sign Up
- Verify FL data quality matches your needs (use 7-day trial first)
- Upgrade to Premium tier (required for API access)
- Settings → API → Generate API Key
- Save your key

**2. Add to environment:**

```bash
# Edit ~/dealmatcher/.env.cheaphomesfla — add these two lines:
PROPSTREAM_USERNAME=info@cheaphomesfla.com  # or whatever email you signed up with
PROPSTREAM_API_KEY=<paste your API key>
```

**3. Test one address:**

```bash
cd ~/dealmatcher && python3 tools/propstream_enrich.py --address "14250 NW 5th Ave" --city "Miami" --state "FL"
```

Expected: JSON output with bed/bath/sqft/owner/distress flags.

**4. Bulk-enrich today's scraped deals (cached after first run):**

```bash
python3 tools/propstream_enrich.py --hours=24
```

First run takes ~5-10 min for ~250 unique addresses (rate-limited at 0.3s/call). Subsequent runs are instant for already-cached addresses.

**5. (Optional) Add Railway env vars** so cloud scripts can use PropStream:

Railway dashboard → service `dealmatcher` → Variables:
- `PROPSTREAM_USERNAME = <same as .env>`
- `PROPSTREAM_API_KEY = <same as .env>`

### What enriched data gets used for

After tonight's enrichment runs, this data flows into:

| Use | How |
|---|---|
| Daily CC email | Re-enable bed/bath/sqft display with VERIFIED data instead of wholesaler-typed |
| SF Lead/Contact | Update each scraped property's record with verified property data |
| Distress signals | Flag any deal where seller has tax delinquency, foreclosure, probate, etc. → high-priority |
| Buyer matching | Match deals to investors who bought similar properties recently |
| Article generation | Articles auto-cite real data from your stack ("Today's Miami-Dade picks have an avg equity of 67%") |

---

## 3. After both are live

- **Tomorrow morning's email** uses PropStream-enriched data (verified bed/bath/sqft + photos where available)
- **Every click + open** in tomorrow's email logs to SF Activity automatically
- **By Friday** you have 4 days of click data showing engagement patterns by county
- **Next week** I can write SF reports + dashboards that visualize the engagement heatmap

---

## Push to GitHub

After tonight's deployments work end-to-end:

```bash
cd ~/dealmatcher && git add -A && git commit -m "CC events worker + PropStream enrichment integration ready (keys pending)" && git push origin main
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| CC events worker /health shows `cc_secret: false` | SHARED_SECRET not set | Re-run step 2 |
| No SF Activities appearing | SF auth failing | Check worker logs in Cloudflare dashboard |
| PropStream returns 401 | API key wrong or plan not Premium | Verify in PropStream dashboard |
| PropStream returns 0 results | Address format mismatch | Try with full city + zip |
| Cache not saving | Permissions issue | `chmod 644 ~/dealmatcher/logs/propstream_cache.json` |
