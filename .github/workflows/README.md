# GitHub Actions — auto-deploy on push

## What's in here

- **deploy-cloudflare.yml** — On every push to `main` that touches `cloudflare/**`, automatically runs `wrangler deploy` for the changed Worker(s) only. Manual trigger via "Run workflow" button on GitHub Actions tab.

## One-time setup (5 min, your action — only after Phase 1 GitHub push is done)

The workflow needs a Cloudflare API token to deploy on your behalf. Create one with the minimum scope it needs.

### 1. Create the Cloudflare API token

1. Open https://dash.cloudflare.com/profile/api-tokens
2. Click **"Create Token"** → **"Edit Cloudflare Workers"** template (this is the right preset)
3. Account Resources: **Include — your account**
4. Zone Resources: **All zones** (or just `cbfcalcio5.workers.dev` if you prefer)
5. Click **Continue to Summary** → **Create Token**
6. **Copy the token** (you'll never see it again — paste somewhere safe for the next step)

### 2. Find your Cloudflare Account ID

1. Open https://dash.cloudflare.com
2. Right sidebar → **Account ID** → click to copy

### 3. Add both to GitHub Secrets

1. https://github.com/YOURUSER/dealmatcher/settings/secrets/actions
2. **New repository secret** → Name: `CLOUDFLARE_API_TOKEN`, Value: (token from step 1)
3. **New repository secret** → Name: `CLOUDFLARE_ACCOUNT_ID`, Value: (account ID from step 2)

### 4. Test it

Make a tiny change to any worker (e.g., add a comment to `cloudflare/propertyleads-worker/propertyleads_ppl_worker.js`):

```bash
cd ~/dealmatcher
echo "// auto-deploy test $(date)" >> cloudflare/propertyleads-worker/propertyleads_ppl_worker.js
git add . && git commit -m "test: trigger CF auto-deploy" && git push
```

Then watch:
- https://github.com/YOURUSER/dealmatcher/actions

A new workflow run should kick off within ~30 seconds. Click into it; expand "deploy propertyleads-worker"; you should see `wrangler deploy` output ending with the `https://propertyleads-ppl-worker.cbfcalcio5.workers.dev` URL.

If green: from now on, every push that changes a CF worker auto-deploys. No more manually running `wrangler deploy` from your Mac.

## Behavior

- **Only changed workers redeploy.** Pushing a Python edit doesn't re-deploy CF; pushing a CF edit doesn't re-trigger Railway (Railway has its own listener).
- **Failed deploys stop only that worker.** `fail-fast: false` means if `sendgrid-events` fails to deploy, `propertyleads` still deploys cleanly.
- **First push or manual trigger deploys all.** The detection logic falls back to "deploy everything" if it can't compute a diff (first commit ever, or you click the "Run workflow" button).
- **Wrangler secrets stay in Cloudflare.** This workflow only deploys code; the secret values you set with `wrangler secret put` are stored on Cloudflare's side and aren't touched by the deploy.

## Future workflows to add

- `deploy-railway.yml` — Railway already auto-deploys from GitHub natively (built-in), no workflow needed.
- `run-tests.yml` — pytest the Python code on every push, block merge if tests fail. Build later.
- `lint.yml` — ruff + black on Python, eslint on JS. Build later.
