# Deploy: sendgrid-events Cloudflare Worker

## What this does
Receives every SendGrid email event (open, click, bounce, etc.) and:
- Creates a Task on the matching Lead/Contact in Salesforce
- Auto-creates a Contact for unknown openers (forwards / opt-in candidates)
- Auto-marks Leads as "Doesn't own anymore" on bounces
- Auto-marks Leads as "Take me off the list" on spamreport/unsubscribe

## One-time setup (~15 min, your action)

### 1. Deploy the Worker (3 min)

```bash
cd ~/dealmatcher/cloudflare/sendgrid-events
wrangler deploy
```

Note the URL it gives you: `https://sendgrid-events.<your-subdomain>.workers.dev`

### 2. Create the KV namespace (1 min)

```bash
wrangler kv namespace create LAST_EVENT_AT
```

It prints something like:
```
[[kv_namespaces]]
binding = "LAST_EVENT_AT"
id      = "abc123def456..."
```

Paste that `id` into `wrangler.toml` (replace `PASTE_KV_ID_HERE`), then:

```bash
wrangler deploy
```

### 3. Set Wrangler secrets (3 min)

```bash
wrangler secret put SF_USERNAME       # paste: info@johnsonbuys.com
wrangler secret put SF_PASSWORD       # paste your SF password
wrangler secret put SF_SECURITY_TOKEN # paste your SF security token
wrangler secret put SF_LOGIN_DOMAIN   # paste: login
```

(Optional) For URL-based auth if you want to harden:
```bash
wrangler secret put SHARED_SECRET     # paste any random string, e.g. openssl rand -hex 16
```

### 4. Configure SendGrid Event Webhook (5 min)

1. Login to https://app.sendgrid.com
2. Settings (left sidebar) → **Mail Settings** → **Event Webhook**
3. Set:
   - **HTTP Post URL:** the Worker URL from step 1, e.g. `https://sendgrid-events.cbfcalcio5.workers.dev/`
     - If you set `SHARED_SECRET`, append `?secret=<value>` to the URL
   - **Authorization Method:** None (or "OAuth 2.0" if you set up SendGrid OAuth)
   - **Test Your Integration** — click this button. If you see ✓, you're done.
   - **Events to send:** check
     - Delivered (optional — high volume)
     - Open
     - Click
     - Bounce
     - Spam Report
     - Unsubscribe
     - Group Unsubscribe
     - Dropped
4. Toggle the master switch to **ON** at the top
5. Save

### 5. Verify in Salesforce (2 min)

1. Open SF → any Lead you've recently emailed
2. Open the email (a fresh open ideally) from your phone or another device
3. Wait 30 seconds, refresh the Lead's Activity Timeline
4. You should see a new Task: `Email-Open — <subject>`

If no Task appears within 1 minute:
- Check Worker logs: `wrangler tail sendgrid-events`
- Check SendGrid Event Webhook page → "View Sample Body" → confirm payload is hitting the URL

## Operational notes

- Worker always returns 200 to SendGrid (per their docs they retry aggressively otherwise)
- If SF login fails, events are dropped (logged to console only) — daily reconciliation can catch missed events
- Task subjects start with `Email-` so dashboard 7 (Campaign Health) picks them up automatically
- Open events on a Lead that ISN'T in SF auto-create a Contact with `LeadSource = "Email Engagement (auto-created)"` — review these weekly to merge or delete
