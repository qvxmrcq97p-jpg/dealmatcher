#!/usr/bin/env bash
# cf_deploy_all.sh — deploy all 5 Cloudflare Workers from the repo
#
# What it does, for each worker:
#   1. Creates the KV namespace (if not already created)
#   2. Patches wrangler.toml with the returned KV id
#   3. Runs `wrangler deploy`
#
# Run:
#   cd ~/dealmatcher && bash tools/cf_deploy_all.sh
#
# Prerequisites:
#   - wrangler installed (`npm install -g wrangler`)
#   - logged in (`wrangler login`)

set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

red()    { printf "\033[0;31m%s\033[0m\n" "$*"; }
green()  { printf "\033[0;32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[0;33m%s\033[0m\n" "$*"; }
section(){ echo; printf "\033[1;34m═══ %s ═══\033[0m\n" "$*"; }

# ── Sanity checks ────────────────────────────────────────────────────
if ! command -v wrangler &>/dev/null; then
    red "✗ wrangler not installed. Run: npm install -g wrangler"
    exit 1
fi
if ! wrangler whoami &>/dev/null; then
    yellow "⚠ wrangler not logged in. Running: wrangler login"
    wrangler login
fi

# ── Per-worker deploy ────────────────────────────────────────────────
# Each entry: dir|kv_binding_name
WORKERS=(
    "cloudflare/propertyleads-worker|LAST_LEAD_AT"
    "cloudflare/motivatedsellers-worker|LAST_LEAD_AT"
    "cloudflare/whatsapp-worker|LAST_MSG_AT"
    "cloudflare/sendgrid-events|LAST_EVENT_AT"
    "cloudflare/railway-deploy-alerts|LAST_ALERT_AT"
)

deploy_worker() {
    local dir="$1"
    local binding="$2"
    section "$dir  ($binding)"

    cd "$REPO/$dir"
    local toml="wrangler.toml"

    # Already configured? (no PASTE_KV_ID_HERE in toml)
    if grep -q "PASTE_KV_ID_HERE" "$toml"; then
        echo "→ creating KV namespace: $binding"
        local out
        out=$(wrangler kv namespace create "$binding" 2>&1)
        echo "$out"
        # Extract id like: id = "abc123def456"
        local kv_id
        kv_id=$(echo "$out" | grep -E '^[[:space:]]*id[[:space:]]*=' | head -1 | sed -E 's/.*id[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')
        if [ -z "$kv_id" ]; then
            red "  ✗ Could not parse KV namespace id from wrangler output."
            red "    Manually edit $dir/wrangler.toml and replace PASTE_KV_ID_HERE."
            return 1
        fi
        echo "→ patching wrangler.toml with id=$kv_id"
        # Mac sed needs '' after -i for in-place
        sed -i '' "s/PASTE_KV_ID_HERE/$kv_id/" "$toml"
        green "  ✓ KV namespace + toml updated"
    else
        echo "· KV namespace already configured (skipping create)"
    fi

    echo "→ deploying worker..."
    wrangler deploy
    green "  ✓ Deployed: $dir"

    cd "$REPO"
}

failed=()
for entry in "${WORKERS[@]}"; do
    IFS="|" read -r dir binding <<< "$entry"
    if ! deploy_worker "$dir" "$binding"; then
        failed+=("$dir")
    fi
done

echo
section "SUMMARY"
if [ ${#failed[@]} -eq 0 ]; then
    green "✓ All 5 Cloudflare Workers deployed."
    echo
    echo "Next: set Wrangler secrets for the 2 new workers"
    echo "  • cloudflare/sendgrid-events"
    echo "  • cloudflare/railway-deploy-alerts"
    echo "(see each DEPLOY.md for the secret list)"
else
    red "✗ ${#failed[@]} worker(s) failed:"
    for f in "${failed[@]}"; do echo "  - $f"; done
fi
