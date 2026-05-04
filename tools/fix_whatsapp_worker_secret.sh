#!/usr/bin/env bash
# Fix the missing SHARED_SECRET on the cheaphomesfla-whatsapp-webhook Worker.
#
# Background: when the WA worker was deployed, it had a SHARED_SECRET set
# during desktop wrangler deploy. After the cloud migration that secret was
# never re-loaded, leaving the worker rejecting all incoming webhooks with
# 401. This script generates a fresh SHARED_SECRET, sets it on the worker,
# and prints what to paste into Green-API.

set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"

cd "$REPO/cloudflare/whatsapp-worker"

# Generate a new secret (or reuse existing if WA_SHARED_SECRET is in .env)
EXISTING=$(awk -F= '$1=="WA_SHARED_SECRET" { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE" 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    SECRET="$EXISTING"
    echo "→ Reusing WA_SHARED_SECRET from .env.cheaphomesfla"
else
    SECRET=$(openssl rand -hex 16)
    echo "→ Generated new SHARED_SECRET (also saving to .env.cheaphomesfla):"
    echo ""
    echo "  $SECRET"
    echo ""
    echo "" >> "$ENV_FILE"
    echo "# --- Green-API → WhatsApp worker (added $(date +%F)) ---" >> "$ENV_FILE"
    echo "WA_SHARED_SECRET=$SECRET" >> "$ENV_FILE"
fi

echo ""
echo "→ Setting SHARED_SECRET on worker via wrangler..."
echo "$SECRET" | wrangler secret put SHARED_SECRET 2>&1 | tail -3

echo ""
echo "→ Verifying via /health..."
sleep 3
curl -s https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health | python3 -m json.tool
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "Now update Green-API to send X-Webhook-Secret header:"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Webhook URL:    https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/"
echo "  Header name:    X-Webhook-Secret"
echo "  Header value:   $SECRET"
echo ""
echo "Steps in Green-API console (https://console.green-api.com):"
echo "  1. Pick your instance"
echo "  2. Settings → Webhooks"
echo "  3. Set URL to the webhook URL above"
echo "  4. Add custom header: X-Webhook-Secret = $SECRET"
echo "  5. Enable: 'Receive group messages', 'Receive message events'"
echo "  6. Save"
echo ""
echo "Test from Green-API console: there's usually a 'Send test webhook' button."
echo "Then re-check /health — last_message_at should populate within 60s."