#!/usr/bin/env bash
# Deploy script for cc-events-worker.
# One-shot setup: KV namespace + worker deploy + secrets + verification.
#
# Run:
#   bash ~/dealmatcher/cloudflare/cc-events-worker/deploy.sh
#
# Prereqs:
#   - wrangler installed and logged into the right Cloudflare account
#     (the cbfcalcio5 account that owns the other workers)
#   - openssl available (standard on macOS)
#   - python3 available (standard on macOS)

set -e
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════"
echo "  cc-events-worker deploy"
echo "═══════════════════════════════════════════════════════"
echo ""

# 1. Create KV namespace (idempotent: if it already exists, wrangler will
#    say "already exists" and we'll extract the existing id)
echo "▶ Step 1: KV namespace LAST_EVENT_AT_CC"
KV_OUTPUT=$(wrangler kv namespace create LAST_EVENT_AT_CC 2>&1 || true)
echo "$KV_OUTPUT"
echo ""

# Try to extract the id from wrangler's output. Wrangler's output format
# changes between versions; try a few patterns.
KV_ID=$(echo "$KV_OUTPUT" \
    | grep -oE 'id\s*=\s*"[a-f0-9]+"' \
    | grep -oE '"[a-f0-9]+"' \
    | tr -d '"' \
    | head -1)
if [ -z "$KV_ID" ]; then
    # JSON-format fallback
    KV_ID=$(echo "$KV_OUTPUT" | python3 -c "
import sys, re
m = re.search(r'\"id\":\\s*\"([a-f0-9]+)\"', sys.stdin.read())
print(m.group(1)) if m else None
" 2>/dev/null || true)
fi
if [ -z "$KV_ID" ]; then
    # Last resort — ask the user to paste it
    echo ""
    echo "⚠  Could not auto-extract the KV namespace id from wrangler output."
    echo "   Look above for a line like   id = \"abc123def456...\""
    echo "   Paste just the id (no quotes):"
    read -r KV_ID
fi

if [ -z "$KV_ID" ]; then
    echo "✗ Still no KV ID. Aborting."
    exit 1
fi
echo "✓ KV namespace id: $KV_ID"
echo ""

# 2. Update wrangler.toml
echo "▶ Step 2: Update wrangler.toml with KV id"
if grep -q 'id\s*=\s*"REPLACE_AFTER_FIRST_DEPLOY"' wrangler.toml; then
    sed -i.bak "s|id\s*=\s*\"REPLACE_AFTER_FIRST_DEPLOY\"|id      = \"$KV_ID\"|" wrangler.toml
    rm -f wrangler.toml.bak
    echo "✓ wrangler.toml updated"
else
    # Already has an id — maybe a previous run. Update it anyway.
    sed -i.bak "s|^\(id\s*=\s*\"\)[^\"]*\(\".*\)|\1${KV_ID}\2|" wrangler.toml
    rm -f wrangler.toml.bak
    echo "✓ wrangler.toml id field overwritten with $KV_ID"
fi
echo ""

# 3. Deploy worker
echo "▶ Step 3: wrangler deploy"
wrangler deploy
echo ""

# 4. Set secrets
echo "▶ Step 4: Set secrets"
SECRET=$(openssl rand -hex 16)
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  📝 WEBHOOK SECRET (save this — needed in step 6):"
echo "      $SECRET"
echo "═══════════════════════════════════════════════════════"
echo ""

ENV_FILE="../../.env.cheaphomesfla"
if [ ! -f "$ENV_FILE" ]; then
    echo "✗ Cannot find $ENV_FILE — SF secrets won't be set."
    exit 1
fi

read_env() {
    grep "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed 's/^[ '"'"'"]//;s/[ '"'"'"]$//'
}

SF_USERNAME=$(read_env SF_USERNAME)
SF_PASSWORD=$(read_env SF_PASSWORD)
SF_SECURITY_TOKEN=$(read_env SF_SECURITY_TOKEN)

echo "$SECRET"            | wrangler secret put CC_WEBHOOK_SECRET
echo "$SF_USERNAME"       | wrangler secret put SF_USERNAME
echo "$SF_PASSWORD"       | wrangler secret put SF_PASSWORD
echo "$SF_SECURITY_TOKEN" | wrangler secret put SF_SECURITY_TOKEN

echo ""
echo "✓ All 4 secrets set"
echo ""

# 5. Verify
echo "▶ Step 5: Verify /health endpoint"
echo "   Waiting 5s for the deploy + secrets to propagate..."
sleep 5
HEALTH=$(curl -s https://cc-events-worker.cbfcalcio5.workers.dev/health)
echo "$HEALTH" | python3 -m json.tool

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  📋 NEXT (browser step): configure CC webhook"
echo ""
echo "  URL to paste into Constant Contact:"
echo "    https://cc-events-worker.cbfcalcio5.workers.dev/?secret=$SECRET"
echo ""
echo "  In Constant Contact dashboard:"
echo "    Settings → Integrations → Webhooks → Add Webhook"
echo "    Paste the URL above"
echo "    Events to subscribe to:"
echo "      ✓ Email Opened"
echo "      ✓ Email Clicked"
echo "      ✓ Email Bounced"
echo "      ✓ Unsubscribed"
echo "      ✓ Spam Complaint"
echo "    Save"
echo ""
echo "  Test: send yourself a test email from CC, click a link."
echo "  Within ~30s:"
echo "    curl https://cc-events-worker.cbfcalcio5.workers.dev/health"
echo "  → last_event_at should populate."
echo ""
echo "  Then in Salesforce, find the Contact for your test email →"
echo "  there should be a new Activity Task '🔗 Email Click: ...'"
echo "═══════════════════════════════════════════════════════"
