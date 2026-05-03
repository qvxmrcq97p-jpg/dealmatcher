# Mobile Dev — Switching Machines Without Losing a Beat

Use this when picking up work on a different Mac (or a fresh setup).

---

## Why this is easy now

Everything runs in cloud. Local Macs are just **admin terminals** for editing code and running ad-hoc tools. The actual work (cron jobs, webhooks, email sending) happens on Railway + Cloudflare regardless of which Mac is awake.

That means:
- ✅ Both Macs see the same Railway logs, Cloudflare metrics, Salesforce data
- ✅ Both Macs can `git push` → triggers same auto-deploy
- ✅ Both Macs can run any script in `tools/`
- ❌ Don't run cron jobs locally on either Mac (Phase 6 disabled them)

---

## First-time setup on a new Mac (~10 min)

### 1. Run the bootstrap script

```bash
mkdir -p ~/dealmatcher && cd ~/dealmatcher
curl -O https://raw.githubusercontent.com/qvxmrcq97p-jpg/dealmatcher/main/tools/bootstrap_macbook.sh
bash bootstrap_macbook.sh
```

This installs Homebrew + git + python3 + node + gh + wrangler + twilio CLI, generates an SSH key, prompts you to add it to GitHub, then clones the repo.

### 2. Transfer credentials

The `.env.cheaphomesfla` file holds all API keys and is **not** in GitHub. From your primary Mac:

```bash
# Option A: AirDrop (simplest)
open -a AirDrop ~/dealmatcher/.env.cheaphomesfla

# Option B: scp over local network
scp christopherjohnson@<primary-mac>.local:~/dealmatcher/.env.cheaphomesfla ~/dealmatcher/

# Option C: 1Password / encrypted USB
```

### 3. Verify

```bash
cd ~/dealmatcher
bash tools/smoke_test_all.sh
```

If 30+ checks pass, you're ready.

### 4. Open Cowork

Cowork → select `~/dealmatcher` folder → first message:

> "Read STATE.md and continue."

Claude picks up exactly where the last session left off.

---

## Returning to a previously-set-up Mac

```bash
cd ~/dealmatcher
git pull --rebase
bash tools/smoke_test_all.sh   # optional sanity check
```

Open Cowork → `~/dealmatcher` → "Read STATE.md and continue."

---

## What stays in sync automatically

| Thing | Synced via | Notes |
|---|---|---|
| Code | git pull / push | Always pull at start of session |
| Deployed Workers | GitHub Actions | Push to main → auto-deploy |
| Salesforce data | SF cloud | Both Macs see same data |
| Railway logs/metrics | Railway dashboard | Open in browser |
| SendGrid stats | SendGrid dashboard | Open in browser |

## What doesn't sync automatically

| Thing | How to sync |
|---|---|
| `.env.cheaphomesfla` | Manual transfer (AirDrop / scp / 1Password) |
| Local backups in `~/Library/LaunchAgents.cutover-backup/` | Re-run Phase 6 if needed |
| Twilio CLI / wrangler login state | Run `twilio login` and `wrangler login` per machine |

---

## Working etiquette across machines

- **Always `git pull` first.** Otherwise you'll write code on stale state.
- **Always `git commit + push` before switching machines.** Otherwise the other Mac doesn't see your changes.
- **Update STATE.md** at the end of any session that meaningfully changes the stack.
- Long-running scripts that talk to an API: prefer running them on whichever Mac is plugged in and won't sleep.

---

## When traveling

The cloud doesn't sleep. From a hotel:
- Open Cowork on whichever Mac you have
- `git pull` to get whatever your past self pushed
- "Read STATE.md and continue."

If only an iPad / borrowed machine is available:
- claude.ai chat → ask Claude to make code changes via the GitHub web editor + commit. CI auto-deploys.
- Or use [github.dev](https://github.dev) — VS Code in a browser, can edit + commit.

---

## Recovery scenarios

### "My MBA SSH key isn't on the right GitHub account"
Run `cat ~/.ssh/id_ed25519.pub | pbcopy` and add it at https://github.com/settings/keys while logged in as `qvxmrcq97p-jpg`.

### "wrangler deploy fails"
`wrangler login` (one-time browser flow). Or — don't deploy locally — push to GitHub and let CI deploy.

### "I lost the .env file"
- Cloudflare secrets and Wrangler secrets persist on the Worker side (use `wrangler secret list` to see what's set).
- You'll need to re-fetch the originals from each provider's dashboard:
  - Twilio: Console → Account → API keys
  - SendGrid: Settings → API Keys (must regenerate if lost — old key still valid until you delete it)
  - Salesforce: User → Settings → My Personal Information → Reset My Security Token

---

## Reference: the cloud surfaces (open in browser)

| What | URL |
|---|---|
| GitHub repo | https://github.com/qvxmrcq97p-jpg/dealmatcher |
| Railway dashboard | https://railway.com/dashboard |
| Cloudflare dashboard | https://dash.cloudflare.com |
| Salesforce | https://johnsonshomes2.my.salesforce.com |
| SendGrid | https://app.sendgrid.com |
| Twilio Console | https://console.twilio.com |

Bookmark these on both Macs.
