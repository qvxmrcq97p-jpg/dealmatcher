# Deploy: railway-deploy-alerts Cloudflare Worker

## What this does
When Railway deploy fails or crashes, you get an **SMS + email within ~60 seconds** so you can fix the bug before the broken deploy stays in production. Closes alert-map gap "h".

## One-time setup (~10 min, your action — only do this AFTER Railway is set up)

### 1. Deploy the worker

```bash
cd ~/dealmatcher/cloudflare/railway-deploy-alerts
wrangler deploy
```

Note the Worker URL: `https://railway-deploy-alerts.<subdomain>.workers.dev`

### 2. Create KV namespace

```bash
wrangler kv namespace create LAST_ALERT_AT
```

Paste the returned `id` into `wrangler.toml`, then `wrangler deploy` again.

### 3. Generate a shared secret

```bash
openssl rand -hex 16
# copy the output, e.g. abc123...
```

### 4. Set Wrangler secrets

```bash
wrangler secret put SHARED_SECRET     # paste the secret from step 3
wrangler secret put SENDGRID_API_KEY  # paste your SG key
wrangler secret put FROM_EMAIL        # paste info@johnsonbuys.com
wrangler secret put ALERT_TO          # paste info@johnsonbuys.com
wrangler secret put TWILIO_ACCOUNT_SID
wrangler secret put TWILIO_AUTH_TOKEN
wrangler secret put TWILIO_FROM       # paste +19549534554
wrangler secret put ALERT_SMS_TO      # paste your phone, e.g. +13055759040
```

### 5. Configure Railway to send the webhook

1. Open Railway → your `dealmatcher` project → **Settings**
2. Scroll to **Notifications** or **Webhooks**
3. Click **+ Add Webhook**
4. URL: `https://railway-deploy-alerts.<subdomain>.workers.dev/?secret=<the secret from step 3>`
5. Triggers — check ALL of:
   - Deploy Failed
   - Deploy Crashed
   - Service Removed (optional)
6. Save

### 6. Test

In Railway, manually trigger a redeploy of the `scraper` service (Deployments → latest → ⋯ → Redeploy). Wait for it to finish. Then to force a failure for the test, push an intentional syntax error and re-push to fix:

```bash
cd ~/dealmatcher
echo "this is bad python = no" >> cheaphomesfla_scraper.py
git add . && git commit -m "test: trigger railway alert" && git push
```

Within ~2 minutes you should:
- See an email at info@johnsonbuys.com titled `🚨 Railway deploy FAILED: scraper`
- See an SMS to your phone

Then fix it:

```bash
git revert HEAD
git push
```

Railway redeploys cleanly; no follow-up alert (success is silent by design).

## Notes

- Worker always returns 200 to Railway — never causes Railway to retry
- SUCCESS deploys produce a console log line only (no alert spam)
- KV stores last alert timestamp for /health visibility
- If SendGrid OR Twilio fails, the other still fires — alerting is OR'd, not AND'd
